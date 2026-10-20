from collections.abc import Sequence
from decimal import Decimal

from backend.app.schemas.parsing import (
    ParsedReceiptItem,
    ReceiptTotalsCheck,
    TotalsCheckStatus,
)


def check_receipt_totals(
    items: Sequence[ParsedReceiptItem],
    total_amount: Decimal | None,
    *,
    tolerance: Decimal = Decimal("0.05"),
) -> tuple[ReceiptTotalsCheck, tuple[str, ...]]:
    if not tolerance.is_finite() or tolerance < 0:
        raise ValueError("Totals tolerance must be finite and non-negative")

    amounts = [item.total_price for item in items if item.total_price is not None]
    missing_amounts = len(items) - len(amounts)
    items_sum = (
        sum(amounts, start=Decimal("0.00")) if items and missing_amounts == 0 else None
    )
    difference = (
        items_sum - total_amount
        if items_sum is not None and total_amount is not None
        else None
    )
    warnings: tuple[str, ...] = ()
    if not items:
        status = TotalsCheckStatus.NO_ITEMS
    elif missing_amounts:
        status = TotalsCheckStatus.INCOMPLETE
        warnings = (
            f"Не удалось сверить итог: у {missing_amounts} позиций отсутствует сумма.",
        )
    elif difference is None:
        status = TotalsCheckStatus.MISSING_TOTAL
    elif difference == 0:
        status = TotalsCheckStatus.MATCHED
    elif abs(difference) <= tolerance:
        status = TotalsCheckStatus.WITHIN_TOLERANCE
    else:
        status = TotalsCheckStatus.MISMATCH
        warnings = (
            (
                f"Сумма позиций {items_sum:.2f} ₽ отличается от итога чека "
                f"{total_amount:.2f} ₽ на {difference:+.2f} ₽ "
                f"(допуск {tolerance:.2f} ₽). Проверьте позиции, скидки и итог."
            ),
        )

    return ReceiptTotalsCheck(
        status=status,
        items_sum=items_sum,
        difference=difference,
        tolerance=tolerance,
        item_count=len(items),
        missing_amount_count=missing_amounts,
    ), warnings
