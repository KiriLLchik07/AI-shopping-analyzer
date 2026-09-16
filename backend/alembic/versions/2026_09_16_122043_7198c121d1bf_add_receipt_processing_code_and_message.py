"""add_receipt_processing_code_and_message

Revision ID: 7198c121d1bf
Revises: 10f68c10ef7d
Create Date: 2026-09-16 12:20:43.857207

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7198c121d1bf"
down_revision: str | Sequence[str] | None = "10f68c10ef7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "receipts",
        sa.Column("processing_error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "receipts",
        sa.Column("processing_error_message", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("receipts", "processing_error_message")
    op.drop_column("receipts", "processing_error_code")
