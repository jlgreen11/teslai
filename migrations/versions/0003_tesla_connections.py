"""Tesla OAuth connection per account, tokens encrypted with a local Fernet key.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE tesla_connections (
        account_id         bigint PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
        client_id          text NOT NULL,
        region             text NOT NULL,
        scopes             text[] NOT NULL DEFAULT '{}',
        access_token_enc   bytea NOT NULL,
        refresh_token_enc  bytea NOT NULL,
        access_expires_at  timestamptz NOT NULL,
        refresh_count      integer NOT NULL DEFAULT 0,
        updated_at         timestamptz NOT NULL DEFAULT now()
    );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tesla_connections")
