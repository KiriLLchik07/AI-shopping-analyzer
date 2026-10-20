import sqlalchemy as sa
from alembic import op

revision = "d83021467fc5"
down_revision = "c72f10356eb4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_reports",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("input_data", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("report_data", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("provider_name", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("report_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "period_start <= period_end", name="llm_report_period_order"
        ),
        sa.CheckConstraint(
            "json_typeof(input_data) = 'object'", name="llm_report_input_object"
        ),
        sa.CheckConstraint(
            "json_typeof(report_data) = 'object'", name="llm_report_output_object"
        ),
        sa.CheckConstraint(
            "length(btrim(timezone)) > 0", name="llm_report_timezone_nonempty"
        ),
        sa.CheckConstraint(
            "length(btrim(prompt_version)) > 0",
            name="llm_report_prompt_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(schema_version)) > 0",
            name="llm_report_schema_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(provider_name)) > 0", name="llm_report_provider_nonempty"
        ),
        sa.CheckConstraint(
            "length(btrim(model_name)) > 0", name="llm_report_model_nonempty"
        ),
    )
    op.create_index(
        "ix_llm_reports_user_created",
        "llm_reports",
        ["user_id", "created_at", "report_id"],
    )
    op.create_table(
        "user_rules",
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rule_text", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("rule_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "length(btrim(rule_text)) > 0", name="user_rule_text_nonempty"
        ),
    )
    op.create_index("ix_user_rules_user_active", "user_rules", ["user_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_user_rules_user_active", table_name="user_rules")
    op.drop_table("user_rules")
    op.drop_index("ix_llm_reports_user_created", table_name="llm_reports")
    op.drop_table("llm_reports")
