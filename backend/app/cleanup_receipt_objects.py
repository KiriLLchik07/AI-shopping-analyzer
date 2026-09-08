import argparse
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.dependencies.storage import get_object_storage
from backend.app.db.session import SessionLocal
from backend.app.models.object_cleanup_task import ObjectCleanupTask
from backend.app.models.receipt import Receipt
from backend.app.storage.exception import ObjectStorageError
from backend.app.storage.interface import ObjectStorage

logger = logging.getLogger(__name__)


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean up objects from failed receipt uploads"
    )

    parser.add_argument(
        "--uploads-stopped",
        action="store_true",
        help="Confirm that all upload processes have been stopped",
    )

    args = parser.parse_args()

    if not args.uploads_stopped:
        parser.error(
            "Finish active uploads and stop all backend processes, "
            "then pass --uploads-stopped"
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        object_storage = get_object_storage()

        with SessionLocal() as session:
            receipt_ids = list(
                session.scalars(
                    select(ObjectCleanupTask.receipt_id).order_by(
                        ObjectCleanupTask.created_at, ObjectCleanupTask.receipt_id
                    )
                ).all()
            )

    except Exception:
        logger.exception("Could not initialize cleanup")
        return 1

    failures = 0
    for receipt_id in receipt_ids:
        try:
            result = cleanup_one(
                receipt_id=receipt_id,
                session_factory=SessionLocal,
                object_storage=object_storage,
            )
        except (SQLAlchemyError, ObjectStorageError):
            failures += 1
            logger.exception(
                "Cleanup failed for receipt %s; rerun the command",
                receipt_id,
            )
        else:
            logger.info(
                "Receipt %s: %s",
                receipt_id,
                result,
            )

    logger.info(
        "Processed %s tasks; failures: %s",
        len(receipt_ids),
        failures,
    )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
