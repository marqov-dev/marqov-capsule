import json
from pathlib import Path
import pytest
from marqov_capsule.redactor import CapsuleRedactor, RedactorError


FIXTURE_DIR = Path(__file__).parent.parent / "spec/v1/conformance"


def test_clean_dir_passes(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "circuit.py").write_text("from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\n")
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is False
    assert result["findings"] == []


def test_detects_name_based_token(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "config.py").write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is True
    assert any("IBM_QUANTUM_TOKEN" in f["match"] for f in result["findings"])


def test_detects_constructor_pattern(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "run.py").write_text('QiskitRuntimeService(token="fake-token-abcdef1234567890")\n')
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is True


def test_detects_key_suffix(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "config.json").write_text('{"AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}\n')
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is True


def test_block_mode_raises(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "config.py").write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')
    redactor = CapsuleRedactor(tmp_path, mode="block")
    with pytest.raises(RedactorError):
        redactor.scan_and_raise()


def test_warn_only_returns_result(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "config.py").write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')
    redactor = CapsuleRedactor(tmp_path, mode="warn_only")
    result = redactor.scan()
    assert result["has_secrets"] is True  # found but not raised


def test_allowlist_digest_fields_not_flagged(tmp_path):
    # SHA-256 hashes in spec-defined fields must not trigger the high-entropy heuristic
    manifest = tmp_path / "capsule.yaml"
    manifest.write_text(
        "checksums_digest: sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890\n"
        "version: '1.0.0'\n"
    )
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is False


def test_capsuleignore_excludes_files(tmp_path):
    """.capsuleignore narrows *scanning* scope, and the narrowing is reported.

    Rewritten for #34. This previously wrote a `.env` containing an AWS key,
    ignored it via `.capsuleignore`, and asserted `has_secrets is False` — the
    test encoded the vulnerability. A credential-shaped file is now a finding
    that no ignore rule can suppress; see the #34 tests below.
    """
    (tmp_path / "vendored.py").write_text("IBM_QUANTUM_TOKEN = 'abc'\n")
    (tmp_path / ".capsuleignore").write_text("vendored.py\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"] is False
    assert "vendored.py" in result["skipped"]


def test_capsule_with_secrets_fixture_detected():
    fixture_dir = FIXTURE_DIR / "capsule_with_secrets"
    redactor = CapsuleRedactor(fixture_dir)
    result = redactor.scan()
    assert result["has_secrets"] is True


def test_valid_capsule_fixture_clean():
    fixture_dir = FIXTURE_DIR / "valid_capsule"
    redactor = CapsuleRedactor(fixture_dir)
    result = redactor.scan()
    assert result["has_secrets"] is False


def test_redactor_does_not_follow_symlinks(tmp_path):
    """Redactor must not follow symlinks out of the capsule tree (#32).

    A symlink whose target lives outside the capsule must not be read; otherwise
    the scanner reaches arbitrary files on the sealer's machine.
    """
    outside = tmp_path / "outside_secret.py"
    outside.write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')

    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    src = capsule_dir / "source"
    src.mkdir()
    (src / "link.py").symlink_to(outside)

    redactor = CapsuleRedactor(capsule_dir)
    result = redactor.scan()
    assert result["has_secrets"] is False


def test_capsule_allow_suppresses_name_pattern(tmp_path):
    # capsule:allow must suppress name-pattern matches, not just entropy heuristic
    src = tmp_path / "source"
    src.mkdir()
    (src / "config.py").write_text('IBM_QUANTUM_TOKEN = "test"  # capsule:allow\n')
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is False


# --- Notebook coverage (#33) ------------------------------------------------
# _scan_notebook walked only `outputs`. A researcher pastes a live token into a
# *source* cell, which is where it actually happens, and seal gates on this scan.

def _notebook(cells):
    import json
    return json.dumps({"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5})


def test_detects_secret_in_code_cell_source(tmp_path):
    (tmp_path / "run.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": ["IBM_QUANTUM_TOKEN = \"abc123\"\n"],
        "outputs": [], "execution_count": 1, "metadata": {},
    }]))
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"], result


def test_detects_secret_in_markdown_cell_source(tmp_path):
    (tmp_path / "notes.ipynb").write_text(_notebook([{
        "cell_type": "markdown", "source": ["Use `IBM_QUANTUM_TOKEN = \"abc\"` to run.\n"],
        "metadata": {},
    }]))
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"], result


def test_detects_secret_in_error_traceback(tmp_path):
    """Tracebacks routinely echo the offending line, tokens included."""
    (tmp_path / "boom.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": ["connect()\n"], "execution_count": 1, "metadata": {},
        "outputs": [{
            "output_type": "error", "ename": "ValueError", "evalue": "bad token",
            "traceback": ["Traceback...", "  IBM_QUANTUM_TOKEN = \"abc123\""],
        }],
    }]))
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"], result


def test_notebook_source_as_plain_string(tmp_path):
    """nbformat allows `source` to be a string rather than a list of lines."""
    (tmp_path / "s.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": "IBM_QUANTUM_TOKEN = \"abc123\"\n",
        "outputs": [], "execution_count": 1, "metadata": {},
    }]))
    assert CapsuleRedactor(tmp_path).scan()["has_secrets"]


def test_notebook_stream_output_still_scanned(tmp_path):
    """Regression: output scanning must survive the source-cell fix."""
    (tmp_path / "o.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": ["print(tok)\n"], "execution_count": 1, "metadata": {},
        "outputs": [{"output_type": "stream", "name": "stdout",
                     "text": ["IBM_QUANTUM_TOKEN = \"abc123\"\n"]}],
    }]))
    assert CapsuleRedactor(tmp_path).scan()["has_secrets"]


def test_clean_notebook_not_flagged(tmp_path):
    (tmp_path / "clean.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": ["from qiskit import QuantumCircuit\n"],
        "outputs": [], "execution_count": 1, "metadata": {},
    }]))
    assert not CapsuleRedactor(tmp_path).scan()["has_secrets"]


def test_malformed_notebook_does_not_crash(tmp_path):
    (tmp_path / "bad.ipynb").write_text("{not valid json")
    (tmp_path / "odd.ipynb").write_text('{"cells": [{"cell_type": "code", "source": null}]}')
    assert not CapsuleRedactor(tmp_path).scan()["has_secrets"]


def test_notebook_reports_the_notebook_path(tmp_path):
    (tmp_path / "run.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": ["IBM_QUANTUM_TOKEN = \"abc\"\n"],
        "outputs": [], "execution_count": 1, "metadata": {},
    }]))
    findings = CapsuleRedactor(tmp_path).scan()["findings"]
    assert findings and findings[0]["file"] == "run.ipynb"
# --- Ignore-file trust and credential-shaped files (#34) --------------------
# Two distinct holes. (1) .capsuleignore is read from inside the capsule and
# REPLACED the whole default ignore set, so a capsule carrying one containing
# `source` silently disabled scanning for that subtree. (2) .env/*.pem/*.key
# were excluded from *scanning* while save_checksums still packaged them, so a
# directory holding secrets scanned clean and sealed with them inside.

def test_env_file_is_a_finding_not_an_exclusion(tmp_path):
    (tmp_path / ".env").write_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"], result
    assert any(f["reason"] == "credential_file" for f in result["findings"]), result


def test_private_key_files_are_findings(tmp_path):
    (tmp_path / "deploy.key").write_text("-----BEGIN PRIVATE KEY-----\n")
    (tmp_path / "server.pem").write_text("-----BEGIN CERTIFICATE-----\n")
    reasons = [f["reason"] for f in CapsuleRedactor(tmp_path).scan()["findings"]]
    assert reasons.count("credential_file") == 2, reasons


def test_capsuleignore_cannot_suppress_a_credential_file(tmp_path):
    """The file is being packaged into the capsule. Not scanning it doesn't help."""
    (tmp_path / ".env").write_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n")
    (tmp_path / ".capsuleignore").write_text(".env\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"], result
    assert any(f["reason"] == "credential_file" for f in result["findings"]), result


def test_seal_is_blocked_by_a_credential_file(tmp_path):
    from marqov_capsule.builder import CapsuleBuilder
    (tmp_path / "payload").mkdir()
    (tmp_path / "payload" / "results.json").write_text('{"counts": {"00": 1}}')
    (tmp_path / ".env").write_text("AWS_SECRET_ACCESS_KEY=abc\n")
    b = CapsuleBuilder.from_manifest({
        "version": "1.0.0", "name": "t", "lifecycle_state": "draft",
        "requirements": {"paradigm": ["gate-based"], "max_qubit_count": 2},
        "task_executions": [],
    })
    with pytest.raises(RedactorError):
        b.seal(capsule_dir=tmp_path, sealed_by="test")


def test_capsuleignore_adds_to_defaults_rather_than_replacing(tmp_path):
    """A .capsuleignore must not be able to un-skip the default noise set."""
    (tmp_path / ".capsuleignore").write_text("data\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.py").write_text("IBM_QUANTUM_TOKEN = 'abc'\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "y.py").write_text("IBM_QUANTUM_TOKEN = 'abc'\n")
    result = CapsuleRedactor(tmp_path).scan()
    scanned = {f["file"] for f in result["findings"]}
    assert not any("__pycache__" in s for s in scanned), scanned
    assert not any("data" in s for s in scanned), scanned


def test_scan_reports_what_it_skipped(tmp_path):
    """Narrowing scope must be visible, not silent."""
    (tmp_path / ".capsuleignore").write_text("source\n")
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "circuit.py").write_text("IBM_QUANTUM_TOKEN = 'abc'\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert not result["has_secrets"]
    assert "source/circuit.py" in result["skipped"], result
    assert "source" in result["capsuleignore_patterns"], result


def test_scan_reports_no_capsuleignore_patterns_when_absent(tmp_path):
    (tmp_path / "a.py").write_text("print(1)\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert result["capsuleignore_patterns"] == []
    assert result["skipped"] == []


def test_seal_dry_run_reports_narrowed_scope(tmp_path):
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli
    (tmp_path / "capsule.yaml").write_text(
        "version: 1.0.0\nname: t\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\n"
        "task_executions: []\n")
    (tmp_path / ".capsuleignore").write_text("source\n")
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "circuit.py").write_text("IBM_QUANTUM_TOKEN = 'abc'\n")
    out = CliRunner().invoke(cli, ["seal", "--dry-run", str(tmp_path)]).output
    assert ".capsuleignore" in out, out
    assert "source" in out, out


def test_real_seal_also_reports_narrowed_scope(tmp_path):
    """--dry-run is the path people skip. The gate itself must say so too."""
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli
    (tmp_path / "capsule.yaml").write_text(
        "version: 1.0.0\nname: t\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\n"
        "task_executions: []\n")
    (tmp_path / ".capsuleignore").write_text("source\n")
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "circuit.py").write_text("print(1)\n")
    result = CliRunner().invoke(cli, ["seal", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert ".capsuleignore" in result.output, result.output
    assert "source" in result.output, result.output


def test_credential_file_error_advises_removal_not_annotation(tmp_path):
    """`# capsule:allow` is line-based and cannot suppress a whole-file finding.
    Advising it for a .env would send the user down a dead end."""
    (tmp_path / ".env").write_text("AWS_SECRET_ACCESS_KEY=abc\n")
    with pytest.raises(RedactorError) as exc:
        CapsuleRedactor(tmp_path).scan_and_raise()
    msg = str(exc.value)
    assert "capsule:allow" not in msg, msg
    assert "move" in msg.lower() or "remove" in msg.lower(), msg
