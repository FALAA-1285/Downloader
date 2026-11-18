"""Test regresi untuk temuan audit (C-01 … L-05)."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, update

from app.core.config import Settings
from app.core.cookies import (
    cookie_header_for,
    parse_cookies,
    to_netscape,
    validate_custom_headers,
)
from app.core.errors import UnsafeURLError
from app.core.guard_proxy import GuardProxy
from app.models.models import Analysis, DownloadJob, utcnow
from app.services.cleanup import run_cleanup
from app.services.download_runner import JobInterrupted, _update
from tests.test_api import PNG, SITE, analyze, mock_site
from tests.test_hardening import create_job, running_app

NETSCAPE = (
    "# Netscape HTTP Cookie File\n"
    ".arsip.example\tTRUE\t/\tTRUE\t0\tsid\tsecret1\n"
    "#HttpOnly_.arsip.example\tTRUE\t/\tTRUE\t0\tauth\tsecret2\n"
    ".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tig\n"
)


# --- Cookie (C-03, H-01) ---------------------------------------------------------------------


def test_parse_netscape_keeps_httponly_and_domains():
    jar = parse_cookies(NETSCAPE, "https://arsip.example/x")
    assert {(c.name, c.domain, c.http_only) for c in jar} == {
        ("sid", "arsip.example", False),
        ("auth", "arsip.example", True),
        ("sessionid", "instagram.com", False),
    }
    assert cookie_header_for("https://arsip.example/a", jar) == "sid=secret1; auth=secret2"
    assert cookie_header_for("https://cdn.arsip.example/a", jar) == "sid=secret1; auth=secret2"
    assert cookie_header_for("https://evil.example/a", jar) is None
    # Cookie `secure` tidak dikirim lewat http.
    assert cookie_header_for("http://arsip.example/a", jar) is None


def test_parse_json_formats_and_header_are_host_scoped():
    arr = json.dumps([{"name": "a", "value": "1", "domain": ".site.example", "path": "/", "secure": True}])
    assert cookie_header_for("https://sub.site.example/", parse_cookies(arr, "https://site.example")) == "a=1"
    obj = parse_cookies('{"b": "2"}', "https://site.example/page")
    assert cookie_header_for("https://site.example/x", obj) == "b=2"
    assert cookie_header_for("https://sub.site.example/x", obj) is None  # host-only
    hdr = parse_cookies("c=3; d=4", "https://site.example/")
    assert cookie_header_for("https://other.example/", hdr) is None


def test_cookie_values_cannot_inject_headers():
    jar = parse_cookies("a=1\r\nX-Evil: 1", "https://site.example")
    assert cookie_header_for("https://site.example/", jar) == "a=1"
    bad_json = json.dumps([{"name": "b", "value": "2\r\nX-Evil: 1", "domain": "site.example"}])
    assert parse_cookies(bad_json, "https://site.example") == []


def test_netscape_roundtrip():
    jar = parse_cookies(NETSCAPE, "https://arsip.example")
    again = parse_cookies(to_netscape(jar), "https://arsip.example")
    assert {(c.name, c.domain, c.http_only) for c in again} == {(c.name, c.domain, c.http_only) for c in jar}


@pytest.mark.parametrize(
    "headers", [{"Host": "x"}, {"Transfer-Encoding": "chunked"}, {"Cookie": "a=1"}, {"X-A": "1\r\n"}]
)
def test_custom_headers_allowlist(headers):
    with pytest.raises(ValueError):
        validate_custom_headers(headers)
    assert validate_custom_headers({"Referer": "r", "X-Token": "t"}) == {"Referer": "r", "X-Token": "t"}


async def test_netscape_cookies_no_longer_break_analysis(client, web):
    """H-01: dulu teks multi-baris dikirim apa adanya sebagai header dan h11 menolaknya."""
    mock_site(web)
    res = await analyze(client, cookies=NETSCAPE)
    assert res.status_code == 200, res.text
    page_req = web.calls[0].request
    assert page_req.headers["cookie"] == "sid=secret1; auth=secret2"


async def test_cookies_not_sent_to_other_hosts_on_redirect(client, web):
    web.get(f"{SITE}/pindah").mock(return_value=httpx.Response(302, headers={"Location": "https://other.example/p"}))
    target = web.get("https://other.example/p").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"<html><p>x</p></html>")
    )
    res = await analyze(
        client, url=f"{SITE}/pindah", cookies="sid=rahasia", headers={"Authorization": "Bearer t", "Referer": "r"}
    )
    assert res.status_code == 200, res.text
    sent = target.calls.last.request.headers
    assert "cookie" not in sent and "authorization" not in sent
    assert sent["referer"] == "r"


async def test_cookies_are_not_persisted_in_analysis(app, client, web):
    mock_site(web)
    data = (await analyze(client, cookies="sid=rahasia")).json()
    async with app.state.sessions() as s:
        row = await s.get(Analysis, uuid.UUID(data["id"]))
    assert "rahasia" not in json.dumps(row.result)


async def test_cookies_wiped_from_job_after_completion(app, client, web):
    job = await create_job(client, web, cookies="sid=rahasia")
    await app.state.queue.drain()
    async with app.state.sessions() as s:
        row = await s.get(DownloadJob, uuid.UUID(job["id"]))
    assert row.status == "completed"
    assert not row.options or "cookies" not in row.options


async def test_invalid_custom_header_rejected(client):
    res = await client.post("/api/v1/analyze", json={"url": f"{SITE}/x", "headers": {"Host": "evil"}})
    assert res.status_code == 422


# --- Guard proxy (C-01, C-02) ----------------------------------------------------------------


@pytest.fixture
async def upstream():
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    yield server.sockets[0].getsockname()[1]
    server.close()


async def test_guard_proxy_forwards_public_and_blocks_internal(upstream, monkeypatch):
    settings = Settings(_env_file=None, allowed_ports=f"80,443,{upstream}")

    async def fake_resolve(host, port):
        if host == "public.example":
            return ["127.0.0.1"]  # anggap publik; server uji ada di loopback
        raise UnsafeURLError("diblokir")

    monkeypatch.setattr("app.core.guard_proxy.resolve_public", fake_resolve)
    proxy = GuardProxy(settings)
    await proxy.start()
    try:
        async with httpx.AsyncClient(proxy=proxy.url) as c:
            ok = await c.get(f"http://public.example:{upstream}/")
            assert ok.status_code == 200 and ok.text == "hello"
            blocked = await c.get(f"http://internal.example:{upstream}/")
            assert blocked.status_code == 403
            # Port di luar allowlist ditolak sebelum DNS.
            assert (await c.get("http://public.example:6379/")).status_code == 403

        reader, writer = await asyncio.open_connection("127.0.0.1", int(proxy.url.rsplit(":", 1)[1]))
        writer.write(b"CONNECT 169.254.169.254:443 HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        assert (await reader.readline()).startswith(b"HTTP/1.1 403")
        writer.close()
        assert proxy.blocked == 3
    finally:
        await proxy.close()


async def test_guard_proxy_uses_real_resolver_checks():
    """Domain yang di-resolve ke loopback (fixture conftest) ditolak oleh resolve_public sungguhan."""
    proxy = GuardProxy(Settings(_env_file=None))
    await proxy.start()
    try:
        async with httpx.AsyncClient(proxy=proxy.url) as c:
            assert (await c.get("http://internal-rebind.example/")).status_code == 403
            assert (await c.get("http://localhost/")).status_code == 403
    finally:
        await proxy.close()


# --- Jeda / lanjut / batal (H-06) ------------------------------------------------------------


async def _suppress_enqueue(app, monkeypatch):
    original = app.state.queue.enqueue

    async def never(_job_id):
        return None

    monkeypatch.setattr(app.state.queue, "enqueue", never)
    return original


async def test_pause_resume_continues_with_range(app, client, web, settings, monkeypatch):
    original = await _suppress_enqueue(app, monkeypatch)
    job = await create_job(client, web)
    assert (await client.post(f"/api/v1/downloads/{job['id']}/pause")).json()["status"] == "paused"

    # Separuh file sudah diterima sebelum dijeda.
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    (settings.temp_dir / f"{uuid.UUID(job['id']).hex}.part").write_bytes(PNG[:1000])
    seen_ranges: list[str | None] = []

    def serve(request):
        seen_ranges.append(request.headers.get("range"))
        return httpx.Response(
            206,
            headers={"Content-Type": "image/png", "Content-Range": f"bytes 1000-{len(PNG) - 1}/{len(PNG)}"},
            content=PNG[1000:],
        )

    web.get(f"{SITE}/img/ok.png").mock(side_effect=serve)
    monkeypatch.setattr(app.state.queue, "enqueue", original)
    resumed = await client.post(f"/api/v1/downloads/{job['id']}/resume")
    assert resumed.json()["status"] == "pending"
    await app.state.queue.drain()

    done = (await client.get(f"/api/v1/downloads/{job['id']}")).json()
    assert done["status"] == "completed", done
    assert seen_ranges == ["bytes=1000-"]
    assert (await client.get(f"/api/v1/downloads/{job['id']}/file")).content == PNG


async def test_cancel_paused_job_removes_partials(app, client, web, settings, monkeypatch):
    await _suppress_enqueue(app, monkeypatch)
    job = await create_job(client, web, cookies="sid=rahasia")
    await client.post(f"/api/v1/downloads/{job['id']}/pause")
    part = settings.temp_dir / f"{uuid.UUID(job['id']).hex}.part"
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x")
    cancelled = (await client.post(f"/api/v1/downloads/{job['id']}/cancel")).json()
    assert cancelled["status"] == "cancelled"
    assert not part.exists()
    async with app.state.sessions() as s:
        row = await s.get(DownloadJob, uuid.UUID(job["id"]))
    assert not row.options or "cookies" not in row.options
    # Job batal bisa dicoba lagi; job selesai tidak bisa dijeda.
    assert (await client.post(f"/api/v1/downloads/{job['id']}/retry")).status_code == 200
    assert (await client.post(f"/api/v1/downloads/{job['id']}/resume")).status_code == 409


async def test_running_job_stops_when_paused(app, client, web, monkeypatch):
    await _suppress_enqueue(app, monkeypatch)
    job = await create_job(client, web)
    job_id = uuid.UUID(job["id"])
    async with app.state.sessions() as s:
        await s.execute(update(DownloadJob).where(DownloadJob.id == job_id).values(status="downloading"))
        await s.commit()
    await client.post(f"/api/v1/downloads/{job['id']}/pause")
    with pytest.raises(JobInterrupted) as exc:
        await _update(app.state.sessions, job_id, size_downloaded=10)
    assert exc.value.status == "paused"


async def test_batch_status_endpoint(app, client, web, monkeypatch):
    await _suppress_enqueue(app, monkeypatch)
    a = await create_job(client, web)
    b = await create_job(client, web)
    res = await client.post("/api/v1/downloads/status", json={"ids": [a["id"], b["id"], str(uuid.uuid4())]})
    assert res.status_code == 200
    assert {j["id"] for j in res.json()} == {a["id"], b["id"]}


# --- Cleanup & retensi (H-02) ----------------------------------------------------------------


async def test_cleanup_retention_rules(app, client, web, settings, monkeypatch):
    await _suppress_enqueue(app, monkeypatch)
    paused = await create_job(client, web, cookies="sid=1")
    failed = await create_job(client, web, cookies="sid=2")
    old = await create_job(client, web)
    long_ago = utcnow() - timedelta(days=settings.history_retention_days + 1)
    async with app.state.sessions() as s:
        await s.execute(
            update(DownloadJob)
            .where(DownloadJob.id == uuid.UUID(paused["id"]))
            .values(status="paused", updated_at=utcnow() - timedelta(hours=settings.file_retention_hours + 1))
        )
        await s.execute(
            update(DownloadJob)
            .where(DownloadJob.id == uuid.UUID(failed["id"]))
            .values(status="failed", updated_at=utcnow() - timedelta(hours=settings.analysis_retention_hours + 1))
        )
        await s.execute(
            update(DownloadJob)
            .where(DownloadJob.id == uuid.UUID(old["id"]))
            .values(status="completed", updated_at=long_ago)
        )
        await s.commit()

    report = await run_cleanup(app.state.sessions, settings)
    assert report.paused_expired == 1 and report.old_jobs == 1 and report.secrets_wiped >= 1
    async with app.state.sessions() as s:
        rows = {str(j.id): j for j in (await s.scalars(select(DownloadJob))).all()}
    assert rows[paused["id"]].status == "cancelled"
    assert not rows[failed["id"]].options or "cookies" not in rows[failed["id"]].options
    assert old["id"] not in rows


async def test_cleanup_keeps_partials_of_paused_jobs(app, client, web, settings, monkeypatch):
    await _suppress_enqueue(app, monkeypatch)
    job = await create_job(client, web)
    await client.post(f"/api/v1/downloads/{job['id']}/pause")
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    keep = settings.temp_dir / f"{uuid.UUID(job['id']).hex}.part"
    stale = settings.temp_dir / f"{uuid.uuid4().hex}.part"
    for p in (keep, stale):
        p.write_bytes(b"x")
        old = time.time() - 10 * 24 * 3600
        import os

        os.utime(p, (old, old))
    await run_cleanup(app.state.sessions, settings)
    assert keep.exists() and not stale.exists()


# --- Lain-lain -------------------------------------------------------------------------------


async def test_disabled_platform_adapter_is_enforced(settings):
    """M-07: dulu hanya `generic` yang benar-benar bisa dinonaktifkan."""
    settings = settings.model_copy(update={"disabled_adapters": "youtube"})
    async with running_app(settings) as application:
        transport = httpx.ASGITransport(app=application, client=("127.0.0.1", 1))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver", headers={"X-UMD-Client": "t"}
        ) as c:
            res = await c.post("/api/v1/analyze", json={"url": "https://www.youtube.com/watch?v=abcdefghijk"})
    assert res.status_code == 503 and res.json()["detail"]["code"] == "adapter_disabled"


async def test_client_without_ip_is_rejected(app):
    """L-05: klien tanpa alamat IP yang jelas tidak lagi lolos penjaga jaringan."""
    transport = httpx.ASGITransport(app=app, client=("unix-socket", 0))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        assert (await c.get("/api/v1/history")).status_code == 403


async def test_zip_size_cap(app, client, web, settings):
    job = await create_job(client, web)
    await app.state.queue.drain()
    app.state.settings.max_zip_size_mb = 0
    try:
        res = await client.post("/api/v1/downloads/zip", json={"job_ids": [job["id"]]})
    finally:
        app.state.settings.max_zip_size_mb = 4096
    assert res.status_code == 413


def test_iframe_ads_are_not_video_candidates():
    """M-03: iframe yang URL-nya kebetulan memuat 'video'/'player' bukan media yang bisa diunduh."""
    from bs4 import BeautifulSoup

    from app.extractors.media import extract_av

    html = """<html><body>
    <iframe src="https://ads.example.net/video/player?slot=1"></iframe>
    <iframe src="https://widgets.example.com/embed/stream"></iframe>
    <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>
    </body></html>"""
    items, _ = extract_av(BeautifulSoup(html, "html.parser"), "https://site.example/")
    assert [i.url for i in items] == ["https://www.youtube.com/embed/dQw4w9WgXcQ"]


def test_doh_cache_is_bounded(monkeypatch):
    from app.core import url_guard

    monkeypatch.setattr(url_guard, "_DOH_CACHE_MAX", 3)
    url_guard._DOH_CACHE.clear()
    for i in range(10):
        url_guard._cache_put(f"h{i}.example", ["93.184.216.34"])
    assert len(url_guard._DOH_CACHE) == 3
    url_guard._DOH_CACHE.clear()
