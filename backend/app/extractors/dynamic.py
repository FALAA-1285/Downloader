"""Dynamic headless browser renderer & network sniffer using Playwright.

Mengeksekusi JavaScript pada situs SPA/Next.js/React untuk mendeteksi
pemutar video dinamis dan menyadap (sniff) URL stream HLS/DASH/video dan subtitle
dari lalu lintas jaringan (network request) secara langsung.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from app.core.config import Settings
from app.extractors.common import Candidate, absolutize, mime_from_ext, url_ext

logger = logging.getLogger(__name__)

STREAM_MIME_TYPES = {
    "application/x-mpegurl",
    "application/vnd.apple.mpegurl",
    "application/dash+xml",
    "video/mp4",
    "video/webm",
}

SUBTITLE_MIME_TYPES = {
    "text/vtt",
    "application/x-subrip",
    "text/plain",
}


def _is_media_url(url: str) -> tuple[str | None, str | None]:
    """Mengembalikan (media_type, mime_type) jika URL cocok dengan aliran video/subtitle."""
    clean_url = url.split("?")[0].lower()
    if clean_url.endswith(".m3u8"):
        return "video", "video/mp4"
    if clean_url.endswith(".mpd"):
        return "video", "video/mp4"
    if clean_url.endswith((".mp4", ".mkv", ".webm", ".mov")):
        return "video", "video/mp4"
    if clean_url.endswith((".vtt", ".srt")):
        return "subtitle", "text/vtt"
    return None, None


def _parse_cookies_for_playwright(cookie_str: str, target_url: str) -> list[dict[str, Any]]:
    """Ubah string cookie (format Netscape cookies.txt atau key=value;) menjadi list cookie Playwright."""
    domain = urlsplit(target_url).hostname or "localhost"
    cookies: list[dict[str, Any]] = []
    lines = [l.strip() for l in cookie_str.strip().splitlines() if l.strip()]
    if any("\t" in l for l in lines):
        for line in lines:
            if line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                d, _, p, _, _, name, val = parts[:7]
                cookies.append({
                    "name": name.strip(),
                    "value": val.strip(),
                    "domain": d.strip().lstrip("."),
                    "path": p.strip() or "/",
                })
    else:
        for chunk in cookie_str.split(";"):
            if "=" in chunk:
                k, v = chunk.strip().split("=", 1)
                cookies.append({
                    "name": k.strip(),
                    "value": v.strip(),
                    "domain": domain,
                    "path": "/",
                })
    return cookies


async def render_and_sniff(
    url: str,
    settings: Settings,
    *,
    wants_video: bool = True,
    wants_subtitles: bool = True,
    cookies: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[str, list[Candidate], list[str]]:
    """Membuka halaman dengan Playwright Chromium, mengeksekusi JS, menyadap request media,

    dan mengembalikan (rendered_html, intercepted_candidates, warnings).
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright tidak terpasang. Dynamic rendering dilewati.")
        return "", [], ["Engine rendering dinamis (Playwright) belum terpasang."]

    intercepted: dict[str, Candidate] = {}
    warnings: list[str] = []
    rendered_html = ""

    timeout_ms = int(settings.dynamic_render_timeout_seconds * 1000)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--mute-audio",
                    "--disable-gpu",
                    "--disable-extensions",
                ],
            )
            try:
                context = await browser.new_context(
                    user_agent=settings.user_agent,
                    viewport={"width": 1920, "height": 1080},
                    ignore_https_errors=True,
                )
                if headers:
                    await context.set_extra_http_headers(headers)
                if cookies:
                    parsed_cookies = _parse_cookies_for_playwright(cookies, url)
                    if parsed_cookies:
                        try:
                            await context.add_cookies(parsed_cookies)
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("Gagal menyuntikkan cookie ke Playwright: %s", exc)

                page = await context.new_page()

                def _handle_intercept(target_url: str, content_type: str | None = None) -> None:
                    if not target_url or target_url.startswith("data:") or target_url.startswith("blob:"):
                        return
                    if target_url in intercepted:
                        return

                    m_type, inferred_mime = _is_media_url(target_url)
                    ct = (content_type or "").split(";")[0].strip().lower()

                    if not m_type:
                        if ct in STREAM_MIME_TYPES or ct.startswith("video/"):
                            m_type = "video"
                            inferred_mime = ct if "octet" not in ct else "video/mp4"
                        elif ct in SUBTITLE_MIME_TYPES and any(k in target_url.lower() for k in ("vtt", "sub", "caption")):
                            m_type = "subtitle"
                            inferred_mime = "text/vtt"

                    if not m_type:
                        return
                    if m_type == "video" and not wants_video:
                        return
                    if m_type == "subtitle" and not wants_subtitles:
                        return

                    is_stream = ".m3u8" in target_url or ".mpd" in target_url or "mpegurl" in (inferred_mime or "")
                    label = (
                        "Captured Stream (HLS/DASH).mp4"
                        if is_stream
                        else ("Captured Video.mp4" if m_type == "video" else "Captured Subtitle.vtt")
                    )

                    intercepted[target_url] = Candidate(
                        type=m_type,
                        url=target_url,
                        mime_type=inferred_mime or ("video/mp4" if m_type == "video" else "text/vtt"),
                        downloadable=True,
                        label=label,
                        probe=False if is_stream else True,
                        options={"downloader": "yt-dlp"} if (is_stream or m_type == "video") else None,
                    )

                def on_request(request: Any) -> None:
                    try:
                        _handle_intercept(request.url)
                    except Exception:  # noqa: BLE001
                        pass

                def on_response(response: Any) -> None:
                    try:
                        headers = response.headers
                        ct = headers.get("content-type")
                        _handle_intercept(response.url, ct)
                    except Exception:  # noqa: BLE001
                        pass

                page.on("request", on_request)
                page.on("response", on_response)

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Page goto timeout/error (dilanjutkan untuk sniffing): %s", exc)

                # Coba interaksi dengan pemutar video untuk memicu pemuatan stream jika ada
                play_selectors = [
                    "button.play",
                    ".play-button",
                    ".vjs-big-play-button",
                    ".jw-display-icon-container",
                    "#player",
                    ".player",
                    "video",
                    "iframe[src*='embed']",
                ]
                for sel in play_selectors:
                    try:
                        loc = page.locator(sel).first
                        if await loc.count() > 0:
                            await loc.hover(timeout=500)
                            # Coba klik jika berupa tombol
                            if "button" in sel or "icon" in sel:
                                await loc.click(timeout=800)
                            break
                    except Exception:  # noqa: BLE001
                        pass

                # Beri jeda singkat agar XHR/Fetch stream sempat berjalan
                try:
                    await asyncio.sleep(2.5)
                except asyncio.CancelledError:
                    pass

                rendered_html = await page.content()
            finally:
                await browser.close()

    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal melakukan dynamic sniffing dengan Playwright: %s", exc)
        warnings.append(f"Dynamic renderer menemui kendala: {exc}")

    return rendered_html, list(intercepted.values()), warnings
