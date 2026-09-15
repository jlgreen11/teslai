"""Derived sessions: drives, charges, idles, sleeps and unreachable periods.

Sessions are always re-derivable from raw data. builder_version records which
builder produced a row; a rebuild deletes and re-inserts a vehicle's sessions for
a time window in one transaction.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-15
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE sessions (
        id               bigserial PRIMARY KEY,
        account_id       bigint NOT NULL,
        vehicle_id       bigint NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
        kind             text NOT NULL
                         CHECK (kind IN ('drive', 'charge', 'idle', 'sleep', 'unreachable')),
        start_ts         timestamptz NOT NULL,
        end_ts           timestamptz,
        start_odometer   double precision,
        end_odometer     double precision,
        start_battery    double precision,
        end_battery      double precision,
        energy_added_kwh double precision,
        charger          text CHECK (charger IN ('ac', 'dc')),
        flags            text[] NOT NULL DEFAULT '{}',
        source           text NOT NULL CHECK (source IN ('telemetry', 'teslafi_import', 'mixed')),
        builder_version  integer NOT NULL,
        created_at       timestamptz NOT NULL DEFAULT now(),
        CHECK (end_ts IS NULL OR end_ts >= start_ts)
    );
    CREATE INDEX sessions_vehicle_start_idx ON sessions (account_id, vehicle_id, start_ts);
    CREATE UNIQUE INDEX sessions_vehicle_kind_start_uq ON sessions (vehicle_id, kind, start_ts);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sessions")
