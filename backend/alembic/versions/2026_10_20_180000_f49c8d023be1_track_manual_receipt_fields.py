import sqlalchemy as sa
from alembic import op

revision = "f49c8d023be1"
down_revision = "e38b7c912ad0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column(
            "manually_updated_fields", sa.JSON(), nullable=False, server_default="[]"
        ),
    )


def downgrade() -> None:
    op.drop_column("receipts", "manually_updated_fields")
