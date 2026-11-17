"""Registry adapter: memisahkan deteksi sumber dari implementasi ekstraksi (FR-02, FR-10)."""

from __future__ import annotations

from .base import Adapter
from .generic import GenericAdapter
from .platforms.social import SOCIAL_ADAPTERS, UniversalPlatformAdapter, is_ytdlp_supported


class AdapterRegistry:
    def __init__(self, disabled: set[str] | None = None) -> None:
        self.disabled = disabled or set()
        self.generic = GenericAdapter()
        self.platforms: list[Adapter] = [cls() for cls in SOCIAL_ADAPTERS]

    def resolve(self, domain: str, url: str | None = None) -> Adapter:
        """Adapter khusus yang cocok dengan domain, platform yt-dlp universal, atau Generic Adapter.

        Platform yang dikenali tetap diarahkan ke adapternya walau dinonaktifkan, agar
        domain platform tidak diam-diam dianalisis sebagai website umum.
        """
        for adapter in self.platforms:
            if adapter.matches(domain):
                return adapter
        if url:
            supported, _ = is_ytdlp_supported(url)
            if supported:
                return next((a for a in self.platforms if isinstance(a, UniversalPlatformAdapter)), UniversalPlatformAdapter())
        return self.generic

    def status_of(self, adapter: Adapter) -> str:
        return "disabled" if adapter.id in self.disabled else adapter.status

    def all(self) -> list[Adapter]:
        return [self.generic, *self.platforms]
