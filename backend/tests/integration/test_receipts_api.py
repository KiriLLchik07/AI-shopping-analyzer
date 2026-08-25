from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.receipt import Receipt
from backend.app.models.user import User


pytestmark = pytest.mark.integration


USER_PAYLOAD = {
    "user_name": "Receipt",
    "user_surname": "Owner",
    "user_mail": "receipt-api@example.com",
    "user_password": "strong-test-password",
}


def register_and_login(client: TestClient) -> None:
    register_response = client.post(
        "/api/register_user",
        json=USER_PAYLOAD,
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/auth_login",
        json={
            "user_mail": USER_PAYLOAD["user_mail"],
            "user_password": USER_PAYLOAD["user_password"],
        },
    )
    assert login_response.status_code == 200


def get_registered_user(db_session: Session) -> User:
    return db_session.scalars(
        select(User).where(User.user_mail == USER_PAYLOAD["user_mail"])
    ).one()


def add_receipts(
    db_session: Session,
    user: User,
    store_names: list[str],
) -> None:
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
