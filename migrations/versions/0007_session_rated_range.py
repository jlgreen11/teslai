"""Rated range at the end of each session, for the battery report.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-15
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sessions ADD COLUMN end_rated_range double precision")


def downgrade() -> None:
    op.execute("ALTER TABLE sessions DROP COLUMN end_rated_range")
