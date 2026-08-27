"""add receipt domain models

Revision ID: 967e026b6ed8
Revises: 4640cc65be73
Create Date: 2026-08-24 19:07:20.035934

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "967e026b6ed8"
down_revision: Union[str, Sequence[str], None] = "4640cc65be73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "categories",
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("category_name", sa.String(length=100), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["categories.category_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("category_id"),
        sa.UniqueConstraint("category_name"),
    )
    op.create_index(
        op.f("ix_categories_parent_id"), "categories", ["parent_id"], unique=False
    )
    op.create_table(
        "receipts",
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_user_id", sa.Uuid(), nullable=False),
        sa.Column("store_name", sa.String(length=100), nullable=True),
        sa.Column("store_inn", sa.String(length=12), nullable=True),
        sa.Column("purchase_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("payment_type", sa.String(length=30), nullable=True),
        sa.Column("fiscal_drive_number", sa.String(length=16), nullable=True),
        sa.Column("fiscal_document_number", sa.String(), nullable=True),
        sa.Column("fiscal_sign", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(length=256), nullable=False),
        sa.Column("raw_ocr_text", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "uploaded",
                "preprocessing",
                "ocr_processing",
                "parsing",
                "need_review",
                "completed",
                "failed",
                name="receipt_status",
            ),
            server_default="uploaded",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("LENGTH(store_inn) <= 12", name="store_inn_check"),
        sa.CheckConstraint("total_amount > 0", name="total_amount_check"),
        sa.ForeignKeyConstraint(
            ["receipt_user_id"], ["users.user_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("receipt_id"),
    )
    op.create_index(
        op.f("ix_receipts_store_name"), "receipts", ["store_name"], unique=False
    )
    op.create_index(
        "ix_receipts_user_datetime",
        "receipts",
        ["receipt_user_id", "purchase_datetime"],
        unique=False,
    )
    op.create_table(
        "receipt_items",
        sa.Column("receipt_item_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("raw_name", sa.String(length=256), nullable=False),
        sa.Column("normalized_name", sa.String(length=256), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column("weight", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("total_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "discount_amount",
            sa.Numeric(precision=12, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "is_impulse_candidate", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="receipt_item_confidence_range"
        ),
        sa.CheckConstraint("quantity > 0", name="quantity_check"),
        sa.CheckConstraint("total_price > 0", name="total_price_check"),
        sa.CheckConstraint("unit_price > 0", name="unit_price_check"),
        sa.CheckConstraint("weight > 0", name="weight_check"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.category_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"], ["receipts.receipt_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("receipt_item_id"),
    )
    op.create_index(
        op.f("ix_receipt_items_category_id"),
        "receipt_items",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_receipt_items_receipt_id"),
        "receipt_items",
        ["receipt_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_receipt_items_receipt_id"), table_name="receipt_items")
    op.drop_index(op.f("ix_receipt_items_category_id"), table_name="receipt_items")
    op.drop_table("receipt_items")
    op.drop_index("ix_receipts_user_datetime", table_name="receipts")
    op.drop_index(op.f("ix_receipts_store_name"), table_name="receipts")
    op.drop_table("receipts")
    sa.Enum(
        "uploaded",
        "preprocessing",
        "ocr_processing",
        "parsing",
        "need_review",
        "completed",
        "failed",
        name="receipt_status",
    ).drop(
        op.get_bind(),
        checkfirst=True,
    )
    op.drop_index(op.f("ix_categories_parent_id"), table_name="categories")
    op.drop_table("categories")
