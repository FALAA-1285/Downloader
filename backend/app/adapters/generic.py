"""Generic Adapter: analisis HTML untuk website umum (FR-03 s.d. FR-07)."""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urlsplit

from app.core.cookies import parse_cookies
from app.core.errors import AppError
from app.core.http_client import open_stream, read_limited, status_error
from app.extractors.common import (
    AUDIO_EXT,
    IMAGE_EXT,
    STREAM_EXT,
    SUBTITLE_EXT,
    VIDEO_EXT,
    Candidate,
    mime_from_ext,
    url_ext,
)
from app.extractors.images import extract_images
from app.extractors.media import extract_av, extract_subtitles
from app.extractors.page import has_login_form, is_login_url, needs_javascript, parse_html
from app.extractors.probe import probe_candidates
from app.extractors.text import extract_text, word_count

from .base import Adapter, AnalysisContext, AnalysisOutcome

HTML_TYPES = ("text/html", "application/xhtml+xml")
log = logging.getLogger(__name__)


def _direct_type(mime: str, ext: str | None) -> str | None:
    if mime.startswith("image/") or ext in IMAGE_EXT:
        return "image"
    if "mpegurl" in mime or "dash+xml" in mime or ext in STREAM_EXT:
        return "stream"
    if mime.startswith("video/") or ext in VIDEO_EXT:
        return "video"
    if mime.startswith("audio/") or ext in AUDIO_EXT:
        return "audio"
    if mime in ("text/vtt", "application/x-subrip") or ext in SUBTITLE_EXT:
        return "subtitle"
    return None


class GenericAdapter(Adapter):
    id = "generic"
    name = "Website umum"
    source_type = "generic"
    domains = ("*",)
    status = "active"
    note = "Analisis HTML: gambar, teks, video langsung, audio, dan subtitle."

    def matches(self, domain: str) -> bool:
        return True

    async def analyze(self, ctx: AnalysisContext) -> AnalysisOutcome:
        settings = ctx.settings
        headers = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"}
        if ctx.headers:
            headers.update(ctx.headers)
        # Cookie diubah ke daftar terikat domain; open_stream hanya mengirim yang cocok per hop.
        jar = parse_cookies(ctx.cookies, ctx.url)
        async with open_stream(ctx.client, ctx.url, settings, headers=headers, cookies=jar) as (resp, final_url):
            if resp.status_code >= 400:
                raise status_error(resp.status_code)
            mime = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()

            if not mime.startswith(HTML_TYPES):
                return self._direct_file(final_url, mime, resp.headers.get("content-length"), ctx)

            data, truncated = await read_limited(resp, settings.max_page_bytes)
            charset = resp.charset_encoding

        page, media, warnings, text_title, text = await asyncio.to_thread(self._extract, data, final_url, charset, ctx)
        if truncated:
            warnings.insert(
                0, f"Halaman lebih besar dari {settings.max_page_size_mb:g} MB; hanya bagian awal yang dianalisis."
            )

        words = word_count(text)
        if is_login_url(final_url):
            raise AppError(
                "auth_required",
                "Halaman ini membutuhkan login. Konten di balik autentikasi tidak dianalisis.",
                422,
            )
        if has_login_form(page, words):
            # Bukan error: halaman bisa saja punya form login di header tetapi tetap berisi media publik.
            warnings.append("Halaman memuat form login; konten yang membutuhkan login tidak dianalisis.")
        if needs_javascript(page, words):
            warnings.append("Halaman tampaknya dimuat dengan JavaScript; sebagian konten mungkin tidak terdeteksi.")

        has_video = any(m.type == "video" for m in media)
        has_subtitle = any(m.type == "subtitle" for m in media)
        is_streaming_spa = bool(
            page.soup.find(id=re.compile(r"^(root|app|__next|__nuxt)$"))
            or "self.__next_f" in page.html
            or needs_javascript(page, words)
        )

        if settings.enable_dynamic_rendering and is_streaming_spa and (not has_video or not has_subtitle):
            try:
                from app.extractors.dynamic import render_and_sniff

                r_html, intercepted, dyn_warnings = await render_and_sniff(
                    final_url,
                    settings,
                    wants_video=ctx.wants("video"),
                    wants_subtitles=ctx.wants("subtitle"),
                    cookies=ctx.cookies,
                    headers=ctx.headers,
                )
                warnings.extend(dyn_warnings)

                existing_urls = {m.url for m in media}
                for c in intercepted:
                    if c.url not in existing_urls:
                        media.append(c)
                        existing_urls.add(c.url)

                if r_html:
                    _, r_media, r_warn, _, _ = await asyncio.to_thread(
                        self._extract, r_html.encode("utf-8", "ignore"), final_url, "utf-8", ctx
                    )
                    for c in r_media:
                        if c.url not in existing_urls:
                            media.append(c)
                            existing_urls.add(c.url)
                    warnings.extend(r_warn)
            except Exception:  # noqa: BLE001 - render dinamis bersifat tambahan
                log.warning("renderer dinamis gagal untuk %s", final_url, exc_info=True)
                warnings.append("Renderer dinamis tidak dapat dijalankan; hanya HTML statis yang dianalisis.")

            has_video = any(m.type == "video" for m in media)
            has_subtitle = any(m.type == "subtitle" for m in media)

        if len(media) > settings.max_media_items:
            warnings.append(f"Ditemukan {len(media)} media; hanya {settings.max_media_items} pertama yang ditampilkan.")
            media = media[: settings.max_media_items]

        warnings.extend(await probe_candidates(ctx.client, media, settings, referer=final_url, cookies=jar))

        if ctx.wants("text") and not text:
            warnings.append("Teks utama tidak terdeteksi pada halaman ini.")

        url_path = (urlsplit(final_url).path or "").strip("/")
        if ctx.wants("video") and not has_video and (url_path in ("", "index", "home") or len(media) > 50):
            warnings.append(
                "Halaman ini tampaknya merupakan beranda atau katalog daftar konten (bukan halaman pemutar film). "
                "Untuk mengunduh video, buka judul film yang diinginkan lalu salin URL halaman film spesifik tersebut."
            )

        if is_streaming_spa and ctx.wants("video") and not has_video:
            warnings.append(
                "Halaman ini memuat kontennya lewat JavaScript; sebagian media mungkin tidak terdeteksi. "
                "Konten yang dilindungi DRM atau enkripsi pemutar tidak didukung."
            )

        return AnalysisOutcome(
            final_url=final_url,
            title=page.title,
            description=page.description,
            thumbnail=page.thumbnail,
            media=media,
            text_title=text_title or page.title,
            text_content=text if ctx.wants("text") else None,
            warnings=warnings,
        )

    def _extract(self, data: bytes, final_url: str, charset: str | None, ctx: AnalysisContext):
        page = parse_html(data, final_url, charset)
        media: list[Candidate] = []
        warnings: list[str] = []
        if ctx.wants("image"):
            media += extract_images(page.soup, page.base_url)
        if ctx.wants("video") or ctx.wants("audio"):
            av, av_warnings = extract_av(page.soup, page.base_url)
            media += [m for m in av if ctx.wants(m.type)]
            warnings += av_warnings
        if ctx.wants("subtitle"):
            media += extract_subtitles(page.soup, page.base_url)
        # Teks dihitung selalu untuk deteksi login/JavaScript, tetapi hanya dikirim bila diminta.
        text_title, text = extract_text(page.html, final_url, page.soup)
        return page, media, warnings, text_title, text

    def _direct_file(self, url: str, mime: str, length: str | None, ctx: AnalysisContext) -> AnalysisOutcome:
        ext = url_ext(url)
        kind = _direct_type(mime, ext)
        if kind is None:
            raise AppError("unsupported_content", f"Tipe konten {mime or 'tidak dikenal'} tidak didukung.", 422)
        media_type = "video" if kind == "stream" else kind
        size = int(length) if length and length.isdigit() else None
        is_stream = kind == "stream"
        item = Candidate(
            type=media_type,
            url=url,
            mime_type="video/mp4" if is_stream else (mime or mime_from_ext(ext)),
            size=size,
            preview_url=url if media_type == "image" else None,
            probe=False,
            downloadable=True,
            reason=None,
            options={"downloader": "yt-dlp"} if is_stream else None,
        )
        if not is_stream and size is not None and size > ctx.settings.max_download_bytes:
            item.downloadable = False
            item.reason = f"Ukuran file melebihi batas {ctx.settings.max_download_size_mb} MB yang diizinkan."
        warnings = [] if ctx.wants(media_type) else [f"URL ini adalah file {media_type} langsung."]
        return AnalysisOutcome(final_url=url, title=item.filename, media=[item], warnings=warnings)
