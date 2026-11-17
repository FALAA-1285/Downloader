"""Skema request/response API (PRD §12). Bentuknya mengikuti tipe di frontend (`types/index.ts`)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

MediaType = Literal["image", "video", "audio", "subtitle", "text"]
JobStatus = Literal["pending", "processing", "downloading", "completed", "failed"]
SourceType = Literal["generic", "youtube", "instagram", "tiktok", "x"]


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    media_types: list[MediaType] = Field(default_factory=list, max_length=5)


class SourceInfo(BaseModel):
    type: SourceType
    domain: str
    name: str


class PageInfo(BaseModel):
    url: str
    final_url: str | None = None
    title: str | None = None
    description: str | None = None
    thumbnail: str | None = None


class MediaItem(BaseModel):
    id: str
    type: MediaType
    filename: str
    url: str
    mime_type: str | None = None
    size: int | None = None
    downloadable: bool = True
    reason: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    language: str | None = None
    preview_url: str | None = None


class TextContent(BaseModel):
    title: str | None = None
    content: str | None = None
    word_count: int = 0


class AnalyzeResponse(BaseModel):
    id: uuid.UUID
    success: bool = True
    source: SourceInfo
    page: PageInfo
    media: list[MediaItem]
    text: TextContent | None = None
    warnings: list[str] = Field(default_factory=list)
    analyzed_at: datetime


class AnalysisJob(BaseModel):
    """GET /jobs/{id}: analisis berjalan sinkron, jadi status selalu `completed`."""

    id: uuid.UUID
    status: Literal["completed"] = "completed"
    source_url: str
    source_domain: str
    platform: str
    title: str | None
    media_count: dict[str, int]
    created_at: datetime
    expires_at: datetime


class CreateDownloadsRequest(BaseModel):
    analysis_id: uuid.UUID
    media_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(min_length=1, max_length=50)
    subtitle_format: Literal["original", "srt"] = "original"


class DownloadJobOut(BaseModel):
    id: uuid.UUID
    status: JobStatus
    progress: int | None
    filename: str
    media_type: MediaType
    source_url: str
    source_domain: str
    size_downloaded: int
    size_total: int | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None


class AdapterOut(BaseModel):
    id: str
    name: str
    domains: list[str]
    status: Literal["active", "evaluating", "disabled"]
    note: str


class ConfigOut(BaseModel):
    max_download_size_mb: int
    download_timeout_seconds: int
    file_retention_hours: int
    storage_path: str
    version: str
    queue_backend: str


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    queue: bool
    version: str
