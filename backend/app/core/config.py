"""Konfigurasi aplikasi dari environment variables (NFR-05)."""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "production", "test"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    database_url: str = "postgresql+asyncpg://postgres@127.0.0.1:5432/media_downloader"
    redis_url: str = "redis://localhost:6379/0"
    # inline: unduhan dijalankan di proses API (cocok untuk Windows/dev).
    # rq: unduhan dikirim ke Redis dan diproses oleh worker RQ terpisah.
    queue_backend: Literal["inline", "rq"] = "inline"

    storage_path: Path = Path("../storage")
    max_download_size_mb: int = 200
    max_storage_mb: int = 2048
    download_timeout_seconds: int = 120
    download_max_retries: int = 2
    download_concurrency: int = 3
    file_retention_hours: int = 24
    analysis_retention_hours: int = 24
    cleanup_interval_seconds: int = 600

    analyze_timeout_seconds: float = 25.0
    analyze_concurrency: int = 4
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 20.0
    max_page_size_mb: float = 5.0
    max_redirects: int = 5
    max_media_items: int = 300
    probe_limit: int = 80
    probe_concurrency: int = 8
    probe_budget_seconds: float = 10.0
    allowed_ports: str = "80,443,8080,8443"
    user_agent: str = "UniversalMediaDownloader/0.1 (personal use)"

    frontend_origin: str = "http://localhost:3000,http://127.0.0.1:3000"
    allowed_hosts: str = "localhost,127.0.0.1,backend"
    allowed_client_networks: str = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    rate_limit_analyze_per_minute: int = 20
    rate_limit_downloads_per_minute: int = 30

    disabled_adapters: str = ""
    ffprobe_path: str = "ffprobe"
    log_level: str = "INFO"

    @property
    def cors_origins(self) -> list[str]:
        return _csv(self.frontend_origin)

    @property
    def trusted_hosts(self) -> list[str]:
        return _csv(self.allowed_hosts)

    @property
    def client_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        return [ipaddress.ip_network(n, strict=False) for n in _csv(self.allowed_client_networks)]

    @property
    def port_allowlist(self) -> set[int]:
        return {int(p) for p in _csv(self.allowed_ports)}

    @property
    def disabled_adapter_ids(self) -> set[str]:
        return set(_csv(self.disabled_adapters))

    @property
    def max_download_bytes(self) -> int:
        return self.max_download_size_mb * 1024 * 1024

    @property
    def max_storage_bytes(self) -> int:
        return self.max_storage_mb * 1024 * 1024

    @property
    def max_page_bytes(self) -> int:
        return int(self.max_page_size_mb * 1024 * 1024)

    @property
    def storage_root(self) -> Path:
        return self.storage_path.resolve()

    @property
    def downloads_dir(self) -> Path:
        return self.storage_root / "downloads"

    @property
    def temp_dir(self) -> Path:
        return self.storage_root / "temp"


@lru_cache
def get_settings() -> Settings:
    return Settings()
