"""Alert rule firings, for de-duplication and resolution notices.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-15
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE rule_firings (
        id           bigserial PRIMARY KEY,
        account_id   bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        rule         text NOT NULL,
        key          text NOT NULL DEFAULT '',
        code         text NOT NULL,
        message      text NOT NULL,
        fired_at     timestamptz NOT NULL,
        resolved_at  timestamptz
    );
    CREATE UNIQUE INDEX rule_firings_open_uq ON rule_firings (account_id, rule, key)
        WHERE resolved_at IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rule_firings")
