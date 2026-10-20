import re
import unicodedata

ABBREVIATIONS = {
    "б/п": "быстрого приготовления",
    "с/м": "свежемороженый",
    "ср-во": "средство",
    "лап": "лапша",
    "гов": "говядина",
    "кур": "курица",
    "мол": "молочный",
    "паст": "пастеризованный",
    "шок": "шоколад",
    "конф": "конфеты",
    "печ": "печенье",
    "газ": "газированный",
    "мин": "минеральная",
    "стир": "стирка",
    "зуб": "зубная",
}


def normalize_category_text(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold().replace("ё", "е")
    for short, expanded in ABBREVIATIONS.items():
        text = re.sub(rf"(?<!\w){re.escape(short)}(?!\w)\.?", expanded, text)
    return " ".join(re.sub(r"[^\w]+", " ", text).split())
