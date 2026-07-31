"""initial

Revision ID: a9dd13931339
Revises: 
Create Date: 2026-07-31 18:36:28.236797

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a9dd13931339'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("user_name", sa.String(50), nullable=False),
        sa.Column("user_surname", sa.String(100), nullable=False),
        sa.Column("user_mail", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("user_password_hash", sa.String(255), nullable=False),
        sa.Column("user_age", sa.Integer),
        sa.Column("user_country", sa.String(30)),
        sa.Column("user_city", sa.String(50)),
    )
    op.create_check_constraint(
        "user_mail_validation",
        "users",
        r"user_mail ~ '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'"
    )
    op.create_check_constraint(
        "user_age_validation",
        "users",
        "user_age >= 14"
    )

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("user_age_validation", "users", type_="check")
    op.drop_constraint("user_mail_validation", "users", type_="check")
    op.drop_table("users")

