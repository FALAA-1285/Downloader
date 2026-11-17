"""Adapter platform yang dikenali tetapi belum memiliki metode integrasi resmi yang berizin.

Sesuai FR-02: platform yang dikenali tidak otomatis berarti kontennya dapat diunduh.
Adapter ini hanya mengklasifikasikan sumber dan mengembalikan peringatan. Implementasi
nyata baru ditambahkan setelah tersedia API resmi dan izin yang jelas (PRD §4.1).
"""

from __future__ import annotations

from app.adapters.base import Adapter, AnalysisContext, AnalysisOutcome


class _PendingPlatform(Adapter):
    status = "evaluating"

    async def analyze(self, ctx: AnalysisContext) -> AnalysisOutcome:
        return AnalysisOutcome(
            final_url=ctx.url,
            warnings=[
                f"Adapter {self.name} masih dalam evaluasi. Platform yang dikenali tidak otomatis "
                "berarti kontennya dapat diunduh."
            ],
        )


class YouTubeAdapter(_PendingPlatform):
    id = "youtube"
    name = "YouTube"
    source_type = "youtube"
    domains = ("youtube.com", "youtu.be", "youtube-nocookie.com")
    note = "Menunggu metode integrasi resmi yang berizin."


class InstagramAdapter(_PendingPlatform):
    id = "instagram"
    name = "Instagram"
    source_type = "instagram"
    domains = ("instagram.com", "cdninstagram.com")
    note = "Konten privat dan konten di balik login tidak diakses."


class TikTokAdapter(_PendingPlatform):
    id = "tiktok"
    name = "TikTok"
    source_type = "tiktok"
    domains = ("tiktok.com",)
    note = "Bergantung pada API dan izin yang tersedia."


class XAdapter(_PendingPlatform):
    id = "x"
    name = "X (Twitter)"
    source_type = "x"
    domains = ("x.com", "twitter.com", "t.co")
    note = "Bergantung pada API dan izin yang tersedia."


PLATFORM_ADAPTERS: tuple[type[Adapter], ...] = (YouTubeAdapter, InstagramAdapter, TikTokAdapter, XAdapter)
