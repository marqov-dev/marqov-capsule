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
    (tmp_path / ".env").write_text('AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n')
    (tmp_path / ".capsuleignore").write_text(".env\n")
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is False


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
