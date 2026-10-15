"""Initial ChangeWatch schema.

Revision ID: 0001_initial
Revises:
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "monitors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("sensitivity", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("include_selectors_json", sa.Text(), nullable=False),
        sa.Column("ignore_selectors_json", sa.Text(), nullable=False),
        sa.Column("normalization_rules_json", sa.Text(), nullable=False),
        sa.Column("notification_preferences_json", sa.Text(), nullable=False),
        sa.Column("keywords_json", sa.Text(), nullable=False),
        sa.Column("numeric_selector", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_changed_at", sa.DateTime(), nullable=True),
        sa.Column("next_check_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=False),
        sa.Column("last_error_code", sa.String(length=50), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_version_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitors_user_id", "monitors", ["user_id"], unique=False)
    op.create_index("ix_monitors_next_check_at", "monitors", ["next_check_at"], unique=False)

    op.create_table(
        "check_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("monitor_id", sa.String(length=36), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("changed", sa.Boolean(), nullable=False),
        sa.Column("failure_code", sa.String(length=50), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.Column("capture_metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_check_runs_monitor_id", "check_runs", ["monitor_id"], unique=False)
    op.create_index("ix_check_runs_created_at", "check_runs", ["created_at"], unique=False)

    op.create_table(
        "versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("monitor_id", sa.String(length=36), nullable=False),
        sa.Column("check_run_id", sa.String(length=36), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("screenshot_artifact_key", sa.String(length=255), nullable=True),
        sa.Column("raw_text_artifact_key", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("capture_metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["check_run_id"], ["check_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_versions_monitor_id", "versions", ["monitor_id"], unique=False)
    op.create_index("ix_versions_content_hash", "versions", ["content_hash"], unique=False)
    op.create_index("ix_versions_created_at", "versions", ["created_at"], unique=False)

    op.create_table(
        "notification_channels",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("channel_type", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(), nullable=True),
        sa.Column("last_delivery_status", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_channels_user_id", "notification_channels", ["user_id"], unique=False)

    op.create_table(
        "alert_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("monitor_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("dedupe_key", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("diff_snippet", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_events_monitor_id", "alert_events", ["monitor_id"], unique=False)
    op.create_index("ix_alert_events_dedupe_key", "alert_events", ["dedupe_key"], unique=True)

    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("alert_event_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("dedupe_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("provider_error_code", sa.String(length=50), nullable=True),
        sa.Column("provider_error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["alert_event_id"], ["alert_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["notification_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_deliveries_alert_event_id", "alert_deliveries", ["alert_event_id"], unique=False)
    op.create_index("ix_alert_deliveries_channel_id", "alert_deliveries", ["channel_id"], unique=False)
    op.create_index("ix_alert_deliveries_dedupe_key", "alert_deliveries", ["dedupe_key"], unique=True)

    op.create_table(
        "queue_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("queue", sa.String(length=50), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_queue_jobs_queue", "queue_jobs", ["queue"], unique=False)
    op.create_index("ix_queue_jobs_task_type", "queue_jobs", ["task_type"], unique=False)
    op.create_index("ix_queue_jobs_status", "queue_jobs", ["status"], unique=False)
    op.create_index("ix_queue_jobs_scheduled_at", "queue_jobs", ["scheduled_at"], unique=False)

    op.create_table(
        "numeric_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("monitor_id", sa.String(length=36), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("raw_text", sa.String(length=100), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_numeric_observations_monitor_id", "numeric_observations", ["monitor_id"], unique=False)
    op.create_index("ix_numeric_observations_recorded_at", "numeric_observations", ["recorded_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_numeric_observations_recorded_at", table_name="numeric_observations")
    op.drop_index("ix_numeric_observations_monitor_id", table_name="numeric_observations")
    op.drop_table("numeric_observations")

    op.drop_index("ix_queue_jobs_scheduled_at", table_name="queue_jobs")
    op.drop_index("ix_queue_jobs_status", table_name="queue_jobs")
    op.drop_index("ix_queue_jobs_task_type", table_name="queue_jobs")
    op.drop_index("ix_queue_jobs_queue", table_name="queue_jobs")
    op.drop_table("queue_jobs")

    op.drop_index("ix_alert_deliveries_dedupe_key", table_name="alert_deliveries")
    op.drop_index("ix_alert_deliveries_channel_id", table_name="alert_deliveries")
    op.drop_index("ix_alert_deliveries_alert_event_id", table_name="alert_deliveries")
    op.drop_table("alert_deliveries")

    op.drop_index("ix_alert_events_dedupe_key", table_name="alert_events")
    op.drop_index("ix_alert_events_monitor_id", table_name="alert_events")
    op.drop_table("alert_events")

    op.drop_index("ix_notification_channels_user_id", table_name="notification_channels")
    op.drop_table("notification_channels")

    op.drop_index("ix_versions_created_at", table_name="versions")
    op.drop_index("ix_versions_content_hash", table_name="versions")
    op.drop_index("ix_versions_monitor_id", table_name="versions")
    op.drop_table("versions")

    op.drop_index("ix_check_runs_created_at", table_name="check_runs")
    op.drop_index("ix_check_runs_monitor_id", table_name="check_runs")
    op.drop_table("check_runs")

    op.drop_index("ix_monitors_next_check_at", table_name="monitors")
    op.drop_index("ix_monitors_user_id", table_name="monitors")
    op.drop_table("monitors")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
