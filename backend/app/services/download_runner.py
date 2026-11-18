"""Eksekusi satu pekerjaan unduhan (PRD §7.2, NFR-02, NFR-03).

Dipakai oleh antrean inline (proses API) maupun worker RQ.
- Job diklaim secara atomik (`pending` → `processing`), sehingga tidak diproses dua kali.
- Streaming ke file sementara; tulis disk dilakukan di thread agar event loop tidak terblokir.
- Batas ukuran per file (lebih kecil untuk subtitle), batas total storage, dan batas waktu total —
  berlaku untuk jalur HTTP langsung MAUPUN yt-dlp (H-03).
- Retry terbatas untuk error sementara.
- Isi divalidasi dengan magic bytes; video/audio dicek ffprobe dengan whitelist protokol & format.
- Jeda / lanjut / batal (H-06): endpoint mengubah status job; runner memeriksanya setiap kali
  melaporkan progres lalu berhenti. Jeda menyimpan file parsial agar bisa dilanjutkan (HTTP Range
  atau `.part` yt-dlp); batal dan gagal membersihkannya.
- Semua koneksi yt-dlp lewat proxy penjaga SSRF (C-01); cookie terikat domain (C-03, H-01) dan
  dihapus dari database begitu job selesai (H-02).
"""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import yt_dlp
from sqlalchemy import func, select, update

from app.core.config import Settings
from app.core.cookies import Cookie, parse_cookies
from app.core.errors import AppError, TransientError
from app.core.guard_proxy import get_guard_proxy
from app.core.http_client import build_client, is_encoded, iter_body, open_stream, status_error
from app.core.url_guard import redact_url, validate_url
from app.downloaders.file_validator import Kind, resolve_kind
from app.downloaders.subtitles import validate_subtitle, vtt_to_srt
from app.downloaders.ytdlp_common import base_options, cookiefile, safe_headers
from app.extractors.common import sanitize_filename
from app.models.db import SessionFactory
from app.models.models import TERMINAL_STATUSES, DownloadFile, DownloadHistory, DownloadJob, utcnow

log = logging.getLogger(__name__)

CHUNK = 64 * 1024
WRITE_BUFFER = 1024 * 1024
PROGRESS_INTERVAL = 0.5
YTDLP_PROGRESS_INTERVAL = 1.0
SNIFF_BYTES = 4096
FFPROBE_TIMEOUT = 30
UNEXPECTED = "Terjadi kesalahan tak terduga saat mengunduh. Coba lagi."
INTERRUPT_STATUSES = ("paused", "cancelled")
SECRET_OPTIONS = ("cookies", "headers")
_FORMAT_PART = re.compile(r"\.f\d+(-\d+)?")  # file per-format sebelum merge, mis. .f137
PLATFORMS_VIA_YTDLP = ("youtube", "instagram", "facebook", "tiktok", "x", "social_other")

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


class JobInterrupted(Exception):  # noqa: N818 - bukan error, sinyal kendali
    """Job dijeda atau dibatalkan pengguna saat sedang berjalan."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def partial_paths(temp_dir: Path, job_id: uuid.UUID) -> list[Path]:
    """Semua file sementara milik job (unduhan HTTP dan file/fragmen yt-dlp)."""
    if not temp_dir.exists():
        return []
    return [p for p in temp_dir.glob(f"{job_id.hex}*") if p.is_file()]


def remove_partials(temp_dir: Path, job_id: uuid.UUID) -> None:
    for path in partial_paths(temp_dir, job_id):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.warning("gagal menghapus file sementara %s", path.name, exc_info=True)


def strip_secrets(options: dict | None) -> dict | None:
    """Opsi job tanpa cookie & header pengguna (H-02)."""
    if not options:
        return options
    clean = {k: v for k, v in options.items() if k not in SECRET_OPTIONS}
    return clean or None


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
            return  # sudah diambil proses lain, dihapus, dijeda, atau bukan pending
        s.add(DownloadHistory(job_id=job_id, action="started"))
        await s.commit()

    attempt = 0
    while True:
        attempt += 1
        try:
            await _attempt(job_id, sessions, settings, attempt)
            return
        except JobInterrupted as exc:
            log.info("download %s dihentikan: %s", job_id, exc.status)
            return
        except TransientError as exc:
            if attempt <= settings.download_max_retries:
                delay = 2 ** (attempt - 1)
                await _event(sessions, job_id, "retry_scheduled", {"attempt": attempt, "reason": exc.message})
                await asyncio.sleep(delay)
                continue
            await asyncio.to_thread(remove_partials, settings.temp_dir, job_id)
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
        if job.status in INTERRUPT_STATUSES:
            raise JobInterrupted(job.status)
        job.attempts = attempt
        await s.commit()
        media_url, media_type = job.media_url, job.media_type
        display_name, options = job.filename, dict(job.options or {})
        platform = job.platform
        source_url = job.source_url

    validate_url(media_url, settings.port_allowlist)
    await check_storage_capacity(sessions, settings, incoming=None, exclude=None)

    await asyncio.to_thread(settings.temp_dir.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(settings.downloads_dir.mkdir, parents=True, exist_ok=True)
    tmp_path = settings.temp_dir / f"{job_id.hex}.part"
    lower_url = media_url.lower()
    use_ytdlp = (
        platform in PLATFORMS_VIA_YTDLP
        or options.get("downloader") == "yt-dlp"
        or ".m3u8" in lower_url
        or ".mpd" in lower_url
    )
    speed_limit = speed_limit_bytes(options, settings)
    keep_partial = False
    try:
        if use_ytdlp:
            head, size = await _run_ytdlp(
                job_id, media_url, media_type, tmp_path, options, sessions, settings, source_url
            )
        else:
            try:
                async with asyncio.timeout(_time_budget(media_type, settings, speed_limit)):
                    head, size = await _stream_to_file(
                        job_id,
                        media_url,
                        media_type,
                        tmp_path,
                        sessions,
                        settings,
                        referer=source_url,
                        cookies=options.get("cookies"),
                        custom_headers=options.get("headers"),
                        speed_limit=speed_limit,
                    )
            except AppError as exc:
                if (exc.status_code in (401, 403) or exc.code in ("forbidden", "auth_required")) and media_type in (
                    "video",
                    "audio",
                ):
                    log.info("direct stream %s gagal (%s), beralih ke yt-dlp", redact_url(media_url), exc.code)
                    await asyncio.to_thread(tmp_path.unlink, missing_ok=True)
                    head, size = await _run_ytdlp(
                        job_id, media_url, media_type, tmp_path, options, sessions, settings, source_url
                    )
                else:
                    raise
        await _finalize(job_id, tmp_path, head, size, media_type, display_name, options, sessions, settings)
    except JobInterrupted as exc:
        keep_partial = exc.status == "paused"
        raise
    except TransientError:
        # Retry berikutnya melanjutkan dari file parsial (Range / segmen / `.part` yt-dlp).
        keep_partial = True
        raise
    except TimeoutError as exc:
        keep_partial = True
        raise TransientError(
            f"Unduhan melewati batas waktu {settings.download_timeout_seconds} detik.", code="download_timeout"
        ) from exc
    except OSError as exc:
        raise _storage_error(exc) from exc
    finally:
        if not keep_partial:
            await asyncio.to_thread(remove_partials, settings.temp_dir, job_id)


def _time_budget(media_type: str, settings: Settings, speed_limit: int) -> float:
    """Batas waktu total. Dengan batas kecepatan, waktunya diperpanjang secukupnya agar file
    sebesar batas maksimum tetap bisa selesai."""
    if not speed_limit:
        return float(settings.download_timeout_seconds)
    max_bytes, _ = _size_limit(media_type, settings)
    return max(float(settings.download_timeout_seconds), max_bytes / speed_limit * 1.2 + 60)


# ---------------------------------------------------------------------------------------------
# yt-dlp
# ---------------------------------------------------------------------------------------------


@dataclass
class _Control:
    """Sinyal antara event loop dan thread yt-dlp."""

    deadline: float
    max_bytes: int
    loop: asyncio.AbstractEventLoop
    stop: threading.Event = field(default_factory=threading.Event)
    reason: str | None = None

    def halt(self, reason: str) -> None:
        if self.reason is None:
            self.reason = reason
        self.stop.set()


class _Stopped(Exception):  # noqa: N818
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _run_ytdlp(
    job_id: uuid.UUID,
    url: str,
    media_type: str,
    tmp_path: Path,
    options: dict,
    sessions: SessionFactory,
    settings: Settings,
    source_url: str | None,
) -> tuple[bytes, int]:
    proxy = await get_guard_proxy(settings)
    loop = asyncio.get_running_loop()
    max_bytes, limit_label = _size_limit(media_type, settings)
    budget = _time_budget(media_type, settings, speed_limit_bytes(options, settings))
    control = _Control(deadline=time.monotonic() + budget, max_bytes=max_bytes, loop=loop)
    try:
        # Batas waktu juga diperiksa di dalam thread (progress hook); ini jaring pengaman bila
        # yt-dlp tertahan di fase tanpa progres (ekstraksi, koneksi).
        async with asyncio.timeout(budget + 60):
            return await asyncio.to_thread(
                _download_ytdlp_sync,
                url,
                media_type,
                tmp_path,
                options,
                job_id,
                sessions,
                settings,
                proxy.url,
                source_url,
                control,
            )
    except TimeoutError:
        control.halt("timeout")
        raise
    except asyncio.CancelledError:
        control.halt("shutdown")
        raise
    except _Stopped as exc:
        if exc.reason in INTERRUPT_STATUSES:
            raise JobInterrupted(exc.reason) from None
        if exc.reason == "timeout":
            raise TimeoutError from None
        if exc.reason == "too_large":
            raise AppError("file_too_large", f"Unduhan dihentikan: file melebihi batas {limit_label}.", 413) from None
        if exc.reason == "job_deleted":
            raise AppError("job_deleted", "Pekerjaan dihapus saat berjalan.", 410) from None
        raise AppError("download_failed", "Unduhan dihentikan.", 500) from None


def _find_output(info: dict | None) -> Path | None:
    """Path file akhir dari hasil yt-dlp (setelah merge/post-processing)."""
    if not info:
        return None
    for entry in (info, *(info.get("entries") or [])):
        if not isinstance(entry, dict):
            continue
        for dl in entry.get("requested_downloads") or []:
            path = dl.get("filepath") or dl.get("_filename")
            if path and Path(path).is_file():
                return Path(path)
        path = entry.get("filepath")
        if path and Path(path).is_file():
            return Path(path)
    return None


def _approx_size(info: dict) -> int | None:
    formats = info.get("requested_formats") or [info]
    sizes = [f.get("filesize") or f.get("filesize_approx") for f in formats]
    return sum(sizes) if sizes and all(sizes) else None


def _download_ytdlp_sync(
    url: str,
    media_type: str,
    tmp_path: Path,
    options: dict,
    job_id: uuid.UUID,
    sessions: SessionFactory,
    settings: Settings,
    proxy_url: str,
    source_url: str | None,
    control: _Control,
) -> tuple[bytes, int]:
    clean_url = url.split("#")[0]
    temp_dir = tmp_path.parent
    ffmpeg_bin = shutil.which("ffmpeg")
    last_report = 0.0

    def progress_hook(d: dict[str, Any]) -> None:
        nonlocal last_report
        if control.stop.is_set():
            raise yt_dlp.utils.DownloadCancelled(control.reason or "stopped")
        if time.monotonic() > control.deadline:
            control.halt("timeout")
            raise yt_dlp.utils.DownloadCancelled("timeout")
        if d.get("status") != "downloading":
            return
        downloaded = int(d.get("downloaded_bytes") or 0)
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if downloaded > control.max_bytes or (total and total > control.max_bytes * 1.05):
            control.halt("too_large")
            raise yt_dlp.utils.DownloadCancelled("too_large")
        now = time.monotonic()
        if now - last_report < YTDLP_PROGRESS_INTERVAL:
            return
        last_report = now
        future = asyncio.run_coroutine_threadsafe(_report_progress(sessions, job_id, downloaded, total), control.loop)
        try:
            status = future.result(timeout=10)
        except Exception as exc:  # noqa: BLE001 - progres gagal dicatat tidak menghentikan unduhan
            log.debug("gagal memperbarui progres %s: %s", job_id, exc)
            return
        if status is None:
            control.halt("job_deleted")
        elif status in INTERRUPT_STATUSES:
            control.halt(status)
        if control.stop.is_set():
            raise yt_dlp.utils.DownloadCancelled(control.reason or "stopped")

    referer = source_url if source_url and source_url != clean_url else None
    with cookiefile(options.get("cookies"), source_url or clean_url, temp_dir) as cookie_path:
        ydl_opts = base_options(
            proxy_url, headers=safe_headers(options.get("headers"), referer=referer), cookie_path=cookie_path
        ) | {
            "paths": {"home": str(temp_dir), "temp": str(temp_dir)},
            "outtmpl": f"{job_id.hex}_ytdlp.%(ext)s",
            "playlist_items": "1",
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 8,
            "abort_on_unavailable_fragments": True,
            "continuedl": True,
            "http_chunk_size": 10485760,
            "buffersize": 1024 * 1024,
            "updatetime": False,
            "progress_hooks": [progress_hook],
        }
        rate = speed_limit_bytes(options, settings)
        if rate:
            ydl_opts["ratelimit"] = rate
        if ffmpeg_bin:
            ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_bin).resolve().parent)
        if media_type == "audio":
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}
            ]
        else:
            ydl_opts["format"] = options.get("format_id") or "bestvideo+bestaudio/best"
            ydl_opts["merge_output_format"] = "mp4"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=False) or {}
                entry = (info.get("entries") or [info])[0] if info.get("_type") == "playlist" else info
                if isinstance(entry, dict):
                    if entry.get("is_live") or entry.get("live_status") == "is_live":
                        raise AppError(
                            "livestream_unsupported", "Siaran langsung (live stream) tidak dapat diunduh.", 422
                        )
                    duration = entry.get("duration")
                    max_seconds = settings.max_video_duration_minutes * 60
                    if duration and duration > max_seconds:
                        raise AppError(
                            "duration_limit_exceeded",
                            f"Durasi media ({int(duration // 60)} menit) melebihi batas "
                            f"{settings.max_video_duration_minutes} menit.",
                            422,
                        )
                    approx = _approx_size(entry)
                    if approx and approx > control.max_bytes:
                        control.halt("too_large")
                        raise _Stopped("too_large")
                result = ydl.process_ie_result(info, download=True)
        except yt_dlp.utils.DownloadCancelled as exc:
            raise _Stopped(control.reason or "stopped") from exc
        except yt_dlp.utils.YoutubeDLError as exc:
            if control.reason:
                raise _Stopped(control.reason) from exc
            clean_msg = str(exc).split("ERROR:")[-1].strip()
            if "tunnel connection failed: 403" in clean_msg.lower():
                raise AppError("unsafe_url", "Alamat media mengarah ke jaringan internal dan diblokir.", 422) from exc
            raise AppError("download_failed", f"Gagal mengunduh media: {clean_msg[:300]}", 502) from exc

    output = _find_output(result)
    if output is None:
        # Cadangan: file hasil dengan nama job, bukan file per-format (.fNNN.) atau parsial.
        candidates = [
            p
            for p in temp_dir.glob(f"{job_id.hex}_ytdlp.*")
            if not p.name.endswith((".part", ".ytdl", ".temp"))
            and ".part-" not in p.name
            and not _FORMAT_PART.fullmatch(p.suffixes[0] if p.suffixes else "")
        ]
        output = max(candidates, key=lambda p: p.stat().st_size) if candidates else None
    if output is None:
        raise AppError("download_failed", "File hasil unduhan tidak ditemukan di penyimpanan sementara.", 500)

    size = output.stat().st_size
    if size > control.max_bytes:
        raise _Stopped("too_large")
    output.replace(tmp_path)
    for leftover in temp_dir.glob(f"{job_id.hex}_ytdlp*"):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            log.debug("gagal menghapus sisa yt-dlp %s", leftover.name)
    with tmp_path.open("rb") as fh:  # H-04: cukup 4 KB untuk deteksi tipe
        head = fh.read(SNIFF_BYTES)
    return head, size


async def _report_progress(
    sessions: SessionFactory, job_id: uuid.UUID, downloaded: int, total: int | None
) -> str | None:
    """Mencatat progres yt-dlp. Mengembalikan status job terkini (None bila job dihapus).

    Status akhir/jeda/batal tidak pernah ditimpa, sehingga job yang ditandai gagal oleh
    pembersihan otomatis atau dijeda pengguna tidak "hidup lagi".
    """
    async with sessions() as s:
        job = await s.get(DownloadJob, job_id)
        if job is None:
            return None
        if job.status in (*TERMINAL_STATUSES, *INTERRUPT_STATUSES):
            return job.status
        job.status = "downloading"
        job.size_downloaded = downloaded
        if total and total > 0:
            job.size_total = int(total)
        await s.commit()
        return job.status


# ---------------------------------------------------------------------------------------------
# HTTP langsung (satu koneksi atau multi-koneksi)
# ---------------------------------------------------------------------------------------------

MIN_SEGMENT_BYTES = 2 * 1024 * 1024
SEGMENT_RETRIES = 3


def _size_limit(media_type: str, settings: Settings) -> tuple[int, str]:
    if media_type == "subtitle":
        return min(settings.max_subtitle_bytes, settings.max_download_bytes), f"{settings.max_subtitle_size_mb} MB"
    return settings.max_download_bytes, f"{settings.max_download_size_mb} MB"


def speed_limit_bytes(options: dict, settings: Settings) -> int:
    """Batas kecepatan job dalam byte/detik (0 = tanpa batas)."""
    kbps = options.get("max_speed_kbps") or settings.download_speed_limit_kbps
    return int(kbps) * 1024 if kbps else 0


class RateLimiter:
    """Token bucket async; dipakai bersama oleh semua koneksi satu unduhan."""

    def __init__(self, bytes_per_second: int) -> None:
        self.rate = float(bytes_per_second)
        self.tokens = self.rate
        self.last = time.monotonic()
        self._lock = asyncio.Lock()

    async def consume(self, amount: int) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.rate, self.tokens + (now - self.last) * self.rate)
                self.last = now
                # Potongan lebih besar dari kapasitas bucket diizinkan dengan "utang" token.
                if self.tokens >= amount or self.tokens >= self.rate:
                    self.tokens -= amount
                    return
                await asyncio.sleep((min(amount, self.rate) - self.tokens) / self.rate)


def _content_range(value: str | None) -> tuple[int, int | None] | None:
    """`bytes START-END/TOTAL` → (START, TOTAL)."""
    if not value or not value.startswith("bytes "):
        return None
    try:
        span, _, total = value[6:].partition("/")
        start = int(span.split("-", 1)[0])
        return start, (int(total) if total.isdigit() else None)
    except ValueError:
        return None


def _sidecar(tmp_path: Path) -> Path:
    """Status segmen unduhan multi-koneksi (untuk jeda/lanjut)."""
    return tmp_path.with_name(tmp_path.name.removesuffix(".part") + ".segments.json")


class _RangeUnsupported(Exception):  # noqa: N818
    """Server tidak menghormati Range saat unduhan multi-koneksi; ulang dengan satu koneksi."""


async def _stream_to_file(
    job_id: uuid.UUID,
    url: str,
    media_type: str,
    tmp_path: Path,
    sessions: SessionFactory,
    settings: Settings,
    referer: str | None = None,
    cookies: str | None = None,
    custom_headers: dict[str, str] | None = None,
    speed_limit: int = 0,
    allow_segments: bool = True,
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
    if custom_headers:
        headers.update(custom_headers)
    jar = parse_cookies(cookies, referer or url)
    limiter = RateLimiter(speed_limit) if speed_limit else None
    sidecar = _sidecar(tmp_path)

    if allow_segments and await asyncio.to_thread(sidecar.is_file):
        try:
            return await _segmented_download(
                job_id, url, None, tmp_path, headers, jar, sessions, settings, max_bytes, limit_label, limiter
            )
        except _RangeUnsupported:
            await asyncio.to_thread(remove_partials, settings.temp_dir, job_id)

    # Lanjutkan unduhan satu-koneksi yang dijeda: minta sisa file dengan Range.
    offset = await asyncio.to_thread(lambda: tmp_path.stat().st_size if tmp_path.exists() else 0)
    if offset:
        headers["Range"] = f"bytes={offset}-"

    segmented_total: int | None = None
    segmented_url = url
    async with (
        build_client(settings) as client,
        open_stream(client, url, settings, headers=headers, cookies=jar) as (resp, final_url),
    ):
        if resp.status_code == 416 and offset:
            # Server menolak Range: file parsial dianggap tidak valid, ulang dari awal.
            await asyncio.to_thread(tmp_path.unlink, missing_ok=True)
            raise TransientError("Unduhan lanjutan ditolak server; diulang dari awal.", code="resume_rejected")
        if resp.status_code >= 400:
            raise status_error(resp.status_code, subject="File")

        resumed = False
        total: int | None = None
        if offset and resp.status_code == 206:
            cr = _content_range(resp.headers.get("content-range"))
            if cr and cr[0] == offset:
                resumed, total = True, cr[1]
        if not resumed:
            offset = 0
            length = resp.headers.get("content-length")
            # Content-Length dari respons terkompresi bukan ukuran file sebenarnya.
            total = int(length) if length and length.isdigit() and not is_encoded(resp) else None
        if total is not None and total > max_bytes:
            raise AppError(
                "file_too_large",
                f"Ukuran file ({total / 1_048_576:.1f} MB) melebihi batas {limit_label}.",
                413,
            )

        # Multi-koneksi (seperti IDM/1DM): file besar dengan dukungan Range dipecah ke beberapa
        # koneksi paralel. Respons pertama ditutup tanpa membaca body-nya.
        if (
            allow_segments
            and not resumed
            and resp.status_code == 200
            and total is not None
            and total >= settings.multi_connection_min_mb * 1024 * 1024
            and settings.download_connections > 1
            and resp.headers.get("accept-ranges", "").lower() == "bytes"
            and not is_encoded(resp)
        ):
            segmented_total, segmented_url = total, final_url
        else:
            await check_storage_capacity(
                sessions, settings, incoming=(total - offset) if total is not None else None, exclude=tmp_path
            )
            await _update(sessions, job_id, status="downloading", size_total=total, size_downloaded=offset)

            written = offset
            head = b""
            if resumed:
                head = await asyncio.to_thread(_read_head, tmp_path)
            buffer = bytearray()
            last_report = time.monotonic()
            fh = await asyncio.to_thread(tmp_path.open, "ab" if resumed else "wb")
            try:
                async for chunk in iter_body(resp, CHUNK):
                    written += len(chunk)
                    if written > max_bytes:
                        raise AppError("file_too_large", f"Unduhan dihentikan: file melebihi batas {limit_label}.", 413)
                    if limiter:
                        await limiter.consume(len(chunk))
                    if len(head) < SNIFF_BYTES:
                        head += chunk[: SNIFF_BYTES - len(head)]
                    buffer += chunk
                    if len(buffer) >= WRITE_BUFFER:
                        await asyncio.to_thread(fh.write, bytes(buffer))
                        buffer.clear()
                    if time.monotonic() - last_report >= PROGRESS_INTERVAL:
                        last_report = time.monotonic()
                        try:
                            await _update(sessions, job_id, size_downloaded=written)
                        except JobInterrupted:
                            # Simpan yang sudah diterima agar bisa dilanjutkan.
                            if buffer:
                                await asyncio.to_thread(fh.write, bytes(buffer))
                                buffer.clear()
                            raise
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

    try:
        return await _segmented_download(
            job_id,
            segmented_url,
            segmented_total,
            tmp_path,
            headers,
            jar,
            sessions,
            settings,
            max_bytes,
            limit_label,
            limiter,
        )
    except _RangeUnsupported:
        log.info("server %s tidak menghormati Range; beralih ke satu koneksi", redact_url(url))
        await asyncio.to_thread(remove_partials, settings.temp_dir, job_id)
        return await _stream_to_file(
            job_id,
            url,
            media_type,
            tmp_path,
            sessions,
            settings,
            referer=referer,
            cookies=cookies,
            custom_headers=custom_headers,
            speed_limit=speed_limit,
            allow_segments=False,
        )


def _write_at(path: Path, position: int, data: bytes) -> None:
    with path.open("r+b") as fh:
        fh.seek(position)
        fh.write(data)


def _prepare_segments(tmp_path: Path, sidecar: Path, url: str, total: int, connections: int) -> list[list[int]]:
    count = max(1, min(connections, total // MIN_SEGMENT_BYTES))
    size = -(-total // count)  # pembulatan ke atas
    segments = [[start, min(start + size, total) - 1, 0] for start in range(0, total, size)]
    with tmp_path.open("wb") as fh:
        fh.truncate(total)
    sidecar.write_text(json.dumps({"url": url, "total": total, "segments": segments}), encoding="utf-8")
    return segments


def _save_sidecar(sidecar: Path, url: str, total: int, segments: list[list[int]]) -> None:
    tmp = sidecar.with_name(sidecar.name + ".tmp")
    tmp.write_text(json.dumps({"url": url, "total": total, "segments": segments}), encoding="utf-8")
    os.replace(tmp, sidecar)


async def _segmented_download(
    job_id: uuid.UUID,
    url: str,
    total: int | None,
    tmp_path: Path,
    headers: dict[str, str],
    jar: list[Cookie],
    sessions: SessionFactory,
    settings: Settings,
    max_bytes: int,
    limit_label: str,
    limiter: RateLimiter | None,
) -> tuple[bytes, int]:
    """Unduhan multi-koneksi: setiap segmen diminta dengan Range dan ditulis ke posisinya sendiri.

    Status segmen disimpan di file sidecar sehingga jeda/retry melanjutkan setiap segmen dari
    posisi terakhirnya. Setiap koneksi tetap lewat `open_stream` (validasi SSRF per hop).
    """
    sidecar = _sidecar(tmp_path)
    if total is None:
        try:
            state = json.loads(await asyncio.to_thread(sidecar.read_text, encoding="utf-8"))
            total, segments, url = int(state["total"]), [list(map(int, s)) for s in state["segments"]], state["url"]
            if not await asyncio.to_thread(lambda: tmp_path.is_file() and tmp_path.stat().st_size == total):
                raise ValueError("ukuran file parsial tidak cocok")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise _RangeUnsupported from exc
        validate_url(url, settings.port_allowlist)
    else:
        if total > max_bytes:
            raise AppError("file_too_large", f"Ukuran file melebihi batas {limit_label}.", 413)
        segments = await asyncio.to_thread(
            _prepare_segments, tmp_path, sidecar, url, total, settings.download_connections
        )

    done_bytes = sum(s[2] for s in segments)
    await check_storage_capacity(sessions, settings, incoming=total - done_bytes, exclude=tmp_path)
    await _update(sessions, job_id, status="downloading", size_total=total, size_downloaded=done_bytes)

    async def fetch(client: httpx.AsyncClient, seg: list[int]) -> None:
        start, end = seg[0], seg[1]
        failures = 0
        while start + seg[2] <= end:
            before = seg[2]
            pos = start + seg[2]
            seg_headers = {**headers, "Range": f"bytes={pos}-{end}"}
            buffer = bytearray()
            buffer_pos = pos
            error: Exception | None = None
            try:
                async with open_stream(client, url, settings, headers=seg_headers, cookies=jar) as (resp, _final):
                    if resp.status_code in (200, 416):
                        raise _RangeUnsupported
                    if resp.status_code != 206:
                        raise status_error(resp.status_code, subject="File")
                    cr = _content_range(resp.headers.get("content-range"))
                    if not cr or cr[0] != pos:
                        raise _RangeUnsupported
                    async for chunk in iter_body(resp, CHUNK):
                        chunk = chunk[: end - (start + seg[2]) + 1]
                        if not chunk:
                            break
                        if limiter:
                            await limiter.consume(len(chunk))
                        buffer += chunk
                        seg[2] += len(chunk)
                        if len(buffer) >= WRITE_BUFFER:
                            await asyncio.to_thread(_write_at, tmp_path, buffer_pos, bytes(buffer))
                            buffer_pos += len(buffer)
                            buffer.clear()
                        if start + seg[2] > end:
                            break
            except (TransientError, httpx.HTTPError) as exc:
                error = exc
            finally:
                if buffer:
                    await asyncio.to_thread(_write_at, tmp_path, buffer_pos, bytes(buffer))
            if start + seg[2] > end:
                return
            # Koneksi putus/ditutup lebih awal: lanjutkan dari posisi terakhir. Hanya percobaan
            # tanpa kemajuan sama sekali yang dihitung gagal.
            failures = failures + 1 if seg[2] == before else 0
            if failures > SEGMENT_RETRIES:
                raise TransientError("Salah satu koneksi unduhan terus terputus.", code="segment_failed") from error
            await asyncio.sleep(min(2**failures, 8) if failures else 0)

    async def reporter() -> None:
        while True:
            await asyncio.sleep(PROGRESS_INTERVAL)
            await asyncio.to_thread(_save_sidecar, sidecar, url, total, segments)
            await _update(sessions, job_id, size_downloaded=sum(s[2] for s in segments))

    pending = [s for s in segments if s[0] + s[2] <= s[1]]
    async with build_client(settings) as client:
        report_task = asyncio.create_task(reporter())
        workers = [asyncio.create_task(fetch(client, seg)) for seg in pending]
        all_workers = asyncio.gather(*workers)
        try:
            # Selesai bila semua segmen selesai, atau berhenti begitu satu segmen gagal atau
            # reporter mendeteksi jeda/batal (JobInterrupted).
            done, _ = await asyncio.wait([all_workers, report_task], return_when=asyncio.FIRST_COMPLETED)
            if report_task in done:
                report_task.result()
            all_workers.result()
        finally:
            for task in (*workers, report_task):
                task.cancel()
            await asyncio.gather(*workers, report_task, return_exceptions=True)
            all_workers.cancel()
            await asyncio.to_thread(_save_sidecar, sidecar, url, total, segments)

    written = sum(s[2] for s in segments)
    if written < total:
        raise TransientError("Unduhan terputus sebelum file lengkap.", code="incomplete")
    await asyncio.to_thread(sidecar.unlink, missing_ok=True)
    await _update(sessions, job_id, size_downloaded=total, size_total=total)
    return await asyncio.to_thread(_read_head, tmp_path), total


def _read_head(path: Path) -> bytes:
    with path.open("rb") as fh:
        return fh.read(SNIFF_BYTES)


# ---------------------------------------------------------------------------------------------
# Finalisasi
# ---------------------------------------------------------------------------------------------


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
        if job is None or job.status == "cancelled":  # dihapus/dibatalkan saat berjalan
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
        # URL dan kredensial tidak lagi dibutuhkan setelah selesai; buang query string yang bisa
        # berisi token (PRD §11) dan cookie/header pengguna (H-02).
        job.media_url = redact_url(job.media_url)
        job.options = strip_secrets(job.options)
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


async def check_storage_capacity(
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
    """Memperbarui job yang sedang berjalan; berhenti bila pengguna menjeda/membatalkannya."""
    async with sessions() as s:
        job = await s.get(DownloadJob, job_id)
        if job is None:
            raise AppError("job_deleted", "Pekerjaan dihapus saat berjalan.", 410)
        if job.status in INTERRUPT_STATUSES:
            raise JobInterrupted(job.status)
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
        if job is None or job.status in INTERRUPT_STATUSES:
            return
        job.status = "failed"
        job.error_message = message
        job.completed_at = utcnow()
        s.add(DownloadHistory(job_id=job_id, action="failed", details={"error": message}))
        await s.commit()
    log.info("download %s gagal: %s", job_id, message)
