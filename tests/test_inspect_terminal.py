"""Terminal output must not execute or visually hide untrusted metadata."""
import json

import pytest
import yaml
from click.testing import CliRunner

from marqov_capsule.cli.main import cli


@pytest.mark.parametrize("control", ["\x1b[2J", "\x1b]52;c;fake\x07", "\r", "\n", "\x9b", "\u202e", "\u2028"])
def test_inspect_escapes_controls_everywhere(tmp_path, control):
    value = "before" + control + "after"
    manifest = {
        "name": value, "version": value, "lifecycle_state": value,
        "sealed_at": value, "requirements": {"paradigm": [value], "max_qubit_count": value},
        "task_executions": [{"backend": {"provider": value, "name": value},
                             "status": value, "result_type": value}],
        "derived_from": value, "checksums_digest": value,
    }
    (tmp_path / "capsule.yaml").write_text(yaml.safe_dump(manifest))
    result = CliRunner().invoke(cli, ["inspect", str(tmp_path)], color=True)
    assert result.exit_code == 0, result.output
    assert len(result.output.splitlines()) == 10
    assert all(c.isprintable() or c == "\n" for c in result.output)
    assert "before" + control.encode("unicode_escape").decode("ascii") in result.output
    machine = CliRunner().invoke(cli, ["inspect", str(tmp_path), "--json"], color=True)
    assert machine.exit_code == 0
    assert json.loads(machine.output) == manifest


def test_inspect_preserves_readable_unicode(tmp_path):
    (tmp_path / "capsule.yaml").write_text('name: "Bell — café ⚛"\n')
    result = CliRunner().invoke(cli, ["inspect", str(tmp_path)], color=True)
    assert result.exit_code == 0
    assert "Bell — café ⚛" in result.output
