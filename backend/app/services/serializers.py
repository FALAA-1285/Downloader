from __future__ import annotations

from app.models.models import DownloadJob, aware
from app.schemas.api import DownloadJobOut


def job_out(job: DownloadJob) -> DownloadJobOut:
    """Progres hanya dihitung dari informasi nyata; tanpa ukuran total, progres = null (PRD §12.3)."""
    if job.status == "completed":
        progress: int | None = 100
    elif job.size_total:
        progress = min(100, int(job.size_downloaded * 100 / job.size_total))
    elif job.status in ("pending", "processing"):
        progress = 0 if job.size_total else None
    else:
        progress = None

    file = job.file
    return DownloadJobOut(
        id=job.id,
        status=job.status,  # type: ignore[arg-type]
        progress=progress,
        filename=file.filename if file else job.filename,
        media_type=job.media_type,  # type: ignore[arg-type]
        source_url=job.source_url,
        source_domain=job.source_domain,
        size_downloaded=job.size_downloaded,
        size_total=job.size_total,
        error_message=job.error_message,
        created_at=aware(job.created_at),
        completed_at=aware(job.completed_at),
        expires_at=aware(file.expires_at) if file else None,
    )
