from __future__ import annotations

import asyncio
import logging
import posixpath
import re
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Query, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.api.deps import QueueDep, SessionDep, SessionFactoryDep, SettingsDep, rate_limit
from app.core.errors import AppError
from app.extractors.common import sanitize_filename
from app.schemas.api import BatchZipOut, BatchZipRequest, CreateDownloadsRequest, DownloadJobOut, JobStatusRequest
from app.services import download_service
from app.services.download_runner import check_storage_capacity
from app.services.serializers import job_out
from app.workers.queue import DownloadQueue

router = APIRouter(prefix="/downloads", tags=["downloads"])
log = logging.getLogger(__name__)

QUEUE_UNAVAILABLE = "Antrean unduhan tidak tersedia. Coba lagi setelah layanan antrean berjalan."
ZIP_ID = re.compile(r"^[0-9a-f]{32}$")
FILE_HEADERS = {"Content-Security-Policy": "default-src 'none'; sandbox", "Cache-Control": "private, no-store"}


def _disposition(filename: str, fallback: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "") or fallback
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


async def _enqueue_or_fail(session: SessionDep, queue: DownloadQueue, job_id: uuid.UUID) -> bool:
    """Job yang gagal masuk antrean langsung ditandai gagal agar tidak tertinggal sebagai `pending`."""
    try:
        await queue.enqueue(job_id)
        return True
    except Exception:
        log.exception("gagal memasukkan job %s ke antrean", job_id)
        await download_service.mark_failed(session, job_id, QUEUE_UNAVAILABLE)
        return False


@router.post(
    "",
    response_model=list[DownloadJobOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limit("downloads", "rate_limit_downloads_per_minute")],
)
async def create_downloads(
    body: CreateDownloadsRequest, session: SessionDep, settings: SettingsDep, queue: QueueDep
) -> list[DownloadJobOut]:
    """Membuat pekerjaan unduhan dari media hasil analisis (FR-08)."""
    jobs = await download_service.create_jobs(
        session,
        settings,
        body.analysis_id,
        body.media_ids,
        body.subtitle_format,
        cookies=body.cookies,
        headers=body.headers,
        scheduled_at=body.scheduled_at,
        max_speed_kbps=body.max_speed_kbps,
    )
    for job in jobs:
        # Job terjadwal diantrekan oleh penjadwal saat waktunya tiba.
        if job.status == "pending" and not await _enqueue_or_fail(session, queue, job.id):
            await session.refresh(job)
    return [job_out(j) for j in jobs]


@router.post("/status", response_model=list[DownloadJobOut])
async def jobs_status(body: JobStatusRequest, session: SessionDep) -> list[DownloadJobOut]:
    """Status banyak job dalam satu request (dipakai polling progres frontend)."""
    return [job_out(j) for j in await download_service.get_jobs(session, body.ids)]


@router.post("/zip", response_model=BatchZipOut, status_code=status.HTTP_201_CREATED)
async def create_batch_zip(
    body: BatchZipRequest, session: SessionDep, sessions: SessionFactoryDep, settings: SettingsDep
) -> BatchZipOut:
    """Mengemas file hasil unduhan menjadi satu ZIP di server (H-05).

    ZIP dibuat di thread terpisah (event loop tetap melayani request lain) tanpa kompresi ulang
    — media sudah terkompresi — lalu diunduh lewat `GET /downloads/zip/{id}` sehingga browser
    bisa menyimpannya langsung ke disk tanpa memuat seluruh isi ke memori.
    """
    servables: list[download_service.ServableFile] = []
    skipped = 0
    for jid in dict.fromkeys(body.job_ids):
        try:
            servables.append(await download_service.get_servable_file(session, settings, jid))
        except AppError as exc:
            skipped += 1
            log.debug("melewati job %s saat membuat zip: %s", jid, exc.code)
    if not servables:
        raise AppError("no_files", "Tidak ada file yang siap dikemas ke dalam ZIP.", 404)

    total = sum(sf.file.file_size or 0 for sf in servables)
    if total > settings.max_zip_bytes:
        raise AppError(
            "zip_too_large",
            f"Total ukuran file ({total / 1_048_576:.0f} MB) melebihi batas ZIP {settings.max_zip_size_mb} MB. "
            "Pilih lebih sedikit file.",
            413,
        )
    await check_storage_capacity(sessions, settings, incoming=total, exclude=None)

    zip_id = uuid.uuid4().hex
    zip_path = settings.temp_dir / f"zip-{zip_id}.zip"
    entries = [(sf.path, sf.file.filename, sf.file.extension) for sf in servables]
    try:
        await asyncio.to_thread(_build_zip, zip_path, entries)
    except OSError as exc:
        await asyncio.to_thread(zip_path.unlink, missing_ok=True)
        raise AppError("zip_failed", "Gagal membuat file ZIP di server.", 500) from exc

    name = sanitize_filename(body.zip_name or "media_downloads", fallback="media_downloads")
    size = await asyncio.to_thread(lambda: zip_path.stat().st_size)
    return BatchZipOut(id=zip_id, filename=f"{name}.zip", size=size, file_count=len(entries), skipped=skipped)


@router.get("/zip/{zip_id}", response_class=FileResponse)
async def download_batch_zip(
    zip_id: str, settings: SettingsDep, name: str = Query(default="media_downloads", max_length=100)
) -> FileResponse:
    """Menyajikan ZIP yang sudah dibuat lalu menghapusnya setelah terkirim."""
    if not ZIP_ID.fullmatch(zip_id):
        raise AppError("zip_not_found", "File ZIP tidak ditemukan.", 404)
    zip_path = settings.temp_dir / f"zip-{zip_id}.zip"
    if not await asyncio.to_thread(zip_path.is_file):
        raise AppError("zip_not_found", "File ZIP tidak ditemukan atau sudah diunduh.", 404)
    filename = sanitize_filename(name.removesuffix(".zip"), fallback="media_downloads") + ".zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        background=BackgroundTask(_unlink, zip_path),
        headers={"Content-Disposition": _disposition(filename, "downloads.zip"), **FILE_HEADERS},
    )


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


def _build_zip(zip_path: Path, entries: list[tuple[Path, str, str]]) -> None:
    used_names: set[str] = set()
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for path, fname, extension in entries:
            base, ext = posixpath.splitext(fname) if "." in fname else (fname, f".{extension}")
            arcname = fname
            counter = 1
            while arcname.lower() in used_names:
                arcname = f"{base}_{counter}{ext}"
                counter += 1
            used_names.add(arcname.lower())
            zf.write(path, arcname=arcname)


@router.get("/{job_id}", response_model=DownloadJobOut)
async def get_download(job_id: uuid.UUID, session: SessionDep) -> DownloadJobOut:
    return job_out(await download_service.get_job(session, job_id))


@router.post("/{job_id}/retry", response_model=DownloadJobOut)
async def retry_download(job_id: uuid.UUID, session: SessionDep, queue: QueueDep) -> DownloadJobOut:
    job = await download_service.retry_job(session, job_id)
    if not await _enqueue_or_fail(session, queue, job.id):
        await session.refresh(job)
    return job_out(job)


@router.post("/{job_id}/pause", response_model=DownloadJobOut)
async def pause_download(job_id: uuid.UUID, session: SessionDep) -> DownloadJobOut:
    return job_out(await download_service.pause_job(session, job_id))


@router.post("/{job_id}/resume", response_model=DownloadJobOut)
async def resume_download(job_id: uuid.UUID, session: SessionDep, queue: QueueDep) -> DownloadJobOut:
    job = await download_service.resume_job(session, job_id)
    if not await _enqueue_or_fail(session, queue, job.id):
        await session.refresh(job)
    return job_out(job)


@router.post("/{job_id}/cancel", response_model=DownloadJobOut)
async def cancel_download(job_id: uuid.UUID, session: SessionDep, settings: SettingsDep) -> DownloadJobOut:
    return job_out(await download_service.cancel_job(session, settings, job_id))


@router.get("/{job_id}/file", response_class=FileResponse)
async def download_file(job_id: uuid.UUID, session: SessionDep, settings: SettingsDep) -> FileResponse:
    """Menyajikan file hasil melalui endpoint terkontrol, bukan dari folder publik (NFR-01)."""
    servable = await download_service.get_servable_file(session, settings, job_id)
    file = servable.file
    return FileResponse(
        servable.path,
        media_type=file.mime_type,
        headers={"Content-Disposition": _disposition(file.filename, f"download.{file.extension}"), **FILE_HEADERS},
    )
