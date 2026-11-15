# Mutation report — `_canonical.py`, `verifier.py`, `redactor.py`

Date: 2026-10-15 (run finished early 2026-10-16). Tool: mutmut 3.8.0 (uv-installed, Python 3.13) against commit `7019c01` (main after #138). Suite: 1358 passed, 3 skipped, run as the test command for every mutant. Nothing in `src/` or `tests/` was modified; the run happened in a scratch copy of the worktree (see *Method*).

## TL;DR

The 1358-test suite covers these three modules at ~93% branch coverage but **kills 70.8% of the mutants mutmut can make in them** (1695 of 2395). The 700 survivors break down as:

| class | count | what it means |
|---|---|---|
| **(b) real gap** | **40** | a security or correctness guard can be removed, or a verdict/record field flipped, with the suite still green. 13 distinct findings, each with a one-test kill that was verified (passes on the original, fails on the mutant). |
| (a) equivalent | 80 | no observable behaviour change (e.g. `all_match = None` is as falsy as `False`; `"UTF-8"` vs `"utf-8"`). |
| (c1) message text | 195 | the text of an error/reason/warning string. Not asserted anywhere; arguably correct. |
| (c2) output contract | 184 | a result-dict key, list (`mismatched`, `missing`, `symlinks`) or finding field (`tier`, `reason`, `match`) that no test reads. Consumers (CLI JSON, downstream integrations) do read some of these. |
| (c3) diagnostic value | 29 | chi-squared p-value and energy distance: computed, reported, never pinned. By design they never change the verdict. |
| (c4) boundary / default / edge | 81 | `<` vs `<=`, default arguments, `continue`→`break` on a secondary path, redaction prefix length. |
| (c5) platform-masked | 16 | `.CHECKSUMS` is found on case-insensitive APFS; NFC/NFD collisions cannot exist on APFS; `encoding=None` is UTF-8 on this Mac. Re-run on Linux (ext4, 2026-10-30): 9 of the 16 are killed there; the 7 `encoding=None` / `"UTF-8"` mutants survive on any UTF-8 locale. |
| (c6) unused helper | 20 | `_shannon_entropy` and `_looks_like_digest_line` have no caller in the package (only a research note imports the first). |
| (c7) detection completeness | 55 | a warn-only or secondary detection path that no test exercises positively: **the whole Tier B entropy tier**, notebook `execute_result`/`display_data`/`error` outputs, two findings on one line. |

**Scores per module**

| module | mutants | killed | survived | score | (b) survivors |
|---|---|---|---|---|---|
| `_canonical.py` | 363 | 325 | 38 | **89.5%** | 1 |
| `verifier.py` | 1084 | 703 | 381 | **64.9%** | 22 |
| `redactor.py` | 948 | 667 | 281 (20 with no covering test) | **70.4%** | 17 |
| total | 2395 | 1695 | 700 | **70.8%** | 40 |

The hotspots the review flagged line up with the data. `_canonical.load_manifest_yaml` and all five strict scalar constructors score **100%** (every mutant killed); the YAML-profile work since #122 is genuinely pinned. `verifier.verify_checksums` (61%), `_parse_normative_checksums` (53%) and `redactor._scan_text` (75%) carry 20 of the 40 (b) survivors between them, plus almost all of the output-contract gaps.

**Comparison with #117.** The six guards reported in September (M3, M4, M19, M20 are outside these modules; M24 `min(n_ref, n_new)` and M42 bool/None key spelling are inside) are all killed now: `_stringify_key` and `verify_statistical`'s shot gate have no survivors of that kind. The gaps below are the next layer down.

## Method

- **Tool and scope.** `mutmut run --max-children 4`, `only_mutate` restricted to the three modules, full `tests/` as the test command. mutmut 3 first records which tests execute each function (stats pass, one full suite run), then runs only those tests per mutant; 2395 mutants finished in about 45 minutes at 3.05 mutants/s. The task brief's fallback (restrict to the review's hotspot functions if runtime is prohibitive) was not needed.
- **Repo never touched.** The worktree was `rsync`ed to the session scratchpad, `git init`ed (one packaging test shells out to `git ls-files`), given its own venv (`uv venv` + `uv pip install -e ".[dev]" mutmut`), and mutmut was configured there in `[tool.mutmut]`. `git status` in the worktree is clean and the suite re-ran green after the run (1358 passed, 3 skipped).
- **Three accommodations in the scratch copy only, none in the repo:**
  1. `tests/test_os_independence.py`'s three *static source-scan* tests were deselected: they read `src/` as text and trip on mutmut's rewritten source (`read_text(encoding=None)` mutants etc.). They are lint, not behaviour.
  2. The five wall-clock assertions in `tests/test_manifest_hostile.py` (`< 1.0 s`, `< 0.5 s`) were relaxed to `< 30 s`. mutmut's per-call trampoline makes the depth-1000 flow-sequence case take ~1.9 s, which failed the clean run; left in place they would also have produced false kills. The behavioural asserts in those tests (fails closed, "could not be parsed") were kept and did kill mutants.
  3. `.github/` added to `also_copy` (a packaging test reads the CI workflow).
- **What mutmut does not mutate.** Only function bodies. Module-level constants are untouched: the redactor's `_SHAPE_RULES` / `_KNOWN_NAME_RE` / `_DIGEST_LINE_RE` tables, the entropy thresholds, `_MAX_NESTING_DEPTH`, the implicit-resolver registrations in `_canonical`. A wrong regex in `_SHAPE_RULES` is therefore outside this measurement.
- **Verification of the (b) list.** Each proposed killing test was written to a scratch file, run against the original (19 tests, all pass), then each targeted mutant was applied with `mutmut apply`, the test re-run, and `src` restored with `git checkout`. 60 mutant/test pairs were checked; every mutant classified (b) below fails its named test. Pairs that did *not* fail were reclassified from the evidence (e.g. every `all_match = None` is (a); `_finding_allowed` `rfind` is (c4)).
- **Caveats.** (i) Platform: run on macOS/APFS. A Linux re-run of the 16 (c5) survivors and the B2/B3 mutants on 2026-10-30 is reported under the (c5) bullet below; it needed the `pytest==9.1.1` pin (mutmut 3.8.0 reads a private pytest attribute that newer pytest removed) and a native-arch image (emulated x86_64 trips the wall-clock asserts). (ii) One pre-existing intermittent failure in the suite, `test_manifest_hostile.py::test_cli_commands_exit_1_without_traceback[deep-flow-sequence-*]` (then a `< 1.0 s` wall-clock assert), failed once in three plain runs; it is unrelated to mutation. The CI-gates session (gallant-jepsen) hit the same budgets under `--cov` and on 3.10. All seven wall-clock budgets were raised to `< 5.0 s` in #146, which still catches the quadratic blow-ups they guard. (iii) Line numbers below are computed from each mutant's diff against the function source and were cross-checked against the file text (0 mismatches of 700).

## (b) findings — guards removable with the suite green

Each row is one finding; the mutant numbers are mutmut's per-function indices (listed in the appendix). "Kill" is a test that passes today and fails under every listed mutant; all were run.

| id | file:line | mutation(s) that survive | why it matters | kill (one test) |
|---|---|---|---|---|
| **B1** | `verifier.py:510-511`, `:525-526` | `"status": "fail"`→`"XXfailXX"`, `"passed": False`→`True` in the early returns for a **missing** or **undecodable** `.checksums` (mutants 11, 12, 15, 34, 35, 38) | `verify_checksums` on a capsule with no `.checksums` can report `passed: True`. Only `verify_integrity` callers are protected (it re-derives from `status != "pass"`); direct API/platform callers are not. | `r = CapsuleVerifier.verify_checksums(tmp_path); assert (r["status"], r["passed"]) == ("fail", False)` — and the same after writing `b"\xff\xfe\x00"` to `.checksums`. |
| **B2** | `verifier.py:603-607` | `all_match = True` after a **non-string key** (146); `"match": True` in its record (138); `invalid.append(None)` (143); `continue`→`break` (147) | A legacy-YAML `.checksums` whose only defect is a `~:`/`[a]:` key, with every real file matching, verifies as **pass**. The existing non-string-key test passes for the wrong reason (its fixture fails on other grounds too). | legacy `.checksums` = `? ~\n: <hex>\npayload/r.json: <digest>` with a matching `payload/r.json`; assert `status == "fail"`, `invalid == ["None"]`, `files["None"]["match"] is False`, `files["payload/r.json"]["match"] is True`. |
| **B3** | `verifier.py:595-597` | duplicate-NFC-key detection: `all_match = True` (127), `invalid.append(None)` (125), `normalized_expected.add(None)` (128) | Two keys that are NFC-equivalent (`é` and `é`) both resolve to the same file on APFS and both match; the duplicate guard is the only thing failing the verdict, and no test exercises it. | legacy `.checksums` with `"é.txt"` and `"é.txt"` → same digest, one file on disk; assert `status == "fail"` and `"é.txt" in invalid`. |
| **B4** | `verifier.py:756` | `checksums_digest_match = False`→`True`/`None` when the manifest **declares** `checksums_digest` but `.checksums` is **absent** (72, 73) | JSON consumers reading `checksums_digest_match` get `True` for a capsule whose checksum file was deleted. `status` is still `fail`, so the CLI exit code is right; the machine-readable detail is wrong. | manifest `checksums_digest: sha256:…`, no `.checksums`; assert `verify_integrity(d)["checksums_digest_match"] is False`. |
| **B5** | `verifier.py:479` | `sort_keys=True` removed/`False` (3, 6, 8); `default=str` removed/`None` (4, 7) | `verify_deterministic` **REJECTs equal data** whose dict keys arrive in a different order, and raises `TypeError` instead of comparing when a value is a `datetime`. Both are correctness guards of the one deterministic verdict in the package. | `verify_deterministic({"a":1,"b":2}, {"b":2,"a":1})["verdict"] == "VERIFIED"`; `verify_deterministic({"t": datetime(2026,1,1)}, {"t": datetime(2026,1,1)})["verdict"] == "VERIFIED"`. |
| **B6** | `verifier.py:117` | `_ChecksumsGrammarError(line_no, …)` called with one argument / positional dropped (76, 77) | A malformed normative line that has a valid digest **and a control character** (e.g. a lone space then `\r`) raises `TypeError` out of `verify_checksums` instead of returning a grammar-error verdict: a bare exception from untrusted input, the exact class of bug #61/#123 closed. | `.checksums` = `f"sha256:{'a'*64} payload\rx\n"`; assert `verify_checksums(d)["status"] == "fail"` and `"control character" in r["error"]`. |
| **B7** | `redactor.py:381-382` | `comma = None` / `tail.find("XX,XX")` / `or True` (2, 5, 8) | The documented scoping of `# capsule:allow` ("must appear before any `,`, so one literal inside a minified JSON value cannot disable a real token elsewhere") is enforced by code no test exercises: an allow comment **after a comma** suppresses a blocking finding before it. | `_scan_text('key = "AKIAIOSFODNN7EXAMPLE", other = 1  # capsule:allow', "x.py")` has exactly one `aws_access_key_id` finding. |
| **B8** | `redactor.py:236` | `return True`→`False` for the exact-name set (6) | `id_rsa`, `id_ed25519`, `id_ecdsa`, `id_dsa` are never tested as credential files; only the extension rule (`.pem`, `.key`, …) is. | capsule containing `id_rsa`; assert the scan's single finding has `reason == "credential_file"`. |
| **B9** | `redactor.py:282` | `and`→`or` (4) | A high-signal credential name assigned **from the environment** (`IBM_QUANTUM_TOKEN = os.environ["…"]`) would block the seal: the false-positive guard the docstring promises has no test. | `_scan_text('IBM_QUANTUM_TOKEN = os.environ["IBM_QUANTUM_TOKEN"]', "x.py") == []`. |
| **B10** | `redactor.py:524`, `:529`, `:532` | `continue`→`break` on a non-dict cell / non-list `outputs` / non-dict output (24, 41, 44) | A hostile notebook puts one malformed cell (or output) first and **every later cell is unscanned**: a bypass of the pre-seal scan with a single integer in the JSON. | `_scan_notebook("n.ipynb", json.dumps({"cells": [1, {"source": "k='AKIA…'"}]}))` has one finding; same with `{"source":"","outputs":5}` first, and with `"outputs":[7, {"output_type":"stream","text":"k='AKIA…'"}]`. |
| **B11** | `redactor.py:392-393` | `begin_line` computed over the rest of the file (15, 20, 21, 23, 25) | `# capsule:allow` on **any later line** suppresses a PEM private-key block; the annotation is supposed to be honoured only on the `-----BEGIN` line. | PEM block followed by a line `# capsule:allow`; assert one `private_key_block` finding. |
| **B12** | `redactor.py:668`, `:692`, `:698`, `:702` | `continue`→`break` at the symlink / `.capsuleignore` / binary / unreadable skips (11, 53, 61, 71) | The first skipped entry in sorted order **ends the scan**: a capsule with `0.bin` (contains a NUL byte) and `z.py` holding an AWS key scans clean and seals. Four independent ways to disable the redactor, none observed by a test. | capsule with `0.bin` (`b"\x00\x01"`), `1link` (dangling symlink), `2unreadable` (`chmod 0`), `__pycache__/3.pyc`, and `z.py` with an AWS key; assert the findings' files == `["z.py"]`. |
| **B13** | `_canonical.py:421` | `not isinstance(number, bool)`→`isinstance(number, bool)` (3) | The RFC 8785 safe-range guard for an **integer mapping key** is disabled; `jcs` then rounds `2**53` through `float` silently. Reachable only through the Python API (the YAML loader rejects non-string keys), so low exposure, but it is the fail-closed rule from spec §5. | `with pytest.raises(ValueError): coerce_for_canonical({2**53: 1})`. |

Two things the (b) list is **not** saying: none of these is a vulnerability in shipped behaviour (the original code is correct in every case probed), and `status`/exit codes stay right in B1-B4; what is wrong is that the suite would not notice if the guard went away.

## (c) classes worth a decision

- **(c7) Tier B is unverified end to end.** 55 survivors across `_charset_entropy`, `_entropy_reason`, `_iter_entropy_candidates` and `_plausible_secret_value`: the entropy function can return 0 for everything, the candidate gating can be inverted, and no test fails, because no test asserts a `high_entropy_hex`/`high_entropy_base64` finding (only `name_entropy`, which does not use entropy). Tier B is warn-only by design, so this is (c) not (b), but it means the research note's measured thresholds are not pinned by anything. One test: `_scan_text('secret = "Zq9Kp2Lm8Rt4Vx7Wn3Yb6Hc1Jd5Fg0Sa"', "x.py")` yields one non-blocking `high_entropy_base64` finding (verified to kill 5 of the 6 `_charset_entropy` mutants and the gating inversion).
- **(c7) notebook outputs.** `execute_result`/`display_data` `text/plain` and `error` `evalue` outputs are never asserted (20 survivors); only `stream` and `traceback` are.
- **(c2) the verifier's backwards-compat lists.** `mismatched`, `missing`, `symlinks` and the per-file `files[...]` records can be emptied or renamed with the suite green (≈50 survivors). A downstream integration is exactly the kind of consumer that reads `passed`/`mismatched`. One golden-output test per verdict kind would pin all of them.
- **(c4) `_redact_value` leaks one more character** under seven survivors (prefix 3 or 5 instead of 2 or 4, boundary 6/7). Redaction exists so a report never contains the secret; the exact mask format is not asserted anywhere.
- **(c4) `verify_statistical` defaults.** `min_shots` default 100 and `epsilon` default 0.02 are never exercised; a settings dict without `epsilon` would raise `TypeError` (`tvd_ucb <= None`). Fine if `policy.resolve` is the only caller, which is the current contract.
- **(c4) `_iter_private_key_blocks` with two PEM blocks** raises `TypeError` under mutant 20 (`resume = None`); no test has two blocks in one file.
- **(c5) measured on Linux (2026-10-30, python:3.12 arm64 container, ext4, non-root).** The plain suite passes (1359 passed, 2 skipped). Of the 16 platform-masked survivors, the 9 that depend on the filesystem are killed there: `.CHECKSUMS`/`.CAPSULEIGNORE` case (`verify_checksums` 6, `verify_integrity` 65, `_load_capsuleignore` 4), the NFC on-disk mapping (`_check_entry` 22, 33) and collision detection (`verify_checksums` 100, 110, 112, 113). The 7 that depend on the locale (`encoding=None`: `verify_integrity` 48, `load_capsule` 3, `_load_capsuleignore` 7, 9, `scan` 63, 65; and `verify_checksums` 115) survive on Linux too, because Python 3.12 defaults to UTF-8 there as well. The B2/B3 mutants survive on Linux with the original suite, as expected (closed since by #140).
- **(c6) dead code.** `_shannon_entropy` (18 mutants, no test) and `_looks_like_digest_line` (2, no test) have no caller in the package. Keep for the research note or delete; either way they inflate the module's survivor count by 20.
- **(c1) message text, 195 survivors.** Deliberately not recommended as tests: asserting exact error strings makes refactors expensive and finds few bugs. The exception is B6, where the mutation turns a message into a traceback.

## Highest-value tests to add, in order

Ordered by what they protect, then by how many survivors one test kills. None of these were added; this is the proposal.

1. **B12** redactor scan continues past skipped entries — kills 4 bypasses of the pre-seal scan with one fixture.
2. **B10** notebook scan continues past malformed cells/outputs — 3 bypasses, one fixture with three cases.
3. **B7 + B11** `# capsule:allow` scoping (after a comma; on a later line than `-----BEGIN`) — 8 survivors, the two ways to turn a comment into a suppression.
4. **B2 + B3** legacy `.checksums` with a non-string key / with NFC-duplicate keys and an otherwise matching payload — 7 survivors; also fixes a test that passes for the wrong reason.
5. **B1** `verify_checksums` early returns pin `status`/`passed` — 6 survivors, one two-case test.
6. **B6** malformed line with a control character returns a verdict, never a traceback — 2 survivors, the bare-exception class.
7. **B5** `verify_deterministic` key order and `default=str` — 5 survivors, the only deterministic verdict.
8. **B4** `checksums_digest_match is False` when `.checksums` is absent — 2 survivors, machine-readable detail.
9. **B8 + B9** `id_rsa` is a credential file; a known name assigned from `os.environ` is not embedded — 2 survivors, one positive and one negative.
10. **B13** unsafe int key rejected — 1 survivor, spec §5 fail-closed.
11. **C\*** one positive Tier B entropy test — ~20 (c7) survivors; cheap and pins the research thresholds.
12. **Golden-output tests** for `verify_checksums` (one per kind: mismatch, missing, symlink, extra, invalid) asserting the whole result dict — ≈50 (c2) survivors.
13. Keep one Linux leg in CI — it kills 9 of the 16 (c5) survivors for free (measured; see the (c5) bullet).

## Reproducing

In a copy of the repo (not the checkout), append to `pyproject.toml`:

```toml
[tool.mutmut]
source_paths = ["src"]
only_mutate = ["src/marqov_capsule/_canonical.py", "src/marqov_capsule/verifier.py", "src/marqov_capsule/redactor.py"]
also_copy = ["spec", "examples", "tools", "docs", ".github", "README.md", "CHANGELOG.md", "CONTRIBUTING.md", "RELEASING.md", "LICENSE-CODE", "LICENSE-SPEC"]
pytest_add_cli_args = ["-p", "no:cacheprovider", "-W", "ignore",
    "--deselect", "tests/test_os_independence.py::test_no_capsule_relative_path_uses_the_native_separator",
    "--deselect", "tests/test_os_independence.py::test_every_text_read_and_write_names_its_encoding",
    "--deselect", "tests/test_os_independence.py::test_no_text_mode_open_without_an_encoding"]
pytest_add_cli_args_test_selection = ["tests/"]
```

then relax the five `time.perf_counter()` asserts in `tests/test_manifest_hostile.py`, `git init && git add -A && git commit -m base`, `uv venv .venv && uv pip install -p .venv/bin/python -e ".[dev]" mutmut`, and `.venv/bin/mutmut run --max-children 4` (about 45 min). `mutmut show <name>` prints any mutant in the appendix; `mutmut browse` is the TUI. The proposed killing tests exist as a scratch file (`test_probe.py`, 19 tests) in the session scratchpad and are reproduced one-line each in the table above.

## Per-function scores

Sorted by survivors. The last column counts the survivors that are not message text, output-field spelling, diagnostics, platform or dead code — the ones a test could reasonably target.

| module | function | mutants | killed | survived | score | (b) | (b)+(c4)+(c7) |
|---|---|---|---|---|---|---|---|
| _canonical.py | `_ManifestLoader.scan_flow_scalar_breaks` | 29 | 13 | 16 | 45% | 0 | 0 |
| _canonical.py | `_reject_tag` | 8 | 0 | 8 | 0% | 0 | 0 |
| _canonical.py | `_ManifestLoader.scan_directive` | 20 | 15 | 5 | 75% | 0 | 0 |
| _canonical.py | `_canonical_number_str` | 10 | 6 | 4 | 60% | 1 | 2 |
| _canonical.py | `compute_capsule_id` | 8 | 4 | 4 | 50% | 0 | 0 |
| _canonical.py | `parse_capsule_id` | 9 | 8 | 1 | 89% | 0 | 0 |
| _canonical.py | `_ManifestLoader.__init__` | 3 | 3 | 0 | 100% | 0 | 0 |
| _canonical.py | `_ManifestLoader.compose_node` | 31 | 31 | 0 | 100% | 0 | 0 |
| _canonical.py | `_ManifestLoader.construct_mapping` | 54 | 54 | 0 | 100% | 0 | 0 |
| _canonical.py | `_construct_manifest_string` | 17 | 17 | 0 | 100% | 0 | 0 |
| _canonical.py | `_construct_int_base10` | 34 | 34 | 0 | 100% | 0 | 0 |
| _canonical.py | `_construct_float_strict` | 14 | 14 | 0 | 100% | 0 | 0 |
| _canonical.py | `_construct_null_strict` | 12 | 12 | 0 | 100% | 0 | 0 |
| _canonical.py | `_construct_bool_strict` | 14 | 14 | 0 | 100% | 0 | 0 |
| _canonical.py | `load_manifest_yaml` | 22 | 22 | 0 | 100% | 0 | 0 |
| _canonical.py | `_represent_manifest_string` | 13 | 13 | 0 | 100% | 0 | 0 |
| _canonical.py | `dump_manifest_yaml` | 14 | 14 | 0 | 100% | 0 | 0 |
| _canonical.py | `_nfc` | 6 | 6 | 0 | 100% | 0 | 0 |
| _canonical.py | `_stringify_key` | 18 | 18 | 0 | 100% | 0 | 0 |
| _canonical.py | `coerce_for_canonical` | 25 | 25 | 0 | 100% | 0 | 0 |
| _canonical.py | `canonical_bytes` | 2 | 2 | 0 | 100% | 0 | 0 |
| verifier.py | `CapsuleVerifier.verify_checksums` | 256 | 155 | 101 | 61% | 13 | 15 |
| verifier.py | `_parse_normative_checksums` | 146 | 78 | 68 | 53% | 2 | 3 |
| verifier.py | `CapsuleVerifier.verify_statistical` | 158 | 119 | 39 | 75% | 0 | 5 |
| verifier.py | `_check_entry` | 84 | 46 | 38 | 55% | 0 | 1 |
| verifier.py | `CapsuleVerifier.verify_integrity` | 129 | 92 | 37 | 71% | 2 | 4 |
| verifier.py | `_compute_chi_squared_p` | 50 | 32 | 18 | 64% | 0 | 0 |
| verifier.py | `CapsuleVerifier.verify_capsule` | 17 | 2 | 15 | 12% | 0 | 0 |
| verifier.py | `_compute_energy_distance` | 56 | 45 | 11 | 80% | 0 | 1 |
| verifier.py | `CapsuleVerifier.verify_deterministic` | 30 | 19 | 11 | 63% | 5 | 5 |
| verifier.py | `CapsuleVerifier.compare_capsules` | 14 | 3 | 11 | 21% | 0 | 0 |
| verifier.py | `CapsuleVerifier.__init__` | 16 | 7 | 9 | 44% | 0 | 0 |
| verifier.py | `CapsuleVerifier.check_calibration_drift` | 12 | 3 | 9 | 25% | 0 | 0 |
| verifier.py | `_require_numpy` | 6 | 0 | 6 | 0% | 0 | 0 |
| verifier.py | `_is_within_root` | 15 | 11 | 4 | 73% | 0 | 2 |
| verifier.py | `CapsuleVerifier.load_capsule` | 11 | 8 | 3 | 73% | 0 | 0 |
| verifier.py | `_tvd_upper_confidence_bound` | 35 | 34 | 1 | 97% | 0 | 0 |
| verifier.py | `_normalise_counts` | 20 | 20 | 0 | 100% | 0 | 0 |
| verifier.py | `_ChecksumsGrammarError.__init__` | 1 | 1 | 0 | 100% | 0 | 0 |
| verifier.py | `_tvd_point` | 28 | 28 | 0 | 100% | 0 | 0 |
| redactor.py | `_scan_text` | 277 | 208 | 69 | 75% | 5 | 26 |
| redactor.py | `_scan_notebook` | 107 | 74 | 33 | 69% | 3 | 23 |
| redactor.py | `_scan_manifest_values` | 114 | 86 | 28 | 75% | 0 | 5 |
| redactor.py | `CapsuleRedactor.scan` | 106 | 85 | 21 | 80% | 4 | 8 |
| redactor.py | `_shannon_entropy` | 18 | 0 | 18 | 0% | 0 | 0 |
| redactor.py | `_entropy_reason` | 33 | 16 | 17 | 48% | 0 | 13 |
| redactor.py | `_redact_value` | 23 | 10 | 13 | 43% | 0 | 7 |
| redactor.py | `_iter_entropy_candidates` | 25 | 13 | 12 | 52% | 0 | 12 |
| redactor.py | `_plausible_secret_value` | 18 | 7 | 11 | 39% | 0 | 9 |
| redactor.py | `_load_capsuleignore` | 18 | 8 | 10 | 44% | 0 | 6 |
| redactor.py | `CapsuleRedactor.scan_and_raise` | 37 | 30 | 7 | 81% | 0 | 0 |
| redactor.py | `_charset_entropy` | 14 | 8 | 6 | 57% | 0 | 6 |
| redactor.py | `_iter_private_key_blocks` | 20 | 14 | 6 | 70% | 0 | 6 |
| redactor.py | `_iter_constructor_literals` | 20 | 14 | 6 | 70% | 0 | 6 |
| redactor.py | `finding_location` | 36 | 30 | 6 | 83% | 0 | 0 |
| redactor.py | `_finding_allowed` | 13 | 9 | 4 | 69% | 3 | 4 |
| redactor.py | `_is_ignored` | 13 | 10 | 3 | 77% | 0 | 3 |
| redactor.py | `_is_embedded_value` | 7 | 4 | 3 | 57% | 1 | 1 |
| redactor.py | `_looks_like_digest_line` | 2 | 0 | 2 | 0% | 0 | 0 |
| redactor.py | `_joined` | 3 | 1 | 2 | 33% | 0 | 1 |
| redactor.py | `CapsuleRedactor.__init__` | 18 | 16 | 2 | 89% | 0 | 0 |
| redactor.py | `_is_credential_file` | 16 | 15 | 1 | 94% | 1 | 1 |
| redactor.py | `_looks_binary` | 10 | 9 | 1 | 90% | 0 | 1 |

## Appendix — every surviving mutant

One row per survivor, grouped by function, sorted by line. `#` is mutmut's index within the function (`mutmut show marqov_capsule.<module>.<x_func>__mutmut_<#>` reproduces it; methods are spelled `xǁClassǁmethod`). Classes are defined in the TL;DR table. Where the first changed line repeats within the function (e.g. `continue`), the line was resolved from the diff hunk offset, not by text search.

### _canonical.py


**`_ManifestLoader.scan_directive`** — 5 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 88 | 7 | `raise ManifestError(f"unsupported manifest directive %{token.name}")` → `raise ManifestError(None)` | c1 |  |
| 90 | 17 | `raise ManifestError("manifest YAML directive must name 1.1 or 1.2")` → `raise ManifestError(None)` | c1 |  |
| 90 | 18 | `raise ManifestError("manifest YAML directive must name 1.1 or 1.2")` → `raise ManifestError("XXmanifest YAML directive must name 1.1 or 1.2XX…` | c1 |  |
| 90 | 19 | `raise ManifestError("manifest YAML directive must name 1.1 or 1.2")` → `raise ManifestError("manifest yaml directive must name 1.1 or 1.2")` | c1 |  |
| 90 | 20 | `raise ManifestError("manifest YAML directive must name 1.1 or 1.2")` → `raise ManifestError("MANIFEST YAML DIRECTIVE MUST NAME 1.1 OR 1.2")` | c1 |  |

**`_ManifestLoader.scan_flow_scalar_breaks`** — 16 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 94 | 2 | `chunks = super().scan_flow_scalar_breaks(double, start_mark)` → `chunks = super().scan_flow_scalar_breaks(None, start_mark)` | a | PyYAML ignores `double` in scan_flow_scalar_breaks |
| 94 | 3 | `chunks = super().scan_flow_scalar_breaks(double, start_mark)` → `chunks = super().scan_flow_scalar_breaks(double, None)` | c1 | error mark of the rare document-separator error |
| 99 | 6 | `if self.line > start_mark.line and self.indent >= 0:` → `if self.line > start_mark.line or self.indent >= 0:` | a | after a line break self.line > start line always holds; indent<0 passes the prefix check trivially |
| 99 | 7 | `if self.line > start_mark.line and self.indent >= 0:` → `if self.line >= start_mark.line and self.indent >= 0:` | a | after a line break self.line > start line always holds; indent<0 passes the prefix check trivially |
| 102 | 18 | `raise ScannerError("while scanning a quoted scalar", start_mark,` → `raise ScannerError(None, start_mark,` | c1 |  |
| 102 | 19 | `raise ScannerError("while scanning a quoted scalar", start_mark,` → `raise ScannerError("while scanning a quoted scalar", None,` | c1 |  |
| 102 | 22 | `raise ScannerError("while scanning a quoted scalar", start_mark,` → `raise ScannerError(start_mark,` | c1 |  |
| 102 | 23 | `raise ScannerError("while scanning a quoted scalar", start_mark, ⏎ "c…` → `raise ScannerError("while scanning a quoted scalar", "continuation mu…` | c1 |  |
| 102 | 26 | `raise ScannerError("while scanning a quoted scalar", start_mark,` → `raise ScannerError("XXwhile scanning a quoted scalarXX", start_mark,` | c1 |  |
| 102 | 27 | `raise ScannerError("while scanning a quoted scalar", start_mark,` → `raise ScannerError("WHILE SCANNING A QUOTED SCALAR", start_mark,` | c1 |  |
| 103 | 20 | `"continuation must be indented beyond its containing block",` → `None,` | c1 |  |
| 103 | 24 | `"continuation must be indented beyond its containing block",` → `(removed)` | c1 |  |
| 103 | 28 | `"continuation must be indented beyond its containing block",` → `"XXcontinuation must be indented beyond its containing blockXX",` | c1 |  |
| 103 | 29 | `"continuation must be indented beyond its containing block",` → `"CONTINUATION MUST BE INDENTED BEYOND ITS CONTAINING BLOCK",` | c1 |  |
| 104 | 21 | `self.get_mark())` → `None)` | c1 |  |
| 104 | 25 | `self.get_mark())` → `)` | c1 |  |

**`_reject_tag`** — 8 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 267 | 3 | `None, None,` → `None,` | c1 | message text / error mark |
| 267 | 4 | `None, None, ⏎ f"found tag {tag}: only the YAML core tags (str, int, f…` → `None, f"found tag {tag}: only the YAML core tags (str, int, float, bo…` | c1 | message text / error mark |
| 268 | 1 | `f"found tag {tag}: only the YAML core tags (str, int, float, bool, " …` → `None,` | c1 | message text / error mark |
| 268 | 5 | `f"found tag {tag}: only the YAML core tags (str, int, float, bool, " …` → `(removed)` | c1 | message text / error mark |
| 269 | 7 | `"null, seq, map) are permitted in a capsule manifest",` → `"XXnull, seq, map) are permitted in a capsule manifestXX",` | c1 | message text / error mark |
| 269 | 8 | `"null, seq, map) are permitted in a capsule manifest",` → `"NULL, SEQ, MAP) ARE PERMITTED IN A CAPSULE MANIFEST",` | c1 | message text / error mark |
| 270 | 2 | `node.start_mark,` → `None,` | c1 | message text / error mark |
| 270 | 6 | `node.start_mark, ⏎ )` → `)` | c1 | message text / error mark |

**`_canonical_number_str`** — 4 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 421 | 3 | `if isinstance(number, int) and not isinstance(number, bool) and abs(n…` → `if isinstance(number, int) and isinstance(number, bool) and abs(numbe…` | b | int-key safe-range guard disabled; jcs silently rounds 2**53 through float — kill: B13 |
| 421 | 5 | `if isinstance(number, int) and not isinstance(number, bool) and abs(n…` → `if isinstance(number, int) and not isinstance(number, bool) and abs(n…` | c4 | boundary: key exactly 2**53-1 would be rejected |
| 423 | 6 | `f"integer {number} exceeds the RFC 8785 safe range " ⏎ f"(\|n\| <= {_…` → `None` | c1 |  |
| 426 | 10 | `return jcs.canonicalize(number).decode("utf-8")` → `return jcs.canonicalize(number).decode("UTF-8")` | a | codec name case |

**`compute_capsule_id`** — 4 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 525 | 2 | `raise ValueError("a capsule manifest must be a mapping; " ⏎ f"got {ty…` → `raise ValueError(None)` | c1 |  |
| 525 | 3 | `raise ValueError("a capsule manifest must be a mapping; "` → `raise ValueError("XXa capsule manifest must be a mapping; XX"` | c1 |  |
| 525 | 4 | `raise ValueError("a capsule manifest must be a mapping; "` → `raise ValueError("A CAPSULE MANIFEST MUST BE A MAPPING; "` | c1 |  |
| 526 | 5 | `f"got {type(capsule_dict).__name__}")` → `f"got {type(None).__name__}")` | c1 |  |

**`parse_capsule_id`** — 1 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 540 | 4 | `raise ValueError(f"not a valid capsule ID: {capsule_id!r}")` → `raise ValueError(None)` | c1 |  |

### verifier.py


**`_is_within_root`** — 4 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 32 | 2 | `return False` → `return True` | c4 | absolute path to a file *inside* the capsule: resolve()+closed-set still fail the verdict, only `invalid` dif… |
| 33 | 5 | `root_str = os.path.abspath(str(root))` → `root_str = os.path.abspath(str(None))` | a | resolve()-based containment in _check_entry gives identical output (probed) |
| 34 | 11 | `full = os.path.abspath(os.path.join(root_str, rel_path))` → `full = os.path.abspath(os.path.join(root_str, ))` | a | resolve()-based containment in _check_entry gives identical output (probed) |
| 35 | 13 | `return full == root_str or full.startswith(root_str + os.sep)` → `return full != root_str or full.startswith(root_str + os.sep)` | c4 | only rel_path '.'/'' differ; neither is a regular file |

**`_parse_normative_checksums`** — 68 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 94 | 3 | `if raw == "":` → `if raw == "XXXX":` | a | empty text reaches the same {} through the loop |
| 96 | 5 | `if raw.startswith("\ufeff"):` → `if raw.startswith("XX\ufeffXX"):` | c1 | BOM then rejected as an unknown algorithm prefix instead |
| 96 | 6 | `if raw.startswith("\ufeff"):` → `if raw.startswith("\uFEFF"):` | a | same code point |
| 97 | 7 | `raise _ChecksumsGrammarError(1, "byte order mark is not permitted")` → `raise _ChecksumsGrammarError(None, "byte order mark is not permitted")` | c1 | grammar-error reason / line number text |
| 97 | 8 | `raise _ChecksumsGrammarError(1, "byte order mark is not permitted")` → `raise _ChecksumsGrammarError(1, None)` | c1 | grammar-error reason / line number text |
| 97 | 11 | `raise _ChecksumsGrammarError(1, "byte order mark is not permitted")` → `raise _ChecksumsGrammarError(2, "byte order mark is not permitted")` | c1 | grammar-error reason / line number text |
| 97 | 12 | `raise _ChecksumsGrammarError(1, "byte order mark is not permitted")` → `raise _ChecksumsGrammarError(1, "XXbyte order mark is not permittedXX…` | c1 | grammar-error reason / line number text |
| 97 | 13 | `raise _ChecksumsGrammarError(1, "byte order mark is not permitted")` → `raise _ChecksumsGrammarError(1, "BYTE ORDER MARK IS NOT PERMITTED")` | c1 | grammar-error reason / line number text |
| 104 | 28 | `raise _ChecksumsGrammarError(line_no, "blank line")` → `raise _ChecksumsGrammarError(None, "blank line")` | c1 | grammar-error reason / line number text |
| 104 | 29 | `raise _ChecksumsGrammarError(line_no, "blank line")` → `raise _ChecksumsGrammarError(line_no, None)` | c1 | grammar-error reason / line number text |
| 104 | 32 | `raise _ChecksumsGrammarError(line_no, "blank line")` → `raise _ChecksumsGrammarError(line_no, "XXblank lineXX")` | c1 | grammar-error reason / line number text |
| 104 | 33 | `raise _ChecksumsGrammarError(line_no, "blank line")` → `raise _ChecksumsGrammarError(line_no, "BLANK LINE")` | c1 | grammar-error reason / line number text |
| 107 | 38 | `token = line.split(" ", 1)[0]` → `token = line.split(None, 1)[0]` | c1 | already-malformed branch: only which reason is reported changes |
| 107 | 41 | `token = line.split(" ", 1)[0]` → `token = line.split(" ", )[0]` | c1 | already-malformed branch: only which reason is reported changes |
| 107 | 42 | `token = line.split(" ", 1)[0]` → `token = line.rsplit(" ", 1)[0]` | c1 | already-malformed branch: only which reason is reported changes |
| 107 | 43 | `token = line.split(" ", 1)[0]` → `token = line.split("XX XX", 1)[0]` | c1 | already-malformed branch: only which reason is reported changes |
| 107 | 44 | `token = line.split(" ", 1)[0]` → `token = line.split(" ", 2)[0]` | c1 | already-malformed branch: only which reason is reported changes |
| 108 | 48 | `algorithm, sep, digest = token.partition(":")` → `algorithm, sep, digest = token.rpartition(":")` | c1 | already-malformed branch: only which reason is reported changes |
| 108 | 49 | `algorithm, sep, digest = token.partition(":")` → `algorithm, sep, digest = token.partition("XX:XX")` | c1 | already-malformed branch: only which reason is reported changes |
| 109 | 51 | `if not sep or algorithm != "sha256":` → `if sep or algorithm != "sha256":` | c1 | already-malformed branch: only which reason is reported changes |
| 109 | 53 | `if not sep or algorithm != "sha256":` → `if not sep or algorithm != "XXsha256XX":` | c1 | already-malformed branch: only which reason is reported changes |
| 109 | 54 | `if not sep or algorithm != "sha256":` → `if not sep or algorithm != "SHA256":` | c1 | already-malformed branch: only which reason is reported changes |
| 111 | 59 | `line_no, f"unrecognised digest algorithm prefix {algorithm[:20]!r} (e…` → `line_no, f"unrecognised digest algorithm prefix {algorithm[:21]!r} (e…` | c1 | grammar-error reason / line number text |
| 112 | 60 | `if not re.fullmatch(r"[0-9a-f]{64}", digest):` → `if re.fullmatch(r"[0-9a-f]{64}", digest):` | c1 | already-malformed branch: only which reason is reported changes |
| 112 | 65 | `if not re.fullmatch(r"[0-9a-f]{64}", digest):` → `if not re.fullmatch(r"XX[0-9a-f]{64}XX", digest):` | c1 | already-malformed branch: only which reason is reported changes |
| 112 | 66 | `if not re.fullmatch(r"[0-9a-f]{64}", digest):` → `if not re.fullmatch(r"[0-9A-F]{64}", digest):` | c1 | already-malformed branch: only which reason is reported changes |
| 113 | 67 | `raise _ChecksumsGrammarError(line_no, "digest must be 64 lowercase he…` → `raise _ChecksumsGrammarError(None, "digest must be 64 lowercase hex c…` | c1 | grammar-error reason / line number text |
| 113 | 68 | `raise _ChecksumsGrammarError(line_no, "digest must be 64 lowercase he…` → `raise _ChecksumsGrammarError(line_no, None)` | c1 | grammar-error reason / line number text |
| 113 | 71 | `raise _ChecksumsGrammarError(line_no, "digest must be 64 lowercase he…` → `raise _ChecksumsGrammarError(line_no, "XXdigest must be 64 lowercase …` | c1 | grammar-error reason / line number text |
| 113 | 72 | `raise _ChecksumsGrammarError(line_no, "digest must be 64 lowercase he…` → `raise _ChecksumsGrammarError(line_no, "DIGEST MUST BE 64 LOWERCASE HE…` | c1 | grammar-error reason / line number text |
| 117 | 74 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError(None, "control character (lines end with…` | c1 | grammar-error reason / line number text |
| 117 | 75 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError(line_no, None)` | c1 | grammar-error reason / line number text |
| 117 | 76 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError("control character (lines end with a sin…` | b | _ChecksumsGrammarError called with wrong arity -> TypeError escapes verify_checksums as a traceback — kill: B6 |
| 117 | 77 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError(line_no, )` | b | _ChecksumsGrammarError called with wrong arity -> TypeError escapes verify_checksums as a traceback — kill: B6 |
| 117 | 78 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError(line_no, "XXcontrol character (lines end…` | c1 | grammar-error reason / line number text |
| 117 | 79 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` | c1 | grammar-error reason / line number text |
| 117 | 80 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError(line_no, "CONTROL CHARACTER (LINES END W…` | c1 | grammar-error reason / line number text |
| 118 | 81 | `raise _ChecksumsGrammarError(line_no, "digest and path must be separa…` → `raise _ChecksumsGrammarError(None, "digest and path must be separated…` | c1 | grammar-error reason / line number text |
| 118 | 82 | `raise _ChecksumsGrammarError(line_no, "digest and path must be separa…` → `raise _ChecksumsGrammarError(line_no, None)` | c1 | grammar-error reason / line number text |
| 118 | 85 | `raise _ChecksumsGrammarError(line_no, "digest and path must be separa…` → `raise _ChecksumsGrammarError(line_no, "XXdigest and path must be sepa…` | c1 | grammar-error reason / line number text |
| 118 | 86 | `raise _ChecksumsGrammarError(line_no, "digest and path must be separa…` → `raise _ChecksumsGrammarError(line_no, "DIGEST AND PATH MUST BE SEPARA…` | c1 | grammar-error reason / line number text |
| 125 | 91 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError(None, "control character (lines end with…` | c1 | grammar-error reason / line number text |
| 125 | 92 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError(line_no, None)` | c1 | grammar-error reason / line number text |
| 125 | 95 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError(line_no, "XXcontrol character (lines end…` | c1 | grammar-error reason / line number text |
| 125 | 96 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` | c1 | grammar-error reason / line number text |
| 125 | 97 | `raise _ChecksumsGrammarError(line_no, "control character (lines end w…` → `raise _ChecksumsGrammarError(line_no, "CONTROL CHARACTER (LINES END W…` | c1 | grammar-error reason / line number text |
| 126 | 98 | `if len(name.encode("utf-8")) > _MAX_CHECKSUM_PATH_BYTES:` → `if len(name.encode("utf-8")) >= _MAX_CHECKSUM_PATH_BYTES:` | c4 | path-length boundary |
| 127 | 99 | `raise _ChecksumsGrammarError(line_no, "path is too long")` → `raise _ChecksumsGrammarError(None, "path is too long")` | c1 | grammar-error reason / line number text |
| 127 | 100 | `raise _ChecksumsGrammarError(line_no, "path is too long")` → `raise _ChecksumsGrammarError(line_no, None)` | c1 | grammar-error reason / line number text |
| 127 | 103 | `raise _ChecksumsGrammarError(line_no, "path is too long")` → `raise _ChecksumsGrammarError(line_no, "XXpath is too longXX")` | c1 | grammar-error reason / line number text |
| 127 | 104 | `raise _ChecksumsGrammarError(line_no, "path is too long")` → `raise _ChecksumsGrammarError(line_no, "PATH IS TOO LONG")` | c1 | grammar-error reason / line number text |
| 128 | 114 | `decoded = re.sub(r"%[0-9A-Fa-f]{2}", lambda m: _PATH_ESCAPES.get(m[0]…` → `decoded = re.sub(r"%[0-9A-FA-F]{2}", lambda m: _PATH_ESCAPES.get(m[0]…` | a | unknown/lowercase escapes are rejected by the re-encode check either way (re.sub treats None as '') |
| 128 | 117 | `decoded = re.sub(r"%[0-9A-Fa-f]{2}", lambda m: _PATH_ESCAPES.get(m[0]…` → `decoded = re.sub(r"%[0-9A-Fa-f]{2}", lambda m: _PATH_ESCAPES.get(m[0]…` | a | unknown/lowercase escapes are rejected by the re-encode check either way (re.sub treats None as '') |
| 128 | 118 | `decoded = re.sub(r"%[0-9A-Fa-f]{2}", lambda m: _PATH_ESCAPES.get(m[0]…` → `decoded = re.sub(r"%[0-9A-Fa-f]{2}", lambda m: _PATH_ESCAPES.get(m[0]…` | a | unknown/lowercase escapes are rejected by the re-encode check either way (re.sub treats None as '') |
| 128 | 119 | `decoded = re.sub(r"%[0-9A-Fa-f]{2}", lambda m: _PATH_ESCAPES.get(m[0]…` → `decoded = re.sub(r"%[0-9A-Fa-f]{2}", lambda m: _PATH_ESCAPES.get(m[0]…` | a | unknown/lowercase escapes are rejected by the re-encode check either way (re.sub treats None as '') |
| 132 | 124 | `raise _ChecksumsGrammarError(line_no, "path is not in canonical encod…` → `raise _ChecksumsGrammarError(None, "path is not in canonical encoded …` | c1 | grammar-error reason / line number text |
| 132 | 125 | `raise _ChecksumsGrammarError(line_no, "path is not in canonical encod…` → `raise _ChecksumsGrammarError(line_no, None)` | c1 | grammar-error reason / line number text |
| 132 | 128 | `raise _ChecksumsGrammarError(line_no, "path is not in canonical encod…` → `raise _ChecksumsGrammarError(line_no, "XXpath is not in canonical enc…` | c1 | grammar-error reason / line number text |
| 132 | 129 | `raise _ChecksumsGrammarError(line_no, "path is not in canonical encod…` → `raise _ChecksumsGrammarError(line_no, "PATH IS NOT IN CANONICAL ENCOD…` | c1 | grammar-error reason / line number text |
| 134 | 131 | `raise _ChecksumsGrammarError(line_no, "duplicate path")` → `raise _ChecksumsGrammarError(None, "duplicate path")` | c1 | grammar-error reason / line number text |
| 134 | 132 | `raise _ChecksumsGrammarError(line_no, "duplicate path")` → `raise _ChecksumsGrammarError(line_no, None)` | c1 | grammar-error reason / line number text |
| 134 | 135 | `raise _ChecksumsGrammarError(line_no, "duplicate path")` → `raise _ChecksumsGrammarError(line_no, "XXduplicate pathXX")` | c1 | grammar-error reason / line number text |
| 134 | 136 | `raise _ChecksumsGrammarError(line_no, "duplicate path")` → `raise _ChecksumsGrammarError(line_no, "DUPLICATE PATH")` | c1 | grammar-error reason / line number text |
| 137 | 140 | `raise _ChecksumsGrammarError(len(lines), "missing the final LF")` → `raise _ChecksumsGrammarError(None, "missing the final LF")` | c1 | grammar-error reason / line number text |
| 137 | 141 | `raise _ChecksumsGrammarError(len(lines), "missing the final LF")` → `raise _ChecksumsGrammarError(len(lines), None)` | c1 | grammar-error reason / line number text |
| 137 | 144 | `raise _ChecksumsGrammarError(len(lines), "missing the final LF")` → `raise _ChecksumsGrammarError(len(lines), "XXmissing the final LFXX")` | c1 | grammar-error reason / line number text |
| 137 | 145 | `raise _ChecksumsGrammarError(len(lines), "missing the final LF")` → `raise _ChecksumsGrammarError(len(lines), "missing the final lf")` | c1 | grammar-error reason / line number text |
| 137 | 146 | `raise _ChecksumsGrammarError(len(lines), "missing the final LF")` → `raise _ChecksumsGrammarError(len(lines), "MISSING THE FINAL LF")` | c1 | grammar-error reason / line number text |

**`_require_numpy`** — 6 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 148 | 1 | `"Statistical verification requires numpy and scipy: " ⏎ "pip install …` → `None` | c1 |  |
| 148 | 2 | `"Statistical verification requires numpy and scipy: "` → `"XXStatistical verification requires numpy and scipy: XX"` | c1 |  |
| 148 | 3 | `"Statistical verification requires numpy and scipy: "` → `"statistical verification requires numpy and scipy: "` | c1 |  |
| 148 | 4 | `"Statistical verification requires numpy and scipy: "` → `"STATISTICAL VERIFICATION REQUIRES NUMPY AND SCIPY: "` | c1 |  |
| 149 | 5 | `"pip install numpy scipy"` → `"XXpip install numpy scipyXX"` | c1 |  |
| 149 | 6 | `"pip install numpy scipy"` → `"PIP INSTALL NUMPY SCIPY"` | c1 |  |

**`_tvd_upper_confidence_bound`** — 1 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 171 | 1 | `alpha: float = 0.05,` → `alpha: float = 1.05,` | a | default alpha never used; caller passes alpha |

**`_compute_chi_squared_p`** — 18 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 228 | 14 | `ref_obs = np.array([ref_counts.get(k, 0) for k in all_keys], dtype=fl…` → `ref_obs = np.array([ref_counts.get(k, 0) for k in all_keys], dtype=No…` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 228 | 16 | `ref_obs = np.array([ref_counts.get(k, 0) for k in all_keys], dtype=fl…` → `ref_obs = np.array([ref_counts.get(k, 0) for k in all_keys], ) + 0.5` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 228 | 18 | `ref_obs = np.array([ref_counts.get(k, 0) for k in all_keys], dtype=fl…` → `ref_obs = np.array([ref_counts.get(k, None) for k in all_keys], dtype…` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 228 | 20 | `ref_obs = np.array([ref_counts.get(k, 0) for k in all_keys], dtype=fl…` → `ref_obs = np.array([ref_counts.get(k, ) for k in all_keys], dtype=flo…` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 228 | 21 | `ref_obs = np.array([ref_counts.get(k, 0) for k in all_keys], dtype=fl…` → `ref_obs = np.array([ref_counts.get(k, 1) for k in all_keys], dtype=fl…` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 229 | 25 | `new_raw = np.array([new_counts.get(k, 0) for k in all_keys], dtype=fl…` → `new_raw = np.array([new_counts.get(k, 0) for k in all_keys], dtype=No…` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 229 | 27 | `new_raw = np.array([new_counts.get(k, 0) for k in all_keys], dtype=fl…` → `new_raw = np.array([new_counts.get(k, 0) for k in all_keys], )` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 229 | 29 | `new_raw = np.array([new_counts.get(k, 0) for k in all_keys], dtype=fl…` → `new_raw = np.array([new_counts.get(k, None) for k in all_keys], dtype…` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 229 | 31 | `new_raw = np.array([new_counts.get(k, 0) for k in all_keys], dtype=fl…` → `new_raw = np.array([new_counts.get(k, ) for k in all_keys], dtype=flo…` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 229 | 32 | `new_raw = np.array([new_counts.get(k, 0) for k in all_keys], dtype=fl…` → `new_raw = np.array([new_counts.get(k, 1) for k in all_keys], dtype=fl…` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 230 | 35 | `new_scaled = new_raw * (n_ref / n_new) + 0.5` → `new_scaled = new_raw / (n_ref / n_new) + 0.5` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 231 | 38 | `if np.all(ref_obs >= 5) and np.all(new_scaled >= 5):` → `if np.all(ref_obs >= 5) or np.all(new_scaled >= 5):` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 231 | 40 | `if np.all(ref_obs >= 5) and np.all(new_scaled >= 5):` → `if np.all(ref_obs > 5) and np.all(new_scaled >= 5):` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 231 | 41 | `if np.all(ref_obs >= 5) and np.all(new_scaled >= 5):` → `if np.all(ref_obs >= 6) and np.all(new_scaled >= 5):` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 231 | 43 | `if np.all(ref_obs >= 5) and np.all(new_scaled >= 5):` → `if np.all(ref_obs >= 5) and np.all(new_scaled > 5):` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 231 | 44 | `if np.all(ref_obs >= 5) and np.all(new_scaled >= 5):` → `if np.all(ref_obs >= 5) and np.all(new_scaled >= 6):` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 233 | 47 | `_, p_value = ss.chisquare(new_scaled, f_exp=ref_obs)` → `_, p_value = ss.chisquare(new_scaled, f_exp=None)` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |
| 233 | 49 | `_, p_value = ss.chisquare(new_scaled, f_exp=ref_obs)` → `_, p_value = ss.chisquare(new_scaled, )` | c3 | chi-squared p-value is diagnostic only; no test pins its value or its cell-count gate |

**`_compute_energy_distance`** — 11 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 257 | 8 | `if len(all_keys) > _ENERGY_DISTANCE_MAX_OUTCOMES:` → `if len(all_keys) >= _ENERGY_DISTANCE_MAX_OUTCOMES:` | c4 | OOM guard boundary at exactly 2000 outcomes |
| 262 | 15 | `ref_probs = np.array([ref_counts.get(k, 0) / n_ref for k in all_keys])` → `ref_probs = np.array([ref_counts.get(k, 0) * n_ref for k in all_keys])` | c3 | energy distance is diagnostic only; no test pins its value |
| 262 | 20 | `ref_probs = np.array([ref_counts.get(k, 0) / n_ref for k in all_keys])` → `ref_probs = np.array([ref_counts.get(k, 1) / n_ref for k in all_keys])` | c3 | energy distance is diagnostic only; no test pins its value |
| 263 | 23 | `new_probs = np.array([new_counts.get(k, 0) / n_new for k in all_keys])` → `new_probs = np.array([new_counts.get(k, 0) * n_new for k in all_keys])` | c3 | energy distance is diagnostic only; no test pins its value |
| 263 | 28 | `new_probs = np.array([new_counts.get(k, 0) / n_new for k in all_keys])` → `new_probs = np.array([new_counts.get(k, 1) / n_new for k in all_keys])` | c3 | energy distance is diagnostic only; no test pins its value |
| 265 | 30 | `key_len = max(len(k) for k in all_keys) or 1` → `key_len = max(len(k) for k in all_keys) and 1` | c3 | energy distance is diagnostic only; no test pins its value |
| 265 | 32 | `key_len = max(len(k) for k in all_keys) or 1` → `key_len = max(len(k) for k in all_keys) or 2` | c3 | energy distance is diagnostic only; no test pins its value |
| 273 | 40 | `d[i, j] = sum(a != b for a, b in zip(all_keys[i], all_keys[j])) / key…` → `d[i, j] = sum(a != b for a, b in zip(all_keys[i], all_keys[j])) * key…` | c3 | energy distance is diagnostic only; no test pins its value |
| 278 | 53 | `return 2.0 * e_pq - e_pp - e_qq` → `return 2.0 * e_pq - e_pp + e_qq` | c3 | energy distance is diagnostic only; no test pins its value |
| 278 | 54 | `return 2.0 * e_pq - e_pp - e_qq` → `return 2.0 * e_pq + e_pp - e_qq` | c3 | energy distance is diagnostic only; no test pins its value |
| 278 | 56 | `return 2.0 * e_pq - e_pp - e_qq` → `return 3.0 * e_pq - e_pp - e_qq` | c3 | energy distance is diagnostic only; no test pins its value |

**`_check_entry`** — 38 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 293 | 3 | `detail = {"expected": expected_digest, "actual": actual, "match": mat…` → `detail = {"XXexpectedXX": expected_digest, "actual": actual, "match":…` | c2 | per-file record keys / error detail |
| 293 | 4 | `detail = {"expected": expected_digest, "actual": actual, "match": mat…` → `detail = {"EXPECTED": expected_digest, "actual": actual, "match": mat…` | c2 | per-file record keys / error detail |
| 295 | 9 | `detail["error"] = error` → `detail["error"] = None` | c2 | per-file record keys / error detail |
| 295 | 10 | `detail["error"] = error` → `detail["XXerrorXX"] = error` | c2 | per-file record keys / error detail |
| 295 | 11 | `detail["error"] = error` → `detail["ERROR"] = error` | c2 | per-file record keys / error detail |
| 300 | 14 | `if not _is_within_root(rel_path, capsule_path):` → `if not _is_within_root(rel_path, None):` | a | lexical anchor: any absolute root gives the same verdict |
| 301 | 19 | `return "invalid", record("path escapes capsule root")` → `return "invalid", record(None)` | c1 |  |
| 301 | 20 | `return "invalid", record("path escapes capsule root")` → `return "invalid", record("XXpath escapes capsule rootXX")` | c1 |  |
| 301 | 21 | `return "invalid", record("path escapes capsule root")` → `return "invalid", record("PATH ESCAPES CAPSULE ROOT")` | c1 |  |
| 302 | 22 | `normalized = unicodedata.normalize("NFC", rel_path)` → `normalized = None` | c5 | NFC->on-disk mapping disabled; APFS is normalisation-insensitive so the plain path still resolves |
| 304 | 30 | `return "colliding", None` → `return "XXcollidingXX", None` | a | kind 'colliding' is never compared by the caller |
| 304 | 31 | `return "colliding", None` → `return "COLLIDING", None` | a | kind 'colliding' is never compared by the caller |
| 305 | 33 | `file_path = actual_paths.get(normalized, capsule_path / rel_path)` → `file_path = actual_paths.get(None, capsule_path / rel_path)` | c5 | NFC->on-disk mapping disabled; APFS is normalisation-insensitive so the plain path still resolves |
| 308 | 38 | `return "symlink", record("symlink not permitted")` → `return "XXsymlinkXX", record("symlink not permitted")` | c2 | kind string -> entry dropped from symlinks/missing/mismatched list; status unchanged |
| 308 | 39 | `return "symlink", record("symlink not permitted")` → `return "SYMLINK", record("symlink not permitted")` | c2 | kind string -> entry dropped from symlinks/missing/mismatched list; status unchanged |
| 308 | 40 | `return "symlink", record("symlink not permitted")` → `return "symlink", record(None)` | c1 |  |
| 308 | 41 | `return "symlink", record("symlink not permitted")` → `return "symlink", record("XXsymlink not permittedXX")` | c2 | kind string -> entry dropped from symlinks/missing/mismatched list; status unchanged |
| 308 | 42 | `return "symlink", record("symlink not permitted")` → `return "symlink", record("SYMLINK NOT PERMITTED")` | c2 | kind string -> entry dropped from symlinks/missing/mismatched list; status unchanged |
| 316 | 44 | `resolved = None` → `resolved = ""` | c4 | resolve() failure branch; Python 3.13 non-strict realpath no longer raises on loops/NAME_MAX |
| 318 | 49 | `return "invalid", record("path escapes capsule root")` → `return "XXinvalidXX", record("path escapes capsule root")` | c1 |  |
| 318 | 50 | `return "invalid", record("path escapes capsule root")` → `return "INVALID", record("path escapes capsule root")` | c1 |  |
| 318 | 51 | `return "invalid", record("path escapes capsule root")` → `return "invalid", record(None)` | c1 |  |
| 318 | 52 | `return "invalid", record("path escapes capsule root")` → `return "invalid", record("XXpath escapes capsule rootXX")` | c1 |  |
| 318 | 53 | `return "invalid", record("path escapes capsule root")` → `return "invalid", record("PATH ESCAPES CAPSULE ROOT")` | c1 |  |
| 320 | 55 | `return "missing", record()` → `return "XXmissingXX", record()` | c2 | kind string -> entry dropped from symlinks/missing/mismatched list; status unchanged |
| 320 | 56 | `return "missing", record()` → `return "MISSING", record()` | c2 | kind string -> entry dropped from symlinks/missing/mismatched list; status unchanged |
| 322 | 60 | `return "invalid", record("not a regular file")` → `return "invalid", record(None)` | c1 |  |
| 322 | 61 | `return "invalid", record("not a regular file")` → `return "invalid", record("XXnot a regular fileXX")` | c1 |  |
| 322 | 62 | `return "invalid", record("not a regular file")` → `return "invalid", record("NOT A REGULAR FILE")` | c1 |  |
| 326 | 68 | `return "invalid", record("payload could not be read")` → `return "XXinvalidXX", record("payload could not be read")` | c1 |  |
| 326 | 69 | `return "invalid", record("payload could not be read")` → `return "INVALID", record("payload could not be read")` | c1 |  |
| 326 | 70 | `return "invalid", record("payload could not be read")` → `return "invalid", record(None)` | c1 |  |
| 326 | 71 | `return "invalid", record("payload could not be read")` → `return "invalid", record("XXpayload could not be readXX")` | c1 |  |
| 326 | 72 | `return "invalid", record("payload could not be read")` → `return "invalid", record("PAYLOAD COULD NOT BE READ")` | c1 |  |
| 328 | 79 | `return ("match" if match else "mismatch"), record(actual=actual, matc…` → `return ("match" if match else "XXmismatchXX"), record(actual=actual, …` | c2 | kind string -> entry dropped from symlinks/missing/mismatched list; status unchanged |
| 328 | 80 | `return ("match" if match else "mismatch"), record(actual=actual, matc…` → `return ("match" if match else "MISMATCH"), record(actual=actual, matc…` | c2 | kind string -> entry dropped from symlinks/missing/mismatched list; status unchanged |
| 328 | 81 | `return ("match" if match else "mismatch"), record(actual=actual, matc…` → `return ("match" if match else "mismatch"), record(actual=None, match=…` | c2 | actual digest omitted from the record |
| 328 | 83 | `return ("match" if match else "mismatch"), record(actual=actual, matc…` → `return ("match" if match else "mismatch"), record(match=match)` | c2 | actual digest omitted from the record |

**`CapsuleVerifier.__init__`** — 9 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 342 | 8 | `"CapsuleVerifier(schema_path=...) is ignored and will be removed: "` → `"XXCapsuleVerifier(schema_path=...) is ignored and will be removed: X…` | c1 | deprecation text / stacklevel |
| 342 | 9 | `"CapsuleVerifier(schema_path=...) is ignored and will be removed: "` → `"capsuleverifier(schema_path=...) is ignored and will be removed: "` | c1 | deprecation text / stacklevel |
| 343 | 11 | `"the verifier does not validate against a schema; use "` → `"XXthe verifier does not validate against a schema; use XX"` | c1 | deprecation text / stacklevel |
| 343 | 12 | `"the verifier does not validate against a schema; use "` → `"THE VERIFIER DOES NOT VALIDATE AGAINST A SCHEMA; USE "` | c1 | deprecation text / stacklevel |
| 344 | 13 | `"CapsuleValidator.validate().",` → `"XXCapsuleValidator.validate().XX",` | c1 | deprecation text / stacklevel |
| 344 | 14 | `"CapsuleValidator.validate().",` → `"capsulevalidator.validate().",` | c1 | deprecation text / stacklevel |
| 344 | 15 | `"CapsuleValidator.validate().",` → `"CAPSULEVALIDATOR.VALIDATE().",` | c1 | deprecation text / stacklevel |
| 346 | 7 | `stacklevel=2, ⏎ )` → `)` | c1 | deprecation text / stacklevel |
| 346 | 16 | `stacklevel=2,` → `stacklevel=3,` | c1 | deprecation text / stacklevel |

**`CapsuleVerifier.verify_statistical`** — 39 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 401 | 8 | `min_shots = verification_settings.get("min_shots", 100)` → `min_shots = verification_settings.get("min_shots", 101)` | c4 | settings defaults (min_shots 100, epsilon 0.02) never exercised; missing epsilon would raise TypeError |
| 402 | 11 | `tolerance_regime = verification_settings.get("tolerance_regime", "str…` → `tolerance_regime = verification_settings.get("tolerance_regime", None)` | a | default regime only compared against 'calibration_drift' |
| 402 | 13 | `tolerance_regime = verification_settings.get("tolerance_regime", "str…` → `tolerance_regime = verification_settings.get("tolerance_regime", )` | a | default regime only compared against 'calibration_drift' |
| 402 | 16 | `tolerance_regime = verification_settings.get("tolerance_regime", "str…` → `tolerance_regime = verification_settings.get("tolerance_regime", "XXs…` | a | default regime only compared against 'calibration_drift' |
| 402 | 17 | `tolerance_regime = verification_settings.get("tolerance_regime", "str…` → `tolerance_regime = verification_settings.get("tolerance_regime", "STR…` | a | default regime only compared against 'calibration_drift' |
| 403 | 20 | `epsilon = verification_settings.get("epsilon", 0.02)` → `epsilon = verification_settings.get("epsilon", None)` | c4 | settings defaults (min_shots 100, epsilon 0.02) never exercised; missing epsilon would raise TypeError |
| 403 | 22 | `epsilon = verification_settings.get("epsilon", 0.02)` → `epsilon = verification_settings.get("epsilon", )` | c4 | settings defaults (min_shots 100, epsilon 0.02) never exercised; missing epsilon would raise TypeError |
| 403 | 25 | `epsilon = verification_settings.get("epsilon", 0.02)` → `epsilon = verification_settings.get("epsilon", 1.02)` | c4 | settings defaults (min_shots 100, epsilon 0.02) never exercised; missing epsilon would raise TypeError |
| 410 | 47 | `ref_counts = _normalise_counts(ref_counts, "ref_counts")` → `ref_counts = _normalise_counts(ref_counts, "XXref_countsXX")` | c1 |  |
| 411 | 54 | `new_counts = _normalise_counts(new_counts, "new_counts")` → `new_counts = _normalise_counts(new_counts, "XXnew_countsXX")` | c1 |  |
| 419 | 71 | `"reason": "one or both arms have zero shots; TVD is undefined",` → `"reason": "XXone or both arms have zero shots; TVD is undefinedXX",` | c1 |  |
| 419 | 72 | `"reason": "one or both arms have zero shots; TVD is undefined",` → `"reason": "one or both arms have zero shots; tvd is undefined",` | c1 |  |
| 419 | 73 | `"reason": "one or both arms have zero shots; TVD is undefined",` → `"reason": "ONE OR BOTH ARMS HAVE ZERO SHOTS; TVD IS UNDEFINED",` | c1 |  |
| 421 | 76 | `"epsilon_used": epsilon,` → `"XXepsilon_usedXX": epsilon,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 421 | 77 | `"epsilon_used": epsilon,` → `"EPSILON_USED": epsilon,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 422 | 78 | `"shots_ref": n_ref,` → `"XXshots_refXX": n_ref,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 422 | 79 | `"shots_ref": n_ref,` → `"SHOTS_REF": n_ref,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 423 | 80 | `"shots_new": n_new,` → `"XXshots_newXX": n_new,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 423 | 81 | `"shots_new": n_new,` → `"SHOTS_NEW": n_new,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 424 | 82 | `"min_shots": min_shots,` → `"XXmin_shotsXX": min_shots,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 424 | 83 | `"min_shots": min_shots,` → `"MIN_SHOTS": min_shots,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 435 | 98 | `"epsilon_used": epsilon,` → `"XXepsilon_usedXX": epsilon,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 435 | 99 | `"epsilon_used": epsilon,` → `"EPSILON_USED": epsilon,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 436 | 100 | `"shots_ref": n_ref,` → `"XXshots_refXX": n_ref,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 436 | 101 | `"shots_ref": n_ref,` → `"SHOTS_REF": n_ref,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 437 | 102 | `"shots_new": n_new,` → `"XXshots_newXX": n_new,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 437 | 103 | `"shots_new": n_new,` → `"SHOTS_NEW": n_new,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 438 | 104 | `"min_shots": min_shots,` → `"XXmin_shotsXX": min_shots,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 438 | 105 | `"min_shots": min_shots,` → `"MIN_SHOTS": min_shots,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 451 | 132 | `"shots_ref": n_ref,` → `"XXshots_refXX": n_ref,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 451 | 133 | `"shots_ref": n_ref,` → `"SHOTS_REF": n_ref,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 452 | 134 | `"shots_new": n_new,` → `"XXshots_newXX": n_new,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 452 | 135 | `"shots_new": n_new,` → `"SHOTS_NEW": n_new,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 455 | 137 | `metrics["chi_squared_p_value"] = chi2_p` → `metrics["chi_squared_p_value"] = None` | c3 |  |
| 459 | 144 | `if tvd_ucb <= epsilon:` → `if tvd_ucb < epsilon:` | c4 | tvd_ucb == epsilon exactly |
| 461 | 148 | `reason = f"tvd_ucb ({tvd_ucb:.4f}) <= epsilon ({epsilon})"` → `reason = None` | c1 |  |
| 464 | 152 | `reason = f"tvd_ucb ({tvd_ucb:.4f}) > epsilon ({epsilon}); TVD = {tvd_…` → `reason = None` | c1 |  |
| 468 | 155 | `"reason": reason,` → `"XXreasonXX": reason,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |
| 468 | 156 | `"reason": reason,` → `"REASON": reason,` | c2 | metrics keys in INCONCLUSIVE returns / reason key |

**`CapsuleVerifier.verify_deterministic`** — 11 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 479 | 3 | `s = json.dumps(obj, sort_keys=True, default=str)` → `s = json.dumps(obj, sort_keys=None, default=str)` | b | key order treated as significant -> equal data REJECTED — kill: B5 |
| 479 | 4 | `s = json.dumps(obj, sort_keys=True, default=str)` → `s = json.dumps(obj, sort_keys=True, default=None)` | b | non-JSON scalars (datetime) raise instead of comparing — kill: B5 |
| 479 | 6 | `s = json.dumps(obj, sort_keys=True, default=str)` → `s = json.dumps(obj, default=str)` | b | key order treated as significant -> equal data REJECTED — kill: B5 |
| 479 | 7 | `s = json.dumps(obj, sort_keys=True, default=str)` → `s = json.dumps(obj, sort_keys=True, )` | b | non-JSON scalars (datetime) raise instead of comparing — kill: B5 |
| 479 | 8 | `s = json.dumps(obj, sort_keys=True, default=str)` → `s = json.dumps(obj, sort_keys=False, default=str)` | b | key order treated as significant -> equal data REJECTED — kill: B5 |
| 480 | 10 | `return "sha256:" + hashlib.sha256(s.encode()).hexdigest()` → `return "XXsha256:XX" + hashlib.sha256(s.encode()).hexdigest()` | c2 | digest prefix / result keys |
| 480 | 11 | `return "sha256:" + hashlib.sha256(s.encode()).hexdigest()` → `return "SHA256:" + hashlib.sha256(s.encode()).hexdigest()` | c2 | digest prefix / result keys |
| 487 | 27 | `"ref_digest": ref_digest,` → `"XXref_digestXX": ref_digest,` | c2 | digest prefix / result keys |
| 487 | 28 | `"ref_digest": ref_digest,` → `"REF_DIGEST": ref_digest,` | c2 | digest prefix / result keys |
| 488 | 29 | `"new_digest": new_digest,` → `"XXnew_digestXX": new_digest,` | c2 | digest prefix / result keys |
| 488 | 30 | `"new_digest": new_digest,` → `"NEW_DIGEST": new_digest,` | c2 | digest prefix / result keys |

**`CapsuleVerifier.verify_checksums`** — 101 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 507 | 6 | `checksums_file = capsule_path / ".checksums"` → `checksums_file = capsule_path / ".CHECKSUMS"` | c5 | '.CHECKSUMS' found on case-insensitive APFS |
| 510 | 11 | `"status": "fail",` → `"status": "XXfailXX",` | b | missing/undecodable .checksums early return: status/passed can be flipped — kill: B1 |
| 510 | 12 | `"status": "fail",` → `"status": "FAIL",` | b | missing/undecodable .checksums early return: status/passed can be flipped — kill: B1 |
| 511 | 13 | `"passed": False,` → `"XXpassedXX": False,` | c2 | early-return dict keys |
| 511 | 14 | `"passed": False,` → `"PASSED": False,` | c2 | early-return dict keys |
| 511 | 15 | `"passed": False,` → `"passed": True,` | b | missing/undecodable .checksums early return: status/passed can be flipped — kill: B1 |
| 512 | 16 | `"error": ".checksums missing or not a regular file",` → `"XXerrorXX": ".checksums missing or not a regular file",` | c2 | early-return dict keys |
| 512 | 17 | `"error": ".checksums missing or not a regular file",` → `"ERROR": ".checksums missing or not a regular file",` | c2 | early-return dict keys |
| 512 | 18 | `"error": ".checksums missing or not a regular file",` → `"error": "XX.checksums missing or not a regular fileXX",` | c1 |  |
| 512 | 19 | `"error": ".checksums missing or not a regular file",` → `"error": ".CHECKSUMS MISSING OR NOT A REGULAR FILE",` | c1 |  |
| 513 | 20 | `"files": {},` → `"XXfilesXX": {},` | c2 | early-return dict keys |
| 513 | 21 | `"files": {},` → `"FILES": {},` | c2 | early-return dict keys |
| 514 | 22 | `"mismatched": [],` → `"XXmismatchedXX": [],` | c2 | early-return dict keys |
| 514 | 23 | `"mismatched": [],` → `"MISMATCHED": [],` | c2 | early-return dict keys |
| 515 | 24 | `"missing": [],` → `"XXmissingXX": [],` | c2 | early-return dict keys |
| 515 | 25 | `"missing": [],` → `"MISSING": [],` | c2 | early-return dict keys |
| 516 | 26 | `"extra": [],` → `"XXextraXX": [],` | c2 | early-return dict keys |
| 516 | 27 | `"extra": [],` → `"EXTRA": [],` | c2 | early-return dict keys |
| 522 | 31 | `raw = checksums_file.read_bytes().decode("utf-8")` → `raw = checksums_file.read_bytes().decode("UTF-8")` | a | codec case / empty-string path reaches the same {} |
| 525 | 34 | `"status": "fail",` → `"status": "XXfailXX",` | b | missing/undecodable .checksums early return: status/passed can be flipped — kill: B1 |
| 525 | 35 | `"status": "fail",` → `"status": "FAIL",` | b | missing/undecodable .checksums early return: status/passed can be flipped — kill: B1 |
| 526 | 36 | `"passed": False,` → `"XXpassedXX": False,` | c2 | early-return dict keys |
| 526 | 37 | `"passed": False,` → `"PASSED": False,` | c2 | early-return dict keys |
| 526 | 38 | `"passed": False,` → `"passed": True,` | b | missing/undecodable .checksums early return: status/passed can be flipped — kill: B1 |
| 527 | 39 | `"error": ".checksums could not be read as text",` → `"XXerrorXX": ".checksums could not be read as text",` | c2 | early-return dict keys |
| 527 | 40 | `"error": ".checksums could not be read as text",` → `"ERROR": ".checksums could not be read as text",` | c2 | early-return dict keys |
| 527 | 41 | `"error": ".checksums could not be read as text",` → `"error": "XX.checksums could not be read as textXX",` | c1 |  |
| 527 | 42 | `"error": ".checksums could not be read as text",` → `"error": ".CHECKSUMS COULD NOT BE READ AS TEXT",` | c1 |  |
| 528 | 43 | `"files": {},` → `"XXfilesXX": {},` | c2 | early-return dict keys |
| 528 | 44 | `"files": {},` → `"FILES": {},` | c2 | early-return dict keys |
| 529 | 45 | `"mismatched": [],` → `"XXmismatchedXX": [],` | c2 | early-return dict keys |
| 529 | 46 | `"mismatched": [],` → `"MISMATCHED": [],` | c2 | early-return dict keys |
| 530 | 47 | `"missing": [],` → `"XXmissingXX": [],` | c2 | early-return dict keys |
| 530 | 48 | `"missing": [],` → `"MISSING": [],` | c2 | early-return dict keys |
| 531 | 49 | `"extra": [],` → `"XXextraXX": [],` | c2 | early-return dict keys |
| 531 | 50 | `"extra": [],` → `"EXTRA": [],` | c2 | early-return dict keys |
| 541 | 57 | `if raw != "" and not _NORMATIVE_ATTEMPT_RE.match(raw):` → `if raw != "XXXX" and not _NORMATIVE_ATTEMPT_RE.match(raw):` | a | codec case / empty-string path reaches the same {} |
| 547 | 62 | `legacy = None` → `legacy = ""` | a | codec case / empty-string path reaches the same {} |
| 559 | 79 | `"format": checksums_format,` → `"XXformatXX": checksums_format,` | c2 | early-return dict keys |
| 559 | 80 | `"format": checksums_format,` → `"FORMAT": checksums_format,` | c2 | early-return dict keys |
| 560 | 81 | `"files": {},` → `"XXfilesXX": {},` | c2 | early-return dict keys |
| 560 | 82 | `"files": {},` → `"FILES": {},` | c2 | early-return dict keys |
| 563 | 87 | `"extra": [],` → `"XXextraXX": [],` | c2 | early-return dict keys |
| 563 | 88 | `"extra": [],` → `"EXTRA": [],` | c2 | early-return dict keys |
| 582 | 100 | `for fp in capsule_path.rglob("*"):` → `for fp in capsule_path.rglob("XX*XX"):` | c5 | NFC collision detection; APFS cannot hold two normalisation-equivalent names |
| 585 | 110 | `colliding_paths.add(normalized)` → `colliding_paths.add(None)` | c5 | NFC collision detection; APFS cannot hold two normalisation-equivalent names |
| 588 | 112 | `invalid.extend(sorted(colliding_paths))` → `invalid.extend(None)` | c5 | NFC collision detection; APFS cannot hold two normalisation-equivalent names |
| 588 | 113 | `invalid.extend(sorted(colliding_paths))` → `invalid.extend(sorted(None))` | c5 | NFC collision detection; APFS cannot hold two normalisation-equivalent names |
| 589 | 114 | `all_match = False` → `all_match = None` | a | all_match = None is falsy: identical verdict |
| 589 | 115 | `all_match = False` → `all_match = True` | c5 | NFC collision detection; APFS cannot hold two normalisation-equivalent names |
| 595 | 125 | `invalid.append(normalized)` → `invalid.append(None)` | b | legacy .checksums with two NFC-equivalent keys passes — kill: B3 |
| 596 | 126 | `all_match = False` → `all_match = None` | a | all_match = None is falsy: identical verdict |
| 596 | 127 | `all_match = False` → `all_match = True` | b | legacy .checksums with two NFC-equivalent keys passes — kill: B3 |
| 597 | 128 | `normalized_expected.add(normalized)` → `normalized_expected.add(None)` | b | legacy .checksums with two NFC-equivalent keys passes — kill: B3 |
| 603 | 130 | `files[str(rel_path)] = {"expected": expected_digest, "actual": None, …` → `files[str(rel_path)] = None` | c2 | non-string-key record fields |
| 603 | 131 | `files[str(rel_path)] = {"expected": expected_digest, "actual": None,` → `files[str(None)] = {"expected": expected_digest, "actual": None,` | c2 | non-string-key record fields |
| 603 | 132 | `files[str(rel_path)] = {"expected": expected_digest, "actual": None,` → `files[str(rel_path)] = {"XXexpectedXX": expected_digest, "actual": No…` | c2 | non-string-key record fields |
| 603 | 133 | `files[str(rel_path)] = {"expected": expected_digest, "actual": None,` → `files[str(rel_path)] = {"EXPECTED": expected_digest, "actual": None,` | c2 | non-string-key record fields |
| 603 | 134 | `files[str(rel_path)] = {"expected": expected_digest, "actual": None,` → `files[str(rel_path)] = {"expected": expected_digest, "XXactualXX": No…` | c2 | non-string-key record fields |
| 603 | 135 | `files[str(rel_path)] = {"expected": expected_digest, "actual": None,` → `files[str(rel_path)] = {"expected": expected_digest, "ACTUAL": None,` | c2 | non-string-key record fields |
| 604 | 136 | `"match": False, "error": "non-string .checksums key"}` → `"XXmatchXX": False, "error": "non-string .checksums key"}` | c2 | non-string-key record fields |
| 604 | 137 | `"match": False, "error": "non-string .checksums key"}` → `"MATCH": False, "error": "non-string .checksums key"}` | c2 | non-string-key record fields |
| 604 | 138 | `"match": False, "error": "non-string .checksums key"}` → `"match": True, "error": "non-string .checksums key"}` | b | legacy .checksums with a non-string key and matching payload passes / record wrong — kill: B2 |
| 604 | 139 | `"match": False, "error": "non-string .checksums key"}` → `"match": False, "XXerrorXX": "non-string .checksums key"}` | c2 | non-string-key record fields |
| 604 | 140 | `"match": False, "error": "non-string .checksums key"}` → `"match": False, "ERROR": "non-string .checksums key"}` | c2 | non-string-key record fields |
| 604 | 141 | `"match": False, "error": "non-string .checksums key"}` → `"match": False, "error": "XXnon-string .checksums keyXX"}` | c2 | non-string-key record fields |
| 604 | 142 | `"match": False, "error": "non-string .checksums key"}` → `"match": False, "error": "NON-STRING .CHECKSUMS KEY"}` | c2 | non-string-key record fields |
| 605 | 143 | `invalid.append(str(rel_path))` → `invalid.append(None)` | b | legacy .checksums with a non-string key and matching payload passes / record wrong — kill: B2 |
| 605 | 144 | `invalid.append(str(rel_path))` → `invalid.append(str(None))` | a | str(None) == 'None' already |
| 606 | 145 | `all_match = False` → `all_match = None` | a | all_match = None is falsy: identical verdict |
| 606 | 146 | `all_match = False` → `all_match = True` | b | legacy .checksums with a non-string key and matching payload passes / record wrong — kill: B2 |
| 607 | 147 | `continue` → `break` | b | legacy .checksums with a non-string key and matching payload passes / record wrong — kill: B2 |
| 619 | 162 | `files[rel_path] = {"expected": expected_digest, "actual": None,` → `files[rel_path] = {"XXexpectedXX": expected_digest, "actual": None,` | c2 | unchecked-path record fields / invalid list |
| 619 | 163 | `files[rel_path] = {"expected": expected_digest, "actual": None,` → `files[rel_path] = {"EXPECTED": expected_digest, "actual": None,` | c2 | unchecked-path record fields / invalid list |
| 619 | 164 | `files[rel_path] = {"expected": expected_digest, "actual": None,` → `files[rel_path] = {"expected": expected_digest, "XXactualXX": None,` | c2 | unchecked-path record fields / invalid list |
| 619 | 165 | `files[rel_path] = {"expected": expected_digest, "actual": None,` → `files[rel_path] = {"expected": expected_digest, "ACTUAL": None,` | c2 | unchecked-path record fields / invalid list |
| 620 | 166 | `"match": False, "error": "path could not be checked"}` → `"XXmatchXX": False, "error": "path could not be checked"}` | c2 | unchecked-path record fields / invalid list |
| 620 | 167 | `"match": False, "error": "path could not be checked"}` → `"MATCH": False, "error": "path could not be checked"}` | c2 | unchecked-path record fields / invalid list |
| 620 | 168 | `"match": False, "error": "path could not be checked"}` → `"match": True, "error": "path could not be checked"}` | c2 | unchecked-path record fields / invalid list |
| 620 | 169 | `"match": False, "error": "path could not be checked"}` → `"match": False, "XXerrorXX": "path could not be checked"}` | c2 | unchecked-path record fields / invalid list |
| 620 | 170 | `"match": False, "error": "path could not be checked"}` → `"match": False, "ERROR": "path could not be checked"}` | c2 | unchecked-path record fields / invalid list |
| 620 | 171 | `"match": False, "error": "path could not be checked"}` → `"match": False, "error": "XXpath could not be checkedXX"}` | c2 | unchecked-path record fields / invalid list |
| 620 | 172 | `"match": False, "error": "path could not be checked"}` → `"match": False, "error": "PATH COULD NOT BE CHECKED"}` | c2 | unchecked-path record fields / invalid list |
| 621 | 173 | `invalid.append(rel_path)` → `invalid.append(None)` | c2 | unchecked-path record fields / invalid list |
| 623 | 176 | `continue` → `break` | c4 | break after an unchecked path skips later entries; verdict already fail |
| 630 | 187 | `if kind == "mismatch":` → `if kind == "XXmismatchXX":` | c2 | mismatched/missing/symlinks lists never asserted |
| 630 | 188 | `if kind == "mismatch":` → `if kind == "MISMATCH":` | c2 | mismatched/missing/symlinks lists never asserted |
| 631 | 189 | `mismatched.append(rel_path)` → `mismatched.append(None)` | c2 | mismatched/missing/symlinks lists never asserted |
| 632 | 191 | `elif kind == "missing":` → `elif kind == "XXmissingXX":` | c2 | mismatched/missing/symlinks lists never asserted |
| 632 | 192 | `elif kind == "missing":` → `elif kind == "MISSING":` | c2 | mismatched/missing/symlinks lists never asserted |
| 633 | 193 | `missing.append(rel_path)` → `missing.append(None)` | c2 | mismatched/missing/symlinks lists never asserted |
| 634 | 195 | `elif kind == "symlink":` → `elif kind == "XXsymlinkXX":` | c2 | mismatched/missing/symlinks lists never asserted |
| 634 | 196 | `elif kind == "symlink":` → `elif kind == "SYMLINK":` | c2 | mismatched/missing/symlinks lists never asserted |
| 635 | 197 | `symlinks.append(rel_path)` → `symlinks.append(None)` | c2 | mismatched/missing/symlinks lists never asserted |
| 651 | 209 | `all_match = False` → `all_match = None` | a | all_match = None is falsy: identical verdict |
| 652 | 211 | `continue` → `break` | c4 | break on the first symlink in the walk: `extra` list incomplete; verdict already fail |
| 663 | 231 | `all_match = False` → `all_match = None` | a | all_match = None is falsy: identical verdict |
| 670 | 247 | `"mismatched": mismatched,` → `"XXmismatchedXX": mismatched,` | c2 | mismatched/missing/symlinks lists never asserted |
| 670 | 248 | `"mismatched": mismatched,` → `"MISMATCHED": mismatched,` | c2 | mismatched/missing/symlinks lists never asserted |
| 671 | 249 | `"missing": missing,` → `"XXmissingXX": missing,` | c2 | mismatched/missing/symlinks lists never asserted |
| 671 | 250 | `"missing": missing,` → `"MISSING": missing,` | c2 | mismatched/missing/symlinks lists never asserted |

**`CapsuleVerifier.verify_integrity`** — 37 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 709 | 9 | `expected_id_usable = False` → `expected_id_usable = None` | a | None is falsy / codec case |
| 712 | 12 | `"(expected mqc:<version>:<64 lowercase hex>)"` → `"XX(expected mqc:<version>:<64 lowercase hex>)XX"` | c1 |  |
| 712 | 13 | `"(expected mqc:<version>:<64 lowercase hex>)"` → `"(EXPECTED MQC:<VERSION>:<64 LOWERCASE HEX>)"` | c1 |  |
| 716 | 15 | `expected_id_usable = False` → `expected_id_usable = None` | a | None is falsy / codec case |
| 724 | 26 | `errors.append("payload does not match .checksums")` → `errors.append("XXpayload does not match .checksumsXX")` | c1 |  |
| 724 | 27 | `errors.append("payload does not match .checksums")` → `errors.append("PAYLOAD DOES NOT MATCH .CHECKSUMS")` | c1 |  |
| 726 | 28 | `checksums_digest_match: Optional[bool] = None` → `checksums_digest_match: Optional[bool] = ""` | c2 | checksums_digest_match ''/warning ''/result key |
| 735 | 43 | `errors.append("capsule.yaml missing or not a regular file — no manife…` → `errors.append(None)` | c1 |  |
| 735 | 44 | `errors.append("capsule.yaml missing or not a regular file — no manife…` → `errors.append("XXcapsule.yaml missing or not a regular file — no mani…` | c1 |  |
| 735 | 45 | `errors.append("capsule.yaml missing or not a regular file — no manife…` → `errors.append("CAPSULE.YAML MISSING OR NOT A REGULAR FILE — NO MANIFE…` | c1 |  |
| 740 | 48 | `parsed = load_manifest_yaml(manifest_path.read_text(encoding="utf-8"))` → `parsed = load_manifest_yaml(manifest_path.read_text(encoding=None))` | c5 | encoding=None / '.CHECKSUMS' on APFS |
| 740 | 50 | `parsed = load_manifest_yaml(manifest_path.read_text(encoding="utf-8"))` → `parsed = load_manifest_yaml(manifest_path.read_text(encoding="UTF-8"))` | a | None is falsy / codec case |
| 747 | 53 | `errors.append("capsule.yaml is not a YAML mapping")` → `errors.append(None)` | c1 |  |
| 747 | 54 | `errors.append("capsule.yaml is not a YAML mapping")` → `errors.append("XXcapsule.yaml is not a YAML mappingXX")` | c1 |  |
| 747 | 55 | `errors.append("capsule.yaml is not a YAML mapping")` → `errors.append("capsule.yaml is not a yaml mapping")` | c1 |  |
| 747 | 56 | `errors.append("capsule.yaml is not a YAML mapping")` → `errors.append("CAPSULE.YAML IS NOT A YAML MAPPING")` | c1 |  |
| 752 | 65 | `checksums_file = capsule_path / ".checksums"` → `checksums_file = capsule_path / ".CHECKSUMS"` | c5 | encoding=None / '.CHECKSUMS' on APFS |
| 754 | 68 | `errors.append("manifest has no checksums_digest — capsule is not seal…` → `errors.append("XXmanifest has no checksums_digest — capsule is not se…` | c1 |  |
| 756 | 72 | `checksums_digest_match = False` → `checksums_digest_match = None` | b | manifest declares checksums_digest, .checksums absent -> checksums_digest_match reported True — kill: B4 |
| 756 | 73 | `checksums_digest_match = False` → `checksums_digest_match = True` | b | manifest declares checksums_digest, .checksums absent -> checksums_digest_match reported True — kill: B4 |
| 757 | 74 | `errors.append(".checksums missing or not a regular file but manifest …` → `errors.append(None)` | c1 |  |
| 757 | 75 | `errors.append(".checksums missing or not a regular file but manifest …` → `errors.append("XX.checksums missing or not a regular file but manifes…` | c1 |  |
| 757 | 76 | `errors.append(".checksums missing or not a regular file but manifest …` → `errors.append(".CHECKSUMS MISSING OR NOT A REGULAR FILE BUT MANIFEST …` | c1 |  |
| 762 | 82 | `checksums_digest_match = False` → `checksums_digest_match = None` | c4 | unreadable .checksums branch (needs a chmod-0 file) |
| 762 | 83 | `checksums_digest_match = False` → `checksums_digest_match = True` | c4 | unreadable .checksums branch (needs a chmod-0 file) |
| 763 | 84 | `errors.append(".checksums could not be read to verify checksums_diges…` → `errors.append(None)` | c1 |  |
| 763 | 85 | `errors.append(".checksums could not be read to verify checksums_diges…` → `errors.append("XX.checksums could not be read to verify checksums_dig…` | c1 |  |
| 763 | 86 | `errors.append(".checksums could not be read to verify checksums_diges…` → `errors.append(".CHECKSUMS COULD NOT BE READ TO VERIFY CHECKSUMS_DIGES…` | c1 |  |
| 768 | 90 | `f"checksums_digest mismatch: manifest declares {declared}, " ⏎ f".che…` → `None` | c1 |  |
| 779 | 93 | `f"capsule ID could not be computed: {exc.__class__.__name__}"` → `None` | c1 |  |
| 794 | 101 | `warning = None` → `warning = ""` | c2 | checksums_digest_match ''/warning ''/result key |
| 797 | 104 | `"manifest is not authenticated — nothing on disk can attest to it; "` → `"XXmanifest is not authenticated — nothing on disk can attest to it; …` | c1 |  |
| 797 | 105 | `"manifest is not authenticated — nothing on disk can attest to it; "` → `"MANIFEST IS NOT AUTHENTICATED — NOTHING ON DISK CAN ATTEST TO IT; "` | c1 |  |
| 798 | 106 | `"pass --id <trusted-id> to verify layer 3 (spec §6)"` → `"XXpass --id <trusted-id> to verify layer 3 (spec §6)XX"` | c1 |  |
| 798 | 107 | `"pass --id <trusted-id> to verify layer 3 (spec §6)"` → `"PASS --ID <TRUSTED-ID> TO VERIFY LAYER 3 (SPEC §6)"` | c1 |  |
| 803 | 116 | `"checksums": checksums,` → `"XXchecksumsXX": checksums,` | c2 | checksums_digest_match ''/warning ''/result key |
| 803 | 117 | `"checksums": checksums,` → `"CHECKSUMS": checksums,` | c2 | checksums_digest_match ''/warning ''/result key |

**`CapsuleVerifier.load_capsule`** — 3 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 818 | 3 | `manifest = load_manifest_yaml(Path(filepath).read_text(encoding="utf-…` → `manifest = load_manifest_yaml(Path(filepath).read_text(encoding=None))` | c5 | encoding=None: UTF-8 locale |
| 818 | 6 | `manifest = load_manifest_yaml(Path(filepath).read_text(encoding="utf-…` → `manifest = load_manifest_yaml(Path(filepath).read_text(encoding="UTF-…` | a |  |
| 820 | 9 | `raise ValueError("capsule.yaml must be a YAML mapping")` → `raise ValueError("XXcapsule.yaml must be a YAML mappingXX")` | c1 |  |

**`CapsuleVerifier.verify_capsule`** — 15 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 828 | 1 | `tolerance: float = 0.01,` → `tolerance: float = 1.01,` | a | retired API raises before touching its arguments |
| 829 | 2 | `significance_level: float = 0.05,` → `significance_level: float = 1.05,` | a | retired API raises before touching its arguments |
| 837 | 4 | `"verify_capsule() was retired before 0.1.0: use "` → `"XXverify_capsule() was retired before 0.1.0: use XX"` | c1 |  |
| 837 | 5 | `"verify_capsule() was retired before 0.1.0: use "` → `"VERIFY_CAPSULE() WAS RETIRED BEFORE 0.1.0: USE "` | c1 |  |
| 838 | 6 | `"verify_integrity(directory, expected_id=trusted_id) for file integri…` → `"XXverify_integrity(directory, expected_id=trusted_id) for file integ…` | c1 |  |
| 839 | 8 | `"verify_deterministic(ref_data, new_data) for explicit result equalit…` → `"XXverify_deterministic(ref_data, new_data) for explicit result equal…` | c1 |  |
| 839 | 9 | `"verify_deterministic(ref_data, new_data) for explicit result equalit…` → `"VERIFY_DETERMINISTIC(REF_DATA, NEW_DATA) FOR EXPLICIT RESULT EQUALIT…` | c1 |  |
| 840 | 10 | `"or verify_statistical(ref_counts, new_counts, policy.resolve(declare…` → `"XXor verify_statistical(ref_counts, new_counts, policy.resolve(decla…` | c1 |  |
| 840 | 11 | `"or verify_statistical(ref_counts, new_counts, policy.resolve(declare…` → `"OR VERIFY_STATISTICAL(REF_COUNTS, NEW_COUNTS, POLICY.RESOLVE(DECLARE…` | c1 |  |
| 841 | 12 | `"with a verifier-owned VerificationPolicy for count equivalence. "` → `"XXwith a verifier-owned VerificationPolicy for count equivalence. XX"` | c1 |  |
| 841 | 13 | `"with a verifier-owned VerificationPolicy for count equivalence. "` → `"with a verifier-owned verificationpolicy for count equivalence. "` | c1 |  |
| 841 | 14 | `"with a verifier-owned VerificationPolicy for count equivalence. "` → `"WITH A VERIFIER-OWNED VERIFICATIONPOLICY FOR COUNT EQUIVALENCE. "` | c1 |  |
| 842 | 15 | `"Metadata alone cannot establish any of these guarantees."` → `"XXMetadata alone cannot establish any of these guarantees.XX"` | c1 |  |
| 842 | 16 | `"Metadata alone cannot establish any of these guarantees."` → `"metadata alone cannot establish any of these guarantees."` | c1 |  |
| 842 | 17 | `"Metadata alone cannot establish any of these guarantees."` → `"METADATA ALONE CANNOT ESTABLISH ANY OF THESE GUARANTEES."` | c1 |  |

**`CapsuleVerifier.check_calibration_drift`** — 9 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 849 | 1 | `max_fidelity_drift: float = 0.01,` → `max_fidelity_drift: float = 1.01,` | a | retired API raises before touching its arguments |
| 853 | 3 | `"check_calibration_drift() was retired before 0.1.0. "` → `"XXcheck_calibration_drift() was retired before 0.1.0. XX"` | a | retired API raises before touching its arguments |
| 853 | 4 | `"check_calibration_drift() was retired before 0.1.0. "` → `"CHECK_CALIBRATION_DRIFT() WAS RETIRED BEFORE 0.1.0. "` | c1 |  |
| 854 | 5 | `"No replacement calibration-verdict API is provided; compare explicit…` → `"XXNo replacement calibration-verdict API is provided; compare explic…` | c1 |  |
| 855 | 8 | `"validated calibration measurements with a domain-specific policy. "` → `"XXvalidated calibration measurements with a domain-specific policy. …` | c1 |  |
| 855 | 9 | `"validated calibration measurements with a domain-specific policy. "` → `"VALIDATED CALIBRATION MEASUREMENTS WITH A DOMAIN-SPECIFIC POLICY. "` | c1 |  |
| 856 | 10 | `"A statistical calibration_drift tolerance is not a calibration check…` → `"XXA statistical calibration_drift tolerance is not a calibration che…` | c1 |  |
| 856 | 11 | `"A statistical calibration_drift tolerance is not a calibration check…` → `"a statistical calibration_drift tolerance is not a calibration check…` | c1 |  |
| 856 | 12 | `"A statistical calibration_drift tolerance is not a calibration check…` → `"A STATISTICAL CALIBRATION_DRIFT TOLERANCE IS NOT A CALIBRATION CHECK…` | c1 |  |

**`CapsuleVerifier.compare_capsules`** — 11 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 863 | 1 | `method: str = "statistical",` → `method: str = "XXstatisticalXX",` | a | retired API raises before touching its arguments |
| 863 | 2 | `method: str = "statistical",` → `method: str = "STATISTICAL",` | a | retired API raises before touching its arguments |
| 864 | 3 | `tolerance: float = 0.01,` → `tolerance: float = 1.01,` | a | retired API raises before touching its arguments |
| 868 | 5 | `"compare_capsules() was retired before 0.1.0: verify each directory "` → `"XXcompare_capsules() was retired before 0.1.0: verify each directory…` | c1 |  |
| 868 | 6 | `"compare_capsules() was retired before 0.1.0: verify each directory "` → `"COMPARE_CAPSULES() WAS RETIRED BEFORE 0.1.0: VERIFY EACH DIRECTORY "` | c1 |  |
| 869 | 7 | `"with verify_integrity and its independently trusted ID, then compare…` → `"XXwith verify_integrity and its independently trusted ID, then compa…` | c1 |  |
| 869 | 8 | `"with verify_integrity and its independently trusted ID, then compare…` → `"with verify_integrity and its independently trusted id, then compare…` | c1 |  |
| 869 | 9 | `"with verify_integrity and its independently trusted ID, then compare…` → `"WITH VERIFY_INTEGRITY AND ITS INDEPENDENTLY TRUSTED ID, THEN COMPARE…` | c1 |  |
| 870 | 10 | `"explicit result data with verify_deterministic or verify_statistical…` → `"XXexplicit result data with verify_deterministic or verify_statistic…` | c1 |  |
| 870 | 11 | `"explicit result data with verify_deterministic or verify_statistical…` → `"EXPLICIT RESULT DATA WITH VERIFY_DETERMINISTIC OR VERIFY_STATISTICAL…` | c1 |  |
| 871 | 12 | `"Matching capsule names do not establish consistency."` → `"XXMatching capsule names do not establish consistency.XX"` | c1 |  |

### redactor.py


**`_shannon_entropy`** — 18 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 192 | 1 | `if not s:` → `if s:` | c6 | retained for the research note only |
| 193 | 2 | `return 0.0` → `return 1.0` | c6 | retained for the research note only |
| 194 | 3 | `freq: dict[str, int] = {}` → `freq: dict[str, int] = None` | c6 | retained for the research note only |
| 196 | 4 | `freq[c] = freq.get(c, 0) + 1` → `freq[c] = None` | c6 | retained for the research note only |
| 196 | 5 | `freq[c] = freq.get(c, 0) + 1` → `freq[c] = freq.get(c, 0) - 1` | c6 | retained for the research note only |
| 196 | 6 | `freq[c] = freq.get(c, 0) + 1` → `freq[c] = freq.get(None, 0) + 1` | c6 | retained for the research note only |
| 196 | 7 | `freq[c] = freq.get(c, 0) + 1` → `freq[c] = freq.get(c, None) + 1` | c6 | retained for the research note only |
| 196 | 8 | `freq[c] = freq.get(c, 0) + 1` → `freq[c] = freq.get(0) + 1` | c6 | retained for the research note only |
| 196 | 9 | `freq[c] = freq.get(c, 0) + 1` → `freq[c] = freq.get(c, ) + 1` | c6 | retained for the research note only |
| 196 | 10 | `freq[c] = freq.get(c, 0) + 1` → `freq[c] = freq.get(c, 1) + 1` | c6 | retained for the research note only |
| 196 | 11 | `freq[c] = freq.get(c, 0) + 1` → `freq[c] = freq.get(c, 0) + 2` | c6 | retained for the research note only |
| 197 | 12 | `n = len(s)` → `n = None` | c6 | retained for the research note only |
| 198 | 13 | `return -sum((f / n) * math.log2(f / n) for f in freq.values())` → `return +sum((f / n) * math.log2(f / n) for f in freq.values())` | c6 | retained for the research note only |
| 198 | 14 | `return -sum((f / n) * math.log2(f / n) for f in freq.values())` → `return -sum(None)` | c6 | retained for the research note only |
| 198 | 15 | `return -sum((f / n) * math.log2(f / n) for f in freq.values())` → `return -sum((f / n) / math.log2(f / n) for f in freq.values())` | c6 | retained for the research note only |
| 198 | 16 | `return -sum((f / n) * math.log2(f / n) for f in freq.values())` → `return -sum((f * n) * math.log2(f / n) for f in freq.values())` | c6 | retained for the research note only |
| 198 | 17 | `return -sum((f / n) * math.log2(f / n) for f in freq.values())` → `return -sum((f / n) * math.log2(None) for f in freq.values())` | c6 | retained for the research note only |
| 198 | 18 | `return -sum((f / n) * math.log2(f / n) for f in freq.values())` → `return -sum((f / n) * math.log2(f * n) for f in freq.values())` | c6 | retained for the research note only |

**`_charset_entropy`** — 6 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 205 | 1 | `if not s:` → `if s:` | c7 | Tier B entropy never asserted: any of these silences high_entropy_* warnings — kill: C* |
| 206 | 2 | `return 0.0` → `return 1.0` | c7 | Tier B entropy never asserted: any of these silences high_entropy_* warnings — kill: C* |
| 210 | 7 | `p_x = s.count(x) / n` → `p_x = s.count(x) * n` | c7 | Tier B entropy never asserted: any of these silences high_entropy_* warnings — kill: C* |
| 211 | 10 | `if p_x > 0:` → `if p_x > 1:` | c7 | Tier B entropy never asserted: any of these silences high_entropy_* warnings — kill: C* |
| 212 | 11 | `entropy -= p_x * math.log2(p_x)` → `entropy = p_x * math.log2(p_x)` | c7 | Tier B entropy never asserted: any of these silences high_entropy_* warnings — kill: C* |
| 212 | 12 | `entropy -= p_x * math.log2(p_x)` → `entropy += p_x * math.log2(p_x)` | c7 | Tier B entropy never asserted: any of these silences high_entropy_* warnings — kill: C* |

**`_redact_value`** — 13 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 218 | 2 | `v = value.strip().strip("'\"").strip()` → `v = value.strip().strip(None).strip()` | a |  |
| 218 | 3 | `v = value.strip().strip("'\"").strip()` → `v = value.strip().strip("XX'\"XX").strip()` | a |  |
| 220 | 5 | `return "***"` → `return "XX***XX"` | c2 | mask glyphs |
| 221 | 6 | `if len(v) <= 6:` → `if len(v) < 6:` | c4 | redaction prefix length not pinned (one extra secret char would leak into reports) |
| 221 | 7 | `if len(v) <= 6:` → `if len(v) <= 7:` | c4 | redaction prefix length not pinned (one extra secret char would leak into reports) |
| 222 | 9 | `return v[:2] + "***"` → `return v[:3] + "***"` | c4 | redaction prefix length not pinned (one extra secret char would leak into reports) |
| 222 | 10 | `return v[:2] + "***"` → `return v[:2] + "XX***XX"` | c2 | mask glyphs |
| 223 | 13 | `return v[:4] + "…" + "*" * min(len(v) - 4, 8)` → `return v[:5] + "…" + "*" * min(len(v) - 4, 8)` | c4 | redaction prefix length not pinned (one extra secret char would leak into reports) |
| 223 | 14 | `return v[:4] + "…" + "*" * min(len(v) - 4, 8)` → `return v[:4] + "XX…XX" + "*" * min(len(v) - 4, 8)` | c2 | mask glyphs |
| 223 | 16 | `return v[:4] + "…" + "*" * min(len(v) - 4, 8)` → `return v[:4] + "…" + "XX*XX" * min(len(v) - 4, 8)` | c2 | mask glyphs |
| 223 | 21 | `return v[:4] + "…" + "*" * min(len(v) - 4, 8)` → `return v[:4] + "…" + "*" * min(len(v) + 4, 8)` | c4 | redaction prefix length not pinned (one extra secret char would leak into reports) |
| 223 | 22 | `return v[:4] + "…" + "*" * min(len(v) - 4, 8)` → `return v[:4] + "…" + "*" * min(len(v) - 5, 8)` | c4 | redaction prefix length not pinned (one extra secret char would leak into reports) |
| 223 | 23 | `return v[:4] + "…" + "*" * min(len(v) - 4, 8)` → `return v[:4] + "…" + "*" * min(len(v) - 4, 9)` | c4 | redaction prefix length not pinned (one extra secret char would leak into reports) |

**`_looks_like_digest_line`** — 2 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 227 | 1 | `return bool(_DIGEST_LINE_RE.search(line))` → `return bool(None)` | c6 | helper unused by the package |
| 227 | 2 | `return bool(_DIGEST_LINE_RE.search(line))` → `return bool(_DIGEST_LINE_RE.search(None))` | c6 | helper unused by the package |

**`_is_credential_file`** — 1 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 236 | 6 | `return True` → `return False` | b | id_rsa / id_ed25519 exact-name rule never tested — kill: B8 |

**`_load_capsuleignore`** — 10 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 250 | 4 | `ignore_file = capsule_dir / ".capsuleignore"` → `ignore_file = capsule_dir / ".CAPSULEIGNORE"` | c5 |  |
| 254 | 7 | `lines = ignore_file.read_text(encoding="utf-8", errors="replace").spl…` → `lines = ignore_file.read_text(encoding=None, errors="replace").splitl…` | c5 |  |
| 254 | 8 | `lines = ignore_file.read_text(encoding="utf-8", errors="replace").spl…` → `lines = ignore_file.read_text(encoding="utf-8", errors=None).splitlin…` | c4 | non-UTF-8 / blank / comment lines in .capsuleignore |
| 254 | 9 | `lines = ignore_file.read_text(encoding="utf-8", errors="replace").spl…` → `lines = ignore_file.read_text(errors="replace").splitlines()` | c5 |  |
| 254 | 10 | `lines = ignore_file.read_text(encoding="utf-8", errors="replace").spl…` → `lines = ignore_file.read_text(encoding="utf-8", ).splitlines()` | c4 | non-UTF-8 / blank / comment lines in .capsuleignore |
| 254 | 12 | `lines = ignore_file.read_text(encoding="utf-8", errors="replace").spl…` → `lines = ignore_file.read_text(encoding="UTF-8", errors="replace").spl…` | a |  |
| 254 | 13 | `lines = ignore_file.read_text(encoding="utf-8", errors="replace").spl…` → `lines = ignore_file.read_text(encoding="utf-8", errors="XXreplaceXX")…` | c4 | non-UTF-8 / blank / comment lines in .capsuleignore |
| 254 | 14 | `lines = ignore_file.read_text(encoding="utf-8", errors="replace").spl…` → `lines = ignore_file.read_text(encoding="utf-8", errors="REPLACE").spl…` | c4 | non-UTF-8 / blank / comment lines in .capsuleignore |
| 259 | 15 | `if line.strip() and not line.strip().startswith("#")` → `if line.strip() or not line.strip().startswith("#")` | c4 | non-UTF-8 / blank / comment lines in .capsuleignore |
| 259 | 18 | `if line.strip() and not line.strip().startswith("#")` → `if line.strip() and not line.strip().startswith("XX#XX")` | c4 | non-UTF-8 / blank / comment lines in .capsuleignore |

**`_is_ignored`** — 3 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 266 | 4 | `if pattern.startswith("*."):` → `if pattern.startswith("XX*.XX"):` | c4 | `*.ext` ignore patterns; skipped list never asserted |
| 267 | 6 | `ext = pattern[1:]` → `ext = pattern[2:]` | c4 | `*.ext` ignore patterns; skipped list never asserted |
| 269 | 8 | `return True` → `return False` | c4 | `*.ext` ignore patterns; skipped list never asserted |

**`_is_embedded_value`** — 3 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 281 | 2 | `v = value.strip().strip("'\"").strip()` → `v = value.strip().strip(None).strip()` | a | regex capture already excludes quotes |
| 281 | 3 | `v = value.strip().strip("'\"").strip()` → `v = value.strip().strip("XX'\"XX").strip()` | a | regex capture already excludes quotes |
| 282 | 4 | `return bool(v) and not _VALUE_REJECT_RE.search(v)` → `return bool(v) or not _VALUE_REJECT_RE.search(v)` | b | known-name assigned from os.environ would block the seal (false positive) — kill: B9 |

**`_plausible_secret_value`** — 11 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 289 | 2 | `v = value.strip().strip("'\"").strip()` → `v = value.strip().strip(None).strip()` | a |  |
| 289 | 3 | `v = value.strip().strip("'\"").strip()` → `v = value.strip().strip("XX'\"XX").strip()` | a |  |
| 290 | 4 | `if len(v) < 4 or v.isspace():` → `if len(v) < 4 and v.isspace():` | c4 | length boundary |
| 290 | 5 | `if len(v) < 4 or v.isspace():` → `if len(v) <= 4 or v.isspace():` | c4 | length boundary |
| 290 | 6 | `if len(v) < 4 or v.isspace():` → `if len(v) < 5 or v.isspace():` | c4 | length boundary |
| 291 | 7 | `return False` → `return True` | c7 | name_entropy false positives on short/env/alphabetic values |
| 293 | 9 | `return False` → `return True` | c7 | name_entropy false positives on short/env/alphabetic values |
| 294 | 14 | `if re.fullmatch(r"[A-Za-z_.\-]+", v):` → `if re.fullmatch(r"XX[A-Za-z_.\-]+XX", v):` | c7 | name_entropy false positives on short/env/alphabetic values |
| 294 | 15 | `if re.fullmatch(r"[A-Za-z_.\-]+", v):` → `if re.fullmatch(r"[a-za-z_.\-]+", v):` | c7 | name_entropy false positives on short/env/alphabetic values |
| 294 | 16 | `if re.fullmatch(r"[A-Za-z_.\-]+", v):` → `if re.fullmatch(r"[A-ZA-Z_.\-]+", v):` | c7 | name_entropy false positives on short/env/alphabetic values |
| 295 | 17 | `return False` → `return True` | c7 | name_entropy false positives on short/env/alphabetic values |

**`_entropy_reason`** — 17 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 302 | 1 | `if _UUID_RE.match(candidate) or candidate.isdigit():` → `if _UUID_RE.match(candidate) and candidate.isdigit():` | c4 | all-digit >=20-char token would be flagged as hex |
| 304 | 7 | `if re.fullmatch(r"[0-9A-Fa-f]+", candidate):` → `if re.fullmatch(r"XX[0-9A-Fa-f]+XX", candidate):` | c7 | hex/base64 classification or crash on a candidate; Tier B never asserted — kill: C* |
| 304 | 8 | `if re.fullmatch(r"[0-9A-Fa-f]+", candidate):` → `if re.fullmatch(r"[0-9a-fa-f]+", candidate):` | c7 | hex/base64 classification or crash on a candidate; Tier B never asserted — kill: C* |
| 304 | 9 | `if re.fullmatch(r"[0-9A-Fa-f]+", candidate):` → `if re.fullmatch(r"[0-9A-FA-F]+", candidate):` | c7 | hex/base64 classification or crash on a candidate; Tier B never asserted — kill: C* |
| 305 | 10 | `if _charset_entropy(candidate.lower(), _HEX_CHARSET) >= _HEX_ENTROPY_…` → `if _charset_entropy(None, _HEX_CHARSET) >= _HEX_ENTROPY_THRESHOLD:` | c7 | hex/base64 classification or crash on a candidate; Tier B never asserted — kill: C* |
| 305 | 14 | `if _charset_entropy(candidate.lower(), _HEX_CHARSET) >= _HEX_ENTROPY_…` → `if _charset_entropy(candidate.upper(), _HEX_CHARSET) >= _HEX_ENTROPY_…` | c7 | hex/base64 classification or crash on a candidate; Tier B never asserted — kill: C* |
| 305 | 15 | `if _charset_entropy(candidate.lower(), _HEX_CHARSET) >= _HEX_ENTROPY_…` → `if _charset_entropy(candidate.lower(), _HEX_CHARSET) > _HEX_ENTROPY_T…` | c4 | threshold boundary |
| 306 | 16 | `return "high_entropy_hex"` → `return "XXhigh_entropy_hexXX"` | c2 | reason string |
| 306 | 17 | `return "high_entropy_hex"` → `return "HIGH_ENTROPY_HEX"` | c2 | reason string |
| 308 | 22 | `if re.fullmatch(r"[A-Za-z0-9+/=_\-]+", candidate):` → `if re.fullmatch(r"XX[A-Za-z0-9+/=_\-]+XX", candidate):` | c7 | hex/base64 classification or crash on a candidate; Tier B never asserted — kill: C* |
| 308 | 23 | `if re.fullmatch(r"[A-Za-z0-9+/=_\-]+", candidate):` → `if re.fullmatch(r"[a-za-z0-9+/=_\-]+", candidate):` | c7 | hex/base64 classification or crash on a candidate; Tier B never asserted — kill: C* |
| 308 | 24 | `if re.fullmatch(r"[A-Za-z0-9+/=_\-]+", candidate):` → `if re.fullmatch(r"[A-ZA-Z0-9+/=_\-]+", candidate):` | c7 | hex/base64 classification or crash on a candidate; Tier B never asserted — kill: C* |
| 310 | 25 | `if not any(c.isdigit() for c in candidate):` → `if any(c.isdigit() for c in candidate):` | c7 | hex/base64 classification or crash on a candidate; Tier B never asserted — kill: C* |
| 312 | 27 | `if _charset_entropy(candidate, _BASE64_CHARSET) >= _BASE64_ENTROPY_TH…` → `if _charset_entropy(None, _BASE64_CHARSET) >= _BASE64_ENTROPY_THRESHO…` | c7 | hex/base64 classification or crash on a candidate; Tier B never asserted — kill: C* |
| 312 | 31 | `if _charset_entropy(candidate, _BASE64_CHARSET) >= _BASE64_ENTROPY_TH…` → `if _charset_entropy(candidate, _BASE64_CHARSET) > _BASE64_ENTROPY_THR…` | c4 | threshold boundary |
| 313 | 32 | `return "high_entropy_base64"` → `return "XXhigh_entropy_base64XX"` | c2 | reason string |
| 313 | 33 | `return "high_entropy_base64"` → `return "HIGH_ENTROPY_BASE64"` | c2 | reason string |

**`_iter_entropy_candidates`** — 12 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 325 | 5 | `for m in re.finditer(r"[A-Za-z0-9+/_\-]+", line):` → `for m in re.finditer(r"XX[A-Za-z0-9+/_\-]+XX", line):` | c7 | Tier B candidate gating; never asserted — kill: C* |
| 325 | 6 | `for m in re.finditer(r"[A-Za-z0-9+/_\-]+", line):` → `for m in re.finditer(r"[a-za-z0-9+/_\-]+", line):` | c7 | Tier B candidate gating; never asserted — kill: C* |
| 325 | 7 | `for m in re.finditer(r"[A-Za-z0-9+/_\-]+", line):` → `for m in re.finditer(r"[A-ZA-Z0-9+/_\-]+", line):` | c7 | Tier B candidate gating; never asserted — kill: C* |
| 327 | 12 | `if not (_MIN_ENTROPY_LEN <= len(tok) <= _MAX_ENTROPY_LEN):` → `if not (_MIN_ENTROPY_LEN < len(tok) <= _MAX_ENTROPY_LEN):` | c4 | length-cap boundaries |
| 327 | 13 | `if not (_MIN_ENTROPY_LEN <= len(tok) <= _MAX_ENTROPY_LEN):` → `if not (_MIN_ENTROPY_LEN <= len(tok) < _MAX_ENTROPY_LEN):` | c4 | length-cap boundaries |
| 328 | 14 | `continue` → `break` | c7 | Tier B candidate gating; never asserted — kill: C* |
| 329 | 15 | `before = line[:m.start()].rstrip()` → `before = None` | c7 | Tier B candidate gating; never asserted — kill: C* |
| 329 | 16 | `before = line[:m.start()].rstrip()` → `before = line[:m.start()].lstrip()` | c7 | Tier B candidate gating; never asserted — kill: C* |
| 330 | 21 | `if not before or before[-1] not in "'\"=:":` → `if not before or before[-1] in "'\"=:":` | c7 | Tier B candidate gating; never asserted — kill: C* |
| 330 | 22 | `if not before or before[-1] not in "'\"=:":` → `if not before or before[-1] not in "XX'\"=:XX":` | c7 | Tier B candidate gating; never asserted — kill: C* |
| 331 | 23 | `continue  # not quoted / not an assignment RHS` → `break  # not quoted / not an assignment RHS` | c7 | Tier B candidate gating; never asserted — kill: C* |
| 332 | 24 | `reason = _entropy_reason(tok)` → `reason = None` | c7 | Tier B candidate gating; never asserted — kill: C* |

**`_iter_private_key_blocks`** — 6 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 351 | 8 | `continue` → `break` | c4 | PEM pairing edges (nested BEGIN, min body, max block) |
| 352 | 14 | `i = bisect.bisect_left(end_starts, begin.end() + _PEM_MIN_BODY)` → `i = bisect.bisect_left(end_starts, begin.end() - _PEM_MIN_BODY)` | c4 | PEM pairing edges (nested BEGIN, min body, max block) |
| 356 | 17 | `if end_end - begin.start() > _PEM_MAX_BLOCK:` → `if end_end + begin.start() > _PEM_MAX_BLOCK:` | c4 | PEM pairing edges (nested BEGIN, min body, max block) |
| 356 | 18 | `if end_end - begin.start() > _PEM_MAX_BLOCK:` → `if end_end - begin.start() >= _PEM_MAX_BLOCK:` | c4 | PEM pairing edges (nested BEGIN, min body, max block) |
| 357 | 19 | `continue` → `break` | c4 | PEM pairing edges (nested BEGIN, min body, max block) |
| 359 | 20 | `resume = end_end` → `resume = None` | c4 | resume=None -> TypeError on a file with two PEM blocks |

**`_iter_constructor_literals`** — 6 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 368 | 11 | `open_paren = window.rfind("(")` → `open_paren = window.find("(")` | c4 | constructor-window edge cases |
| 369 | 13 | `if open_paren == -1 or ")" in window[open_paren:]:` → `if open_paren == -1 and ")" in window[open_paren:]:` | c4 | constructor-window edge cases |
| 369 | 15 | `if open_paren == -1 or ")" in window[open_paren:]:` → `if open_paren == +1 or ")" in window[open_paren:]:` | c4 | constructor-window edge cases |
| 369 | 16 | `if open_paren == -1 or ")" in window[open_paren:]:` → `if open_paren == -2 or ")" in window[open_paren:]:` | c4 | constructor-window edge cases |
| 369 | 17 | `if open_paren == -1 or ")" in window[open_paren:]:` → `if open_paren == -1 or "XX)XX" in window[open_paren:]:` | c4 | constructor-window edge cases |
| 370 | 19 | `continue` → `break` | c4 | constructor-window edge cases |

**`_finding_allowed`** — 4 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 381 | 2 | `comma = tail.find(",")` → `comma = None` | b | `# capsule:allow` after a comma suppresses a finding before it — kill: B7 |
| 381 | 4 | `comma = tail.find(",")` → `comma = tail.rfind(",")` | c4 | rfind: only an allow between two commas differs |
| 381 | 5 | `comma = tail.find(",")` → `comma = tail.find("XX,XX")` | b | `# capsule:allow` after a comma suppresses a finding before it — kill: B7 |
| 382 | 8 | `region = tail if comma == -1 else tail[:comma]` → `region = tail if (comma == -1) or True else tail[:comma]` | b | `# capsule:allow` after a comma suppresses a finding before it — kill: B7 |

**`_scan_text`** — 69 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 391 | 7 | `line_no = text.count("\n", 0, start) + 1` → `line_no = text.count("\n", None, start) + 1` | c2 | PEM line number |
| 391 | 13 | `line_no = text.count("\n", 0, start) + 1` → `line_no = text.count("\n", 1, start) + 1` | c2 | PEM line number |
| 392 | 15 | `newline = text.find("\n", start)` → `newline = None` | b | `# capsule:allow` on a later line suppresses a PEM block — kill: B11 |
| 392 | 17 | `newline = text.find("\n", start)` → `newline = text.find("\n", None)` | c4 | begin_line edge: stricter, only when BEGIN is not on line 1 / has no trailing LF |
| 392 | 19 | `newline = text.find("\n", start)` → `newline = text.find("\n", )` | c4 | begin_line edge: stricter, only when BEGIN is not on line 1 / has no trailing LF |
| 392 | 20 | `newline = text.find("\n", start)` → `newline = text.rfind("\n", start)` | b | `# capsule:allow` on a later line suppresses a PEM block — kill: B11 |
| 392 | 21 | `newline = text.find("\n", start)` → `newline = text.find("XX\nXX", start)` | b | `# capsule:allow` on a later line suppresses a PEM block — kill: B11 |
| 393 | 23 | `begin_line = text[start:newline if newline != -1 else len(text)]` → `begin_line = text[start:newline if (newline != -1) and False else len…` | b | `# capsule:allow` on a later line suppresses a PEM block — kill: B11 |
| 393 | 24 | `begin_line = text[start:newline if newline != -1 else len(text)]` → `begin_line = text[start:newline if (newline != -1) or True else len(t…` | c4 | begin_line edge: stricter, only when BEGIN is not on line 1 / has no trailing LF |
| 393 | 25 | `begin_line = text[start:newline if newline != -1 else len(text)]` → `begin_line = text[start:newline if newline == -1 else len(text)]` | b | `# capsule:allow` on a later line suppresses a PEM block — kill: B11 |
| 393 | 26 | `begin_line = text[start:newline if newline != -1 else len(text)]` → `begin_line = text[start:newline if newline != +1 else len(text)]` | a | newline index can never be 1 or 2 after a BEGIN marker |
| 393 | 27 | `begin_line = text[start:newline if newline != -1 else len(text)]` → `begin_line = text[start:newline if newline != -2 else len(text)]` | a | newline index can never be 1 or 2 after a BEGIN marker |
| 395 | 30 | `continue` → `break` | c7 | break after an allowed PEM block hides later PEM blocks |
| 399 | 36 | `"match": _redact_value(text[start:end]),` → `"XXmatchXX": _redact_value(text[start:end]),` | c2 | tier/reason/match field values |
| 399 | 37 | `"match": _redact_value(text[start:end]),` → `"MATCH": _redact_value(text[start:end]),` | c2 | tier/reason/match field values |
| 402 | 46 | `"tier": "A",` → `"XXtierXX": "A",` | c2 | tier/reason/match field values |
| 402 | 47 | `"tier": "A",` → `"TIER": "A",` | c2 | tier/reason/match field values |
| 402 | 48 | `"tier": "A",` → `"tier": "XXAXX",` | c2 | tier/reason/match field values |
| 402 | 49 | `"tier": "A",` → `"tier": "a",` | c2 | tier/reason/match field values |
| 408 | 66 | `line = line[:start] + " " * (end - start) + line[end:]` → `line = line[:start] + "XX XX" * (end - start) + line[end:]` | c4 | masking width of derived_from / digest values |
| 408 | 67 | `line = line[:start] + " " * (end - start) + line[end:]` → `line = line[:start] + " " * (end + start) + line[end:]` | c4 | masking width of derived_from / digest values |
| 411 | 73 | `line = _DIGEST_LINE_RE.sub(lambda m: " " * len(m.group(0)), line)` → `line = _DIGEST_LINE_RE.sub(lambda m: None, line)` | c4 | masking width of derived_from / digest values |
| 411 | 75 | `line = _DIGEST_LINE_RE.sub(lambda m: " " * len(m.group(0)), line)` → `line = _DIGEST_LINE_RE.sub(lambda m: "XX XX" * len(m.group(0)), line)` | c4 | masking width of derived_from / digest values |
| 423 | 89 | `"tier": tier,` → `"XXtierXX": tier,` | c2 | tier/reason/match field values |
| 423 | 90 | `"tier": tier,` → `"TIER": tier,` | c2 | tier/reason/match field values |
| 429 | 93 | `val = m.groupdict().get("val") or m.group(0)` → `val = m.groupdict().get("val") and m.group(0)` | a | val == group(0) == group(1) for every shape rule / blocking None is falsy |
| 429 | 94 | `val = m.groupdict().get("val") or m.group(0)` → `val = m.groupdict().get(None) or m.group(0)` | a | val == group(0) == group(1) for every shape rule / blocking None is falsy |
| 429 | 95 | `val = m.groupdict().get("val") or m.group(0)` → `val = m.groupdict().get("XXvalXX") or m.group(0)` | a | val == group(0) == group(1) for every shape rule / blocking None is falsy |
| 429 | 96 | `val = m.groupdict().get("val") or m.group(0)` → `val = m.groupdict().get("VAL") or m.group(0)` | a | val == group(0) == group(1) for every shape rule / blocking None is falsy |
| 429 | 97 | `val = m.groupdict().get("val") or m.group(0)` → `val = m.groupdict().get("val") or m.group(None)` | a | val == group(0) == group(1) for every shape rule / blocking None is falsy |
| 429 | 98 | `val = m.groupdict().get("val") or m.group(0)` → `val = m.groupdict().get("val") or m.group(1)` | a | val == group(0) == group(1) for every shape rule / blocking None is falsy |
| 430 | 104 | `add(m.start(), m.end(), reason, val, True, "A")` → `add(m.start(), m.end(), reason, val, True, None)` | c2 | tier/reason/match field values |
| 430 | 112 | `add(m.start(), m.end(), reason, val, True, "A")` → `add(m.start(), m.end(), reason, val, True, "XXAXX")` | c2 | tier/reason/match field values |
| 430 | 113 | `add(m.start(), m.end(), reason, val, True, "A")` → `add(m.start(), m.end(), reason, val, True, "a")` | c2 | tier/reason/match field values |
| 434 | 115 | `lo = max(0, m.start() - _IBM_PROXIMITY)` → `lo = None` | c4 | IBM keyword proximity window |
| 434 | 120 | `lo = max(0, m.start() - _IBM_PROXIMITY)` → `lo = max(1, m.start() - _IBM_PROXIMITY)` | c4 | IBM keyword proximity window |
| 435 | 122 | `hi = min(len(line), m.end() + _IBM_PROXIMITY)` → `hi = None` | c4 | IBM keyword proximity window |
| 437 | 131 | `add(m.start(), m.end(), "ibm_quantum_token", m.group(0), True, "A")` → `add(m.start(), m.end(), None, m.group(0), True, "A")` | c2 | tier/reason/match field values |
| 437 | 134 | `add(m.start(), m.end(), "ibm_quantum_token", m.group(0), True, "A")` → `add(m.start(), m.end(), "ibm_quantum_token", m.group(0), True, None)` | c2 | tier/reason/match field values |
| 437 | 141 | `add(m.start(), m.end(), "ibm_quantum_token", m.group(0), True, "A")` → `add(m.start(), m.end(), "XXibm_quantum_tokenXX", m.group(0), True, "A…` | c2 | reason string |
| 437 | 142 | `add(m.start(), m.end(), "ibm_quantum_token", m.group(0), True, "A")` → `add(m.start(), m.end(), "IBM_QUANTUM_TOKEN", m.group(0), True, "A")` | c2 | reason string |
| 437 | 146 | `add(m.start(), m.end(), "ibm_quantum_token", m.group(0), True, "A")` → `add(m.start(), m.end(), "ibm_quantum_token", m.group(0), True, "XXAXX…` | c2 | tier/reason/match field values |
| 437 | 147 | `add(m.start(), m.end(), "ibm_quantum_token", m.group(0), True, "A")` → `add(m.start(), m.end(), "ibm_quantum_token", m.group(0), True, "a")` | c2 | tier/reason/match field values |
| 443 | 159 | `add(m.start("val"), m.end("val"), "name_pattern", val, True, "A")` → `add(m.start("val"), m.end("val"), "name_pattern", val, True, None)` | c2 | tier/reason/match field values |
| 443 | 175 | `add(m.start("val"), m.end("val"), "name_pattern", val, True, "A")` → `add(m.start("val"), m.end("val"), "name_pattern", val, True, "XXAXX")` | c2 | tier/reason/match field values |
| 443 | 176 | `add(m.start("val"), m.end("val"), "name_pattern", val, True, "A")` → `add(m.start("val"), m.end("val"), "name_pattern", val, True, "a")` | c2 | tier/reason/match field values |
| 447 | 178 | `add(m.start("val"), m.end("val"), "constructor_pattern",` → `add(None, m.end("val"), "constructor_pattern",` | c4 | constructor span None |
| 447 | 179 | `add(m.start("val"), m.end("val"), "constructor_pattern",` → `add(m.start("val"), None, "constructor_pattern",` | c4 | constructor span None |
| 448 | 183 | `m.group("val"), True, "A")` → `m.group("val"), True, None)` | c2 | tier/reason/match field values |
| 448 | 202 | `m.group("val"), True, "A")` → `m.group("val"), True, "XXAXX")` | c2 | tier/reason/match field values |
| 448 | 203 | `m.group("val"), True, "A")` → `m.group("val"), True, "a")` | c2 | tier/reason/match field values |
| 454 | 210 | `continue` → `break` | c4 | continue->break in allowlist / plausibility / overlap / allow filters: later candidates on the same line drop… |
| 457 | 217 | `continue` → `break` | c4 | continue->break in allowlist / plausibility / overlap / allow filters: later candidates on the same line drop… |
| 458 | 222 | `add(m.start("val"), m.end("val"), "name_entropy", val, False, "B")` → `add(m.start("val"), m.end("val"), "name_entropy", val, None, "B")` | a | val == group(0) == group(1) for every shape rule / blocking None is falsy |
| 458 | 223 | `add(m.start("val"), m.end("val"), "name_entropy", val, False, "B")` → `add(m.start("val"), m.end("val"), "name_entropy", val, False, None)` | c2 | tier/reason/match field values |
| 458 | 236 | `add(m.start("val"), m.end("val"), "name_entropy", val, False, "B")` → `add(m.start("val"), m.end("val"), "XXname_entropyXX", val, False, "B")` | c2 | tier/reason/match field values |
| 458 | 239 | `add(m.start("val"), m.end("val"), "name_entropy", val, False, "B")` → `add(m.start("val"), m.end("val"), "name_entropy", val, False, "XXBXX")` | c2 | tier/reason/match field values |
| 458 | 240 | `add(m.start("val"), m.end("val"), "name_entropy", val, False, "B")` → `add(m.start("val"), m.end("val"), "name_entropy", val, False, "b")` | c2 | tier/reason/match field values |
| 462 | 244 | `add(start, end, reason, val, False, "B")` → `add(start, end, None, val, False, "B")` | c2 | tier/reason/match field values |
| 462 | 246 | `add(start, end, reason, val, False, "B")` → `add(start, end, reason, val, None, "B")` | a | val == group(0) == group(1) for every shape rule / blocking None is falsy |
| 462 | 247 | `add(start, end, reason, val, False, "B")` → `add(start, end, reason, val, False, None)` | c2 | tier/reason/match field values |
| 462 | 255 | `add(start, end, reason, val, False, "B")` → `add(start, end, reason, val, False, "XXBXX")` | c2 | tier/reason/match field values |
| 462 | 256 | `add(start, end, reason, val, False, "B")` → `add(start, end, reason, val, False, "b")` | c2 | tier/reason/match field values |
| 465 | 263 | `candidates.sort(key=lambda c: (not c[2]["blocking"], c[0]))` → `candidates.sort(key=lambda c: (not c[2]["blocking"], c[1]))` | c4 | dedup ordering / adjacent spans |
| 468 | 266 | `if any(start < a_end and end > a_start for a_start, a_end in accepted…` → `if any(start < a_end or end > a_start for a_start, a_end in accepted):` | c7 | second finding on a line dropped as an 'overlap' — kill: C-two |
| 468 | 267 | `if any(start < a_end and end > a_start for a_start, a_end in accepted…` → `if any(start <= a_end and end > a_start for a_start, a_end in accepte…` | c4 | dedup ordering / adjacent spans |
| 468 | 268 | `if any(start < a_end and end > a_start for a_start, a_end in accepted…` → `if any(start < a_end and end >= a_start for a_start, a_end in accepte…` | c4 | dedup ordering / adjacent spans |
| 469 | 269 | `continue` → `break` | c4 | continue->break in allowlist / plausibility / overlap / allow filters: later candidates on the same line drop… |
| 472 | 276 | `continue` → `break` | c4 | continue->break in allowlist / plausibility / overlap / allow filters: later candidates on the same line drop… |

**`_joined`** — 2 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 483 | 2 | `return "".join(v for v in value if isinstance(v, str))` → `return "XXXX".join(v for v in value if isinstance(v, str))` | c7 | junk inserted between notebook source lines |
| 484 | 3 | `return ""` → `return "XXXX"` | a | junk string matches no rule |

**`_scan_notebook`** — 33 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 524 | 24 | `continue` → `break` | b | a non-dict cell / non-list outputs / non-dict output ends the whole notebook scan — kill: B10 |
| 529 | 41 | `continue` → `break` | b | a non-dict cell / non-list outputs / non-dict output ends the whole notebook scan — kill: B10 |
| 532 | 44 | `continue` → `break` | b | a non-dict cell / non-list outputs / non-dict output ends the whole notebook scan — kill: B10 |
| 534 | 48 | `output_type = output.get("output_type", "")` → `output_type = output.get("output_type", None)` | a | output_type default: neither branch matches |
| 534 | 50 | `output_type = output.get("output_type", "")` → `output_type = output.get("output_type", )` | a | output_type default: neither branch matches |
| 534 | 53 | `output_type = output.get("output_type", "")` → `output_type = output.get("output_type", "XXXX")` | a | output_type default: neither branch matches |
| 537 | 67 | `elif output_type in ("display_data", "execute_result"):` → `elif output_type in ("XXdisplay_dataXX", "execute_result"):` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 537 | 68 | `elif output_type in ("display_data", "execute_result"):` → `elif output_type in ("DISPLAY_DATA", "execute_result"):` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 537 | 69 | `elif output_type in ("display_data", "execute_result"):` → `elif output_type in ("display_data", "XXexecute_resultXX"):` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 537 | 70 | `elif output_type in ("display_data", "execute_result"):` → `elif output_type in ("display_data", "EXECUTE_RESULT"):` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 538 | 71 | `data = output.get("data")` → `data = None` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 538 | 72 | `data = output.get("data")` → `data = output.get(None)` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 538 | 73 | `data = output.get("data")` → `data = output.get("XXdataXX")` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 538 | 74 | `data = output.get("data")` → `data = output.get("DATA")` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 539 | 76 | `if isinstance(data, dict) and "text/plain" in data:` → `if isinstance(data, dict) and "XXtext/plainXX" in data:` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 539 | 77 | `if isinstance(data, dict) and "text/plain" in data:` → `if isinstance(data, dict) and "TEXT/PLAIN" in data:` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 539 | 78 | `if isinstance(data, dict) and "text/plain" in data:` → `if isinstance(data, dict) and "text/plain" not in data:` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 540 | 79 | `scan(data["text/plain"], cell_index, location)` → `scan(None, cell_index, location)` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 540 | 80 | `scan(data["text/plain"], cell_index, location)` → `scan(data["text/plain"], None, location)` | c2 | cell/location metadata |
| 540 | 81 | `scan(data["text/plain"], cell_index, location)` → `scan(data["text/plain"], cell_index, None)` | c2 | cell/location metadata |
| 540 | 82 | `scan(data["text/plain"], cell_index, location)` → `scan(cell_index, location)` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 540 | 83 | `scan(data["text/plain"], cell_index, location)` → `scan(data["text/plain"], location)` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 540 | 84 | `scan(data["text/plain"], cell_index, location)` → `scan(data["text/plain"], cell_index, )` | c2 | cell/location metadata |
| 540 | 85 | `scan(data["text/plain"], cell_index, location)` → `scan(data["XXtext/plainXX"], cell_index, location)` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 540 | 86 | `scan(data["text/plain"], cell_index, location)` → `scan(data["TEXT/PLAIN"], cell_index, location)` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 542 | 91 | `scan(output.get("traceback"), cell_index, location)` → `scan(output.get("traceback"), None, location)` | c2 | cell/location metadata |
| 542 | 92 | `scan(output.get("traceback"), cell_index, location)` → `scan(output.get("traceback"), cell_index, None)` | c2 | cell/location metadata |
| 543 | 99 | `scan(output.get("evalue"), cell_index, location)` → `scan(None, cell_index, location)` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 543 | 100 | `scan(output.get("evalue"), cell_index, location)` → `scan(output.get("evalue"), None, location)` | c2 | cell/location metadata |
| 543 | 101 | `scan(output.get("evalue"), cell_index, location)` → `scan(output.get("evalue"), cell_index, None)` | c2 | cell/location metadata |
| 543 | 105 | `scan(output.get("evalue"), cell_index, location)` → `scan(output.get(None), cell_index, location)` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 543 | 106 | `scan(output.get("evalue"), cell_index, location)` → `scan(output.get("XXevalueXX"), cell_index, location)` | c7 | display_data/execute_result text and error evalue outputs never asserted |
| 543 | 107 | `scan(output.get("evalue"), cell_index, location)` → `scan(output.get("EVALUE"), cell_index, location)` | c7 | display_data/execute_result text and error evalue outputs never asserted |

**`finding_location`** — 6 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 550 | 1 | `if "field" in finding:` → `if "XXfieldXX" in finding:` | c2 |  |
| 550 | 2 | `if "field" in finding:` → `if "FIELD" in finding:` | c2 |  |
| 555 | 21 | `if finding.get("location", "source") != "source":` → `if finding.get("location", None) != "source":` | a | location is always set by _scan_notebook |
| 555 | 23 | `if finding.get("location", "source") != "source":` → `if finding.get("location", ) != "source":` | a | location is always set by _scan_notebook |
| 555 | 26 | `if finding.get("location", "source") != "source":` → `if finding.get("location", "XXsourceXX") != "source":` | a | location is always set by _scan_notebook |
| 555 | 27 | `if finding.get("location", "source") != "source":` → `if finding.get("location", "SOURCE") != "source":` | a | location is always set by _scan_notebook |

**`_scan_manifest_values`** — 28 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 579 | 31 | `if keys and keys[-1] == "derived_from" and re.fullmatch(r"mqc:[0-9]+:…` → `if keys and keys[-1] == "derived_from" or re.fullmatch(r"mqc:[0-9]+:[…` | c4 | precedence: mqc IDs under any key skipped |
| 583 | 47 | `f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_as…` → `f"{json.dumps(key, ensure_ascii=None)}: {json.dumps(value, ensure_asc…` | a | ASCII tokens unaffected / falsy / label of throwaway scan |
| 583 | 49 | `f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_as…` → `f"{json.dumps(key, )}: {json.dumps(value, ensure_ascii=False)}"` | a | ASCII tokens unaffected / falsy / label of throwaway scan |
| 583 | 50 | `f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_as…` → `f"{json.dumps(key, ensure_ascii=True)}: {json.dumps(value, ensure_asc…` | a | ASCII tokens unaffected / falsy / label of throwaway scan |
| 583 | 52 | `f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_as…` → `f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_as…` | a | ASCII tokens unaffected / falsy / label of throwaway scan |
| 583 | 54 | `f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_as…` → `f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, )}"` | a | ASCII tokens unaffected / falsy / label of throwaway scan |
| 583 | 55 | `f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_as…` → `f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_as…` | a | ASCII tokens unaffected / falsy / label of throwaway scan |
| 588 | 57 | `for finding in _scan_text(representation, "capsule.yaml", honor_allow…` → `for finding in _scan_text(representation, None, honor_allow=False):` | c2 | field/file/line metadata of manifest-value findings |
| 588 | 58 | `for finding in _scan_text(representation, "capsule.yaml", honor_allow…` → `for finding in _scan_text(representation, "capsule.yaml", honor_allow…` | a | ASCII tokens unaffected / falsy / label of throwaway scan |
| 588 | 62 | `for finding in _scan_text(representation, "capsule.yaml", honor_allow…` → `for finding in _scan_text(representation, "XXcapsule.yamlXX", honor_a…` | c2 | field/file/line metadata of manifest-value findings |
| 588 | 63 | `for finding in _scan_text(representation, "capsule.yaml", honor_allow…` → `for finding in _scan_text(representation, "CAPSULE.YAML", honor_allow…` | c2 | field/file/line metadata of manifest-value findings |
| 591 | 71 | `continue` → `break` | c4 | dedup of text-vs-value findings; allow handling of key text |
| 592 | 72 | `seen.add(identity)` → `seen.add(None)` | c4 | dedup of text-vs-value findings; allow handling of key text |
| 593 | 76 | `safe_path = ["[redacted-key]" if _scan_text(p, "key", honor_allow=Fal…` → `safe_path = ["XX[redacted-key]XX" if _scan_text(p, "key", honor_allow…` | c2 | field/file/line metadata of manifest-value findings |
| 593 | 77 | `safe_path = ["[redacted-key]" if _scan_text(p, "key", honor_allow=Fal…` → `safe_path = ["[REDACTED-KEY]" if _scan_text(p, "key", honor_allow=Fal…` | c2 | field/file/line metadata of manifest-value findings |
| 593 | 79 | `safe_path = ["[redacted-key]" if _scan_text(p, "key", honor_allow=Fal…` → `safe_path = ["[redacted-key]" if _scan_text(p, None, honor_allow=Fals…` | a | ASCII tokens unaffected / falsy / label of throwaway scan |
| 593 | 80 | `safe_path = ["[redacted-key]" if _scan_text(p, "key", honor_allow=Fal…` → `safe_path = ["[redacted-key]" if _scan_text(p, "key", honor_allow=Non…` | a | ASCII tokens unaffected / falsy / label of throwaway scan |
| 593 | 83 | `safe_path = ["[redacted-key]" if _scan_text(p, "key", honor_allow=Fal…` → `safe_path = ["[redacted-key]" if _scan_text(p, "key", ) else p` | c4 | dedup of text-vs-value findings; allow handling of key text |
| 593 | 84 | `safe_path = ["[redacted-key]" if _scan_text(p, "key", honor_allow=Fal…` → `safe_path = ["[redacted-key]" if _scan_text(p, "XXkeyXX", honor_allow…` | a | ASCII tokens unaffected / falsy / label of throwaway scan |
| 593 | 85 | `safe_path = ["[redacted-key]" if _scan_text(p, "key", honor_allow=Fal…` → `safe_path = ["[redacted-key]" if _scan_text(p, "KEY", honor_allow=Fal…` | a | ASCII tokens unaffected / falsy / label of throwaway scan |
| 593 | 86 | `safe_path = ["[redacted-key]" if _scan_text(p, "key", honor_allow=Fal…` → `safe_path = ["[redacted-key]" if _scan_text(p, "key", honor_allow=Tru…` | c4 | dedup of text-vs-value findings; allow handling of key text |
| 595 | 87 | `finding.update(line=0, field="/" + "/".join(` → `finding.update(line=None, field="/" + "/".join(` | c2 | field/file/line metadata of manifest-value findings |
| 595 | 89 | `finding.update(line=0, field="/" + "/".join(` → `finding.update(field="/" + "/".join(` | c2 | field/file/line metadata of manifest-value findings |
| 595 | 91 | `finding.update(line=0, field="/" + "/".join(` → `finding.update(line=1, field="/" + "/".join(` | c2 | field/file/line metadata of manifest-value findings |
| 596 | 104 | `p.replace("~", "~0").replace("/", "~1") for p in safe_path))` → `p.replace("XX~XX", "~0").replace("/", "~1") for p in safe_path))` | c2 | field/file/line metadata of manifest-value findings |
| 596 | 105 | `p.replace("~", "~0").replace("/", "~1") for p in safe_path))` → `p.replace("~", "XX~0XX").replace("/", "~1") for p in safe_path))` | c2 | field/file/line metadata of manifest-value findings |
| 596 | 106 | `p.replace("~", "~0").replace("/", "~1") for p in safe_path))` → `p.replace("~", "~0").replace("XX/XX", "~1") for p in safe_path))` | c2 | field/file/line metadata of manifest-value findings |
| 596 | 107 | `p.replace("~", "~0").replace("/", "~1") for p in safe_path))` → `p.replace("~", "~0").replace("/", "XX~1XX") for p in safe_path))` | c2 | field/file/line metadata of manifest-value findings |

**`_looks_binary`** — 1 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 613 | 10 | `return False` → `return True` | c4 | unreadable file treated as binary |

**`CapsuleRedactor.__init__`** — 2 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 629 | 10 | `raise ValueError(f"mode must be 'block' or 'warn_only', got {mode!r}")` → `raise ValueError(None)` | c1 |  |
| 637 | 17 | `self.capsuleignore_patterns = sorted(self._capsuleignore)` → `self.capsuleignore_patterns = None` | c2 |  |

**`CapsuleRedactor.scan`** — 21 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 668 | 11 | `continue` → `break` | b | a symlink / ignored / binary / unreadable entry ends the scan of every later file — kill: B12 |
| 672 | 17 | `entries.append((rel, pending.pop(rel) if rel in pending else file_pat…` → `entries.append((rel, pending.pop(rel) if (rel in pending) and False e…` | a | override text still scanned via pending / notebook JSON is not binary / codec case |
| 682 | 29 | `"line": 0,` → `"line": 1,` | c2 |  |
| 683 | 30 | `"match": rel,` → `"XXmatchXX": rel,` | c2 |  |
| 683 | 31 | `"match": rel,` → `"MATCH": rel,` | c2 |  |
| 686 | 39 | `"tier": "file",` → `"XXtierXX": "file",` | c2 |  |
| 686 | 40 | `"tier": "file",` → `"TIER": "file",` | c2 |  |
| 686 | 41 | `"tier": "file",` → `"tier": "XXfileXX",` | c2 |  |
| 686 | 42 | `"tier": "file",` → `"tier": "FILE",` | c2 |  |
| 692 | 53 | `continue` → `break` | b | a symlink / ignored / binary / unreadable entry ends the scan of every later file — kill: B12 |
| 696 | 57 | `if not rel.endswith(".ipynb") and _looks_binary(source):` → `if not rel.endswith("XX.ipynbXX") and _looks_binary(source):` | a | override text still scanned via pending / notebook JSON is not binary / codec case |
| 696 | 58 | `if not rel.endswith(".ipynb") and _looks_binary(source):` → `if not rel.endswith(".IPYNB") and _looks_binary(source):` | a | override text still scanned via pending / notebook JSON is not binary / codec case |
| 698 | 61 | `continue` → `break` | b | a symlink / ignored / binary / unreadable entry ends the scan of every later file — kill: B12 |
| 700 | 63 | `content = source.read_text(encoding="utf-8", errors="replace")` → `content = source.read_text(encoding=None, errors="replace")` | c5 |  |
| 700 | 64 | `content = source.read_text(encoding="utf-8", errors="replace")` → `content = source.read_text(encoding="utf-8", errors=None)` | c4 | non-UTF-8 files silently skipped |
| 700 | 65 | `content = source.read_text(encoding="utf-8", errors="replace")` → `content = source.read_text(errors="replace")` | c5 |  |
| 700 | 66 | `content = source.read_text(encoding="utf-8", errors="replace")` → `content = source.read_text(encoding="utf-8", )` | c4 | non-UTF-8 files silently skipped |
| 700 | 68 | `content = source.read_text(encoding="utf-8", errors="replace")` → `content = source.read_text(encoding="UTF-8", errors="replace")` | a | override text still scanned via pending / notebook JSON is not binary / codec case |
| 700 | 69 | `content = source.read_text(encoding="utf-8", errors="replace")` → `content = source.read_text(encoding="utf-8", errors="XXreplaceXX")` | c4 | non-UTF-8 files silently skipped |
| 700 | 70 | `content = source.read_text(encoding="utf-8", errors="replace")` → `content = source.read_text(encoding="utf-8", errors="REPLACE")` | c4 | non-UTF-8 files silently skipped |
| 702 | 71 | `continue` → `break` | b | a symlink / ignored / binary / unreadable entry ends the scan of every later file — kill: B12 |

**`CapsuleRedactor.scan_and_raise`** — 7 survivor(s)

| line | # | original → mutant | class | note / test |
|---|---|---|---|---|
| 735 | 15 | `summary = "; ".join(` → `summary = "XX; XX".join(` | c1 |  |
| 736 | 19 | `f"{finding_location(f)} ({f['reason']})" for f in blocking[:5]` → `f"{finding_location(f)} ({f['reason']})" for f in blocking[:6]` | c1 |  |
| 747 | 30 | `f"{', '.join(sorted(set(credential_files)))}. "` → `f"{'XX, XX'.join(sorted(set(credential_files)))}. "` | c1 |  |
| 752 | 33 | `advice = "Remove secrets or annotate with # capsule:allow to suppress…` → `advice = None` | c1 |  |
| 752 | 34 | `advice = "Remove secrets or annotate with # capsule:allow to suppress…` → `advice = "XXRemove secrets or annotate with # capsule:allow to suppre…` | c1 |  |
| 752 | 35 | `advice = "Remove secrets or annotate with # capsule:allow to suppress…` → `advice = "remove secrets or annotate with # capsule:allow to suppress…` | c1 |  |
| 752 | 36 | `advice = "Remove secrets or annotate with # capsule:allow to suppress…` → `advice = "REMOVE SECRETS OR ANNOTATE WITH # CAPSULE:ALLOW TO SUPPRESS…` | c1 |  |
