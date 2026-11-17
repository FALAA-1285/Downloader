"""Direct video, audio (FR-06) dan subtitle (FR-07) extractor."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .common import (
    AUDIO_EXT,
    STREAM_EXT,
    SUBTITLE_EXT,
    VIDEO_EXT,
    Candidate,
    absolutize,
    meta_content,
    mime_from_ext,
    parse_int,
    url_ext,
)

EMBED_HOSTS = {
    "youtube.com": "YouTube",
    "youtube-nocookie.com": "YouTube",
    "player.vimeo.com": "Vimeo",
    "dailymotion.com": "Dailymotion",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
}

LANG_NAMES = {
    "id": "Indonesia",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "zh": "中文",
    "ms": "Melayu",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "ar": "العربية",
    "pt": "Português",
}


def _kind_for(url: str, mime: str | None, default: str) -> str | None:
    ext = url_ext(url)
    mime = (mime or "").lower()
    if ext in STREAM_EXT or "mpegurl" in mime or "dash+xml" in mime:
        return "stream"
    if ext in VIDEO_EXT or mime.startswith("video/"):
        return "video"
    if ext in AUDIO_EXT or mime.startswith("audio/"):
        return "audio"
    if ext is None and not mime:
        return default
    return None


def extract_av(soup: BeautifulSoup, base: str) -> tuple[list[Candidate], list[str]]:
    """Mengembalikan (kandidat video+audio, peringatan)."""
    found: dict[str, Candidate] = {}
    warnings: list[str] = []
    blob_sources = 0

    def add(raw, *, default: str, mime=None, poster=None, width=None, height=None, label=None, duration=None):
        nonlocal blob_sources
        if raw and str(raw).strip().startswith("blob:"):
            blob_sources += 1
            return
        url = absolutize(base, raw)
        if not url or url in found:
            return
        kind = _kind_for(url, mime, default)
        if kind is None:
            return
        ext = url_ext(url)
        media_type = "audio" if kind == "audio" else "video"
        is_stream = kind == "stream"
        found[url] = Candidate(
            type=media_type,
            url=url,
            mime_type="video/mp4" if is_stream else (mime or mime_from_ext(ext)),
            downloadable=True,
            reason=None,
            preview_url=absolutize(base, poster) if media_type == "video" else None,
            width=parse_int(width),
            height=parse_int(height),
            label=label or (f"{media_type}.mp4 (HLS Stream)" if is_stream else None),
            duration=duration,
            probe=False if is_stream else True,
            options={"downloader": "yt-dlp"} if is_stream else None,
        )

    for el in soup.find_all(["video", "audio"]):
        default = el.name
        poster = el.get("poster")
        add(el.get("src"), default=default, poster=poster, width=el.get("width"), height=el.get("height"))
        for source in el.find_all("source"):
            source_res = parse_int(source.get("res") or source.get("height"))
            source_label = source.get("label") or source.get("title")
            add(
                source.get("src"),
                default=default,
                mime=source.get("type"),
                poster=poster,
                width=parse_int(source.get("width")) or parse_int(el.get("width")),
                height=source_res or parse_int(el.get("height")),
                label=source_label,
            )

    for name in ("og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"):
        content = meta_content(soup, name)
        if content:
            mime = meta_content(soup, "og:video:type", "twitter:player:stream:content_type")
            add(
                content,
                default="video",
                mime=mime,
                poster=meta_content(soup, "og:image"),
                width=meta_content(soup, "og:video:width"),
                height=meta_content(soup, "og:video:height"),
            )
    for name in ("og:audio", "og:audio:url", "og:audio:secure_url"):
        content = meta_content(soup, name)
        if content:
            add(content, default="audio", mime=meta_content(soup, "og:audio:type"))

    for a in soup.find_all("a", href=True):
        ext = url_ext(str(a["href"]))
        if ext in VIDEO_EXT | AUDIO_EXT | STREAM_EXT:
            add(a["href"], default="video", label=a.get_text(" ", strip=True) or None)

    # Pemutar tersemat dari platform: dilaporkan, tetapi tidak diunduh.
    for iframe in soup.find_all("iframe", src=True):
        url = absolutize(base, iframe["src"])
        if not url or url in found:
            continue
        host = re.sub(r"^www\.", "", url.split("/")[2].lower())
        platform = next((name for h, name in EMBED_HOSTS.items() if host == h or host.endswith("." + h)), None)
        if platform:
            found[url] = Candidate(
                type="video",
                url=url,
                downloadable=True,
                reason=None,
                label=f"{platform} Embed Video",
                probe=False,
                options={"downloader": "yt-dlp"},
            )

    if blob_sources:
        warnings.append(
            f"{blob_sources} sumber media dimuat lewat MediaSource (blob:) dan tidak dapat diakses langsung."
        )
    return list(found.values()), warnings


def extract_subtitles(soup: BeautifulSoup, base: str) -> list[Candidate]:
    found: dict[str, Candidate] = {}

    def add(raw, *, lang=None, label=None):
        url = absolutize(base, raw)
        if not url or url in found:
            return
        ext = url_ext(url)
        lang_code = (lang or "").split("-")[0].lower() or None
        found[url] = Candidate(
            type="subtitle",
            url=url,
            mime_type=mime_from_ext(ext) or "text/vtt",
            language=(label or LANG_NAMES.get(lang_code or "", lang) or None),
            label=label,
        )

    for track in soup.find_all("track", src=True):
        kind = (track.get("kind") or "subtitles").lower()
        if kind in ("subtitles", "captions"):
            add(track["src"], lang=track.get("srclang"), label=track.get("label"))

    for a in soup.find_all("a", href=True):
        if url_ext(str(a["href"])) in SUBTITLE_EXT:
            add(a["href"], lang=a.get("hreflang"), label=None)

    return list(found.values())
