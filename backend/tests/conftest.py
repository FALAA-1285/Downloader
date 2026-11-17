from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import respx

from app.core.config import Settings
from app.main import create_app
from app.models import Base
from app.models.db import make_engine

PUBLIC_IP = "93.184.216.34"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        storage_path=tmp_path / "storage",
        queue_backend="inline",
        cleanup_interval_seconds=0,
        allowed_hosts="testserver,localhost",
        max_download_size_mb=1,
        max_storage_mb=10,
        download_max_retries=1,
        probe_budget_seconds=5,
        rate_limit_analyze_per_minute=100,
        ffprobe_path="__no_ffprobe__",
    )


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Semua domain dianggap publik kecuali yang diatur test; tanpa DNS sungguhan."""

    async def fake_getaddrinfo(self, host, port, *args, **kwargs):
        ip = PUBLIC_IP
        if "internal-rebind" in str(host):
            ip = "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    import asyncio

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)


@pytest.fixture
async def app(settings: Settings):
    engine = make_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", headers={"X-UMD-Client": "test"}
    ) as c:
        yield c


@pytest.fixture
def web() -> AsyncIterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router
