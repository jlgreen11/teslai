"""Foundations schema: accounts, vehicles, telemetry events, connectivity, snapshots, usage.

Every table carries account_id. Row-level security policies are deferred to the
sharing gate; until then teslai.db.repo is the only query path and always filters
by account_id.

telemetry_events is range-partitioned by month on the vehicle timestamp. A default
partition catches rows for months that have no partition yet, so inserts never fail;
teslai.db.repo.ensure_month_partition() creates real partitions ahead of time.

Revision ID: 0001
Revises:
Create Date: 2026-09-15
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("""
    CREATE TABLE accounts (
        id          bigserial PRIMARY KEY,
        name        text NOT NULL,
        created_at  timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE users (
        id          bigserial PRIMARY KEY,
        account_id  bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        email       text NOT NULL,
        created_at  timestamptz NOT NULL DEFAULT now(),
        UNIQUE (account_id, email)
    );

    CREATE TABLE vehicles (
        id            bigserial PRIMARY KEY,
        account_id    bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        vin           text NOT NULL UNIQUE,
        display_name  text,
        timezone      text NOT NULL DEFAULT 'UTC',
        created_at    timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX vehicles_account_idx ON vehicles (account_id);

    CREATE TABLE telemetry_events (
        account_id   bigint NOT NULL,
        vehicle_id   bigint NOT NULL,
        ts           timestamptz NOT NULL,
        field        text NOT NULL,
        value        jsonb,
        source       text NOT NULL DEFAULT 'telemetry',
        received_at  timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (vehicle_id, ts, field)
    ) PARTITION BY RANGE (ts);
    CREATE TABLE telemetry_events_default PARTITION OF telemetry_events DEFAULT;
    CREATE INDEX telemetry_events_account_ts_idx ON telemetry_events (account_id, vehicle_id, ts);

    CREATE TABLE connectivity_events (
        account_id   bigint NOT NULL,
        vehicle_id   bigint NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
        ts           timestamptz NOT NULL,
        connected    boolean NOT NULL,
        received_at  timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (vehicle_id, ts, connected)
    );

    CREATE TABLE raw_states (
        account_id    bigint NOT NULL,
        vehicle_id    bigint NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
        ts            timestamptz NOT NULL,
        source        text NOT NULL CHECK (source IN ('telemetry', 'teslafi_import', 'manual')),
        fields        jsonb NOT NULL,
        carried       jsonb NOT NULL DEFAULT '{}'::jsonb,
        gear          text,
        charge_state  text,
        speed         double precision,
        odometer      double precision,
        battery_level double precision,
        location      geography(Point, 4326),
        PRIMARY KEY (vehicle_id, ts, source)
    );
    CREATE INDEX raw_states_account_ts_idx ON raw_states (account_id, vehicle_id, ts);

    CREATE TABLE api_usage (
        account_id  bigint NOT NULL,
        vehicle_id  bigint NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
        day         date NOT NULL,
        category    text NOT NULL CHECK (category IN ('signal', 'command', 'wake', 'data')),
        field       text NOT NULL DEFAULT '',
        count       bigint NOT NULL DEFAULT 0,
        PRIMARY KEY (vehicle_id, day, category, field)
    );
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS api_usage;
    DROP TABLE IF EXISTS raw_states;
    DROP TABLE IF EXISTS connectivity_events;
    DROP TABLE IF EXISTS telemetry_events;
    DROP TABLE IF EXISTS vehicles;
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS accounts;
    """)
