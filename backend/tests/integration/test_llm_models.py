from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import JSON, delete, select
from sqlalchemy.exc import IntegrityError

from backend.app.models import LlmReport, User, UserRule

pytestmark = pytest.mark.integration


def owner():
    return User(
        user_name="Report",
        user_surname="Owner",
        user_mail=f"{uuid4()}@example.com",
        user_password_hash="unused",
    )


def report(user=None, **values):
    fields = {
        "user": user or owner(),
        "period_start": date(2026, 9, 1),
        "period_end": date(2026, 9, 30),
        "timezone": "Asia/Omsk",
        "input_data": {"total_amount": "5000.00", "purchase_count": 10},
        "report_data": {"summary": "Расходы за месяц", "recommendations": []},
        "prompt_version": "monthly-v1",
        "schema_version": "monthly-v1",
        "provider_name": "local",
        "model_name": "test-model",
    }
    fields.update(values)
    if "user_id" in values:
        fields.pop("user")
    return LlmReport(**fields)


def test_report_preserves_snapshot_and_generation_metadata(db_session):
    value = report()
    db_session.add(value)
    db_session.commit()
    report_id = value.report_id
    db_session.expunge_all()
    saved = db_session.get(LlmReport, report_id)
    assert saved.input_data == {"total_amount": "5000.00", "purchase_count": 10}
    assert saved.report_data == {"summary": "Расходы за месяц", "recommendations": []}
    assert saved.period_start == date(2026, 9, 1)
    assert saved.period_end == date(2026, 9, 30)
    assert saved.timezone == "Asia/Omsk"
    assert saved.prompt_version == saved.schema_version == "monthly-v1"
    assert saved.provider_name == "local"
    assert saved.model_name == "test-model"
    assert saved.created_at.utcoffset() is not None
    assert saved.user.llm_reports == [saved]


def test_can_keep_multiple_reports_for_same_month(db_session):
    user = owner()
    first, second = report(user), report(user, prompt_version="monthly-v2")
    db_session.add_all([first, second])
    db_session.commit()
    assert first.report_id != second.report_id
    assert len(user.llm_reports) == 2


def test_rule_can_be_edited_and_disabled(db_session):
    value = UserRule(user=owner(), rule_text="Расходы на кафе — до 5 000 ₽ в месяц")
    db_session.add(value)
    db_session.commit()
    assert value.is_active is True
    assert value.created_at.utcoffset() is not None
    assert value.updated_at.utcoffset() is not None
    assert value.user.rules == [value]
    rule_id, created_at = value.rule_id, value.created_at
    value.rule_text = "Расходы на кафе — до 4 000 ₽ в месяц"
    value.is_active = False
    db_session.commit()
    db_session.expunge_all()
    saved = db_session.get(UserRule, rule_id)
    assert saved.is_active is False
    assert "4 000" in saved.rule_text
    assert saved.created_at == created_at
    assert saved.updated_at >= saved.created_at


def test_deleting_user_cascades_to_reports_and_rules(db_session):
    user = owner()
    value = report(user)
    rule = UserRule(user=user, rule_text="Покупать меньше сладостей")
    db_session.add_all([value, rule])
    db_session.commit()
    report_id, rule_id, user_id = value.report_id, rule.rule_id, user.user_id
    db_session.execute(delete(User).where(User.user_id == user_id))
    db_session.commit()
    db_session.expunge_all()
    assert db_session.get(LlmReport, report_id) is None
    assert db_session.get(UserRule, rule_id) is None


def test_reports_and_rules_belong_to_their_owner(db_session):
    first, second = owner(), owner()
    db_session.add_all(
        [
            report(first),
            report(second),
            UserRule(user=first, rule_text="Первое правило"),
            UserRule(user=second, rule_text="Второе правило"),
        ]
    )
    db_session.commit()
    assert (
        len(
            db_session.scalars(
                select(LlmReport).where(LlmReport.user_id == first.user_id)
            ).all()
        )
        == 1
    )
    assert [
        rule.rule_text
        for rule in db_session.scalars(
            select(UserRule).where(UserRule.user_id == first.user_id)
        )
    ] == ["Первое правило"]


@pytest.mark.parametrize("field", ["input_data", "report_data"])
@pytest.mark.parametrize("value", [None, JSON.NULL, [], "text", 42])
def test_report_requires_json_objects(db_session, field, value):
    db_session.add(report(**{field: value}))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_report_rejects_reversed_period(db_session):
    db_session.add(report(period_end=date(2026, 8, 31)))
    with pytest.raises(IntegrityError, match="llm_report_period_order"):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize(
    "field",
    ["timezone", "prompt_version", "schema_version", "provider_name", "model_name"],
)
def test_report_rejects_blank_metadata(db_session, field):
    db_session.add(report(**{field: "   "}))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_rule_rejects_empty_instruction(db_session):
    db_session.add(UserRule(user=owner(), rule_text="   "))
    with pytest.raises(IntegrityError, match="user_rule_text_nonempty"):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize("model", [LlmReport, UserRule])
def test_owner_must_exist(db_session, model):
    value = (
        report(user_id=uuid4())
        if model is LlmReport
        else UserRule(user_id=uuid4(), rule_text="Правило")
    )
    db_session.add(value)
    with pytest.raises(IntegrityError, match="foreign key"):
        db_session.flush()
    db_session.rollback()
