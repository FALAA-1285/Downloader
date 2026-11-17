"""Pembersihan berkala (PRD §13, NFR-03): file kedaluwarsa, file sementara, job macet, analisis lama."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select

from app.core.config import Settings
from app.models.db import SessionFactory
from app.models.models import Analysis, DownloadFile, DownloadHistory, DownloadJob, utcnow

from .download_service import remove_file

log = logging.getLogger(__name__)


@dataclass
class CleanupReport:
    expired_files: int = 0
    temp_files: int = 0
    orphan_files: int = 0
    stuck_jobs: int = 0
    analyses: int = 0


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
            remove_file(settings, file.storage_key)
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

        result = await s.execute(delete(Analysis).where(Analysis.expires_at < now))
        report.analyses = result.rowcount or 0

        known = set((await s.scalars(select(DownloadFile.storage_key).where(DownloadFile.deleted_at.is_(None)))).all())
        await s.commit()

    # File sementara yang tertinggal (proses terhenti di tengah unduhan).
    temp_age = settings.download_timeout_seconds * 2 + 300
    report.temp_files = _sweep(settings.temp_dir, max_age=temp_age, keep=set())
    # File di folder downloads tanpa catatan database.
    report.orphan_files = _sweep(settings.downloads_dir, max_age=3600, keep=known)

    if any(vars(report).values()):
        log.info("cleanup: %s", report)
    return report


def _sweep(folder, *, max_age: float, keep: set[str]) -> int:
    if not folder.exists():
        return 0
    removed = 0
    cutoff = time.time() - max_age
    for path in folder.iterdir():
        if not path.is_file() or path.name in keep or path.name.startswith("."):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            log.warning("gagal membersihkan %s", path, exc_info=True)
    return removed
