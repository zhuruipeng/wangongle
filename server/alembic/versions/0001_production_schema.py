"""Create the production database schema.

Revision ID: 0001
Revises:
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("openid", sa.String(length=128), nullable=False),
        sa.Column("unionid", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("technician_name", sa.String(length=100), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("openid"),
    )
    op.create_index("ix_users_openid", "users", ["openid"], unique=False)
    op.create_index("ix_users_unionid", "users", ["unionid"], unique=False)

    op.create_table(
        "refresh_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index("ix_refresh_sessions_token_digest", "refresh_sessions", ["token_digest"], unique=False)
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"], unique=False)

    op.create_table(
        "service_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("order_no", sa.String(length=64), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("customer_name", sa.String(length=100), nullable=False),
        sa.Column("customer_phone", sa.String(length=50), nullable=False),
        sa.Column("service_address", sa.String(length=500), nullable=False),
        sa.Column("service_type", sa.String(length=300), nullable=False),
        sa.Column("technician_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("report_json", sa.Text(), nullable=True),
        sa.Column("total_amount_cents", sa.Integer(), nullable=False),
        sa.Column("paid_amount_cents", sa.Integer(), nullable=False),
        sa.Column("audio_url", sa.String(length=500), nullable=True),
        sa.Column("audio_object_key", sa.String(length=512), nullable=True),
        sa.Column("transcription_status", sa.String(length=32), nullable=False),
        sa.Column("transcription_error", sa.Text(), nullable=True),
        sa.Column("asr_request_id", sa.String(length=100), nullable=True),
        sa.Column("audio_duration_ms", sa.Integer(), nullable=True),
        sa.Column("report_generation_status", sa.String(length=32), nullable=False),
        sa.Column("report_generation_error", sa.Text(), nullable=True),
        sa.Column("report_model", sa.String(length=200), nullable=True),
        sa.Column("report_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft','in_progress','waiting_acceptance','accepted','cancelled')", name="ck_service_order_status"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "order_no", name="uq_service_orders_owner_order_no"),
    )
    op.create_index("ix_service_orders_order_no", "service_orders", ["order_no"], unique=False)
    op.create_index("ix_service_orders_owner_user_id", "service_orders", ["owner_user_id"], unique=False)
    op.create_index("ix_service_orders_status", "service_orders", ["status"], unique=False)

    op.create_table(
        "service_order_photos",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("service_order_id", sa.String(length=36), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("file_url", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("phase IN ('before','after')", name="ck_service_order_photo_phase"),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_order_photos_service_order_id", "service_order_photos", ["service_order_id"], unique=False)

    op.create_table(
        "customer_acceptances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("service_order_id", sa.String(length=36), nullable=False),
        sa.Column("signature_object_key", sa.String(length=512), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["service_order_id"], ["service_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_order_id"),
    )
    op.create_index("ix_customer_acceptances_service_order_id", "customer_acceptances", ["service_order_id"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"], unique=False)
    op.create_index("ix_audit_events_outcome", "audit_events", ["outcome"], unique=False)
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"], unique=False)
    op.create_index("ix_audit_events_resource_id", "audit_events", ["resource_id"], unique=False)
    op.create_index("ix_audit_events_resource_type", "audit_events", ["resource_type"], unique=False)
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_events_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_resource_type", table_name="audit_events")
    op.drop_index("ix_audit_events_resource_id", table_name="audit_events")
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index("ix_audit_events_outcome", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_customer_acceptances_service_order_id", table_name="customer_acceptances")
    op.drop_table("customer_acceptances")
    op.drop_index("ix_service_order_photos_service_order_id", table_name="service_order_photos")
    op.drop_table("service_order_photos")
    op.drop_index("ix_service_orders_status", table_name="service_orders")
    op.drop_index("ix_service_orders_owner_user_id", table_name="service_orders")
    op.drop_index("ix_service_orders_order_no", table_name="service_orders")
    op.drop_table("service_orders")
    op.drop_index("ix_refresh_sessions_user_id", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_token_digest", table_name="refresh_sessions")
    op.drop_table("refresh_sessions")
    op.drop_index("ix_users_unionid", table_name="users")
    op.drop_index("ix_users_openid", table_name="users")
    op.drop_table("users")
