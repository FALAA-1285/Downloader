"""Menjalankan API dengan host/port dari konfigurasi: `uv run python -m app`.

Migrasi database (`alembic upgrade head`) dijalankan lebih dulu, sama seperti perintah container
Docker. Tanpa ini, kode baru yang memakai kolom baru akan gagal saat startup, dan dalam mode
reload uvicorn port tetap terbuka tanpa worker sehingga semua permintaan menggantung.
"""

import logging
import sys
from pathlib import Path

import uvicorn
from alembic.config import Config

from alembic import command
from app.core.config import BASE_DIR, get_settings

log = logging.getLogger("app")


def migrate() -> None:
    cfg = Config(str(Path(BASE_DIR) / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(BASE_DIR) / "alembic"))
    command.upgrade(cfg, "head")


if __name__ == "__main__":
    settings = get_settings()
    try:
        migrate()
    except Exception:
        logging.basicConfig(level=logging.INFO)
        log.exception("Migrasi database gagal; server tidak dijalankan. Periksa DATABASE_URL lalu coba lagi.")
        sys.exit(1)
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
    )
