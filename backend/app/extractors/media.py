"""Direct video, audio (FR-06) dan subtitle (FR-07) extractor."""

from __future__ import annotations

import re
from typing import Any

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
    parse_duration,
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

STREAM_EMBED_KEYWORDS = (
    "player",
    "embed",
    "video",
    "stream",
    "videonode",
    "playcdn",
    "fembed",
    "streamtape",
    "doodstream",
    "mixdrop",
    "hxfile",
    "vidsrc",
    "2embed",
    "superembed",
)


def _resolve_videonode_stream(embed_url: str) -> dict | None:
    """Mengekstrak file playlist HLS direct (.m3u8) dari pemutar videonode (LK21 / Layarkaca21)."""
    m = re.search(r"videonode\.de/iframe3/([^/]+)/([^/?#]+)", embed_url)
    if not m:
        return None
    host, vid_id = m.group(1), m.group(2)
    req_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": embed_url,
    }
    try:
        import httpx

        with httpx.Client(headers=req_headers, timeout=5.0) as cl:
            resp = cl.post("https://videonode.de/api.php", data={"host": host, "id": vid_id})
            if resp.status_code != 200:
                return None
            data = resp.json()
            play_url = data.get("embedUrl")
            if not play_url:
                return None
            slug = play_url.split("?")[0].split("/")[-1]
            verify_url = f"https://playcdn.de/verify/{slug}"
            resp2 = cl.get(verify_url, headers={"Referer": play_url, "X-Requested-With": "XMLHttpRequest"})
            if resp2.status_code == 200:
                data2 = resp2.json()
                if data2.get("fileUrl"):
                    return {
                        "stream_url": data2["fileUrl"],
                        "title": data2.get("title"),
                        "poster": data2.get("poster"),
                        "server": host,
                    }
    except Exception:  # noqa: BLE001, S110
        pass
    return None


_TRAILER_RE = re.compile(r"\b(trailer|teaser|cuplikan)\b", re.I)


def _is_trailer(label: str | None) -> bool:
    """Trailer/teaser tidak boleh mewarisi durasi film dari metadata halaman."""
    return bool(label and _TRAILER_RE.search(label))


def _extract_ldjson_videos(
    data: Any,
    base: str,
    add_fn: Any,
    player_urls: list[tuple[str, str | None]],
    page_durations: list[float] | None = None,
) -> None:
    def _handle_url(v_url: str, name: str | None, thumb: str | None, dur: float | None = None) -> None:
        url = absolutize(base, v_url)
        if not url:
            return
        is_embed = any(h in url.lower() for h in EMBED_HOSTS) or any(k in url.lower() for k in STREAM_EMBED_KEYWORDS)
        if is_embed:
            player_urls.append((url, name))
        else:
            add_fn(url, default="video", poster=thumb, label=name, duration=dur)

    if isinstance(data, dict):
        dur = parse_duration(data.get("duration"))
        if dur and page_durations is not None:
            page_durations.append(dur)

        typ = str(data.get("@type", ""))
        if typ == "VideoObject" or "VideoObject" in typ:
            v_url = data.get("contentUrl") or data.get("embedUrl")
            if v_url:
                name = data.get("name") or data.get("description")
                thumb = data.get("thumbnailUrl") or data.get("thumbnail")
                if isinstance(thumb, list) and thumb:
                    thumb = thumb[0]
                _handle_url(v_url, name, thumb, dur)

        for k, val in data.items():
            if k in ("trailer", "video") and isinstance(val, dict):
                v_url = val.get("contentUrl") or val.get("embedUrl")
                if v_url:
                    name = val.get("name") or val.get("description")
                    thumb = val.get("thumbnailUrl") or val.get("thumbnail")
                    if isinstance(thumb, list) and thumb:
                        thumb = thumb[0]
                    # Durasi induk (mis. Movie) adalah durasi film, bukan durasi trailer.
                    v_dur = parse_duration(val.get("duration"))
                    _handle_url(v_url, name, thumb, v_dur)
            elif isinstance(val, (dict, list)):
                _extract_ldjson_videos(val, base, add_fn, player_urls, page_durations)
    elif isinstance(data, list):
        for item in data:
            _extract_ldjson_videos(item, base, add_fn, player_urls, page_durations)


def _extract_ldjson_subtitles(data: Any, base: str, add_fn: Any) -> None:
    if isinstance(data, dict):
        for k in ("subtitle", "subtitles", "caption", "captions"):
            val = data.get(k)
            if isinstance(val, str) and val.startswith(("http://", "https://", "/")):
                add_fn(val)
            elif isinstance(val, dict):
                s_url = val.get("url") or val.get("@id") or val.get("src")
                if s_url:
                    add_fn(s_url, lang=val.get("language") or val.get("inLanguage"), label=val.get("name"))
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.startswith(("http://", "https://", "/")):
                        add_fn(item)
                    elif isinstance(item, dict):
                        s_url = item.get("url") or item.get("@id") or item.get("src")
                        if s_url:
                            add_fn(s_url, lang=item.get("language") or item.get("inLanguage"), label=item.get("name"))
        for val in data.values():
            if isinstance(val, (dict, list)):
                _extract_ldjson_subtitles(val, base, add_fn)
    elif isinstance(data, list):
        for item in data:
            _extract_ldjson_subtitles(item, base, add_fn)

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

    page_durations: list[float] = []
    for meta_name in ("video:duration", "og:video:duration", "music:duration", "duration"):
        val = meta_content(soup, meta_name)
        if val:
            d = parse_duration(val)
            if d:
                page_durations.append(d)
                break
    for tag in soup.find_all(attrs={"itemprop": "duration"}):
        dt = tag.get("datetime") or tag.get("content") or tag.get_text(strip=True)
        if dt:
            d = parse_duration(dt)
            if d:
                page_durations.append(d)
                break

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
        dur = duration or (page_durations[0] if page_durations and not _is_trailer(label) else None)
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
            duration=dur,
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

    # Deteksi URL stream HLS/DASH mentah di dalam tag <script>
    for script in soup.find_all("script"):
        txt = script.string or ""
        if not txt or len(txt) > 200_000:
            continue
        for m in re.finditer(r'(https?://[^\s"\'<>]+\.(?:m3u8|mpd))', txt):
            raw_url = m.group(1)
            add(raw_url, default="video", label="Embedded Stream (HLS/DASH)")

    # Kumpulkan kandidat URL player dari iframe dan elemen opsi player
    player_urls: list[tuple[str, str | None]] = []

    # Deteksi VideoObject di dalam tag <script type="application/ld+json">
    for script in soup.find_all("script", type=re.compile(r"application/(?:ld\+)?json", re.I)):
        txt = script.string or ""
        if not txt or len(txt) > 500_000:
            continue
        try:
            import json

            data = json.loads(txt)
            _extract_ldjson_videos(data, base, add, player_urls, page_durations)
        except Exception:
            pass
    for iframe in soup.find_all("iframe"):
        raw = iframe.get("src") or iframe.get("data-src") or iframe.get("data-url")
        url = absolutize(base, raw)
        if url:
            lbl = iframe.get("title") or iframe.get("name")
            player_urls.append((url, lbl))

    for el in soup.find_all(["a", "option", "button"], attrs={"data-url": True}):
        url = absolutize(base, el["data-url"])
        if url:
            txt = el.get_text(" ", strip=True) or el.get("data-server")
            player_urls.append((url, txt))

    for opt in soup.find_all("option", value=True):
        val = opt["value"].strip()
        if val.startswith(("http://", "https://")):
            url = absolutize(base, val)
            if url:
                player_urls.append((url, opt.get_text(" ", strip=True)))

    page_dur = page_durations[0] if page_durations else None
    for url, label in player_urls:
        if not url or url in found:
            continue
        try:
            host = re.sub(r"^www\.", "", url.split("/")[2].lower())
        except IndexError:
            continue

        if "videonode.de" in host:
            resolved = _resolve_videonode_stream(url)
            if resolved and resolved.get("stream_url"):
                s_url = resolved["stream_url"]
                if s_url not in found:
                    found[s_url] = Candidate(
                        type="video",
                        url=s_url,
                        mime_type="video/mp4",
                        downloadable=True,
                        reason=None,
                        preview_url=resolved.get("poster"),
                        label=f"{resolved.get('title') or 'Movie'} ({resolved.get('server', 'p2p').upper()} - HLS Stream)",
                        duration=page_dur,
                        probe=False,
                        options={"downloader": "yt-dlp"},
                    )
                continue

        platform = next((name for h, name in EMBED_HOSTS.items() if host == h or host.endswith("." + h)), None)
        is_player_embed = (
            platform is not None
            or any(k in host for k in STREAM_EMBED_KEYWORDS)
            or any(k in url.lower() for k in STREAM_EMBED_KEYWORDS)
        )
        if is_player_embed:
            name = platform or host.split(".")[0].capitalize()
            found[url] = Candidate(
                type="video",
                url=url,
                mime_type="video/mp4",
                downloadable=True,
                reason=None,
                label=f"{label or name} Player Video.mp4",
                duration=None if _is_trailer(label) else page_dur,
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

    # Deteksi subtitle di dalam tag <script type="application/ld+json">
    for script in soup.find_all("script", type=re.compile(r"application/(?:ld\+)?json", re.I)):
        txt = script.string or ""
        if not txt or len(txt) > 500_000:
            continue
        try:
            import json

            data = json.loads(txt)
            _extract_ldjson_subtitles(data, base, add)
        except Exception:
            pass

    return list(found.values())
