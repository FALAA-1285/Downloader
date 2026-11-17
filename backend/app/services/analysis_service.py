"""Alur analisis (PRD §7.1): validasi → deteksi sumber → adapter → ekstraksi → simpan hasil."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AnalysisContext
from app.adapters.registry import AdapterRegistry
from app.core.config import Settings
from app.core.errors import AppError
from app.core.http_client import build_client
from app.core.url_guard import validate_url
from app.extractors.text import word_count
from app.models.models import Analysis, utcnow
from app.schemas.api import AnalyzeResponse, MediaItem, PageInfo, SourceInfo, TextContent

log = logging.getLogger(__name__)


class AnalysisService:
    def __init__(self, settings: Settings, registry: AdapterRegistry) -> None:
        self.settings = settings
        self.registry = registry
        self._semaphore = asyncio.Semaphore(settings.analyze_concurrency)

    async def analyze(self, session: AsyncSession, raw_url: str, media_types: list[str]) -> AnalyzeResponse:
        target = validate_url(raw_url, self.settings.port_allowlist)
        adapter = self.registry.resolve(target.domain)
        if adapter is self.registry.generic and "generic" in self.registry.disabled:
            raise AppError("adapter_disabled", "Analisis website umum sedang dinonaktifkan.", 503)

        async with self._semaphore, build_client(self.settings) as client:
            ctx = AnalysisContext(
                url=target.url,
                domain=target.domain,
                media_types=set(media_types),
                client=client,
                settings=self.settings,
            )
            try:
                outcome = await asyncio.wait_for(adapter.analyze(ctx), self.settings.analyze_timeout_seconds)
            except TimeoutError as exc:
                raise AppError(
                    "analyze_timeout",
                    "Analisis melewati batas waktu. Coba lagi atau gunakan URL lain.",
                    504,
                ) from exc

        now = utcnow()
        analysis_id = uuid.uuid4()
        text = None
        if outcome.text_content is not None:
            text = TextContent(
                title=outcome.text_title,
                content=outcome.text_content,
                word_count=word_count(outcome.text_content),
            )
        result = AnalyzeResponse(
            id=analysis_id,
            source=SourceInfo(type=adapter.source_type, domain=target.domain, name=adapter.name),
            page=PageInfo(
                url=target.url,
                final_url=outcome.final_url if outcome.final_url != target.url else None,
                title=outcome.title,
                description=outcome.description,
                thumbnail=outcome.thumbnail,
            ),
            media=[
                MediaItem(
                    id=c.id,
                    type=c.type,
                    filename=c.filename,
                    url=c.url,
                    mime_type=c.mime_type,
                    size=c.size,
                    downloadable=c.downloadable,
                    reason=c.reason,
                    width=c.width,
                    height=c.height,
                    duration=c.duration,
                    language=c.language,
                    preview_url=c.preview_url if c.downloadable or c.type != "image" else None,
                )
                for c in outcome.media
            ],
            text=text,
            warnings=list(dict.fromkeys(outcome.warnings)),
            analyzed_at=now,
        )

        session.add(
            Analysis(
                id=analysis_id,
                source_url=target.url,
                source_domain=target.domain,
                platform=adapter.source_type,
                title=outcome.title,
                result=result.model_dump(mode="json"),
                created_at=now,
                expires_at=now + timedelta(hours=self.settings.analysis_retention_hours),
            )
        )
        await session.commit()
        log.info("analysis %s: %s media from %s", analysis_id, len(result.media), target.domain)
        return result
