import logging
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    Response,
    UploadFile,
)
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.dependencies.auth import get_current_user
from backend.app.api.dependencies.storage import get_object_storage
from backend.app.core.config import image_settings
from backend.app.db.session import SessionLocal, get_db
from backend.app.models.user import User
from backend.app.schemas.request import (
    ReceiptItemCreateRequest,
    ReceiptItemUpdateRequest,
    ReceiptListParams,
    ReceiptReprocessRequest,
    ReceiptUpdateRequest,
)
from backend.app.schemas.response import (
    ReceiptDetailResponse,
    ReceiptImageUrlResponse,
    ReceiptItemResponse,
    ReceiptListResponse,
    ReceiptReprocessResponse,
    ReceiptResponse,
)
from backend.app.services.receipt_processing_service import ReceiptProcessingService
from backend.app.services.receipt_service import ReceiptService
from backend.app.services.receipt_upload_service import ReceiptUploadService
from backend.app.storage.interface import ObjectStorage
from backend.app.workers.queue import enqueue_receipt

router = APIRouter()

logger = logging.getLogger(__name__)


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


@router.get("/api/receipts/{receipt_id}", response_model=ReceiptDetailResponse)
def get_receipt_by_id(
    receipt_id: Annotated[UUID, Path()],
    db_session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ReceiptDetailResponse:

    receipt = ReceiptService(db_session).get_receipt_by_id(receipt_id, user.user_id)
    return ReceiptDetailResponse.model_validate(receipt)


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
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> None:

    ReceiptService(db_session).delete_receipt(
        receipt_id=receipt_id,
        user_id=user.user_id,
        object_storage=object_storage,
        cleanup_session_factory=SessionLocal,
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


@router.patch(
    "/api/receipts/{receipt_id}/items/{receipt_item_id}",
    response_model=ReceiptItemResponse,
)
def update_receipt_item(
    receipt_id: Annotated[UUID, Path()],
    receipt_item_id: Annotated[UUID, Path()],
    payload: ReceiptItemUpdateRequest,
    db_session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ReceiptItemResponse:

    receipt_item = ReceiptService(db_session).update_receipt_item(
        payload=payload,
        receipt_id=receipt_id,
        receipt_item_id=receipt_item_id,
        user_id=user.user_id,
    )

    return ReceiptItemResponse.model_validate(receipt_item)


@router.delete(
    "/api/receipts/{receipt_id}/items/{receipt_item_id}",
    status_code=204,
)
def delete_receipt_item(
    receipt_id: Annotated[UUID, Path()],
    receipt_item_id: Annotated[UUID, Path()],
    db_session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:

    ReceiptService(db_session).delete_receipt_item(
        receipt_id=receipt_id,
        receipt_item_id=receipt_item_id,
        user_id=user.user_id,
    )


@router.post("/api/receipts/upload", status_code=201, response_model=ReceiptResponse)
def upload_receipt(
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[Session, Depends(get_db)],
    object_storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> ReceiptResponse:
    service = ReceiptUploadService(
        db_session=db_session,
        object_storage=object_storage,
        cleanup_session_factory=SessionLocal,
    )
    receipt = service.upload(user_id=user.user_id, file=file.file)
    try:
        enqueue_receipt(
            receipt.receipt_id, processing_version=receipt.processing_version
        )
    except RedisError as error:
        logger.exception(
            "Could not confirm receipt enqueue receipt_id=%s",
            receipt.receipt_id,
        )

        raise HTTPException(
            status_code=503,
            detail={
                "code": "receipt_enqueue_unconfirmed",
                "message": (
                    "Чек сохранён, но не удалось подтвердить постановку "
                    "в очередь обработки. Не загружайте изображение повторно."
                ),
                "receipt_id": str(receipt.receipt_id),
            },
        ) from error

    return ReceiptResponse.model_validate(receipt)


@router.get(
    "/api/receipts/{receipt_id}/image-url",
    status_code=200,
    response_model=ReceiptImageUrlResponse,
)
def get_receipt_image_url(
    response: Response,
    receipt_id: Annotated[UUID, Path()],
    user: Annotated[User, Depends(get_current_user)],
    db_session: Annotated[Session, Depends(get_db)],
    object_storage: Annotated[
        ObjectStorage,
        Depends(get_object_storage),
    ],
) -> ReceiptImageUrlResponse:
    image_url = ReceiptService(db_session).get_image_url(
        receipt_id=receipt_id,
        user_id=user.user_id,
        object_storage=object_storage,
        expires_seconds=image_settings.url_ttl_seconds,
    )

    response.headers["Cache-Control"] = "no-store"

    return ReceiptImageUrlResponse(
        image_url=image_url,
        expires_in=image_settings.url_ttl_seconds,
    )


@router.post(
    "/api/receipts/{receipt_id}/reprocess",
    status_code=202,
    response_model=ReceiptReprocessResponse,
)
def reprocess_receipt(
    receipt_id: Annotated[UUID, Path()],
    user: Annotated[User, Depends(get_current_user)],
    payload: ReceiptReprocessRequest | None = None,
) -> ReceiptReprocessResponse:
    service = ReceiptProcessingService(SessionLocal)

    ticket = service.prepare_process(
        receipt_id=receipt_id,
        user_id=user.user_id,
        replace_items=payload.replace_items if payload else False,
    )

    try:
        job_id = enqueue_receipt(
            ticket.receipt_id,
            processing_version=ticket.processing_version,
        )
    except RedisError as error:
        logger.exception(
            "Could not confirm reprocess enqueue receipt_id=%s processing_version=%s",
            ticket.receipt_id,
            ticket.processing_version,
        )

        try:
            service.mark_enqueue_unconfirmed(
                receipt_id=ticket.receipt_id,
                processing_version=ticket.processing_version,
            )
        except SQLAlchemyError:
            logger.exception(
                "Could not persist reprocess enqueue failure "
                "receipt_id=%s processing_version=%s",
                ticket.receipt_id,
                ticket.processing_version,
            )

        raise HTTPException(
            status_code=503,
            detail={
                "code": "receipt_enqueue_unconfirmed",
                "message": (
                    "Не удалось подтвердить постановку чека "
                    "в очередь. Проверьте текущий статус чека."
                ),
                "receipt_id": str(ticket.receipt_id),
                "processing_version": ticket.processing_version,
            },
        ) from error

    return ReceiptReprocessResponse(
        receipt_id=ticket.receipt_id,
        processing_version=ticket.processing_version,
        job_id=job_id,
    )
