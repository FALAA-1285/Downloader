"""Fitur ala IDM/1DM: unduhan multi-koneksi, batas kecepatan, dan antrean terjadwal."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import update

from app.main import run_scheduler_once
from app.models.models import DownloadJob
from app.services import download_runner
from app.services.download_runner import RateLimiter
from tests.test_api import SITE
from tests.test_audit_fixes import _suppress_enqueue
from tests.test_hardening import create_job

BIG_PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 2400  # ±600 KB, isi bervariasi


def ranged_server(body: bytes, calls: list, *, ranges: bool = True):
    def serve(request: httpx.Request) -> httpx.Response:
        rng = request.headers.get("range")
        calls.append(rng)
        if rng and ranges:
            start_s, end_s = rng.removeprefix("bytes=").split("-")
            start = int(start_s)
            end = int(end_s) if end_s else len(body) - 1
            return httpx.Response(
                206,
                headers={"Content-Type": "image/png", "Content-Range": f"bytes {start}-{end}/{len(body)}"},
                content=body[start : end + 1],
            )
        headers = {"Content-Type": "image/png", "Content-Length": str(len(body))}
        if ranges:
            headers["Accept-Ranges"] = "bytes"
        return httpx.Response(200, headers=headers, content=body)

    return serve


@pytest.fixture
def multi(settings, monkeypatch):
    monkeypatch.setattr(download_runner, "MIN_SEGMENT_BYTES", 100 * 1024)
    settings.multi_connection_min_mb = 0
    settings.download_connections = 4
    return settings


async def _rerun_with(app, client, web, job, serve):
    """Ganti server sumber lalu jalankan ulang job (create_job sudah menjalankannya sekali)."""
    await app.state.queue.drain()
    web.get(f"{SITE}/img/ok.png").mock(side_effect=serve)
    async with app.state.sessions() as s:
        await s.execute(update(DownloadJob).where(DownloadJob.id == uuid.UUID(job["id"])).values(status="failed"))
        await s.commit()
    await client.post(f"/api/v1/downloads/{job['id']}/retry")
    await app.state.queue.drain()


async def test_multi_connection_download_assembles_file(app, client, web, multi):
    calls: list = []
    job = await create_job(client, web)
    await _rerun_with(app, client, web, job, ranged_server(BIG_PNG, calls))

    done = (await client.get(f"/api/v1/downloads/{job['id']}")).json()
    assert done["status"] == "completed", done
    assert calls[0] is None  # permintaan pertama untuk mengetahui ukuran & dukungan Range
    assert len([c for c in calls if c]) == 4  # empat koneksi paralel
    assert (await client.get(f"/api/v1/downloads/{job['id']}/file")).content == BIG_PNG
    assert not list(multi.temp_dir.glob("*.segments.json"))


async def test_server_without_ranges_uses_single_connection(app, client, web, multi):
    calls: list = []
    job = await create_job(client, web)
    await _rerun_with(app, client, web, job, ranged_server(BIG_PNG, calls, ranges=False))
    assert calls == [None]
    assert (await client.get(f"/api/v1/downloads/{job['id']}/file")).content == BIG_PNG


async def test_segments_resume_from_sidecar(app, client, web, multi, monkeypatch):
    original = await _suppress_enqueue(app, monkeypatch)
    job = await create_job(client, web)
    job_id = uuid.UUID(job["id"])
    await client.post(f"/api/v1/downloads/{job['id']}/pause")

    # Simulasi jeda di tengah: sebagian tiap segmen sudah tertulis.
    total, half = len(BIG_PNG), len(BIG_PNG) // 2
    segs = [[0, half - 1, 1000], [half, total - 1, 2000]]
    data = bytearray(total)
    for start, _end, done in segs:
        data[start : start + done] = BIG_PNG[start : start + done]
    multi.temp_dir.mkdir(parents=True, exist_ok=True)
    (multi.temp_dir / f"{job_id.hex}.part").write_bytes(bytes(data))
    (multi.temp_dir / f"{job_id.hex}.segments.json").write_text(
        json.dumps({"url": f"{SITE}/img/ok.png", "total": total, "segments": segs})
    )

    calls: list = []
    web.get(f"{SITE}/img/ok.png").mock(side_effect=ranged_server(BIG_PNG, calls))
    monkeypatch.setattr(app.state.queue, "enqueue", original)
    await client.post(f"/api/v1/downloads/{job['id']}/resume")
    await app.state.queue.drain()

    assert (await client.get(f"/api/v1/downloads/{job['id']}")).json()["status"] == "completed"
    assert sorted(calls) == sorted([f"bytes=1000-{half - 1}", f"bytes={half + 2000}-{total - 1}"])
    assert (await client.get(f"/api/v1/downloads/{job['id']}/file")).content == BIG_PNG


async def test_rate_limiter_throttles():
    limiter = RateLimiter(200 * 1024)
    start = time.monotonic()
    for _ in range(8):
        await limiter.consume(64 * 1024)  # 512 KB pada 200 KB/s
    assert time.monotonic() - start >= 1.3


def test_time_budget_grows_with_speed_limit(settings):
    from app.services.download_runner import _time_budget

    assert _time_budget("video", settings, 0) == settings.download_timeout_seconds
    slow = _time_budget("video", settings, 16 * 1024)  # 1 MB pada 16 KB/s
    assert slow > settings.max_download_bytes / (16 * 1024)


async def test_speed_limit_is_stored_and_reported(app, client, web, monkeypatch):
    await _suppress_enqueue(app, monkeypatch)
    job = await create_job(client, web, max_speed_kbps=512)
    assert job["max_speed_kbps"] == 512
    bad = await client.post(
        "/api/v1/downloads", json={"analysis_id": str(uuid.uuid4()), "media_ids": ["x"], "max_speed_kbps": 1}
    )
    assert bad.status_code == 422


async def test_scheduled_download_waits_then_runs(app, client, web):
    later = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    job = await create_job(client, web, scheduled_at=later)
    assert job["status"] == "scheduled" and job["scheduled_at"]
    await app.state.queue.drain()
    assert await run_scheduler_once(app) == 0
    assert (await client.get(f"/api/v1/downloads/{job['id']}")).json()["status"] == "scheduled"

    # Waktunya tiba: penjadwal memasukkannya ke antrean.
    async with app.state.sessions() as s:
        await s.execute(
            update(DownloadJob)
            .where(DownloadJob.id == uuid.UUID(job["id"]))
            .values(scheduled_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert await run_scheduler_once(app) == 1
    await app.state.queue.drain()
    assert (await client.get(f"/api/v1/downloads/{job['id']}")).json()["status"] == "completed"


async def test_scheduled_job_can_start_now_or_be_cancelled(app, client, web):
    later = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    a = await create_job(client, web, scheduled_at=later)
    b = await create_job(client, web, scheduled_at=later)
    assert (await client.post(f"/api/v1/downloads/{a['id']}/resume")).json()["status"] == "pending"
    await app.state.queue.drain()
    assert (await client.get(f"/api/v1/downloads/{a['id']}")).json()["status"] == "completed"
    assert (await client.post(f"/api/v1/downloads/{b['id']}/cancel")).json()["status"] == "cancelled"
    # Waktu tanpa zona waktu ditolak agar jadwal tidak bergeser.
    naive = await client.post(
        "/api/v1/downloads",
        json={"analysis_id": str(uuid.uuid4()), "media_ids": ["x"], "scheduled_at": "2030-01-01T00:00"},
    )
    assert naive.status_code == 422
