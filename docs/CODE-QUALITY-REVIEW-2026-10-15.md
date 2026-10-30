# Code quality review — 2026-10-15

Snapshot of `main` at `7019c01` (#138), taken after fast-forwarding the local
checkout, which had fallen five commits behind origin (#134–#138 landed
2026-10-12 to 10-15). Everything below was measured locally with the project
venv (Python 3.12.12) or `uvx`-pinned tools; nothing has been committed.

## 1. Headline

The codebase is in good shape for a project that has absorbed ~35 review
findings and six hardening PRs in five weeks. Tests, coverage, security
posture and docstrings are all strong. The gaps are **not** in the code you
have written. They are in what the repo *does not check*: there is no lint,
format, type or coverage gate anywhere, so quality is currently held up by
reviewer attention alone. That is the thing to fix first, because it is cheap
now and will not stay cheap.

| Signal | Measured | Verdict |
| --- | --- | --- |
| Test suite | 1358 passed, 3 skipped, 6.7 s | Healthy |
| Branch coverage (`src/`) | 93 % total; lowest `cli/commands/open.py` 70 % | Healthy |
| `ruff check` (default rules) | 8 findings, all in `tests/`, 7 auto-fixable | Clean enough to gate today |
| `ruff format --check` | 68 of 74 files would reformat | Never formatted; one-time cost |
| `mypy src` (default) | 5 errors, one file (`_canonical.py`) | Clean enough to gate today |
| `mypy --check-untyped-defs` | +1 (`cli/commands/init.py:45`, `validator.py:35`) | Worth fixing |
| Return-type annotations | Core modules 60–80 %; `cli/commands/` 4 of 21 | CLI layer is untyped |
| Public docstrings | 57 of 67 public defs | Good |
| `bandit -ll` | 3 findings, all already mitigated (see §3) | Clean |
| Dead code (`vulture ≥80`) | 14 hits, 12 are the retired `NoReturn` stubs | Clean; stubs are deliberate |
| Cyclomatic complexity | 1 function at E (34), 2 at D (25, 26) | Three hotspots, all in `verifier.py` / `redactor.py` |
| Broad `except` | 6 sites | All defensible, all commented |
| TODO / FIXME in `src/` | 0 | Clean |

## 2. What is strong

- **Security hardening is real, not cosmetic.** Both `tarfile.extractall`
  sites use the PEP 706 `data` filter with a hand-rolled fallback for older
  interpreters; `yaml.load` goes through a `SafeLoader` subclass. The bandit
  hits are the scanner not understanding the mitigation.
- **Test shape matches the threat model.** 500 test functions, 963 asserts,
  property-based tests via Hypothesis, hostile-input suites for archive,
  checksums and manifest, and an independent Node conformance checker for the
  spec vectors. Coverage is branch coverage, not line coverage.
- **CI already covers the portability claim.** Linux 3.10–3.12, macOS 3.12
  (NFD / case-insensitive FS), Windows 3.12 (CRLF, `\\`), plus a wheel-install
  smoke test. The release workflow has a test gate and read-only token scope.
- **Failure handling is intentional.** Every broad `except` is paired with a
  comment explaining the fallback (legacy YAML form, unreadable ignore file,
  non-JSON notebook, atomic-write cleanup, draft restore after failed seal).
- **Legacy API retirement is explicit.** `verify_capsule`,
  `check_calibration_drift` and `compare_capsules` raise `NotImplementedError`
  with migration text instead of silently returning a wrong answer.

## 3. What is drifting

### 3.1 No mechanical quality gates (highest leverage)

`pyproject.toml` has no `[tool.ruff]`, `[tool.mypy]`, `[tool.coverage]` or
`[tool.pytest]` section. There is no `.pre-commit-config.yaml`. CI runs tests
and smoke checks only. Consequences already visible:

- Eight ruff findings (unused imports, `json` re-imported inside a test, an
  `l` variable) have been merged across several PRs because nothing flagged
  them.
- The codebase has never been run through a formatter, so every future
  "format on save" diff will be noisy and reviewers will learn to skim it.
- Five mypy errors in `_canonical.py` (lines 190–254, `construct_scalar`
  called with a bare `Node`) have shipped in 0.2.0 and 0.2.1. They are almost
  certainly benign at runtime, but they are exactly the kind of thing a type
  checker exists to catch in a canonicalisation layer.
- Coverage is 93 % but nothing stops it dropping to 80 % in one PR.

Two agents push to this repo under one account and PRs are squash-merged.
That setup *especially* needs gates that do not depend on a human noticing.

### 3.2 Three complexity hotspots

| Function | Lines | Cyclomatic | Note |
| --- | --- | --- | --- |
| `verifier.py:496 CapsuleVerifier.verify_checksums` | 180 | **E (34)** | Parses two checksum formats, walks the tree, compares digests, and classifies failures in one body |
| `verifier.py:678 CapsuleVerifier.verify_integrity` | 133 | D (26) | Manifest load, ID recompute, delegation, verdict assembly |
| `redactor.py:386 _scan_text` | 90 | D (25) | Pattern loop plus notebook / binary / ignore handling |

`verifier.py` and `redactor.py` are also the two most-churned modules of the
last 60 days (8 and 4 touching commits) and have the lowest maintainability
index in the tree (28.8 and 31.0; everything else is above 44). High churn ×
high complexity is where the next regression will come from. None of this
needs a rewrite; it needs the two 130–180-line verifier methods split into
named phases so a reviewer can hold one phase in their head.

### 3.3 The CLI layer is a different codebase

`src/marqov_capsule/cli/commands/` has return annotations on 4 of 21
functions and the lowest coverage in the tree (`open.py` 70 %, uncovered
lines 42–47 and 75–82 are error paths). The core library is typed and
documented; the Click layer is not. It is thin, so this is a small job, but it
is where user-facing error messages live and where #109-style message bugs
keep appearing.

### 3.4 Test suite is organised by provenance, not by behaviour

Fifteen of the 50 test files are named after the event that produced them
rather than what they test: `test_bugfixes.py`, `test_verifier_bugfixes.py`,
`test_review_hardening.py`, `test_gemini_review_022.py`,
`test_correctness_bundle.py`, `test_readiness_bundle.py`,
`test_conference_demo.py`, `test_managed_result_rehearsal.py`, and the
`*_hostile` / `*_hardening` family. The tests themselves are good. The
problem is discoverability: a contributor fixing checksum parsing has to grep
six files to find the existing cases, and the next review will add a
`test_<reviewer>_review_023.py`. Issue #118 (tests that pass for the wrong
reason) is a symptom of the same drift: tests landed fast as evidence for a
finding, not as a specification of the module.

### 3.5 `tools/` is growing without the same bar

`tools/` is now 882 lines across eight scripts, including the new
`evaluation/run.py` and `export_completeness/check.py` from #135–#136, plus a
Node checker. Six test files touch it, but it is outside the coverage
measurement, outside the (nonexistent) lint gate, and `check_urls.py` has an
open hardening issue (#62). Decide whether `tools/` is product (then it gets
the same gates) or scaffolding (then say so in a README and keep it out of
the wheel, which it already is).

### 3.6 Small items

- `verify_checksums` line 546 and `redactor.py` line 255 swallow `Exception`
  where the specific YAML / OS error would do; the comments justify the
  fallback, so narrowing is optional, but the type checker cannot help you
  there today.
- Three `NoReturn` legacy stubs in `verifier.py` (lines 823–872) are the
  right call for 0.x, but they are 50 lines of dead surface; schedule their
  removal for 0.3.0 and say so in the CHANGELOG.
- `__main__.py` has 0 % coverage (3 statements). Trivial, but a one-line
  `python -m marqov_capsule --version` test closes it.
- Untracked `docs/HANDOVER-*`, `docs/fable-review-*` and `.claude/` in the
  working tree. Fine as a deliberate choice, but they are invisible to anyone
  cloning the repo and will be lost if this checkout is.

## 4. How to keep checking this: a layered approach

The question was how to verify quality is keeping up, not just whether it is
today. Four layers, cheapest first. Each is independent.

### Layer 1 — Mechanical gates in CI (do this week, ~half a day)

Cost check first: current CI is 11 jobs in ~90 s wall clock, billed as a
private repo, dominated by the macOS (10×) and Windows (2×, 81 s) legs. The
gates below add one Linux runner for well under a minute and ~3 s of coverage
overhead on one pytest leg. Minutes are not the constraint. **Friction is**:
a gate that goes red for something nobody cares about trains both agents to
sprinkle `noqa` and makes red PRs mean less. So the gates are tiered.

**Evidence check (added after challenge).** Running the broader rule set
`E, F, W, I, B, UP` at the Marqov house line length of 100 produces 290
findings: 167 line-too-long (not auto-fixable), 117 auto-fixable cosmetics
(import order, `X | None` syntax), and 6 substantive, of which 2 (`B023` in
`redactor.py:417`) are false positives and 3 (`B904`) are exception-chaining
style. Zero real bugs. The 5 mypy errors are an over-broad `yaml.Node`
annotation, benign at runtime. And none of the 35 Fable findings or the
Gemini findings would have been caught by ruff or mypy: they were silent
fallbacks (#99), guards that survive mutation (#117), tests that cannot fail
(#118), a `TypeError` on hostile notebook JSON (#125), a silent overwrite
(#106). So lint is **not** where this project's bugs are. Its value is
consistency and cheap review as more contributors land, and that value is
real but modest. Size the gate accordingly.

**Blocking** (near-instant, objective, auto-fixable or real bugs):

- `ruff check` with `F, I` only (unused code, import order): 19 current
  findings, 18 auto-fixable, zero judgement calls. Add `B` and `UP` later if
  wanted, as their own auto-fix PR. Do not add `E501` without a formatter
  sweep first.
- `mypy src --check-untyped-defs`, with `disallow_untyped_defs` scoped to
  `marqov_capsule.cli` first (it is small) then widened.
- The existing test matrix.

**Informational** (same job, written to the step summary, never fails):

- `pytest --cov --cov-branch` on the Linux 3.12 leg. No `fail_under` yet: the
  code is at 93 % and a floor at 90 leaves one new module of headroom. Watch
  the number for a release cycle, then add the floor a few points below
  where it settles.
- `ruff check --select C901 --exit-zero` so the three hotspots and any new
  ones are visible on every PR without blocking.
- `bandit -r src -ll --exit-zero`; the three current hits are mitigated.

**Not in PR CI at all** (release-time or weekly): `pip-audit`, mutation
testing, fuzzing, the independent semantic review in Layer 3. The formatter
sweep (`ruff format`, 68 of 74 files) is a separate no-logic PR with a
`.git-blame-ignore-revs` entry; add `format --check` to the blocking tier
only after that lands.

Most of the "catch it as you work" value is in the local loop, not CI: a
`.pre-commit-config.yaml` running `ruff check --fix` and `mypy src` fixes the
problem in under a second before CI sees it. Put the exact commands and the
tiering rule in `CONTRIBUTING.md`, which today says only "all tests must
pass".

For reference, no sibling repo enforces any of this: `marqov-platform` and
`marqov-sdk` declare `mypy strict = true` in `pyproject.toml` but never run
it in CI; `marqov-quantumflow` has the fullest config and also never runs it.
Capsule is the right place to prove the pattern (small, clean baseline), and
the resulting config is the template to copy to `marqov-sdk` next.

### Layer 2 — Structural review of the hotspots (one PR each)

- Split `verify_checksums` into parse / walk / compare / classify. The
  existing hostile-checksum tests pin the behaviour, so this is a safe
  refactor; run the suite after each extraction.
- Same for `verify_integrity`.
- Type and docstring the Click commands; add the two missing `open.py` error
  path tests.
- Reorganise `tests/` by module (`test_verifier_checksums.py`,
  `test_redactor_scan.py`, …), keeping a `# originally from #NNN` comment on
  moved tests so provenance survives. Fold #118's "wrong reason" fixes into
  the move.

### Layer 3 — Independent semantic review of the recent diff

Static tools will not find a verifier that accepts something it should
reject. The Fable review (#91) found 35 issues that way; the Gemini pass
(#138) found more. Repeat it, but scope it:

- Run `/code-review ultra` against the diff `v0.1.1..main` (the full
  hardening cycle), or module-by-module with a fresh session per module so
  the reviewer is not anchored on the earlier findings. Ask explicitly for
  "tests that pass for the wrong reason" (#118) and for divergence between
  the spec text, the JSON schema and the Python behaviour (#112 shows these
  can drift three ways).
- Resurrect the mutation harness in `docs/fable-review-harness/mutation/`
  (`mutate.sh` plus three probes exist, nothing runs them). A 1358-test suite
  with 93 % coverage can still have a low mutation score; this is the only
  cheap way to know whether the hostile-input tests are actually
  discriminating. Target `_canonical.py`, `verifier.py` and `redactor.py`
  first.
- Fuzz the two parsers (`load_manifest_yaml`, `_parse_normative_checksums`)
  with Hypothesis strategies that already exist in `test_invariants.py`;
  the `fuzz/` harness directory is scaffolding for this.

### Layer 4 — Process so it stays this way

- A PR template with three checkboxes: gates green, CHANGELOG entry, spec /
  schema / code agree (or "n/a: no spec surface").
- Record a one-paragraph quality bar in `CONTRIBUTING.md`: typed public API,
  docstring on every public def, no function over complexity 15 without a
  comment saying why, test file named after the module under test.
- Re-run this measurement at each release (the commands are in §5) and keep
  the table in §1 as a trend line in `docs/`. Three data points will tell you
  more than any single review.

## 5. Reproducing the numbers

```bash
.venv/bin/python -m pytest tests/ -q -p no:cacheprovider
uv run --with pytest-cov pytest tests/ -q --cov=marqov_capsule --cov-branch --cov-report=term-missing
uvx ruff@0.14.0 check src tests tools --statistics
uvx ruff@0.14.0 format --check src tests tools
uvx --with pyyaml --with jsonschema --with click --with jcs --with types-PyYAML --with types-jsonschema mypy@1.18.2 src --ignore-missing-imports --check-untyped-defs
uvx radon@6.0.1 cc src -s -n C
uvx radon@6.0.1 mi src -s
uvx bandit@1.8.6 -r src -q -ll
uvx vulture@2.14 src --min-confidence 80
```

`pip-audit` via `uvx` failed locally (the uv-managed Python 3.13 could not
bootstrap `ensurepip`); run it from the project venv instead once it is
installed there.

## 6. Suggested order (revised after the evidence check in §4 Layer 1)

1. Layer 3 mutation run on `_canonical.py`, `verifier.py` and `redactor.py`,
   using the existing `docs/fable-review-harness/mutation/mutate.sh`. This is
   the only technique in this document with a track record on this codebase
   (#117 found six surviving mutants) and its result decides how urgent the
   test reorganisation is.
2. Layer 1 minimal gate (`ruff F,I` + `mypy`), one small PR. Cheap insurance,
   not a bug-finder; do it because the baseline is 19 findings today and will
   not stay there.
3. Layer 2 verifier split, then CLI typing, then test reorganisation.
4. Layer 3 independent review of `v0.1.1..main`.
