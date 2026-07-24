"""Add precise service location coordinates.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_orders",
        sa.Column("service_location_name", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "service_orders",
        sa.Column("service_latitude", sa.Float(), nullable=True),
    )
    op.add_column(
        "service_orders",
        sa.Column("service_longitude", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("service_orders", "service_longitude")
    op.drop_column("service_orders", "service_latitude")
    op.drop_column("service_orders", "service_location_name")
