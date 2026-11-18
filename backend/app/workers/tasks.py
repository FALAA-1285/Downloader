"""Fungsi yang dijalankan worker RQ: `rq worker downloads --url $REDIS_URL`."""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.core.config import get_settings
from app.core.guard_proxy import shutdown_guard_proxy
from app.core.url_guard import install_doh_socket_patch
from app.models.db import make_engine, make_session_factory
from app.services.download_runner import run_download


def download_job(job_id: str) -> None:
    logging.basicConfig(level=get_settings().log_level)
    # Perilaku DNS sama dengan proses API (M-11).
    install_doh_socket_patch()
    asyncio.run(_main(uuid.UUID(job_id)))


async def _main(job_id: uuid.UUID) -> None:
    settings = get_settings()
    # Engine dibuat per job karena setiap job RQ memiliki event loop sendiri.
    engine = make_engine(settings)
    try:
        await run_download(job_id, make_session_factory(engine), settings)
    finally:
        # Proxy penjaga SSRF terikat event loop job ini.
        await shutdown_guard_proxy()
        await engine.dispose()
