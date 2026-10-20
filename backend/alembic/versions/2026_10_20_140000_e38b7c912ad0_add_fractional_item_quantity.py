import sqlalchemy as sa

from alembic import op

revision = "e38b7c912ad0"
down_revision = "d27a4b6019ef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "receipt_items",
        "quantity",
        existing_type=sa.Integer(),
        type_=sa.Numeric(15, 3),
        nullable=True,
        postgresql_using="quantity::numeric(15, 3)",
    )
    op.drop_constraint("unit_price_check", "receipt_items", type_="check")
    op.drop_constraint("total_price_check", "receipt_items", type_="check")
    op.create_check_constraint("unit_price_check", "receipt_items", "unit_price >= 0")
    op.create_check_constraint("total_price_check", "receipt_items", "total_price >= 0")


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM receipt_items WHERE quantity IS NULL
                OR quantity <> trunc(quantity) OR quantity > 2147483647
                OR unit_price = 0 OR total_price = 0
            ) THEN
                RAISE EXCEPTION 'Cannot downgrade: receipt items need the new quantity/price format';
            END IF;
        END $$
    """)
    op.drop_constraint("unit_price_check", "receipt_items", type_="check")
    op.drop_constraint("total_price_check", "receipt_items", type_="check")
    op.create_check_constraint("unit_price_check", "receipt_items", "unit_price > 0")
    op.create_check_constraint("total_price_check", "receipt_items", "total_price > 0")
    op.alter_column(
        "receipt_items",
        "quantity",
        existing_type=sa.Numeric(15, 3),
        type_=sa.Integer(),
        nullable=False,
        postgresql_using="quantity::integer",
    )
