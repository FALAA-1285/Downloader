from __future__ import annotations

from app.extractors.common import sanitize_filename
from app.extractors.images import extract_images
from app.extractors.media import extract_av, extract_subtitles
from app.extractors.page import parse_html
from app.extractors.text import extract_text

BASE = "https://news.example/2026/liputan"

HTML = """<!doctype html><html lang="id"><head>
<title>Judul Fallback</title>
<meta property="og:title" content="Liputan Pameran Arsip Kota">
<meta name="description" content="Ringkasan liputan.">
<meta property="og:image" content="/img/cover.jpg">
</head><body>
<nav><a href="/">Beranda</a></nav>
<article>
  <h1>Liputan Pameran</h1>
  <p>Pameran arsip kota dibuka hari ini dengan ratusan dokumen dan foto bersejarah yang belum pernah dipamerkan.</p>
  <p>Pengunjung dapat melihat peta lama, surat kabar, dan rekaman suara dari berbagai dekade di gedung utama.</p>
  <img src="/img/cover.jpg" alt="Sampul">
  <img src="data:image/gif;base64,R0lGOD" data-src="/img/lazy-01.webp" width="800" height="600">
  <img src="/img/small.jpg" srcset="/img/small.jpg 400w, /img/large.jpg 1600w">
  <img src="/pixel.gif" width="1" height="1">
  <img src="/img/cover.jpg">
  <picture><source srcset="/img/pic.avif 1x, /img/pic@2x.avif 2x" type="image/avif"><img src="/img/pic.jpg"></picture>
  <a href="/files/foto-asli.png">Unduh foto</a>
  <a href="/tentang">Tentang</a>
  <video src="/media/liputan.mp4" poster="/img/poster.jpg" width="1920" height="1080">
    <track kind="subtitles" src="/subs/id.vtt" srclang="id" label="Indonesia">
    <track kind="chapters" src="/subs/chapters.vtt">
  </video>
  <video><source src="/stream/master.m3u8" type="application/x-mpegURL"></video>
  <video src="blob:https://news.example/123"></video>
  <audio controls><source src="/audio/wawancara.mp3" type="audio/mpeg"></audio>
  <a href="/subs/en.srt">English subtitles</a>
  <iframe src="https://www.youtube.com/embed/abc123"></iframe>
</article>
<footer>Hak cipta</footer>
</body></html>"""


def page():
    return parse_html(HTML.encode(), BASE, "utf-8")


def test_page_metadata():  # TC-05
    p = page()
    assert p.title == "Liputan Pameran Arsip Kota"
    assert p.description == "Ringkasan liputan."
    assert p.thumbnail == "https://news.example/img/cover.jpg"


def test_images_detected_and_normalized():  # TC-06
    urls = [c.url for c in extract_images(page().soup, BASE)]
    assert "https://news.example/img/cover.jpg" in urls
    assert "https://news.example/img/lazy-01.webp" in urls
    assert "https://news.example/img/large.jpg" in urls  # srcset terbesar dipilih
    assert "https://news.example/img/pic@2x.avif" in urls
    assert "https://news.example/files/foto-asli.png" in urls
    assert not any("pixel.gif" in u for u in urls)  # piksel pelacak dilewati
    assert not any(u.startswith("data:") for u in urls)
    assert len(urls) == len(set(urls))  # tanpa duplikasi
    assert not any("tentang" in u for u in urls)


def test_image_ids_are_stable_and_unique():
    a = [c.id for c in extract_images(page().soup, BASE)]
    b = [c.id for c in extract_images(page().soup, BASE)]
    assert a == b and len(set(a)) == len(a)


def test_video_audio_detection():
    items, warnings = extract_av(page().soup, BASE)
    by_url = {c.url: c for c in items}
    mp4 = by_url["https://news.example/media/liputan.mp4"]
    assert mp4.type == "video" and mp4.downloadable and mp4.height == 1080
    assert mp4.preview_url == "https://news.example/img/poster.jpg"
    hls = by_url["https://news.example/stream/master.m3u8"]
    assert not hls.downloadable and "HLS" in hls.reason
    assert by_url["https://news.example/audio/wawancara.mp3"].type == "audio"
    embed = by_url["https://www.youtube.com/embed/abc123"]
    assert not embed.downloadable and "YouTube" in embed.reason
    assert any("blob:" in w for w in warnings)


def test_subtitles_detected_with_language():
    subs = {c.url: c for c in extract_subtitles(page().soup, BASE)}
    assert subs["https://news.example/subs/id.vtt"].language == "Indonesia"
    assert "https://news.example/subs/en.srt" in subs
    assert "https://news.example/subs/chapters.vtt" not in subs


def test_text_extraction_removes_boilerplate():  # TC-07
    p = page()
    _title, text = extract_text(p.html, BASE, p.soup)
    assert text and "Pameran arsip kota dibuka" in text
    assert "Hak cipta" not in text


def test_filename_sanitized():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("foto asli (1).JPG") == "foto-asli-1.JPG"
    assert sanitize_filename("%2e%2e%2fsecret.txt") == "secret.txt"
