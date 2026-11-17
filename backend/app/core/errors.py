"""Error aplikasi dengan pesan yang mudah dipahami pengguna (NFR-04)."""

from __future__ import annotations


class AppError(Exception):
    """Error yang aman ditampilkan ke pengguna.

    `code` stabil untuk dibaca mesin, `message` dalam Bahasa Indonesia untuk manusia.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.headers = headers


class UnsafeURLError(AppError):
    """URL ditolak oleh kebijakan keamanan (SSRF, skema, port, kredensial)."""

    def __init__(self, message: str, code: str = "url_blocked") -> None:
        super().__init__(code, message, 400)


class TransientError(AppError):
    """Kegagalan sementara yang boleh dicoba ulang (timeout, 5xx, koneksi putus)."""

    def __init__(self, message: str, code: str = "transient_error") -> None:
        super().__init__(code, message, 502)
