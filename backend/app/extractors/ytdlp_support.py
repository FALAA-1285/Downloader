"""Deteksi URL yang dikenali extractor khusus yt-dlp (bukan extractor `generic`)."""

from __future__ import annotations

import functools
import logging
import threading
from typing import Any

log = logging.getLogger(__name__)

_EXTRACTORS: list[Any] | None = None
_LOCK = threading.Lock()


def _extractor_classes() -> list[Any]:
    global _EXTRACTORS
    if _EXTRACTORS is None:
        with _LOCK:
            if _EXTRACTORS is None:
                import yt_dlp

                _EXTRACTORS = [ie for ie in yt_dlp.extractor.gen_extractor_classes() if ie.IE_NAME != "generic"]
    return _EXTRACTORS


@functools.lru_cache(maxsize=2048)
def is_ytdlp_supported(url: str) -> tuple[bool, str | None]:
    """Apakah URL cocok dengan salah satu extractor khusus yt-dlp (YouTube, Vimeo, dll.)."""
    try:
        for ie in _extractor_classes():
            if ie.suitable(url):
                return True, ie.IE_NAME
    except Exception as exc:  # noqa: BLE001 - extractor pihak ketiga; anggap tidak didukung
        log.debug("Gagal memeriksa dukungan yt-dlp untuk %s: %s", url, exc)
    return False, None
