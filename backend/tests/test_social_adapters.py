"""Unit test untuk platform adapters (YouTube, Instagram, Facebook, TikTok, X, dll.) via mock."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.adapters.base import AnalysisContext
from app.adapters.platforms.social import (
    FacebookAdapter,
    InstagramAdapter,
    TikTokAdapter,
    UniversalPlatformAdapter,
    XAdapter,
    YouTubeAdapter,
    extract_social_media,
    is_ytdlp_supported,
)
from app.core.config import Settings
from app.core.errors import AppError


@pytest.fixture
def dummy_ctx():
    settings = Settings(
        max_video_duration_minutes=180,
    )
    return AnalysisContext(
        url="https://example.com/video/123",
        domain="example.com",
        media_types={"video", "audio", "image"},
        client=MagicMock(),
        settings=settings,
    )


def test_is_ytdlp_supported():
    # Cache and evaluation test
    supported, name = is_ytdlp_supported("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert supported is True
    assert name is not None

    unsupported, u_name = is_ytdlp_supported("https://127.0.0.1/fake-internal-url")
    assert unsupported is False
    assert u_name is None


@pytest.mark.asyncio
async def test_extract_social_media_success(dummy_ctx):
    mock_info = {
        "title": "Sample Great Video",
        "description": "Video description here",
        "thumbnail": "https://example.com/thumb.jpg",
        "duration": 120.0,
        "width": 1920,
        "height": 1080,
        "filesize": 15_000_000,
        "webpage_url": "https://example.com/video/123",
    }
    with patch("app.adapters.platforms.social._ytdlp_extract_sync", return_value=mock_info):
        outcome = await extract_social_media("https://example.com/video/123", dummy_ctx, "YouTube")
        assert outcome.title == "Sample Great Video"
        assert outcome.thumbnail == "https://example.com/thumb.jpg"
        assert len(outcome.media) >= 3  # Best video, 720p/480p, audio, thumbnail

        types = [m.type for m in outcome.media]
        assert "video" in types
        assert "audio" in types
        assert "image" in types


@pytest.mark.asyncio
async def test_extract_livestream_rejected(dummy_ctx):
    mock_info = {
        "title": "Live Stream Right Now",
        "is_live": True,
        "live_status": "is_live",
        "duration": None,
    }
    with patch("app.adapters.platforms.social._ytdlp_extract_sync", return_value=mock_info):
        with pytest.raises(AppError) as exc_info:
            await extract_social_media("https://example.com/live", dummy_ctx, "YouTube")
        assert exc_info.value.code == "livestream_unsupported"
        assert "live stream" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_extract_duration_limit_exceeded(dummy_ctx):
    # Duration = 4 hours (14400 seconds), exceeding 180 min limit
    mock_info = {
        "title": "Very Long Video (4 Hours)",
        "duration": 14400.0,
        "width": 1280,
        "height": 720,
    }
    with patch("app.adapters.platforms.social._ytdlp_extract_sync", return_value=mock_info):
        with pytest.raises(AppError) as exc_info:
            await extract_social_media("https://example.com/long-video", dummy_ctx, "YouTube")
        assert exc_info.value.code == "duration_limit_exceeded"
        assert "melebihi batas maksimum" in exc_info.value.message


@pytest.mark.asyncio
async def test_platform_adapters_instantiation():
    adapters = [
        YouTubeAdapter(),
        InstagramAdapter(),
        FacebookAdapter(),
        TikTokAdapter(),
        XAdapter(),
        UniversalPlatformAdapter(),
    ]
    for a in adapters:
        assert a.id is not None
        assert a.name is not None
        assert a.status == "active"


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (
            "ERROR: [Instagram] x: Instagram sent an empty media response. Check ... without being logged-in.",
            "login_required",
        ),
        ("ERROR: [vimeo] 1: The web client only works when logged-in. Use --cookies", "login_required"),
        ("ERROR: [twitter] 1: No video could be found in this tweet", "no_video"),
        ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", "private_video"),
    ],
)
def test_extract_errors_are_actionable(message, code):
    from app.adapters.platforms.social import _map_extract_error

    err = _map_extract_error(Exception(message), "https://www.instagram.com/reel/x/")
    assert err.code == code
    if code == "login_required":
        assert "instagram.com" in err.message and "cookies.txt" in err.message
