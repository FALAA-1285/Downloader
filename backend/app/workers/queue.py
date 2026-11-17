"""Antrean unduhan (NFR-02).

- `InlineQueue`: menjalankan unduhan sebagai task asyncio di proses API, dengan batas
  konkurensi. Dipakai untuk pengembangan lokal (termasuk Windows, tempat worker RQ
  tidak dapat berjalan).
- `RQQueue`: mengirim pekerjaan ke Redis untuk diproses worker RQ terpisah (Docker).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Protocol

from sqlalchemy import select

from app.core.config import Settings
from app.models.db import SessionFactory
from app.models.models import DownloadHistory, DownloadJob, utcnow
from app.services.download_runner import run_download

log = logging.getLogger(__name__)


class DownloadQueue(Protocol):
    name: str

    async def enqueue(self, job_id: uuid.UUID) -> None: ...
    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def healthy(self) -> bool: ...


class InlineQueue:
    name = "inline"

    def __init__(self, sessions: SessionFactory, settings: Settings) -> None:
        self.sessions = sessions
        self.settings = settings
        self._semaphore = asyncio.Semaphore(settings.download_concurrency)
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(self, job_id: uuid.UUID) -> None:
        task = asyncio.create_task(self._run(job_id), name=f"download-{job_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, job_id: uuid.UUID) -> None:
        async with self._semaphore:
            await run_download(job_id, self.sessions, self.settings)

    async def startup(self) -> None:
        """Pulihkan pekerjaan setelah restart: yang terputus ditandai gagal, yang antre dijalankan lagi."""
        async with self.sessions() as s:
            interrupted = (
                await s.scalars(select(DownloadJob).where(DownloadJob.status.in_(("processing", "downloading"))))
            ).all()
            for job in interrupted:
                job.status = "failed"
                job.error_message = "Server dimulai ulang saat unduhan berjalan. Coba lagi."
                job.completed_at = utcnow()
                s.add(DownloadHistory(job_id=job.id, action="failed", details={"error": "restart"}))
            pending = (await s.scalars(select(DownloadJob.id).where(DownloadJob.status == "pending"))).all()
            await s.commit()
        for job_id in pending:
            await self.enqueue(job_id)
        if interrupted or pending:
            log.info("inline queue: %d dihentikan, %d dilanjutkan", len(interrupted), len(pending))

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def healthy(self) -> bool:
        return True

    async def drain(self) -> None:
        """Menunggu semua unduhan selesai (dipakai di test)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


class RQQueue:
    name = "rq"
    QUEUE_NAME = "downloads"

    def __init__(self, settings: Settings) -> None:
        from redis import Redis
        from rq import Queue

        self.settings = settings
        self._redis = Redis.from_url(settings.redis_url)
        self._queue = Queue(self.QUEUE_NAME, connection=self._redis)

    async def enqueue(self, job_id: uuid.UUID) -> None:
        timeout = self.settings.download_timeout_seconds * (self.settings.download_max_retries + 1) + 120
        await asyncio.to_thread(
            self._queue.enqueue_call,
            func="app.workers.tasks.download_job",
            args=(str(job_id),),
            timeout=timeout,
            job_id=f"download-{job_id}-{utcnow().timestamp():.0f}",
            result_ttl=3600,
            failure_ttl=86400,
        )

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        await asyncio.to_thread(self._redis.close)

    async def healthy(self) -> bool:
        try:
            return bool(await asyncio.to_thread(self._redis.ping))
        except Exception:  # noqa: BLE001
            return False


def make_queue(settings: Settings, sessions: SessionFactory) -> DownloadQueue:
    if settings.queue_backend == "rq":
        return RQQueue(settings)
    return InlineQueue(sessions, settings)
