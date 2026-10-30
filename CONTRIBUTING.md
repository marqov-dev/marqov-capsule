# Contributing

## Development setup

From an authorized repository checkout, install the development dependencies.
Contact `hello@marqov.ai` for contribution access.

```bash
pip install -e ".[dev]"
pytest tests/
```

The `[dev]` extra includes numpy and scipy (needed for statistical verification tests) plus pytest.

## Running tests

```bash
pytest tests/ -v
```

All tests must pass before submitting a PR. If you are adding a new spec feature, add a conformance fixture under `spec/v1/conformance/` alongside the code change.

## Quality gates

CI runs the same three checks as the `lint` job, so run them locally before
opening a PR (all are installed by the `[dev]` extra):

```bash
ruff format --check src tests tools   # or `ruff format ...` to apply
ruff check src tests tools            # or `ruff check --fix ...` to apply
mypy src
pytest tests/ --cov --cov-report=xml
diff-cover coverage.xml --compare-branch=origin/main --fail-under=90
```

Or let pre-commit run the first three on every commit:

```bash
pip install pre-commit
pre-commit install
```

The rules, chosen to match Qiskit, Cirq, PennyLane and the Braket SDK:

- **Line length is 100.** The formatter owns wrapping; `E501` is not enforced,
  so a long string or URL the formatter cannot split is fine.
- **Lint set is `E, F, W, I, B, UP`** (pycodestyle, pyflakes, isort, bugbear,
  pyupgrade) at ruff's defaults. Suppress a false positive with a targeted
  `# noqa: <code>` and a one-line reason, never a blanket ignore.
- **mypy** checks `src/` with `check_untyped_defs`; everything under
  `marqov_capsule.cli` must be fully annotated.
- **Changed lines must be covered.** `diff-cover` requires at least 90 % of
  the lines a PR touches to be exercised by the suite. There is **no global
  coverage floor** and **no complexity cap**; reviewers judge those.

### When hosted CI is unavailable

`tools/local_ci.sh` replicates every job in `.github/workflows/ci.yml` except
`test-windows`, each in a fresh uv-managed virtualenv (Python 3.10, 3.11 and
3.12, wheel build and isolated install, base install without the `[dev]`
extra, lowest declared dependency versions, the Node conformance checker and
the offline link check). Run it against the branch you want to merge, from
any checkout, and paste its summary table into the PR before merging:

```bash
tools/local_ci.sh path/to/worktree origin/main
```

It takes about three minutes and needs `uv` and `npm` on the PATH.

The one-time formatting sweep is listed in `.git-blame-ignore-revs`. To keep
`git blame` pointing at the real authors, run once per clone:

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

## License agreement

This repository contains two separately licensed components:

- Contributions to `spec/v1/` are licensed under **CC-BY-4.0**.
- Contributions to the Python package (`src/`) are licensed under **Apache 2.0**.

By submitting a pull request you agree that your contribution may be distributed under these terms.

---

## RFC Evolution Process

Breaking changes to `spec/v1/` follow a public RFC process:
1. Open an issue using the RFC template below.
2. Mandatory public comment period (minimum 2 weeks).
3. Once non-Marqov maintainers exist, spec-breaking changes require sign-off from at least one external maintainer.

## RFC Template

Every spec change proposal MUST include:

**Reproducibility impact:** Does this change affect what can be verified, or how?
Does it alter §6 (verification), §5 (digest scheme), §4 (lifecycle), or the §8 conformance requirements (including the credential check)?

**Portability impact:** Does this change affect what a third party (human or agent)
needs to re-target and re-execute a capsule? Does it introduce any
platform-specific element, non-machine-readable field, or dependency on
the originating implementation?
