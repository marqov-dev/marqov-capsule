"""A valid digest chain must not hide an export's missing authored content."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from marqov_capsule import CapsuleBuilder, CapsuleVerifier
from marqov_capsule.archive import pack_capsule

SCRIPT = Path(__file__).parents[1] / "tools/export_completeness/check.py"
spec = importlib.util.spec_from_file_location("export_acceptance", SCRIPT)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)

FILES = {
    "source.qasm": ("source", b"source snapshot\n"),
    "counts.json": ("result", b'{"00":500,"11":500}\n'),
    "config.json": ("configuration", b'{"shots":1000}\n'),
    "report.md": ("report", b"# Authored Report\n"),
    "figure.bin": ("figure", b"illustrative figure bytes\x00\xff"),
}


def inventory():
    return {
        "version": 1,
        "required_roles": ["source", "result", "configuration", "report", "figure"],
        "files": [
            {
                "path": name,
                "role": role,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
            for name, (role, data) in FILES.items()
        ],
    }


def seal(tmp_path, files=None):
    directory = tmp_path / "record"
    directory.mkdir()
    for name, (_, data) in (FILES if files is None else files).items():
        (directory / name).write_bytes(data)
    ident = (
        CapsuleBuilder()
        .start_capsule(
            name="acceptance", requirements={"paradigm": ["gate-based"], "max_qubit_count": 2}
        )
        .seal(directory)
    )
    return directory, ident


def test_intact_record_passes_directory_and_archive(tmp_path):
    directory, ident = seal(tmp_path)
    expected = inventory()
    assert acceptance.check_export(directory, expected, ident, tmp_path)["status"] == "pass"
    archive = pack_capsule(directory, tmp_path / "export.capsule")
    result = acceptance.check_export(archive, expected, ident, tmp_path)
    assert result["status"] == "pass"
    assert result["integrity"]["manifest_authenticated"]
    assert result["schema"]["valid"]
    assert not list(tmp_path.glob("capsule-acceptance-*"))


def test_report_omitted_before_sealing_passes_integrity_but_not_completeness(tmp_path):
    directory, ident = seal(tmp_path, {k: v for k, v in FILES.items() if k != "report.md"})
    assert CapsuleVerifier.verify_integrity(directory, expected_id=ident)["status"] == "pass"
    archive = pack_capsule(directory, tmp_path / "export.capsule")
    result = acceptance.check_export(archive, inventory(), ident, tmp_path)
    assert result["integrity"]["status"] == "pass"
    assert result["status"] == "fail"
    assert result["completeness"]["missing"] == ["report.md"]
    assert result["completeness"]["unsatisfied_roles"] == ["report"]


def test_source_replaced_before_sealing_fails_external_hash(tmp_path):
    files = dict(FILES, **{"source.qasm": ("source", b"editable replacement\n")})
    directory, ident = seal(tmp_path, files)
    result = acceptance.check_export(directory, inventory(), ident, tmp_path)
    assert result["integrity"]["status"] == "pass"
    assert result["completeness"]["sha256_mismatches"] == ["source.qasm"]
    assert result["completeness"]["unsatisfied_roles"] == ["source"]
    assert result["status"] == "fail"


def test_unexpected_sealed_file_requires_explicit_external_policy(tmp_path):
    files = dict(FILES, **{"extra.txt": ("other", b"extra\n")})
    directory, ident = seal(tmp_path, files)
    expected = inventory()
    result = acceptance.check_export(directory, expected, ident, tmp_path)
    assert result["status"] == "fail"
    assert result["completeness"]["unexpected"] == ["extra.txt"]
    expected["allow_extra"] = True
    assert acceptance.check_export(directory, expected, ident, tmp_path)["status"] == "pass"


def test_wrong_id_and_post_seal_tamper_stop_before_completeness(tmp_path):
    directory, ident = seal(tmp_path)
    wrong = "mqc:1:" + "0" * 64
    result = acceptance.check_export(directory, inventory(), wrong, tmp_path)
    assert result["status"] == "fail" and result["completeness"] is None
    (directory / "report.md").write_bytes(b"changed")
    result = acceptance.check_export(directory, inventory(), ident, tmp_path)
    assert result["integrity"]["status"] == "fail" and result["completeness"] is None


def test_invalid_schema_cannot_pass_completeness(tmp_path):
    directory = tmp_path / "invalid-schema"
    directory.mkdir()
    (directory / "report.md").write_bytes(FILES["report.md"][1])
    ident = (
        CapsuleBuilder()
        .start_capsule(
            name="invalid", requirements={"paradigm": ["classical"], "max_qubit_count": -1}
        )
        .seal(directory, validate=False)
    )
    expected = {
        "version": 1,
        "required_roles": ["report"],
        "files": [{"path": "report.md", "role": "report"}],
    }
    result = acceptance.check_export(directory, expected, ident, tmp_path)
    assert result["integrity"]["status"] == "pass"
    assert result["schema"]["valid"] is False
    assert result["status"] == "fail" and result["completeness"] is None


def test_presence_only_checks_are_disclosed(tmp_path):
    directory, ident = seal(tmp_path)
    expected = inventory()
    for entry in expected["files"]:
        del entry["sha256"]
    result = acceptance.check_export(directory, expected, ident, tmp_path)
    assert result["status"] == "pass"
    assert result["completeness"]["presence_only_files"] == 5
    assert result["completeness"]["present_hash_pinned_files"] == 0


@pytest.mark.parametrize(
    "path",
    [
        ".",
        "../report.md",
        "/report.md",
        "C:/report.md",
        "a\\report.md",
        "a//b",
        "a/./b",
        "a/../b",
        "a/",
        "capsule.yaml",
        ".checksums",
        "bad\nname",
        "cafe\u0301.md",
    ],
)
def test_inventory_cannot_use_unsafe_or_ambiguous_paths(path):
    expected = inventory()
    expected["files"][0]["path"] = path
    with pytest.raises(ValueError):
        acceptance.validate_inventory(expected)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(version=True),
        lambda d: d.update(allow_extra="false"),
        lambda d: d.update(required_roles=[]),
        lambda d: d.update(required_roles=["report", "report"]),
        lambda d: d.update(required_roles=["unknown"]),
        lambda d: d.update(files=[]),
        lambda d: d["files"].append(d["files"][0].copy()),
        lambda d: d["files"][0].update(sha256="A" * 64),
        lambda d: d["files"][0].update(size_bytes=True),
        lambda d: d["files"][0].update(extra="typo"),
        lambda d: d.update(unexpected="typo"),
        lambda d: d.update(files=d["files"][:1]),
    ],
)
def test_malformed_inventory_is_rejected(change):
    expected = inventory()
    change(expected)
    with pytest.raises(ValueError):
        acceptance.validate_inventory(expected)


def test_inventory_file_rejects_duplicate_keys_and_oversize(tmp_path):
    path = tmp_path / "expected.json"
    path.write_text('{"version":1,"version":2}')
    with pytest.raises(ValueError, match="duplicate"):
        acceptance.load_inventory(path)
    path.write_bytes(b" " * (acceptance.MAX_INVENTORY_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds"):
        acceptance.load_inventory(path)


def test_cli_reports_failure_for_valid_but_incomplete_export(tmp_path):
    directory, ident = seal(tmp_path, {k: v for k, v in FILES.items() if k != "report.md"})
    expected = tmp_path / "external.json"
    raw = json.dumps(inventory()).encode()
    expected.write_bytes(raw)
    # Editable CI installations cannot exercise the installed-only CLI; use the
    # callable path there. The release consumer smoke command is run separately.
    import importlib.metadata

    direct = json.loads(
        importlib.metadata.distribution("marqov-capsule").read_text("direct_url.json") or "{}"
    )
    if direct.get("dir_info", {}).get("editable"):
        pytest.skip("installed-only CLI is covered by release consumer acceptance")
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCRIPT),
            str(directory),
            str(expected),
            "--id",
            ident,
            "--scratch-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1, run.stderr
    result = json.loads(run.stdout)
    assert result["integrity"]["status"] == "pass"
    assert result["completeness"]["missing"] == ["report.md"]
    assert result["inventory_sha256"] == hashlib.sha256(raw).hexdigest()


def test_cli_clean_errors_for_malformed_input(tmp_path):
    import importlib.metadata

    direct = json.loads(
        importlib.metadata.distribution("marqov-capsule").read_text("direct_url.json") or "{}"
    )
    if direct.get("dir_info", {}).get("editable"):
        pytest.skip("installed-only CLI is covered by release consumer acceptance")
    archive = tmp_path / "bad.capsule"
    archive.write_bytes(b"not an archive")
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps(inventory()))
    args = [
        sys.executable,
        "-I",
        str(SCRIPT),
        str(archive),
        str(expected),
        "--id",
        "mqc:1:" + "0" * 64,
        "--scratch-dir",
        str(tmp_path),
    ]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 1 and "Traceback" not in result.stderr
    assert json.loads(result.stdout)["stage"] == "export"
    expected.write_text("[" * 3000 + "0" + "]" * 3000)
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 2 and "Traceback" not in result.stderr
    assert json.loads(result.stdout)["stage"] == "inventory"
