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


def test_capsule_allow_suppresses_name_pattern(tmp_path):
    # capsule:allow must suppress name-pattern matches, not just entropy heuristic
    src = tmp_path / "source"
    src.mkdir()
    (src / "config.py").write_text('IBM_QUANTUM_TOKEN = "test"  # capsule:allow\n')
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is False
