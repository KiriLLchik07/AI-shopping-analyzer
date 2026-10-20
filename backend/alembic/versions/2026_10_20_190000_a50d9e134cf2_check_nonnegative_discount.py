from alembic import op

revision = "a50d9e134cf2"
down_revision = "f49c8d023be1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "discount_amount_check", "receipt_items", "discount_amount >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("discount_amount_check", "receipt_items", type_="check")
