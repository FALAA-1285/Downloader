"""Text extractor (FR-05): teks utama artikel dengan trafilatura, fallback heuristik."""

from __future__ import annotations

import re

import trafilatura
from bs4 import BeautifulSoup

MAX_CHARS = 200_000
BOILERPLATE = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe", "svg", "button"]


def extract_text(html: str, url: str, soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Mengembalikan (judul, isi)."""
    content: str | None = None
    title: str | None = None
    try:
        content = trafilatura.extract(
            html,
            url=url,
            output_format="txt",
            include_comments=False,
            include_tables=False,
            include_images=False,
            favor_precision=True,
            deduplicate=True,
        )
        meta = trafilatura.extract_metadata(html, default_url=url)
        title = meta.title if meta else None
    except Exception:  # noqa: BLE001 - library pihak ketiga; jatuh ke fallback
        content = None

    if not content or len(content.split()) < 30:
        fallback = _fallback(soup)
        if fallback and len(fallback.split()) > len((content or "").split()):
            content = fallback

    if content:
        content = re.sub(r"\n{3,}", "\n\n", content).strip()[:MAX_CHARS]
    return title, content or None


def _fallback(soup: BeautifulSoup) -> str | None:
    root = soup.find("article") or soup.find("main") or soup.body
    if root is None:
        return None
    root = BeautifulSoup(str(root), "lxml")
    for tag in root.find_all(BOILERPLATE):
        tag.decompose()
    blocks = []
    for el in root.find_all(["h1", "h2", "h3", "p", "li", "blockquote"]):
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if el.name == "p" and len(text) < 40:
            continue
        if text:
            blocks.append(text)
    return "\n\n".join(blocks) or None


def word_count(text: str | None) -> int:
    return len(text.split()) if text else 0
