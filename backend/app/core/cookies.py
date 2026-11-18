"""Cookie sesi pengguna: parsing, pencocokan domain, dan konversi format (C-03, H-01).

Format masukan yang didukung:
- Netscape `cookies.txt` (termasuk baris `#HttpOnly_`), seperti ekspor yt-dlp/ekstensi browser.
- JSON: array objek `{name, value, domain, path, secure, httpOnly, expirationDate}`
  (format EditThisCookie/Cookie-Editor) atau objek sederhana `{"nama": "nilai"}`.
- Header `nama=nilai; nama2=nilai2`.

Cookie tanpa domain (JSON sederhana atau `nama=nilai`) dibatasi ke host URL sumber, sehingga
cookie situs A tidak pernah terkirim ke situs B, ke CDN pihak ketiga, atau ke tujuan redirect lain.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

HTTPONLY_PREFIX = "#HttpOnly_"
MAX_COOKIES = 300


@dataclass(frozen=True)
class Cookie:
    name: str
    value: str
    domain: str  # tanpa titik di depan, huruf kecil
    path: str = "/"
    secure: bool = False
    http_only: bool = False
    expires: int | None = None
    # True: hanya untuk host persis (cookie tanpa atribut domain); False: host + subdomain.
    host_only: bool = False

    def matches(self, url: str) -> bool:
        try:
            parts = urlsplit(url)
        except ValueError:
            return False
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            return False
        if self.host_only:
            if host != self.domain:
                return False
        elif host != self.domain and not host.endswith("." + self.domain):
            return False
        if self.secure and parts.scheme != "https":
            return False
        if self.expires and 0 < self.expires < time.time():
            return False
        path = parts.path or "/"
        return path == self.path or path.startswith(self.path.rstrip("/") + "/") or self.path == "/"


def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _clean_domain(domain: str) -> str:
    return domain.strip().lower().lstrip(".").rstrip(".")


def _valid_token(name: str, value: str) -> bool:
    # Nilai berisi CR/LF/`;` akan merusak header Cookie (dan bisa menyisipkan header lain).
    bad = ("\r", "\n", "\x00")
    return (
        bool(name)
        and not any(c in name for c in (*bad, ";", "=", " ", "\t"))
        and not any(c in value for c in (*bad, ";"))
    )


def _parse_netscape(lines: list[str]) -> list[Cookie]:
    out: list[Cookie] = []
    for raw in lines:
        line = raw.strip()
        http_only = False
        if line.startswith(HTTPONLY_PREFIX):
            http_only = True
            line = line[len(HTTPONLY_PREFIX) :]
        elif not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, include_sub, path, secure, expires, name, value = parts[:7]
        try:
            exp = int(float(expires)) or None
        except ValueError:
            exp = None
        name, value = name.strip(), value.strip()
        if not _valid_token(name, value) or not _clean_domain(domain):
            continue
        out.append(
            Cookie(
                name=name,
                value=value,
                domain=_clean_domain(domain),
                path=path.strip() or "/",
                secure=secure.strip().upper() == "TRUE",
                http_only=http_only,
                expires=exp,
                host_only=include_sub.strip().upper() != "TRUE" and not domain.strip().startswith("."),
            )
        )
    return out


def _parse_json(data: object, default_host: str) -> list[Cookie]:
    out: list[Cookie] = []
    if isinstance(data, dict):
        for name, value in data.items():
            if isinstance(value, (str, int, float)) and _valid_token(str(name), str(value)) and default_host:
                out.append(Cookie(name=str(name), value=str(value), domain=default_host, host_only=True))
        return out
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        name, value = str(item.get("name") or ""), str(item.get("value") or "")
        raw_domain = str(item.get("domain") or "")
        domain = _clean_domain(raw_domain) or default_host
        if not domain or not _valid_token(name, value):
            continue
        exp_raw = item.get("expirationDate") or item.get("expires")
        try:
            exp = int(float(exp_raw)) if exp_raw not in (None, "", -1) else None
        except (TypeError, ValueError):
            exp = None
        host_only = bool(item.get("hostOnly")) if "hostOnly" in item else not raw_domain.startswith(".")
        if not raw_domain:
            host_only = True
        out.append(
            Cookie(
                name=name,
                value=value,
                domain=domain,
                path=str(item.get("path") or "/"),
                secure=bool(item.get("secure")),
                http_only=bool(item.get("httpOnly")),
                expires=exp if exp and exp > 0 else None,
                host_only=host_only,
            )
        )
    return out


def _parse_header(text: str, default_host: str) -> list[Cookie]:
    out: list[Cookie] = []
    if not default_host:
        return out
    for chunk in text.replace("\n", ";").split(";"):
        if "=" not in chunk:
            continue
        name, value = chunk.strip().split("=", 1)
        name, value = name.strip(), value.strip()
        if _valid_token(name, value):
            out.append(Cookie(name=name, value=value, domain=default_host, host_only=True))
    return out


def parse_cookies(raw: str | None, source_url: str) -> list[Cookie]:
    """Mengubah teks cookie (format apa pun di atas) menjadi daftar `Cookie` yang terikat domain."""
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    default_host = _host_of(source_url)
    cookies: list[Cookie]
    if text[:1] in ("[", "{"):
        try:
            cookies = _parse_json(json.loads(text), default_host)
        except ValueError:
            cookies = []
    else:
        lines = text.splitlines()
        if any("\t" in ln for ln in lines) or text.startswith("# Netscape") or text.startswith(HTTPONLY_PREFIX):
            cookies = _parse_netscape(lines)
        else:
            cookies = _parse_header(text, default_host)
    return cookies[:MAX_COOKIES]


def cookie_header_for(url: str, cookies: list[Cookie]) -> str | None:
    """Nilai header `Cookie` untuk satu URL; hanya cookie yang domain/path/secure-nya cocok."""
    pairs = [f"{c.name}={c.value}" for c in cookies if c.matches(url)]
    return "; ".join(pairs) or None


def to_netscape(cookies: list[Cookie]) -> str:
    """Format cookies.txt untuk opsi `cookiefile` yt-dlp (yang menerapkan pencocokan domain sendiri)."""
    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        domain = c.domain if c.host_only else "." + c.domain
        prefix = HTTPONLY_PREFIX if c.http_only else ""
        lines.append(
            "\t".join(
                (
                    f"{prefix}{domain}",
                    "FALSE" if c.host_only else "TRUE",
                    c.path,
                    "TRUE" if c.secure else "FALSE",
                    str(c.expires or 0),
                    c.name,
                    c.value,
                )
            )
        )
    return "\n".join(lines) + "\n"


def to_playwright(cookies: list[Cookie]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for c in cookies:
        item: dict[str, object] = {
            "name": c.name,
            "value": c.value,
            "domain": c.domain if c.host_only else "." + c.domain,
            "path": c.path,
            "secure": c.secure,
            "httpOnly": c.http_only,
        }
        if c.expires:
            item["expires"] = c.expires
        out.append(item)
    return out


def same_host(a: str, b: str) -> bool:
    return bool(_host_of(a)) and _host_of(a) == _host_of(b)


# Header kustom yang boleh dikirim pengguna (M-06). Header hop-by-hop / framing (Host,
# Content-Length, Transfer-Encoding, Connection) dan Cookie (punya jalur sendiri) ditolak.
ALLOWED_CUSTOM_HEADERS = {"referer", "origin", "user-agent", "accept-language", "authorization"}
# Header yang aman bila ikut terkirim ke host lain (mis. CDN yang dipanggil yt-dlp).
NON_SENSITIVE_HEADERS = {"referer", "origin", "user-agent", "accept-language"}
MAX_CUSTOM_HEADERS = 20


def validate_custom_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    if not headers:
        return None
    if len(headers) > MAX_CUSTOM_HEADERS:
        raise ValueError(f"maksimal {MAX_CUSTOM_HEADERS} header")
    clean: dict[str, str] = {}
    for key, value in headers.items():
        name = key.strip()
        lower = name.lower()
        if lower not in ALLOWED_CUSTOM_HEADERS and not lower.startswith("x-"):
            raise ValueError(f"header {name!r} tidak diizinkan")
        if any(c in name for c in ":\r\n\t ") or any(c in value for c in "\r\n\x00"):
            raise ValueError(f"header {name!r} berisi karakter tidak valid")
        if len(value) > 4096:
            raise ValueError(f"nilai header {name!r} terlalu panjang")
        clean[name] = value
    return clean or None


def first_party_headers(headers: dict[str, str] | None, url: str, source_url: str) -> dict[str, str]:
    """Header kustom lengkap hanya untuk host sumber; host lain hanya menerima header non-sensitif."""
    if not headers:
        return {}
    if same_host(url, source_url):
        return dict(headers)
    return {k: v for k, v in headers.items() if k.lower() in NON_SENSITIVE_HEADERS}
