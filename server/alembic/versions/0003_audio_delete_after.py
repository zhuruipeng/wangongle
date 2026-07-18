"""Add audio deletion deadline to service orders.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_orders",
        sa.Column("audio_delete_after", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_orders", "audio_delete_after")
