from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import AnalysisDep, SessionDep, rate_limit
from app.schemas.api import AnalysisJob, AnalyzeRequest, AnalyzeResponse
from app.services import analysis_service

router = APIRouter(tags=["analyze"])


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    dependencies=[rate_limit("analyze", "rate_limit_analyze_per_minute")],
)
async def analyze(body: AnalyzeRequest, session: SessionDep, service: AnalysisDep) -> AnalyzeResponse:
    """Menganalisis URL dan mengembalikan media yang dapat diakses (FR-01 s.d. FR-07)."""
    return await service.analyze(session, body.url, list(body.media_types))


@router.get("/jobs/{job_id}", response_model=AnalysisJob)
async def get_analysis_job(job_id: uuid.UUID, session: SessionDep) -> AnalysisJob:
    """Ringkasan hasil analisis. Analisis berjalan sinkron, jadi statusnya selalu `completed`."""
    return analysis_service.summarize(await analysis_service.load_analysis(session, job_id))


@router.get("/jobs/{job_id}/media", response_model=AnalyzeResponse)
async def get_analysis_media(job_id: uuid.UUID, session: SessionDep) -> AnalyzeResponse:
    analysis = await analysis_service.load_analysis(session, job_id)
    return AnalyzeResponse.model_validate(analysis.result)
