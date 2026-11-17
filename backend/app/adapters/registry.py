"""Registry adapter: memisahkan deteksi sumber dari implementasi ekstraksi (FR-02, FR-10)."""

from __future__ import annotations

from .base import Adapter
from .generic import GenericAdapter
from .platforms.social import SOCIAL_ADAPTERS


class AdapterRegistry:
    def __init__(self, disabled: set[str] | None = None) -> None:
        self.disabled = disabled or set()
        self.generic = GenericAdapter()
        self.platforms: list[Adapter] = [cls() for cls in SOCIAL_ADAPTERS]

    def resolve(self, domain: str) -> Adapter:
        """Adapter khusus yang cocok dengan domain, atau Generic Adapter.

        Platform yang dikenali tetap diarahkan ke adapternya walau dinonaktifkan, agar
        domain platform tidak diam-diam dianalisis sebagai website umum.
        """
        for adapter in self.platforms:
            if adapter.matches(domain):
                return adapter
        return self.generic

    def status_of(self, adapter: Adapter) -> str:
        return "disabled" if adapter.id in self.disabled else adapter.status

    def all(self) -> list[Adapter]:
        return [self.generic, *self.platforms]
