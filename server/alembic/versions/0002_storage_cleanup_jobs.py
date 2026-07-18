"""Add durable storage cleanup jobs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_cleanup_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index(
        "ix_storage_cleanup_jobs_object_key",
        "storage_cleanup_jobs",
        ["object_key"],
        unique=False,
    )
    op.create_index(
        "ix_storage_cleanup_jobs_source",
        "storage_cleanup_jobs",
        ["source"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_storage_cleanup_jobs_source", table_name="storage_cleanup_jobs")
    op.drop_index("ix_storage_cleanup_jobs_object_key", table_name="storage_cleanup_jobs")
    op.drop_table("storage_cleanup_jobs")
