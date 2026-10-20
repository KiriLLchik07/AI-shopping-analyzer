from uuid import NAMESPACE_URL, UUID, uuid5

DEFAULT_CATEGORIES = (
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
)
FALLBACK_CATEGORY = "прочее"


def default_category_id(name: str) -> UUID:
    if name not in DEFAULT_CATEGORIES:
        raise ValueError(f"Unknown default category: {name}")
    return uuid5(NAMESPACE_URL, f"ai-shopping-analyzer/category/{name}")
