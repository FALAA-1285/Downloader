"""Opsi yt-dlp bersama untuk analisis dan unduhan.

- Semua koneksi yt-dlp (dan ffmpeg yang dipanggilnya) lewat proxy penjaga SSRF (C-01).
- Cookie ditulis sebagai cookies.txt sementara (izin 0600, di folder temp aplikasi) sehingga
  yt-dlp menerapkan pencocokan domain sendiri; cookie tidak pernah dipasang sebagai header global.
- Header kustom yang sensitif (Authorization, X-*) tidak diteruskan karena yt-dlp mengirim
  `http_headers` ke semua host, termasuk CDN pihak ketiga (C-03).
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.core.cookies import NON_SENSITIVE_HEADERS, parse_cookies, to_netscape


@contextlib.contextmanager
def cookiefile(raw: str | None, source_url: str, temp_dir: Path) -> Iterator[str | None]:
    """cookies.txt sementara untuk yt-dlp; selalu dihapus setelah dipakai."""
    cookies = parse_cookies(raw, source_url)
    if not cookies:
        yield None
        return
    temp_dir.mkdir(parents=True, exist_ok=True)
    path = temp_dir / f"cookies-{uuid.uuid4().hex}.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(to_netscape(cookies))
        yield str(path)
    finally:
        with contextlib.suppress(OSError):
            path.unlink()


def safe_headers(headers: dict[str, str] | None, referer: str | None = None) -> dict[str, str]:
    out = {k: v for k, v in (headers or {}).items() if k.lower() in NON_SENSITIVE_HEADERS}
    if referer and not any(k.lower() == "referer" for k in out):
        out["Referer"] = referer
    return out


def base_options(proxy_url: str, *, headers: dict[str, str], cookie_path: str | None) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "no_color": True,
        "noprogress": True,
        "noplaylist": True,
        "proxy": proxy_url,
        # Unduhan HLS/DASH lewat downloader Python agar selalu melewati proxy penjaga.
        "external_downloader": {"default": "native"},
        "http_headers": headers,
    }
    if cookie_path:
        opts["cookiefile"] = cookie_path
    return opts
