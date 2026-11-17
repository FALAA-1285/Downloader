"""Parser dan konversi subtitle (FR-07): validasi SRT/VTT, konversi VTT ke SRT."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.errors import AppError

TIMING = re.compile(r"^\s*((?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3})")
KEEP_TAGS = re.compile(r"</?(?:i|b|u)>", re.I)
ANY_TAG = re.compile(r"<[^>]+>")


@dataclass
class Cue:
    start: float
    end: float
    text: str


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", "replace")


def _seconds(stamp: str) -> float:
    stamp = stamp.replace(",", ".")
    parts = stamp.split(":")
    if len(parts) == 2:
        parts.insert(0, "0")
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _srt_stamp(value: float) -> str:
    ms_total = round(value * 1000)
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def _clean_cue_text(text: str) -> str:
    kept: list[str] = []

    def stash(match: re.Match[str]) -> str:
        kept.append(match.group(0).lower())
        return f"\x00{len(kept) - 1}\x00"

    text = KEEP_TAGS.sub(stash, text)
    text = ANY_TAG.sub("", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ").strip()


def parse_cues(text: str) -> list[Cue]:
    """Parser blok untuk SRT dan WebVTT."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        head = lines[0].strip()
        if head.startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing_idx = next((i for i, ln in enumerate(lines[:2]) if TIMING.match(ln)), None)
        if timing_idx is None:
            continue
        match = TIMING.match(lines[timing_idx])
        assert match is not None
        start, end = _seconds(match.group(1)), _seconds(match.group(2))
        body = _clean_cue_text("\n".join(lines[timing_idx + 1 :]))
        if body and end >= start:
            cues.append(Cue(start, end, body))
    return cues


def validate_subtitle(data: bytes, kind: str) -> list[Cue] | None:
    """Memastikan file subtitle dapat dibaca. Mengembalikan cue untuk SRT/VTT."""
    text = decode_text(data)
    if kind in ("srt", "vtt"):
        cues = parse_cues(text)
        if not cues:
            raise AppError("invalid_subtitle", "File subtitle tidak berisi cue yang valid. File tidak disimpan.", 422)
        return cues
    if kind == "ass" and "[Events]" not in text:
        raise AppError("invalid_subtitle", "File subtitle ASS tidak memiliki bagian [Events].", 422)
    if kind == "ttml" and "<p" not in text:
        raise AppError("invalid_subtitle", "File subtitle TTML tidak berisi teks.", 422)
    return None


def cues_to_srt(cues: list[Cue]) -> str:
    blocks = [f"{n}\n{_srt_stamp(c.start)} --> {_srt_stamp(c.end)}\n{c.text}" for n, c in enumerate(cues, start=1)]
    return "\n\n".join(blocks) + "\n"


def vtt_to_srt(data: bytes) -> bytes:
    cues = parse_cues(decode_text(data))
    if not cues:
        raise AppError("invalid_subtitle", "Subtitle VTT tidak dapat dikonversi karena tidak berisi cue.", 422)
    return cues_to_srt(cues).encode("utf-8")
