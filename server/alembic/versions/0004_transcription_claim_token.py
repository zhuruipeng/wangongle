"""Add transcription claim fencing token.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_orders",
        sa.Column("transcription_claim_token", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_orders", "transcription_claim_token")
