"""The values the spec's field tables quote must equal the schema's (#112)."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "spec/v1/README.md").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "spec/v1/capsule-schema.json").read_text(encoding="utf-8"))
PROPERTIES = SCHEMA["properties"]
TASK = PROPERTIES["task_executions"]["items"]["properties"]


def _row(field):
    match = re.search(rf"^\| `{field}` \|(.*)$", README, re.M)
    assert match, f"no README table row for {field}"
    return match.group(1)


@pytest.mark.parametrize(
    "field,schema",
    [
        ("lifecycle_state", PROPERTIES["lifecycle_state"]),
        ("status", TASK["status"]),
        ("result_type", TASK["result_type"]),
        ("paradigm", PROPERTIES["requirements"]["properties"]["paradigm"]["items"]),
    ],
)
def test_quoted_enums_match_the_schema(field, schema):
    assert sorted(re.findall(r"`([^`]+)`", _row(field))) == sorted(schema["enum"])


def test_version_matches_the_schema():
    assert f'`"{PROPERTIES["version"]["const"]}"`' in _row("version")


def test_max_qubit_count_minimum_matches_the_schema():
    minimum = PROPERTIES["requirements"]["properties"]["max_qubit_count"]["minimum"]
    assert f"integer \N{GREATER-THAN OR EQUAL TO} {minimum}" in _row("max_qubit_count")
