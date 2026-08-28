from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.models.enums import ReceiptStatus
from backend.app.models.receipt import Category, Receipt, ReceiptItem
from backend.app.models.user import User

pytestmark = pytest.mark.integration


USER_PAYLOAD = {
    "user_name": "Receipt",
    "user_surname": "Owner",
    "user_mail": "receipt-api@example.com",
    "user_password": "strong-test-password",
}

OTHER_USER_PAYLOAD = {
    "user_name": "Other",
    "user_surname": "Owner",
    "user_mail": "other-receipt-api@example.com",
    "user_password": "other-strong-password",
}


def register_and_login(
    client: TestClient,
    payload: dict[str, str] = USER_PAYLOAD,
) -> None:
    register_response = client.post(
        "/api/register_user",
        json=payload,
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/auth_login",
        json={
            "user_mail": payload["user_mail"],
            "user_password": payload["user_password"],
        },
    )
    assert login_response.status_code == 200


def get_registered_user(
    db_session: Session,
    email: str = USER_PAYLOAD["user_mail"],
) -> User:
    return db_session.scalars(select(User).where(User.user_mail == email)).one()


def add_receipts(
    db_session: Session,
    user: User,
    store_names: list[str],
) -> list[Receipt]:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    receipts = [
        Receipt(
            user=user,
            store_name=store_name,
            image_url=f"receipts/{index}.webp",
            created_at=created_at + timedelta(minutes=index),
        )
        for index, store_name in enumerate(store_names)
    ]
    db_session.add_all(receipts)
    db_session.commit()
    return receipts


def test_receipts_require_authentication(client: TestClient) -> None:
    response = client.get("/api/receipts")

    assert response.status_code == 401


def test_empty_receipt_list_returns_first_empty_page(
    client: TestClient,
) -> None:
    register_and_login(client)

    response = client.get("/api/receipts")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "page": 1,
        "page_size": 20,
        "total": 0,
        "total_pages": 0,
    }


def test_receipts_are_paginated_and_ordered_newest_first(
    client: TestClient,
    db_session: Session,
) -> None:
    register_and_login(client)
    user = get_registered_user(db_session)
    add_receipts(
        db_session,
        user,
        ["First", "Second", "Third", "Fourth", "Fifth"],
    )

    first_page = client.get(
        "/api/receipts",
        params={"page": 1, "page_size": 2},
    )
    second_page = client.get(
        "/api/receipts",
        params={"page": 2, "page_size": 2},
    )

    assert first_page.status_code == 200
    assert first_page.json()["page"] == 1
    assert first_page.json()["page_size"] == 2
    assert first_page.json()["total"] == 5
    assert first_page.json()["total_pages"] == 3
    assert [item["store_name"] for item in first_page.json()["items"]] == [
        "Fifth",
        "Fourth",
    ]

    assert second_page.status_code == 200
    assert second_page.json()["page"] == 2
    assert [item["store_name"] for item in second_page.json()["items"]] == [
        "Third",
        "Second",
    ]


def test_receipt_list_contains_only_current_users_receipts(
    client: TestClient,
    db_session: Session,
) -> None:
    register_and_login(client)
    current_user = get_registered_user(db_session)
    other_user = User(
        user_name="Other",
        user_surname="User",
        user_mail="other-receipt-owner@example.com",
        user_password_hash="test-password-hash",
    )
    add_receipts(db_session, current_user, ["Current user store"])
    add_receipts(db_session, other_user, ["Other user store"])

    response = client.get("/api/receipts")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["store_name"] for item in response.json()["items"]] == [
        "Current user store"
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"user_id": "00000000-0000-0000-0000-000000000000"},
    ],
)
def test_invalid_pagination_parameters_return_422(
    client: TestClient,
    params: dict[str, int | str],
) -> None:
    register_and_login(client)

    response = client.get("/api/receipts", params=params)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/receipts", None),
        ("GET", f"/api/receipts/{uuid4()}", None),
        ("PATCH", f"/api/receipts/{uuid4()}", {"store_name": "Store"}),
        ("DELETE", f"/api/receipts/{uuid4()}", None),
        (
            "POST",
            f"/api/receipts/{uuid4()}/items",
            {"raw_name": "Milk", "quantity": 1},
        ),
        (
            "PATCH",
            f"/api/receipts/{uuid4()}/items/{uuid4()}",
            {"raw_name": "Bread"},
        ),
        ("DELETE", f"/api/receipts/{uuid4()}/items/{uuid4()}", None),
        ("GET", "/api/categories", None),
    ],
)
def test_every_receipt_route_requires_authentication(
    client: TestClient,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    response = client.request(method, path, json=payload)

    assert response.status_code == 401


def test_receipt_filters_are_applied_together(
    client: TestClient,
    db_session: Session,
) -> None:
    register_and_login(client)
    user = get_registered_user(db_session)
    target_date = datetime(2026, 5, 10, 12, tzinfo=timezone.utc)
    db_session.add_all(
        [
            Receipt(
                user=user,
                store_name="SuperMarket",
                purchase_datetime=target_date,
                status=ReceiptStatus.COMPLETED,
                image_url="receipts/matching.webp",
            ),
            Receipt(
                user=user,
                store_name="Other store",
                purchase_datetime=target_date,
                status=ReceiptStatus.COMPLETED,
                image_url="receipts/wrong-store.webp",
            ),
            Receipt(
                user=user,
                store_name="SuperMarket",
                purchase_datetime=target_date - timedelta(days=1),
                status=ReceiptStatus.COMPLETED,
                image_url="receipts/wrong-date.webp",
            ),
            Receipt(
                user=user,
                store_name="SuperMarket",
                purchase_datetime=target_date,
                status=ReceiptStatus.FAILED,
                image_url="receipts/wrong-status.webp",
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        "/api/receipts",
        params={
            "date_from": "2026-05-10",
            "date_to": "2026-05-10",
            "store_name": "market",
            "status": "completed",
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["store_name"] == "SuperMarket"


def test_get_receipt_returns_items_without_orm_or_secret_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    register_and_login(client)
    user = get_registered_user(db_session)
    category = Category(category_name="Drinks")
    receipt = Receipt(
        user=user,
        store_name="Coffee shop",
        total_amount=Decimal("25.50"),
        image_url="receipts/coffee.webp",
    )
    receipt.items.append(
        ReceiptItem(
            category=category,
            raw_name="Coffee",
            quantity=1,
            total_price=Decimal("25.50"),
        )
    )
    db_session.add(receipt)
    db_session.commit()

    response = client.get(f"/api/receipts/{receipt.receipt_id}")

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["receipt_id"] == str(receipt.receipt_id)
    assert response_data["total_amount"] == "25.50"
    assert len(response_data["items"]) == 1
    assert response_data["items"][0]["raw_name"] == "Coffee"
    assert response_data["items"][0]["category_id"] == str(category.category_id)
    assert "user_password_hash" not in response_data
    assert "_sa_instance_state" not in response_data


def test_update_receipt_changes_only_provided_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    register_and_login(client)
    user = get_registered_user(db_session)
    receipt = Receipt(
        user=user,
        store_name="Old store",
        store_inn="1234567890",
        image_url="receipts/update.webp",
    )
    db_session.add(receipt)
    db_session.commit()

    response = client.patch(
        f"/api/receipts/{receipt.receipt_id}",
        json={"store_name": "New store", "total_amount": "175.50"},
    )

    assert response.status_code == 200
    assert response.json()["store_name"] == "New store"
    assert response.json()["store_inn"] == "1234567890"
    assert response.json()["total_amount"] == "175.50"

    db_session.expire_all()
    saved_receipt = db_session.get(Receipt, receipt.receipt_id)
    assert saved_receipt is not None
    assert saved_receipt.store_name == "New store"
    assert saved_receipt.store_inn == "1234567890"
    assert saved_receipt.total_amount == Decimal("175.50")


def test_delete_receipt_cascades_to_items(
    client: TestClient,
    db_session: Session,
) -> None:
    register_and_login(client)
    user = get_registered_user(db_session)
    receipt = Receipt(user=user, image_url="receipts/delete.webp")
    item = ReceiptItem(receipt=receipt, raw_name="Milk", quantity=1)
    db_session.add(item)
    db_session.commit()
    receipt_id = receipt.receipt_id
    item_id = item.receipt_item_id

    response = client.delete(f"/api/receipts/{receipt_id}")

    assert response.status_code == 204
    assert response.content == b""
    db_session.expire_all()
    assert db_session.get(Receipt, receipt_id) is None
    assert db_session.get(ReceiptItem, item_id) is None
    assert client.get(f"/api/receipts/{receipt_id}").status_code == 404


def test_create_update_and_delete_receipt_item(
    client: TestClient,
    db_session: Session,
) -> None:
    register_and_login(client)
    user = get_registered_user(db_session)
    receipt = Receipt(user=user, image_url="receipts/item-crud.webp")
    category = Category(category_name="Products")
    db_session.add_all([receipt, category])
    db_session.commit()

    create_response = client.post(
        f"/api/receipts/{receipt.receipt_id}/items",
        json={
            "raw_name": "Milk",
            "category_id": str(category.category_id),
            "quantity": 2,
            "unit_price": "12.50",
            "total_price": "25.00",
        },
    )

    assert create_response.status_code == 201
    item_id = create_response.json()["receipt_item_id"]
    assert create_response.json()["category_id"] == str(category.category_id)

    update_response = client.patch(
        f"/api/receipts/{receipt.receipt_id}/items/{item_id}",
        json={
            "raw_name": "Whole milk",
            "quantity": 3,
            "category_id": None,
        },
    )

    assert update_response.status_code == 200
    assert update_response.json()["raw_name"] == "Whole milk"
    assert update_response.json()["quantity"] == 3
    assert update_response.json()["category_id"] is None
    assert update_response.json()["unit_price"] == "12.50"

    delete_response = client.delete(
        f"/api/receipts/{receipt.receipt_id}/items/{item_id}"
    )

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    db_session.expire_all()
    assert db_session.get(ReceiptItem, item_id) is None
    assert client.get(f"/api/receipts/{receipt.receipt_id}").json()["items"] == []


def test_unknown_category_is_rejected_for_item_create_and_update(
    client: TestClient,
    db_session: Session,
) -> None:
    register_and_login(client)
    user = get_registered_user(db_session)
    receipt = Receipt(user=user, image_url="receipts/category-check.webp")
    item = ReceiptItem(receipt=receipt, raw_name="Milk", quantity=1)
    db_session.add(item)
    db_session.commit()
    unknown_category_id = uuid4()

    create_response = client.post(
        f"/api/receipts/{receipt.receipt_id}/items",
        json={
            "raw_name": "Bread",
            "quantity": 1,
            "category_id": str(unknown_category_id),
        },
    )
    update_response = client.patch(
        f"/api/receipts/{receipt.receipt_id}/items/{item.receipt_item_id}",
        json={"category_id": str(unknown_category_id)},
    )

    assert create_response.status_code == 404
    assert create_response.json() == {"detail": "Category not found"}
    assert update_response.status_code == 404
    assert update_response.json() == {"detail": "Category not found"}
    db_session.expire_all()
    saved_items = db_session.scalars(
        select(ReceiptItem).where(ReceiptItem.receipt_id == receipt.receipt_id)
    ).all()
    assert len(saved_items) == 1
    assert saved_items[0].category_id is None


def test_missing_receipt_and_item_resources_return_404(
    client: TestClient,
    db_session: Session,
) -> None:
    register_and_login(client)
    user = get_registered_user(db_session)
    receipt = Receipt(user=user, image_url="receipts/missing-item.webp")
    db_session.add(receipt)
    db_session.commit()
    missing_receipt_id = uuid4()
    missing_item_id = uuid4()

    missing_receipt_responses = [
        client.get(f"/api/receipts/{missing_receipt_id}"),
        client.patch(
            f"/api/receipts/{missing_receipt_id}",
            json={"store_name": "Store"},
        ),
        client.delete(f"/api/receipts/{missing_receipt_id}"),
        client.post(
            f"/api/receipts/{missing_receipt_id}/items",
            json={"raw_name": "Milk", "quantity": 1},
        ),
    ]
    missing_item_responses = [
        client.patch(
            f"/api/receipts/{receipt.receipt_id}/items/{missing_item_id}",
            json={"raw_name": "Milk"},
        ),
        client.delete(f"/api/receipts/{receipt.receipt_id}/items/{missing_item_id}"),
    ]

    assert [response.status_code for response in missing_receipt_responses] == [
        404,
        404,
        404,
        404,
    ]
    assert all(
        response.json() == {"detail": "Receipt not found"}
        for response in missing_receipt_responses
    )
    assert [response.status_code for response in missing_item_responses] == [404, 404]
    assert all(
        response.json() == {"detail": "Receipt item not found"}
        for response in missing_item_responses
    )


def test_other_user_cannot_access_or_modify_receipt_resources(
    client: TestClient,
    db_session: Session,
) -> None:
    register_and_login(client)
    owner = get_registered_user(db_session)
    receipt = Receipt(user=owner, image_url="receipts/private.webp")
    item = ReceiptItem(receipt=receipt, raw_name="Private item", quantity=1)
    db_session.add(item)
    db_session.commit()
    receipt_id = receipt.receipt_id
    item_id = item.receipt_item_id

    with TestClient(app) as other_client:
        register_and_login(other_client, OTHER_USER_PAYLOAD)

        assert other_client.get("/api/receipts").json()["total"] == 0
        responses = [
            other_client.get(f"/api/receipts/{receipt_id}"),
            other_client.patch(
                f"/api/receipts/{receipt_id}",
                json={"store_name": "Changed"},
            ),
            other_client.delete(f"/api/receipts/{receipt_id}"),
            other_client.post(
                f"/api/receipts/{receipt_id}/items",
                json={"raw_name": "Injected item", "quantity": 1},
            ),
            other_client.patch(
                f"/api/receipts/{receipt_id}/items/{item_id}",
                json={"raw_name": "Changed item"},
            ),
            other_client.delete(f"/api/receipts/{receipt_id}/items/{item_id}"),
        ]

    assert all(response.status_code == 404 for response in responses)
    assert all(
        response.json() == {"detail": "Receipt not found"} for response in responses
    )
    assert client.get(f"/api/receipts/{receipt_id}").status_code == 200
    db_session.expire_all()
    saved_receipt = db_session.get(Receipt, receipt_id)
    saved_item = db_session.get(ReceiptItem, item_id)
    assert saved_receipt is not None
    assert saved_receipt.store_name is None
    assert saved_item is not None
    assert saved_item.raw_name == "Private item"


def test_categories_are_authenticated_and_returned_in_name_order(
    client: TestClient,
    db_session: Session,
) -> None:
    assert client.get("/api/categories").status_code == 401
    register_and_login(client)
    db_session.add_all(
        [
            Category(category_name="Zeta"),
            Category(category_name="Alpha"),
        ]
    )
    db_session.commit()

    response = client.get("/api/categories")

    assert response.status_code == 200
    assert [category["category_name"] for category in response.json()] == [
        "Alpha",
        "Zeta",
    ]
    assert all(
        set(category) == {"category_id", "category_name", "parent_id"}
        for category in response.json()
    )


def test_empty_patch_requests_are_rejected(
    client: TestClient,
    db_session: Session,
) -> None:
    register_and_login(client)
    user = get_registered_user(db_session)
    receipt = Receipt(user=user, image_url="receipts/validation.webp")
    item = ReceiptItem(receipt=receipt, raw_name="Milk", quantity=1)
    db_session.add(item)
    db_session.commit()

    receipt_response = client.patch(f"/api/receipts/{receipt.receipt_id}", json={})
    item_response = client.patch(
        f"/api/receipts/{receipt.receipt_id}/items/{item.receipt_item_id}",
        json={},
    )

    assert receipt_response.status_code == 422
    assert item_response.status_code == 422
