"""Pembuatan dan pengelolaan pekerjaan unduhan (FR-08, FR-09)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.url_guard import redact_url, validate_url
from app.extractors.common import sanitize_filename
from app.models.models import Analysis, DownloadFile, DownloadHistory, DownloadJob, aware, utcnow

# Status yang sedang dikerjakan worker. `pending` tidak termasuk: job antre boleh dihapus,
# dan runner akan melewatinya karena klaim atomiknya gagal.
RUNNING_STATUSES = ("processing", "downloading")

log = logging.getLogger(__name__)


async def create_jobs(
    session: AsyncSession,
    settings: Settings,
    analysis_id: uuid.UUID,
    media_ids: list[str],
    subtitle_format: str,
) -> list[DownloadJob]:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None or aware(analysis.expires_at) < utcnow():
        raise AppError("analysis_expired", "Hasil analisis sudah kedaluwarsa. Analisis ulang URL tersebut.", 404)

    items = {m["id"]: m for m in analysis.result.get("media", [])}
    jobs: list[DownloadJob] = []
    for media_id in dict.fromkeys(media_ids):
        item = items.get(media_id)
        if item is None:
            raise AppError("media_not_found", "Media yang dipilih tidak ada di hasil analisis.", 404)
        if not item.get("downloadable"):
            raise AppError(
                "media_not_downloadable",
                f"{item.get('filename')} tidak dapat diunduh: {item.get('reason') or 'tidak tersedia'}",
                422,
            )
        # Validasi ulang sumber sebelum membuat pekerjaan (PRD §7.2 langkah 3).
        validate_url(item["url"], settings.port_allowlist)
        options = {"subtitle_format": subtitle_format} if item["type"] == "subtitle" else None
        job = DownloadJob(
            analysis_id=analysis.id,
            media_id=media_id,
            source_url=analysis.source_url,
            media_url=item["url"],
            source_domain=analysis.source_domain,
            platform=analysis.platform,
            media_type=item["type"],
            filename=sanitize_filename(item.get("filename") or item["type"], fallback=item["type"]),
            size_total=item.get("size"),
            options=options,
            status="pending",
        )
        session.add(job)
        jobs.append(job)

    await session.flush()
    for job in jobs:
        session.add(DownloadHistory(job_id=job.id, action="created", details={"media_url": redact_url(job.media_url)}))
    await session.commit()
    for job in jobs:
        await session.refresh(job, attribute_names=["file"])
    return jobs


def history_query(
    status: str | None = None, media_type: str | None = None, q: str | None = None
) -> Select[tuple[DownloadJob]]:
    stmt = select(DownloadJob).order_by(DownloadJob.created_at.desc())
    if status:
        stmt = stmt.where(DownloadJob.status == status)
    if media_type:
        stmt = stmt.where(DownloadJob.media_type == media_type)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(DownloadJob.filename.ilike(like), DownloadJob.source_url.ilike(like), DownloadJob.media_url.ilike(like))
        )
    return stmt


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> DownloadJob:
    job = await session.get(DownloadJob, job_id)
    if job is None:
        raise AppError("job_not_found", "Pekerjaan unduhan tidak ditemukan.", 404)
    return job


async def retry_job(session: AsyncSession, job_id: uuid.UUID) -> DownloadJob:
    job = await get_job(session, job_id)
    if job.status != "failed":
        raise AppError("job_not_failed", "Hanya pekerjaan yang gagal yang dapat dicoba lagi.", 409)
    job.status = "pending"
    job.error_message = None
    job.size_downloaded = 0
    job.completed_at = None
    session.add(DownloadHistory(job_id=job.id, action="retried"))
    await session.commit()
    return job


def remove_file(settings: Settings, storage_key: str) -> None:
    """Sinkron; panggil lewat `remove_file_async` dari kode async."""
    path = safe_storage_path(settings, storage_key)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.warning("gagal menghapus file %s", storage_key, exc_info=True)


async def remove_file_async(settings: Settings, storage_key: str) -> None:
    await asyncio.to_thread(remove_file, settings, storage_key)


async def mark_failed(session: AsyncSession, job_id: uuid.UUID, message: str) -> None:
    job = await session.get(DownloadJob, job_id)
    if job is None or job.status != "pending":
        return
    job.status = "failed"
    job.error_message = message
    job.completed_at = utcnow()
    session.add(DownloadHistory(job_id=job.id, action="failed", details={"error": message}))
    await session.commit()


@dataclass
class ServableFile:
    path: Path
    file: DownloadFile


async def get_servable_file(session: AsyncSession, settings: Settings, job_id: uuid.UUID) -> ServableFile:
    """File hasil yang boleh disajikan: job selesai, belum kedaluwarsa, dan ada di disk."""
    job = await get_job(session, job_id)
    file = job.file
    if job.status != "completed" or file is None:
        raise AppError("file_not_ready", "File belum tersedia untuk pekerjaan ini.", 409)
    expires = aware(file.expires_at)
    if file.deleted_at is not None or (expires is not None and expires < utcnow()):
        raise AppError(
            "file_expired", "File sudah kedaluwarsa dan dihapus dari server. Unduh ulang dari URL sumber.", 410
        )
    path = safe_storage_path(settings, file.storage_key)
    if not await asyncio.to_thread(path.is_file):
        raise AppError("file_missing", "File tidak ditemukan di penyimpanan server.", 410)
    return ServableFile(path=path, file=file)


def safe_storage_path(settings: Settings, storage_key: str) -> Path:
    """Path file di dalam folder downloads; menolak traversal."""
    root = settings.downloads_dir.resolve()
    path = (root / storage_key).resolve()
    if path.parent != root:
        raise AppError("invalid_storage_key", "Lokasi file tidak valid.", 400)
    return path


async def delete_job(session: AsyncSession, settings: Settings, job_id: uuid.UUID) -> None:
    """Menghapus riwayat beserta file sementaranya dan log kejadiannya."""
    job = await get_job(session, job_id)
    if job.status in RUNNING_STATUSES:
        raise AppError("job_active", "Pekerjaan masih berjalan. Tunggu hingga selesai sebelum menghapus.", 409)
    if job.file is not None:
        await remove_file_async(settings, job.file.storage_key)
    await session.delete(job)
    await session.commit()
