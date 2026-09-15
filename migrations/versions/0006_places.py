"""Places and session locations.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-15
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE places (
        id          bigserial PRIMARY KEY,
        account_id  bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        name        text NOT NULL,
        kind        text NOT NULL CHECK (kind IN ('home', 'work', 'free', 'supercharger', 'other')),
        latitude    double precision NOT NULL,
        longitude   double precision NOT NULL,
        radius_m    double precision NOT NULL CHECK (radius_m BETWEEN 5 AND 5000),
        UNIQUE (account_id, name)
    );
    ALTER TABLE sessions
        ADD COLUMN start_latitude  double precision,
        ADD COLUMN start_longitude double precision,
        ADD COLUMN end_latitude    double precision,
        ADD COLUMN end_longitude   double precision,
        ADD COLUMN start_place_id  bigint REFERENCES places(id) ON DELETE SET NULL,
        ADD COLUMN end_place_id    bigint REFERENCES places(id) ON DELETE SET NULL;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE sessions DROP COLUMN start_latitude, DROP COLUMN start_longitude,
        DROP COLUMN end_latitude, DROP COLUMN end_longitude,
        DROP COLUMN start_place_id, DROP COLUMN end_place_id;
    DROP TABLE IF EXISTS places;
    """)
