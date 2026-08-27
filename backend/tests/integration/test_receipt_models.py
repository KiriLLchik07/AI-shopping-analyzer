from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.enums import ReceiptStatus
from backend.app.models.receipt import Category, Receipt, ReceiptItem
from backend.app.models.user import User

pytestmark = pytest.mark.integration


def make_user() -> User:
    return User(
        user_name="Receipt",
        user_surname="Owner",
        user_mail="receipt-owner@example.com",
        user_password_hash="test-password-hash",
    )


def make_receipt(user: User, **values: object) -> Receipt:
    return Receipt(
        user=user,
        image_url="receipts/test-receipt.webp",
        **values,
    )


def test_minimal_receipt_has_expected_defaults(
    db_session: Session,
) -> None:
    receipt = make_receipt(make_user())
    db_session.add(receipt)
    db_session.commit()
    db_session.refresh(receipt)

    assert receipt.status is ReceiptStatus.UPLOADED
    assert receipt.store_name is None
    assert receipt.store_inn is None
    assert receipt.purchase_datetime is None
    assert receipt.total_amount is None
    assert receipt.raw_ocr_text is None
    assert receipt.created_at is not None
    assert receipt.updated_at is not None


@pytest.mark.parametrize("status", list(ReceiptStatus))
def test_receipt_status_round_trip(
    db_session: Session,
    status: ReceiptStatus,
) -> None:
    receipt = make_receipt(make_user(), status=status)
    db_session.add(receipt)
    db_session.commit()

    receipt_id = receipt.receipt_id
    db_session.expunge_all()

    saved_receipt = db_session.get(Receipt, receipt_id)

    assert saved_receipt is not None
    assert saved_receipt.status is status


def test_money_values_are_returned_as_exact_decimals(
    db_session: Session,
) -> None:
    receipt = make_receipt(
        make_user(),
        total_amount=Decimal("123.45"),
    )
    item = ReceiptItem(
        receipt=receipt,
        raw_name="Coffee",
        quantity=1,
        weight=Decimal("1.25"),
        unit_price=Decimal("10.10"),
        total_price=Decimal("12.63"),
        discount_amount=Decimal("0.50"),
    )
    db_session.add(item)
    db_session.commit()

    receipt_id = receipt.receipt_id
    item_id = item.receipt_item_id
    db_session.expunge_all()

    saved_receipt = db_session.get(Receipt, receipt_id)
    saved_item = db_session.get(ReceiptItem, item_id)

    assert saved_receipt is not None
    assert saved_item is not None
    assert saved_receipt.total_amount == Decimal("123.45")
    assert saved_item.weight == Decimal("1.25")
    assert saved_item.unit_price == Decimal("10.10")
    assert saved_item.total_price == Decimal("12.63")
    assert saved_item.discount_amount == Decimal("0.50")
    assert isinstance(saved_receipt.total_amount, Decimal)
    assert isinstance(saved_item.total_price, Decimal)


def test_receipt_item_and_category_relationships(
    db_session: Session,
) -> None:
    parent = Category(category_name="Food")
    category = Category(category_name="Snacks", parent=parent)
    receipt = make_receipt(make_user())
    item = ReceiptItem(
        receipt=receipt,
        category=category,
        raw_name="Chips",
        quantity=1,
    )
    db_session.add_all([parent, item])
    db_session.commit()

    receipt_id = receipt.receipt_id
    category_id = category.category_id
    db_session.expunge_all()

    saved_receipt = db_session.get(Receipt, receipt_id)
    saved_category = db_session.get(Category, category_id)

    assert saved_receipt is not None
    assert saved_category is not None
    assert saved_receipt.user.user_mail == "receipt-owner@example.com"
    assert [saved_item.raw_name for saved_item in saved_receipt.items] == ["Chips"]
    assert saved_receipt.items[0].category is saved_category
    assert saved_category.parent is not None
    assert saved_category.parent.category_name == "Food"
    assert saved_category in saved_category.parent.children


def test_deleting_receipt_cascades_to_items(
    db_session: Session,
) -> None:
    receipt = make_receipt(make_user())
    item = ReceiptItem(receipt=receipt, raw_name="Milk", quantity=1)
    db_session.add(item)
    db_session.commit()

    receipt_id = receipt.receipt_id
    item_id = item.receipt_item_id
    db_session.expunge_all()

    db_session.execute(delete(Receipt).where(Receipt.receipt_id == receipt_id))
    db_session.commit()

    assert db_session.get(Receipt, receipt_id) is None
    assert db_session.get(ReceiptItem, item_id) is None


def test_deleting_user_cascades_to_receipts_and_items(
    db_session: Session,
) -> None:
    user = make_user()
    receipt = make_receipt(user)
    item = ReceiptItem(receipt=receipt, raw_name="Bread", quantity=1)
    db_session.add(item)
    db_session.commit()

    user_id = user.user_id
    receipt_id = receipt.receipt_id
    item_id = item.receipt_item_id
    db_session.expunge_all()

    db_session.execute(delete(User).where(User.user_id == user_id))
    db_session.commit()

    assert db_session.get(User, user_id) is None
    assert db_session.get(Receipt, receipt_id) is None
    assert db_session.get(ReceiptItem, item_id) is None


def test_deleting_categories_sets_foreign_keys_to_null(
    db_session: Session,
) -> None:
    parent = Category(category_name="Food")
    category = Category(category_name="Drinks", parent=parent)
    receipt = make_receipt(make_user())
    item = ReceiptItem(
        receipt=receipt,
        category=category,
        raw_name="Water",
        quantity=1,
    )
    db_session.add_all([parent, item])
    db_session.commit()

    parent_id = parent.category_id
    category_id = category.category_id
    item_id = item.receipt_item_id
    db_session.expunge_all()

    db_session.execute(delete(Category).where(Category.category_id == parent_id))
    db_session.commit()
    db_session.expire_all()

    saved_category = db_session.get(Category, category_id)
    assert saved_category is not None
    assert saved_category.parent_id is None

    db_session.execute(delete(Category).where(Category.category_id == category_id))
    db_session.commit()
    db_session.expire_all()

    saved_item = db_session.get(ReceiptItem, item_id)
    assert saved_item is not None
    assert saved_item.category_id is None


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("quantity", 0),
        ("weight", Decimal("0.00")),
        ("unit_price", Decimal("-0.01")),
        ("total_price", Decimal("0.00")),
        ("confidence", -0.01),
        ("confidence", 1.01),
    ],
)
def test_receipt_item_constraints_reject_invalid_values(
    db_session: Session,
    field: str,
    invalid_value: object,
) -> None:
    receipt = make_receipt(make_user())
    item_values = {
        "receipt": receipt,
        "raw_name": "Invalid item",
        "quantity": 1,
        field: invalid_value,
    }
    db_session.add(ReceiptItem(**item_values))

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


@pytest.mark.parametrize("invalid_total", [Decimal("0.00"), Decimal("-0.01")])
def test_receipt_constraint_rejects_non_positive_total(
    db_session: Session,
    invalid_total: Decimal,
) -> None:
    db_session.add(make_receipt(make_user(), total_amount=invalid_total))

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_category_name_must_be_unique(db_session: Session) -> None:
    db_session.add_all(
        [
            Category(category_name="Transport"),
            Category(category_name="Transport"),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_item_defaults_and_timestamps_are_saved(
    db_session: Session,
) -> None:
    category = Category(category_name="Household")
    receipt = make_receipt(make_user())
    item = ReceiptItem(
        receipt=receipt,
        category=category,
        raw_name="Soap",
        quantity=1,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    db_session.refresh(category)

    assert item.discount_amount == Decimal("0.00")
    assert item.is_impulse_candidate is False
    assert receipt.created_at is not None
    assert receipt.updated_at is not None
    assert item.created_at is not None
    assert item.updated_at is not None
    assert category.created_at is not None
    assert category.updated_at is not None


def test_receipt_items_can_be_selected_by_receipt_id(
    db_session: Session,
) -> None:
    receipt = make_receipt(make_user())
    receipt.items = [
        ReceiptItem(raw_name="First", quantity=1),
        ReceiptItem(raw_name="Second", quantity=2),
    ]
    db_session.add(receipt)
    db_session.commit()

    items = db_session.scalars(
        select(ReceiptItem).where(ReceiptItem.receipt_id == receipt.receipt_id)
    ).all()

    assert {item.raw_name for item in items} == {"First", "Second"}
