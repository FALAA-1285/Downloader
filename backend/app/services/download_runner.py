"""Eksekusi satu pekerjaan unduhan (PRD §7.2, NFR-02, NFR-03).

Dipakai oleh antrean inline (proses API) maupun worker RQ.
- Job diklaim secara atomik (`pending` → `processing`), sehingga tidak diproses dua kali.
- Streaming ke file sementara; tulis disk dilakukan di thread agar event loop tidak terblokir.
- Batas ukuran per file (lebih kecil untuk subtitle), batas total storage, dan batas waktu total.
- Retry terbatas untuk error sementara.
- Isi divalidasi dengan magic bytes; video/audio dicek ffprobe dengan whitelist protokol & format.
- File sementara selalu dibersihkan bila gagal.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import shutil
import subprocess
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import yt_dlp
from sqlalchemy import func, select, update

from app.core.config import Settings
from app.core.errors import AppError, TransientError
from app.core.http_client import build_client, is_encoded, iter_body, open_stream, status_error
from app.core.url_guard import redact_url, validate_url
from app.downloaders.file_validator import Kind, resolve_kind
from app.downloaders.subtitles import validate_subtitle, vtt_to_srt
from app.extractors.common import sanitize_filename
from app.models.db import SessionFactory
from app.models.models import DownloadFile, DownloadHistory, DownloadJob, utcnow

log = logging.getLogger(__name__)

CHUNK = 64 * 1024
WRITE_BUFFER = 1024 * 1024
PROGRESS_INTERVAL = 0.5
SNIFF_BYTES = 4096
FFPROBE_TIMEOUT = 30
UNEXPECTED = "Terjadi kesalahan tak terduga saat mengunduh. Coba lagi."

# Demuxer FFmpeg yang boleh dipakai untuk setiap jenis hasil deteksi magic bytes. Tanpa
# whitelist ini, ffprobe bisa mengenali konten lain (mis. playlist HLS) dan membuka sumber lain.
FFPROBE_FORMATS = {
    "mp4": "mov,mp4,m4a,3gp,3g2,mj2",
    "mov": "mov,mp4,m4a,3gp,3g2,mj2",
    "m4a": "mov,mp4,m4a,3gp,3g2,mj2",
    "webm": "matroska,webm",
    "mkv": "matroska,webm",
    "ogg": "ogg",
    "mp3": "mp3",
    "aac": "aac",
    "wav": "wav",
    "flac": "flac",
}


async def run_download(job_id: uuid.UUID, sessions: SessionFactory, settings: Settings) -> None:
    now = utcnow()
    async with sessions() as s:
        claimed = await s.execute(
            update(DownloadJob)
            .where(DownloadJob.id == job_id, DownloadJob.status == "pending")
            .values(status="processing", started_at=now, error_message=None, updated_at=now)
        )
        if claimed.rowcount != 1:
            await s.rollback()
            return  # sudah diambil proses lain, dihapus, atau bukan pending
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
        except Exception as exc:
            log.exception("download %s gagal", job_id)
            err_msg = f"{UNEXPECTED} ({type(exc).__name__}: {exc})" if settings.app_env == "development" else UNEXPECTED
            await _fail(sessions, job_id, err_msg)
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
        platform = job.platform
        source_url = job.source_url

    validate_url(media_url, settings.port_allowlist)
    await _check_storage_capacity(sessions, settings, incoming=None, exclude=None)

    await asyncio.to_thread(settings.temp_dir.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(settings.downloads_dir.mkdir, parents=True, exist_ok=True)
    tmp_path = settings.temp_dir / f"{job_id.hex}.part"
    is_social = (
        platform in ("youtube", "instagram", "facebook", "tiktok", "x", "social_other")
        or options.get("downloader") == "yt-dlp"
        or media_url.endswith((".m3u8", ".mpd"))
        or ".m3u8" in media_url
        or ".mpd" in media_url
    )
    try:
        if is_social:
            loop = asyncio.get_running_loop()
            head, size = await asyncio.to_thread(
                _download_ytdlp_sync, media_url, media_type, tmp_path, options, job_id, loop, sessions, source_url
            )
        else:
            try:
                async with asyncio.timeout(settings.download_timeout_seconds):
                    head, size = await _stream_to_file(
                        job_id, media_url, media_type, tmp_path, sessions, settings, referer=source_url
                    )
            except AppError as exc:
                if exc.status_code in (401, 403) and media_type in ("video", "audio"):
                    log.info("direct stream %s gagal (%s), beralih ke yt-dlp", media_url, exc.message)
                    loop = asyncio.get_running_loop()
                    head, size = await asyncio.to_thread(
                        _download_ytdlp_sync, media_url, media_type, tmp_path, options, job_id, loop, sessions, source_url
                    )
                else:
                    raise
        await _finalize(job_id, tmp_path, head, size, media_type, display_name, options, sessions, settings)
    except TimeoutError as exc:
        raise TransientError(
            f"Unduhan melewati batas waktu {settings.download_timeout_seconds} detik.", code="download_timeout"
        ) from exc
    except OSError as exc:
        raise _storage_error(exc) from exc
    finally:
        await asyncio.to_thread(tmp_path.unlink, missing_ok=True)


def _download_ytdlp_sync(
    url: str,
    media_type: str,
    tmp_path: Path,
    options: dict,
    job_id: uuid.UUID,
    loop: asyncio.AbstractEventLoop,
    sessions: SessionFactory,
    source_url: str | None = None,
) -> tuple[bytes, int]:
    clean_url = url.split("#")[0]
    out_base = tmp_path.parent / f"{job_id.hex}_ytdlp"
    out_tmpl = str(out_base) + ".%(ext)s"

    ffmpeg_bin = shutil.which("ffmpeg")
    ffmpeg_dir = str(Path(ffmpeg_bin).resolve().parent) if ffmpeg_bin else None

    last_update_time = 0.0

    async def _update_db(status: str, downloaded: int, total: int | None) -> None:
        try:
            async with sessions() as s:
                job = await s.get(DownloadJob, job_id)
                if job and job.status not in ("completed", "failed"):
                    job.status = status
                    job.size_downloaded = downloaded
                    if total and total > 0:
                        job.size_total = total
                    await s.commit()
        except Exception as exc:
            log.debug("gagal memperbarui progres ke database: %s", exc)

    def progress_hook(d: dict[str, Any]) -> None:
        nonlocal last_update_time
        now = time.monotonic()
        status = d.get("status")
        if status == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if now - last_update_time >= 1.0:
                last_update_time = now
                asyncio.run_coroutine_threadsafe(_update_db("downloading", downloaded, total), loop)
        elif status == "finished":
            total = d.get("total_bytes") or d.get("downloaded_bytes") or 0
            asyncio.run_coroutine_threadsafe(_update_db("processing", total, total), loop)

    headers = {}
    if source_url:
        headers["Referer"] = source_url

    ydl_opts: dict[str, Any] = {
        "outtmpl": out_tmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 8,
        "http_chunk_size": 10485760,
        "buffersize": 1024 * 1024,
        "updatetime": False,
        "progress_hooks": [progress_hook],
        "http_headers": headers,
    }
    if ffmpeg_dir:
        ydl_opts["ffmpeg_location"] = ffmpeg_dir

    format_id = options.get("format_id")
    if media_type == "audio":
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }
        ]
    else:
        ydl_opts["format"] = format_id if format_id else "bestvideo+bestaudio/best"
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([clean_url])
    except yt_dlp.utils.DownloadError as exc:
        clean_msg = str(exc).split("ERROR:")[-1].strip()
        raise AppError("download_failed", f"Gagal mengunduh media dari platform: {clean_msg}", 502) from exc

    candidates = list(tmp_path.parent.glob(f"{job_id.hex}_ytdlp.*"))
    if not candidates:
        raise AppError("download_failed", "File unduhan tidak ditemukan di penyimpanan sementara.", 500)

    res_file = candidates[0]
    if tmp_path.exists():
        tmp_path.unlink()
    res_file.replace(tmp_path)

    size = tmp_path.stat().st_size
    head = tmp_path.read_bytes()[:SNIFF_BYTES]
    return head, size


def _size_limit(media_type: str, settings: Settings) -> tuple[int, str]:
    if media_type == "subtitle":
        return min(settings.max_subtitle_bytes, settings.max_download_bytes), f"{settings.max_subtitle_size_mb} MB"
    return settings.max_download_bytes, f"{settings.max_download_size_mb} MB"


async def _stream_to_file(
    job_id: uuid.UUID,
    url: str,
    media_type: str,
    tmp_path: Path,
    sessions: SessionFactory,
    settings: Settings,
    referer: str | None = None,
) -> tuple[bytes, int]:
    max_bytes, limit_label = _size_limit(media_type, settings)
    headers = {
        "Accept-Encoding": "identity",
        "User-Agent": settings.user_agent,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
        "Sec-Fetch-Mode": "no-cors",
    }
    if referer:
        headers["Referer"] = referer
    async with (
        build_client(settings) as client,
        open_stream(client, url, settings, headers=headers) as (resp, _final),
    ):
        if resp.status_code >= 400:
            raise status_error(resp.status_code, subject="File")
        length = resp.headers.get("content-length")
        # Content-Length dari respons terkompresi bukan ukuran file sebenarnya.
        total = int(length) if length and length.isdigit() and not is_encoded(resp) else None
        if total is not None and total > max_bytes:
            raise AppError(
                "file_too_large",
                f"Ukuran file ({total / 1_048_576:.1f} MB) melebihi batas {limit_label}.",
                413,
            )
        await _check_storage_capacity(sessions, settings, incoming=total, exclude=tmp_path)
        await _update(sessions, job_id, status="downloading", size_total=total, size_downloaded=0)

        written = 0
        head = b""
        buffer = bytearray()
        last_report = time.monotonic()
        fh = await asyncio.to_thread(tmp_path.open, "wb")
        try:
            async for chunk in iter_body(resp, CHUNK):
                written += len(chunk)
                if written > max_bytes:
                    raise AppError("file_too_large", f"Unduhan dihentikan: file melebihi batas {limit_label}.", 413)
                if len(head) < SNIFF_BYTES:
                    head += chunk[: SNIFF_BYTES - len(head)]
                buffer += chunk
                if len(buffer) >= WRITE_BUFFER:
                    await asyncio.to_thread(fh.write, bytes(buffer))
                    buffer.clear()
                if time.monotonic() - last_report >= PROGRESS_INTERVAL:
                    last_report = time.monotonic()
                    await _update(sessions, job_id, size_downloaded=written)
            if buffer:
                await asyncio.to_thread(fh.write, bytes(buffer))
        finally:
            await asyncio.to_thread(fh.close)

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
        data = await asyncio.to_thread(tmp_path.read_bytes)  # sudah dibatasi max_subtitle_size_mb
        validate_subtitle(data, kind.name)
        if options.get("subtitle_format") == "srt" and kind.name == "vtt":
            converted = vtt_to_srt(data)
            await asyncio.to_thread(tmp_path.write_bytes, converted)
            mime, ext, size = "application/x-subrip", "srt", len(converted)
    elif media_type in ("video", "audio"):
        await _ffprobe_check(tmp_path, kind, settings)

    storage_key = f"{job_id.hex}.{ext}"
    final_path = settings.downloads_dir / storage_key
    await asyncio.to_thread(os.replace, tmp_path, final_path)

    stem = sanitize_filename(Path(display_name).stem or media_type, fallback=media_type)
    now = utcnow()
    async with sessions() as s:
        job = await s.get(DownloadJob, job_id)
        if job is None:  # dihapus saat berjalan
            await asyncio.to_thread(final_path.unlink, missing_ok=True)
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
        # URL tidak lagi dibutuhkan setelah selesai; buang query string yang bisa berisi token (PRD §11).
        job.media_url = redact_url(job.media_url)
        s.add(DownloadHistory(job_id=job_id, action="completed", details={"size": size, "mime": mime}))
        await s.commit()
    log.info("download %s selesai (%s bytes)", job_id, size)


def _run_ffprobe(raw_binary: str, formats: str, path: Path) -> int:
    try:
        binary = str(Path(raw_binary).resolve())
        proc = subprocess.run(  # noqa: S603 - argumen whitelist tetap, tanpa shell
            [
                binary,
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                formats,
                "-show_entries",
                "format=format_name",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            timeout=FFPROBE_TIMEOUT,
        )
        return proc.returncode
    except subprocess.TimeoutExpired as exc:
        raise AppError(
            "invalid_media", "Pemeriksaan file media melewati batas waktu. File tidak disimpan.", 422
        ) from exc
    except OSError as exc:
        log.warning("ffprobe tidak dapat dijalankan (%s); pemeriksaan dilewati", exc)
        return 0


async def _ffprobe_check(path: Path, kind: Kind, settings: Settings) -> None:
    """Validasi kontainer media dengan ffprobe bila tersedia. File tidak pernah dieksekusi.

    `-protocol_whitelist file` mencegah ffprobe membuka URL/protokol lain yang dirujuk isi file,
    dan `-format_whitelist` memaksa demuxer sesuai hasil deteksi magic bytes.
    """
    found = shutil.which(settings.ffprobe_path)
    formats = FFPROBE_FORMATS.get(kind.name)
    if not found or not formats:
        return
    returncode = await asyncio.to_thread(_run_ffprobe, found, formats, path)
    if returncode != 0:
        raise AppError("invalid_media", "File media rusak atau tidak dapat dibaca. File tidak disimpan.", 422)


def _temp_usage(folder: Path, exclude: Path | None) -> int:
    if not folder.exists():
        return 0
    total = 0
    for path in folder.iterdir():
        if path.is_file() and path != exclude:
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


async def _check_storage_capacity(
    sessions: SessionFactory, settings: Settings, incoming: int | None, exclude: Path | None
) -> None:
    """Kuota mencakup file selesai di database dan unduhan lain yang sedang berjalan di temp/."""
    async with sessions() as s:
        used = await s.scalar(
            select(func.coalesce(func.sum(DownloadFile.file_size), 0)).where(DownloadFile.deleted_at.is_(None))
        )
    in_progress = await asyncio.to_thread(_temp_usage, settings.temp_dir, exclude)
    if int(used or 0) + in_progress + (incoming or 0) > settings.max_storage_bytes:
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
