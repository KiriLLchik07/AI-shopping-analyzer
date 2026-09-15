from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from backend.app.api import receipts as receipts_api
from backend.app.api.dependencies.auth import get_current_user
from backend.app.api.dependencies.storage import get_object_storage
from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.core.exceptions import (
    ReceiptDeletionUnavailableError,
    ReceiptNotFoundError,
)
from backend.app.db.session import get_db
from backend.app.models.object_cleanup_task import ObjectCleanupTask
from backend.app.models.receipt import Category, Receipt, ReceiptItem
from backend.app.services.object_cleanup_service import cleanup_one
from backend.app.services.receipt_service import ReceiptService
from backend.app.storage.exception import ObjectStorageError


@pytest.fixture
def deletion_case(tmp_path):
    # Isolated SQLite database: transaction tests, not PostgreSQL lock tests.
    engine = create_engine("sqlite:///" + str(tmp_path / "deletion.db"))
    for model in (Category, Receipt, ReceiptItem, ObjectCleanupTask):
        model.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    receipt_id, user_id = uuid4(), uuid4()
    key = f"users/{user_id}/receipts/{receipt_id}/original.jpg"
    with factory.begin() as session:
        session.add(
            Receipt(
                receipt_id=receipt_id, receipt_user_id=user_id, image_object_key=key
            )
        )
    storage = Mock()

    def delete(key_arg):
        assert key_arg == key
        with factory() as session:
            assert session.get(Receipt, receipt_id) is None
            assert session.get(ObjectCleanupTask, receipt_id) is not None

    storage.delete.side_effect = delete
    yield SimpleNamespace(
        factory=factory,
        receipt_id=receipt_id,
        user_id=user_id,
        key=key,
        storage=storage,
    )
    engine.dispose()


def state(case):
    with case.factory() as session:
        return (
            session.get(Receipt, case.receipt_id) is not None,
            session.get(ObjectCleanupTask, case.receipt_id) is not None,
        )


def test_success_deletes_file_after_commit(deletion_case):
    c = deletion_case
    with c.factory() as session:
        ReceiptService(session).delete_receipt(
            c.receipt_id, c.user_id, c.storage, c.factory
        )
    c.storage.delete.assert_called_once_with(c.key)
    assert state(c) == (False, False)


def test_storage_failure_keeps_task_and_manual_retry_works(deletion_case):
    c = deletion_case
    c.storage.delete.side_effect = ObjectStorageError("offline")
    with c.factory() as session:
        ReceiptService(session).delete_receipt(
            c.receipt_id, c.user_id, c.storage, c.factory
        )
    assert state(c) == (False, True)
    c.storage.delete.side_effect = None
    assert cleanup_one(c.receipt_id, c.factory, c.storage) == "image_deleted"
    assert state(c) == (False, False)
    assert cleanup_one(c.receipt_id, c.factory, c.storage) == "already_processed"


@pytest.mark.parametrize("commit_succeeded", [False, True])
def test_commit_error_never_triggers_file_deletion(
    deletion_case, monkeypatch, commit_succeeded
):
    c = deletion_case
    with c.factory() as session:
        original_commit = session.commit

        def fail_commit():
            if commit_succeeded:
                original_commit()
            raise OperationalError("COMMIT", {}, RuntimeError("connection lost"))

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(ReceiptDeletionUnavailableError):
            ReceiptService(session).delete_receipt(
                c.receipt_id, c.user_id, c.storage, c.factory
            )
    c.storage.delete.assert_not_called()
    assert state(c) == ((False, True) if commit_succeeded else (True, False))


@pytest.mark.parametrize("missing", [False, True])
def test_other_owner_and_missing_receipt_do_not_touch_storage(deletion_case, missing):
    c = deletion_case
    receipt_id = uuid4() if missing else c.receipt_id
    with c.factory() as session, pytest.raises(ReceiptNotFoundError):
        ReceiptService(session).delete_receipt(
            receipt_id, uuid4(), c.storage, c.factory
        )
    assert state(c) == (True, False)
    c.storage.delete.assert_not_called()


def test_cleanup_commit_failure_leaves_retry_task(deletion_case):
    c = deletion_case

    # Fail the cleanup transaction after S3 succeeds, before context commits.
    from sqlalchemy import event

    cleanup_factory = sessionmaker(c.factory.kw["bind"], expire_on_commit=False)

    def fail_commit(session):
        raise OperationalError("COMMIT", {}, RuntimeError("offline"))

    event.listen(cleanup_factory, "before_commit", fail_commit)
    with c.factory() as session:
        ReceiptService(session).delete_receipt(
            c.receipt_id, c.user_id, c.storage, cleanup_factory
        )
    c.storage.delete.assert_called_once_with(c.key)
    assert state(c) == (False, True)


def test_delete_endpoint_returns_204_with_pending_cleanup(deletion_case, monkeypatch):
    c = deletion_case
    app = FastAPI()
    app.include_router(receipts_api.router)
    register_exception_handlers(app)

    def db():
        with c.factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        user_id=c.user_id
    )
    app.dependency_overrides[get_object_storage] = lambda: c.storage
    monkeypatch.setattr(receipts_api, "SessionLocal", c.factory)
    c.storage.delete.side_effect = ObjectStorageError("offline")
    with TestClient(app) as client:
        response = client.delete(f"/api/receipts/{c.receipt_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert state(c) == (False, True)
