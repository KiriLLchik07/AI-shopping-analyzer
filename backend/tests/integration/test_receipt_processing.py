from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from backend.app.api.dependencies.auth import get_current_user
from backend.app.core.exceptions import ReceiptProcessingConflictError
from backend.app.core.receipt_processing_errors import get_safe_processing_error
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Receipt, ReceiptItem, User
from backend.app.models.enums import ReceiptStatus
from backend.app.repositories.receipt_processing_repository import (
    ReceiptProcessingRepository,
)
from backend.app.schemas.processing import (
    ReceiptProcessingInput,
    ReceiptProcessingResult,
)
from backend.app.schemas.request import ReceiptItemCreateRequest
from backend.app.services.receipt_pipeline import ReceiptPipeline
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
    SaveProcessingOutcome,
)
from backend.app.storage.exception import ObjectStorageError
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


class StubPipeline(ReceiptPipeline):
    def preprocess(self, source: ReceiptProcessingInput) -> bytes:
        return b"test-image"

    def recognize(self, image: bytes) -> str:
        return "Milk\nBread"

    def parse(self, raw_text: str) -> ReceiptProcessingResult:
        return make_result()


def receipt_status(receipt_id: UUID) -> ReceiptStatus:
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt is not None
        return receipt.status


def test_repeated_job_keeps_same_items(receipt_id, monkeypatch):
    calls = []

    class CountingPipeline(StubPipeline):
        def preprocess(self, source):
            calls.append(source.receipt_id)
            return super().preprocess(source)

    monkeypatch.setattr(jobs, "get_receipt_pipeline", CountingPipeline)
    jobs.process_receipt(str(receipt_id))
    first_ids = item_ids(receipt_id)
    jobs.process_receipt(str(receipt_id))
    assert len(first_ids) == 2
    assert item_ids(receipt_id) == first_ids
    assert calls == [receipt_id]
    assert receipt_status(receipt_id) == ReceiptStatus.NEED_REVIEW


def test_parallel_jobs_save_only_once(receipt_id, monkeypatch):
    entered = Event()
    release = Event()
    calls = []

    class PausingPipeline(StubPipeline):
        def preprocess(self, source):
            calls.append(source.receipt_id)
            entered.set()
            if not release.wait(timeout=10):
                raise TimeoutError("Test did not release pipeline")
            return super().preprocess(source)

    monkeypatch.setattr(jobs, "get_receipt_pipeline", PausingPipeline)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(jobs.process_receipt, str(receipt_id))
        try:
            assert entered.wait(timeout=5)
            second = executor.submit(jobs.process_receipt, str(receipt_id))
            second.result(timeout=5)
            assert calls == [receipt_id]
            assert receipt_status(receipt_id) == ReceiptStatus.PREPROCESSING
        finally:
            release.set()
        first.result(timeout=10)
    assert len(item_ids(receipt_id)) == 2
    assert receipt_status(receipt_id) == ReceiptStatus.NEED_REVIEW


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


def test_status_is_committed_before_each_step(receipt_id, monkeypatch):
    observed = []

    class ObservingPipeline(StubPipeline):
        def preprocess(self, source):
            assert isinstance(source.receipt_id, UUID)
            observed.append(receipt_status(receipt_id))
            return super().preprocess(source)

        def recognize(self, image):
            assert image == b"test-image"
            observed.append(receipt_status(receipt_id))
            return super().recognize(image)

        def parse(self, raw_text):
            assert raw_text == "Milk\nBread"
            observed.append(receipt_status(receipt_id))
            return ReceiptProcessingResult(items=make_result().items)

    monkeypatch.setattr(jobs, "get_receipt_pipeline", ObservingPipeline)
    jobs.process_receipt(str(receipt_id))
    assert observed == [
        ReceiptStatus.PREPROCESSING,
        ReceiptStatus.OCR_PROCESSING,
        ReceiptStatus.PARSING,
    ]
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.raw_ocr_text == "Milk\nBread"
        assert receipt.processing_result_saved_at is not None
        assert len(receipt.items) == 2


@pytest.mark.parametrize(
    ("step", "expected_status"),
    [
        ("preprocess", ReceiptStatus.PREPROCESSING),
        ("recognize", ReceiptStatus.OCR_PROCESSING),
        ("parse", ReceiptStatus.PARSING),
    ],
)
def test_pipeline_error_sets_failed(receipt_id, monkeypatch, step, expected_status):
    pipeline = StubPipeline()

    def fail(*args):
        assert receipt_status(receipt_id) == expected_status
        raise RuntimeError("Test pipeline failure")

    monkeypatch.setattr(pipeline, step, fail)
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline)
    with pytest.raises(RuntimeError, match="Test pipeline failure"):
        jobs.process_receipt(str(receipt_id))
    assert receipt_status(receipt_id) == ReceiptStatus.FAILED
    assert item_ids(receipt_id) == set()
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).processing_result_saved_at is None


def test_failed_receipt_can_be_started_again(receipt_id, monkeypatch):
    class FailingPipeline(StubPipeline):
        def recognize(self, image):
            raise RuntimeError("Temporary OCR failure")

    monkeypatch.setattr(jobs, "get_receipt_pipeline", FailingPipeline)
    with pytest.raises(RuntimeError, match="Temporary OCR failure"):
        jobs.process_receipt(str(receipt_id))
    assert receipt_status(receipt_id) == ReceiptStatus.FAILED
    monkeypatch.setattr(jobs, "get_receipt_pipeline", StubPipeline)
    jobs.process_receipt(str(receipt_id))
    assert receipt_status(receipt_id) == ReceiptStatus.NEED_REVIEW
    assert len(item_ids(receipt_id)) == 2


@pytest.mark.parametrize("status", [ReceiptStatus.NEED_REVIEW, ReceiptStatus.COMPLETED])
def test_finished_receipt_status_cannot_be_overwritten(receipt_id, status):
    service = ReceiptProcessingService(SessionLocal)
    service.save_result(receipt_id, make_result())
    with SessionLocal.begin() as session:
        session.get(Receipt, receipt_id).status = status
    assert service.start_processing(receipt_id) is None
    assert not service.advance_status(
        receipt_id, ReceiptStatus.PREPROCESSING, ReceiptStatus.OCR_PROCESSING
    )
    assert not service.mark_failed(receipt_id)
    assert receipt_status(receipt_id) == status


def test_invalid_and_stale_transitions_do_not_change_status(receipt_id):
    service = ReceiptProcessingService(SessionLocal)
    assert service.start_processing(receipt_id) is not None
    with pytest.raises(ValueError, match="Unsupported processing transition"):
        service.advance_status(
            receipt_id, ReceiptStatus.PREPROCESSING, ReceiptStatus.PARSING
        )
    assert not service.advance_status(
        receipt_id, ReceiptStatus.OCR_PROCESSING, ReceiptStatus.PARSING
    )
    assert receipt_status(receipt_id) == ReceiptStatus.PREPROCESSING


def test_deleted_during_preprocessing_stops_pipeline(receipt_id, monkeypatch):
    class DeletingPipeline(StubPipeline):
        def preprocess(self, source):
            with SessionLocal.begin() as session:
                session.execute(delete(Receipt).where(Receipt.receipt_id == receipt_id))
            return b"test-image"

        def recognize(self, image):
            pytest.fail("OCR must not run after receipt deletion")

    monkeypatch.setattr(jobs, "get_receipt_pipeline", DeletingPipeline)
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id) is None


def test_save_failure_sets_failed_without_partial_result(receipt_id, monkeypatch):
    class InvalidResultPipeline(StubPipeline):
        def parse(self, raw_text):
            return ReceiptProcessingResult(
                items=(
                    ReceiptItemCreateRequest(
                        raw_name="Invalid", quantity=1, category_id=uuid4()
                    ),
                )
            )

    monkeypatch.setattr(jobs, "get_receipt_pipeline", InvalidResultPipeline)
    with pytest.raises(IntegrityError):
        jobs.process_receipt(str(receipt_id))
    assert receipt_status(receipt_id) == ReceiptStatus.FAILED
    assert item_ids(receipt_id) == set()
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).processing_result_saved_at is None


def test_failure_reporting_preserves_original_exception(receipt_id, monkeypatch):
    class FailingPipeline(StubPipeline):
        def preprocess(self, source):
            raise RuntimeError("Original pipeline error")

    def fail_to_record(self, receipt_id, error=None):
        assert isinstance(error, RuntimeError)
        raise OSError("Database unavailable")

    monkeypatch.setattr(jobs, "get_receipt_pipeline", FailingPipeline)
    monkeypatch.setattr(ReceiptProcessingService, "mark_failed", fail_to_record)
    with pytest.raises(RuntimeError, match="Original pipeline error"):
        jobs.process_receipt(str(receipt_id))


def test_parallel_result_saves_are_idempotent(receipt_id):
    barrier = Barrier(2)

    def save():
        barrier.wait(timeout=5)
        return ReceiptProcessingService(SessionLocal).save_result(
            receipt_id, make_result()
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save) for _ in range(2)]
        outcomes = [future.result(timeout=10) for future in futures]
    assert set(outcomes) == {
        SaveProcessingOutcome.SAVED,
        SaveProcessingOutcome.ALREADY_SAVED,
    }
    assert len(item_ids(receipt_id)) == 2


@pytest.mark.parametrize(
    ("error_type", "expected_code"),
    [
        (RuntimeError, "processing_failed"),
        (ObjectStorageError, "image_storage_unavailable"),
        (ReceiptProcessingConflictError, "processing_conflict"),
    ],
)
def test_processing_error_does_not_store_exception_text(
    receipt_id, monkeypatch, error_type, expected_code
):
    original_error = error_type(
        "Traceback: password=secret-test-value; internal_host=database.private"
    )

    class FailingPipeline(StubPipeline):
        def preprocess(self, source):
            raise original_error

    monkeypatch.setattr(jobs, "get_receipt_pipeline", FailingPipeline)
    with pytest.raises(error_type) as caught:
        jobs.process_receipt(str(receipt_id))
    assert caught.value is original_error
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.FAILED
        assert receipt.processing_error_code == expected_code
        assert receipt.processing_error_message
        for forbidden in ("secret-test-value", "database.private", "Traceback"):
            assert forbidden not in receipt.processing_error_message
        assert receipt.processing_result_saved_at is None
        assert receipt.raw_ocr_text is None


def test_receipt_api_returns_only_safe_processing_error(
    receipt_id, client, monkeypatch
):
    service = ReceiptProcessingService(SessionLocal)
    assert service.start_processing(receipt_id) is not None
    error = RuntimeError("SECRET-DIAGNOSTIC Traceback internal SQL")
    assert service.mark_failed(receipt_id, error)
    with SessionLocal() as session:
        user = session.get(Receipt, receipt_id).user
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    expected = get_safe_processing_error(error)
    for url in (f"/api/receipts/{receipt_id}", "/api/receipts"):
        response = client.get(url)
        assert response.status_code == 200
        body = response.json()
        receipt_body = body["items"][0] if url == "/api/receipts" else body
        assert receipt_body["status"] == "failed"
        assert receipt_body["processing_error_code"] == expected.code
        assert receipt_body["processing_error_message"] == expected.message
        for forbidden in ("SECRET-DIAGNOSTIC", "Traceback", "internal SQL", "exc_info"):
            assert forbidden not in response.text
        assert "traceback" not in receipt_body


def test_new_processing_attempt_clears_previous_error(receipt_id):
    service = ReceiptProcessingService(SessionLocal)
    assert service.start_processing(receipt_id) is not None
    assert service.mark_failed(receipt_id, RuntimeError("First failure"))
    assert service.start_processing(receipt_id) is not None
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.PREPROCESSING
        assert receipt.processing_error_code is None
        assert receipt.processing_error_message is None


def test_successful_save_clears_previous_error(receipt_id):
    service = ReceiptProcessingService(SessionLocal)
    assert service.start_processing(receipt_id) is not None
    assert service.mark_failed(receipt_id, RuntimeError("Earlier failure"))
    assert service.save_result(receipt_id, make_result()) == SaveProcessingOutcome.SAVED
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.processing_error_code is None
        assert receipt.processing_error_message is None


def test_late_error_does_not_overwrite_saved_result(receipt_id):
    service = ReceiptProcessingService(SessionLocal)
    service.save_result(receipt_id, make_result())
    assert not service.mark_failed(receipt_id, RuntimeError("Late failure"))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.processing_error_code is None
        assert receipt.processing_error_message is None


def test_error_and_status_roll_back_together(receipt_id, monkeypatch):
    service = ReceiptProcessingService(SessionLocal)
    assert service.start_processing(receipt_id) is not None
    original = ReceiptProcessingRepository.set_processing_error

    def fail_after_flush(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("Failure before commit")

    monkeypatch.setattr(
        ReceiptProcessingRepository, "set_processing_error", fail_after_flush
    )
    with pytest.raises(RuntimeError, match="Failure before commit"):
        service.mark_failed(receipt_id, RuntimeError("OCR failure"))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.PREPROCESSING
        assert receipt.processing_error_code is None
        assert receipt.processing_error_message is None


def test_mark_failed_without_exception_uses_generic_message(receipt_id):
    service = ReceiptProcessingService(SessionLocal)
    assert service.start_processing(receipt_id) is not None
    assert service.mark_failed(receipt_id)
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.processing_error_code == "processing_failed"
        assert (
            receipt.processing_error_message == get_safe_processing_error(None).message
        )
