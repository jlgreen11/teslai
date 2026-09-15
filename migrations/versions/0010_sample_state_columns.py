"""Software version, lock state and charge limit on samples, for the status bar.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-15
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE samples ADD COLUMN version text, ADD COLUMN locked boolean, "
               "ADD COLUMN charge_limit double precision")


def downgrade() -> None:
    op.execute("ALTER TABLE samples DROP COLUMN version, DROP COLUMN locked, DROP COLUMN charge_limit")
