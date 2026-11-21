"""Separate receipt review from OCR processing."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "6ed1ac09f482"
down_revision = "d83021467fc5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column(
            "receipt_status", sa.String(16), nullable=False, server_default="draft"
        ),
    )
    op.add_column(
        "receipts",
        sa.Column(
            "processing_status",
            sa.String(24),
            nullable=False,
            server_default="pending_dispatch",
        ),
    )
    op.add_column(
        "receipts",
        sa.Column(
            "ocr_due_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    for name in ("manual_ocr_runs", "automatic_ocr_retries"):
        op.add_column(
            "receipts",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )
    op.add_column("receipts", sa.Column("ocr_correlation_id", sa.String(128)))

    op.execute("""
        UPDATE receipts
        SET receipt_status = CASE
                WHEN status = 'completed'
                     AND purchase_datetime IS NOT NULL AND confirmed_at IS NOT NULL
                    THEN 'confirmed'
                WHEN status IN ('need_review', 'completed') THEN 'needs_review'
                ELSE 'draft'
            END,
            processing_status = CASE
                WHEN status = 'failed' THEN 'failed'
                WHEN status IN ('need_review', 'completed') THEN 'succeeded'
                ELSE 'pending_dispatch'
            END,
            ocr_due_at = CASE
                WHEN status IN ('failed', 'need_review', 'completed') THEN NULL
                ELSE now()
            END,
            processing_version = CASE
                WHEN status IN ('uploaded', 'preprocessing', 'ocr_processing', 'parsing')
                    THEN processing_version + 1
                ELSE processing_version
            END,
            processing_items_revision = CASE
                WHEN status IN ('uploaded', 'preprocessing', 'ocr_processing', 'parsing')
                    THEN items_revision
                ELSE processing_items_revision
            END,
            confirmed_at = CASE
                WHEN status = 'completed' AND purchase_datetime IS NOT NULL
                    THEN confirmed_at
                ELSE NULL
            END
    """)
    op.create_index("ix_receipts_ocr_due_at", "receipts", ["ocr_due_at"])
    op.drop_column("receipts", "status")


def downgrade() -> None:
    old_status = postgresql.ENUM(name="receipt_status", create_type=False)
    op.add_column("receipts", sa.Column("status", old_status))
    op.execute("""
        UPDATE receipts
        SET status = (CASE
            WHEN receipt_status = 'confirmed' THEN 'completed'
            WHEN receipt_status = 'needs_review' THEN 'need_review'
            WHEN processing_status = 'failed' THEN 'failed'
            ELSE 'uploaded'
        END)::receipt_status
    """)
    op.alter_column(
        "receipts", "status", nullable=False, server_default=sa.text("'uploaded'")
    )
    op.drop_index("ix_receipts_ocr_due_at", table_name="receipts")
    for name in (
        "ocr_correlation_id",
        "automatic_ocr_retries",
        "manual_ocr_runs",
        "ocr_due_at",
        "processing_status",
        "receipt_status",
    ):
        op.drop_column("receipts", name)
