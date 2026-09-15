import re

import pytest

from teslai.errors import CATALOG, TeslaiError


def test_every_entry_is_complete_and_code_shaped():
    for code, info in CATALOG.items():
        assert re.fullmatch(r"TSL-[A-Z0-9-]+", code), code
        assert info.code == code
        assert info.problem and info.cause and info.fix
        assert info.anchor == f"docs/errors.md#{code.lower()}"


def test_plan_required_codes_exist():
    for code in ["TSL-KEY-UNPAIRED", "TSL-PARTNER-UNREGISTERED", "TSL-SCOPE-MISSING",
                 "TSL-BILLING-DISABLED", "TSL-CONFIG-NULL", "TSL-CA-MISMATCH",
                 "TSL-FIRMWARE-TOO-OLD", "TSL-VIN-REJECTED", "TSL-REGION-WRONG",
                 "TSL-TOKEN-CONSUMED"]:
        assert code in CATALOG


def test_error_renders_problem_cause_fix_and_docs():
    msg = str(TeslaiError("TSL-KEY-UNPAIRED", "VIN ending 1234"))
    assert msg.startswith("TSL-KEY-UNPAIRED:")
    assert "Likely cause:" in msg and "Fix:" in msg and "Docs: docs/errors.md#" in msg
    assert "VIN ending 1234" in msg


def test_unknown_code_is_a_programming_error():
    with pytest.raises(KeyError):
        TeslaiError("TSL-NOT-REAL")
