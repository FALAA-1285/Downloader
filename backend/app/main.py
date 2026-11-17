"""Entry point FastAPI: `uvicorn app.main:app`."""

from __future__ import annotations

import asyncio
import contextlib
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
from app.models.db import make_engine, make_session_factory
from app.services.analysis_service import AnalysisService
from app.services.cleanup import run_cleanup
from app.workers.queue import make_queue

log = logging.getLogger("app")

FIELD_LABELS = {"url": "URL", "media_types": "jenis media", "media_ids": "pilihan media", "analysis_id": "ID analisis"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
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
        return _error(422, "invalid_request", f"Nilai {field} tidak valid.")

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return _error(500, "internal_error", "Terjadi kesalahan di server. Coba lagi.")

    for router in (analyze.router, downloads.router, history.router, system.router):
        app.include_router(router, prefix="/api/v1")

    return app


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
