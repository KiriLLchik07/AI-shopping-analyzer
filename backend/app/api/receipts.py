from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from backend.app.api.dependencies.auth import get_current_user
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.request import (
    ReceiptItemCreateRequest,
    ReceiptListParams,
    ReceiptUpdateRequest,
)
from backend.app.schemas.response import (
    ReceiptItemResponse,
    ReceiptListResponse,
    ReceiptResponse,
)
from backend.app.services.receipt_service import ReceiptService

router = APIRouter()


@router.get("/api/receipts", response_model=ReceiptListResponse)
def get_receipts_with_pagination(
    params: Annotated[ReceiptListParams, Query()],
    user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[Session, Depends(get_db)],
) -> ReceiptListResponse:
    receipts, total = ReceiptService(db_session).get_receipts(
        user_id=user.user_id, params=params
    )
    total_pages = (total + params.page_size - 1) // params.page_size

    return ReceiptListResponse(
        items=[ReceiptResponse.model_validate(receipt) for receipt in receipts],
        page=params.page,
        page_size=params.page_size,
        total=total,
        total_pages=total_pages,
    )


@router.get("/api/receipts/{receipt_id}", response_model=ReceiptResponse)
def get_receipt_by_id(
    receipt_id: Annotated[UUID, Path()],
    db_session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ReceiptResponse:

    receipt = ReceiptService(db_session).get_receipt_by_id(receipt_id, user.user_id)
    return ReceiptResponse.model_validate(receipt)


@router.patch("/api/receipts/{receipt_id}", response_model=ReceiptResponse)
def update_receipt(
    receipt_id: Annotated[UUID, Path()],
    payload: ReceiptUpdateRequest,
    db_session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ReceiptResponse:

    receipt = ReceiptService(db_session).update_receipt(
        payload=payload, receipt_id=receipt_id, user_id=user.user_id
    )

    return ReceiptResponse.model_validate(receipt)


@router.delete("/api/receipts/{receipt_id}", status_code=204)
def delete_receipt(
    receipt_id: Annotated[UUID, Path()],
    db_session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:

    ReceiptService(db_session).delete_receipt(
        receipt_id=receipt_id,
        user_id=user.user_id,
    )


@router.post(
    "/api/receipts/{receipt_id}/items",
    status_code=201,
    response_model=ReceiptItemResponse,
)
def create_receipt_item(
    payload: ReceiptItemCreateRequest,
    receipt_id: Annotated[UUID, Path()],
    db_session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ReceiptItemResponse:

    receipt_item = ReceiptService(db_session).create_receipt_item(
        payload=payload, receipt_id=receipt_id, user_id=user.user_id
    )

    return ReceiptItemResponse.model_validate(receipt_item)
