"""The archive layer on malformed or crafted input: documented exceptions only,
clean CLI exits, and the right ``.checksums`` member (#124, #96, #94).
"""

import gzip
import io
import json
import tarfile

import pytest
from click.testing import CliRunner

from marqov_capsule.archive import pack_capsule, payload_digest, unpack_capsule
from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.cli.main import cli

REQUIREMENTS = {"paradigm": ["gate-based"], "max_qubit_count": 2}


def _sealed(tmp_path, name="cap"):
    d = tmp_path / name
    d.mkdir()
    (d / "payload.txt").write_text("x\n")
    CapsuleBuilder().start_capsule(name=name, requirements=REQUIREMENTS).seal(d)
    return d


def _tar_gz(members) -> bytes:
    """Build a gzipped tar from (TarInfo, bytes|None) pairs."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for info, data in members:
            if data is not None:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
            else:
                tf.addfile(info)
    return gzip.compress(buf.getvalue(), mtime=0)


def _info(name, typeflag=tarfile.REGTYPE, linkname=""):
    info = tarfile.TarInfo(name)
    info.type = typeflag
    info.linkname = linkname
    info.mode = 0o644
    return info


MANIFEST = b"version: '1.0.0'\nname: t\nlifecycle_state: sealed\n"


def _archive_with_checksums_member(info, data=None) -> bytes:
    return _tar_gz(
        [
            (_info("cap", tarfile.DIRTYPE), None),
            (_info("cap/capsule.yaml"), MANIFEST),
            (info, data),
        ]
    )


# --- #124: documented exception types only -----------------------------------


def test_truncated_gzip_is_a_value_error_from_unpack(tmp_path):
    archive = pack_capsule(_sealed(tmp_path), tmp_path / "a.capsule")
    data = archive.read_bytes()
    truncated = tmp_path / "t.capsule"
    truncated.write_bytes(data[: len(data) // 2])
    with pytest.raises(ValueError, match="truncated|corrupt"):
        unpack_capsule(truncated, tmp_path / "out")


def test_truncated_gzip_is_a_value_error_from_payload_digest(tmp_path):
    archive = pack_capsule(_sealed(tmp_path), tmp_path / "a.capsule")
    data = archive.read_bytes()
    truncated = tmp_path / "t.capsule"
    truncated.write_bytes(data[: len(data) // 2])
    with pytest.raises(ValueError, match="truncated|corrupt"):
        payload_digest(truncated)


@pytest.mark.parametrize(
    "member",
    [
        pytest.param(
            _info("cap/.checksums", tarfile.SYMTYPE, "../../etc/passwd"), id="symlink-outside"
        ),
        pytest.param(_info("cap/.checksums", tarfile.SYMTYPE, "missing"), id="symlink-dangling"),
        pytest.param(_info("cap/.checksums", tarfile.SYMTYPE, ".checksums"), id="symlink-self"),
        pytest.param(_info("cap/.checksums", tarfile.LNKTYPE, "cap/capsule.yaml"), id="hardlink"),
        pytest.param(_info("cap/.checksums", tarfile.DIRTYPE), id="directory"),
    ],
)
def test_non_regular_checksums_member_is_a_value_error(member, tmp_path):
    archive = tmp_path / "bad.capsule"
    archive.write_bytes(_archive_with_checksums_member(member))
    with pytest.raises(ValueError, match="regular file"):
        payload_digest(archive)


@pytest.mark.parametrize(
    "member",
    [
        pytest.param(_info("cap/.checksums", tarfile.SYMTYPE, ".checksums"), id="symlink-self"),
        pytest.param(_info("cap/.checksums", tarfile.LNKTYPE, "cap/capsule.yaml"), id="hardlink"),
        pytest.param(_info("cap/.checksums", tarfile.DIRTYPE), id="directory"),
    ],
)
@pytest.mark.parametrize("command", ["verify", "unpack"])
def test_cli_exits_1_cleanly_on_crafted_checksums_member(command, member, tmp_path):
    archive = tmp_path / "bad.capsule"
    archive.write_bytes(_archive_with_checksums_member(member))
    args = [command, str(archive)]
    if command == "unpack":
        args += ["-o", str(tmp_path / "out")]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )


@pytest.mark.parametrize("command", ["verify", "unpack"])
def test_cli_exits_1_cleanly_on_truncated_archive(command, tmp_path):
    archive = pack_capsule(_sealed(tmp_path), tmp_path / "a.capsule")
    data = archive.read_bytes()
    truncated = tmp_path / "t.capsule"
    truncated.write_bytes(data[: len(data) // 2])
    args = [command, str(truncated)]
    if command == "unpack":
        args += ["-o", str(tmp_path / "out")]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )


# --- #96: unpack/pack error handling ----------------------------------------


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_unpack_of_non_archive_exits_1_cleanly(as_json, tmp_path):
    bogus = tmp_path / "notatar.capsule"
    bogus.write_text("nope\n")
    args = ["unpack", str(bogus), "-o", str(tmp_path / "out")] + (["--json"] if as_json else [])
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )
    if as_json:
        assert json.loads(result.output)["status"] == "error"
    else:
        assert "Error:" in result.output


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_pack_output_over_capsule_dir_exits_1_cleanly(as_json, tmp_path):
    d = _sealed(tmp_path)
    args = ["pack", str(d), "-o", str(d)] + (["--json"] if as_json else [])
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )
    if as_json:
        assert json.loads(result.output)["status"] == "error"
    else:
        assert "Refusing" in result.output
    assert d.is_dir() and (d / "capsule.yaml").is_file()


@pytest.mark.parametrize("as_json", [False, True], ids=["text", "json"])
def test_pack_into_unwritable_location_exits_1_cleanly(as_json, tmp_path):
    d = _sealed(tmp_path)
    target = tmp_path / "no-such-dir" / "x.capsule"
    args = ["pack", str(d), "-o", str(target)] + (["--json"] if as_json else [])
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )


# --- #94: the root .checksums, not the first one in byte order ---------------


def test_payload_digest_of_archive_uses_root_checksums(tmp_path):
    d = tmp_path / "cap"
    (d / "-data").mkdir(parents=True)
    (d / "-data" / ".checksums").write_text("decoy\n")
    (d / "payload.txt").write_text("x\n")
    CapsuleBuilder().start_capsule(name="cap", requirements=REQUIREMENTS).seal(d)
    archive = pack_capsule(d, tmp_path / "x.capsule")
    assert payload_digest(archive) == payload_digest(d)


def test_pack_cli_reports_root_payload_digest(tmp_path):
    d = tmp_path / "cap"
    (d / "-data").mkdir(parents=True)
    (d / "-data" / ".checksums").write_text("decoy\n")
    CapsuleBuilder().start_capsule(name="cap", requirements=REQUIREMENTS).seal(d)
    result = CliRunner().invoke(cli, ["pack", "--json", str(d), "-o", str(tmp_path / "x.capsule")])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["payload_digest"] == payload_digest(d)


def test_payload_digest_rejects_archive_with_multiple_roots(tmp_path):
    archive = tmp_path / "two.capsule"
    archive.write_bytes(
        _tar_gz(
            [
                (_info("a/capsule.yaml"), MANIFEST),
                (_info("a/.checksums"), b""),
                (_info("b/.checksums"), b""),
            ]
        )
    )
    with pytest.raises(ValueError, match="single top-level"):
        payload_digest(archive)


def test_payload_digest_rejects_archive_without_root_checksums(tmp_path):
    archive = tmp_path / "nested-only.capsule"
    archive.write_bytes(
        _tar_gz(
            [
                (_info("cap/capsule.yaml"), MANIFEST),
                (_info("cap/sub/.checksums"), b"decoy\n"),
            ]
        )
    )
    with pytest.raises(FileNotFoundError):
        payload_digest(archive)
