import logging
from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import parsing_settings
from backend.app.core.exceptions import (
    BusinessRuleError,
    CategoryNotFoundError,
    ConflictError,
    ReceiptDeletionUnavailableError,
    ReceiptImageUnavailableError,
    ReceiptItemNotFoundError,
    ReceiptNotFoundError,
)
from backend.app.models.enums import ReceiptStatus
from backend.app.models.object_cleanup_task import ObjectCleanupTask
from backend.app.models.receipt import Receipt, ReceiptItem
from backend.app.repositories.category_repository import CategoryRepository
from backend.app.repositories.receipt_repository import ReceiptRepository
from backend.app.schemas.items import ReceiptItemData
from backend.app.schemas.request import (
    ReceiptItemCreateRequest,
    ReceiptItemUpdateRequest,
    ReceiptListParams,
    ReceiptUpdateRequest,
)
from backend.app.services.object_cleanup_service import cleanup_one
from backend.app.services.receipt_arithmetic import validate_receipt_arithmetic
from backend.app.services.receipt_categorization_service import (
    ReceiptCategorizationService,
)
from backend.app.storage.exception import ObjectStorageError
from backend.app.storage.interface import ObjectStorage

logger = logging.getLogger(__name__)


class ReceiptService:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.repository = ReceiptRepository(db_session)
        self.category_repository = CategoryRepository(db_session)

    def get_receipts(
        self, user_id: UUID, params: ReceiptListParams
    ) -> tuple[list[Receipt], int]:
        offset = (params.page - 1) * params.page_size

        date_from = (
            datetime.combine(params.date_from, time.min, timezone.utc)
            if params.date_from
            else None
        )

        date_to = (
            datetime.combine(
                params.date_to + timedelta(days=1),
                time.min,
                timezone.utc,
            )
            if params.date_to
            else None
        )

        filters = {
            "date_from": date_from,
            "date_to": date_to,
            "store_name": params.store_name,
            "status": params.status,
        }

        receipts = self.repository.get_receipts(
            user_id=user_id,
            offset=offset,
            limit=params.page_size,
            **filters,
        )
        total = self.repository.count_receipts(user_id, **filters)

        return receipts, total

    def get_receipt_by_id(
        self, receipt_id: UUID, user_id: UUID, for_update: bool = False
    ) -> Receipt:
        receipt = self.repository.get_receipt_by_id(
            receipt_id, user_id, for_update=for_update
        )
        if receipt is None:
            raise ReceiptNotFoundError()

        return receipt

    def update_receipt(
        self, payload: ReceiptUpdateRequest, receipt_id: UUID, user_id: UUID
    ) -> Receipt:
        receipt = self.get_receipt_by_id(receipt_id, user_id, for_update=True)

        update_data = payload.model_dump(exclude_unset=True)

        receipt = self.repository.update_receipt(receipt, update_data)

        self.db_session.commit()
        self.db_session.refresh(receipt)

        return receipt

    def confirm_receipt(self, receipt_id: UUID, user_id: UUID) -> Receipt:
        receipt = self.get_receipt_by_id(receipt_id, user_id, for_update=True)
        if receipt.status not in {ReceiptStatus.NEED_REVIEW, ReceiptStatus.COMPLETED}:
            raise ConflictError("Only a receipt awaiting review can be confirmed")
        if receipt.status == ReceiptStatus.NEED_REVIEW or receipt.confirmed_at is None:
            try:
                items = [
                    ReceiptItemData.model_validate(item)
                    for item in self.repository.get_receipt_items(receipt_id)
                ]
            except ValidationError as error:
                raise BusinessRuleError(
                    "Проверьте значения товарных позиций: числа должны быть "
                    "конечными и неотрицательными, количество — положительным."
                ) from error
            validate_receipt_arithmetic(
                items, receipt.total_amount, tolerance=parsing_settings.total_tolerance
            )
            self.repository.confirm_receipt(
                receipt, confirmed_at=datetime.now(timezone.utc)
            )

        self.db_session.commit()
        self.db_session.refresh(receipt)
        return receipt

    def delete_receipt(
        self,
        receipt_id: UUID,
        user_id: UUID,
        object_storage: ObjectStorage,
        cleanup_session_factory: sessionmaker[Session],
    ) -> None:
        try:
            receipt = self.repository.get_receipt_by_id(
                receipt_id, user_id, for_update=True
            )
            if receipt is None:
                raise ReceiptNotFoundError()

            task = self.db_session.get(ObjectCleanupTask, receipt_id)
            if task is None:
                self.db_session.add(
                    ObjectCleanupTask(
                        receipt_id=receipt_id,
                        object_key=receipt.image_object_key,
                    )
                )

            self.repository.delete_receipt(receipt)
            self.db_session.commit()
        except SQLAlchemyError as error:
            try:
                self.db_session.rollback()
            except SQLAlchemyError:
                logger.exception("Failed to roll back receipt deletion")
            logger.exception("Failed to commit deletion of receipt %s", receipt_id)
            raise ReceiptDeletionUnavailableError() from error

        try:
            cleanup_one(receipt_id, cleanup_session_factory, object_storage)
        except (SQLAlchemyError, ObjectStorageError):
            logger.exception(
                "Receipt %s deleted; image cleanup needs retry", receipt_id
            )

    def create_receipt_item(
        self,
        payload: ReceiptItemCreateRequest,
        receipt_id: UUID,
        user_id: UUID,
    ) -> ReceiptItem:

        receipt = self.get_receipt_by_id(
            receipt_id=receipt_id, user_id=user_id, for_update=True
        )

        self._validate_category(payload.category_id)

        item_data = (
            ReceiptCategorizationService(self.db_session)
            .suggest_items((ReceiptItemData.model_validate(payload),))[0]
            .model_dump()
        )
        if "category_id" in payload.model_fields_set:
            item_data["category_id"] = payload.category_id
            item_data["category_confirmed_at"] = datetime.now(timezone.utc)
            item_data["category_source"] = "manual"

        receipt_item = self.repository.create_receipt_item(
            receipt_id=receipt.receipt_id, item_data=item_data
        )

        self.repository.increment_items_revision(receipt_id)
        self.db_session.commit()
        self.db_session.refresh(receipt_item)

        return receipt_item

    def _get_receipt_item(
        self,
        receipt_id: UUID,
        receipt_item_id: UUID,
        user_id: UUID,
    ) -> ReceiptItem:

        receipt = self.get_receipt_by_id(
            receipt_id=receipt_id, user_id=user_id, for_update=True
        )

        receipt_item = self.repository.get_receipt_item(
            receipt_id=receipt.receipt_id,
            receipt_item_id=receipt_item_id,
        )

        if receipt_item is None:
            raise ReceiptItemNotFoundError

        return receipt_item

    def update_receipt_item(
        self,
        payload: ReceiptItemUpdateRequest,
        receipt_id: UUID,
        receipt_item_id: UUID,
        user_id: UUID,
    ) -> ReceiptItem:
        receipt_item = self._get_receipt_item(
            receipt_id=receipt_id,
            receipt_item_id=receipt_item_id,
            user_id=user_id,
        )

        update_data = payload.model_dump(exclude_unset=True)

        if "category_id" in update_data and update_data["category_id"] is not None:
            self._validate_category(update_data["category_id"])

        if {"raw_name", "normalized_name"} & update_data.keys():
            candidate = ReceiptItemData.model_validate(receipt_item).model_copy(
                update=update_data
            )
            if "raw_name" in update_data and "normalized_name" not in update_data:
                candidate = candidate.model_copy(update={"normalized_name": None})
            suggestion = ReceiptCategorizationService(self.db_session).suggest_items(
                (candidate,)
            )[0]
            update_data.update(
                suggestion.model_dump(
                    include={
                        "suggested_category_id",
                        "category_rule_version",
                        "category_match",
                        "category_input",
                    }
                )
            )
            legacy_category = (
                receipt_item.category_rule_version is None
                and receipt_item.category_id is not None
            )
            has_manual_category = (
                receipt_item.category_source in {"manual", "legacy"} or legacy_category
            )
            if legacy_category and receipt_item.category_source != "manual":
                update_data["category_source"] = "legacy"
            if "category_id" not in update_data and not has_manual_category:
                update_data["category_id"] = suggestion.suggested_category_id
        if "category_id" in payload.model_fields_set:
            update_data["category_confirmed_at"] = datetime.now(timezone.utc)
            update_data["category_source"] = "manual"

        receipt_item = self.repository.update_receipt_item(
            receipt_item=receipt_item,
            update_data=update_data,
        )

        self.repository.increment_items_revision(receipt_id)
        self.db_session.commit()
        self.db_session.refresh(receipt_item)

        return receipt_item

    def delete_receipt_item(
        self,
        receipt_id: UUID,
        receipt_item_id: UUID,
        user_id: UUID,
    ) -> None:
        receipt_item = self._get_receipt_item(
            receipt_id=receipt_id,
            receipt_item_id=receipt_item_id,
            user_id=user_id,
        )

        self.repository.delete_receipt_item(receipt_item)
        self.repository.increment_items_revision(receipt_id)
        self.db_session.commit()

    def _validate_category(self, category_id: UUID | None) -> None:
        if category_id is None:
            return

        category = self.category_repository.get_category_by_id(category_id)

        if category is None:
            raise CategoryNotFoundError

    def get_image_url(
        self,
        receipt_id: UUID,
        user_id: UUID,
        object_storage: ObjectStorage,
        expires_seconds: int,
    ) -> str:

        receipt = self.get_receipt_by_id(receipt_id=receipt_id, user_id=user_id)
        try:
            return object_storage.generate_download_url(
                object_key=receipt.image_object_key,
                expires_seconds=expires_seconds,
            )
        except ObjectStorageError as error:
            logger.exception(
                "Failed to generate image URL for receipt %s",
                receipt_id,
            )
            raise ReceiptImageUnavailableError() from error
