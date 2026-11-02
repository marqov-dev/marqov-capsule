"""Redactor robustness: malformed notebooks scan to nothing (#125), the two
quadratic rules are linear (#126), and ``seal --warn-only`` actually warns (#105).
"""

import json
import time

import pytest
from click.testing import CliRunner

from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.cli.main import cli
from marqov_capsule.redactor import CapsuleRedactor, _scan_notebook, _scan_text
from marqov_capsule.validator import CapsuleValidator

REQUIREMENTS = {"paradigm": ["gate-based"], "max_qubit_count": 2}
GITHUB_TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


# --- #125 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "notebook",
    [
        '{"cells": 1}',
        '{"cells": true}',
        '{"cells": "abc"}',
        '{"cells": [1, "x", null]}',
        '{"cells": [{"outputs": 1}]}',
        '{"cells": [{"outputs": "abc"}]}',
        '{"cells": [{"source": 5, "outputs": [{"output_type": "stream", "text": 7}]}]}',
        '{"cells": [{"outputs": [{"output_type": "execute_result", "data": 3}]}]}',
        '{"cells": [{"outputs": [{"output_type": "error", "traceback": 3, "evalue": {}}]}]}',
        "[]",
        '"str"',
        "5",
        "null",
        "{",
    ],
)
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
    assert seconds < 5.0, f"{seconds:.2f}s for 1 MB of BEGIN markers"
    assert findings == []


def test_constructor_prefix_flood_is_linear():
    text = "IBMQ(" * 200_000  # ~1 MB single line, no closing paren
    findings, seconds = _timed(text)
    assert seconds < 5.0, f"{seconds:.2f}s for 1 MB of IBMQ( fragments"
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
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\ntask_executions: []\n"
    )
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
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\ntask_executions: []\n"
    )
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
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\ntask_executions: []\n"
    )
    (d / "data.txt").write_text("hello\n")
    result = CliRunner().invoke(cli, ["seal", "--json", str(d)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["findings"] == []
    text = CliRunner().invoke(cli, ["inspect", str(d)])
    assert "warning" not in text.output.lower()


# Mutation C*: Tier B entropy detection emits a non-blocking high_entropy_base64 finding
def test_high_entropy_base64_literal_is_a_tier_b_warning():
    findings = _scan_text('secret = "Zq9Kp2Lm8Rt4Vx7Wn3Yb6Hc1Jd5Fg0Sa"', "x.py")
    assert [f["reason"] for f in findings] == ["high_entropy_base64"]
    assert findings[0]["blocking"] is False


# --- mutation gaps (docs/MUTATION-REPORT-2026-10-15.md) -----------------------

AWS_KEY_LINE = "k = 'AKIAIOSFODNN7EXAMPLE'\n"


# Mutation B12: scan must continue past skipped entries (binary, symlink, ignored, unreadable)
def test_scan_continues_past_every_kind_of_skipped_entry(tmp_path):
    (tmp_path / "0.bin").write_bytes(b"\x00\x01")
    (tmp_path / "1link").symlink_to(tmp_path / "does-not-exist")
    unreadable = tmp_path / "2unreadable"
    unreadable.write_text("nothing\n", encoding="utf-8")
    unreadable.chmod(0)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "3.pyc").write_text("x\n", encoding="utf-8")
    (tmp_path / "z.py").write_text(AWS_KEY_LINE, encoding="utf-8")
    try:
        result = CapsuleRedactor(tmp_path).scan()
    finally:
        unreadable.chmod(0o600)
    assert [f["file"] for f in result["findings"]] == ["z.py"]
    assert result["skipped_binary"] == ["0.bin"]


# Mutation B10: notebook scan must continue past a malformed cell / outputs / output
@pytest.mark.parametrize(
    "notebook",
    [
        {"cells": [1, {"source": AWS_KEY_LINE}]},
        {"cells": [{"source": "", "outputs": 5}, {"source": AWS_KEY_LINE}]},
        {"cells": [{"outputs": [7, {"output_type": "stream", "text": AWS_KEY_LINE}]}]},
    ],
    ids=["non-dict-cell", "non-list-outputs", "non-dict-output"],
)
def test_notebook_scan_continues_past_malformed_entries(notebook):
    findings = _scan_notebook("n.ipynb", json.dumps(notebook))
    assert [f["reason"] for f in findings] == ["aws_access_key_id"]


# Mutation B7: capsule:allow after a comma does not reach back past it
def test_capsule_allow_after_a_comma_does_not_suppress_an_earlier_literal():
    findings = _scan_text('key = "AKIAIOSFODNN7EXAMPLE", other = 1  # capsule:allow', "x.py")
    assert [f["reason"] for f in findings] == ["aws_access_key_id"]


# Mutation B11: capsule:allow on a later line does not suppress a PEM block
def test_pem_block_allow_annotation_on_a_later_line_is_not_honoured():
    text = (
        "-----BEGIN PRIVATE KEY-----\nAAAAAAAAAAAAAAAAAAAAAAAA\n-----END PRIVATE KEY-----\n"
        "# capsule:allow\n"
    )
    assert [f["reason"] for f in _scan_text(text, "key.txt")] == ["private_key_block"]


# Mutation B9: a known credential name assigned from os.environ is not an embedded value
def test_known_name_assigned_from_environ_is_not_embedded():
    assert _scan_text('IBM_QUANTUM_TOKEN = os.environ["IBM_QUANTUM_TOKEN"]\n', "x.py") == []


# --- seal --dry-run on a manifest a real seal would refuse --------------------

UNSEALABLE_MANIFESTS = {
    "syntax-error": b"a: [\n",
    "forbidden-tag": b"a: !!python/object:os.system {}\n",
    "raw-control-char": b"a: \x01\n",
    "duplicate-key": b"a: 1\na: 2\n",
    "too-deep": b"a: " + b"[" * 5000 + b"\n",
    "empty": b"",
    "not-a-mapping": b"- a\n- b\n",
    "not-utf8": b"a: \xff\xfe\n",
}
LOADER_REJECTED = ["syntax-error", "forbidden-tag", "raw-control-char", "duplicate-key", "too-deep"]


@pytest.mark.parametrize("name", LOADER_REJECTED)
def test_scan_tolerates_a_manifest_that_does_not_parse(name, tmp_path):
    (tmp_path / "capsule.yaml").write_bytes(UNSEALABLE_MANIFESTS[name])
    assert CapsuleRedactor(tmp_path).scan()["findings"] == []


def test_scan_still_finds_a_literal_token_in_an_unparsable_manifest(tmp_path):
    (tmp_path / "capsule.yaml").write_text(f"note: {GITHUB_TOKEN}\na: [\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert [f["file"] for f in result["findings"]] == ["capsule.yaml"]
    assert result["findings"][0]["blocking"]


@pytest.mark.parametrize("name", UNSEALABLE_MANIFESTS)
def test_cli_dry_run_reports_an_unsealable_manifest_at_exit_0(name, tmp_path):
    (tmp_path / "capsule.yaml").write_bytes(UNSEALABLE_MANIFESTS[name])
    result = CliRunner().invoke(cli, ["seal", "--dry-run", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "no issues found" not in result.output
    assert len(result.output.strip().splitlines()) == 1
    assert "real seal would refuse" in result.output


@pytest.mark.parametrize("name", UNSEALABLE_MANIFESTS)
def test_cli_dry_run_json_reports_an_unsealable_manifest_at_exit_0(name, tmp_path):
    (tmp_path / "capsule.yaml").write_bytes(UNSEALABLE_MANIFESTS[name])
    result = CliRunner().invoke(cli, ["seal", "--dry-run", "--json", str(tmp_path)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["status"] == "warnings"
    assert "capsule.yaml" in report["manifest_error"]
    assert "\n" not in report["manifest_error"]
    assert report["findings"] == []


def test_cli_dry_run_json_clean_capsule_has_no_manifest_error(tmp_path):
    CapsuleBuilder().start_capsule(name="c", requirements=REQUIREMENTS).save_capsule(tmp_path)
    report = json.loads(
        CliRunner().invoke(cli, ["seal", "--dry-run", "--json", str(tmp_path)]).output
    )
    assert report["status"] == "clean"
    assert report["manifest_error"] is None


def test_cli_dry_run_keeps_findings_beside_a_manifest_error(tmp_path):
    (tmp_path / "capsule.yaml").write_text("a: [\n")
    (tmp_path / "run.py").write_text(f"token = '{GITHUB_TOKEN}'\n")
    result = CliRunner().invoke(cli, ["seal", "--dry-run", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "1 credential pattern(s) found" in result.output
    assert "run.py" in result.output
    assert "real seal would refuse" in result.output


@pytest.mark.parametrize(
    "manifest",
    [
        f"token: [{GITHUB_TOKEN}\nb: }}\n",
        f"x: 1\n{GITHUB_TOKEN}: 2\n{GITHUB_TOKEN}: 3\n",
        f"name: !!foo {GITHUB_TOKEN}\n",
        f"%{GITHUB_TOKEN} foo\n---\na: 1\n",
    ],
    ids=["snippet", "duplicate-key", "tag", "directive"],
)
@pytest.mark.parametrize("flags", [["--dry-run"], ["--dry-run", "--json"], [], ["--json"]])
def test_manifest_parse_errors_do_not_echo_credentials(flags, manifest, tmp_path):
    # PyYAML quotes the offending source line; findings are redacted, so the
    # message beside them must not print the token whole.
    (tmp_path / "capsule.yaml").write_text(manifest)
    result = CliRunner().invoke(cli, ["seal", *flags, str(tmp_path)])
    assert GITHUB_TOKEN not in result.output
    assert GITHUB_TOKEN[:20] not in result.output


def test_real_seal_still_refuses_an_unparsable_manifest(tmp_path):
    (tmp_path / "capsule.yaml").write_text("a: [\n")
    result = CliRunner().invoke(cli, ["seal", str(tmp_path)])
    assert result.exit_code == 1
    assert "could not be parsed" in result.output


# --- validate must not print what the credential scan redacts -----------------


@pytest.mark.parametrize(
    "manifest",
    [
        f"token: [{GITHUB_TOKEN}\nb: }}\n",
        f"x: 1\n{GITHUB_TOKEN}: 2\n{GITHUB_TOKEN}: 3\n",
        f"name: !!foo {GITHUB_TOKEN}\n",
        f"%{GITHUB_TOKEN} foo\n---\na: 1\n",
        f"name: t\nlifecycle_state: {GITHUB_TOKEN}\n",
        f"name: {{token: {GITHUB_TOKEN}}}\n",
        f"name: t\nrequirements:\n  paradigm: [{GITHUB_TOKEN}]\n",
        f"name: t\nrequirements:\n  {GITHUB_TOKEN}: 1\n",
    ],
    ids=[
        "snippet",
        "duplicate-key",
        "tag",
        "directive",
        "enum-value",
        "object-value",
        "array-item",
        "unexpected-key",
    ],
)
@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["text", "json"])
def test_validate_does_not_echo_credentials(flags, manifest, tmp_path):
    (tmp_path / "capsule.yaml").write_text(manifest)
    result = CliRunner().invoke(cli, ["validate", *flags, str(tmp_path)])
    assert result.exit_code == 1
    assert GITHUB_TOKEN[:20] not in result.output


def test_validate_api_does_not_echo_a_credential_key_in_a_domain_error():
    # The YAML loader rejects these numbers first, so only the Python API gets here.
    result = CapsuleValidator.validate({GITHUB_TOKEN: {"a": float("inf")}, "b": [float("nan")]})
    assert sorted(e["path"] for e in result["errors"]) == ["[redacted-key]/a", "b/0"]


def test_warn_only_seal_does_not_echo_credentials_in_schema_errors(tmp_path):
    (tmp_path / "capsule.yaml").write_text(
        f"version: '1.0.0'\nname: t\nlifecycle_state: draft\nrequirements: {REQUIREMENTS}\n"
        f"description: {{a: {GITHUB_TOKEN}}}\n"
    )
    result = CliRunner().invoke(cli, ["seal", "--warn-only", str(tmp_path)])
    assert result.exit_code == 1
    assert "does not validate" in result.output
    assert GITHUB_TOKEN[:20] not in result.output


def test_validate_parse_error_gives_the_location(tmp_path):
    (tmp_path / "capsule.yaml").write_text("a: [\n")
    result = CliRunner().invoke(cli, ["validate", "--json", str(tmp_path)])
    message = json.loads(result.output)["errors"][0]["message"]
    assert message == "YAML parse error: line 2, column 1"


def test_validate_schema_error_still_explains_the_problem(tmp_path):
    (tmp_path / "capsule.yaml").write_text("name: t\nlifecycle_state: nope\n")
    result = CliRunner().invoke(cli, ["validate", "--json", str(tmp_path)])
    errors = {e["path"]: e["message"] for e in json.loads(result.output)["errors"]}
    assert errors["lifecycle_state"].startswith("<value> is not one of [")
    assert "'draft'" in errors["lifecycle_state"]
