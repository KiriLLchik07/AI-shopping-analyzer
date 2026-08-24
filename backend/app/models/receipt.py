from sqlalchemy import (
    Uuid, String, Integer, DateTime, Index,
    func, ForeignKey, Numeric, Text, Boolean,
    CheckConstraint, Float, Enum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID, uuid4
from datetime import datetime
from decimal import Decimal

from backend.app.db.base import Base
from backend.app.models.enums import ReceiptStatus

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.models.user import User

class Receipt(Base):
    __tablename__ = "receipts" 

    receipt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    receipt_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    store_name: Mapped[str | None] = mapped_column(String(100), index=True)
    store_inn: Mapped[str | None] = mapped_column(String(12))
    purchase_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    payment_type: Mapped[str | None] = mapped_column(String(30))
    fiscal_drive_number: Mapped[str | None] = mapped_column(String(16))
    fiscal_document_number: Mapped[str | None] = mapped_column(String)
    fiscal_sign: Mapped[str | None] = mapped_column(String)
    image_url: Mapped[str] = mapped_column(String(256), nullable=False)
    raw_ocr_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ReceiptStatus] = mapped_column(
        Enum(
            ReceiptStatus,
            name="receipt_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=ReceiptStatus.UPLOADED,
        server_default=ReceiptStatus.UPLOADED.value,
    )    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="receipts")
    items: Mapped[list["ReceiptItem"]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    __table_args__ = (
        Index("ix_receipts_user_datetime", "receipt_user_id", "purchase_datetime"),
        CheckConstraint("LENGTH(store_inn) <= 12", "store_inn_check"),
        CheckConstraint("total_amount > 0", "total_amount_check"),
    )

class ReceiptItem(Base):
    __tablename__ = "receipt_items" 

    receipt_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    receipt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("receipts.receipt_id", ondelete="CASCADE"), nullable=False, index=True)
    raw_name: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_name: Mapped[str | None] = mapped_column(String(256))
    category_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("categories.category_id", ondelete="SET NULL"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(100))
    weight: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"), server_default="0")
    confidence: Mapped[float | None] = mapped_column(Float)
    is_impulse_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    category: Mapped["Category | None"] = relationship(
        back_populates="receipt_items",
    )

    receipt: Mapped["Receipt"] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity > 0", "quantity_check"),
        CheckConstraint("weight > 0", "weight_check"),
        CheckConstraint("unit_price > 0", "unit_price_check"),
        CheckConstraint("total_price > 0", "total_price_check"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="receipt_item_confidence_range"),
    )

class Category(Base):
    __tablename__ = "categories"
    category_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    category_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "categories.category_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    parent: Mapped["Category | None"] = relationship(
        "Category",
        back_populates="children",
        remote_side=[category_id],
    )

    children: Mapped[list["Category"]] = relationship(
        "Category",
        back_populates="parent",
        passive_deletes=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    receipt_items: Mapped[list["ReceiptItem"]] = relationship(
        back_populates="category",
        passive_deletes=True
    )
