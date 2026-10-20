import sqlalchemy as sa
from alembic import op

revision = "c72f10356eb4"
down_revision = "b61e0f245da3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "receipt_items", sa.Column("suggested_category_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "receipt_items",
        sa.Column("category_rule_version", sa.String(64), nullable=True),
    )
    op.add_column(
        "receipt_items",
        sa.Column(
            "category_source", sa.String(16), nullable=False, server_default="automatic"
        ),
    )
    op.execute(
        "UPDATE receipt_items SET category_source = 'legacy' WHERE category_id IS NOT NULL"
    )
    op.create_check_constraint(
        "category_source_check",
        "receipt_items",
        "category_source IN ('automatic', 'manual', 'legacy')",
    )
    op.add_column(
        "receipt_items", sa.Column("category_match", sa.String(256), nullable=True)
    )
    op.add_column(
        "receipt_items", sa.Column("category_input", sa.Text(), nullable=True)
    )
    op.add_column(
        "receipt_items",
        sa.Column("category_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_receipt_items_suggested_category",
        "receipt_items",
        "categories",
        ["suggested_category_id"],
        ["category_id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_receipt_items_suggested_category_id",
        "receipt_items",
        ["suggested_category_id"],
    )


def downgrade() -> None:
    op.drop_constraint("category_source_check", "receipt_items", type_="check")
    op.drop_index("ix_receipt_items_suggested_category_id", table_name="receipt_items")
    op.drop_constraint(
        "fk_receipt_items_suggested_category", "receipt_items", type_="foreignkey"
    )
    for column in (
        "category_confirmed_at",
        "category_source",
        "category_input",
        "category_match",
        "category_rule_version",
        "suggested_category_id",
    ):
        op.drop_column("receipt_items", column)
