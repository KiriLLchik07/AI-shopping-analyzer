"""seed default categories

Revision ID: 1c8f59ea29ac
Revises: 967e026b6ed8
Create Date: 2026-08-28 23:57:29.484782

"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1c8f59ea29ac"
down_revision: str | Sequence[str] | None = "967e026b6ed8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORY_NAMES = [
    "продукты",
    "снеки",
    "сладкое",
    "напитки",
    "алкоголь",
    "бытовая химия",
    "кафе",
    "готовая еда",
    "рестораны",
    "аптеки",
    "больницы",
    "техника",
    "товары для дома",
    "гигиена",
    "одежда",
    "питомцы",
    "транспорт",
    "подписки",
    "прочее",
]

categories = sa.table(
    "categories",
    sa.column("category_id", sa.Uuid()),
    sa.column("category_name", sa.String()),
    sa.column("parent_id", sa.Uuid()),
)


def get_category_id(name: str):
    return uuid5(
        NAMESPACE_URL,
        f"ai-shopping-analyzer/category/{name}",
    )


def upgrade() -> None:
    op.bulk_insert(
        categories,
        [
            {
                "category_id": get_category_id(name),
                "category_name": name,
                "parent_id": None,
            }
            for name in CATEGORY_NAMES
        ],
    )


def downgrade() -> None:
    category_ids = [get_category_id(name) for name in CATEGORY_NAMES]

    op.execute(categories.delete().where(categories.c.category_id.in_(category_ids)))
