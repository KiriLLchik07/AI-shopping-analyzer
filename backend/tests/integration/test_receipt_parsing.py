from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

import pytest
from backend.app.api.dependencies.auth import get_current_user
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Receipt, User
from backend.app.models.enums import ReceiptStatus
from backend.app.parsing.receipt_parser import ReceiptParser
from backend.app.schemas.ocr import OcrResult
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.schemas.request import ReceiptItemCreateRequest
from backend.app.services.receipt_pipeline import UnconfiguredReceiptPipeline
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
    SaveProcessingOutcome,
)
from backend.app.workers import jobs
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration
TEXT = 'ООО "Тестовый магазин"\n20.10.2026 17:46\nИТОГ 3 240,00 ₽'


@pytest.fixture
def receipt_owner():
    with SessionLocal.begin() as session:
        user = User(
            user_name="Parser",
            user_surname="Test",
            user_mail=f"{uuid4()}@example.com",
            user_password_hash="test-hash",
        )
        receipt = Receipt(user=user, image_object_key="parsing/test.jpg")
        session.add(receipt)
        session.flush()
        return receipt.receipt_id, user


def pipeline(timezone="Asia/Omsk", text=TEXT):
    storage, normalizer, provider = Mock(), Mock(), Mock()
    storage.download.return_value = b"source-image"
    normalizer.normalize_with_report.return_value = Mock(
        image=b"normalized-image", report=None
    )
    provider.recognize.return_value = OcrResult(raw_text=text, confidence=0.9)
    return UnconfiguredReceiptPipeline(
        storage, normalizer, provider, ReceiptParser(timezone)
    )


def test_worker_parses_metadata_persists_report_and_exposes_api(
    receipt_owner, client, monkeypatch
):
    receipt_id, user = receipt_owner
    monkeypatch.setattr(jobs, "get_receipt_pipeline", pipeline)
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.store_name == 'ООО "Тестовый магазин"'
        assert receipt.total_amount == Decimal("3240.00")
        assert receipt.purchase_datetime == datetime(2026, 10, 20, 11, 46, tzinfo=UTC)
        assert receipt.raw_ocr_text == TEXT
        assert receipt.ocr_confidence == 0.9
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.items == []
        assert receipt.parsing_report["warnings"] == []
        assert "raw_ocr_text" not in receipt.parsing_report
        assert "items" not in receipt.parsing_report
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    for url in (f"/api/receipts/{receipt_id}", "/api/receipts"):
        response = client.get(url)
        assert response.status_code == 200
        body = response.json()
        receipt = body["items"][0] if url == "/api/receipts" else body
        assert receipt["store_name"] == 'ООО "Тестовый магазин"'
        assert Decimal(receipt["total_amount"]) == Decimal("3240.00")
        assert (
            receipt["parsing_report"]["purchase_datetime"]
            == "2026-10-20T17:46:00+06:00"
        )


def test_unknown_timezone_preserves_local_time_in_report_without_db_assumption(
    receipt_owner, client, monkeypatch
):
    receipt_id, user = receipt_owner
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline(timezone=None))
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.purchase_datetime is None
        assert receipt.parsing_report["purchase_datetime"] == "2026-10-20T17:46:00"
        assert any(
            "PARSING_TIMEZONE" in warning
            for warning in receipt.parsing_report["warnings"]
        )
        assert receipt.status == ReceiptStatus.NEED_REVIEW
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    response = client.get(f"/api/receipts/{receipt_id}")
    assert response.status_code == 200
    assert (
        response.json()["parsing_report"]["purchase_datetime"] == "2026-10-20T17:46:00"
    )


def test_missing_metadata_goes_to_review_instead_of_failed(receipt_owner, monkeypatch):
    receipt_id, _ = receipt_owner
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline(text="Молоко"))
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert (
            receipt.store_name
            is receipt.purchase_datetime
            is receipt.total_amount
            is None
        )
        assert len(receipt.parsing_report["warnings"]) == 3
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.processing_error_code is None


def test_parser_does_not_overwrite_existing_metadata(receipt_owner, monkeypatch):
    receipt_id, _ = receipt_owner
    corrected_datetime = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    with SessionLocal.begin() as session:
        receipt = session.get(Receipt, receipt_id)
        receipt.store_name = "Исправленный магазин"
        receipt.total_amount = Decimal("123.45")
        receipt.purchase_datetime = corrected_datetime
    monkeypatch.setattr(jobs, "get_receipt_pipeline", pipeline)
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.store_name == "Исправленный магазин"
        assert receipt.total_amount == Decimal("123.45")
        assert receipt.purchase_datetime == corrected_datetime
        assert receipt.parsing_report["total_amount"] == "3240.00"


def test_stale_and_duplicate_results_cannot_replace_metadata(receipt_owner):
    receipt_id, _ = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    result = pipeline().parse(TEXT)
    assert (
        service.save_result(receipt_id, result, processing_version=2)
        == SaveProcessingOutcome.STALE_JOB
    )
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.store_name is receipt.parsing_report is None
    assert service.save_result(receipt_id, result) == SaveProcessingOutcome.SAVED
    changed = pipeline().parse("МАГНИТ\nИТОГ 100.00")
    assert (
        service.save_result(receipt_id, changed) == SaveProcessingOutcome.ALREADY_SAVED
    )
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.total_amount == Decimal("3240.00")
        assert receipt.parsing_report["total_amount"] == "3240.00"


def test_metadata_report_items_and_saved_marker_roll_back_together(receipt_owner):
    receipt_id, _ = receipt_owner
    result = ReceiptProcessingResult(
        raw_ocr_text=TEXT,
        parsed_receipt=ReceiptParser("Asia/Omsk").parse(TEXT),
        items=(
            ReceiptItemCreateRequest(raw_name="Товар", quantity=1, category_id=uuid4()),
        ),
    )
    with pytest.raises(IntegrityError):
        ReceiptProcessingService(SessionLocal).save_result(receipt_id, result)
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert (
            receipt.store_name
            is receipt.total_amount
            is receipt.purchase_datetime
            is None
        )
        assert receipt.parsing_report is receipt.processing_result_saved_at is None
        assert receipt.items == []


def test_reprocess_clears_report_and_ignores_old_job(receipt_owner):
    receipt_id, user = receipt_owner
    service = ReceiptProcessingService(SessionLocal)
    service.save_result(receipt_id, pipeline().parse(TEXT))
    ticket = service.prepare_process(receipt_id, user.user_id, replace_items=False)
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).parsing_report is None
    assert (
        service.save_result(receipt_id, pipeline().parse(TEXT))
        == SaveProcessingOutcome.STALE_JOB
    )
    assert service.start_processing(receipt_id, ticket.processing_version) is not None
    assert (
        service.save_result(
            receipt_id, pipeline().parse(TEXT), ticket.processing_version
        )
        == SaveProcessingOutcome.SAVED
    )
