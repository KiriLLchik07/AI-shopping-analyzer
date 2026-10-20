import unicodedata


def normalize_item_name(raw_name: str) -> str | None:
    name = unicodedata.normalize("NFC", raw_name)
    name = unicodedata.normalize("NFC", " ".join(name.split()).lower())
    return name if name and len(name) <= 256 else None
