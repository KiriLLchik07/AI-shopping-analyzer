UNIT_PATTERN = r"[a-zа-яё]{1,24}\.?"

UNIT_ALIASES = {
    alias: unit
    for unit, aliases in {
        "шт": ("шт", "штука", "штуки", "штук", "pcs", "pc"),
        "кг": ("кг", "килограмм", "килограмма", "килограммов", "kg"),
        "г": ("г", "гр", "грамм", "грамма", "граммов", "g"),
        "л": ("л", "литр", "литра", "литров", "l"),
        "мл": ("мл", "миллилитр", "миллилитра", "миллилитров", "ml"),
        "упак": ("уп", "упак", "упаковка", "упаковки", "упаковок", "pack"),
    }.items()
    for alias in aliases
}


def normalize_unit(value: str | None) -> str | None:
    if value is None:
        return None
    return UNIT_ALIASES.get(value.strip().casefold().removesuffix("."))
