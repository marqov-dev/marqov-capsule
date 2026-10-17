"""Spec section 5, Layer 1: the normative ``.checksums`` grammar is byte-exact,
and a reader reports a grammar violation as such, not as a payload mismatch
(#108). Layer 3: ``expected_id`` is parsed and dispatched on, never string
compared (#114).

The legacy YAML-mapping form stays readable: marqov-platform's vendored
builder still writes it (D5 precondition checked 2026-10-03).
"""

import pytest
import yaml
from click.testing import CliRunner

from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.cli.main import cli
from marqov_capsule.verifier import CapsuleVerifier

GATE = {"paradigm": ["gate-based"], "max_qubit_count": 2}


def _sealed(tmp_path, name="cap"):
    d = tmp_path / name
    (d / "payload").mkdir(parents=True)
    (d / "payload" / "results.json").write_text('{"counts": {"00": 1}}')
    (d / "notes.txt").write_text("n\n")
    sealed_id = CapsuleBuilder().start_capsule(name=name, requirements=GATE).seal(d)
    return d, sealed_id


def _variant(text: str, kind: str) -> str:
    lines = text.splitlines(keepends=True)
    if kind == "no-trailing-lf":
        return text.rstrip("\n")
    if kind == "blank-lines":
        return "\n" + text + "\n\n"
    if kind == "sha512-prefix":
        return text.replace("sha256:", "sha512:", 1)
    if kind == "uppercase-hex":
        first = lines[0]
        return first[:7] + first[7:71].upper() + first[71:] + "".join(lines[1:])
    if kind == "bom":
        return "﻿" + text
    if kind == "crlf":
        return text.replace("\n", "\r\n")
    if kind == "single-space-separator":
        return text.replace("  ", " ", 1)
    if kind == "short-digest":
        return text.replace("sha256:" + text[7:71], "sha256:" + text[7:70], 1)
    raise AssertionError(kind)


GRAMMAR_VARIANTS = [
    "no-trailing-lf",
    "blank-lines",
    "sha512-prefix",
    "uppercase-hex",
    "bom",
    "crlf",
    "single-space-separator",
    "short-digest",
]


@pytest.mark.parametrize("kind", GRAMMAR_VARIANTS)
def test_non_normative_framing_is_a_grammar_error_not_a_mismatch(kind, tmp_path):
    d, _ = _sealed(tmp_path)
    text = (d / ".checksums").read_text(encoding="utf-8")
    (d / ".checksums").write_text(_variant(text, kind), encoding="utf-8", newline="")
    result = CapsuleVerifier.verify_checksums(d)
    assert result["status"] == "fail"
    assert "grammar" in result["error"], result
    assert result["mismatched"] == [] and result["missing"] == []


def test_grammar_error_names_the_line(tmp_path):
    d, _ = _sealed(tmp_path)
    text = (d / ".checksums").read_text(encoding="utf-8")
    (d / ".checksums").write_text(_variant(text, "sha512-prefix"), encoding="utf-8")
    result = CapsuleVerifier.verify_checksums(d)
    assert "line 1" in result["error"]
    assert "sha512" in result["error"] or "algorithm" in result["error"]


def test_writer_output_always_passes_the_strict_reader(tmp_path):
    d, _ = _sealed(tmp_path)
    (d / "payload" / "with space.txt").write_text("s")
    (d / "payload" / "100%.txt").write_text("p")
    (d / "payload" / "é.txt").write_text("e")
    CapsuleBuilder().save_checksums(d)
    result = CapsuleVerifier.verify_checksums(d)
    assert result["status"] == "pass", result
    assert result["format"] == "normative"


def test_empty_payload_is_a_zero_byte_file_and_a_lone_newline_is_not(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    (d / ".checksums").write_bytes(b"")
    assert CapsuleVerifier.verify_checksums(d)["status"] == "pass"
    (d / ".checksums").write_bytes(b"\n")
    result = CapsuleVerifier.verify_checksums(d)
    assert result["status"] == "fail"
    assert "grammar" in result["error"]


def test_legacy_yaml_mapping_still_reads_and_is_labelled(tmp_path):
    d, _ = _sealed(tmp_path)
    expected = {}
    for line in (d / ".checksums").read_text(encoding="utf-8").splitlines():
        digest, path = line.split("  ", 1)
        expected[path] = digest
    (d / ".checksums").write_text(yaml.safe_dump(expected, sort_keys=True), encoding="utf-8")
    result = CapsuleVerifier.verify_checksums(d)
    assert result["status"] == "pass", result
    assert result["format"] == "legacy-yaml"


# --- #114: --id is parsed, not string-compared -------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "0" * 64,
        "",
        "MQC:1:" + "a" * 64,
        "mqc:1:" + "A" * 64,
        "mqc:1:" + "a" * 63,
        "sha256:" + "a" * 64,
        "mqc::" + "a" * 64,
    ],
)
def test_malformed_expected_id_is_reported_as_such(bad_id, tmp_path):
    d, _ = _sealed(tmp_path)
    result = CapsuleVerifier.verify_integrity(d, expected_id=bad_id)
    assert result["status"] == "fail"
    assert any("not a capsule ID" in e for e in result["errors"]), result["errors"]
    assert not any("mismatch" in e for e in result["errors"])
    assert result["capsule_id_match"] is False
    assert result["manifest_authenticated"] is False


def test_unsupported_id_version_is_rejected_not_compared(tmp_path):
    d, _ = _sealed(tmp_path)
    result = CapsuleVerifier.verify_integrity(d, expected_id="mqc:2:" + "a" * 64)
    assert result["status"] == "fail"
    assert any("version 2" in e and "not supported" in e for e in result["errors"]), result[
        "errors"
    ]
    assert not any("mismatch" in e for e in result["errors"])


def test_well_formed_mismatch_is_still_a_mismatch(tmp_path):
    d, sealed_id = _sealed(tmp_path)
    other = "mqc:1:" + ("0" if sealed_id[6] != "0" else "1") + sealed_id[7:]
    result = CapsuleVerifier.verify_integrity(d, expected_id=other)
    assert any("capsule ID mismatch" in e for e in result["errors"])
    assert CapsuleVerifier.verify_integrity(d, expected_id=sealed_id)["status"] == "pass"


@pytest.mark.parametrize("command", ["verify", "open"])
def test_cli_malformed_id_is_a_usage_error(command, tmp_path):
    d, _ = _sealed(tmp_path)
    result = CliRunner().invoke(cli, [command, str(d), "--id", "0" * 64])
    assert result.exit_code == 2, result.output
    assert "not a capsule ID" in result.output


@pytest.mark.parametrize("command", ["verify", "open"])
def test_cli_unsupported_id_version_exits_1_with_reason(command, tmp_path):
    d, _ = _sealed(tmp_path)
    result = CliRunner().invoke(cli, [command, str(d), "--id", "mqc:2:" + "a" * 64])
    assert result.exit_code == 1, result.output
    assert "version 2" in result.output and "not supported" in result.output
