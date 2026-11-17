"""Integration test alur API (PRD §14.2, §14.4) dengan SQLite dan HTTP sumber yang di-mock."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, update

from app.models.models import DownloadFile, DownloadHistory, utcnow

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000
VTT = b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHalo\n"

PAGE = b"""<!doctype html><html><head><title>Arsip Kota</title>
<meta name="description" content="Halaman uji."></head><body><article>
<h1>Arsip Kota</h1>
<p>Pameran arsip kota dibuka hari ini dengan ratusan dokumen dan foto bersejarah yang belum pernah dipamerkan sebelumnya.</p>
<p>Pengunjung dapat melihat peta lama, surat kabar, dan rekaman suara dari berbagai dekade di gedung utama museum kota.</p>
<img src="/img/ok.png" alt="ok">
<img src="/img/missing.jpg">
<img src="/img/fake.png">
<img src="/img/big.png">
<video src="/media/klip.mp4"></video>
<video><source src="/media/live.m3u8"></video>
<track kind="subtitles" src="/subs/id.vtt" srclang="id">
</article></body></html>"""

SITE = "https://arsip.example"


def mock_site(web, *, fake_body=b"<html><body>bukan gambar</body></html>"):
    web.get(f"{SITE}/artikel").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "text/html; charset=utf-8"}, content=PAGE)
    )
    web.head(f"{SITE}/img/ok.png").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "image/png", "Content-Length": str(len(PNG))})
    )
    web.get(f"{SITE}/img/ok.png").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "image/png"}, content=PNG)
    )
    web.head(f"{SITE}/img/missing.jpg").mock(return_value=httpx.Response(404))
    web.get(f"{SITE}/img/missing.jpg").mock(return_value=httpx.Response(404))
    web.head(f"{SITE}/img/fake.png").mock(return_value=httpx.Response(200, headers={"Content-Type": "image/png"}))
    web.get(f"{SITE}/img/fake.png").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "image/png"}, content=fake_body)
    )
    web.head(f"{SITE}/img/big.png").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "image/png", "Content-Length": str(50 * 1024 * 1024)})
    )
    web.head(f"{SITE}/media/klip.mp4").mock(return_value=httpx.Response(405))
    web.get(f"{SITE}/media/klip.mp4").mock(
        return_value=httpx.Response(206, headers={"Content-Type": "video/mp4", "Content-Range": "bytes 0-0/4096"})
    )
    web.head(f"{SITE}/subs/id.vtt").mock(return_value=httpx.Response(200, headers={"Content-Type": "text/vtt"}))
    web.get(f"{SITE}/subs/id.vtt").mock(return_value=httpx.Response(200, content=VTT))


async def analyze(client, url=f"{SITE}/artikel", **extra):
    return await client.post("/api/v1/analyze", json={"url": url, **extra})


def by_name(result, name):
    return next(m for m in result["media"] if m["filename"] == name)


async def test_analyze_page(client, web):  # TC-05, TC-06, TC-07, TC-08
    mock_site(web)
    res = await analyze(client)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert data["source"] == {"type": "generic", "domain": "arsip.example", "name": "Website umum"}
    assert data["page"]["title"] == "Arsip Kota"
    assert "Pameran arsip kota" in data["text"]["content"]

    ok = by_name(data, "ok.png")
    assert ok["downloadable"] and ok["size"] == len(PNG) and ok["mime_type"] == "image/png"
    missing = by_name(data, "missing.jpg")
    assert not missing["downloadable"] and "404" in missing["reason"]  # TC-08
    big = by_name(data, "big.png")
    assert not big["downloadable"] and "batas" in big["reason"]
    clip = by_name(data, "klip.mp4")
    assert clip["downloadable"] and clip["size"] == 4096  # fallback HEAD → GET Range
    live = by_name(data, "live.m3u8")
    assert live["downloadable"] and (live.get("options") or {}).get("downloader") == "yt-dlp"

    stored = await client.get(f"/api/v1/jobs/{data['id']}/media")
    assert stored.json()["media"] == data["media"]
    job = (await client.get(f"/api/v1/jobs/{data['id']}")).json()
    assert job["status"] == "completed" and job["media_count"]["image"] == 4


async def test_analyze_respects_media_type_filter(client, web):
    mock_site(web)
    data = (await analyze(client, media_types=["subtitle"])).json()
    assert {m["type"] for m in data["media"]} == {"subtitle"}
    assert data["text"] is None


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("", "tidak valid"),
        ("ftp://example.com/x", "tidak didukung"),
        ("http://localhost:8000/api", "diblokir"),  # TC-04
        ("http://192.168.1.1/", "diblokir"),
    ],
)
async def test_analyze_rejects_bad_urls(client, url, message):  # TC-02, TC-03, TC-04
    res = await analyze(client, url=url)
    assert res.status_code in (400, 422)
    assert message in res.json()["detail"]["message"]


async def test_analyze_upstream_errors(client, web):
    web.get("https://gone.example/").mock(return_value=httpx.Response(404))
    web.get("https://login.example/private").mock(
        return_value=httpx.Response(302, headers={"Location": "https://login.example/login?next=/private"})
    )
    web.get("https://login.example/login?next=/private").mock(
        return_value=httpx.Response(
            200, headers={"Content-Type": "text/html"}, content=b"<form><input type=password></form>"
        )
    )
    web.get("https://slow.example/").mock(side_effect=httpx.ConnectTimeout("timeout"))

    assert "tidak ditemukan" in (await analyze(client, url="https://gone.example/")).json()["detail"]["message"]
    login = await analyze(client, url="https://login.example/private")
    assert login.status_code == 422 and "login" in login.json()["detail"]["message"]
    slow = await analyze(client, url="https://slow.example/")
    assert slow.status_code == 502 and "batas waktu" in slow.json()["detail"]["message"]


async def test_platform_recognized_but_not_downloadable(client, monkeypatch):
    monkeypatch.setattr(
        "app.adapters.platforms.social._ytdlp_extract_sync",
        lambda url: {
            "title": "Video Uji Coba",
            "webpage_url": "https://www.youtube.com/watch?v=12345678901",
            "duration": 60,
            "thumbnail": "https://i.ytimg.com/vi/12345678901/hqdefault.jpg",
            "formats": [
                {
                    "format_id": "18",
                    "ext": "mp4",
                    "width": 640,
                    "height": 360,
                    "filesize": 1024000,
                    "url": "https://googlevideo.com/videoplayback",
                }
            ],
        },
    )
    res = await analyze(client, url="https://www.youtube.com/watch?v=12345678901")
    assert res.status_code == 200
    data = res.json()
    assert data["source"]["type"] == "youtube"
    assert data["page"]["title"] == "Video Uji Coba"
    assert len(data["media"]) > 0


async def test_direct_file_url(client, web):
    web.get("https://cdn.example/foto.png").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "image/png", "Content-Length": "2008"}, content=PNG)
    )
    data = (await analyze(client, url="https://cdn.example/foto.png")).json()
    assert len(data["media"]) == 1 and data["media"][0]["type"] == "image" and data["media"][0]["size"] == 2008


async def wait_jobs(app):
    await app.state.queue.drain()


async def test_download_flow(app, client, web, settings):  # TC-10
    mock_site(web)
    data = (await analyze(client)).json()
    ok, sub = by_name(data, "ok.png"), by_name(data, "id.vtt")

    res = await client.post(
        "/api/v1/downloads",
        json={"analysis_id": data["id"], "media_ids": [ok["id"], sub["id"]], "subtitle_format": "srt"},
    )
    assert res.status_code == 201, res.text
    jobs = res.json()
    assert [j["status"] for j in jobs] == ["pending", "pending"]
    await wait_jobs(app)

    image_job = (await client.get(f"/api/v1/downloads/{jobs[0]['id']}")).json()
    assert image_job["status"] == "completed" and image_job["progress"] == 100
    assert image_job["filename"] == "ok.png" and image_job["expires_at"]

    file_res = await client.get(f"/api/v1/downloads/{jobs[0]['id']}/file")
    assert file_res.status_code == 200 and file_res.content == PNG
    assert file_res.headers["content-type"] == "image/png"
    assert "attachment" in file_res.headers["content-disposition"]
    assert file_res.headers["x-content-type-options"] == "nosniff"

    # Nama file di disk dibuat server, bukan dari sumber.
    stored = list(settings.downloads_dir.iterdir())
    assert sorted(p.suffix for p in stored) == [".png", ".srt"]
    assert all(p.stem in {j["id"].replace("-", "") for j in jobs} for p in stored)

    srt = await client.get(f"/api/v1/downloads/{jobs[1]['id']}/file")
    assert srt.text.startswith("1\n00:00:01,000 --> 00:00:02,000\nHalo")

    # Uji pengemasan batch ZIP
    import io
    import zipfile
    zip_res = await client.post("/api/v1/downloads/zip", json={"job_ids": [jobs[0]["id"], jobs[1]["id"]]})
    assert zip_res.status_code == 200
    assert zip_res.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
        names = zf.namelist()
        assert len(names) == 2
        assert any(n.endswith(".png") for n in names)
        assert any(n.endswith(".srt") for n in names)

    history = (await client.get("/api/v1/history")).json()
    assert {h["id"] for h in history} == {j["id"] for j in jobs}
    assert (await client.get("/api/v1/history", params={"media_type": "subtitle"})).json()[0]["id"] == jobs[1]["id"]

    # UC-10: hapus riwayat → file dan log kejadian ikut terhapus.
    assert (await client.delete(f"/api/v1/history/{jobs[0]['id']}")).status_code == 204
    assert len(list(settings.downloads_dir.iterdir())) == 1
    async with app.state.sessions() as s:
        events = (await s.scalars(select(DownloadHistory.job_id))).all()
    assert all(str(e) != jobs[0]["id"] for e in events)
    assert (await client.get(f"/api/v1/downloads/{jobs[0]['id']}")).status_code == 404


async def test_fake_mime_fails_with_message(app, client, web, settings):  # TC-11
    mock_site(web)
    data = (await analyze(client)).json()
    fake = by_name(data, "fake.png")
    jobs = (await client.post("/api/v1/downloads", json={"analysis_id": data["id"], "media_ids": [fake["id"]]})).json()
    await wait_jobs(app)
    job = (await client.get(f"/api/v1/downloads/{jobs[0]['id']}")).json()
    assert job["status"] == "failed" and "halaman HTML" in job["error_message"]
    assert list(settings.temp_dir.iterdir()) == []  # file sementara dibersihkan
    assert (await client.get(f"/api/v1/downloads/{jobs[0]['id']}/file")).status_code == 409


async def test_oversized_stream_is_stopped(app, client, web, settings):  # TC-09
    mock_site(web, fake_body=b"\x89PNG\r\n\x1a\n" + b"\x00" * (2 * 1024 * 1024))
    data = (await analyze(client)).json()
    fake = by_name(data, "fake.png")
    jobs = (await client.post("/api/v1/downloads", json={"analysis_id": data["id"], "media_ids": [fake["id"]]})).json()
    await wait_jobs(app)
    job = (await client.get(f"/api/v1/downloads/{jobs[0]['id']}")).json()
    assert job["status"] == "failed" and "batas 1 MB" in job["error_message"]
    assert list(settings.temp_dir.iterdir()) == []


async def test_transient_error_is_retried(app, client, web, monkeypatch):
    import app.services.download_runner as runner

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(runner.asyncio, "sleep", no_sleep)
    mock_site(web)
    web.get(f"{SITE}/img/ok.png").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, headers={"Content-Type": "image/png"}, content=PNG)]
    )
    data = (await analyze(client)).json()
    ok = by_name(data, "ok.png")
    jobs = (await client.post("/api/v1/downloads", json={"analysis_id": data["id"], "media_ids": [ok["id"]]})).json()
    await wait_jobs(app)
    assert (await client.get(f"/api/v1/downloads/{jobs[0]['id']}")).json()["status"] == "completed"


async def test_failed_job_can_be_retried(app, client, web, monkeypatch):
    import app.services.download_runner as runner

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(runner.asyncio, "sleep", no_sleep)
    mock_site(web)
    route = web.get(f"{SITE}/img/ok.png").mock(return_value=httpx.Response(500))
    data = (await analyze(client)).json()
    ok = by_name(data, "ok.png")
    jobs = (await client.post("/api/v1/downloads", json={"analysis_id": data["id"], "media_ids": [ok["id"]]})).json()
    await wait_jobs(app)
    failed = (await client.get(f"/api/v1/downloads/{jobs[0]['id']}")).json()
    assert failed["status"] == "failed" and "HTTP 500" in failed["error_message"]

    route.mock(return_value=httpx.Response(200, headers={"Content-Type": "image/png"}, content=PNG))
    retried = await client.post(f"/api/v1/downloads/{jobs[0]['id']}/retry")
    assert retried.json()["status"] == "pending"
    await wait_jobs(app)
    assert (await client.get(f"/api/v1/downloads/{jobs[0]['id']}")).json()["status"] == "completed"


async def test_cannot_download_unavailable_or_unknown_media(client, web):
    mock_site(web)
    data = (await analyze(client)).json()
    missing = by_name(data, "missing.jpg")
    res = await client.post("/api/v1/downloads", json={"analysis_id": data["id"], "media_ids": [missing["id"]]})
    assert res.status_code == 422 and "404" in res.json()["detail"]["message"]
    res = await client.post("/api/v1/downloads", json={"analysis_id": data["id"], "media_ids": ["img-arbitrary"]})
    assert res.status_code == 404


async def test_expired_file_is_rejected(app, client, web):  # TC-12
    mock_site(web)
    data = (await analyze(client)).json()
    ok = by_name(data, "ok.png")
    jobs = (await client.post("/api/v1/downloads", json={"analysis_id": data["id"], "media_ids": [ok["id"]]})).json()
    await wait_jobs(app)
    async with app.state.sessions() as s:
        await s.execute(update(DownloadFile).values(expires_at=utcnow() - timedelta(minutes=1)))
        await s.commit()
    res = await client.get(f"/api/v1/downloads/{jobs[0]['id']}/file")
    assert res.status_code == 410 and "kedaluwarsa" in res.json()["detail"]["message"]

    from app.services.cleanup import run_cleanup

    report = await run_cleanup(app.state.sessions, app.state.settings)
    assert report.expired_files == 1
    assert list(app.state.settings.downloads_dir.iterdir()) == []


async def test_validation_error_shape(client):
    res = await client.post("/api/v1/downloads", json={"analysis_id": "bukan-uuid", "media_ids": []})
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_request"


async def test_rate_limit(app, client, web):
    app.state.settings.rate_limit_analyze_per_minute = 2
    web.get("https://gone.example/").mock(return_value=httpx.Response(404))
    for _ in range(2):
        await analyze(client, url="https://gone.example/")
    res = await analyze(client, url="https://gone.example/")
    assert res.status_code == 429 and "Retry-After" in res.headers


async def test_untrusted_network_and_host_blocked(app):
    outside = httpx.ASGITransport(app=app, client=("8.8.8.8", 4000))
    async with httpx.AsyncClient(transport=outside, base_url="http://testserver") as c:
        assert (await c.get("/api/v1/health")).status_code == 403
    local = httpx.ASGITransport(app=app, client=("127.0.0.1", 4000))
    async with httpx.AsyncClient(transport=local, base_url="http://evil.example") as c:
        assert (await c.get("/api/v1/health")).status_code == 400


async def test_system_endpoints(client):
    health = (await client.get("/api/v1/health")).json()
    assert health["status"] == "ok" and health["database"]
    adapters = {a["id"]: a["status"] for a in (await client.get("/api/v1/adapters")).json()}
    assert adapters["generic"] == "active" and adapters["youtube"] == "active"
    config = (await client.get("/api/v1/config")).json()
    assert config["max_download_size_mb"] == 1 and config["queue_backend"] == "inline"
