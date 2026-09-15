"""add_processing_result_saved_at

Revision ID: 10f68c10ef7d
Revises: 039fed28e7ca
Create Date: 2026-09-15 10:10:44.989152

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "10f68c10ef7d"
down_revision: str | Sequence[str] | None = "039fed28e7ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column(
            "processing_result_saved_at",
            sa.DateTime(timezone=True),
        ),
    )


def downgrade() -> None:
    op.drop_column("receipts", "processing_result_saved_at")
