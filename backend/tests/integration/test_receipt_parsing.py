from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.api.dependencies.auth import get_current_user
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models import Receipt, User
from backend.app.models.enums import ReceiptStatus
from backend.app.parsing.receipt_parser import ReceiptParser
from backend.app.schemas.ocr import OcrFragment, OcrResult
from backend.app.schemas.processing import ReceiptProcessingResult
from backend.app.schemas.request import ReceiptItemCreateRequest
from backend.app.services.receipt_pipeline import UnconfiguredReceiptPipeline
from backend.app.services.receipt_processing_service import (
    ReceiptProcessingService,
    SaveProcessingOutcome,
)
from backend.app.workers import jobs

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
        assert receipt.parsing_report["warnings"] == ["Товарные строки не найдены."]
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
        assert len(receipt.parsing_report["warnings"]) == 4
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


@pytest.mark.parametrize(
    ("number", "count"), [(1, 8), (2, 6), (3, 1), (4, 1), (5, 3), (6, 1), (7, 3)]
)
def test_worker_saves_fixture_items_and_duplicate_job_is_idempotent(
    receipt_owner, client, monkeypatch, number, count
):
    receipt_id, user = receipt_owner
    root = Path(__file__).resolve().parents[1] / "fixtures/ocr/v1/texts"
    raw = (root / f"receipt_{number:03}.txt").read_text(encoding="utf-8-sig")
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline(text=raw))
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert len(receipt.items) == count
        original_ids = {item.receipt_item_id for item in receipt.items}
        assert all(
            item.raw_name and item.unit_price is not None for item in receipt.items
        )
        assert all(item.confidence is None for item in receipt.items)
        if number == 7:
            bananas = next(
                item for item in receipt.items if item.raw_name == "Бананы 1КГ"
            )
            assert bananas.quantity == Decimal("0.432")
            assert bananas.unit_price == Decimal("169.99")
            assert bananas.total_price == Decimal("73.44")
            assert bananas.unit == "кг"
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        assert {
            item.receipt_item_id for item in session.get(Receipt, receipt_id).items
        } == original_ids
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    response = client.get(f"/api/receipts/{receipt_id}")
    assert response.status_code == 200
    assert len(response.json()["items"]) == count
    if number == 7:
        bananas = next(
            item
            for item in response.json()["items"]
            if item["raw_name"] == "Бананы 1КГ"
        )
        assert Decimal(bananas["quantity"]) == Decimal("0.432")


def test_partial_item_is_persisted_without_fake_quantity(
    receipt_owner, client, monkeypatch
):
    receipt_id, user = receipt_owner
    raw = "Неясный товар =90.00\nИТОГ 90.00"
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline(text=raw))
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        item = receipt.items[0]
        assert item.quantity is item.unit_price is None
        assert item.total_price == Decimal("90.00")
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert any(
            "количество" in warning for warning in receipt.parsing_report["warnings"]
        )
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    body = client.get(f"/api/receipts/{receipt_id}").json()
    assert body["items"][0]["quantity"] is None


def test_free_item_prices_are_persisted_as_zero(receipt_owner, monkeypatch):
    receipt_id, _ = receipt_owner
    monkeypatch.setattr(
        jobs,
        "get_receipt_pipeline",
        lambda: pipeline(text="Подарок 0.00*1шт =0.00\nИТОГ 100.00"),
    )
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        item = session.get(Receipt, receipt_id).items[0]
        assert item.quantity == 1
        assert item.unit_price == item.total_price == 0


def test_fractional_quantity_can_be_created_and_corrected_in_api(
    receipt_owner, client, monkeypatch
):
    receipt_id, user = receipt_owner
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    response = client.post(
        f"/api/receipts/{receipt_id}/items",
        json={
            "raw_name": "Бананы",
            "quantity": "0.432",
            "unit": "кг",
            "unit_price": "169.99",
            "total_price": "73.44",
        },
    )
    assert response.status_code == 201
    item_id = response.json()["receipt_item_id"]
    assert Decimal(response.json()["quantity"]) == Decimal("0.432")
    response = client.patch(
        f"/api/receipts/{receipt_id}/items/{item_id}", json={"quantity": "0.501"}
    )
    assert response.status_code == 200
    assert Decimal(response.json()["quantity"]) == Decimal("0.501")
    response = client.patch(
        f"/api/receipts/{receipt_id}/items/{item_id}", json={"quantity": "0.0001"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("number", "count"), [(1, 8), (2, 6), (3, 0), (4, 1), (5, 0), (6, 1), (7, 3)]
)
def test_actual_ocr_fragments_can_be_processed_and_saved(
    receipt_owner, monkeypatch, number, count
):
    receipt_id, _ = receipt_owner
    root = Path(__file__).resolve().parents[1] / "fixtures/parsing/v1/ocr"
    text = (root / f"receipt_{number:03}.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline(text=text))
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.processing_error_code is None
        assert len(receipt.items) == count
        assert receipt.raw_ocr_text == text
        if count == 0:
            assert "Товарные строки не найдены." in receipt.parsing_report["warnings"]


@pytest.mark.parametrize(
    ("date_text", "price", "total"),
    [
        ("1.2.2026 09:05", "100,5 ₽", "201,00 руб."),
        ("2026/02/01 09:05:00", "100.50 р.", "201 RUB"),
        ("01/02/26 09:05 +03:00", "100,50 рублей", "201,00 ₽"),
    ],
)
def test_currency_and_date_formats_are_saved_and_exposed_in_api(
    receipt_owner, client, monkeypatch, date_text, price, total
):
    receipt_id, user = receipt_owner
    raw = f"МАГНИТ\nДата: {date_text}\nТовар {price}*2шт={total}\nИТОГ {total}"
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline(text=raw))
    jobs.process_receipt(str(receipt_id))
    expected_hour = 6 if "+03:00" in date_text else 3
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.purchase_datetime == datetime(
            2026, 2, 1, expected_hour, 5, tzinfo=UTC
        )
        assert receipt.total_amount == Decimal("201.00")
        assert receipt.raw_ocr_text == raw
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.items[0].raw_name == "Товар"
        assert receipt.items[0].quantity == 2
        assert receipt.items[0].unit_price == Decimal("100.50")
        assert receipt.items[0].total_price == Decimal("201.00")
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    response = client.get(f"/api/receipts/{receipt_id}")
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["items"][0]["unit_price"]) == Decimal("100.50")
    assert Decimal(body["total_amount"]) == Decimal("201.00")


@pytest.mark.parametrize(
    ("raw", "status", "items_sum", "difference"),
    [
        ("Товар 100.00*1шт=100.00\nИТОГ 100.00", "matched", "100.00", "0.00"),
        ("Товар 100.00*1шт=100.00\nИТОГ 100.05", "within_tolerance", "100.00", "-0.05"),
        ("Товар 100.00*1шт=100.00\nИТОГ 110.00", "mismatch", "100.00", "-10.00"),
        ("Товар 100.00*1шт=100.00\nИТОГ 90.00", "mismatch", "100.00", "10.00"),
        ("Товар 10.00*1шт=10000000000.00\nИТОГ 10.00", "incomplete", None, None),
        ("Товар 100.00*1шт=100.00", "missing_total", "100.00", None),
        ("ИТОГ 100.00", "no_items", None, None),
    ],
)
def test_totals_check_is_saved_and_available_in_api_without_failing_job(
    receipt_owner, client, monkeypatch, raw, status, items_sum, difference
):
    receipt_id, user = receipt_owner
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline(text=raw))
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.processing_error_code is None
        assert receipt.processing_result_saved_at is not None
        assert receipt.raw_ocr_text == raw
        check = receipt.parsing_report["totals_check"]
        assert check["status"] == status
        assert check["items_sum"] == items_sum
        assert check["difference"] == difference
        assert check["tolerance"] == "0.05"
        if status == "mismatch":
            assert any(
                "Сумма позиций" in warning
                for warning in receipt.parsing_report["warnings"]
            )
            assert receipt.items[0].total_price == Decimal("100.00")
        if status == "incomplete":
            assert receipt.items[0].total_price is None
            assert check["missing_amount_count"] == 1
        original_report = receipt.parsing_report
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).parsing_report == original_report
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    for url in (f"/api/receipts/{receipt_id}", "/api/receipts"):
        response = client.get(url)
        assert response.status_code == 200
        body = response.json()
        if url == "/api/receipts":
            body = body["items"][0]
        assert body["parsing_report"]["totals_check"] == check


def test_api_accepts_report_saved_before_totals_check_was_added(
    receipt_owner, client, monkeypatch
):
    receipt_id, user = receipt_owner
    with SessionLocal.begin() as session:
        receipt = session.get(Receipt, receipt_id)
        receipt.parsing_report = {"total_amount": "100.00", "warnings": []}
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    response = client.get(f"/api/receipts/{receipt_id}")
    assert response.status_code == 200
    assert response.json()["parsing_report"]["totals_check"] is None


@pytest.mark.parametrize(
    ("raw_unit", "unit"),
    [
        ("ШТ.", "шт"),
        ("килограмма", "кг"),
        ("ГР.", "г"),
        ("литра", "л"),
        ("миллилитров", "мл"),
        ("упаковки", "упак"),
        ("WT.", None),
        ("Kr", None),
    ],
)
def test_worker_persists_normalized_units_and_api_preserves_values(
    receipt_owner, client, monkeypatch, raw_unit, unit
):
    receipt_id, user = receipt_owner
    raw = f"Молоко 900 мл 100.00*2{raw_unit}=200.00\nИТОГ 200.00"
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline(text=raw))
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.raw_ocr_text == raw
        item = receipt.items[0]
        assert item.raw_name == "Молоко 900 мл"
        assert item.unit == unit
        assert item.quantity == 2
        assert item.unit_price == Decimal("100.00")
        assert item.total_price == Decimal("200.00")
        assert receipt.parsing_report["totals_check"]["status"] == "matched"
        if unit is None:
            assert any(
                raw_unit in warning and "единиц" in warning
                for warning in receipt.parsing_report["warnings"]
            )
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    response = client.get(f"/api/receipts/{receipt_id}")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["unit"] == unit
    assert Decimal(item["quantity"]) == 2
    assert Decimal(item["unit_price"]) == Decimal("100.00")


@pytest.mark.parametrize(
    ("raw_name", "normalized_name"),
    [
        ("МОЛОКО 3,2% 900мл", "молоко 3,2% 900мл"),
        ("RITTER\tSPORT  ШОКОЛАД", "ritter sport шоколад"),
        ("ЧАИ\u0306 ЗЕЛЕ\u0308НЫИ\u0306", "чай зелёный"),
        ("4514 ЛУЗИНСКАЯ КРЫНОЧКА 2.5% 900М", "4514 лузинская крыночка 2.5% 900м"),
        ("SNICKERS орех 81г:32/160", "snickers орех 81г:32/160"),
    ],
)
def test_worker_saves_raw_and_normalized_names_and_api_returns_both(
    receipt_owner, client, monkeypatch, raw_name, normalized_name
):
    receipt_id, user = receipt_owner
    raw = f"{raw_name} 100.00*1шт=100.00\nИТОГ 100.00"
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: pipeline(text=raw))
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert receipt.raw_ocr_text == raw
        assert len(receipt.items) == 1
        assert receipt.items[0].raw_name == raw_name
        assert receipt.items[0].normalized_name == normalized_name
        assert receipt.items[0].unit_price == Decimal("100.00")
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    response = client.get(f"/api/receipts/{receipt_id}")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["raw_name"] == raw_name
    assert item["normalized_name"] == normalized_name


def test_manual_normalized_name_survives_duplicate_job_and_requires_replacement_consent(
    receipt_owner, client, monkeypatch
):
    from backend.app.api import receipts as receipts_api

    receipt_id, user = receipt_owner
    monkeypatch.setattr(
        jobs,
        "get_receipt_pipeline",
        lambda: pipeline(text="МОЛОКО 100.00*1шт=100.00\nИТОГ 100.00"),
    )
    jobs.process_receipt(str(receipt_id))
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    body = client.get(f"/api/receipts/{receipt_id}").json()
    item_id = body["items"][0]["receipt_item_id"]
    response = client.patch(
        f"/api/receipts/{receipt_id}/items/{item_id}",
        json={"normalized_name": "Молоко фермерское"},
    )
    assert response.status_code == 200
    assert response.json()["raw_name"] == "МОЛОКО"
    jobs.process_receipt(str(receipt_id))
    monkeypatch.setattr(
        receipts_api, "enqueue_receipt", lambda *args, **kwargs: "names-test-job"
    )
    assert client.post(f"/api/receipts/{receipt_id}/reprocess").status_code == 409
    item = client.get(f"/api/receipts/{receipt_id}").json()["items"][0]
    assert item["normalized_name"] == "Молоко фермерское"
    assert item["raw_name"] == "МОЛОКО"
    response = client.post(
        f"/api/receipts/{receipt_id}/reprocess", json={"replace_items": True}
    )
    assert response.status_code == 202
    jobs.process_receipt(str(receipt_id), response.json()["processing_version"])
    items = client.get(f"/api/receipts/{receipt_id}").json()["items"]
    assert len(items) == 1
    assert items[0]["raw_name"] == "МОЛОКО"
    assert items[0]["normalized_name"] == "молоко"


def confidence_pipeline(parts):
    result = OcrResult(
        raw_text="\n".join(text for text, _ in parts),
        confidence=0.99,
        fragments=tuple(
            OcrFragment(text=text, confidence=score) for text, score in parts
        ),
    )
    configured = pipeline(text=result.raw_text)
    configured.ocr_provider.recognize.return_value = result
    return configured


def test_worker_stores_distinct_item_confidences_and_exposes_them_in_api(
    receipt_owner, client, monkeypatch
):
    receipt_id, user = receipt_owner
    configured = confidence_pipeline(
        [
            ("Молоко", 0.96),
            ("100.00*1шт=100.00", 0.91),
            ("Молоко", 0.67),
            ("100.00*1шт=100.00", 0.88),
            ("ИТОГ 200.00", 0.05),
        ]
    )
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: configured)
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert receipt.ocr_confidence == 0.99
        assert receipt.status == ReceiptStatus.NEED_REVIEW
        assert sorted(item.confidence for item in receipt.items) == [0.67, 0.91]
        assert receipt.parsing_report["item_confidence_method"] == "min_ocr_fragment_v1"
        original_ids = {item.receipt_item_id for item in receipt.items}
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert {item.receipt_item_id for item in receipt.items} == original_ids
        assert sorted(item.confidence for item in receipt.items) == [0.67, 0.91]
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    response = client.get(f"/api/receipts/{receipt_id}")
    assert response.status_code == 200
    assert sorted(item["confidence"] for item in response.json()["items"]) == [
        0.67,
        0.91,
    ]


@pytest.mark.parametrize("score", [0.0, 1.0])
def test_worker_preserves_item_confidence_boundaries(receipt_owner, monkeypatch, score):
    receipt_id, _ = receipt_owner
    configured = confidence_pipeline(
        [("Товар 100.00*1шт=100.00", score), ("ИТОГ 100.00", 0.6)]
    )
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: configured)
    jobs.process_receipt(str(receipt_id))
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).items[0].confidence == score


def test_reprocessing_replaces_confidence_only_after_consent(
    receipt_owner, monkeypatch
):
    from backend.app.core.exceptions import ConflictError

    receipt_id, user = receipt_owner
    configured = confidence_pipeline(
        [("Товар 100.00*1шт=100.00", 0.9), ("ИТОГ 100.00", 0.99)]
    )
    monkeypatch.setattr(jobs, "get_receipt_pipeline", lambda: configured)
    jobs.process_receipt(str(receipt_id))
    service = ReceiptProcessingService(SessionLocal)
    with pytest.raises(ConflictError):
        service.prepare_process(receipt_id, user.user_id, replace_items=False)
    ticket = service.prepare_process(receipt_id, user.user_id, replace_items=True)
    configured = confidence_pipeline(
        [("Товар 100.00*1шт=100.00", 0.72), ("ИТОГ 100.00", 0.99)]
    )
    jobs.process_receipt(str(receipt_id), ticket.processing_version)
    with SessionLocal() as session:
        receipt = session.get(Receipt, receipt_id)
        assert len(receipt.items) == 1
        assert receipt.items[0].confidence == 0.72
    jobs.process_receipt(str(receipt_id), ticket.processing_version - 1)
    with SessionLocal() as session:
        assert session.get(Receipt, receipt_id).items[0].confidence == 0.72
