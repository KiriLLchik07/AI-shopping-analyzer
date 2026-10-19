"""Add orientation preprocessing report.

Revision ID: a61f39d2e780
Revises: 85d7b56e2134
"""

import sqlalchemy as sa
from alembic import op

revision = "a61f39d2e780"
down_revision = "85d7b56e2134"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column("orientation_report", sa.JSON(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("receipts", "orientation_report")
