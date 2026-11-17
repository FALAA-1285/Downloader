from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import SessionDep, SettingsDep
from app.schemas.api import DownloadJobOut, JobStatus, MediaType
from app.services import download_service
from app.services.serializers import job_out

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=list[DownloadJobOut])
async def list_history(
    session: SessionDep,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    media_type: MediaType | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DownloadJobOut]:
    """Riwayat pekerjaan, terbaru di atas (FR-09)."""
    stmt = download_service.history_query(status_filter, media_type, q).limit(limit).offset(offset)
    jobs = (await session.scalars(stmt)).all()
    return [job_out(j) for j in jobs]


@router.delete("/{history_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_history(history_id: uuid.UUID, session: SessionDep, settings: SettingsDep) -> Response:
    """Menghapus riwayat. Aturan: file sementara dan log kejadian ikut dihapus."""
    await download_service.delete_job(session, settings, history_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
