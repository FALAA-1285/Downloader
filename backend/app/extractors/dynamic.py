"""Render dinamis dengan Playwright (Chromium headless) dan penyadapan request media.

Halaman SPA (React/Next.js/Vue) baru memuat pemutar, gambar, dan teks setelah JavaScript
berjalan. Modul ini merender halaman, mencatat request media (HLS/DASH/video/subtitle) dari
lalu lintas jaringan, lalu mengembalikan HTML hasil render untuk diekstrak ulang.

Keamanan (C-02):
- Semua lalu lintas Chromium lewat proxy penjaga SSRF (`core.guard_proxy`), termasuk loopback
  (Playwright memaksa aturan `<-loopback>` sehingga 127.0.0.1 tidak di-bypass).
- Lapis kedua: `context.route` menolak URL dengan host internal/literal IP privat sebelum dikirim.
- Sertifikat TLS diverifikasi; WebRTC tidak boleh membuka UDP langsung (kebocoran ke LAN).

Kinerja (M-01): satu proses Chromium dipakai bersama; setiap analisis mendapat context baru yang
terisolasi (cookie, cache, storage) dan ditutup di akhir analisis.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.core.cookies import first_party_headers, parse_cookies, to_playwright
from app.core.errors import UnsafeURLError
from app.core.guard_proxy import get_guard_proxy
from app.core.url_guard import validate_url
from app.extractors.common import Candidate

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

PLAY_SELECTORS = (
    "button.play",
    ".play-button",
    ".vjs-big-play-button",
    ".jw-display-icon-container",
    "#player",
    ".player",
    "video",
)
SETTLE_SECONDS = 2.5

# Penanda halaman tantangan anti-bot (Cloudflare, DDoS-Guard, dll.). Halaman seperti ini tidak
# berisi konten; aplikasi tidak mencoba mengakalinya, hanya memberi pesan yang jelas.
CHALLENGE_MARKERS = re.compile(
    r"just a moment\.\.\.|attention required! \| cloudflare|cf-browser-verification|challenges\.cloudflare\.com"
    r"|/cdn-cgi/challenge-platform|ddos-guard|checking your browser|captcha-delivery",
    re.I,
)


@dataclass
class RenderResult:
    html: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: int | None = None  # status HTTP dokumen utama
    final_url: str | None = None
    challenge: bool = False


def looks_like_challenge(html: str, status: int | None) -> bool:
    if not html or not CHALLENGE_MARKERS.search(html[:200_000]):
        return False
    # Banyak halaman normal memuat reCAPTCHA di form; anggap tantangan hanya bila dokumen utama
    # ditolak atau halamannya nyaris kosong.
    return status in (403, 429, 503) or len(html) < 30_000


CHROMIUM_ARGS = [
    "--disable-dev-shm-usage",
    "--mute-audio",
    "--disable-gpu",
    "--disable-extensions",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-features=WebRtcHideLocalIpsWithMdns",
]


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


def _is_safe_url(url: str, settings: Settings) -> bool:
    """Pemeriksaan cepat tanpa DNS; resolusi DNS diperiksa proxy penjaga saat koneksi dibuka."""
    try:
        validate_url(url, settings.port_allowlist)
        return True
    except UnsafeURLError:
        return False


class BrowserPool:
    """Satu Chromium per event loop, diluncurkan saat pertama kali dibutuhkan."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._proxy_url: str | None = None
        self._lock: asyncio.Lock | None = None

    async def browser(self, settings: Settings) -> Any:
        loop = asyncio.get_running_loop()
        proxy = await get_guard_proxy(settings)
        if self._usable(loop, proxy.url):
            return self._browser
        if self._lock is None or self._loop is not loop:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._usable(loop, proxy.url):
                return self._browser
            await self.close()
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                chromium_sandbox=settings.chromium_sandbox,
                proxy={"server": proxy.url},
                args=CHROMIUM_ARGS,
            )
            self._loop = loop
            self._proxy_url = proxy.url
            return self._browser

    def _usable(self, loop: asyncio.AbstractEventLoop, proxy_url: str) -> bool:
        return bool(
            self._browser is not None
            and self._loop is loop
            and self._proxy_url == proxy_url
            and self._browser.is_connected()
        )

    async def close(self) -> None:
        browser, pw = self._browser, self._playwright
        self._browser = self._playwright = None
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        if pw is not None:
            with contextlib.suppress(Exception):
                await pw.stop()


_pool = BrowserPool()


async def shutdown_browser_pool() -> None:
    await _pool.close()


async def render_and_sniff(
    url: str,
    settings: Settings,
    *,
    wants_video: bool = True,
    wants_subtitles: bool = True,
    cookies: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[str, list[Candidate], list[str]]:
    """Membuka halaman, mengeksekusi JS, menyadap request media.

    Mengembalikan (rendered_html, intercepted_candidates, warnings).
    """
    result = await render_page(
        url, settings, wants_video=wants_video, wants_subtitles=wants_subtitles, cookies=cookies, headers=headers
    )
    return result.html, result.candidates, result.warnings


async def render_page(
    url: str,
    settings: Settings,
    *,
    wants_video: bool = True,
    wants_subtitles: bool = True,
    cookies: str | None = None,
    headers: dict[str, str] | None = None,
) -> RenderResult:
    """Seperti `render_and_sniff`, ditambah status HTTP dokumen utama, URL akhir, dan
    apakah halaman yang didapat adalah tantangan anti-bot."""
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        logger.warning("Playwright tidak terpasang. Dynamic rendering dilewati.")
        return RenderResult(warnings=["Engine rendering dinamis (Playwright) belum terpasang."])

    intercepted: dict[str, Candidate] = {}
    warnings: list[str] = []
    rendered_html = ""
    main_status: int | None = None
    final_url: str | None = None
    timeout_ms = int(settings.dynamic_render_timeout_seconds * 1000)

    def _handle_intercept(target_url: str, content_type: str | None = None) -> None:
        if not target_url or target_url.startswith(("data:", "blob:")) or target_url in intercepted:
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
        if not m_type or (m_type == "video" and not wants_video) or (m_type == "subtitle" and not wants_subtitles):
            return
        if not _is_safe_url(target_url, settings):
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
            probe=not is_stream,
            options={"downloader": "yt-dlp"} if (is_stream or m_type == "video") else None,
        )

    def on_request(request: Any) -> None:
        try:
            _handle_intercept(request.url)
        except Exception as exc:  # noqa: BLE001 - event handler tidak boleh menggagalkan render
            logger.debug("gagal memproses request %s: %s", getattr(request, "url", "?"), exc)

    def on_response(response: Any) -> None:
        try:
            _handle_intercept(response.url, response.headers.get("content-type"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("gagal memproses response %s: %s", getattr(response, "url", "?"), exc)

    async def guard_route(route: Any) -> None:
        req_url = route.request.url
        if req_url.startswith(("http://", "https://")) and not _is_safe_url(req_url, settings):
            await route.abort("blockedbyclient")
            return
        extra = first_party_headers(headers, req_url, url)
        if extra:
            await route.continue_(headers={**route.request.headers, **extra})
        else:
            await route.continue_()

    context = None
    try:
        browser = await _pool.browser(settings)
        context = await browser.new_context(
            user_agent=settings.user_agent,
            viewport={"width": 1920, "height": 1080},
            ignore_https_errors=False,
            service_workers="block",
        )
        await context.route("**/*", guard_route)
        if cookies:
            parsed = to_playwright(parse_cookies(cookies, url))
            if parsed:
                try:
                    await context.add_cookies(parsed)
                except Exception as exc:  # noqa: BLE001
                    warnings.append("Sebagian cookie tidak dapat dipakai oleh renderer dinamis.")
                    logger.debug("Gagal menyuntikkan cookie ke Playwright: %s", exc)

        page = await context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            main_status = response.status if response is not None else None
        except Exception as exc:  # noqa: BLE001 - halaman lambat tetap disadap
            logger.debug("Page goto timeout/error (dilanjutkan untuk sniffing): %s", exc)

        # Picu pemutar agar stream mulai dimuat.
        for sel in PLAY_SELECTORS:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.hover(timeout=500)
                    if "button" in sel or "icon" in sel:
                        await loc.click(timeout=800)
                    break
            except Exception as exc:  # noqa: BLE001
                logger.debug("interaksi pemutar %s gagal: %s", sel, exc)

        # Jeda singkat agar XHR/fetch stream sempat berjalan. Pembatalan (batas waktu analisis)
        # TIDAK ditelan agar `wait_for` di lapisan atas benar-benar berhenti.
        await asyncio.sleep(SETTLE_SECONDS)
        rendered_html = await page.content()
        final_url = page.url if isinstance(page.url, str) else None
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal melakukan dynamic sniffing dengan Playwright: %s", exc)
        warnings.append("Renderer dinamis menemui kendala; hasil analisis mungkin tidak lengkap.")
    finally:
        if context is not None:
            with contextlib.suppress(Exception):
                await asyncio.shield(context.close())

    return RenderResult(
        html=rendered_html,
        candidates=list(intercepted.values()),
        warnings=warnings,
        status=main_status if isinstance(main_status, int) else None,
        final_url=final_url,
        challenge=looks_like_challenge(rendered_html, main_status if isinstance(main_status, int) else None),
    )
