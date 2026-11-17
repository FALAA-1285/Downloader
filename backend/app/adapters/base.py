"""Kontrak adapter yang seragam (FR-10)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Literal

import httpx

from app.core.config import Settings
from app.extractors.common import Candidate

AdapterStatus = Literal["active", "evaluating", "disabled"]


@dataclass
class AnalysisContext:
    url: str
    domain: str
    media_types: set[str]
    client: httpx.AsyncClient
    settings: Settings

    def wants(self, media_type: str) -> bool:
        return not self.media_types or media_type in self.media_types


@dataclass
class AnalysisOutcome:
    """Format hasil standar yang dikembalikan semua adapter."""

    final_url: str | None = None
    title: str | None = None
    description: str | None = None
    thumbnail: str | None = None
    media: list[Candidate] = field(default_factory=list)
    text_title: str | None = None
    text_content: str | None = None
    warnings: list[str] = field(default_factory=list)


class Adapter(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    source_type: ClassVar[str]
    domains: ClassVar[tuple[str, ...]] = ()
    status: ClassVar[AdapterStatus] = "active"
    note: ClassVar[str] = ""

    def matches(self, domain: str) -> bool:
        return any(domain == d or domain.endswith("." + d) for d in self.domains)

    @abstractmethod
    async def analyze(self, ctx: AnalysisContext) -> AnalysisOutcome: ...
