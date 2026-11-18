"""antrean terjadwal: status `scheduled` dan kolom scheduled_at

Revision ID: 7d2e9a1b4c3f
Revises: 3c1d2e4f5a6b
Create Date: 2026-11-18 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7d2e9a1b4c3f"
down_revision: str | Sequence[str] | None = "3c1d2e4f5a6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "status IN ('pending', 'processing', 'downloading', 'paused', 'completed', 'failed', 'cancelled')"
NEW = "status IN ('scheduled', 'pending', 'processing', 'downloading', 'paused', 'completed', 'failed', 'cancelled')"


def upgrade() -> None:
    with op.batch_alter_table("download_jobs") as batch:
        batch.add_column(sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_download_jobs_scheduled_at", ["scheduled_at"])
        batch.drop_constraint("ck_download_jobs_status", type_="check")
        batch.create_check_constraint("ck_download_jobs_status", NEW)


def downgrade() -> None:
    op.execute("UPDATE download_jobs SET status = 'pending' WHERE status = 'scheduled'")
    with op.batch_alter_table("download_jobs") as batch:
        batch.drop_constraint("ck_download_jobs_status", type_="check")
        batch.create_check_constraint("ck_download_jobs_status", OLD)
        batch.drop_index("ix_download_jobs_scheduled_at")
        batch.drop_column("scheduled_at")
