"""HTTP client keluar yang aman (NFR-01).

- Setiap koneksi TCP baru melewati `GuardedBackend.connect_tcp`, yang me-resolve DNS,
  menolak alamat non-publik, lalu terhubung ke IP yang sudah divalidasi. TLS/SNI tetap
  memakai nama host asli sehingga verifikasi sertifikat tidak terpengaruh.
- Redirect diikuti manual agar setiap hop divalidasi ulang (skema, port, host).
- Tidak memakai proxy dari environment, tidak meneruskan cookie antar permintaan.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from urllib.parse import urljoin

import certifi
import httpcore
import httpx

from .config import Settings
from .errors import AppError, TransientError, UnsafeURLError
from .url_guard import resolve_public, validate_url

REDIRECT_CODES = {301, 302, 303, 307, 308}


class GuardedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, allowed_ports: set[int]) -> None:
        self._inner = httpcore.AnyIOBackend()
        self._allowed_ports = allowed_ports

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - antarmuka httpcore
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if port not in self._allowed_ports:
            raise UnsafeURLError(f"Port {port} tidak diizinkan.", code="url_port")
        addresses = await resolve_public(host, port)
        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    async def connect_unix_socket(self, *args: object, **kwargs: object) -> httpcore.AsyncNetworkStream:
        raise UnsafeURLError("Koneksi unix socket tidak diizinkan.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def build_client(settings: Settings, *, read_timeout: float | None = None) -> httpx.AsyncClient:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    transport = httpx.AsyncHTTPTransport(retries=0)
    # httpx tidak mengekspos `network_backend`, jadi pool diganti dengan yang memakai GuardedBackend.
    transport._pool = httpcore.AsyncConnectionPool(  # noqa: SLF001
        ssl_context=ssl_context,
        max_connections=20,
        max_keepalive_connections=10,
        keepalive_expiry=5.0,
        http1=True,
        http2=False,
        network_backend=GuardedBackend(settings.port_allowlist),
    )
    timeout = httpx.Timeout(
        connect=settings.connect_timeout_seconds,
        read=read_timeout or settings.read_timeout_seconds,
        write=settings.read_timeout_seconds,
        pool=settings.connect_timeout_seconds,
    )
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        headers={
            "User-Agent": settings.user_agent,
            "Accept-Language": "id,en;q=0.8",
        },
    )


@asynccontextmanager
async def open_stream(
    client: httpx.AsyncClient,
    url: str,
    settings: Settings,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> AsyncIterator[tuple[httpx.Response, str]]:
    """Membuka response streaming dengan redirect yang divalidasi per hop.

    Menghasilkan (response, final_url). Response ditutup otomatis.
    """
    current = validate_url(url, settings.port_allowlist).url
    for _hop in range(settings.max_redirects + 1):
        request = client.build_request(method, current, headers=headers)
        try:
            response = await client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise map_http_error(exc, current) from exc
        finally:
            # Jangan bawa cookie dari satu respons ke permintaan berikutnya.
            client.cookies.clear()

        location = response.headers.get("location")
        if response.status_code in REDIRECT_CODES and location:
            await response.aclose()
            current = validate_url(urljoin(current, location), settings.port_allowlist).url
            if response.status_code == 303:
                method = "GET"
            continue

        try:
            yield response, current
        finally:
            await response.aclose()
        return

    raise AppError("too_many_redirects", "Terlalu banyak pengalihan (redirect) dari sumber.", 502)


async def read_limited(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    """Membaca body sampai `max_bytes`. Mengembalikan (data, terpotong)."""
    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in response.aiter_bytes():
            remaining = max_bytes - total
            if len(chunk) >= remaining:
                chunks.append(chunk[:remaining])
                return b"".join(chunks), True
            chunks.append(chunk)
            total += len(chunk)
    except httpx.HTTPError as exc:
        raise map_http_error(exc, str(response.url)) from exc
    return b"".join(chunks), False


def map_http_error(exc: Exception, url: str) -> AppError:
    host = httpx.URL(url).host
    if isinstance(exc, httpx.TimeoutException):
        return TransientError(f"{host} tidak merespons dalam batas waktu.", code="upstream_timeout")
    if isinstance(exc, httpx.ConnectError):
        text = str(exc)
        if "CERTIFICATE_VERIFY_FAILED" in text or "certificate" in text.lower():
            return AppError("tls_invalid", f"Sertifikat TLS {host} tidak valid.", 502)
        return TransientError(f"Tidak dapat terhubung ke {host}.", code="upstream_unreachable")
    if isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)):
        return TransientError(f"Koneksi ke {host} terputus.", code="upstream_disconnected")
    return AppError("upstream_error", f"Permintaan ke {host} gagal.", 502)


def status_error(status: int, subject: str = "Halaman") -> AppError:
    """Pesan yang bisa ditindaklanjuti untuk status HTTP dari sumber."""
    if status in (401, 407):
        return AppError(
            "auth_required", f"{subject} membutuhkan login. Konten di balik autentikasi tidak diakses.", 422
        )
    if status == 403:
        return AppError("forbidden", f"{subject} menolak akses (HTTP 403).", 422)
    if status == 404 or status == 410:
        return AppError("not_found", f"{subject} tidak ditemukan (HTTP {status}).", 422)
    if status == 451:
        return AppError("unavailable_legal", f"{subject} tidak tersedia karena alasan hukum (HTTP 451).", 422)
    if status == 429:
        return TransientError(
            "Sumber membatasi jumlah permintaan (HTTP 429). Coba lagi nanti.", code="upstream_rate_limited"
        )
    if status >= 500:
        return TransientError(f"Server sumber sedang bermasalah (HTTP {status}).", code="upstream_server_error")
    return AppError("upstream_status", f"{subject} merespons dengan status HTTP {status}.", 422)
