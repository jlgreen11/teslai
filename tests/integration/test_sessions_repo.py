from datetime import UTC, datetime, timedelta

import pytest

from teslai.builder import Session
from teslai.db import repo
from teslai.errors import TeslaiError

pytestmark = pytest.mark.integration
T0 = datetime(2026, 7, 1, tzinfo=UTC)


def _vehicle(conn):
    a = repo.create_account(conn, "owner")
    return a, repo.create_vehicle(conn, a, "TESTVIN0000000002")


def _drive(h, miles):
    return Session("drive", T0 + timedelta(hours=h), T0 + timedelta(hours=h, minutes=30),
                   start_odometer=1000.0, end_odometer=1000.0 + miles, flags={"short"})


def test_replace_is_idempotent_and_scoped_to_window(conn):
    a, v = _vehicle(conn)
    end = T0 + timedelta(days=1)
    assert repo.replace_sessions(conn, a, v, T0, end, [_drive(1, 5), _drive(3, 7)],
                                 "teslafi_import", 1) == 2
    assert repo.replace_sessions(conn, a, v, T0, end, [_drive(1, 5), _drive(3, 7)],
                                 "teslafi_import", 1) == 2
    repo.replace_sessions(conn, a, v, end, end + timedelta(days=1), [_drive(26, 9)],
                          "teslafi_import", 1)
    day1 = repo.sessions_between(conn, a, v, T0, end, kind="drive")
    assert [round(r["end_odometer"] - r["start_odometer"]) for r in day1] == [5, 7]
    assert day1[0]["flags"] == ["short"]
    repo.replace_sessions(conn, a, v, T0, end, [_drive(2, 4)], "teslafi_import", 2)
    day1 = repo.sessions_between(conn, a, v, T0, end)
    assert len(day1) == 1 and day1[0]["builder_version"] == 2
    assert len(repo.sessions_between(conn, a, v, end, end + timedelta(days=1))) == 1


def test_open_session_allowed_and_other_account_rejected(conn):
    a, v = _vehicle(conn)
    live = Session("sleep", T0 + timedelta(hours=5))
    assert repo.replace_sessions(conn, a, v, T0, T0 + timedelta(days=1), [live], "telemetry", 1) == 1
    other = repo.create_account(conn, "someone else")
    with pytest.raises(TeslaiError):
        repo.replace_sessions(conn, other, v, T0, T0 + timedelta(days=1), [], "telemetry", 1)
    assert repo.sessions_between(conn, other, v, T0, T0 + timedelta(days=1)) == []
