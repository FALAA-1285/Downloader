from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.extractors import dynamic
from app.extractors.dynamic import _is_media_url, render_and_sniff


def test_is_media_url():
    assert _is_media_url("https://example.com/stream/index.m3u8") == ("video", "video/mp4")
    assert _is_media_url("https://example.com/dash/manifest.mpd?token=123") == ("video", "video/mp4")
    assert _is_media_url("https://example.com/video.mp4") == ("video", "video/mp4")
    assert _is_media_url("https://example.com/subtitles/id.vtt") == ("subtitle", "text/vtt")
    assert _is_media_url("https://example.com/subtitles/id.srt") == ("subtitle", "text/vtt")
    assert _is_media_url("https://example.com/image.png") == (None, None)
    assert _is_media_url("https://example.com/page.html") == (None, None)


@pytest.mark.asyncio
async def test_render_and_sniff_handles_import_error():
    with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
        settings = Settings()
        html, candidates, warnings = await render_and_sniff("https://example.com", settings)
        assert html == ""
        assert candidates == []
        assert any("Playwright" in w for w in warnings)


def _mock_browser(html: str = "<html></html>"):
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value=html)
    mock_page.goto = AsyncMock()
    mock_loc = AsyncMock()
    mock_loc.count = AsyncMock(return_value=0)
    mock_page.locator = MagicMock(return_value=mock_loc)
    handlers: dict = {}
    mock_page.on = MagicMock(side_effect=lambda event, handler: handlers.__setitem__(event, handler))

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    return mock_browser, mock_context, handlers


@pytest.mark.asyncio
async def test_render_and_sniff_intercepts_media_mocked(monkeypatch):
    import asyncio

    browser, context, handlers = _mock_browser(
        "<html><body><video src='https://cdn.example/video.mp4'></video></body></html>"
    )
    monkeypatch.setattr(dynamic._pool, "browser", AsyncMock(return_value=browser))
    monkeypatch.setattr(dynamic, "SETTLE_SECONDS", 0.05)

    task = asyncio.create_task(render_and_sniff("https://spa.example", Settings(_env_file=None)))
    await asyncio.sleep(0.01)
    for url, ct in (
        ("https://stream.example/master.m3u8?token=xyz", "application/vnd.apple.mpegurl"),
        ("https://stream.example/subtitle.vtt", "text/vtt"),
        # Request media ke alamat internal tidak boleh menjadi kandidat (C-02).
        ("http://127.0.0.1:8000/secret.mp4", "video/mp4"),
    ):
        resp = MagicMock()
        resp.url = url
        resp.headers = {"content-type": ct}
        handlers["response"](resp)
    html, candidates, _warnings = await task

    assert "video.mp4" in html
    urls = [c.url for c in candidates]
    assert urls == ["https://stream.example/master.m3u8?token=xyz", "https://stream.example/subtitle.vtt"]
    # Context selalu diberi penjaga route dan ditutup setelah render.
    context.route.assert_awaited_once()
    context.close.assert_awaited()
    assert browser.new_context.await_args.kwargs["ignore_https_errors"] is False


@pytest.mark.asyncio
async def test_route_guard_blocks_internal_and_scopes_headers(monkeypatch):
    browser, context, _handlers = _mock_browser()
    monkeypatch.setattr(dynamic._pool, "browser", AsyncMock(return_value=browser))
    monkeypatch.setattr(dynamic, "SETTLE_SECONDS", 0)
    await render_and_sniff(
        "https://site.example/page", Settings(_env_file=None), headers={"Authorization": "Bearer t", "Referer": "r"}
    )
    guard = context.route.await_args.args[1]

    def route_for(url):
        route = AsyncMock()
        route.request = MagicMock(url=url, headers={"accept": "*/*"})
        return route

    internal = route_for("http://192.168.1.1/admin")
    await guard(internal)
    internal.abort.assert_awaited_once()

    first_party = route_for("https://site.example/api")
    await guard(first_party)
    assert first_party.continue_.await_args.kwargs["headers"]["Authorization"] == "Bearer t"

    third_party = route_for("https://cdn.other.example/x.js")
    await guard(third_party)
    sent = third_party.continue_.await_args.kwargs["headers"]
    assert "Authorization" not in sent and sent["Referer"] == "r"


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed(monkeypatch):
    """Batas waktu analisis harus benar-benar menghentikan render (M-01)."""
    import asyncio

    browser, context, _handlers = _mock_browser()
    monkeypatch.setattr(dynamic._pool, "browser", AsyncMock(return_value=browser))
    monkeypatch.setattr(dynamic, "SETTLE_SECONDS", 30)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(render_and_sniff("https://spa.example", Settings(_env_file=None)), 0.2)
    context.close.assert_awaited()
