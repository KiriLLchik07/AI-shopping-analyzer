from sqlalchemy import Uuid, String, Integer, CheckConstraint, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID, uuid4
from datetime import datetime

from backend.app.db.base import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.models.receipt import Receipt

class User(Base):
    __tablename__ = "users" 

    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_name: Mapped[str] = mapped_column(String(50), nullable=False)
    user_surname: Mapped[str] = mapped_column(String(100), nullable=False)
    user_mail: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    user_password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    user_age: Mapped[int | None] = mapped_column(Integer)
    user_country: Mapped[str | None] = mapped_column(String(30))
    user_city: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(r"user_mail ~ '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'", name="user_mail_validation"),
        CheckConstraint("user_age >= 14", name="user_age_validation"),
    )

    receipts: Mapped[list["Receipt"]] = relationship("Receipt", back_populates="user")
