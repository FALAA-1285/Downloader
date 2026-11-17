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
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from .errors import AppError, UnsafeURLError

MAX_URL_LENGTH = 2048
DEFAULT_PORTS = {"http": 80, "https": 443}
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "metadata.google.internal"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa", ".corp")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

BLOCKED_MESSAGE = "Alamat lokal atau jaringan internal diblokir demi keamanan."


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
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise AppError("dns_failed", f"Domain {host} tidak dapat ditemukan.", 422) from exc

    addresses: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
        if not is_public_ip(ip):
            raise UnsafeURLError(BLOCKED_MESSAGE)
        if ip.compressed not in addresses:
            addresses.append(ip.compressed)
    if not addresses:
        raise AppError("dns_failed", f"Domain {host} tidak memiliki alamat.", 422)
    return addresses
