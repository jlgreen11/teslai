"""Tesla charging history records (Supercharger sessions and invoices).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-15
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE supercharger_sessions (
        id                   bigserial PRIMARY KEY,
        account_id           bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        vehicle_id           bigint NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
        tesla_session_id     text NOT NULL,
        site_name            text,
        start_ts             timestamptz NOT NULL,
        stop_ts              timestamptz,
        currency             text,
        total_due            numeric(12, 2),
        invoice_content_ids  text[] NOT NULL DEFAULT '{}',
        matched_session_id   bigint REFERENCES sessions(id) ON DELETE SET NULL,
        raw                  jsonb NOT NULL,
        fetched_at           timestamptz NOT NULL DEFAULT now(),
        UNIQUE (vehicle_id, tesla_session_id)
    );
    CREATE INDEX supercharger_sessions_start_idx ON supercharger_sessions (vehicle_id, start_ts);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS supercharger_sessions")
