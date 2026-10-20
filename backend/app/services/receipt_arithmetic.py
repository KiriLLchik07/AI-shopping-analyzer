from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from backend.app.core.exceptions import BusinessRuleError
from backend.app.schemas.items import ReceiptItemData


def validate_receipt_arithmetic(
    items: Sequence[ReceiptItemData],
    total_amount: Decimal | None,
    *,
    tolerance: Decimal,
) -> None:
    if not tolerance.is_finite() or tolerance < 0:
        raise ValueError("Totals tolerance must be finite and non-negative")
    if total_amount is None or not total_amount.is_finite() or total_amount <= 0:
        raise BusinessRuleError("Укажите положительную итоговую сумму чека.")
    if not items:
        raise BusinessRuleError("Добавьте хотя бы одну товарную позицию.")

    items_sum = Decimal("0.00")
    for number, item in enumerate(items, start=1):
        if item.quantity is None or item.unit_price is None or item.total_price is None:
            raise BusinessRuleError(
                f"Позиция {number}: укажите количество, цену и сумму."
            )
        expected = (item.quantity * item.unit_price).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if abs(expected - item.total_price) > tolerance:
            raise BusinessRuleError(
                f"Позиция {number}: количество × цена = {expected:.2f} ₽, "
                f"сумма позиции — {item.total_price:.2f} ₽. Проверьте значения."
            )
        items_sum += item.total_price

    if abs(items_sum - total_amount) > tolerance:
        raise BusinessRuleError(
            f"Сумма позиций {items_sum:.2f} ₽ отличается от итога "
            f"{total_amount:.2f} ₽. Допуск — {tolerance:.2f} ₽."
        )
