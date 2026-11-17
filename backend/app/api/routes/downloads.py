from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, status
from fastapi.responses import FileResponse

from app.api.deps import QueueDep, SessionDep, SettingsDep, rate_limit
from app.core.errors import AppError
from app.models.models import aware, utcnow
from app.schemas.api import CreateDownloadsRequest, DownloadJobOut
from app.services import download_service
from app.services.serializers import job_out

router = APIRouter(prefix="/downloads", tags=["downloads"])


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
    jobs = await download_service.create_jobs(session, settings, body.analysis_id, body.media_ids, body.subtitle_format)
    out = [job_out(j) for j in jobs]
    for job in jobs:
        await queue.enqueue(job.id)
    return out


@router.get("/{job_id}", response_model=DownloadJobOut)
async def get_download(job_id: uuid.UUID, session: SessionDep) -> DownloadJobOut:
    return job_out(await download_service.get_job(session, job_id))


@router.post("/{job_id}/retry", response_model=DownloadJobOut)
async def retry_download(job_id: uuid.UUID, session: SessionDep, queue: QueueDep) -> DownloadJobOut:
    job = await download_service.retry_job(session, job_id)
    await queue.enqueue(job.id)
    return job_out(job)


@router.get("/{job_id}/file", response_class=FileResponse)
async def download_file(job_id: uuid.UUID, session: SessionDep, settings: SettingsDep) -> FileResponse:
    """Menyajikan file hasil melalui endpoint terkontrol, bukan dari folder publik (NFR-01)."""
    job = await download_service.get_job(session, job_id)
    file = job.file
    if job.status != "completed" or file is None:
        raise AppError("file_not_ready", "File belum tersedia untuk pekerjaan ini.", 409)
    expires = aware(file.expires_at)
    if file.deleted_at is not None or (expires is not None and expires < utcnow()):
        raise AppError(
            "file_expired", "File sudah kedaluwarsa dan dihapus dari server. Unduh ulang dari URL sumber.", 410
        )
    path = download_service.safe_storage_path(settings, file.storage_key)
    if not path.is_file():
        raise AppError("file_missing", "File tidak ditemukan di penyimpanan server.", 410)

    ascii_name = file.filename.encode("ascii", "ignore").decode() or f"download.{file.extension}"
    return FileResponse(
        path,
        media_type=file.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file.filename)}",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )
