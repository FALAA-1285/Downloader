"""Image extractor (FR-04): img, src, srcset, picture, lazy-load, dan metadata gambar."""

from __future__ import annotations

from bs4 import BeautifulSoup

from .common import IMAGE_EXT, Candidate, absolutize, best_from_srcset, mime_from_ext, parse_int, url_ext

LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-lazy", "data-url")
LAZY_SRCSET = ("srcset", "data-srcset", "data-lazy-srcset")


def extract_images(soup: BeautifulSoup, base: str) -> list[Candidate]:
    found: dict[str, Candidate] = {}

    def add(raw: str | None, *, width=None, height=None, label=None, strict_ext=False) -> None:
        url = absolutize(base, raw)
        if not url or url in found:
            return
        ext = url_ext(url)
        if ext and ext not in IMAGE_EXT:
            return
        if strict_ext and not ext:
            return
        w, h = parse_int(width), parse_int(height)
        if (w is not None and w <= 2) or (h is not None and h <= 2):
            return  # piksel pelacak
        found[url] = Candidate(
            type="image",
            url=url,
            mime_type=mime_from_ext(ext),
            width=w,
            height=h,
            label=label,
            preview_url=url,
        )

    for name in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src"):
        for tag in soup.find_all("meta", attrs={"property": name}) + soup.find_all("meta", attrs={"name": name}):
            add(tag.get("content"))
    for tag in soup.find_all("link", rel=lambda v: v and "image_src" in v):
        add(tag.get("href"))

    for img in soup.find_all("img"):
        alt = img.get("alt")
        best = None
        for attr in LAZY_SRCSET:
            best = best or best_from_srcset(img.get(attr))
        src = None
        for attr in ("src", *LAZY_ATTRS):
            value = img.get(attr)
            if value and not str(value).startswith("data:"):
                src = value
                break
        add(best or src, width=img.get("width"), height=img.get("height"), label=alt)
        if best and src:
            add(src, width=img.get("width"), height=img.get("height"), label=alt)

    for source in soup.select("picture source"):
        mime = (source.get("type") or "").lower()
        if mime and not mime.startswith("image/"):
            continue
        for attr in LAZY_SRCSET:
            add(best_from_srcset(source.get(attr)))

    # Tautan langsung ke file gambar.
    for a in soup.find_all("a", href=True):
        add(a["href"], strict_ext=True, label=a.get_text(" ", strip=True) or None)

    return list(found.values())
