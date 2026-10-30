"""The manifest writer must quote exactly what the manifest loader would type (#92).

PyYAML's emitter decides whether a plain scalar needs quoting using the YAML
1.1 resolvers; the project's loader types scalars with the YAML 1.2 / JSON
profile. Where the two disagree (exponent-shaped strings such as ``1e5``), a
string is written bare and read back as a float, so the ID the sealer
publishes cannot be recomputed from the file it wrote.

Also covers #121: a seal that fails must leave the on-disk draft untouched.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marqov_capsule._canonical import (
    compute_capsule_id,
    dump_manifest_yaml,
    load_manifest_yaml,
)
from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.cli.main import cli
from marqov_capsule.redactor import RedactorError
from marqov_capsule.validator import CapsuleValidator
from marqov_capsule.verifier import CapsuleVerifier

REQUIREMENTS = {"paradigm": ["gate-based"], "max_qubit_count": 2}

# Scalars whose plain spelling is typed differently by YAML 1.1 and YAML 1.2,
# or by YAML and JSON. Every one of these must survive a write/read cycle as
# the exact Python value it started as.
AMBIGUOUS_STRINGS = [
    "1e5",
    "1E5",
    "1e+5",
    "1e-3",
    "12e3",
    "0e0",
    "-1e5",
    "+1e5",
    "1e05",
    "007",
    "0x1f",
    "0o17",
    "1_000",
    "1:30",
    ".5",
    "5.",
    "+5",
    "-0",
    "yes",
    "no",
    "on",
    "off",
    "y",
    "n",
    "true",
    "True",
    "false",
    "null",
    "Null",
    "~",
    "",
    "Inf",
    ".inf",
    "-.inf",
    "NaN",
    ".nan",
    "1.0.0",
    "2026-06-11T00:00:00Z",
    "2026-06-11",
    "12:30:00",
    " leading",
    "trailing ",
    "a: b",
    "- item",
    "#comment",
    "{}",
    "[]",
    "é",
    "naïve",
]

NON_STRING_VALUES = [
    0,
    1,
    -1,
    100000,
    2**53 - 1,
    0.5,
    1e5,
    1e-3,
    -0.0,
    True,
    False,
    None,
    [1, "1", 1.0],
    {"k": "1e5"},
]


@pytest.mark.parametrize("value", AMBIGUOUS_STRINGS, ids=repr)
def test_string_value_round_trips(value):
    assert load_manifest_yaml(dump_manifest_yaml({"k": value}))["k"] == value


@pytest.mark.parametrize("value", AMBIGUOUS_STRINGS, ids=repr)
def test_string_key_round_trips(value):
    loaded = load_manifest_yaml(dump_manifest_yaml({value: "v"}))
    assert list(loaded) == [value]


@pytest.mark.parametrize("value", NON_STRING_VALUES, ids=repr)
def test_typed_value_round_trips(value):
    loaded = load_manifest_yaml(dump_manifest_yaml({"k": value}))["k"]
    assert loaded == value
    assert type(loaded) is type(value)


def test_dump_output_is_a_yaml_12_document_other_readers_agree_on():
    # A 1.1 reader (plain SafeLoader) and the 1.2 loader must both see the
    # string — the writer quotes for the union of the two profiles.
    import yaml

    text = dump_manifest_yaml({"name": "1e5", "flag": "yes", "oct": "007"})
    assert yaml.safe_load(text) == {"name": "1e5", "flag": "yes", "oct": "007"}
    assert load_manifest_yaml(text) == {"name": "1e5", "flag": "yes", "oct": "007"}


def test_sealed_id_is_reproducible_from_disk_for_exponent_shaped_name(tmp_path):
    capsule_dir = tmp_path / "cap"
    capsule_dir.mkdir()
    (capsule_dir / "payload.txt").write_text("x\n")
    builder = CapsuleBuilder().start_capsule(
        name="1e5", parameters={"rate": "1e-3"}, requirements=REQUIREMENTS
    )
    sealed_id = builder.seal(capsule_dir)

    on_disk = load_manifest_yaml((capsule_dir / "capsule.yaml").read_text(encoding="utf-8"))
    assert on_disk["name"] == "1e5"
    assert on_disk["parameters"]["rate"] == "1e-3"
    assert compute_capsule_id(on_disk) == sealed_id
    assert CapsuleVerifier.verify_integrity(capsule_dir, expected_id=sealed_id)["status"] == "pass"
    assert CapsuleValidator.validate_file(capsule_dir / "capsule.yaml")["valid"] is True


def test_seal_returns_the_id_recomputed_from_written_bytes(tmp_path):
    """The published ID must be the one any verifier recomputes from the file."""
    capsule_dir = tmp_path / "cap"
    capsule_dir.mkdir()
    builder = CapsuleBuilder().start_capsule(name="demo", requirements=REQUIREMENTS)
    sealed_id = builder.seal(capsule_dir)
    recomputed = compute_capsule_id(
        load_manifest_yaml((capsule_dir / "capsule.yaml").read_text(encoding="utf-8"))
    )
    assert recomputed == sealed_id


def test_init_name_with_exponent_shape_stays_a_string(tmp_path):
    capsule_dir = tmp_path / "cap"
    result = CliRunner().invoke(cli, ["init", str(capsule_dir), "--name", "1e-3"])
    assert result.exit_code == 0, result.output
    manifest = load_manifest_yaml((capsule_dir / "capsule.yaml").read_text(encoding="utf-8"))
    assert manifest["name"] == "1e-3"
    result = CliRunner().invoke(cli, ["validate", str(capsule_dir)])
    assert result.exit_code == 0, result.output


def test_to_yaml_round_trips_ambiguous_strings():
    builder = CapsuleBuilder().start_capsule(name="1e5", requirements=REQUIREMENTS)
    assert load_manifest_yaml(builder.to_yaml())["name"] == "1e5"


# --- #121: a failed seal must not destroy the draft -------------------------


def _draft_with_secret(capsule_dir: Path) -> bytes:
    capsule_dir.mkdir()
    draft = (
        "# hand-written draft: this comment must survive a failed seal\n"
        "version: '1.0.0'\n"
        "name: demo\n"
        "lifecycle_state: draft\n"
        "requirements:\n"
        "  paradigm: [gate-based]\n"
        "  max_qubit_count: 2\n"
        "task_executions: []\n"
    )
    # Bytes, so the draft is LF on disk on every OS and the comparison is exact.
    (capsule_dir / "capsule.yaml").write_bytes(draft.encode("utf-8"))
    return draft.encode("utf-8")


def test_seal_that_cannot_canonicalise_leaves_draft_bytes_unchanged(tmp_path):
    capsule_dir = tmp_path / "cap"
    original = _draft_with_secret(capsule_dir)
    builder = CapsuleBuilder().start_capsule(
        name="x", parameters={"big": 2**53}, requirements=REQUIREMENTS
    )
    with pytest.raises(ValueError):
        builder.seal(capsule_dir)
    assert (capsule_dir / "capsule.yaml").read_bytes() == original
    assert not (capsule_dir / ".checksums").exists()


def test_seal_blocked_by_redactor_leaves_draft_bytes_unchanged(tmp_path):
    capsule_dir = tmp_path / "cap"
    original = _draft_with_secret(capsule_dir)
    (capsule_dir / "run.py").write_text(
        'IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n', encoding="utf-8"
    )
    builder = CapsuleBuilder.from_manifest(load_manifest_yaml(original.decode("utf-8")))
    with pytest.raises(RedactorError):
        builder.seal(capsule_dir)
    assert (capsule_dir / "capsule.yaml").read_bytes() == original


def test_cli_seal_blocked_leaves_draft_bytes_unchanged(tmp_path):
    capsule_dir = tmp_path / "cap"
    original = _draft_with_secret(capsule_dir)
    (capsule_dir / "run.py").write_text(
        'IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n', encoding="utf-8"
    )
    result = CliRunner().invoke(cli, ["seal", str(capsule_dir)])
    assert result.exit_code == 1, result.output
    assert (capsule_dir / "capsule.yaml").read_bytes() == original


def test_manifest_only_secret_is_still_caught_without_pre_writing_the_draft(tmp_path):
    """#57 regression: the in-memory manifest must be scanned even though the
    draft is no longer written to disk before the credential scan."""
    capsule_dir = tmp_path / "cap"
    capsule_dir.mkdir()
    builder = CapsuleBuilder().start_capsule(
        name="demo",
        parameters={"token": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
        requirements=REQUIREMENTS,
    )
    with pytest.raises(RedactorError):
        builder.seal(capsule_dir)
    # Nothing was sealed: no manifest, no checksums.
    assert not (capsule_dir / "capsule.yaml").exists()
    assert not (capsule_dir / ".checksums").exists()


def test_save_capsule_is_atomic_no_partial_file_on_failure(tmp_path, monkeypatch):
    capsule_dir = tmp_path / "cap"
    original = _draft_with_secret(capsule_dir)
    builder = CapsuleBuilder.from_manifest(load_manifest_yaml(original.decode("utf-8")))

    import marqov_capsule.builder as builder_module

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(builder_module.os, "replace", boom)
    with pytest.raises(OSError):
        builder.save_capsule(capsule_dir / "capsule.yaml")
    assert (capsule_dir / "capsule.yaml").read_bytes() == original
    assert [p.name for p in capsule_dir.iterdir()] == ["capsule.yaml"], "no temp file left behind"


def test_cli_seal_json_round_trip_id_matches_verify(tmp_path):
    capsule_dir = tmp_path / "cap"
    CliRunner().invoke(cli, ["init", str(capsule_dir), "--name", "1e5"])
    (capsule_dir / "p.txt").write_text("x\n")
    sealed = CliRunner().invoke(cli, ["seal", "--json", str(capsule_dir)])
    assert sealed.exit_code == 0, sealed.output
    sealed_id = json.loads(sealed.output)["capsule_id"]
    verified = CliRunner().invoke(cli, ["verify", "--id", sealed_id, str(capsule_dir)])
    assert verified.exit_code == 0, verified.output
