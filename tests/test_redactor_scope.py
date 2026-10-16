"""The credential scan skips binary payloads and says so (#98); notebook
findings say which cell they are in (#100).
"""

import json

import pytest
from click.testing import CliRunner

from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.cli.main import cli
from marqov_capsule.redactor import CapsuleRedactor, RedactorError

GATE = {"paradigm": ["gate-based"], "max_qubit_count": 2}
SECRET = "AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n"


def _capsule(tmp_path):
    d = tmp_path / "cap"
    d.mkdir()
    return d


# --- #98 ----------------------------------------------------------------------


def test_file_with_nul_bytes_is_skipped_as_binary_and_reported(tmp_path):
    d = _capsule(tmp_path)
    (d / "state.npy").write_bytes(b"\x93NUMPY\x00\x00" + SECRET.encode() + bytes(64))
    result = CapsuleRedactor(d).scan()
    assert result["findings"] == []
    assert result["skipped_binary"] == ["state.npy"]
    # .capsuleignore reporting stays about .capsuleignore.
    assert result["skipped"] == []


def test_text_file_with_the_same_content_is_still_scanned(tmp_path):
    d = _capsule(tmp_path)
    (d / "notes.txt").write_text("x" * 64 + "\n" + SECRET, encoding="utf-8")
    result = CapsuleRedactor(d).scan()
    assert [f["reason"] for f in result["findings"]] == ["aws_access_key_id"]
    assert result["skipped_binary"] == []


def test_nul_past_the_sniff_window_does_not_hide_a_text_file(tmp_path):
    d = _capsule(tmp_path)
    (d / "log.txt").write_bytes(SECRET.encode() + b"y" * 9000 + b"\x00")
    result = CapsuleRedactor(d).scan()
    assert len(result["findings"]) == 1
    assert result["skipped_binary"] == []


def test_credential_named_binary_is_still_a_finding(tmp_path):
    d = _capsule(tmp_path)
    (d / "client.p12").write_bytes(b"\x00\x01\x02")
    result = CapsuleRedactor(d).scan()
    assert [f["reason"] for f in result["findings"]] == ["credential_file"]


@pytest.mark.parametrize("flags", [[], ["--dry-run"]], ids=["seal", "dry-run"])
def test_cli_seal_reports_binary_files_it_did_not_scan(flags, tmp_path):
    d = _capsule(tmp_path)
    (d / "state.npy").write_bytes(b"\x00" * 32)
    CapsuleBuilder().start_capsule(name="c", requirements=GATE).save_capsule(d)
    text = CliRunner().invoke(cli, ["seal", str(d)] + flags)
    assert text.exit_code == 0, text.output
    assert "state.npy" in text.output and "binary" in text.output
    d2 = tmp_path / "cap2"
    d2.mkdir()
    (d2 / "state.npy").write_bytes(b"\x00" * 32)
    CapsuleBuilder().start_capsule(name="c", requirements=GATE).save_capsule(d2)
    as_json = CliRunner().invoke(cli, ["seal", "--json", str(d2)] + flags)
    assert json.loads(as_json.output)["skipped_binary"] == ["state.npy"]


# --- #100 ---------------------------------------------------------------------


def _notebook(d):
    nb = {
        "cells": [
            {"cell_type": "code", "source": ["a=1\n"] * 50, "outputs": []},
            {
                "cell_type": "code",
                "source": ["x=1\n", SECRET],
                "outputs": [
                    {"output_type": "stream", "text": ["ok\n"]},
                    {"output_type": "stream", "text": ["a\n", "b\n", SECRET]},
                ],
            },
        ]
    }
    (d / "n.ipynb").write_text(json.dumps(nb), encoding="utf-8")


def test_notebook_findings_carry_cell_index_and_location(tmp_path):
    d = _capsule(tmp_path)
    _notebook(d)
    findings = CapsuleRedactor(d).scan()["findings"]
    assert [(f["cell"], f["location"], f["line"]) for f in findings] == [
        (1, "source", 2),
        (1, "output[1]", 3),
    ]


def test_plain_file_findings_have_no_cell(tmp_path):
    d = _capsule(tmp_path)
    (d / "a.py").write_text(SECRET, encoding="utf-8")
    (finding,) = CapsuleRedactor(d).scan()["findings"]
    assert "cell" not in finding


def test_blocked_seal_message_locates_the_cell(tmp_path):
    d = _capsule(tmp_path)
    _notebook(d)
    with pytest.raises(RedactorError, match=r"n\.ipynb:cell 1:line 2 \(aws_access_key_id\)"):
        CapsuleRedactor(d).scan_and_raise()


def test_cli_dry_run_locates_the_cell(tmp_path):
    d = _capsule(tmp_path)
    _notebook(d)
    CapsuleBuilder().start_capsule(name="c", requirements=GATE).save_capsule(d)
    result = CliRunner().invoke(cli, ["seal", "--dry-run", str(d)])
    assert "n.ipynb:cell 1:line 2" in result.output
    assert "n.ipynb:cell 1:output[1]:line 3" in result.output
