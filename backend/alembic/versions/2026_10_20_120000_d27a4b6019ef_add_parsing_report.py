import sqlalchemy as sa

from alembic import op

revision = "d27a4b6019ef"
down_revision = "c94d2b7e130a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column("parsing_report", sa.JSON(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("receipts", "parsing_report")
