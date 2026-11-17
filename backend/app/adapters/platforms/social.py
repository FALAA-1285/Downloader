"""Adapter untuk platform media sosial (YouTube, Instagram, Facebook, TikTok, X, dll.) via yt-dlp."""

from __future__ import annotations

import asyncio
import logging

import yt_dlp

from app.adapters.base import Adapter, AnalysisContext, AnalysisOutcome
from app.core.errors import AppError
from app.extractors.common import Candidate, sanitize_filename

log = logging.getLogger(__name__)


def _ytdlp_extract_sync(url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": 20,
        "noplaylist": True,
        "check_formats": False,
        "no_color": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            return ydl.extract_info(url, download=False) or {}
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc)
            if "Private video" in msg or "private" in msg.lower():
                raise AppError("private_video", "Video ini bersifat privat atau tidak dapat diakses.", 422) from exc
            if "Video unavailable" in msg or "not found" in msg.lower() or "404" in msg:
                raise AppError("not_found", "Video tidak ditemukan atau telah dihapus.", 404) from exc
            if "Sign in" in msg or "login" in msg.lower():
                raise AppError("login_required", "Konten ini membutuhkan login atau dibatasi usia.", 422) from exc
            clean_msg = msg.split("ERROR:")[-1].strip() if "ERROR:" in msg else msg
            raise AppError("extract_failed", f"Gagal menganalisis video: {clean_msg}", 422) from exc


async def extract_social_media(url: str, ctx: AnalysisContext, platform_name: str) -> AnalysisOutcome:
    info = await asyncio.to_thread(_ytdlp_extract_sync, url)
    if not info:
        raise AppError("empty_result", f"Tidak ada media yang ditemukan dari {platform_name}.", 422)

    title = info.get("title") or f"Video {platform_name}"
    description = info.get("description")
    thumbnail = info.get("thumbnail")
    duration = info.get("duration")
    final_url = info.get("webpage_url") or url

    clean_title = sanitize_filename(title, fallback="video")
    media: list[Candidate] = []

    # 1. Video Options
    if ctx.wants("video"):
        filesize = info.get("filesize") or info.get("filesize_approx")
        width = info.get("width")
        height = info.get("height")
        resolution = f"{height}p" if height else "HD"

        # Kualitas Terbaik (Full HD / 4K / Best)
        media.append(
            Candidate(
                type="video",
                url=url,
                mime_type="video/mp4",
                size=filesize,
                downloadable=True,
                width=width,
                height=height,
                duration=duration,
                label=f"{clean_title}.mp4 ({resolution})",
                preview_url=thumbnail,
                probe=False,
                options={
                    "downloader": "yt-dlp",
                    "format_id": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
                },
            )
        )

        # Opsi 720p jika video aslinya lebih dari 720p (hemat kuota)
        if height and height > 720:
            media.append(
                Candidate(
                    type="video",
                    url=f"{url}#720p",
                    mime_type="video/mp4",
                    size=None,
                    downloadable=True,
                    width=1280 if width else None,
                    height=720,
                    duration=duration,
                    label=f"{clean_title}-720p.mp4 (720p)",
                    preview_url=thumbnail,
                    probe=False,
                    options={
                        "downloader": "yt-dlp",
                        "format_id": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
                    },
                )
            )

        # Opsi 480p (Ukuran Kecil & Download Super Cepat)
        if height and height > 480:
            media.append(
                Candidate(
                    type="video",
                    url=f"{url}#480p",
                    mime_type="video/mp4",
                    size=None,
                    downloadable=True,
                    width=854 if width else None,
                    height=480,
                    duration=duration,
                    label=f"{clean_title}-480p.mp4 (480p - Cepat & Ringan)",
                    preview_url=thumbnail,
                    probe=False,
                    options={
                        "downloader": "yt-dlp",
                        "format_id": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]/best",
                    },
                )
            )

    # 2. Audio Option (MP3)
    if ctx.wants("audio"):
        media.append(
            Candidate(
                type="audio",
                url=f"{url}#audio",
                mime_type="audio/mpeg",
                size=None,
                downloadable=True,
                duration=duration,
                label=f"{clean_title}.mp3 (Audio)",
                preview_url=thumbnail,
                probe=False,
                options={
                    "downloader": "yt-dlp",
                    "format_id": "bestaudio/best",
                },
            )
        )

    # 3. Thumbnail / Cover Image
    if ctx.wants("image") and thumbnail:
        media.append(
            Candidate(
                type="image",
                url=thumbnail,
                mime_type="image/jpeg",
                size=None,
                downloadable=True,
                label=f"{clean_title}-thumbnail.jpg",
                preview_url=thumbnail,
                probe=True,
            )
        )

    return AnalysisOutcome(
        final_url=final_url,
        title=title,
        description=description,
        thumbnail=thumbnail,
        media=media,
    )


class YouTubeAdapter(Adapter):
    id = "youtube"
    name = "YouTube"
    source_type = "youtube"
    domains = ("youtube.com", "youtu.be", "youtube-nocookie.com")
    status = "active"
    note = "Unduhan video dan audio YouTube didukung via yt-dlp."

    async def analyze(self, ctx: AnalysisContext) -> AnalysisOutcome:
        return await extract_social_media(ctx.url, ctx, self.name)


class InstagramAdapter(Adapter):
    id = "instagram"
    name = "Instagram"
    source_type = "instagram"
    domains = ("instagram.com", "instagr.am")
    status = "active"
    note = "Unduhan Reels dan Postingan Instagram didukung via yt-dlp."

    async def analyze(self, ctx: AnalysisContext) -> AnalysisOutcome:
        return await extract_social_media(ctx.url, ctx, self.name)


class FacebookAdapter(Adapter):
    id = "facebook"
    name = "Facebook"
    source_type = "facebook"
    domains = ("facebook.com", "fb.watch", "fb.com", "m.facebook.com", "web.facebook.com")
    status = "active"
    note = "Unduhan Video dan Reels Facebook didukung via yt-dlp."

    async def analyze(self, ctx: AnalysisContext) -> AnalysisOutcome:
        return await extract_social_media(ctx.url, ctx, self.name)


class TikTokAdapter(Adapter):
    id = "tiktok"
    name = "TikTok"
    source_type = "tiktok"
    domains = ("tiktok.com",)
    status = "active"
    note = "Unduhan Video TikTok didukung via yt-dlp."

    async def analyze(self, ctx: AnalysisContext) -> AnalysisOutcome:
        return await extract_social_media(ctx.url, ctx, self.name)


class XAdapter(Adapter):
    id = "x"
    name = "X (Twitter)"
    source_type = "x"
    domains = ("x.com", "twitter.com", "t.co")
    status = "active"
    note = "Unduhan Video X/Twitter didukung via yt-dlp."

    async def analyze(self, ctx: AnalysisContext) -> AnalysisOutcome:
        return await extract_social_media(ctx.url, ctx, self.name)


class OtherSocialAdapter(Adapter):
    id = "social_other"
    name = "Media Sosial Lainnya"
    source_type = "generic"
    domains = (
        "threads.net",
        "reddit.com",
        "pinterest.com",
        "pin.it",
        "vimeo.com",
        "twitch.tv",
        "dailymotion.com",
        "soundcloud.com",
    )
    status = "active"
    note = "Unduhan platform media sosial lainnya didukung via yt-dlp."

    async def analyze(self, ctx: AnalysisContext) -> AnalysisOutcome:
        return await extract_social_media(ctx.url, ctx, self.name)


SOCIAL_ADAPTERS: tuple[type[Adapter], ...] = (
    YouTubeAdapter,
    InstagramAdapter,
    FacebookAdapter,
    TikTokAdapter,
    XAdapter,
    OtherSocialAdapter,
)
