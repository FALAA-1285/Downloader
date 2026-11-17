"""Validasi isi file berdasarkan magic bytes, bukan nama atau header sumber (NFR-01, PRD §13).

Hanya format dalam allowlist yang disimpan; file lain (termasuk executable) ditolak.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.errors import AppError


@dataclass(frozen=True)
class Kind:
    name: str
    mime: str
    ext: str


KINDS = {
    "jpeg": Kind("jpeg", "image/jpeg", "jpg"),
    "png": Kind("png", "image/png", "png"),
    "gif": Kind("gif", "image/gif", "gif"),
    "webp": Kind("webp", "image/webp", "webp"),
    "avif": Kind("avif", "image/avif", "avif"),
    "svg": Kind("svg", "image/svg+xml", "svg"),
    "mp4": Kind("mp4", "video/mp4", "mp4"),
    "mov": Kind("mov", "video/quicktime", "mov"),
    "webm": Kind("webm", "video/webm", "webm"),
    "mkv": Kind("mkv", "video/x-matroska", "mkv"),
    "ogg": Kind("ogg", "audio/ogg", "ogg"),
    "m4a": Kind("m4a", "audio/mp4", "m4a"),
    "mp3": Kind("mp3", "audio/mpeg", "mp3"),
    "aac": Kind("aac", "audio/aac", "aac"),
    "wav": Kind("wav", "audio/wav", "wav"),
    "flac": Kind("flac", "audio/flac", "flac"),
    "vtt": Kind("vtt", "text/vtt", "vtt"),
    "srt": Kind("srt", "application/x-subrip", "srt"),
    "ass": Kind("ass", "text/x-ssa", "ass"),
    "ttml": Kind("ttml", "application/ttml+xml", "ttml"),
}

ALLOWED = {
    "image": {"jpeg", "png", "gif", "webp", "avif", "svg"},
    "video": {"mp4", "mov", "webm", "mkv", "ogg"},
    "audio": {"mp3", "m4a", "ogg", "wav", "flac", "aac", "webm", "mp4"},
    "subtitle": {"vtt", "srt", "ass", "ttml"},
}

DETECTED_LABEL = {
    "html": "halaman HTML",
    "exe": "file executable",
    "zip": "arsip",
    "pdf": "dokumen PDF",
    None: "format tidak dikenal",
}

SRT_HEAD = re.compile(r"^\s*\d+\s*\r?\n\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->", re.M)


FTYP_BRANDS = {
    **dict.fromkeys(
        (
            b"isom",
            b"iso2",
            b"iso4",
            b"iso5",
            b"iso6",
            b"mp41",
            b"mp42",
            b"avc1",
            b"dash",
            b"mmp4",
            b"M4V ",
            b"M4VP",
            b"f4v ",
        ),
        "mp4",
    ),
    b"qt  ": "mov",
    b"M4A ": "m4a",
    b"M4B ": "m4a",
    b"avif": "avif",
    b"avis": "avif",
}

SVG_PROLOG = re.compile(r"^(?:\s+|<\?xml[^>]*\?>|<!--.*?-->|<!DOCTYPE[^>]*>)*", re.S | re.I)


def _is_mpeg_audio_frame(data: bytes) -> bool:
    """Frame sync MPEG audio layer III: 11 bit 1, versi bukan 'reserved', layer III."""
    return len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0 and (data[1] & 0x06) == 0x02


def _mp3_after_id3(head: bytes) -> str | None:
    """MP3 dengan tag ID3v2 harus diikuti frame MPEG audio, bukan konten lain (mis. playlist HLS)."""
    if len(head) < 10:
        return None
    size = (head[6] & 0x7F) << 21 | (head[7] & 0x7F) << 14 | (head[8] & 0x7F) << 7 | (head[9] & 0x7F)
    end = 10 + size + (10 if head[5] & 0x10 else 0)  # footer opsional
    if end + 2 > len(head):
        # Tag lebih besar dari potongan awal (mis. ada cover art). Isinya divalidasi ffprobe
        # dengan format_whitelist=mp3, sehingga konten lain tetap ditolak.
        return "mp3"
    return "mp3" if _is_mpeg_audio_frame(head[end:]) else None


def _svg_root(text: str) -> bool:
    """Elemen root dokumen harus <svg>, bukan HTML yang kebetulan memuat <svg>."""
    body = SVG_PROLOG.sub("", text[:4096], count=1)
    return body[:4].lower() == "<svg"


def detect(head: bytes) -> str | None:
    """Mendeteksi jenis file dari beberapa KB pertama."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[4:8] == b"ftyp":
        return FTYP_BRANDS.get(head[8:12])  # brand tak dikenal (mis. HEIC) → ditolak
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm" if b"webm" in head[:64] else "mkv"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"fLaC"):
        return "flac"
    if head.startswith(b"ID3"):
        return _mp3_after_id3(head)
    if _is_mpeg_audio_frame(head):
        return "mp3"
    if len(head) > 1 and head[0] == 0xFF and head[1] in (0xF1, 0xF9):
        return "aac"
    if head.startswith((b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe")):
        return "exe"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"%PDF"):
        return "pdf"

    text = head.decode("utf-8", "ignore").lstrip("﻿ \t\r\n")
    lower = text[:2048].lower()
    if text.startswith("WEBVTT"):
        return "vtt"
    if text.startswith("[Script Info]"):
        return "ass"
    if SRT_HEAD.match(text):
        return "srt"
    if _svg_root(text):
        return "svg"
    if "<tt" in lower and ("ttml" in lower or "w3.org/ns/ttml" in lower):
        return "ttml"
    if "<html" in lower or "<!doctype html" in lower:
        return "html"
    return None


def resolve_kind(head: bytes, media_type: str) -> Kind:
    detected = detect(head)
    if detected in ALLOWED.get(media_type, set()):
        kind = KINDS[detected]
        if media_type == "audio" and detected in ("webm", "mp4"):
            return Kind(detected, f"audio/{detected}", "webm" if detected == "webm" else "m4a")
        return kind
    label = {"image": "gambar", "video": "video", "audio": "audio", "subtitle": "subtitle"}.get(media_type, "media")
    found = DETECTED_LABEL.get(detected) or (KINDS[detected].ext.upper() if detected in KINDS else "format lain")
    raise AppError(
        "invalid_content",
        f"Isi file tidak sesuai dengan jenis {label} (terdeteksi: {found}). File tidak disimpan.",
        422,
    )
