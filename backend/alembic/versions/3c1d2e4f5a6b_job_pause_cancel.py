"""status job paused & cancelled (H-06)

Revision ID: 3c1d2e4f5a6b
Revises: 115a6c8f8e3f
Create Date: 2026-11-18 11:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "3c1d2e4f5a6b"
down_revision: str | Sequence[str] | None = "115a6c8f8e3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "status IN ('pending', 'processing', 'downloading', 'completed', 'failed')"
NEW = "status IN ('pending', 'processing', 'downloading', 'paused', 'completed', 'failed', 'cancelled')"


def upgrade() -> None:
    with op.batch_alter_table("download_jobs") as batch:
        batch.drop_constraint("ck_download_jobs_status", type_="check")
        batch.create_check_constraint("ck_download_jobs_status", NEW)


def downgrade() -> None:
    op.execute("UPDATE download_jobs SET status = 'failed' WHERE status IN ('paused', 'cancelled')")
    with op.batch_alter_table("download_jobs") as batch:
        batch.drop_constraint("ck_download_jobs_status", type_="check")
        batch.create_check_constraint("ck_download_jobs_status", OLD)
