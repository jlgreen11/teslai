import os

from alembic import context
from sqlalchemy import create_engine

from teslai.settings import Settings


def _url() -> str:
    url = context.config.attributes.get("url") or os.environ.get("DATABASE_URL")
    return url or Settings().database_url


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
