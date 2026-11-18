from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import AppError
from app.downloaders.file_validator import detect, resolve_kind
from app.downloaders.subtitles import parse_cues, validate_subtitle, vtt_to_srt

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
VTT = b"WEBVTT\n\nNOTE komentar\n\n1\n00:01.000 --> 00:04.500 align:start\n<v Andi>Halo <b>semua</b></v>\n\n00:00:05.000 --> 00:00:07.250\nBaris &amp; dua\n"
SRT = b"1\n00:00:01,000 --> 00:00:04,500\nHalo\n\n2\n00:00:05,000 --> 00:00:07,000\nDua\n"


@pytest.mark.parametrize(
    ("head", "kind"),
    [
        (PNG, "png"),
        (JPEG, "jpeg"),
        (b"GIF89a....", "gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
        (MP4, "mp4"),
        (b"\x00\x00\x00\x1cftypqt  ", "mov"),
        (b"\x1a\x45\xdf\xa3\x01\x00webm", "webm"),
        (b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x64", "mp3"),
        (b"\xff\xfb\x90\x64\x00", "mp3"),
        # ID3 diikuti playlist HLS: bukan MP3, harus ditolak (M-01).
        (b"ID3\x04\x00\x00\x00\x00\x00\x00#EXTM3U\n#EXTINF:1,\nfile:///etc/passwd\n", None),
        (b"\x00\x00\x00\x18ftypheic", None),
        (b"\x00\x00\x00\x18ftypisom", "mp4"),
        (b"\x00\x00\x00\x1cftypFACE\x00\x00\x00\x00isom", "mp4"),
        (b"<?xml version='1.0'?>\n<!-- c --><svg xmlns='http://www.w3.org/2000/svg'/>", "svg"),
        (b"<div><svg></svg></div>", None),
        (b"OggS\x00", "ogg"),
        (VTT, "vtt"),
        (SRT, "srt"),
        (b"\xef\xbb\xbf<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'/>", "svg"),
        (b"<!DOCTYPE html><html><body>Login</body></html>", "html"),
        (b"MZ\x90\x00", "exe"),
    ],
)
def test_detect(head, kind):
    assert detect(head) == kind


def test_resolve_kind_accepts_matching_type():
    assert resolve_kind(PNG, "image").ext == "png"
    assert resolve_kind(MP4, "video").mime == "video/mp4"
    assert resolve_kind(MP4, "audio").ext == "m4a"


@pytest.mark.parametrize(
    ("head", "media_type", "fragment"),
    [
        (b"<html><body>404</body></html>", "image", "halaman HTML"),  # MIME palsu
        (b"MZ\x90\x00binary", "video", "executable"),
        (PNG, "video", "PNG"),
        (b"just some text", "subtitle", "tidak dikenal"),
    ],
)
def test_resolve_kind_rejects_mismatch(head, media_type, fragment):
    with pytest.raises(AppError) as e:
        resolve_kind(head, media_type)
    assert fragment in e.value.message


def test_vtt_parsing_and_conversion():
    cues = parse_cues(VTT.decode())
    assert len(cues) == 2
    assert cues[0].start == 1.0 and cues[0].text == "Halo <b>semua</b>"
    srt = vtt_to_srt(VTT).decode()
    assert srt.startswith(
        "1\n00:00:01,000 --> 00:00:04,500\nHalo <b>semua</b>\n\n2\n00:00:05,000 --> 00:00:07,250\nBaris & dua"
    )


def test_invalid_subtitle_rejected():
    with pytest.raises(AppError):
        validate_subtitle(b"WEBVTT\n\nbukan cue\n", "vtt")
    assert validate_subtitle(SRT, "srt")


def test_download_ytdlp_sync_picks_final_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import time
    import uuid
    from unittest.mock import MagicMock

    import yt_dlp

    from app.core.config import Settings
    from app.services.download_runner import _Control, _download_ytdlp_sync

    job_id = uuid.uuid4()
    part_path = tmp_path / f"{job_id.hex}.part"

    # Buat file hasil unduhan seolah-olah yt-dlp sudah selesai mengunduh
    target_file = tmp_path / f"{job_id.hex}_ytdlp.mp4"
    target_file.write_bytes(MP4)
    ytdl_file = tmp_path / f"{job_id.hex}_ytdlp.mp4.ytdl"
    ytdl_file.write_bytes(b"temp_ytdl_metadata")
    frag_file = tmp_path / f"{job_id.hex}_ytdlp.mp4.part-Frag1"
    frag_file.write_bytes(b"temp_frag")
    # File per-format sisa merge tidak boleh terpilih walau lebih besar (M-04).
    fmt_file = tmp_path / f"{job_id.hex}_ytdlp.f137.mp4"
    fmt_file.write_bytes(MP4 * 50)

    seen_opts: dict = {}

    def fake_extract(self, url, download=False):
        seen_opts.update(self.params)
        return {"duration": 30}

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", fake_extract)
    monkeypatch.setattr(
        yt_dlp.YoutubeDL,
        "process_ie_result",
        lambda self, info, download=True: {"requested_downloads": [{"filepath": str(target_file)}]},
    )
    control = _Control(deadline=time.monotonic() + 60, max_bytes=10_000_000, loop=MagicMock())

    head, size = _download_ytdlp_sync(
        "https://example.com/video",
        "video",
        part_path,
        {"cookies": "sid=abc"},
        job_id,
        MagicMock(),
        Settings(_env_file=None, storage_path=tmp_path),
        "http://127.0.0.1:1",
        "https://example.com/page",
        control,
    )

    # Semua koneksi lewat proxy penjaga (C-01); cookie lewat cookiefile, bukan header global (C-03).
    assert seen_opts["proxy"] == "http://127.0.0.1:1"
    assert "Cookie" not in seen_opts["http_headers"]
    assert seen_opts["cookiefile"].endswith(".txt")
    assert not list((tmp_path / "temp").glob("cookies-*"))  # cookiefile sementara dihapus

    assert head.startswith(b"\x00\x00\x00\x18ftypmp42")
    assert size == len(MP4)
    assert part_path.exists()
    assert not target_file.exists()
    assert not ytdl_file.exists()
    assert not frag_file.exists()
    assert not fmt_file.exists()


def test_download_ytdlp_sync_rejects_long_duration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Batas durasi berlaku juga untuk stream generik, bukan hanya adapter sosial (H-03)."""
    import time
    import uuid
    from unittest.mock import MagicMock

    import yt_dlp

    from app.core.config import Settings
    from app.core.errors import AppError
    from app.services.download_runner import _Control, _download_ytdlp_sync

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", lambda self, url, download=False: {"duration": 99_999})
    called = MagicMock()
    monkeypatch.setattr(yt_dlp.YoutubeDL, "process_ie_result", called)
    control = _Control(deadline=time.monotonic() + 60, max_bytes=10_000_000, loop=MagicMock())
    job_id = uuid.uuid4()
    with pytest.raises(AppError) as exc:
        _download_ytdlp_sync(
            "https://example.com/v.m3u8",
            "video",
            tmp_path / f"{job_id.hex}.part",
            {},
            job_id,
            MagicMock(),
            Settings(_env_file=None, storage_path=tmp_path),
            "http://127.0.0.1:1",
            None,
            control,
        )
    assert exc.value.code == "duration_limit_exceeded"
    called.assert_not_called()
