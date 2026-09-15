import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from teslai.paths import REPO_DIR

BASE_URL = os.environ.get("TESLAI_TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def engine():
    if not BASE_URL:
        pytest.skip("TESLAI_TEST_DATABASE_URL not set")
    admin = create_engine(BASE_URL, isolation_level="AUTOCOMMIT")
    dbname = f"teslai_test_{uuid.uuid4().hex[:8]}"
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{dbname}"'))
    url = make_url(BASE_URL).set(database=dbname).render_as_string(hide_password=False)
    cfg = Config(str(REPO_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_DIR / "migrations"))
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    yield eng
    eng.dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE "{dbname}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture()
def conn(engine):
    with engine.connect() as c:
        tx = c.begin()
        yield c
        tx.rollback()
