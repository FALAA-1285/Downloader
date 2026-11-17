from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import AnalysisDep, SessionDep, rate_limit
from app.core.errors import AppError
from app.models.models import Analysis, aware, utcnow
from app.schemas.api import AnalysisJob, AnalyzeRequest, AnalyzeResponse

router = APIRouter(tags=["analyze"])


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    dependencies=[rate_limit("analyze", "rate_limit_analyze_per_minute")],
)
async def analyze(body: AnalyzeRequest, session: SessionDep, service: AnalysisDep) -> AnalyzeResponse:
    """Menganalisis URL dan mengembalikan media yang dapat diakses (FR-01 s.d. FR-07)."""
    return await service.analyze(session, body.url, list(body.media_types))


async def _load(session: SessionDep, job_id: uuid.UUID) -> Analysis:
    analysis = await session.scalar(select(Analysis).where(Analysis.id == job_id))
    if analysis is None or aware(analysis.expires_at) < utcnow():
        raise AppError("analysis_not_found", "Hasil analisis tidak ditemukan atau sudah kedaluwarsa.", 404)
    return analysis


@router.get("/jobs/{job_id}", response_model=AnalysisJob)
async def get_analysis_job(job_id: uuid.UUID, session: SessionDep) -> AnalysisJob:
    analysis = await _load(session, job_id)
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


@router.get("/jobs/{job_id}/media", response_model=AnalyzeResponse)
async def get_analysis_media(job_id: uuid.UUID, session: SessionDep) -> AnalyzeResponse:
    analysis = await _load(session, job_id)
    return AnalyzeResponse.model_validate(analysis.result)
