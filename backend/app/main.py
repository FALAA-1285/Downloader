"""Entry point FastAPI: `uvicorn app.main:app`."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import ipaddress
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.adapters.registry import AdapterRegistry
from app.api.routes import analyze, downloads, history, system
from app.core.config import APP_VERSION, Settings, get_settings
from app.core.errors import AppError
from app.core.ratelimit import RateLimiter
from app.core.url_guard import install_doh_socket_patch
from app.models.db import make_engine, make_session_factory
from app.services.analysis_service import AnalysisService
from app.services.cleanup import run_cleanup
from app.workers.queue import make_queue

# Pasang socket monkeypatch sedini mungkin agar semua request HTTP/DoH/yt-dlp
# bebas dari gangguan pembajakan DNS lokal ISP.
install_doh_socket_patch()

log = logging.getLogger("app")

# Header wajib untuk request yang mengubah data. Header kustom memaksa preflight CORS,
# sehingga situs lain tidak bisa memicu POST/DELETE ke API lokal lewat "simple request".
CLIENT_HEADER = "X-UMD-Client"
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_PATHS = {"/api/v1/health"}

FIELD_LABELS = {"url": "URL", "media_types": "jenis media", "media_ids": "pilihan media", "analysis_id": "ID analisis"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Logger httpx/httpcore mencatat URL lengkap (termasuk query yang bisa berisi token).
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.downloads_dir.mkdir(parents=True, exist_ok=True)
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        engine = make_engine(settings)
        sessions = make_session_factory(engine)
        queue = make_queue(settings, sessions)
        registry = AdapterRegistry(settings.disabled_adapter_ids)

        app.state.settings = settings
        app.state.engine = engine
        app.state.sessions = sessions
        app.state.queue = queue
        app.state.registry = registry
        app.state.analysis = AnalysisService(settings, registry)
        app.state.rate_limiter = RateLimiter()

        await queue.startup()
        cleanup_task = asyncio.create_task(_cleanup_loop(app)) if settings.cleanup_interval_seconds > 0 else None
        log.info("Universal Media Downloader API %s siap (queue=%s)", APP_VERSION, queue.name)
        try:
            yield
        finally:
            if cleanup_task:
                cleanup_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cleanup_task
            await queue.shutdown()
            await engine.dispose()

    app = FastAPI(
        title="Universal Media Downloader API",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )
    app.state.settings = settings

    # Urutan: middleware yang ditambahkan terakhir dijalankan pertama.
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_request_body_kb * 1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Authorization", CLIENT_HEADER],
        max_age=600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    networks = settings.client_networks

    @app.middleware("http")
    async def network_guard(request: Request, call_next):
        """Hanya klien dari jaringan tepercaya yang dilayani (NFR-01, §15.3)."""
        host = request.client.host if request.client else None
        try:
            ip = ipaddress.ip_address(host) if host else None
        except ValueError:
            ip = None
        if ip is not None and not any(ip in net for net in networks):
            return _error(403, "client_forbidden", "Akses dari jaringan ini tidak diizinkan.")
        path = request.url.path
        if path.startswith("/api/") and request.method != "OPTIONS":
            if settings.api_token and path not in PUBLIC_PATHS:
                supplied = request.headers.get("authorization", "")
                if not hmac.compare_digest(supplied.encode(), f"Bearer {settings.api_token}".encode()):
                    return _error(401, "unauthorized", "Token API tidak valid atau tidak dikirim.")
            if request.method in MUTATING_METHODS and not request.headers.get(CLIENT_HEADER):
                return _error(403, "client_header_missing", f"Header {CLIENT_HEADER} wajib untuk permintaan ini.")
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = [str(p) for p in first.get("loc", []) if p not in ("body", "query", "path")]
        field = FIELD_LABELS.get(loc[0], loc[0]) if loc else "permintaan"
        msg = first.get("msg") or ""
        clean_msg = msg.replace("Value error, ", "").strip()
        detail = f"Nilai {field} tidak valid ({clean_msg})." if clean_msg else f"Nilai {field} tidak valid."
        return _error(422, "invalid_request", detail)

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return _error(500, "internal_error", "Terjadi kesalahan di server. Coba lagi.")

    for router in (analyze.router, downloads.router, history.router, system.router):
        app.include_router(router, prefix="/api/v1")

    return app


class BodyLimitMiddleware:
    """Menolak body request yang lebih besar dari batas (NFR-01), termasuk body chunked."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope.get("headers") or []).get(b"content-length")
        if length is not None and length.isdigit() and int(length) > self.max_bytes:
            await _error(413, "body_too_large", "Ukuran permintaan terlalu besar.")(scope, receive, send)
            return

        received = 0
        rejected = False

        async def limited_receive():
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request" and not rejected:
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Kirim 413 sekarang, lalu putuskan body untuk aplikasi; respons aplikasi dibuang.
                    rejected = True
                    await _error(413, "body_too_large", "Ukuran permintaan terlalu besar.")(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            if not rejected:
                await send(message)

        await self.app(scope, limited_receive, guarded_send)


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"detail": {"code": code, "message": message}}, status_code=status, headers=headers)


async def _cleanup_loop(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    while True:
        try:
            await run_cleanup(app.state.sessions, settings)
        except Exception:
            log.exception("cleanup gagal")
        await asyncio.sleep(settings.cleanup_interval_seconds)


app = create_app()
