"""Add objcet cleanup tasks

Revision ID: 039fed28e7ca
Revises: 49185702f47e
Create Date: 2026-09-08 21:49:07.814872

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "039fed28e7ca"
down_revision: str | Sequence[str] | None = "49185702f47e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "object_cleanup_tasks",
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("receipt_id"),
        sa.UniqueConstraint("object_key"),
    )


def downgrade() -> None:
    op.drop_table("object_cleanup_tasks")
