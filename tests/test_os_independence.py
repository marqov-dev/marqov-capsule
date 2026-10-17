"""The package claims "OS Independent". These pin the two things that broke
that on Windows by reading: native path separators in capsule-relative paths
(#113) and platform-default text encodings (#103). The Windows and macOS CI
legs are the end-to-end check; these fail on any OS.
"""

import json
import re
import warnings
from pathlib import Path

import pytest
from click.testing import CliRunner

from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.cli.main import cli
from marqov_capsule.verifier import CapsuleVerifier

SRC = Path(__file__).parent.parent / "src" / "marqov_capsule"
GATE = {"paradigm": ["gate-based"], "max_qubit_count": 2}


def _source_lines():
    for path in sorted(SRC.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.lstrip().startswith("#"):
                yield f"{path.relative_to(SRC).as_posix()}:{number}", line


def test_no_capsule_relative_path_uses_the_native_separator():
    offenders = [
        where for where, line in _source_lines() if re.search(r"str\([^()]*\.relative_to\(", line)
    ]
    assert offenders == [], "use .as_posix(), not str(), for capsule-relative paths"


def test_every_text_read_and_write_names_its_encoding():
    offenders = [
        where
        for where, line in _source_lines()
        if re.search(r"\.(read_text|write_text)\(", line) and "encoding=" not in line
    ]
    assert offenders == []


def test_no_text_mode_open_without_an_encoding():
    offenders = [
        where
        for where, line in _source_lines()
        if re.search(r"(?<![.\w`])open\(", line)
        and not re.search(r"""["'][rwxa]?b[rwxa+]?["']|encoding=|"wb" if""", line)
    ]
    assert offenders == []


def test_nested_payload_verifies_with_no_extra_files(tmp_path):
    d = tmp_path / "cap"
    (d / "payload" / "deep").mkdir(parents=True)
    (d / "payload" / "deep" / "results.json").write_text("{}", encoding="utf-8")
    CapsuleBuilder().start_capsule(name="c", requirements=GATE).seal(d)
    result = CapsuleVerifier.verify_checksums(d)
    assert result["status"] == "pass" and result["extra"] == []
    assert list(result["files"]) == ["payload/deep/results.json"]


def test_checksums_and_manifest_are_written_with_lf_only(tmp_path):
    d = tmp_path / "cap"
    d.mkdir()
    (d / "a.txt").write_text("a", encoding="utf-8")
    (d / "b.txt").write_text("b", encoding="utf-8")
    CapsuleBuilder().start_capsule(name="c", requirements=GATE).seal(d)
    assert b"\r" not in (d / ".checksums").read_bytes()
    assert b"\r" not in (d / "capsule.yaml").read_bytes()


def test_non_ascii_name_round_trips_through_init_seal_verify(tmp_path):
    d = tmp_path / "cap"
    runner = CliRunner()
    assert runner.invoke(cli, ["init", str(d), "--name", "café"]).exit_code == 0
    assert b"\r" not in (d / "capsule.yaml").read_bytes()
    (d / "données.txt").write_text("x", encoding="utf-8")
    sealed = runner.invoke(cli, ["seal", "--json", str(d)])
    assert sealed.exit_code == 0, sealed.output
    capsule_id = json.loads(sealed.output)["capsule_id"]
    verified = runner.invoke(cli, ["verify", str(d), "--id", capsule_id])
    assert verified.exit_code == 0, verified.output


def test_compare_reports_a_non_utf8_counts_file_cleanly(tmp_path):
    bad = tmp_path / "ref.json"
    bad.write_bytes(b'{"00": 1, "caf\xe9": 2}')
    good = tmp_path / "new.json"
    good.write_text('{"00": 1}', encoding="utf-8")
    result = CliRunner().invoke(cli, ["compare", str(bad), str(good)])
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )
    assert result.exit_code != 0
    assert "UTF-8" in result.output


# --- #102: the verifier does not pretend to use a schema path ------------------


def test_verifier_schema_path_is_deprecated_and_not_loaded(tmp_path):
    schema = tmp_path / "schema.json"
    schema.write_text("{not json", encoding="utf-8")
    with pytest.warns(DeprecationWarning, match="schema_path"):
        verifier = CapsuleVerifier(schema_path=schema)
    assert not hasattr(verifier, "schema")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        CapsuleVerifier()
