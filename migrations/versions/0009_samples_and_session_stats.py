"""Time-series samples for charts and maps, and per-session statistics.

samples holds one row per logged moment (TeslaFi CSV rows, or live telemetry
snapshots): position, speed, power, battery, range, temperatures, charging and
tire pressures. Temperatures are Celsius, speeds mph, distances miles, pressure bar.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-15
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE samples (
        account_id          bigint NOT NULL,
        vehicle_id          bigint NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
        ts                  timestamptz NOT NULL,
        source              text NOT NULL,
        latitude            double precision,
        longitude           double precision,
        speed               double precision,
        power               double precision,
        battery_level       double precision,
        rated_range         double precision,
        odometer            double precision,
        energy_remaining    double precision,
        inside_temp         double precision,
        outside_temp        double precision,
        charger_power       double precision,
        charge_energy_added double precision,
        charge_state        text,
        gear                text,
        tpms_fl             double precision,
        tpms_fr             double precision,
        tpms_rl             double precision,
        tpms_rr             double precision,
        PRIMARY KEY (vehicle_id, ts)
    );
    CREATE INDEX samples_account_ts_idx ON samples (account_id, vehicle_id, ts);
    ALTER TABLE sessions
        ADD COLUMN energy_used_kwh    double precision,
        ADD COLUMN rated_miles_used   double precision,
        ADD COLUMN avg_outside_temp   double precision,
        ADD COLUMN avg_inside_temp    double precision,
        ADD COLUMN max_speed          double precision,
        ADD COLUMN avg_speed          double precision,
        ADD COLUMN max_charger_power  double precision;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE sessions DROP COLUMN energy_used_kwh, DROP COLUMN rated_miles_used,
        DROP COLUMN avg_outside_temp, DROP COLUMN avg_inside_temp, DROP COLUMN max_speed,
        DROP COLUMN avg_speed, DROP COLUMN max_charger_power;
    DROP TABLE IF EXISTS samples;
    """)
