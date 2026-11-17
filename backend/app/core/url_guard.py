"""Validasi URL dan mitigasi SSRF (FR-01, NFR-01).

Dua lapis pemeriksaan:
1. `validate_url` — sintaks, skema, kredensial, port, dan nama host (tanpa jaringan).
2. `resolve_public` — resolusi DNS; SEMUA alamat hasil resolusi harus publik.
   Fungsi ini dipanggil saat koneksi TCP dibuka (lihat `http_client.GuardedBackend`),
   sehingga setiap redirect dan setiap koneksi baru ikut diperiksa dan DNS rebinding
   tidak bisa menyelinap di antara validasi dan koneksi.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .errors import AppError, UnsafeURLError

log = logging.getLogger(__name__)

MAX_URL_LENGTH = 2048
DEFAULT_PORTS = {"http": 80, "https": 443}
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "metadata.google.internal"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa", ".corp")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

BLOCKED_MESSAGE = "Alamat lokal atau jaringan internal diblokir demi keamanan."

# Jaringan IP pemblokir ISP di Indonesia (Laman Labuh / Internet Positif / UZone)
_ISP_BLOCK_NETWORKS = (
    ipaddress.ip_network("103.151.222.0/23"),  # Laman Labuh ISPku / Telkom
    ipaddress.ip_network("118.98.0.0/16"),  # Internet Positif Telkom
    ipaddress.ip_network("36.86.63.0/24"),  # Telkomsel UZone
    ipaddress.ip_network("180.250.0.0/16"),  # Telkom TrustPositif
)

_DOH_CACHE: dict[str, tuple[float, list[str]]] = {}
_DOH_CACHE_TTL = 300.0


def _is_isp_blocked_ip(ip: IPAddress) -> bool:
    return any(ip in net for net in _ISP_BLOCK_NETWORKS)


async def resolve_doh(host: str) -> list[str]:
    """Resolusi DNS via DNS-over-HTTPS (DoH) untuk melewati pembajakan DNS ISP."""
    now = time.monotonic()
    if host in _DOH_CACHE:
        cached_time, cached_ips = _DOH_CACHE[host]
        if now - cached_time < _DOH_CACHE_TTL:
            return cached_ips

    endpoints = (
        ("https://cloudflare-dns.com/dns-query?name={host}&type=A", {"Accept": "application/dns-json"}),
        ("https://dns.adguard-dns.com/resolve?name={host}&type=A", {}),
    )
    addresses: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            for url_tmpl, headers in endpoints:
                try:
                    resp = await client.get(url_tmpl.format(host=host), headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        for ans in data.get("Answer", []):
                            if ans.get("type") == 1:
                                raw_ip = str(ans.get("data", "")).strip()
                                try:
                                    ip = ipaddress.ip_address(raw_ip)
                                    if is_public_ip(ip) and ip.compressed not in addresses:
                                        addresses.append(ip.compressed)
                                except ValueError:
                                    continue
                        if addresses:
                            break
                except Exception as exc:
                    log.debug("DoH query gagal pada endpoint %s: %s", url_tmpl, exc)
    except Exception as exc:
        log.debug("DoH query gagal untuk %s: %s", host, exc)

    if addresses:
        _DOH_CACHE[host] = (now, addresses)
    return addresses


def resolve_doh_sync(host: str) -> list[str]:
    """Versi sinkronus DoH untuk socket patch dan proses thread."""
    if host in ("cloudflare-dns.com", "dns.adguard-dns.com", "dns.google"):
        return []
    now = time.monotonic()
    if host in _DOH_CACHE:
        cached_time, cached_ips = _DOH_CACHE[host]
        if now - cached_time < _DOH_CACHE_TTL:
            return cached_ips

    import json
    import urllib.request

    endpoints = (
        (
            "https://cloudflare-dns.com/dns-query?name={host}&type=A",
            {"Accept": "application/dns-json", "User-Agent": "curl/8.0"},
        ),
        ("https://dns.adguard-dns.com/resolve?name={host}&type=A", {"User-Agent": "curl/8.0"}),
    )
    addresses: list[str] = []
    for url_tmpl, headers in endpoints:
        try:
            req = urllib.request.Request(url_tmpl.format(host=host), headers=headers)  # noqa: S310
            with urllib.request.urlopen(req, timeout=5.0) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
                for ans in data.get("Answer", []):
                    if ans.get("type") == 1:
                        raw_ip = str(ans.get("data", "")).strip()
                        try:
                            ip = ipaddress.ip_address(raw_ip)
                            if is_public_ip(ip) and ip.compressed not in addresses:
                                addresses.append(ip.compressed)
                        except ValueError:
                            continue
                if addresses:
                    break
        except Exception as exc:
            log.debug("Sync DoH query gagal pada %s: %s", url_tmpl, exc)

    if addresses:
        _DOH_CACHE[host] = (now, addresses)
    return addresses


_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_PATCH_INSTALLED = False


def install_doh_socket_patch() -> None:
    """Menambal socket.getaddrinfo agar otomatis beralih ke DoH saat DNS lokal dibajak ISP."""
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return
    _PATCH_INSTALLED = True

    def _doh_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        try:
            results = _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)
            if results and host and isinstance(host, str) and not host.startswith("127.") and host != "localhost":
                first_ip = str(results[0][4][0]).split("%", 1)[0]
                try:
                    ip = ipaddress.ip_address(first_ip)
                    if _is_isp_blocked_ip(ip):
                        doh_ips = resolve_doh_sync(host)
                        if doh_ips:
                            return _ORIGINAL_GETADDRINFO(doh_ips[0], port, family, type, proto, flags)
                except ValueError:
                    pass
            return results
        except socket.gaierror:
            if host and isinstance(host, str) and not host.startswith("127.") and host != "localhost":
                doh_ips = resolve_doh_sync(host)
                if doh_ips:
                    return _ORIGINAL_GETADDRINFO(doh_ips[0], port, family, type, proto, flags)
            raise

    socket.getaddrinfo = _doh_getaddrinfo



@dataclass(frozen=True)
class ValidatedURL:
    url: str
    scheme: str
    host: str
    port: int

    @property
    def domain(self) -> str:
        return self.host.removeprefix("www.")


def is_public_ip(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_ip(ip.ipv4_mapped)
        if ip.sixtofour is not None or ip.teredo is not None:
            return False
    return bool(
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def _parse_ip(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]*|\d+)$", re.I)


def _looks_numeric(host: str) -> bool:
    labels = host.split(".")
    return 1 < len(labels) <= 4 and all(_NUMERIC_LABEL.match(label) for label in labels)


def validate_url(raw: str, allowed_ports: set[int]) -> ValidatedURL:
    """Validasi tanpa akses jaringan. Mengembalikan URL yang sudah dinormalisasi."""
    if not isinstance(raw, str) or not raw.strip():
        raise UnsafeURLError("URL wajib diisi.", code="url_empty")
    value = raw.strip()
    if len(value) > MAX_URL_LENGTH:
        raise UnsafeURLError("URL terlalu panjang.", code="url_too_long")
    if any(ord(c) < 32 or c == "\\" for c in value):
        raise UnsafeURLError("URL berisi karakter yang tidak valid.", code="url_malformed")

    try:
        parts = urlsplit(value)
        port_value = parts.port
    except ValueError as exc:
        raise UnsafeURLError("Format URL tidak valid.", code="url_malformed") from exc

    scheme = parts.scheme.lower()
    if not scheme:
        raise UnsafeURLError("URL perlu diawali https:// atau http://.", code="url_no_scheme")
    if scheme not in DEFAULT_PORTS:
        raise UnsafeURLError(f"Skema {scheme} tidak didukung. Gunakan http atau https.", code="url_scheme")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURLError("URL berisi kredensial. Hapus nama pengguna dan kata sandi.", code="url_credentials")

    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURLError("URL tidak memiliki nama domain.", code="url_malformed")

    ip = _parse_ip(host)
    if ip is not None:
        if not is_public_ip(ip):
            raise UnsafeURLError(BLOCKED_MESSAGE)
        netloc_host = f"[{ip.compressed}]" if ip.version == 6 else ip.compressed
    else:
        if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
            raise UnsafeURLError(BLOCKED_MESSAGE)
        if "." not in host:
            # Host satu label (mis. "intranet", "2130706433") hampir selalu internal/numerik.
            raise UnsafeURLError(BLOCKED_MESSAGE)
        if _looks_numeric(host):
            # Bentuk IPv4 non-standar (hex "0x7f.0.0.1", oktal "0177.0.0.1", "127.1") ditafsirkan
            # berbeda oleh tiap resolver; tolak sejak awal daripada mengandalkan resolusi.
            raise UnsafeURLError("Format alamat IP tidak valid.", code="url_malformed")
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise UnsafeURLError("Nama domain tidak valid.", code="url_malformed") from exc
        netloc_host = host

    port = port_value or DEFAULT_PORTS[scheme]
    if port not in allowed_ports:
        raise UnsafeURLError(f"Port {port} tidak diizinkan.", code="url_port")

    netloc = netloc_host if port_value is None else f"{netloc_host}:{port}"
    normalized = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
    return ValidatedURL(url=normalized, scheme=scheme, host=host.strip("[]"), port=port)


async def resolve_public(host: str, port: int) -> list[str]:
    """Resolusi DNS. Gagal jika ADA satu pun alamat yang bukan publik."""
    literal = _parse_ip(host)
    if literal is not None:
        if not is_public_ip(literal):
            raise UnsafeURLError(BLOCKED_MESSAGE)
        return [literal.compressed]

    loop = asyncio.get_running_loop()
    infos: list[Any] = []
    has_gaierror = False
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=2.0,
        )
    except (socket.gaierror, TimeoutError):
        has_gaierror = True

    addresses: list[str] = []
    has_isp_block = False
    if not has_gaierror:
        for _family, _type, _proto, _canon, sockaddr in infos:
            ip = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
            if not is_public_ip(ip):
                raise UnsafeURLError(BLOCKED_MESSAGE)
            if _is_isp_blocked_ip(ip):
                has_isp_block = True
                break
            if ip.compressed not in addresses:
                addresses.append(ip.compressed)

    # Jika DNS dibajak oleh ISP atau gagal me-resolve karena blokir ISP, gunakan DoH
    if has_isp_block or has_gaierror or not addresses:
        doh_addresses = await resolve_doh(host)
        if doh_addresses:
            return doh_addresses

    if not addresses:
        raise AppError("dns_failed", f"Domain {host} tidak dapat ditemukan.", 422)
    return addresses


def redact_url(url: str) -> str:
    """URL tanpa query string dan fragment, untuk log/riwayat (query bisa memuat token)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
