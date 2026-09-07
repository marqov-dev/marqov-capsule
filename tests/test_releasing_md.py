"""RELEASING.md's step-3 CLI validation block must actually run (#63).

The root README's CLI block is executed by tests/test_readme.py (#19); this
block is not, and covers ground that one doesn't — pack/unpack, `-o`, and a
non-empty payload. Undetected doc drift here is exactly how a flag rename or
reordered arg would sit broken in the release runbook until release day.

The `pip install ... marqov-capsule==X.Y.Z` lines install a specific
*published* release from an index — `X.Y.Z` is a literal placeholder, and the
whole point on release day is that version doesn't exist anywhere yet during
development. There's nothing for a test to run there. Everything else in the
block — the actual `marqov-capsule` invocations, exactly as documented — is
executed for real, mirroring test_readme.py's "run the actual documented
commands, don't paraphrase them" idiom, against whatever `marqov-capsule` is
installed in the current environment (the dev checkout, not a TestPyPI
download).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

RELEASING = Path(__file__).parent.parent / "RELEASING.md"


def _step_3_validation_block() -> str:
    """The fenced shell block under step 3's 'Validate the PUBLISHED
    artifact' bullet, with the `pip install` lines (and their `\\`
    continuations) dropped."""
    text = RELEASING.read_text()
    match = re.search(r"Validate the PUBLISHED artifact.*?```\n(.*?)```", text, re.S)
    assert match, "RELEASING.md's step 3 has no 'Validate the PUBLISHED artifact' fenced block"

    kept: list[str] = []
    skipping_continuation = False
    for line in match.group(1).splitlines():
        if skipping_continuation:
            skipping_continuation = line.rstrip().endswith("\\")
            continue
        if line.strip().startswith("pip install"):
            skipping_continuation = line.rstrip().endswith("\\")
            continue
        if line.strip():
            kept.append(line)
    return "\n".join(kept)


def test_step_3_block_is_not_empty():
    script = _step_3_validation_block()
    assert "marqov-capsule init" in script
    assert "marqov-capsule seal" in script
    assert "marqov-capsule pack" in script
    assert "marqov-capsule verify" in script
    assert "marqov-capsule unpack" in script


def test_step_3_block_has_no_pip_install_left():
    """Guards the extraction itself: if RELEASING.md's pip install lines ever
    change shape (e.g. lose the `\\` continuation), this must still catch
    and drop them rather than silently trying to run a real `pip install`
    against a TestPyPI version that doesn't exist during development."""
    assert "pip install" not in _step_3_validation_block()


def test_step_3_cli_block_runs_end_to_end(tmp_path):
    """Run the documented commands for real, in a scratch directory, against
    whatever `marqov-capsule` is on PATH for this environment."""
    script = _step_3_validation_block()

    env = dict(os.environ)
    # sys.exec_prefix, not Path(sys.executable).resolve().parent: on a venv
    # created by `uv venv`, `python` is a symlink into uv's shared interpreter
    # store, so resolving it walks straight out of the venv and away from
    # where `pip install -e` put the `marqov-capsule` console script.
    # exec_prefix is the venv root regardless of how `python` itself is laid out.
    bin_dir = str(Path(sys.exec_prefix) / "bin")
    env["PATH"] = os.pathsep.join([bin_dir, env.get("PATH", "")])

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"RELEASING.md's step-3 CLI block failed:\n{script}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )

    # The flow this block covers that the README's doesn't: pack emits a
    # *file* (not a directory — see .gitignore's `*.capsule` pattern, #63),
    # and unpack restores the original `t/` directory underneath `-o`'s target.
    assert (tmp_path / "t.capsule").is_file()
    assert (tmp_path / "r" / "t" / "capsule.yaml").is_file()
