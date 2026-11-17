"""Eksekusi satu pekerjaan unduhan (PRD §7.2, NFR-02, NFR-03).

Dipakai oleh antrean inline (proses API) maupun worker RQ.
- Streaming ke file sementara; tidak memuat seluruh file ke memori.
- Batas ukuran per file, batas total storage, dan batas waktu total.
- Retry terbatas untuk error sementara.
- Isi divalidasi dengan magic bytes; nama file dibuat server.
- File sementara selalu dibersihkan bila gagal.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import shutil
import time
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.errors import AppError, TransientError
from app.core.http_client import build_client, map_http_error, open_stream, status_error
from app.core.url_guard import validate_url
from app.downloaders.file_validator import resolve_kind
from app.downloaders.subtitles import validate_subtitle, vtt_to_srt
from app.extractors.common import sanitize_filename
from app.models.db import SessionFactory
from app.models.models import DownloadFile, DownloadHistory, DownloadJob, utcnow

log = logging.getLogger(__name__)

CHUNK = 64 * 1024
PROGRESS_INTERVAL = 0.5
SNIFF_BYTES = 4096
UNEXPECTED = "Terjadi kesalahan tak terduga saat mengunduh. Coba lagi."


async def run_download(job_id: uuid.UUID, sessions: SessionFactory, settings: Settings) -> None:
    async with sessions() as s:
        job = await s.get(DownloadJob, job_id)
        if job is None or job.status != "pending":
            return
        job.status = "processing"
        job.started_at = utcnow()
        job.error_message = None
        s.add(DownloadHistory(job_id=job_id, action="started"))
        await s.commit()

    attempt = 0
    while True:
        attempt += 1
        try:
            await _attempt(job_id, sessions, settings, attempt)
            return
        except TransientError as exc:
            if attempt <= settings.download_max_retries:
                delay = 2 ** (attempt - 1)
                await _event(sessions, job_id, "retry_scheduled", {"attempt": attempt, "reason": exc.message})
                await asyncio.sleep(delay)
                continue
            await _fail(sessions, job_id, f"{exc.message} Sudah dicoba {attempt} kali.")
            return
        except AppError as exc:
            await _fail(sessions, job_id, exc.message)
            return
        except asyncio.CancelledError:
            await asyncio.shield(_fail(sessions, job_id, "Pekerjaan dihentikan karena server berhenti."))
            raise
        except Exception:
            log.exception("download %s gagal", job_id)
            await _fail(sessions, job_id, UNEXPECTED)
            return


async def _attempt(job_id: uuid.UUID, sessions: SessionFactory, settings: Settings, attempt: int) -> None:
    async with sessions() as s:
        job = await s.get(DownloadJob, job_id)
        if job is None:
            return
        job.attempts = attempt
        job.size_downloaded = 0
        await s.commit()
        media_url, media_type = job.media_url, job.media_type
        display_name, options = job.filename, job.options or {}

    validate_url(media_url, settings.port_allowlist)
    await _check_storage_capacity(sessions, settings, incoming=None)

    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    settings.downloads_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = settings.temp_dir / f"{job_id.hex}.part"
    try:
        async with asyncio.timeout(settings.download_timeout_seconds):
            head, size = await _stream_to_file(job_id, media_url, tmp_path, sessions, settings)
        await _finalize(job_id, tmp_path, head, size, media_type, display_name, options, sessions, settings)
    except TimeoutError as exc:
        raise TransientError(
            f"Unduhan melewati batas waktu {settings.download_timeout_seconds} detik.", code="download_timeout"
        ) from exc
    except OSError as exc:
        raise _storage_error(exc) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


async def _stream_to_file(
    job_id: uuid.UUID, url: str, tmp_path: Path, sessions: SessionFactory, settings: Settings
) -> tuple[bytes, int]:
    max_bytes = settings.max_download_bytes
    async with (
        build_client(settings) as client,
        open_stream(client, url, settings, headers={"Accept-Encoding": "identity"}) as (resp, _final),
    ):
        if resp.status_code >= 400:
            raise status_error(resp.status_code, subject="File")
        length = resp.headers.get("content-length")
        encoded = resp.headers.get("content-encoding", "identity").lower() not in ("", "identity")
        # Content-Length dari respons terkompresi bukan ukuran file sebenarnya.
        total = int(length) if length and length.isdigit() and not encoded else None
        if total is not None and total > max_bytes:
            raise AppError(
                "file_too_large",
                f"Ukuran file ({total / 1_048_576:.1f} MB) melebihi batas {settings.max_download_size_mb} MB.",
                413,
            )
        await _check_storage_capacity(sessions, settings, incoming=total)
        await _update(sessions, job_id, status="downloading", size_total=total, size_downloaded=0)

        written = 0
        head = b""
        last_report = time.monotonic()
        with tmp_path.open("wb") as fh:
            try:
                async for chunk in resp.aiter_bytes(CHUNK):
                    written += len(chunk)
                    if written > max_bytes:
                        raise AppError(
                            "file_too_large",
                            f"Unduhan dihentikan: file melebihi batas {settings.max_download_size_mb} MB.",
                            413,
                        )
                    if len(head) < SNIFF_BYTES:
                        head += chunk[: SNIFF_BYTES - len(head)]
                    fh.write(chunk)
                    if time.monotonic() - last_report >= PROGRESS_INTERVAL:
                        last_report = time.monotonic()
                        await _update(sessions, job_id, size_downloaded=written)
            except AppError:
                raise
            except httpx.HTTPError as exc:  # error jaringan di tengah stream
                raise map_http_error(exc, url) from exc
        if written == 0:
            raise AppError("empty_file", "Sumber mengirim file kosong.", 422)
        if total is not None and written < total:
            raise TransientError("Unduhan terputus sebelum file lengkap.", code="incomplete")
        await _update(sessions, job_id, size_downloaded=written, size_total=written)
        return head, written


async def _finalize(
    job_id: uuid.UUID,
    tmp_path: Path,
    head: bytes,
    size: int,
    media_type: str,
    display_name: str,
    options: dict,
    sessions: SessionFactory,
    settings: Settings,
) -> None:
    kind = resolve_kind(head, media_type)
    mime, ext = kind.mime, kind.ext

    if media_type == "subtitle":
        data = await asyncio.to_thread(tmp_path.read_bytes)
        validate_subtitle(data, kind.name)
        if options.get("subtitle_format") == "srt" and kind.name == "vtt":
            converted = vtt_to_srt(data)
            await asyncio.to_thread(tmp_path.write_bytes, converted)
            mime, ext, size = "application/x-subrip", "srt", len(converted)
    elif media_type in ("video", "audio"):
        await _ffprobe_check(tmp_path, settings)

    storage_key = f"{job_id.hex}.{ext}"
    final_path = settings.downloads_dir / storage_key
    os.replace(tmp_path, final_path)

    stem = sanitize_filename(Path(display_name).stem or media_type, fallback=media_type)
    now = utcnow()
    async with sessions() as s:
        job = await s.get(DownloadJob, job_id)
        if job is None:  # dihapus saat berjalan
            final_path.unlink(missing_ok=True)
            return
        if job.file is not None:
            await s.delete(job.file)
            await s.flush()
        s.add(
            DownloadFile(
                job_id=job_id,
                filename=f"{stem}.{ext}"[:255],
                storage_key=storage_key,
                mime_type=mime,
                extension=ext,
                file_size=size,
                expires_at=now + timedelta(hours=settings.file_retention_hours),
            )
        )
        job.status = "completed"
        job.completed_at = now
        job.size_downloaded = size
        job.size_total = size
        job.error_message = None
        s.add(DownloadHistory(job_id=job_id, action="completed", details={"size": size, "mime": mime}))
        await s.commit()
    log.info("download %s selesai (%s bytes)", job_id, size)


async def _ffprobe_check(path: Path, settings: Settings) -> None:
    """Validasi kontainer media dengan ffprobe bila tersedia. File tidak pernah dieksekusi."""
    binary = shutil.which(settings.ffprobe_path)
    if not binary:
        return
    proc = await asyncio.create_subprocess_exec(
        binary,
        "-v",
        "error",
        "-show_entries",
        "format=format_name",
        "-of",
        "csv=p=0",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _out, _err = await asyncio.wait_for(proc.communicate(), timeout=30)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return  # ffprobe lambat bukan alasan menolak file
    if proc.returncode != 0:
        raise AppError("invalid_media", "File media rusak atau tidak dapat dibaca. File tidak disimpan.", 422)


async def _check_storage_capacity(sessions: SessionFactory, settings: Settings, incoming: int | None) -> None:
    async with sessions() as s:
        used = await s.scalar(
            select(func.coalesce(func.sum(DownloadFile.file_size), 0)).where(DownloadFile.deleted_at.is_(None))
        )
    if int(used or 0) + (incoming or 0) > settings.max_storage_bytes:
        raise AppError(
            "storage_quota",
            "Kapasitas penyimpanan sementara sudah penuh. Hapus riwayat lama atau tunggu file kedaluwarsa dibersihkan.",
            507,
        )


def _storage_error(exc: OSError) -> AppError:
    if exc.errno == errno.ENOSPC:
        return AppError("disk_full", "Disk server penuh. File tidak dapat disimpan.", 507)
    if isinstance(exc, PermissionError) or exc.errno in (errno.EACCES, errno.EPERM):
        return AppError("storage_permission", "Server tidak memiliki izin menulis ke folder penyimpanan.", 500)
    return AppError("storage_error", "Gagal menulis file ke penyimpanan server.", 500)


async def _update(sessions: SessionFactory, job_id: uuid.UUID, **fields: object) -> None:
    async with sessions() as s:
        job = await s.get(DownloadJob, job_id)
        if job is None:
            raise AppError("job_deleted", "Pekerjaan dihapus saat berjalan.", 410)
        for key, value in fields.items():
            setattr(job, key, value)
        await s.commit()


async def _event(sessions: SessionFactory, job_id: uuid.UUID, action: str, details: dict | None = None) -> None:
    async with sessions() as s:
        s.add(DownloadHistory(job_id=job_id, action=action, details=details))
        await s.commit()


async def _fail(sessions: SessionFactory, job_id: uuid.UUID, message: str) -> None:
    async with sessions() as s:
        job = await s.get(DownloadJob, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = message
        job.completed_at = utcnow()
        s.add(DownloadHistory(job_id=job_id, action="failed", details={"error": message}))
        await s.commit()
    log.info("download %s gagal: %s", job_id, message)
