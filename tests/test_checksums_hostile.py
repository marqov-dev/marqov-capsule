"""``.checksums`` is untrusted input: a hostile path must be a FAIL verdict,
never an exception out of the verifier (#123).
"""
import os
import pytest
from click.testing import CliRunner

from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.cli.main import cli
from marqov_capsule.verifier import CapsuleVerifier

DIGEST = "sha256:" + "0" * 64
REQUIREMENTS = {"paradigm": ["gate-based"], "max_qubit_count": 2}

HOSTILE_PATHS = [
    ("nul-byte", "a\x00b"),
    ("bell", "a\x07b"),
    ("tab", "a\tb"),
    ("escape", "a\x1bb"),
    ("delete", "a\x7fb"),
    ("overlong-component", "x" * 300),
    ("deeply-nested", "a/" * 200 + "f"),
    ("overlong-total", "/".join(["b" * 200] * 30)),
]


def _capsule_with_checksums(tmp_path, line: str):
    (tmp_path / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: t\nlifecycle_state: sealed\n"
        f"checksums_digest: {DIGEST}\n", encoding="utf-8")
    (tmp_path / ".checksums").write_bytes(line.encode("utf-8", "surrogateescape"))
    return tmp_path


@pytest.mark.parametrize("path", [p for _, p in HOSTILE_PATHS], ids=[n for n, _ in HOSTILE_PATHS])
def test_verify_checksums_fails_closed_on_hostile_path(path, tmp_path):
    _capsule_with_checksums(tmp_path, f"{DIGEST}  {path}\n")
    result = CapsuleVerifier.verify_checksums(tmp_path)
    assert result["status"] == "fail"
    assert result["passed"] is False
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in path):
        # The writer never emits a raw control character: parse-time rejection.
        assert "malformed" in result["error"], result


@pytest.mark.parametrize("path", [p for _, p in HOSTILE_PATHS], ids=[n for n, _ in HOSTILE_PATHS])
def test_verify_integrity_fails_closed_on_hostile_path(path, tmp_path):
    _capsule_with_checksums(tmp_path, f"{DIGEST}  {path}\n")
    assert CapsuleVerifier.verify_integrity(tmp_path)["status"] == "fail"


@pytest.mark.parametrize("path", [p for _, p in HOSTILE_PATHS], ids=[n for n, _ in HOSTILE_PATHS])
@pytest.mark.parametrize("command", ["verify", "open"])
def test_cli_exits_1_without_traceback_on_hostile_path(command, path, tmp_path):
    _capsule_with_checksums(tmp_path, f"{DIGEST}  {path}\n")
    result = CliRunner().invoke(cli, [command, str(tmp_path)])
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(result.exception)


@pytest.mark.skipif(os.name == "nt", reason="filename cannot exist on this filesystem")
def test_control_character_in_path_is_noncanonical_even_when_file_exists(tmp_path):
    # A real file whose name carries a tab: the writer never emits a raw
    # control character, so a reader seeing one is looking at a file the
    # reference writer did not produce. Fail, do not hash.
    sealed = tmp_path / "cap"
    sealed.mkdir()
    (sealed / "ok.txt").write_text("x")
    builder = CapsuleBuilder().start_capsule(name="t", requirements=REQUIREMENTS)
    builder.seal(sealed)
    text = (sealed / ".checksums").read_text(encoding="utf-8")
    (sealed / ".checksums").write_text(text.replace("ok.txt", "ok\t.txt"), encoding="utf-8")
    (sealed / "ok.txt").rename(sealed / "ok\t.txt")
    result = CapsuleVerifier.verify_checksums(sealed)
    assert result["status"] == "fail"
