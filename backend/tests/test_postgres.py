"""Integration test terhadap PostgreSQL sungguhan (JSONB, timezone, constraint).

Dilewati kecuali `TEST_DATABASE_URL` diset, mis.:
    TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5432/media_downloader_test uv run pytest -m postgres
Database harus kosong/khusus test: tabel dibuat dan dihapus oleh test ini.
"""

from __future__ import annotations

import os

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from app.models import Base
from app.models.db import make_engine
from app.models.models import DownloadJob
from tests.test_api import PNG, analyze, by_name, mock_site

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL tidak diset"),
]


@pytest.fixture
async def pg_app(settings):
    pg_settings = settings.model_copy(update={"database_url": DATABASE_URL})
    engine = make_engine(pg_settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    application = create_app(pg_settings)
    async with application.router.lifespan_context(application):
        yield application
    engine = make_engine(pg_settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def test_full_flow_on_postgres(pg_app, web):
    transport = httpx.ASGITransport(app=pg_app, client=("127.0.0.1", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers={"X-UMD-Client": "t"}) as c:
        mock_site(web)
        data = (await analyze(c)).json()
        ok = by_name(data, "ok.png")
        jobs = (await c.post("/api/v1/downloads", json={"analysis_id": data["id"], "media_ids": [ok["id"]]})).json()
        await pg_app.state.queue.drain()

        job = (await c.get(f"/api/v1/downloads/{jobs[0]['id']}")).json()
        assert job["status"] == "completed"
        assert job["created_at"].endswith("Z") or "+00:00" in job["created_at"]  # timezone-aware
        assert (await c.get(f"/api/v1/downloads/{jobs[0]['id']}/file")).content == PNG
        stored = (await c.get(f"/api/v1/jobs/{data['id']}/media")).json()  # JSONB round-trip
        assert stored["media"] == data["media"]
        assert (await c.get("/api/v1/history", params={"q": "OK.PNG"})).json()[0]["id"] == jobs[0]["id"]  # ilike


async def test_status_check_constraint(pg_app):
    async with pg_app.state.sessions() as s:
        s.add(
            DownloadJob(
                media_id="x",
                source_url="https://a.example/",
                media_url="https://a.example/x.png",
                source_domain="a.example",
                platform="generic",
                media_type="image",
                filename="x.png",
                status="bogus",
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
