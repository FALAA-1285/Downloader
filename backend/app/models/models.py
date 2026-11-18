"""Skema database (PRD §11), ditambah tabel `analyses` untuk menyimpan hasil analisis
sehingga pekerjaan unduhan hanya bisa dibuat dari media yang benar-benar ditemukan server.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")

JOB_STATUSES = ("pending", "processing", "downloading", "paused", "completed", "failed", "cancelled")
# Status akhir: job tidak lagi dikerjakan worker.
TERMINAL_STATUSES = ("completed", "failed", "cancelled")
MEDIA_TYPES = ("image", "video", "audio", "subtitle", "text")


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    """SQLite mengembalikan datetime tanpa zona waktu; anggap UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_url: Mapped[str] = mapped_column(Text)
    source_domain: Mapped[str] = mapped_column(String(255), index=True)
    platform: Mapped[str] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DownloadJob(Base):
    __tablename__ = "download_jobs"
    __table_args__ = (
        CheckConstraint(f"status IN {JOB_STATUSES}", name="ck_download_jobs_status"),
        CheckConstraint(f"media_type IN {MEDIA_TYPES}", name="ck_download_jobs_media_type"),
        Index("ix_download_jobs_status_updated", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("analyses.id", ondelete="SET NULL"), index=True
    )
    media_id: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    media_url: Mapped[str] = mapped_column(Text)
    source_domain: Mapped[str] = mapped_column(String(255), index=True)
    platform: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    media_type: Mapped[str] = mapped_column(String(30), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    size_downloaded: Mapped[int] = mapped_column(BigInteger, default=0)
    size_total: Mapped[int | None] = mapped_column(BigInteger)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    file: Mapped[DownloadFile | None] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    events: Mapped[list[DownloadHistory]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        # Tidak pernah dimuat otomatis; dihapus lewat ON DELETE CASCADE (passive_deletes).
        lazy="raise",
        passive_deletes=True,
        order_by="DownloadHistory.created_at",
    )


class DownloadFile(Base):
    __tablename__ = "download_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("download_jobs.id", ondelete="CASCADE"), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(150))
    extension: Mapped[str] = mapped_column(String(20))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[DownloadJob] = relationship(back_populates="file")


class DownloadHistory(Base):
    __tablename__ = "download_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("download_jobs.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(50))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[DownloadJob] = relationship(back_populates="events")
