"""RELEASING.md's step-3 CLI validation block must actually run.

It documents the seal -> pack -> verify -> unpack round trip a release
manager runs by hand against a freshly published TestPyPI artifact, but
nothing else exercises that exact sequence, so it can rot silently the way
the README's block would without #19's test. This runs it against the
in-repo CLI rather than an installed TestPyPI wheel (there's nothing to
install from during a normal test run) — it only guards the command
sequence itself, not the published package.
"""
import re
from pathlib import Path

from click.testing import CliRunner

from marqov_capsule.cli.main import cli

RELEASING = Path(__file__).parent.parent / "RELEASING.md"


def _validation_block() -> list[str]:
    """The `marqov-capsule` commands in step 3's artifact-validation block,
    in order, with the X.Y.Z placeholder version stripped out (there's no
    real published version to seal/pack against here)."""
    text = RELEASING.read_text()
    block = re.search(
        r"Validate the PUBLISHED artifact.*?```\n(.*?)```", text, re.S
    )
    assert block, "RELEASING.md has no fenced block under the artifact-validation step"
    parts = (
        part.strip()
        for line in block.group(1).splitlines()
        for part in line.split("&&")
    )
    return [part for part in parts if part.startswith("marqov-capsule ")]


def test_validation_block_is_not_empty():
    cmds = _validation_block()
    assert len(cmds) >= 4, cmds


def test_validation_block_runs_end_to_end(tmp_path):
    """Every documented marqov-capsule command, in documented order, exits 0."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        for cmd in _validation_block():
            args = cmd.split()[1:]  # drop the `marqov-capsule` prefix
            result = runner.invoke(cli, args)
            assert result.exit_code == 0, f"`{cmd}` exited {result.exit_code}:\n{result.output}"
