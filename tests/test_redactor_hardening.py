"""Redactor robustness: malformed notebooks scan to nothing (#125), the two
quadratic rules are linear (#126), and ``seal --warn-only`` actually warns (#105).
"""
import json
import time

import pytest
from click.testing import CliRunner

from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.cli.main import cli
from marqov_capsule.redactor import _scan_notebook, _scan_text

REQUIREMENTS = {"paradigm": ["gate-based"], "max_qubit_count": 2}
GITHUB_TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


# --- #125 ---------------------------------------------------------------------

@pytest.mark.parametrize("notebook", [
    '{"cells": 1}',
    '{"cells": true}',
    '{"cells": "abc"}',
    '{"cells": [1, "x", null]}',
    '{"cells": [{"outputs": 1}]}',
    '{"cells": [{"outputs": "abc"}]}',
    '{"cells": [{"source": 5, "outputs": [{"output_type": "stream", "text": 7}]}]}',
    '{"cells": [{"outputs": [{"output_type": "execute_result", "data": 3}]}]}',
    '{"cells": [{"outputs": [{"output_type": "error", "traceback": 3, "evalue": {}}]}]}',
    '[]', '"str"', '5', 'null', '{',
])
def test_malformed_notebook_scans_to_nothing(notebook):
    assert _scan_notebook("nb.ipynb", notebook) == []


def test_notebook_cells_as_string_is_not_scanned_per_character():
    # A string iterates character by character; each char must not become a cell.
    assert _scan_notebook("nb.ipynb", json.dumps({"cells": GITHUB_TOKEN})) == []


def test_cli_dry_run_on_malformed_notebook_exits_0(tmp_path):
    (tmp_path / "capsule.yaml").write_text("version: '1.0.0'\nname: t\nlifecycle_state: draft\n")
    (tmp_path / "bad.ipynb").write_text('{"cells": [{"outputs": 1}]}')
    result = CliRunner().invoke(cli, ["seal", "--dry-run", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


# --- #126 ---------------------------------------------------------------------

def _timed(text):
    started = time.perf_counter()
    findings = _scan_text(text, "f.txt")
    return findings, time.perf_counter() - started


def test_pem_begin_marker_flood_is_linear():
    text = "-----BEGIN PRIVATE KEY-----\n" * 36_000  # ~1 MB, no END anywhere
    findings, seconds = _timed(text)
    assert seconds < 1.0, f"{seconds:.2f}s for 1 MB of BEGIN markers"
    assert findings == []


def test_constructor_prefix_flood_is_linear():
    text = "IBMQ(" * 200_000  # ~1 MB single line, no closing paren
    findings, seconds = _timed(text)
    assert seconds < 1.0, f"{seconds:.2f}s for 1 MB of IBMQ( fragments"
    assert findings == []


def test_pem_private_key_block_is_still_detected():
    body = "\n".join("MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7" for _ in range(30))
    text = f"# config\n-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----\n"
    findings = _scan_text(text, "key.txt")
    assert [f["reason"] for f in findings] == ["private_key_block"]
    assert findings[0]["line"] == 2
    assert findings[0]["blocking"] is True


def test_pem_block_allow_annotation_on_begin_line_still_honoured():
    text = "-----BEGIN PRIVATE KEY-----  # capsule:allow\nAAAAAAAAAAAAAAAAAAAAAAAA\n-----END PRIVATE KEY-----\n"
    assert _scan_text(text, "key.txt") == []


def test_constructor_literal_token_is_still_detected():
    text = 'service = QiskitRuntimeService(channel="ibm_quantum", token="abc123def456ghi789")\n'
    findings = _scan_text(text, "run.py")
    assert [f["reason"] for f in findings] == ["constructor_pattern"]
    assert findings[0]["blocking"] is True


def test_constructor_with_variable_token_is_not_flagged():
    assert _scan_text("QiskitRuntimeService(token=os.environ['T'])\n", "run.py") == []


# --- #105 ---------------------------------------------------------------------

def _draft_with_token(tmp_path):
    d = tmp_path / "cap"
    d.mkdir()
    (d / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: t\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\ntask_executions: []\n")
    (d / "run.py").write_text(f'token = "{GITHUB_TOKEN}"\n')
    return d


def test_builder_seal_exposes_the_scan_result(tmp_path):
    d = _draft_with_token(tmp_path)
    builder = CapsuleBuilder().start_capsule(name="t", requirements=REQUIREMENTS)
    builder.seal(d, warn_only=True)
    assert [f["reason"] for f in builder.scan_result["findings"]] == ["github_token"]


def test_cli_seal_warn_only_prints_each_finding(tmp_path):
    d = _draft_with_token(tmp_path)
    result = CliRunner().invoke(cli, ["seal", "--warn-only", str(d)])
    assert result.exit_code == 0, result.output
    assert "Sealed:" in result.output
    assert "run.py:1" in result.output
    assert "github_token" in result.output
    assert "warning" in result.output.lower()


def test_cli_seal_warn_only_json_carries_findings(tmp_path):
    d = _draft_with_token(tmp_path)
    result = CliRunner().invoke(cli, ["seal", "--warn-only", "--json", str(d)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "sealed"
    assert [f["reason"] for f in data["findings"]] == ["github_token"]
    assert data["findings"][0]["file"] == "run.py"


def test_cli_seal_prints_tier_b_warnings_in_default_mode(tmp_path):
    d = tmp_path / "cap"
    d.mkdir()
    (d / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: t\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\ntask_executions: []\n")
    (d / "config.py").write_text('SERVICE_API_KEY = "abc123xyz789qrs456"\n')
    result = CliRunner().invoke(cli, ["seal", str(d)])
    assert result.exit_code == 0, result.output  # Tier B never blocks
    assert "config.py:1" in result.output
    assert "name_entropy" in result.output


def test_cli_seal_clean_capsule_prints_no_warning_block(tmp_path):
    d = tmp_path / "cap"
    d.mkdir()
    (d / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: t\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\ntask_executions: []\n")
    (d / "data.txt").write_text("hello\n")
    result = CliRunner().invoke(cli, ["seal", "--json", str(d)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["findings"] == []
    text = CliRunner().invoke(cli, ["inspect", str(d)])
    assert "warning" not in text.output.lower()
