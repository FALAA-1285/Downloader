from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.registry import AdapterRegistry
from app.core.config import Settings
from app.core.ratelimit import RateLimiter
from app.services.analysis_service import AnalysisService
from app.workers.queue import DownloadQueue


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_queue(request: Request) -> DownloadQueue:
    return request.app.state.queue


def get_registry(request: Request) -> AdapterRegistry:
    return request.app.state.registry


def get_analysis_service(request: Request) -> AnalysisService:
    return request.app.state.analysis


def rate_limit(bucket: str, setting: str):
    def dependency(request: Request) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        limit: int = getattr(request.app.state.settings, setting)
        client = request.client.host if request.client else "unknown"
        limiter.check(f"{bucket}:{client}", limit)

    return Depends(dependency)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
QueueDep = Annotated[DownloadQueue, Depends(get_queue)]
RegistryDep = Annotated[AdapterRegistry, Depends(get_registry)]
AnalysisDep = Annotated[AnalysisService, Depends(get_analysis_service)]
