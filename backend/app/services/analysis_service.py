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
from app.core.errors import AppError, UnsafeURLError
from app.core.http_client import build_client
from app.core.url_guard import validate_url
from app.extractors.text import word_count
from app.models.models import Analysis, aware, utcnow
from app.schemas.api import AnalysisJob, AnalyzeResponse, MediaItem, PageInfo, SourceInfo, TextContent

log = logging.getLogger(__name__)


class AnalysisService:
    def __init__(self, settings: Settings, registry: AdapterRegistry) -> None:
        self.settings = settings
        self.registry = registry
        self._semaphore = asyncio.Semaphore(settings.analyze_concurrency)

    def _safe_preview(self, url: str | None) -> str | None:
        """URL pratinjau dimuat langsung oleh browser pengguna, jadi harus lolos aturan SSRF yang sama.

        Thumbnail dan poster dari halaman tak tepercaya bisa menunjuk ke perangkat LAN
        (mis. `http://192.168.1.1/...`); URL seperti itu dibuang (M-02).
        """
        if not url:
            return None
        try:
            return validate_url(url, self.settings.port_allowlist).url
        except UnsafeURLError:
            return None

    async def analyze(self, session: AsyncSession, raw_url: str, media_types: list[str]) -> AnalyzeResponse:
        target = validate_url(raw_url, self.settings.port_allowlist)
        adapter = self.registry.resolve(target.domain, url=target.url)
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
                thumbnail=self._safe_preview(outcome.thumbnail),
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
                    preview_url=self._safe_preview(c.preview_url) if c.downloadable or c.type != "image" else None,
                    options=c.options,
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


async def load_analysis(session: AsyncSession, analysis_id: uuid.UUID) -> Analysis:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None or aware(analysis.expires_at) < utcnow():
        raise AppError("analysis_not_found", "Hasil analisis tidak ditemukan atau sudah kedaluwarsa.", 404)
    return analysis


def summarize(analysis: Analysis) -> AnalysisJob:
    counts: dict[str, int] = {}
    for item in analysis.result.get("media", []):
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    if (analysis.result.get("text") or {}).get("content"):
        counts["text"] = 1
    return AnalysisJob(
        id=analysis.id,
        source_url=analysis.source_url,
        source_domain=analysis.source_domain,
        platform=analysis.platform,
        title=analysis.title,
        media_count=counts,
        created_at=aware(analysis.created_at),
        expires_at=aware(analysis.expires_at),
    )
