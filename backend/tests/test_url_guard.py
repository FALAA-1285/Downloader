"""TC-01 s.d. TC-04 dan uji keamanan SSRF (PRD §14.3)."""

from __future__ import annotations

import socket

import httpx
import pytest
import respx

from app.core.config import Settings
from app.core.errors import AppError, UnsafeURLError
from app.core.http_client import build_client, open_stream
from app.core.url_guard import resolve_public, validate_url

PORTS = {80, 443, 8080, 8443}


def test_valid_url_is_normalized():  # TC-01
    v = validate_url("  HTTPS://WWW.Example.COM/artikel?id=1#bagian  ", PORTS)
    assert v.url == "https://www.example.com/artikel?id=1"
    assert v.domain == "example.com"
    assert v.port == 443


def test_idn_domain_is_punycoded():
    assert validate_url("https://bücher.example/", PORTS).host == "xn--bcher-kva.example"


@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_url_rejected(raw):  # TC-02
    with pytest.raises(UnsafeURLError) as e:
        validate_url(raw, PORTS)
    assert e.value.code == "url_empty"


@pytest.mark.parametrize("raw", ["example.com/page", "http://", "https://exa mple.com:99999/", "http://[::1"])
def test_malformed_url_rejected(raw):  # TC-03
    with pytest.raises(UnsafeURLError):
        validate_url(raw, PORTS)


@pytest.mark.parametrize("raw", ["ftp://example.com/a", "file:///etc/passwd", "javascript:alert(1)", "gopher://x.com"])
def test_non_http_schemes_rejected(raw):
    with pytest.raises(UnsafeURLError):
        validate_url(raw, PORTS)


@pytest.mark.parametrize(
    "raw",
    [
        "http://localhost/",  # TC-04
        "http://LOCALHOST:8080/admin",
        "http://app.localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://172.16.3.4/",
        "http://192.168.1.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fd00::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://printer.local/",
        "http://metadata.google.internal/",
        "http://2130706433/",
        "http://intranet/",
    ],
)
def test_internal_destinations_blocked(raw):
    with pytest.raises(UnsafeURLError) as e:
        validate_url(raw, PORTS)
    assert "diblokir" in e.value.message


def test_credentials_rejected():
    with pytest.raises(UnsafeURLError) as e:
        validate_url("https://user:pass@example.com/", PORTS)
    assert e.value.code == "url_credentials"


def test_port_outside_allowlist_rejected():
    with pytest.raises(UnsafeURLError) as e:
        validate_url("http://example.com:6379/", PORTS)
    assert e.value.code == "url_port"


async def test_dns_resolving_to_private_ip_blocked():
    with pytest.raises(UnsafeURLError):
        await resolve_public("internal-rebind.example", 443)


async def test_dns_with_mixed_answers_blocked(monkeypatch):
    """Satu jawaban DNS privat cukup untuk menolak (DNS rebinding)."""

    async def mixed(self, host, port, *a, **k):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", port)),
        ]

    import asyncio

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", mixed)
    with pytest.raises(UnsafeURLError):
        await resolve_public("mixed.example", 443)


async def test_unknown_domain_gives_clear_error(monkeypatch):
    async def fail(self, *a, **k):
        raise socket.gaierror("nope")

    import asyncio

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fail)
    with pytest.raises(AppError) as e:
        await resolve_public("tidak-ada.example", 443)
    assert e.value.code == "dns_failed"


async def test_client_refuses_to_connect_to_rebound_domain():
    """Pemeriksaan terjadi saat koneksi TCP dibuka, bukan hanya saat validasi awal."""
    settings = Settings(_env_file=None)
    async with build_client(settings) as client:
        with pytest.raises(UnsafeURLError):
            await client.get("http://internal-rebind.example/")


async def test_redirect_to_internal_address_blocked():
    settings = Settings(_env_file=None)
    with respx.mock(assert_all_mocked=True) as web:
        web.get("https://site.example/go").mock(
            return_value=httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
        )
        async with build_client(settings) as client:
            with pytest.raises(UnsafeURLError):
                async with open_stream(client, "https://site.example/go", settings):
                    pass


async def test_too_many_redirects():
    settings = Settings(_env_file=None, max_redirects=2)
    with respx.mock(assert_all_mocked=True) as web:
        web.get("https://loop.example/").mock(return_value=httpx.Response(302, headers={"Location": "/"}))
        async with build_client(settings) as client:
            with pytest.raises(AppError) as e:
                async with open_stream(client, "https://loop.example/", settings):
                    pass
    assert e.value.code == "too_many_redirects"


async def test_cookies_not_carried_between_requests():
    settings = Settings(_env_file=None)
    with respx.mock(assert_all_mocked=True) as web:
        web.get("https://a.example/").mock(return_value=httpx.Response(200, headers={"Set-Cookie": "sid=secret"}))
        second = web.get("https://a.example/next").mock(return_value=httpx.Response(200))
        async with build_client(settings) as client:
            async with open_stream(client, "https://a.example/", settings):
                pass
            async with open_stream(client, "https://a.example/next", settings):
                pass
    assert "cookie" not in second.calls.last.request.headers
