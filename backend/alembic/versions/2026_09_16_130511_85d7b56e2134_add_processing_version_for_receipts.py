"""add_processing_version_for_receipts

Revision ID: 85d7b56e2134
Revises: 7198c121d1bf
Create Date: 2026-09-16 13:05:11.110851

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "85d7b56e2134"
down_revision: str | Sequence[str] | None = "7198c121d1bf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "receipts",
        sa.Column(
            "processing_version", sa.Integer(), server_default="1", nullable=False
        ),
    )
    op.add_column(
        "receipts",
        sa.Column("items_revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "receipts",
        sa.Column(
            "processing_items_revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "receipts",
        sa.Column(
            "processing_replace_items",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("receipts", "processing_replace_items")
    op.drop_column("receipts", "processing_items_revision")
    op.drop_column("receipts", "items_revision")
    op.drop_column("receipts", "processing_version")
