"""Pemeriksaan ketersediaan media hasil ekstraksi (FR-04, FR-06).

Setiap item diperiksa dengan HEAD (fallback GET Range 0-0) secara paralel terbatas,
dalam anggaran waktu tertentu. Kegagalan satu item hanya menandai item itu (NFR-03).
"""

from __future__ import annotations

import asyncio
import re

import httpx

from app.core.config import Settings
from app.core.cookies import Cookie
from app.core.errors import AppError, UnsafeURLError
from app.core.http_client import open_stream

from .common import Candidate

TYPE_LABEL = {"image": "Gambar", "video": "Video", "audio": "Audio", "subtitle": "Subtitle"}
ACCEPTABLE_MIME = {
    "image": ("image/",),
    "video": ("video/", "application/octet-stream", "binary/octet-stream", "application/mp4"),
    "audio": ("audio/", "application/octet-stream", "binary/octet-stream", "application/ogg"),
    "subtitle": (
        "text/",
        "application/x-subrip",
        "application/ttml",
        "application/octet-stream",
        "binary/octet-stream",
    ),
}


def _total_from_content_range(value: str | None) -> int | None:
    match = re.search(r"/(\d+)\s*$", value or "")
    return int(match.group(1)) if match else None


async def _probe_one(
    client: httpx.AsyncClient,
    item: Candidate,
    settings: Settings,
    referer: str | None = None,
    cookies: list[Cookie] | None = None,
) -> None:
    label = TYPE_LABEL.get(item.type, "Media")
    base_headers = {"Referer": referer} if referer else {}
    for method, extra_headers in (("HEAD", None), ("GET", {"Range": "bytes=0-0"})):
        headers = dict(base_headers)
        if extra_headers:
            headers.update(extra_headers)
        async with open_stream(client, item.url, settings, method=method, headers=headers or None, cookies=cookies) as (
            resp,
            _final,
        ):
            if method == "HEAD" and resp.status_code in (403, 405, 501):
                continue  # sebagian server menolak HEAD
            if resp.status_code >= 400:
                item.downloadable = False
                item.reason = f"{label} tidak dapat diakses (HTTP {resp.status_code})."
                return
            mime = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            if mime.startswith("text/html"):
                item.downloadable = False
                item.reason = f"Tautan mengarah ke halaman web, bukan file {label.lower()}."
                return
            if mime and not mime.startswith(ACCEPTABLE_MIME.get(item.type, ())):
                item.downloadable = False
                item.reason = f"Tipe konten {mime} tidak sesuai untuk {label.lower()}."
                return
            if mime and not mime.endswith("octet-stream"):
                item.mime_type = mime
            if resp.status_code == 206:
                item.size = _total_from_content_range(resp.headers.get("content-range"))
            elif resp.headers.get("content-length", "").isdigit() and resp.headers.get(
                "content-encoding", "identity"
            ).lower() in ("", "identity"):
                item.size = int(resp.headers["content-length"])
            if item.size is not None and item.size > settings.max_download_bytes:
                item.downloadable = False
                item.reason = f"Ukuran file melebihi batas {settings.max_download_size_mb} MB yang diizinkan."
            return


async def probe_candidates(
    client: httpx.AsyncClient,
    items: list[Candidate],
    settings: Settings,
    referer: str | None = None,
    cookies: list[Cookie] | None = None,
) -> list[str]:
    """Memeriksa item secara in-place. Mengembalikan peringatan."""
    targets = [i for i in items if i.probe and i.downloadable][: settings.probe_limit]
    skipped = sum(1 for i in items if i.probe and i.downloadable) - len(targets)
    semaphore = asyncio.Semaphore(settings.probe_concurrency)

    async def guarded(item: Candidate) -> None:
        async with semaphore:
            try:
                await _probe_one(client, item, settings, referer=referer, cookies=cookies)
            except UnsafeURLError:
                item.downloadable = False
                item.reason = "Alamat media mengarah ke jaringan internal dan diblokir."
            except AppError as exc:
                item.downloadable = False
                item.reason = exc.message
            except Exception:  # noqa: BLE001 - satu item gagal tidak boleh menggagalkan analisis
                item.downloadable = False
                item.reason = "Media tidak dapat diperiksa."

    warnings: list[str] = []
    if not targets:
        return warnings
    tasks = [asyncio.create_task(guarded(i)) for i in targets]
    _done, pending = await asyncio.wait(tasks, timeout=settings.probe_budget_seconds)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
        warnings.append(f"{len(pending)} media belum selesai diperiksa; ketersediaannya akan dicek saat diunduh.")
    if skipped > 0:
        warnings.append(f"{skipped} media tidak diperiksa karena batas jumlah pemeriksaan.")
    return warnings
