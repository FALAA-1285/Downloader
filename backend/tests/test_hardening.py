"""Test untuk perbaikan hasil audit (AUDIT_REPORT.md) dan celah cakupan M-06."""

from __future__ import annotations

import asyncio
import gzip
import shutil
import socket
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, update

from app.adapters.registry import AdapterRegistry
from app.core.config import Settings
from app.core.errors import AppError, UnsafeURLError
from app.core.http_client import build_client, iter_body, read_limited
from app.core.url_guard import validate_url
from app.downloaders.file_validator import KINDS
from app.main import create_app
from app.models import Base
from app.models.db import make_engine
from app.models.models import DownloadHistory, DownloadJob, utcnow
from app.services import download_service
from app.services.cleanup import run_cleanup
from app.services.download_runner import _ffprobe_check, run_download
from tests.test_api import PNG, SITE, analyze, by_name, mock_site


@asynccontextmanager
async def running_app(settings: Settings):
    engine = make_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


async def create_job(client, web, name="ok.png", **body):
    mock_site(web)
    data = (await analyze(client)).json()
    item = by_name(data, name)
    res = await client.post("/api/v1/downloads", json={"analysis_id": data["id"], "media_ids": [item["id"]], **body})
    assert res.status_code == 201, res.text
    return res.json()[0]


# --- FR-02 / FR-10: registry ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("domain", "adapter"),
    [
        ("youtube.com", "youtube"),
        ("m.youtube.com", "youtube"),
        ("youtu.be", "youtube"),
        ("notyoutube.com", "generic"),
        ("youtube.com.evil.example", "generic"),
        ("www.instagram.com", "instagram"),
        ("x.com", "x"),
        ("example.org", "generic"),
    ],
)
def test_registry_resolves_by_domain(domain, adapter):
    assert AdapterRegistry().resolve(domain).id == adapter


def test_registry_disabled_status():
    registry = AdapterRegistry({"youtube"})
    assert registry.status_of(registry.resolve("youtube.com")) == "disabled"
    assert registry.status_of(registry.generic) == "active"


# --- Transisi status & antrean (M-03, L-07) -------------------------------------------------


async def test_status_transitions_are_recorded(app, client, web):
    job = await create_job(client, web)
    await app.state.queue.drain()
    async with app.state.sessions() as s:
        actions = (
            await s.scalars(
                select(DownloadHistory.action)
                .where(DownloadHistory.job_id == uuid.UUID(job["id"]))
                .order_by(DownloadHistory.created_at)
            )
        ).all()
    assert actions == ["created", "started", "completed"]


async def test_job_is_claimed_only_once(app, client, web):
    job = await create_job(client, web)
    await app.state.queue.drain()
    job_id = uuid.UUID(job["id"])
    async with app.state.sessions() as s:
        await s.execute(update(DownloadJob).where(DownloadJob.id == job_id).values(status="pending"))
        await s.commit()
    # Dua runner bersamaan: hanya satu yang boleh mengklaim job.
    await asyncio.gather(*(run_download(job_id, app.state.sessions, app.state.settings) for _ in range(2)))
    async with app.state.sessions() as s:
        started = (
            await s.scalars(
                select(DownloadHistory).where(DownloadHistory.job_id == job_id, DownloadHistory.action == "started")
            )
        ).all()
    assert len(started) == 2  # satu dari proses awal, satu dari salah satu runner kedua


async def test_pending_job_can_be_deleted_but_running_cannot(app, client, web, monkeypatch):
    async def never(_job_id):
        return None

    monkeypatch.setattr(app.state.queue, "enqueue", never)
    job = await create_job(client, web)
    assert (await client.delete(f"/api/v1/history/{job['id']}")).status_code == 204

    job = await create_job(client, web)
    async with app.state.sessions() as s:
        await s.execute(update(DownloadJob).where(DownloadJob.id == uuid.UUID(job["id"])).values(status="downloading"))
        await s.commit()
    assert (await client.delete(f"/api/v1/history/{job['id']}")).status_code == 409


async def test_enqueue_failure_marks_job_failed(app, client, web, monkeypatch):
    async def broken(_job_id):
        raise ConnectionError("redis down")

    monkeypatch.setattr(app.state.queue, "enqueue", broken)
    job = await create_job(client, web)
    assert job["status"] == "failed" and "Antrean" in job["error_message"]


async def test_cleanup_handles_stale_pending_and_stuck_jobs(app, client, web, monkeypatch):
    async def never(_job_id):
        return None

    monkeypatch.setattr(app.state.queue, "enqueue", never)
    pending = await create_job(client, web)
    stuck = await create_job(client, web)
    old = utcnow() - timedelta(days=1)
    async with app.state.sessions() as s:
        await s.execute(update(DownloadJob).where(DownloadJob.id == uuid.UUID(pending["id"])).values(updated_at=old))
        await s.execute(
            update(DownloadJob)
            .where(DownloadJob.id == uuid.UUID(stuck["id"]))
            .values(status="downloading", updated_at=old)
        )
        await s.commit()

    report = await run_cleanup(app.state.sessions, app.state.settings)
    assert report.stale_pending == 1 and report.stuck_jobs == 1
    for job_id in (pending["id"], stuck["id"]):
        assert (await client.get(f"/api/v1/downloads/{job_id}")).json()["status"] == "failed"


async def test_cleanup_sweeps_orphan_and_temp_files(app):
    settings = app.state.settings
    orphan = settings.downloads_dir / "orphan.png"
    stale_temp = settings.temp_dir / "old.part"
    for path in (orphan, stale_temp):
        path.write_bytes(b"x")
        old = path.stat().st_mtime - 10 * 3600
        import os

        os.utime(path, (old, old))
    report = await run_cleanup(app.state.sessions, settings)
    assert report.orphan_files == 1 and report.temp_files == 1
    assert not orphan.exists() and not stale_temp.exists()


# --- Path traversal & akses file (PRD §14.3) ------------------------------------------------


@pytest.mark.parametrize("key", ["../secret.txt", "..\\secret.txt", "sub/file.png", "/etc/passwd", "C:/Windows/win.ini"])
def test_storage_key_traversal_rejected(settings, key):
    with pytest.raises(AppError) as e:
        download_service.safe_storage_path(settings, key)
    assert e.value.code == "invalid_storage_key"


async def test_file_endpoint_only_serves_its_own_job(app, client, web):
    first = await create_job(client, web)
    second = await create_job(client, web, name="id.vtt")
    await app.state.queue.drain()
    a = await client.get(f"/api/v1/downloads/{first['id']}/file")
    b = await client.get(f"/api/v1/downloads/{second['id']}/file")
    assert a.content == PNG and b.content.startswith(b"WEBVTT") and a.content != b.content
    assert (await client.get(f"/api/v1/downloads/{uuid.uuid4()}/file")).status_code == 404


# --- M-02: URL pratinjau ---------------------------------------------------------------------


async def test_internal_preview_urls_are_dropped(client, web):
    page = b"""<html><head><meta property="og:image" content="http://192.168.1.1/admin.png"></head><body>
    <video src="/a.mp4" poster="http://10.0.0.1/cam.jpg"></video>
    <video src="/b.mp4" poster="/poster.jpg"></video></body></html>"""
    web.get("https://pv.example/").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "text/html"}, content=page)
    )
    for path in ("/a.mp4", "/b.mp4"):
        web.head(f"https://pv.example{path}").mock(return_value=httpx.Response(200, headers={"Content-Type": "video/mp4"}))
    data = (await analyze(client, url="https://pv.example/", media_types=["video"])).json()
    assert data["page"]["thumbnail"] is None
    previews = {m["filename"]: m["preview_url"] for m in data["media"]}
    assert previews["a.mp4"] is None
    assert previews["b.mp4"] == "https://pv.example/poster.jpg"


async def test_login_form_is_a_warning_not_an_error(client, web):
    page = b"""<html><body><form><input type="password"></form><img src="/x.png"></body></html>"""
    web.get("https://gallery.example/").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "text/html"}, content=page)
    )
    web.head("https://gallery.example/x.png").mock(return_value=httpx.Response(200, headers={"Content-Type": "image/png"}))
    res = await analyze(client, url="https://gallery.example/")
    assert res.status_code == 200
    assert any("form login" in w for w in res.json()["warnings"])


# --- L-02, I-04, M-04: proteksi API ----------------------------------------------------------


async def test_request_body_limit(client):
    big = {"url": "https://example.com/" + "a" * 100_000}
    assert (await client.post("/api/v1/analyze", json=big)).status_code == 413

    async def chunks():
        yield b'{"url": "https://example.com/'
        yield b"a" * 100_000
        yield b'"}'

    res = await client.post("/api/v1/analyze", content=chunks(), headers={"Content-Type": "application/json"})
    assert res.status_code == 413


async def test_mutations_require_client_header(app):
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 4000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as bare:
        res = await bare.post("/api/v1/analyze", json={"url": "https://example.com/"})
        assert res.status_code == 403 and res.json()["detail"]["code"] == "client_header_missing"
        assert (await bare.get("/api/v1/history")).status_code == 200


async def test_api_token(settings):
    async with running_app(settings.model_copy(update={"api_token": "rahasia"})) as application:
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 4000))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            assert (await c.get("/api/v1/history")).status_code == 401
            assert (await c.get("/api/v1/history", headers={"Authorization": "Bearer salah"})).status_code == 401
            assert (await c.get("/api/v1/history", headers={"Authorization": "Bearer rahasia"})).status_code == 200
            assert (await c.get("/api/v1/health")).status_code == 200  # healthcheck tetap publik


def test_default_client_networks_are_loopback_only():
    networks = [str(n) for n in Settings(_env_file=None).client_networks]
    assert networks == ["127.0.0.0/8", "::1/128"]


# --- L-03: dekompresi terbatas -------------------------------------------------------------


async def test_gzip_body_is_decoded_in_bounded_chunks():
    bomb = gzip.compress(b"\x00" * (20 * 1024 * 1024))  # ±20 KB terkompresi → 20 MB
    response = httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(bomb))
    sizes = [len(c) async for c in iter_body(response)]
    assert max(sizes) <= 64 * 1024 and sum(sizes) == 20 * 1024 * 1024

    response = httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(bomb))
    data, truncated = await read_limited(response, 1024 * 1024)
    assert truncated and len(data) == 1024 * 1024


async def test_unsupported_encoding_rejected():
    response = httpx.Response(200, headers={"Content-Encoding": "br"}, stream=httpx.ByteStream(b"xx"))
    with pytest.raises(AppError) as e:
        await read_limited(response, 1024)
    assert e.value.code == "unsupported_encoding"


@pytest.mark.parametrize("raw", ["http://0x7f.0.0.1/", "http://0177.0.0.1/", "http://127.1/", "http://0x7f000001.0/"])
def test_nonstandard_ipv4_forms_rejected(raw):
    with pytest.raises(UnsafeURLError):
        validate_url(raw, {80, 443})


async def test_resolver_tricks_blocked_at_connect(monkeypatch):
    """Lapis kedua: domain yang di-resolve ke 127.0.0.1 tetap diblokir saat koneksi."""

    async def resolve_like_inet_aton(self, h, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", resolve_like_inet_aton)
    async with build_client(Settings(_env_file=None)) as client:
        with pytest.raises(UnsafeURLError):
            await client.get("http://looks-public.example/")


# --- L-04: batas ukuran subtitle ------------------------------------------------------------


async def test_subtitle_size_cap(app, client, web):
    app.state.settings.max_download_size_mb = 10
    app.state.settings.max_subtitle_size_mb = 1
    mock_site(web)
    web.get(f"{SITE}/subs/id.vtt").mock(
        return_value=httpx.Response(200, content=b"WEBVTT\n\n" + b"x" * (2 * 1024 * 1024))
    )
    data = (await analyze(client)).json()
    sub = by_name(data, "id.vtt")
    jobs = (await client.post("/api/v1/downloads", json={"analysis_id": data["id"], "media_ids": [sub["id"]]})).json()
    await app.state.queue.drain()
    job = (await client.get(f"/api/v1/downloads/{jobs[0]['id']}")).json()
    assert job["status"] == "failed" and "batas 1 MB" in job["error_message"]


# --- I-07: token di URL tidak disimpan setelah selesai -----------------------------------------


async def test_query_tokens_redacted_from_history(app, client, web):
    web.get("https://cdn.example/foto.png?token=rahasia").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "image/png"}, content=PNG)
    )
    data = (await analyze(client, url="https://cdn.example/foto.png?token=rahasia")).json()
    jobs = (
        await client.post("/api/v1/downloads", json={"analysis_id": data["id"], "media_ids": [data["media"][0]["id"]]})
    ).json()
    await app.state.queue.drain()
    async with app.state.sessions() as s:
        job = await s.get(DownloadJob, uuid.UUID(jobs[0]["id"]))
        events = (await s.scalars(select(DownloadHistory).where(DownloadHistory.job_id == job.id))).all()
    assert job.status == "completed" and "rahasia" not in job.media_url
    assert all("rahasia" not in str(e.details) for e in events)


# --- M-01: ffprobe dengan whitelist ----------------------------------------------------------

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


@pytest.fixture
def sample_mp4(tmp_path: Path) -> Path:
    if not FFMPEG or not FFPROBE:
        pytest.skip("ffmpeg/ffprobe tidak terpasang")
    out = tmp_path / "sample.mp4"
    subprocess.run(  # noqa: S603 - argumen tetap, tanpa shell
        [FFMPEG, "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=32x32:rate=5", "-pix_fmt", "yuv420p", str(out)],
        check=True,
        timeout=60,
    )
    return out


async def test_ffprobe_accepts_real_media(sample_mp4, settings):
    await _ffprobe_check(sample_mp4, KINDS["mp4"], settings.model_copy(update={"ffprobe_path": FFPROBE}))


async def test_ffprobe_rejects_playlist_disguised_as_media(sample_mp4, tmp_path, settings):
    # ffprobe 9.x hanya mengenali HLS dari ekstensi .m3u8; whitelist tetap dipasang sebagai lapis kedua
    # untuk versi lain / file yang lolos deteksi. Ekstensi .m3u8 dipakai agar tanpa whitelist ffprobe
    # benar-benar membuka playlist.
    playlist = tmp_path / "evil.m3u8"
    playlist.write_text(
        f"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\n{sample_mp4.name}\n#EXT-X-ENDLIST\n", encoding="utf-8"
    )
    # Tanpa whitelist, ffprobe mau membuka playlist ini sebagai HLS dan mengikuti rujukannya.
    raw = subprocess.run(  # noqa: S603
        [FFPROBE, "-v", "error", "-show_entries", "format=format_name", "-of", "csv=p=0", str(playlist)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert raw.returncode == 0 and "hls" in raw.stdout
    with pytest.raises(AppError) as e:
        await _ffprobe_check(playlist, KINDS["mp3"], settings.model_copy(update={"ffprobe_path": FFPROBE}))
    assert e.value.code == "invalid_media"


# --- Jalur worker RQ -------------------------------------------------------------------------


async def test_rq_queue_enqueues_task_reference(settings, monkeypatch):
    calls = {}

    class FakeQueue:
        def __init__(self, name, connection):
            calls["name"] = name

        def enqueue_call(self, **kwargs):
            calls.update(kwargs)

    import rq

    monkeypatch.setattr(rq, "Queue", FakeQueue)
    from app.workers.queue import RQQueue

    queue = RQQueue(settings.model_copy(update={"queue_backend": "rq"}))
    job_id = uuid.uuid4()
    await queue.enqueue(job_id)
    assert calls["name"] == "downloads"
    assert calls["func"] == "app.workers.tasks.download_job"
    assert calls["args"] == (str(job_id),)
    assert calls["timeout"] > settings.download_timeout_seconds


async def test_rq_task_runs_download_in_own_event_loop(app, client, web, monkeypatch):
    async def never(_job_id):
        return None

    monkeypatch.setattr(app.state.queue, "enqueue", never)
    job = await create_job(client, web)

    import app.workers.tasks as tasks

    monkeypatch.setattr(tasks, "get_settings", lambda: app.state.settings)
    # Worker RQ memanggil fungsi sinkron yang membuat event loop dan engine sendiri.
    await asyncio.to_thread(tasks.download_job, job["id"])
    assert (await client.get(f"/api/v1/downloads/{job['id']}")).json()["status"] == "completed"
