from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.extractors.dynamic import _is_media_url, _parse_cookies_for_playwright, render_and_sniff


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


@pytest.mark.asyncio
async def test_render_and_sniff_intercepts_media_mocked():
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html><body><video src='https://cdn.example/video.mp4'></video></body></html>")
    mock_page.goto = AsyncMock()
    mock_loc = AsyncMock()
    mock_loc.count = AsyncMock(return_value=0)
    mock_page.locator = MagicMock(return_value=mock_loc)

    handlers = {}
    def on_mock(event, handler):
        handlers[event] = handler

    mock_page.on = MagicMock(side_effect=on_mock)

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_playwright = AsyncMock()
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_playwright
    mock_cm.__aexit__.return_value = None

    with patch("playwright.async_api.async_playwright", return_value=mock_cm):
        settings = Settings(dynamic_render_timeout_seconds=5.0)

        async def run_test():
            task = asyncio.create_task(render_and_sniff("https://spa.example", settings))
            await asyncio.sleep(0.01)
            # Simulasi network response intercepted
            if "response" in handlers:
                mock_resp = MagicMock()
                mock_resp.url = "https://stream.example/master.m3u8?token=xyz"
                mock_resp.headers = {"content-type": "application/vnd.apple.mpegurl"}
                handlers["response"](mock_resp)

                mock_sub_resp = MagicMock()
                mock_sub_resp.url = "https://stream.example/subtitle.vtt"
                mock_sub_resp.headers = {"content-type": "text/vtt"}
                handlers["response"](mock_sub_resp)
            return await task

        import asyncio
        html, candidates, warnings = await run_test()
        assert "video.mp4" in html
        assert len(candidates) == 2
        urls = [c.url for c in candidates]
        assert "https://stream.example/master.m3u8?token=xyz" in urls
        assert "https://stream.example/subtitle.vtt" in urls


def test_parse_cookies_for_playwright():
    kv = "sessionid=abc123xyz; csrftoken=def456"
    cookies = _parse_cookies_for_playwright(kv, "https://sub.example.com/video")
    assert len(cookies) == 2
    assert cookies[0]["name"] == "sessionid" and cookies[0]["value"] == "abc123xyz"
    assert cookies[0]["domain"] == "sub.example.com"
    assert cookies[1]["name"] == "csrftoken" and cookies[1]["value"] == "def456"

    netscape = "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t0\tsession\tsecret123"
    n_cookies = _parse_cookies_for_playwright(netscape, "https://example.com/test")
    assert len(n_cookies) == 1
    assert n_cookies[0]["name"] == "session" and n_cookies[0]["value"] == "secret123"
    assert n_cookies[0]["domain"] == "example.com"
