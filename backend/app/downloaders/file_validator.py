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
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand == b"qt  ":
            return "mov"
        if brand in (b"M4A ", b"M4B "):
            return "m4a"
        return "mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm" if b"webm" in head[:64] else "mkv"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"fLaC"):
        return "flac"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] in (0xFB, 0xF3, 0xF2, 0xFA)):
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
    if "<svg" in lower and "<html" not in lower:
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
