# Changelog

All notable changes to marqov-capsule are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.1.0] — UNRELEASED

First public release. Nothing was published before this, despite an earlier
entry in this file dated 2026-07-22 — that entry described a release that never
happened and has been folded into this one.

### Conference readiness

- Added a runnable SDK local Bell-state export and capsule archive/tamper demonstration.
- Published fixed conformance outputs and tests for digest identity, schema validity, and credential findings.
- Reconciled the statistical verification description with the implemented one-sided bound and verifier-owned policy.
- Reject mapping keys that collide after NFC normalization or legacy key conversion, rather than silently dropping a value.
- Avoid credential-scanner false positives on versioned `derived_from` IDs while preserving detection elsewhere on the same line.
- Corrected source-install instructions and versioned-ID documentation ahead of first publication.

### What 0.1.0 is

- **Sealing** — `CapsuleBuilder` scans for credentials, writes `.checksums`, embeds `checksums_digest`, transitions lifecycle to `sealed`, and returns a versioned `mqc:1:<64 lowercase hex chars>` capsule ID derived from RFC 8785 canonical JSON of the manifest.
- **Integrity verification** — `CapsuleVerifier.verify_integrity()` checks all three layers of the digest chain: payload files against `.checksums` (a closed set — injected files fail), `.checksums` against `checksums_digest`, and the recomputed capsule ID against a trusted ID you supply.
- **Deterministic archives** — `pack` produces a byte-reproducible `.capsule` tarball; `unpack` restores it; `verify` accepts either form.
- **Validation** — `CapsuleValidator` against the bundled JSON Schema 2020-12.
- **Credential scanning** — `CapsuleRedactor` gates sealing. Best-effort defence-in-depth, not a guarantee; see #18.
- **CLI** — `init`, `seal`, `verify`, `inspect`, `open`, `validate`, `pack`, `unpack`.
- **Spec v1** — the format at `spec/v1/` (CC-BY-4.0), independently implementable.

Statistical equivalence testing is **not** in this release — see Not included below.

### Not claimed

Capsules carry no signatures. The digest chain detects **modification, not forgery**: anyone who rewrites the payload, `.checksums` and manifest together produces a self-consistent capsule with a different ID. A capsule ID is only as trustworthy as the channel you received it over. Tracked in #16.

### Not included

- **Statistical equivalence testing has no CLI surface in 0.1.0** (#15). `verify --against` and its `--epsilon` / `--min-shots` / `--honor-calibration-drift` options are not wired up. The underlying estimator, however, is fixed: `CapsuleVerifier.verify_statistical` no longer uses a bootstrap CI — it was provably inconsistent for this functional (TVD is not Hadamard-differentiable at `p = q`, the null under test) and rejected a distribution compared *against itself* as non-reproducible from roughly four qubits upward. It now uses a closed-form one-sided upper confidence bound (Jensen + McDiarmid, no resampling, no seed), and no longer reports an affirmative `REJECTED`, so the verdict space is `VERIFIED` / `INCONCLUSIVE`. A valid lower bound on true TVD does exist (triangle inequality: plug-in estimate minus McDiarmid slack minus a one-sample bias term per arm) but isn't deployed — it depends on the outcome count `K`, and taking `K` from observed support rather than the declared register width fails open, unlike the upper bound's `K`-free slack. The one candidate detection tool (a permutation test against the sharp null) measured power as low as 42% at K=256, too weak to carry an affirmative verdict.

  `VerificationPolicy` (#30) already enforces the trust boundary this needs. Wiring the CLI back up, and reconciling the spec's `tvd_threshold`/`ci_level`/`n_resamples` field names with the implementation's verifier-owned settings vocabulary (`epsilon`, `epsilon_drift`, `min_shots`, `tolerance_regime`, `alpha` — `ci_level` is not read), is tracked in #20. Analysis: `docs/research/2026-08-10-tvd-equivalence-testing.md`.

---

## Development notes

Nothing below is a change *from* a previous release — there wasn't one. These
are the substantive defects found and fixed on the way to 0.1.0, recorded
because what a project looked for says as much as what it shipped.

### Integrity

- **The README's first command works** (#19). `marqov-capsule init --name … --qubits 2` exited 2 — `init` takes a required positional `DIRECTORY` — so a new user's very first documented command failed. The CLI block now passes explicit paths throughout, which also makes it copy-pasteable as a unit with no `cd`. Also corrected: the CLI table said `init` scaffolds "in the current directory"; the install note claimed Python 3.9+ (it has been 3.10+ since #28); the quickstart printed a fabricated capsule ID (`e3b0c442…`, which is the SHA-256 of the empty string); and every relative link rendered as a dead link on the PyPI project page.
- **The payload layout is documented** (#19). The quickstart wrote `results.json` at the capsule root while `verify --against` required `payload/results.json`. That requirement left with the statistical path, so the README now states what is actually true: any file that is not `capsule.yaml` or `.checksums` is payload, and the `payload/` `source/` `environment/` split in the conformance fixtures is a convention rather than a rule.

- **Tamper-evidence: `verify` and `open` now check all three digest-chain layers** (#14). Only layer 1 (payload files vs `.checksums`) was implemented; `checksums_digest` was written at seal time and never recomputed, and the capsule ID was computed only to be printed. Editing a payload file and re-running `save_checksums` therefore passed verification with exit 0. `CapsuleVerifier.verify_integrity()` implements spec §6 in full and is what the CLI now calls.
- **`verify` no longer passes on injected files** (#17). `.checksums` pins a closed set, but `verify_checksums` computed the `extra` list and then ignored it, so a sealed capsule could carry arbitrary undeclared files. Injection also leaves `checksums_digest` and the capsule ID intact, so no other layer could catch it.
- **`capsule.yaml` and `.checksums` are excluded from checksumming by path, not basename.** Both the builder and verifier matched on filename anywhere in the tree, so `payload/capsule.yaml` was skipped at seal time *and* ignored by the extra-file scan — an injection vector invisible to every layer. Only the root-level files are excluded now.

- **`CapsuleVerifier.verify_integrity`(capsule_dir, expected_id=None)`** — full spec §6 integrity check. Reports per-layer results (`checksums_digest_match`, `capsule_id`, `capsule_id_match`, `manifest_authenticated`) and a list of human-readable errors.
- **`verify --id` and `open --id`** — verify the manifest against a trusted capsule ID (layer 3). `capsule.yaml` is outside `.checksums` by design, so without a trusted ID the manifest is unauthenticated; `verify` now states this rather than reporting a bare pass. Combining `--id` with `--against` is rejected, since the statistical path checks no integrity layer.

### Credential scanning

- **The redactor now scans Jupyter notebook source cells** (#33). `_scan_notebook` walked only `cell["outputs"]`, so a live token pasted into a code cell — where it actually happens — passed the seal gate that the identical line in a `.py` file would have blocked. Markdown cells and `error` output tracebacks are scanned too; tracebacks routinely echo the offending line. Notebook fields are now defensively typed, since a hand-edited or truncated `.ipynb` must scan to nothing rather than raise.
- **Credential-bearing files are a finding, not a scan exclusion** (#34). `.env`, `*.pem` and `*.key` sat in the redactor's default *ignore* list while `save_checksums` packaged them regardless — so a directory holding `.env` and `deploy.key` scanned clean and sealed with both inside. Presence is now the finding: not scanning a secret does not make it absent from the capsule. `.p12`, `.pfx`, `id_rsa` and `id_ed25519` are covered too, no ignore rule can suppress them, and the remediation message says to move the file rather than offering `# capsule:allow`, which is line-based and cannot suppress a whole-file finding.
- **`.capsuleignore` can no longer silently narrow the credential scan** (#34). It is read from *inside* the capsule and previously **replaced** the entire default ignore set, so a capsule carrying one containing `source` disabled scanning for that whole subtree with no indication. Its patterns are now unioned with the defaults rather than substituted for them, `scan()` reports `skipped` paths and `capsuleignore_patterns`, and both `seal` and `seal --dry-run` print what was narrowed — with a note to review it when sealing a capsule you did not author.
- **Acceptance thresholds are no longer read from the capsule under test** (#30). `verify --against` took `verification_settings` from the *reference* capsule and handed them straight to the equivalence test, so a published capsule declaring `epsilon: 1.0` forced **every** comparison made against it to `VERIFIED` — TVD is bounded by 1. `tolerance_regime: calibration_drift` was a second lever on the same hole, swapping in a ~4× looser threshold. A third, `min_shots: 10^9`, forced `INCONCLUSIVE` on every comparison, letting a publisher call a result unfalsified because nothing could ever reject it.

  Thresholds now come from a `VerificationPolicy` owned by the verifier. A capsule's declaration is advisory: it may make verification **stricter** but never looser, and the effective value is reported alongside the verdict. New flags `--epsilon`, `--min-shots`, `--honor-calibration-drift`.
- **`verify --against` verifies integrity before comparing.** The statistical path ran no integrity check at all, so shot counts from a tampered capsule were compared as though they had been sealed. Both capsules must now pass `verify_integrity` first. This is a behaviour change: previously it would compare unsealed or draft capsules.
- **`verify_statistical`'s public surface changed along with the CI method** (#15). The `seed=` keyword argument is gone — the closed-form bound has nothing to seed. `REJECTED` is gone from the verdict space, which is now `VERIFIED` / `INCONCLUSIVE`. Emitted metrics are `tvd_ucb` and `alpha`, replacing `tvd_ci_lower`, `tvd_ci_upper`, `bootstrap_resamples`, and `rng_seed`.

### Packaging and format

- **The archive layer is restored** (#48). `marqov-capsule pack` produces a deterministic `.capsule` archive — byte-identical across runs via sorted members, zeroed entry and gzip timestamps, and fixed permissions — and `unpack` restores it. `verify` now accepts a directory or an archive interchangeably, unpacking to a temporary directory to check the contents.

  `src/marqov_capsule/archive.py` and 26 of its tests were deleted by `98f963d`, a `chore:`-labelled commit that removed 1,768 lines as "legacy first-pass files". The module was never broken: it depends only on stdlib and passed unmodified against current code. Its tests failed for a single reason — a builder constructor that had changed the day before — and were deleted rather than migrated. See #48 for the full audit of what else that commit removed.

- **`archive.payload_digest`** — SHA-256 of the `.checksums` bytes. Restored as `content_id`, then renamed, because the name overclaimed: `.checksums` excludes `capsule.yaml`, so two capsules with identical payloads but different manifests produce the same value. It is also, by construction, the number the manifest already stores as `checksums_digest`. `pack` and `verify` now report the **capsule ID** as identity and label the payload digest as what it is. Naming a capsule by the payload digest would have reintroduced the layer-1-only identity that #14 was about.
- `verify` output header is now `Integrity verification:` (was `Checksum verification:`) and lists the recomputed capsule ID, injected files, and per-layer failures.

[0.1.0]: https://github.com/marqov-dev/marqov-capsule/releases/tag/v0.1.0

### Inspection and base-install coverage

- Escape terminal controls in human-readable `inspect` metadata while preserving readable Unicode and JSON round-tripping (#35).
- Run checksum, traversal, symlink, deterministic verification, and early statistical-return tests without NumPy/SciPy; skip only individual tests needing those dependencies (#39).

### Release checks

- Anchor URL scanning at the repository root and preserve tracked filenames containing whitespace. Malformed URLs fail individually; DNS and HTTP outages are reported as inconclusive warnings. Reviewed Marqov hosts are checked independently of DNS, with a required offline CI job.
- Retry restricted HEAD requests with GET, close responses, and exclude the schema identifier from retrieval checks.
- Assert that the spec's advertised schema ID matches the shipped schema and that CI Success includes every job. Make the domain regression guard fail on Git errors and narrow its historical exception to one exact line.

### Cross-language conformance

- Added a pinned Node/YAML corpus checker with independent canonicalization and checksum serialization, required by CI. Added numeric-looking key and checksum path vectors.
- Fixed verification of percent-encoded checksum paths and trailing-space filenames. Decode the normative line format exactly once, reject noncanonical/duplicate paths, and preserve literal paths in legacy YAML checksum mappings.

### Manifest and policy validation

- Enforce declared date-time formats during schema validation, including nested execution timestamps. Add `rfc3339-validator` as a runtime dependency so base installs do not silently skip these checks.
- Treat overflowing numeric thresholds and alpha values as unusable inputs and fall back to verifier policy/defaults without raising `OverflowError`.

### Retired pre-release verification APIs

- Retire `verify_capsule`, `compare_capsules`, and `check_calibration_drift`: they could report success from metadata alone, no statistical tests, equal names, or missing fidelity values. Keep explicit migration errors at their public entry points and remove the old private verifier implementation. Supported integrity, deterministic-result, and count-equivalence APIs remain available; see `docs/legacy-verifier-migration.md`.
- Make `load_capsule` use the capsule YAML profile and reject duplicate keys or non-mapping documents. Loading remains separate from verification.

### Bundled release hardening

- Validate UUID fields, UTF-8 input, and the canonical JSON data model; reject recursive values, normalized key collisions, non-string keys, non-finite numbers, and unsafe integers.
- Resolve NFC checksum paths to filesystem entries and reject filename normalization collisions. Refuse symlinked metadata and non-regular payloads before reading, and report payload read errors as verification failures.
- Add trusted-ID CLI regressions for deleted payloads and a fully rewritten digest chain. Clarify the manifest-version pin, explicit environment capture, and zero-qubit classical workloads.
