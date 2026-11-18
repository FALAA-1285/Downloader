from __future__ import annotations

import functools
import shutil
import subprocess

import yt_dlp.version
from fastapi import APIRouter, Request
from sqlalchemy import text

from app.api.deps import QueueDep, RegistryDep, SessionDep, SettingsDep
from app.core.config import APP_VERSION
from app.schemas.api import AdapterOut, ConfigOut, HealthOut

router = APIRouter(tags=["system"])


@functools.lru_cache(maxsize=1)
def _get_ffmpeg_version() -> str | None:
    bin_path = shutil.which("ffmpeg")
    if not bin_path:
        return None
    try:
        proc = subprocess.run(  # noqa: S603
            [bin_path, "-version"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        line = proc.stdout.splitlines()[0] if proc.stdout else ""
        return line.split("version")[-1].strip().split()[0] if "version" in line else line.strip()
    except Exception:  # noqa: BLE001
        return "terpasang"


@router.get("/health", response_model=HealthOut)
async def health(session: SessionDep, queue: QueueDep) -> HealthOut:
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    queue_ok = await queue.healthy()
    return HealthOut(
        status="ok" if db_ok and queue_ok else "degraded", database=db_ok, queue=queue_ok, version=APP_VERSION
    )


@router.get("/adapters", response_model=list[AdapterOut])
async def adapters(registry: RegistryDep) -> list[AdapterOut]:
    return [
        AdapterOut(
            id=a.id,
            name=a.name,
            domains=list(a.domains),
            status=registry.status_of(a),  # type: ignore[arg-type]
            note=a.note,
        )
        for a in registry.all()
    ]


@router.get("/config", response_model=ConfigOut)
async def config(settings: SettingsDep, request: Request) -> ConfigOut:
    return ConfigOut(
        max_download_size_mb=settings.max_download_size_mb,
        download_timeout_seconds=settings.download_timeout_seconds,
        file_retention_hours=settings.file_retention_hours,
        storage_path=str(settings.storage_path),
        version=APP_VERSION,
        queue_backend=request.app.state.queue.name,
        yt_dlp_version=getattr(yt_dlp.version, "__version__", None),
        ffmpeg_version=_get_ffmpeg_version(),
    )
