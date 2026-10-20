import sqlalchemy as sa
from alembic import op

revision = "b61e0f245da3"
down_revision = "a50d9e134cf2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "receipts", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("receipts", "confirmed_at")
