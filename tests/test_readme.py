"""The README's commands must actually run.

A new user's first command failing is the difference between trying the tool
and closing the tab, and docs drift silently in a way code does not. This
executes the README's own CLI block rather than a paraphrase of it, so the
two cannot diverge (#19).
"""
import re
from pathlib import Path

from click.testing import CliRunner

from marqov_capsule.cli.main import cli

README = Path(__file__).parent.parent / "README.md"


def _cli_block() -> list[str]:
    """The shell commands in the README's CLI section, in order."""
    text = README.read_text()
    block = re.search(r"## CLI.*?```bash\n(.*?)```", text, re.S)
    assert block, "README has no bash block under ## CLI"
    return [
        line.strip()
        for line in block.group(1).splitlines()
        if line.strip().startswith("marqov-capsule ")
    ]


def test_readme_cli_block_is_not_empty():
    cmds = _cli_block()
    assert len(cmds) >= 4, cmds


def test_readme_cli_block_runs_end_to_end(tmp_path):
    """Every documented command, in documented order, exits 0."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        for cmd in _cli_block():
            args = cmd.split()[1:]  # drop the `marqov-capsule` prefix
            result = runner.invoke(cli, args)
            assert result.exit_code == 0, f"`{cmd}` exited {result.exit_code}:\n{result.output}"


def test_readme_cli_block_needs_no_cd(tmp_path):
    """Commands take explicit paths, so the block is copy-pasteable as a unit
    and this test can run it without simulating a shell."""
    text = README.read_text()
    block = re.search(r"## CLI.*?```bash\n(.*?)```", text, re.S).group(1)
    assert "cd " not in block, block


def test_readme_does_not_claim_python_39():
    assert "Python 3.9" not in README.read_text()


def test_readme_links_resolve_on_pypi():
    """Relative links render as dead links on the PyPI project page."""
    text = README.read_text()
    relative = re.findall(r"\]\((?!https?://|#)([^)]+)\)", text)
    assert not relative, f"relative links break on PyPI: {relative}"
