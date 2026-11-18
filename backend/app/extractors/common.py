"""Utilitas bersama untuk extractor."""

from __future__ import annotations

import hashlib
import posixpath
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "webp", "svg", "avif"}
VIDEO_EXT = {"mp4", "webm", "mov", "m4v", "ogv", "mkv"}
AUDIO_EXT = {"mp3", "m4a", "ogg", "oga", "wav", "flac", "aac", "opus"}
SUBTITLE_EXT = {"srt", "vtt", "ass", "ssa", "ttml", "dfxp"}
STREAM_EXT = {"m3u8", "mpd"}

EXT_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "avif": "image/avif",
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "ogv": "video/ogg",
    "mkv": "video/x-matroska",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "opus": "audio/opus",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "ass": "text/x-ssa",
    "ssa": "text/x-ssa",
    "ttml": "application/ttml+xml",
    "dfxp": "application/ttml+xml",
    "m3u8": "application/vnd.apple.mpegurl",
    "mpd": "application/dash+xml",
}

STREAM_REASON = (
    "Streaming adaptif (HLS/DASH) belum didukung. Aplikasi tidak memproses manifest streaming "
    "atau konten yang dilindungi DRM."
)

ID_PREFIX = {"image": "img", "video": "vid", "audio": "aud", "subtitle": "sub"}


@dataclass
class Candidate:
    type: str
    url: str
    mime_type: str | None = None
    size: int | None = None
    downloadable: bool = True
    reason: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    language: str | None = None
    label: str | None = None
    preview_url: str | None = None
    probe: bool = True
    options: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.mime_type:
            ext = url_ext(self.url)
            self.mime_type = mime_from_ext(ext) or (
                "video/mp4" if self.type == "video" else ("audio/mpeg" if self.type == "audio" else None)
            )

    @property
    def id(self) -> str:
        digest = hashlib.sha1(f"{self.type}|{self.url}".encode(), usedforsecurity=False).hexdigest()[:12]
        return f"{ID_PREFIX.get(self.type, 'med')}-{digest}"

    @property
    def filename(self) -> str:
        return filename_from_url(self.url, self.type, self.label)


def absolutize(base: str, ref: str | None) -> str | None:
    """URL absolut http(s) tanpa fragment, atau None untuk data:, blob:, javascript:, dll."""
    if not ref:
        return None
    ref = ref.strip()
    if not ref or ref.startswith(("data:", "blob:", "javascript:", "about:", "mailto:", "#")):
        return None
    try:
        absolute = urljoin(base, ref)
        parts = urlsplit(absolute)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def url_ext(url: str) -> str | None:
    path = urlsplit(url).path
    _, ext = posixpath.splitext(unquote(path))
    ext = ext.lower().lstrip(".")
    return ext if 0 < len(ext) <= 5 else None


def mime_from_ext(ext: str | None) -> str | None:
    return EXT_MIME.get(ext or "")


_UNSAFE = re.compile(r"[^\w.\-]+", re.UNICODE)


def sanitize_filename(name: str, fallback: str = "file") -> str:
    name = unquote(name).replace("\\", "/").split("/")[-1]
    name = _UNSAFE.sub("-", name).strip(".-_ ")
    name = re.sub(r"-{2,}", "-", name)
    name = re.sub(r"-+\.", ".", name)
    return (name or fallback)[:120]


def filename_from_url(url: str, media_type: str, label: str | None = None) -> str:
    clean_label = sanitize_filename(label or "", fallback="")
    base = posixpath.basename(urlsplit(url).path)
    name = sanitize_filename(base, fallback="")
    generic_names = {"-", "index", "0.m3u8", "0", "player", "embed", "watch", "video", "play", "stream"}
    if not name or name.lower() in generic_names or (clean_label and "." not in name):
        if clean_label:
            ext = ".mp4" if media_type == "video" else (".mp3" if media_type == "audio" else (".vtt" if media_type == "subtitle" else ""))
            name = clean_label if "." in clean_label else f"{clean_label}{ext}"
        else:
            name = media_type

    if "." not in name:
        default_ext = {
            "video": ".mp4",
            "audio": ".mp3",
            "image": ".jpg",
            "subtitle": ".vtt",
        }.get(media_type, "")
        name = f"{name}{default_ext}"
    return name


def parse_duration(value: object) -> float | None:
    """Konversi durasi (detik, ISO 8601 seperti PT137M / PT2H17M, atau jam:menit:detik) ke detik (float)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    val_str = str(value).strip()
    if not val_str:
        return None
    try:
        sec = float(val_str)
        return sec if sec > 0 else None
    except ValueError:
        pass
    iso_match = re.match(
        r"^P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?$",
        val_str,
        re.I,
    )
    if iso_match:
        parts = iso_match.groupdict()
        days = float(parts.get("days") or 0)
        hours = float(parts.get("hours") or 0)
        minutes = float(parts.get("minutes") or 0)
        seconds = float(parts.get("seconds") or 0)
        total = days * 86400 + hours * 3600 + minutes * 60 + seconds
        return total if total > 0 else None
    clock_parts = val_str.split(":")
    if len(clock_parts) in (2, 3) and all(p.isdigit() for p in clock_parts):
        if len(clock_parts) == 2:
            return float(int(clock_parts[0]) * 60 + int(clock_parts[1]))
        return float(int(clock_parts[0]) * 3600 + int(clock_parts[1]) * 60 + int(clock_parts[2]))
    return None


def parse_int(value: object) -> int | None:
    if value is None:
        return None
    match = re.match(r"\s*(\d{1,6})", str(value))
    return int(match.group(1)) if match else None


def parse_srcset(srcset: str | None) -> list[tuple[str, float]]:
    """Mengembalikan [(url, bobot)], bobot = lebar (w) atau kerapatan (x)."""
    if not srcset:
        return []
    out: list[tuple[str, float]] = []
    for part in re.split(r",\s+(?=\S)", srcset.strip()):
        bits = part.strip().split()
        if not bits:
            continue
        weight = 1.0
        if len(bits) > 1:
            desc = bits[-1]
            try:
                if desc.endswith("w"):
                    weight = float(desc[:-1])
                elif desc.endswith("x"):
                    weight = float(desc[:-1]) * 1000
            except ValueError:
                weight = 1.0
        out.append((bits[0], weight))
    return out


def best_from_srcset(srcset: str | None) -> str | None:
    items = parse_srcset(srcset)
    return max(items, key=lambda i: i[1])[0] if items else None


def meta_content(soup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return None
