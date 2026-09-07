"""Rename image_url to image_object_key

Revision ID: 49185702f47e
Revises: 1c8f59ea29ac
Create Date: 2026-09-07 20:08:34.404014

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '49185702f47e'
down_revision: Union[str, Sequence[str], None] = '1c8f59ea29ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("receipts", "image_url", new_column_name="image_object_key",)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("receipts", "image_object_key", new_column_name="image_url",)
