from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from backend.app.core.exceptions import ReceiptProcessingConflictError
from backend.app.db.session import SessionLocal
from backend.app.models import Receipt, ReceiptItem, User
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.schemas.request import ReceiptItemCreateRequest
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
    SaveProcessingOutcome,
)
from backend.app.workers import jobs

pytestmark = pytest.mark.integration


@pytest.fixture
def receipt_id() -> UUID:
    with SessionLocal.begin() as session:
        user = User(
            user_name="Processing",
            user_surname="Test",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test-password-hash",
        )
        receipt = Receipt(
            user=user,
            image_object_key="receipts/processing-test.jpg",
        )
        session.add(receipt)
        session.flush()
        return receipt.receipt_id


def make_result() -> ReceiptProcessingResult:
    return ReceiptProcessingResult(
        raw_ocr_text="Milk\nBread",
        items=(
            ReceiptItemCreateRequest(raw_name="Milk", quantity=1),
            ReceiptItemCreateRequest(raw_name="Bread", quantity=2),
        ),
    )


def item_ids(receipt_id: UUID) -> set[UUID]:
    with SessionLocal() as session:
        return set(
            session.scalars(
                select(ReceiptItem.receipt_item_id).where(
                    ReceiptItem.receipt_id == receipt_id
                )
            ).all()
        )


def test_repeated_job_keeps_same_items(
    receipt_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_pipeline(source):
        calls.append(source.receipt_id)
        return make_result()

    monkeypatch.setattr(jobs, "build_receipt_result", fake_pipeline)

    jobs.process_receipt(str(receipt_id))
    first_ids = item_ids(receipt_id)

    jobs.process_receipt(str(receipt_id))

    assert len(first_ids) == 2
    assert item_ids(receipt_id) == first_ids
    assert calls == [receipt_id]


def test_parallel_jobs_save_only_once(
    receipt_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = Barrier(2)

    def fake_pipeline(source):
        # Оба запуска должны пройти предварительную проверку
        # до того, как один из них сохранит результат.
        barrier.wait(timeout=10)
        return make_result()

    monkeypatch.setattr(jobs, "build_receipt_result", fake_pipeline)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(jobs.process_receipt, str(receipt_id)) for _ in range(2)
        ]
        for future in futures:
            future.result(timeout=20)

    assert len(item_ids(receipt_id)) == 2


def test_failed_save_rolls_back_items_and_marker(
    receipt_id: UUID,
) -> None:
    service = ReceiptProcessingService(SessionLocal)

    invalid_result = ReceiptProcessingResult(
        items=(
            ReceiptItemCreateRequest(raw_name="Valid", quantity=1),
            ReceiptItemCreateRequest(
                raw_name="Invalid category",
                quantity=1,
                category_id=uuid4(),  # Такой категории нет в БД.
            ),
        ),
    )

    with pytest.raises(IntegrityError):
        service.save_result(receipt_id, invalid_result)

    assert item_ids(receipt_id) == set()

    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt is not None
        assert receipt.processing_result_saved_at is None

    assert service.save_result(receipt_id, make_result()) == SaveProcessingOutcome.SAVED
    assert len(item_ids(receipt_id)) == 2


def test_retry_preserves_manual_edit(
    receipt_id: UUID,
) -> None:
    service = ReceiptProcessingService(SessionLocal)
    service.save_result(receipt_id, make_result())

    with SessionLocal.begin() as session:
        item = session.scalar(
            select(ReceiptItem).where(
                ReceiptItem.receipt_id == receipt_id,
                ReceiptItem.raw_name == "Milk",
            )
        )
        assert item is not None
        edited_item_id = item.receipt_item_id
        item.raw_name = "Manually corrected milk"

    outcome = service.save_result(receipt_id, make_result())

    assert outcome == SaveProcessingOutcome.ALREADY_SAVED

    with SessionLocal() as session:
        item = session.get(ReceiptItem, edited_item_id)
        assert item is not None
        assert item.raw_name == "Manually corrected milk"


def test_retry_does_not_restore_manually_deleted_items(
    receipt_id: UUID,
) -> None:
    service = ReceiptProcessingService(SessionLocal)
    service.save_result(receipt_id, make_result())

    with SessionLocal.begin() as session:
        session.execute(delete(ReceiptItem).where(ReceiptItem.receipt_id == receipt_id))

    outcome = service.save_result(receipt_id, make_result())

    assert outcome == SaveProcessingOutcome.ALREADY_SAVED
    assert item_ids(receipt_id) == set()


def test_existing_manual_items_are_preserved(
    receipt_id: UUID,
) -> None:
    with SessionLocal.begin() as session:
        session.add(
            ReceiptItem(
                receipt_id=receipt_id,
                raw_name="Manual item",
                quantity=1,
            )
        )

    original_ids = item_ids(receipt_id)
    service = ReceiptProcessingService(SessionLocal)

    with pytest.raises(ReceiptProcessingConflictError):
        service.save_result(receipt_id, make_result())

    assert item_ids(receipt_id) == original_ids

    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt is not None
        assert receipt.processing_result_saved_at is None


def test_empty_result_is_also_saved_once(
    receipt_id: UUID,
) -> None:
    service = ReceiptProcessingService(SessionLocal)
    empty_result = ReceiptProcessingResult(items=())

    assert service.save_result(receipt_id, empty_result) == SaveProcessingOutcome.SAVED
    assert (
        service.save_result(receipt_id, empty_result)
        == SaveProcessingOutcome.ALREADY_SAVED
    )


def test_deleted_receipt_is_skipped() -> None:
    service = ReceiptProcessingService(SessionLocal)

    assert (
        service.save_result(uuid4(), make_result())
        == SaveProcessingOutcome.RECEIPT_DELETED
    )
