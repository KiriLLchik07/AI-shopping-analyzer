from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, cast, distinct, func, literal, select
from sqlalchemy.dialects.postgresql import INTERVAL
from sqlalchemy.orm import Session

from backend.app.models import Category, Receipt, ReceiptItem
from backend.app.models.enums import ReceiptStatus
from backend.app.schemas.analytics import (
    ProductSort,
    ResolvedAnalyticsPeriod,
    TrendGroup,
)

ZERO = Decimal("0.00")


class AnalyticsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _filters(user_id: UUID, period: ResolvedAnalyticsPeriod):
        return (
            Receipt.receipt_user_id == user_id,
            Receipt.status == ReceiptStatus.COMPLETED,
            Receipt.confirmed_at.is_not(None),
            Receipt.purchase_datetime >= period.start_at,
            Receipt.purchase_datetime < period.end_at,
        )

    @staticmethod
    def _clean_name(column):
        return func.nullif(
            func.btrim(func.regexp_replace(column, r"\s+", " ", "g")), ""
        )

    def summary(self, user_id: UUID, period: ResolvedAnalyticsPeriod):
        query = select(
            func.coalesce(func.sum(Receipt.total_amount), ZERO).label("total_amount"),
            func.count(Receipt.receipt_id).label("purchase_count"),
        ).where(*self._filters(user_id, period))
        return self.session.execute(query).mappings().one()

    def categories(self, user_id: UUID, period: ResolvedAnalyticsPeriod):
        amount = func.coalesce(func.sum(ReceiptItem.total_price), ZERO).label(
            "total_amount"
        )
        name = func.coalesce(Category.category_name, "Без категории")
        query = (
            select(
                ReceiptItem.category_id,
                name.label("category_name"),
                amount,
                func.count(distinct(ReceiptItem.receipt_id)).label("purchase_count"),
            )
            .select_from(ReceiptItem)
            .join(Receipt, Receipt.receipt_id == ReceiptItem.receipt_id)
            .outerjoin(Category, Category.category_id == ReceiptItem.category_id)
            .where(*self._filters(user_id, period))
            .group_by(ReceiptItem.category_id, name)
            .order_by(amount.desc(), name, ReceiptItem.category_id.asc().nulls_last())
        )
        return self.session.execute(query).mappings().all()

    def products(
        self,
        user_id: UUID,
        period: ResolvedAnalyticsPeriod,
        limit: int,
        sort_by: ProductSort,
    ):
        name = func.lower(
            func.coalesce(
                self._clean_name(ReceiptItem.normalized_name),
                self._clean_name(ReceiptItem.raw_name),
                "Без названия",
            )
        )
        amount = func.coalesce(func.sum(ReceiptItem.total_price), ZERO).label(
            "total_amount"
        )
        frequency = func.count(distinct(ReceiptItem.receipt_id)).label("purchase_count")
        order = (
            (amount.desc(), frequency.desc())
            if sort_by == ProductSort.AMOUNT
            else (frequency.desc(), amount.desc())
        )
        query = (
            select(name.label("product_name"), amount, frequency)
            .select_from(ReceiptItem)
            .join(Receipt, Receipt.receipt_id == ReceiptItem.receipt_id)
            .where(*self._filters(user_id, period))
            .group_by(name)
            .order_by(*order, name)
            .limit(limit)
        )
        return self.session.execute(query).mappings().all()

    def stores(self, user_id: UUID, period: ResolvedAnalyticsPeriod, limit: int):
        name = func.lower(self._clean_name(Receipt.store_name))
        amount = func.coalesce(func.sum(Receipt.total_amount), ZERO).label(
            "total_amount"
        )
        frequency = func.count(Receipt.receipt_id).label("purchase_count")
        query = (
            select(name.label("store_name"), amount, frequency)
            .where(*self._filters(user_id, period))
            .group_by(name)
            .order_by(amount.desc(), frequency.desc(), name.asc().nulls_last())
            .limit(limit)
        )
        return self.session.execute(query).mappings().all()

    def trends(
        self, user_id: UUID, period: ResolvedAnalyticsPeriod, group_by: TrendGroup
    ):
        local_purchase = func.timezone(period.timezone, Receipt.purchase_datetime)
        bucket = cast(func.date_trunc(group_by.value, local_purchase), Date)
        totals = (
            select(
                bucket.label("bucket_start"),
                func.sum(Receipt.total_amount).label("total_amount"),
                func.count(Receipt.receipt_id).label("purchase_count"),
            )
            .where(*self._filters(user_id, period))
            .group_by(bucket)
            .subquery("totals")
        )
        first = func.date_trunc(
            group_by.value, cast(literal(period.date_from), DateTime())
        )
        last = func.date_trunc(
            group_by.value, cast(literal(period.date_to), DateTime())
        )
        step = cast(
            literal(
                {
                    TrendGroup.DAY: "1 day",
                    TrendGroup.WEEK: "1 week",
                    TrendGroup.MONTH: "1 month",
                }[group_by]
            ),
            INTERVAL(),
        )
        buckets = (
            func.generate_series(first, last, step)
            .table_valued("bucket")
            .render_derived(name="buckets")
        )
        day = cast(buckets.c.bucket, Date)
        query = (
            select(
                day.label("bucket_start"),
                func.coalesce(totals.c.total_amount, ZERO).label("total_amount"),
                func.coalesce(totals.c.purchase_count, 0).label("purchase_count"),
            )
            .select_from(buckets.outerjoin(totals, day == totals.c.bucket_start))
            .order_by(day)
        )
        return self.session.execute(query).mappings().all()
