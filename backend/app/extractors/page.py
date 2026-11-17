"""Page analyzer: parsing HTML dan metadata dasar (FR-03)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .common import absolutize, meta_content

LOGIN_PATH = re.compile(r"/(login|log-in|signin|sign-in|auth|account/login|accounts/login)(/|$|\?)", re.I)


@dataclass
class ParsedPage:
    soup: BeautifulSoup
    html: str
    base_url: str
    title: str | None
    description: str | None
    thumbnail: str | None


def parse_html(data: bytes, url: str, charset: str | None) -> ParsedPage:
    html = _decode(data, charset)
    soup = BeautifulSoup(html, "lxml")

    base_url = url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base_url = absolutize(url, str(base_tag["href"])) or url

    title = meta_content(soup, "og:title", "twitter:title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string
    description = meta_content(soup, "og:description", "description", "twitter:description")
    thumbnail = absolutize(base_url, meta_content(soup, "og:image", "og:image:url", "twitter:image"))

    return ParsedPage(
        soup=soup,
        html=html,
        base_url=base_url,
        title=_clean(title, 300),
        description=_clean(description, 600),
        thumbnail=thumbnail,
    )


def _decode(data: bytes, charset: str | None) -> str:
    for enc in (charset, "utf-8"):
        if not enc:
            continue
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    # Biarkan BeautifulSoup/lxml mendeteksi dari <meta charset>.
    from bs4.dammit import UnicodeDammit

    return UnicodeDammit(data, is_html=True).unicode_markup or data.decode("utf-8", "replace")


def _clean(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit] or None


def is_login_url(final_url: str) -> bool:
    """Sumber mengarahkan ke halaman login: konten di baliknya tidak dianalisis."""
    return bool(LOGIN_PATH.search(final_url))


def has_login_form(page: ParsedPage, word_count: int) -> bool:
    """Ada form kata sandi dan sedikit konten: kemungkinan sebagian konten butuh login."""
    has_password = page.soup.find("input", attrs={"type": "password"}) is not None
    return has_password and word_count < 150


def needs_javascript(page: ParsedPage, word_count: int) -> bool:
    if word_count >= 80:
        return False
    scripts = len(page.soup.find_all("script"))
    noscript = " ".join(t.get_text(" ", strip=True).lower() for t in page.soup.find_all("noscript"))
    root_app = page.soup.find(id=re.compile(r"^(root|app|__next|__nuxt)$"))
    return scripts >= 5 or "javascript" in noscript or root_app is not None
