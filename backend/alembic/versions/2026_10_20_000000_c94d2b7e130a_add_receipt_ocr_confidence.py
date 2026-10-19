"""Add receipt OCR confidence.

Revision ID: c94d2b7e130a
Revises: a61f39d2e780
"""

import sqlalchemy as sa
from alembic import op

revision = "c94d2b7e130a"
down_revision = "a61f39d2e780"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("receipts", sa.Column("ocr_confidence", sa.Float(), nullable=True))
    op.create_check_constraint(
        "receipt_ocr_confidence_range",
        "receipts",
        "ocr_confidence >= 0 AND ocr_confidence <= 1",
    )


def downgrade() -> None:
    op.drop_constraint("receipt_ocr_confidence_range", "receipts", type_="check")
    op.drop_column("receipts", "ocr_confidence")
