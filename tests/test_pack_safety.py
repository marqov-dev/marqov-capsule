"""``pack`` refuses to replace an existing archive (#106) or to archive a draft;
the archive layer bounds how much it will inflate (review finding, 2026-10-02).
"""
import gzip
import io
import json
import tarfile

import pytest
from click.testing import CliRunner

from marqov_capsule import archive as archive_mod
from marqov_capsule.archive import pack_capsule, payload_digest, unpack_capsule
from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.cli.main import cli

GATE = {"paradigm": ["gate-based"], "max_qubit_count": 2}


def _sealed(tmp_path, name="cap"):
    d = tmp_path / name
    d.mkdir()
    (d / "payload.txt").write_text(name + "\n")
    CapsuleBuilder().start_capsule(name=name, requirements=GATE).seal(d)
    return d


# --- #106 -------------------------------------------------------------------

def test_pack_refuses_to_overwrite_an_existing_archive(tmp_path):
    first = _sealed(tmp_path, "one")
    second = _sealed(tmp_path, "two")
    target = tmp_path / "x.capsule"
    pack_capsule(first, target)
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        pack_capsule(second, target)
    assert target.read_bytes() == original


def test_pack_overwrite_flag_replaces_the_archive(tmp_path):
    first = _sealed(tmp_path, "one")
    second = _sealed(tmp_path, "two")
    target = tmp_path / "x.capsule"
    pack_capsule(first, target)
    pack_capsule(second, target, overwrite=True)
    assert payload_digest(target) == payload_digest(second)


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_cli_pack_onto_existing_path_exits_1_and_keeps_bytes(as_json, tmp_path):
    first = _sealed(tmp_path, "one")
    second = _sealed(tmp_path, "two")
    target = tmp_path / "x.capsule"
    pack_capsule(first, target)
    original = target.read_bytes()
    args = ["pack", str(second), "-o", str(target)] + (["--json"] if as_json else [])
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 1, result.output
    assert "exists" in result.output and "--force" in result.output
    assert target.read_bytes() == original
    if as_json:
        assert json.loads(result.output)["status"] == "error"


def test_cli_pack_force_replaces(tmp_path):
    first = _sealed(tmp_path, "one")
    second = _sealed(tmp_path, "two")
    target = tmp_path / "x.capsule"
    pack_capsule(first, target)
    result = CliRunner().invoke(cli, ["pack", str(second), "-o", str(target), "--force"])
    assert result.exit_code == 0, result.output
    assert payload_digest(target) == payload_digest(second)


# --- pack refuses drafts ------------------------------------------------------

def test_pack_refuses_a_draft_with_a_stale_checksums_file(tmp_path):
    d = tmp_path / "draft"
    d.mkdir()
    (d / "payload.txt").write_text("x\n")
    (d / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: d\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\ntask_executions: []\n")
    CapsuleBuilder().save_checksums(d)
    with pytest.raises(ValueError, match="not sealed"):
        pack_capsule(d, tmp_path / "x.capsule")
    assert not (tmp_path / "x.capsule").exists()
    result = CliRunner().invoke(cli, ["pack", str(d), "-o", str(tmp_path / "x.capsule")])
    assert result.exit_code == 1, result.output
    assert "not sealed" in result.output


def test_pack_accepts_an_archived_capsule(tmp_path):
    d = _sealed(tmp_path)
    text = (d / "capsule.yaml").read_text(encoding="utf-8")
    (d / "capsule.yaml").write_text(text.replace("lifecycle_state: sealed", "lifecycle_state: archived"), encoding="utf-8")
    assert pack_capsule(d, tmp_path / "a.capsule").is_file()


# --- inflation caps ------------------------------------------------------------

def _bomb(member_name: str, size: int, extra=()) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        manifest = b"version: '1.0.0'\nname: b\nlifecycle_state: sealed\n"
        info = tarfile.TarInfo("cap/capsule.yaml")
        info.size = len(manifest)
        tf.addfile(info, io.BytesIO(manifest))
        for name, data in extra:
            i = tarfile.TarInfo(name)
            i.size = len(data)
            tf.addfile(i, io.BytesIO(data))
        big = tarfile.TarInfo(member_name)
        big.size = size
        tf.addfile(big, io.BytesIO(bytes(size)))
    return gzip.compress(buf.getvalue(), mtime=0)


def test_unpack_refuses_an_archive_over_the_inflation_cap(tmp_path):
    archive = tmp_path / "bomb.capsule"
    archive.write_bytes(_bomb("cap/zeros.bin", 3 * 1024 * 1024, extra=[("cap/.checksums", b"")]))
    assert archive.stat().st_size < 64 * 1024  # it really is a bomb
    with pytest.raises(ValueError, match="exceeds"):
        unpack_capsule(archive, tmp_path / "out", max_bytes=1024 * 1024)
    assert not (tmp_path / "out" / "cap").exists()


def test_unpack_default_cap_is_generous_and_documented():
    assert archive_mod.MAX_UNPACK_BYTES >= 1024 ** 3


def test_payload_digest_refuses_an_oversized_checksums_member(tmp_path):
    archive = tmp_path / "bigsums.capsule"
    archive.write_bytes(_bomb("cap/.checksums", archive_mod.MAX_CHECKSUMS_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds"):
        payload_digest(archive)


@pytest.mark.parametrize("command", ["verify", "unpack"])
def test_cli_exits_1_cleanly_on_oversized_checksums_member(command, tmp_path):
    archive = tmp_path / "bigsums.capsule"
    archive.write_bytes(_bomb("cap/.checksums", archive_mod.MAX_CHECKSUMS_BYTES + 1))
    args = [command, str(archive)] + (["-o", str(tmp_path / "out")] if command == "unpack" else [])
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(result.exception)
