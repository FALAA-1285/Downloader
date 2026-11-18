from __future__ import annotations

import logging
import posixpath
import tempfile
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.api.deps import QueueDep, SessionDep, SettingsDep, rate_limit
from app.core.errors import AppError
from app.schemas.api import BatchZipRequest, CreateDownloadsRequest, DownloadJobOut
from app.services import download_service
from app.services.serializers import job_out
from app.workers.queue import DownloadQueue

router = APIRouter(prefix="/downloads", tags=["downloads"])
log = logging.getLogger(__name__)

QUEUE_UNAVAILABLE = "Antrean unduhan tidak tersedia. Coba lagi setelah layanan antrean berjalan."


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
    )
    for job in jobs:
        if not await _enqueue_or_fail(session, queue, job.id):
            await session.refresh(job)
    return [job_out(j) for j in jobs]


@router.get("/{job_id}", response_model=DownloadJobOut)
async def get_download(job_id: uuid.UUID, session: SessionDep) -> DownloadJobOut:
    return job_out(await download_service.get_job(session, job_id))


@router.post("/{job_id}/retry", response_model=DownloadJobOut)
async def retry_download(job_id: uuid.UUID, session: SessionDep, queue: QueueDep) -> DownloadJobOut:
    job = await download_service.retry_job(session, job_id)
    if not await _enqueue_or_fail(session, queue, job.id):
        await session.refresh(job)
    return job_out(job)


@router.get("/{job_id}/file", response_class=FileResponse)
async def download_file(job_id: uuid.UUID, session: SessionDep, settings: SettingsDep) -> FileResponse:
    """Menyajikan file hasil melalui endpoint terkontrol, bukan dari folder publik (NFR-01)."""
    servable = await download_service.get_servable_file(session, settings, job_id)
    file = servable.file
    ascii_name = file.filename.encode("ascii", "ignore").decode() or f"download.{file.extension}"
    return FileResponse(
        servable.path,
        media_type=file.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file.filename)}",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/zip", response_class=FileResponse)
async def download_batch_zip(
    body: BatchZipRequest, session: SessionDep, settings: SettingsDep
) -> FileResponse:
    """Mengemas beberapa file hasil unduhan menjadi satu file ZIP agar pengguna tidak perlu menyimpan satu per satu."""
    servables = []
    for jid in dict.fromkeys(body.job_ids):
        try:
            sf = await download_service.get_servable_file(session, settings, jid)
            servables.append(sf)
        except Exception as exc:
            log.debug("melewati job %s saat membuat zip: %s", jid, exc)
            continue

    if not servables:
        raise AppError("no_files", "Tidak ada file yang siap dikemas ke dalam ZIP.", 404)

    tmp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", dir=settings.temp_dir)
    tmp_zip_path = Path(tmp_zip.name)
    tmp_zip.close()

    used_names: set[str] = set()
    with zipfile.ZipFile(tmp_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sf in servables:
            fname = sf.file.filename
            base, ext = posixpath.splitext(fname) if "." in fname else (fname, f".{sf.file.extension}")
            arcname = fname
            counter = 1
            while arcname.lower() in used_names:
                arcname = f"{base}_{counter}{ext}"
                counter += 1
            used_names.add(arcname.lower())
            zf.write(sf.path, arcname=arcname)

    raw_name = body.zip_name or "media_downloads"
    zip_filename = f"{raw_name}.zip"
    ascii_name = zip_filename.encode("ascii", "ignore").decode() or "downloads.zip"

    return FileResponse(
        tmp_zip_path,
        media_type="application/zip",
        background=BackgroundTask(lambda: tmp_zip_path.unlink(missing_ok=True)),
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(zip_filename)}",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )
