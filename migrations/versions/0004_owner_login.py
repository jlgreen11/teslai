"""Owner login credentials on users.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE users
        ADD COLUMN password_hash   text,
        ADD COLUMN totp_secret_enc bytea,
        ADD COLUMN failed_logins   integer NOT NULL DEFAULT 0,
        ADD COLUMN locked_until    timestamptz;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE users DROP COLUMN password_hash, DROP COLUMN totp_secret_enc,
        DROP COLUMN failed_logins, DROP COLUMN locked_until;
    """)
