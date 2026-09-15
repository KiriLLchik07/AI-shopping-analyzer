from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models.object_cleanup_task import ObjectCleanupTask
from backend.app.models.receipt import Receipt
from backend.app.storage.interface import ObjectStorage


def cleanup_one(
    receipt_id: UUID,
    session_factory: sessionmaker[Session],
    object_storage: ObjectStorage,
) -> str:

    with session_factory.begin() as session:
        task = session.get(ObjectCleanupTask, receipt_id, with_for_update=True)

        if task is None:
            return "already_processed"

        existing_receipt_id = session.scalar(
            select(Receipt.receipt_id)
            .where(Receipt.image_object_key == task.object_key)
            .limit(1)
        )

        if existing_receipt_id is not None:
            session.delete(task)
            return "image_preserved"

        object_storage.delete(task.object_key)
        session.delete(task)

        return "image_deleted"
