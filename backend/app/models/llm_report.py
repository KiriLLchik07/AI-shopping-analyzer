from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.user import User


class LlmReport(Base):
    __tablename__ = "llm_reports"

    report_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    input_data: Mapped[dict] = mapped_column(JSON(none_as_null=True), nullable=False)
    report_data: Mapped[dict] = mapped_column(JSON(none_as_null=True), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="llm_reports")

    __table_args__ = (
        Index("ix_llm_reports_user_created", "user_id", "created_at", "report_id"),
        CheckConstraint("period_start <= period_end", name="llm_report_period_order"),
        CheckConstraint(
            "json_typeof(input_data) = 'object'", name="llm_report_input_object"
        ),
        CheckConstraint(
            "json_typeof(report_data) = 'object'", name="llm_report_output_object"
        ),
        CheckConstraint(
            "length(btrim(timezone)) > 0", name="llm_report_timezone_nonempty"
        ),
        CheckConstraint(
            "length(btrim(prompt_version)) > 0",
            name="llm_report_prompt_version_nonempty",
        ),
        CheckConstraint(
            "length(btrim(schema_version)) > 0",
            name="llm_report_schema_version_nonempty",
        ),
        CheckConstraint(
            "length(btrim(provider_name)) > 0", name="llm_report_provider_nonempty"
        ),
        CheckConstraint(
            "length(btrim(model_name)) > 0", name="llm_report_model_nonempty"
        ),
    )
