"""Proxy HTTP lokal penjaga SSRF untuk klien yang tidak memakai `GuardedTransport` (C-01, C-02).

yt-dlp (beserta ffmpeg yang dipanggilnya) dan Chromium/Playwright me-resolve DNS dan membuka
koneksi sendiri, sehingga `validate_url` di awal tidak cukup: redirect, URL segmen di dalam
manifest HLS/DASH, atau sub-resource halaman bisa menunjuk ke jaringan internal.

Semua lalu lintas klien tersebut diarahkan ke proxy ini. Untuk setiap permintaan (CONNECT
untuk HTTPS, absolute-URI untuk HTTP) proxy:
1. memvalidasi host & port dengan `validate_url` (skema, port allowlist, nama host internal);
2. me-resolve DNS dengan `resolve_public` — SEMUA alamat harus publik;
3. terhubung ke IP yang sudah divalidasi itu (bukan me-resolve ulang), sehingga DNS rebinding
   tidak bisa menyelinap di antara validasi dan koneksi.

Proxy hanya mendengarkan di 127.0.0.1 pada port acak dan hanya meneruskan ke alamat publik.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import weakref
from urllib.parse import urlsplit

from .config import Settings
from .errors import AppError
from .url_guard import resolve_public, validate_url

log = logging.getLogger(__name__)

MAX_HEAD = 64 * 1024
PIPE_CHUNK = 64 * 1024
HEAD_TIMEOUT = 30.0
CONNECT_TIMEOUT = 20.0
HOP_BY_HOP = {b"proxy-connection", b"proxy-authorization", b"connection", b"keep-alive"}


class GuardProxy:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._server: asyncio.Server | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.url = ""
        self.blocked = 0  # untuk test & diagnosis
        self._handlers: set[asyncio.Task] = set()

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0, limit=MAX_HEAD)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"

    def is_serving(self) -> bool:
        return bool(self._server and self._server.is_serving() and self.loop and not self.loop.is_closed())

    async def close(self) -> None:
        # Koneksi yang masih terbuka (tunnel keep-alive) dibatalkan agar tidak tertinggal.
        handlers = [t for t in self._handlers if not t.done()]
        for task in handlers:
            task.cancel()
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 2.0)
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(task)
            task.add_done_callback(self._handlers.discard)
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, ConnectionError):
            await _close(writer)
            return
        try:
            request_line, _, rest = head.partition(b"\r\n")
            method, target, version = request_line.decode("latin-1").split(" ", 2)
        except ValueError:
            await _reply(writer, 400, "Bad Request")
            return

        if method.upper() == "CONNECT":
            await self._tunnel(target, reader, writer)
        else:
            await self._forward(method, target, version, rest, reader, writer)

    async def _open_upstream(self, url: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, str]:
        """Validasi tujuan lalu buka koneksi TCP ke IP publik hasil resolusi."""
        target = validate_url(url, self.settings.port_allowlist)
        addresses = await resolve_public(target.host, target.port)
        last: Exception | None = None
        for address in addresses:
            try:
                r, w = await asyncio.wait_for(asyncio.open_connection(address, target.port), CONNECT_TIMEOUT)
                return r, w, target.host
            except (OSError, TimeoutError) as exc:
                last = exc
        raise ConnectionError(f"tidak dapat terhubung ke {target.host}: {last}")

    async def _tunnel(self, authority: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        host, sep, port = authority.rpartition(":")
        if not sep or not port.isdigit():
            await _reply(writer, 400, "Bad Request")
            return
        try:
            up_r, up_w, _ = await self._open_upstream(f"https://{host}:{port}/")
        except AppError as exc:
            self.blocked += 1
            log.info("guard proxy menolak CONNECT %s: %s", host, exc.code)
            await _reply(writer, 403, "Forbidden", exc.message)
            return
        except (ConnectionError, OSError) as exc:
            await _reply(writer, 502, "Bad Gateway", str(exc))
            return
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await _pipe_both(reader, writer, up_r, up_w)

    async def _forward(
        self,
        method: str,
        target: str,
        version: str,
        rest: bytes,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            parts = urlsplit(target)
        except ValueError:
            await _reply(writer, 400, "Bad Request")
            return
        if parts.scheme != "http" or not parts.hostname:
            await _reply(writer, 400, "Bad Request", "Hanya absolute-URI http:// yang didukung.")
            return
        try:
            up_r, up_w, host = await self._open_upstream(target)
        except AppError as exc:
            self.blocked += 1
            log.info("guard proxy menolak %s %s: %s", method, parts.hostname, exc.code)
            await _reply(writer, 403, "Forbidden", exc.message)
            return
        except (ConnectionError, OSError) as exc:
            await _reply(writer, 502, "Bad Gateway", str(exc))
            return

        origin_form = parts.path or "/"
        if parts.query:
            origin_form += "?" + parts.query
        headers = []
        for line in rest.split(b"\r\n"):
            if not line:
                continue
            name = line.split(b":", 1)[0].strip().lower()
            if name in HOP_BY_HOP or name == b"host":
                continue
            headers.append(line)
        host_header = parts.netloc.rsplit("@", 1)[-1]
        out = [f"{method} {origin_form} {version.strip()}".encode("latin-1"), b"Host: " + host_header.encode("idna")]
        out += headers
        # Satu permintaan per koneksi: klien membuka koneksi baru untuk permintaan berikutnya,
        # sehingga setiap permintaan melewati validasi.
        out.append(b"Connection: close")
        up_w.write(b"\r\n".join(out) + b"\r\n\r\n")
        await up_w.drain()
        await _pipe_both(reader, writer, up_r, up_w)


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while data := await src.read(PIPE_CHUNK):
            dst.write(data)
            await dst.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            if dst.can_write_eof():
                dst.write_eof()


async def _pipe_both(
    c_r: asyncio.StreamReader, c_w: asyncio.StreamWriter, u_r: asyncio.StreamReader, u_w: asyncio.StreamWriter
) -> None:
    try:
        await asyncio.gather(_pipe(c_r, u_w), _pipe(u_r, c_w))
    finally:
        await _close(u_w)
        await _close(c_w)


async def _reply(writer: asyncio.StreamWriter, status: int, reason: str, body: str = "") -> None:
    payload = (body or reason).encode("utf-8", "replace")
    with contextlib.suppress(Exception):
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode("latin-1")
            + payload
        )
        await writer.drain()
    await _close(writer)


async def _close(writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(Exception):
        writer.close()
        await asyncio.wait_for(writer.wait_closed(), 2.0)


_current: GuardProxy | None = None
_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = weakref.WeakKeyDictionary()


async def get_guard_proxy(settings: Settings) -> GuardProxy:
    """Proxy untuk event loop yang sedang berjalan; dibuat saat pertama kali dibutuhkan.

    Di proses API proxy hidup sepanjang umur proses. Worker RQ menjalankan setiap job dalam
    event loop baru (`asyncio.run`), sehingga proxy dibuat ulang per job dan ditutup di akhir job.
    """
    global _current
    loop = asyncio.get_running_loop()
    if _current is not None and _current.loop is loop and _current.is_serving():
        return _current
    lock = _locks.setdefault(loop, asyncio.Lock())
    async with lock:
        if _current is not None and _current.loop is loop and _current.is_serving():
            return _current
        proxy = GuardProxy(settings)
        await proxy.start()
        _current = proxy
        log.debug("guard proxy aktif di %s", proxy.url)
        return proxy


async def shutdown_guard_proxy() -> None:
    global _current
    proxy, _current = _current, None
    if proxy is not None and proxy.loop is asyncio.get_running_loop():
        await proxy.close()
