"""Regression tests for the canonicalization / builder-lifecycle bug fixes.

Covers issues #57, #59, and the #20 determinism defects (YAML 1.1 coercion,
datetime on-disk agreement, non-string mapping keys, and the .checksums
on-disk format).
"""

import datetime
import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

from marqov_capsule._canonical import compute_capsule_id, load_manifest_yaml
from marqov_capsule.builder import CapsuleBuilder, CapsuleStateError
from marqov_capsule.redactor import RedactorError
from marqov_capsule.verifier import CapsuleVerifier

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_A64 = "a" * 64  # a valid-looking 64-hex token value


def _draft(**overrides):
    manifest = {
        "version": "1.0.0",
        "name": "bugfix",
        "lifecycle_state": "draft",
        "requirements": {"paradigm": ["gate-based"], "max_qubit_count": 2},
        "task_executions": [],
    }
    manifest.update(overrides)
    return manifest


def _populate(capsule_dir: Path):
    payload = capsule_dir / "payload"
    payload.mkdir(parents=True, exist_ok=True)
    (payload / "results.json").write_text(json.dumps({"counts": {"00": 512, "11": 512}}))
    source = capsule_dir / "source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "circuit.qasm").write_text("OPENQASM 3.0;\n")


def _parse_spec_checksums(text: str) -> dict[str, str]:
    """Parse the spec-format .checksums ('sha256:<hex>  <path>' lines)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, path = line.split("  ", 1)
        out[path] = digest
    return out


# ---------------------------------------------------------------------------
# #57 — credential scan must cover the in-memory manifest
# ---------------------------------------------------------------------------


def test_manifest_borne_secret_is_blocked_via_python_api(tmp_path):
    """A token carried only in the in-memory manifest (not on disk) must still
    block sealing through from_manifest().seal(). Before the fix the scan ran
    before capsule.yaml was written, so this sealed clean. (#57)"""
    capsule_dir = tmp_path / "leak.capsule"
    _populate(capsule_dir)
    b = CapsuleBuilder.from_manifest(_draft(parameters={"IBM_QUANTUM_TOKEN": _A64}))
    with pytest.raises(RedactorError):
        b.seal(capsule_dir=capsule_dir, sealed_by="test")


def test_clean_manifest_still_seals_via_python_api(tmp_path):
    """The scan-the-manifest change must not false-positive a normal capsule."""
    capsule_dir = tmp_path / "clean.capsule"
    _populate(capsule_dir)
    cid = CapsuleBuilder.from_manifest(_draft()).seal(capsule_dir=capsule_dir, sealed_by="test")
    assert cid.startswith("mqc:1:") and len(cid.split(":")[-1]) == 64


# ---------------------------------------------------------------------------
# #59 — no silent re-seal of an already-sealed capsule
# ---------------------------------------------------------------------------


def test_reseal_refused_python_api(tmp_path):
    """Seal, mutate a payload file, seal again -> must be refused. (#59)"""
    capsule_dir = tmp_path / "immutable.capsule"
    _populate(capsule_dir)
    CapsuleBuilder.from_manifest(_draft()).seal(capsule_dir=capsule_dir, sealed_by="a")

    # Mutate a payload file after sealing.
    (capsule_dir / "payload" / "results.json").write_text(json.dumps({"counts": {"00": 1024}}))

    reloaded = load_manifest_yaml((capsule_dir / "capsule.yaml").read_text())
    assert reloaded["lifecycle_state"] == "sealed"
    with pytest.raises(CapsuleStateError):
        CapsuleBuilder.from_manifest(reloaded).seal(capsule_dir=capsule_dir, sealed_by="b")


def test_reseal_refused_cli(tmp_path):
    """The CLI must refuse to re-seal a sealed capsule, with a clean exit 1. (#59)"""
    from click.testing import CliRunner

    from marqov_capsule.cli.main import cli

    _populate(tmp_path)
    (tmp_path / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: t\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\n"
        "task_executions: []\n"
    )
    runner = CliRunner()
    first = runner.invoke(cli, ["seal", str(tmp_path)])
    assert first.exit_code == 0, first.output

    (tmp_path / "payload" / "results.json").write_text(json.dumps({"counts": {"00": 1024}}))

    second = runner.invoke(cli, ["seal", str(tmp_path)])
    assert second.exit_code == 1, second.output
    assert second.exception is None or isinstance(second.exception, SystemExit)
    assert "sealed" in second.output.lower()


# ---------------------------------------------------------------------------
# #20 — YAML 1.1 coercions must not fire (scalars read as strings)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("yes", "yes"),
        ("no", "no"),
        ("on", "on"),
        ("off", "off"),
        ("0x1A", "0x1A"),
        ("0o27", "0o27"),
        ("12:30", "12:30"),
        ("12:30:00", "12:30:00"),
        ("1_000", "1_000"),
    ],
)
def test_yaml_1_1_coercions_round_trip_as_string(raw, expected):
    """Each YAML-1.1-only coercion case must load as the literal string. (#20)"""
    parsed = load_manifest_yaml(f"value: {raw}\n")
    assert parsed["value"] == expected
    assert isinstance(parsed["value"], str)


def test_json_scalars_still_typed():
    """The fix must not turn legitimate JSON scalars into strings."""
    parsed = load_manifest_yaml("i: 256\nf: 0.05\nb: true\nn: null\ns: 1.0.0\n")
    assert parsed["i"] == 256 and isinstance(parsed["i"], int)
    assert parsed["f"] == 0.05 and isinstance(parsed["f"], float)
    assert parsed["b"] is True
    assert parsed["n"] is None
    assert parsed["s"] == "1.0.0"  # not a float


# ---------------------------------------------------------------------------
# #20 — datetime on-disk serialization must agree with the canonical ID
# ---------------------------------------------------------------------------


def test_datetime_parameter_id_round_trips_from_disk(tmp_path):
    """Seal with a datetime parameter; the ID recomputed from the written
    capsule.yaml must equal the published ID. (#20)"""
    capsule_dir = tmp_path / "dt.capsule"
    _populate(capsule_dir)
    b = CapsuleBuilder.from_manifest(
        _draft(parameters={"run_at": datetime.datetime(2026, 6, 11, 12, 30, 0)})
    )
    sealed_id = b.seal(capsule_dir=capsule_dir, sealed_by="test")

    from_disk = compute_capsule_id(load_manifest_yaml((capsule_dir / "capsule.yaml").read_text()))
    assert from_disk == sealed_id


# ---------------------------------------------------------------------------
# #20 / _canonical.py:66 — non-string mapping keys must not crash
# ---------------------------------------------------------------------------


def test_non_string_mapping_keys_do_not_crash():
    """Typed (int/bool) mapping keys never raise a bare exception out of jcs
    (#20). In a YAML manifest they are a parse error, because two readers do
    not agree on their spelling (spec §5, #119); in an in-memory dict handed
    to the builder they are stringified deterministically."""
    with pytest.raises(yaml.YAMLError, match="non-string key"):
        load_manifest_yaml("parameters:\n  123: foo\n  true: bar\n")
    manifest = {"parameters": {123: "foo", True: "bar"}}
    cid = compute_capsule_id(manifest)
    assert cid.startswith("mqc:1:") and len(cid.split(":")[-1]) == 64
    assert cid == compute_capsule_id({"parameters": {"123": "foo", "true": "bar"}})


def test_verify_integrity_survives_non_string_key(tmp_path):
    """verify_integrity must return (not raise) on a manifest with a typed key."""
    capsule_dir = tmp_path / "keyed.capsule"
    capsule_dir.mkdir()
    (capsule_dir / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: t\nlifecycle_state: draft\nparameters:\n  42: x\n"
    )
    result = CapsuleVerifier.verify_integrity(capsule_dir)
    assert result["status"] == "fail"
    assert result["capsule_id"] is None
    assert any("could not be parsed" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# #20 / builder.py:237 — .checksums on-disk format is the spec line format
# ---------------------------------------------------------------------------


def test_checksums_written_in_spec_line_format(tmp_path):
    """Builder must emit newline-delimited 'sha256:<hex>  <path>' lines, sorted
    by path, and checksums_digest must be the SHA-256 of those exact bytes. (#20)"""
    capsule_dir = tmp_path / "fmt.capsule"
    _populate(capsule_dir)
    sealed_id = CapsuleBuilder.from_manifest(_draft()).seal(capsule_dir=capsule_dir, sealed_by="t")

    raw = (capsule_dir / ".checksums").read_text()
    lines = raw.splitlines()
    assert lines, "expected at least one checksum line"
    for line in lines:
        assert re.match(r"^sha256:[0-9a-f]{64}  \S.*$", line), line

    parsed = _parse_spec_checksums(raw)
    assert "payload/results.json" in parsed
    assert "source/circuit.qasm" in parsed
    assert list(parsed.keys()) == sorted(parsed.keys())

    manifest = load_manifest_yaml((capsule_dir / "capsule.yaml").read_text())
    expected_digest = "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert manifest["checksums_digest"] == expected_digest

    # And the whole chain still verifies against the published ID.
    result = CapsuleVerifier.verify_integrity(capsule_dir, expected_id=sealed_id)
    assert result["status"] == "pass", result


def test_empty_payload_checksums_is_zero_bytes(tmp_path):
    """A capsule with no payload files produces an empty .checksums file, and
    still verifies cleanly."""
    capsule_dir = tmp_path / "empty.capsule"
    capsule_dir.mkdir()
    sealed_id = CapsuleBuilder.from_manifest(_draft()).seal(capsule_dir=capsule_dir, sealed_by="t")

    assert (capsule_dir / ".checksums").read_bytes() == b""
    result = CapsuleVerifier.verify_integrity(capsule_dir, expected_id=sealed_id)
    assert result["status"] == "pass", result
