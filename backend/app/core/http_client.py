"""HTTP client keluar yang aman (NFR-01).

- Setiap koneksi TCP baru melewati `GuardedBackend.connect_tcp`, yang me-resolve DNS,
  menolak alamat non-publik, lalu terhubung ke IP yang sudah divalidasi. TLS/SNI tetap
  memakai nama host asli sehingga verifikasi sertifikat tidak terpengaruh.
- `GuardedTransport` dibangun di atas API publik httpcore, sehingga guard tidak bergantung
  pada atribut privat httpx.
- Redirect diikuti manual agar setiap hop divalidasi ulang (skema, port, host).
- Body didekompresi bertahap dengan batas per potongan (`iter_body`), sehingga respons
  terkompresi kecil tidak bisa mengembang tanpa batas di memori.
- Tidak memakai proxy dari environment, tidak meneruskan cookie antar permintaan.
"""

from __future__ import annotations

import ssl
import zlib
from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import asynccontextmanager, contextmanager
from urllib.parse import urljoin

import certifi
import httpcore
import httpx

from .config import Settings
from .errors import AppError, TransientError, UnsafeURLError
from .url_guard import resolve_public, validate_url

REDIRECT_CODES = {301, 302, 303, 307, 308}
BODY_CHUNK = 64 * 1024

# Urutan penting: kelas spesifik sebelum kelas induk.
_ERROR_MAP: tuple[tuple[type[Exception], type[httpx.TransportError]], ...] = (
    (httpcore.ConnectTimeout, httpx.ConnectTimeout),
    (httpcore.ReadTimeout, httpx.ReadTimeout),
    (httpcore.WriteTimeout, httpx.WriteTimeout),
    (httpcore.PoolTimeout, httpx.PoolTimeout),
    (httpcore.TimeoutException, httpx.TimeoutException),
    (httpcore.ConnectError, httpx.ConnectError),
    (httpcore.ReadError, httpx.ReadError),
    (httpcore.WriteError, httpx.WriteError),
    (httpcore.NetworkError, httpx.NetworkError),
    (httpcore.RemoteProtocolError, httpx.RemoteProtocolError),
    (httpcore.LocalProtocolError, httpx.LocalProtocolError),
    (httpcore.ProtocolError, httpx.ProtocolError),
    (httpcore.UnsupportedProtocol, httpx.UnsupportedProtocol),
)


@contextmanager
def _map_transport_errors(request: httpx.Request) -> Iterator[None]:
    try:
        yield
    except Exception as exc:
        for source, target in _ERROR_MAP:
            if isinstance(exc, source):
                raise target(str(exc), request=request) from exc
        raise


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


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: Iterable[bytes] | object, request: httpx.Request) -> None:
        self._stream = stream
        self._request = request

    async def __aiter__(self) -> AsyncIterator[bytes]:
        with _map_transport_errors(self._request):
            async for part in self._stream:  # type: ignore[attr-defined]
                yield part

    async def aclose(self) -> None:
        close = getattr(self._stream, "aclose", None)
        if close is not None:
            await close()


class GuardedTransport(httpx.AsyncBaseTransport):
    """Transport httpx yang memakai pool httpcore dengan `GuardedBackend`."""

    def __init__(self, settings: Settings) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(cafile=certifi.where()),
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=5.0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=GuardedBackend(settings.port_allowlist),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,  # type: ignore[arg-type]
            extensions=request.extensions,
        )
        with _map_transport_errors(request):
            response = await self._pool.handle_async_request(core_request)
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_ResponseStream(response.stream, request),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def build_client(settings: Settings, *, read_timeout: float | None = None) -> httpx.AsyncClient:
    timeout = httpx.Timeout(
        connect=settings.connect_timeout_seconds,
        read=read_timeout or settings.read_timeout_seconds,
        write=settings.read_timeout_seconds,
        pool=settings.connect_timeout_seconds,
    )
    return httpx.AsyncClient(
        transport=GuardedTransport(settings),
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        headers={
            "User-Agent": settings.user_agent,
            "Accept-Language": "id,en;q=0.8",
            # Hanya encoding yang bisa didekompresi bertahap dengan batas (lihat iter_body).
            "Accept-Encoding": "gzip, deflate",
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
        try:
            request = client.build_request(method, current, headers=headers)
        except httpx.InvalidURL as exc:
            raise UnsafeURLError("Format URL tidak valid.", code="url_malformed") from exc
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


def _decoder(content_encoding: str | None):
    encoding = (content_encoding or "").strip().lower()
    if encoding in ("", "identity"):
        return None
    if encoding in ("gzip", "x-gzip"):
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if encoding == "deflate":
        return zlib.decompressobj()
    raise AppError("unsupported_encoding", f"Sumber memakai encoding {encoding} yang tidak didukung.", 502)


def is_encoded(response: httpx.Response) -> bool:
    return (response.headers.get("content-encoding") or "identity").strip().lower() not in ("", "identity")


async def iter_body(response: httpx.Response, chunk_size: int = BODY_CHUNK) -> AsyncIterator[bytes]:
    """Body yang sudah didekode; setiap potongan paling besar `chunk_size` byte."""
    decoder = _decoder(response.headers.get("content-encoding"))
    try:
        async for raw in response.aiter_raw(chunk_size):
            if decoder is None:
                yield raw
                continue
            data = raw
            while True:
                out = decoder.decompress(data, chunk_size)
                if out:
                    yield out
                data = decoder.unconsumed_tail
                if not data and len(out) < chunk_size:
                    break
    except httpx.HTTPError as exc:
        raise map_http_error(exc, str(response.url)) from exc
    except zlib.error as exc:
        raise AppError("decode_error", "Respons terkompresi dari sumber rusak.", 502) from exc


async def read_limited(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    """Membaca body (sudah didekode) sampai `max_bytes`. Mengembalikan (data, terpotong)."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in iter_body(response):
        remaining = max_bytes - total
        if len(chunk) >= remaining:
            chunks.append(chunk[:remaining])
            return b"".join(chunks), True
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), False


def map_http_error(exc: Exception, url: str) -> AppError:
    host = httpx.URL(url).host
    if isinstance(exc, httpx.TimeoutException):
        return TransientError(f"{host} tidak merespons dalam batas waktu.", code="upstream_timeout")
    if isinstance(exc, httpx.ConnectError):
        text = str(exc)
        if "CERTIFICATE_VERIFY_FAILED" in text or "certificate" in text.lower():
            return AppError(
                "tls_invalid",
                f"Sertifikat TLS {host} tidak valid. Domain ini kemungkinan diblokir oleh ISP / Internet Positif sehingga dialihkan ke laman blokir. Aktifkan VPN di perangkat server untuk mengaksesnya.",
                502,
            )
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
