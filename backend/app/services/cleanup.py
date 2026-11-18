"""Pembersihan berkala (PRD §13, NFR-03): file kedaluwarsa, file sementara, job macet/yatim, analisis lama."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select

from app.core.config import Settings
from app.models.db import SessionFactory
from app.models.models import TERMINAL_STATUSES, Analysis, DownloadFile, DownloadHistory, DownloadJob, utcnow

from .download_runner import strip_secrets
from .download_service import remove_file_async

log = logging.getLogger(__name__)


@dataclass
class CleanupReport:
    expired_files: int = 0
    temp_files: int = 0
    orphan_files: int = 0
    stuck_jobs: int = 0
    stale_pending: int = 0
    analyses: int = 0
    paused_expired: int = 0
    secrets_wiped: int = 0
    old_jobs: int = 0


async def run_cleanup(sessions: SessionFactory, settings: Settings) -> CleanupReport:
    report = CleanupReport()
    now = utcnow()

    async with sessions() as s:
        expired = (
            await s.scalars(
                select(DownloadFile).where(DownloadFile.deleted_at.is_(None), DownloadFile.expires_at < now)
            )
        ).all()
        for file in expired:
            await remove_file_async(settings, file.storage_key)
            file.deleted_at = now
            s.add(DownloadHistory(job_id=file.job_id, action="file_expired"))
        report.expired_files = len(expired)

        stuck_after = settings.download_timeout_seconds * (settings.download_max_retries + 1) + 300
        stuck = (
            await s.scalars(
                select(DownloadJob).where(
                    DownloadJob.status.in_(("processing", "downloading")),
                    DownloadJob.updated_at < now - timedelta(seconds=stuck_after),
                )
            )
        ).all()
        for job in stuck:
            job.status = "failed"
            job.error_message = "Pekerjaan terhenti tanpa kabar dan dihentikan otomatis. Coba lagi."
            job.completed_at = now
            s.add(DownloadHistory(job_id=job.id, action="failed", details={"error": "stuck"}))
        report.stuck_jobs = len(stuck)

        # Job antre yang tidak pernah diambil worker (mis. Redis kehilangan job, worker mati).
        stale = (
            await s.scalars(
                select(DownloadJob).where(
                    DownloadJob.status == "pending",
                    DownloadJob.updated_at < now - timedelta(seconds=settings.stale_pending_seconds),
                )
            )
        ).all()
        for job in stale:
            job.status = "failed"
            job.error_message = "Pekerjaan tidak pernah diproses oleh worker antrean. Coba lagi."
            job.completed_at = now
            s.add(DownloadHistory(job_id=job.id, action="failed", details={"error": "stale_pending"}))
        report.stale_pending = len(stale)

        result = await s.execute(delete(Analysis).where(Analysis.expires_at < now))
        report.analyses = result.rowcount or 0

        # Job yang dijeda terlalu lama dibatalkan; file parsialnya ikut dibersihkan di bawah.
        paused_cutoff = now - timedelta(hours=settings.file_retention_hours)
        paused_expired = (
            await s.scalars(
                select(DownloadJob).where(DownloadJob.status == "paused", DownloadJob.updated_at < paused_cutoff)
            )
        ).all()
        for job in paused_expired:
            job.status = "cancelled"
            job.error_message = "Dibatalkan otomatis karena dijeda terlalu lama."
            job.completed_at = now
            job.options = strip_secrets(job.options)
            s.add(DownloadHistory(job_id=job.id, action="cancelled", details={"error": "paused_expired"}))
        report.paused_expired = len(paused_expired)

        # Cookie/header pengguna pada job gagal hanya disimpan selama masa retry (H-02).
        secret_cutoff = now - timedelta(hours=settings.analysis_retention_hours)
        with_secrets = (
            await s.scalars(
                select(DownloadJob).where(
                    DownloadJob.status.in_(TERMINAL_STATUSES),
                    DownloadJob.options.is_not(None),
                    DownloadJob.updated_at < secret_cutoff,
                )
            )
        ).all()
        for job in with_secrets:
            cleaned = strip_secrets(job.options)
            if cleaned != job.options:
                job.options = cleaned
                report.secrets_wiped += 1

        # Retensi riwayat: job selesai/gagal/dibatalkan yang sudah lama dihapus beserta filenya.
        if settings.history_retention_days > 0:
            history_cutoff = now - timedelta(days=settings.history_retention_days)
            old_jobs = (
                await s.scalars(
                    select(DownloadJob).where(
                        DownloadJob.status.in_(TERMINAL_STATUSES), DownloadJob.updated_at < history_cutoff
                    )
                )
            ).all()
            for job in old_jobs:
                if job.file is not None and job.file.deleted_at is None:
                    await remove_file_async(settings, job.file.storage_key)
                await s.delete(job)
            report.old_jobs = len(old_jobs)

        known = set((await s.scalars(select(DownloadFile.storage_key).where(DownloadFile.deleted_at.is_(None)))).all())
        paused_prefixes = tuple(
            job_id.hex
            for job_id in (await s.scalars(select(DownloadJob.id).where(DownloadJob.status == "paused"))).all()
        )
        await s.commit()

    # File sementara yang tertinggal (proses terhenti di tengah unduhan). File parsial milik job
    # yang dijeda dipertahankan agar unduhan bisa dilanjutkan.
    temp_age = settings.download_timeout_seconds * 2 + 300
    report.temp_files = await asyncio.to_thread(
        _sweep, settings.temp_dir, max_age=temp_age, keep=set(), keep_prefixes=paused_prefixes
    )
    # File di folder downloads tanpa catatan database.
    report.orphan_files = await asyncio.to_thread(_sweep, settings.downloads_dir, max_age=3600, keep=known)

    if any(vars(report).values()):
        log.info("cleanup: %s", report)
    return report


def _sweep(folder, *, max_age: float, keep: set[str], keep_prefixes: tuple[str, ...] = ()) -> int:
    if not folder.exists():
        return 0
    removed = 0
    cutoff = time.time() - max_age
    for path in folder.iterdir():
        if not path.is_file() or path.name in keep or path.name.startswith("."):
            continue
        if keep_prefixes and path.name.startswith(keep_prefixes):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            log.warning("gagal membersihkan %s", path, exc_info=True)
    return removed
