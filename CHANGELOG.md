# Changelog

All notable changes to marqov-capsule are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- **The archive layer is restored** (#48). `marqov-capsule pack` produces a deterministic `.capsule` archive — byte-identical across runs via sorted members, zeroed entry and gzip timestamps, and fixed permissions — and `unpack` restores it. `verify` now accepts a directory or an archive interchangeably, unpacking to a temporary directory to check the contents.

  `src/marqov_capsule/archive.py` and 26 of its tests were deleted by `98f963d`, a `chore:`-labelled commit that removed 1,768 lines as "legacy first-pass files". The module was never broken: it depends only on stdlib and passed unmodified against current code. Its tests failed for a single reason — a builder constructor that had changed the day before — and were deleted rather than migrated. See #48 for the full audit of what else that commit removed.

- **`archive.payload_digest`** — SHA-256 of the `.checksums` bytes. Restored as `content_id`, then renamed, because the name overclaimed: `.checksums` excludes `capsule.yaml`, so two capsules with identical payloads but different manifests produce the same value. It is also, by construction, the number the manifest already stores as `checksums_digest`. `pack` and `verify` now report the **capsule ID** as identity and label the payload digest as what it is. Naming a capsule by the payload digest would have reintroduced the layer-1-only identity that #14 was about.

### Removed
- **Statistical equivalence testing is cut from 0.1.0** (#15). `verify --against` and its `--epsilon` / `--min-shots` / `--honor-calibration-drift` options are gone. The estimator is miscalibrated: a distribution compared *against itself* is REJECTED from roughly four qubits upward, because the plug-in TVD carries a noise floor of `√((K−1)/πn)` and the bootstrap interval is displaced upward by it rather than corrected downward. The bootstrap cannot be repaired for this functional — TVD is not Hadamard-differentiable at `p = q`, which is the null under test.

  Shipping it caveated would still have shipped a verdict carrying no information at realistic problem sizes, so it is cut until it is right. `CapsuleVerifier.verify_statistical` remains importable, and now emits a `FutureWarning`, so work on #15 does not have to begin by resurrecting deleted code. `VerificationPolicy` (#30) also stays, so the trust boundary is already correct when the feature returns. Spec §6's statistical procedure is marked under-revision, do-not-implement. Analysis: `docs/research/2026-08-10-tvd-equivalence-testing.md`.

### Security
- **The redactor now scans Jupyter notebook source cells** (#33). `_scan_notebook` walked only `cell["outputs"]`, so a live token pasted into a code cell — where it actually happens — passed the seal gate that the identical line in a `.py` file would have blocked. Markdown cells and `error` output tracebacks are scanned too; tracebacks routinely echo the offending line. Notebook fields are now defensively typed, since a hand-edited or truncated `.ipynb` must scan to nothing rather than raise.
- **Credential-bearing files are a finding, not a scan exclusion** (#34). `.env`, `*.pem` and `*.key` sat in the redactor's default *ignore* list while `save_checksums` packaged them regardless — so a directory holding `.env` and `deploy.key` scanned clean and sealed with both inside. Presence is now the finding: not scanning a secret does not make it absent from the capsule. `.p12`, `.pfx`, `id_rsa` and `id_ed25519` are covered too, no ignore rule can suppress them, and the remediation message says to move the file rather than offering `# capsule:allow`, which is line-based and cannot suppress a whole-file finding.
- **`.capsuleignore` can no longer silently narrow the credential scan** (#34). It is read from *inside* the capsule and previously **replaced** the entire default ignore set, so a capsule carrying one containing `source` disabled scanning for that whole subtree with no indication. Its patterns are now unioned with the defaults rather than substituted for them, `scan()` reports `skipped` paths and `capsuleignore_patterns`, and both `seal` and `seal --dry-run` print what was narrowed — with a note to review it when sealing a capsule you did not author.
- **Acceptance thresholds are no longer read from the capsule under test** (#30). `verify --against` took `verification_settings` from the *reference* capsule and handed them straight to the equivalence test, so a published capsule declaring `epsilon: 1.0` forced **every** comparison made against it to `VERIFIED` — TVD is bounded by 1. `tolerance_regime: calibration_drift` was a second lever on the same hole, swapping in a ~4× looser threshold. A third, `min_shots: 10^9`, forced `INCONCLUSIVE` on every comparison, letting a publisher call a result unfalsified because nothing could ever reject it.

  Thresholds now come from a `VerificationPolicy` owned by the verifier. A capsule's declaration is advisory: it may make verification **stricter** but never looser, and the effective value is reported alongside the verdict. New flags `--epsilon`, `--min-shots`, `--honor-calibration-drift`.
- **`verify --against` verifies integrity before comparing.** The statistical path ran no integrity check at all, so shot counts from a tampered capsule were compared as though they had been sealed. Both capsules must now pass `verify_integrity` first. This is a behaviour change: previously it would compare unsealed or draft capsules.

### Fixed
- **The README's first command works** (#19). `marqov-capsule init --name … --qubits 2` exited 2 — `init` takes a required positional `DIRECTORY` — so a new user's very first documented command failed. The CLI block now passes explicit paths throughout, which also makes it copy-pasteable as a unit with no `cd`. Also corrected: the CLI table said `init` scaffolds "in the current directory"; the install note claimed Python 3.9+ (it has been 3.10+ since #28); the quickstart printed a fabricated capsule ID (`e3b0c442…`, which is the SHA-256 of the empty string); and every relative link rendered as a dead link on the PyPI project page.
- **The payload layout is documented** (#19). The quickstart wrote `results.json` at the capsule root while `verify --against` required `payload/results.json`. That requirement left with the statistical path, so the README now states what is actually true: any file that is not `capsule.yaml` or `.checksums` is payload, and the `payload/` `source/` `environment/` split in the conformance fixtures is a convention rather than a rule.

- **Tamper-evidence: `verify` and `open` now check all three digest-chain layers** (#14). Only layer 1 (payload files vs `.checksums`) was implemented; `checksums_digest` was written at seal time and never recomputed, and the capsule ID was computed only to be printed. Editing a payload file and re-running `save_checksums` therefore passed verification with exit 0. `CapsuleVerifier.verify_integrity()` implements spec §6 in full and is what the CLI now calls.
- **`verify` no longer passes on injected files** (#17). `.checksums` pins a closed set, but `verify_checksums` computed the `extra` list and then ignored it, so a sealed capsule could carry arbitrary undeclared files. Injection also leaves `checksums_digest` and the capsule ID intact, so no other layer could catch it.
- **`capsule.yaml` and `.checksums` are excluded from checksumming by path, not basename.** Both the builder and verifier matched on filename anywhere in the tree, so `payload/capsule.yaml` was skipped at seal time *and* ignored by the extra-file scan — an injection vector invisible to every layer. Only the root-level files are excluded now.

### Added
- **`CapsuleVerifier.verify_integrity(capsule_dir, expected_id=None)`** — full spec §6 integrity check. Reports per-layer results (`checksums_digest_match`, `capsule_id`, `capsule_id_match`, `manifest_authenticated`) and a list of human-readable errors.
- **`verify --id` and `open --id`** — verify the manifest against a trusted capsule ID (layer 3). `capsule.yaml` is outside `.checksums` by design, so without a trusted ID the manifest is unauthenticated; `verify` now states this rather than reporting a bare pass. Combining `--id` with `--against` is rejected, since the statistical path checks no integrity layer.

### Changed
- **Minimum Python is now 3.10** (`requires-python = ">=3.10"`). Dropped Python 3.9, end-of-life since October 2025. CI tests 3.10–3.12.
- `verify` output header is now `Integrity verification:` (was `Checksum verification:`) and lists the recomputed capsule ID, injected files, and per-layer failures.

## [0.1.0] — 2026-07-22

Initial release.

### Added

- **`CapsuleBuilder`** — build, seal, and export capsule manifests. `seal()` runs the full sealing sequence: credential scan, `.checksums` generation, `checksums_digest` embedding, lifecycle transition, and manifest write. Returns the 64-character hex capsule ID.
- **`CapsuleValidator`** — validate `capsule.yaml` against the JSON Schema 2020-12 schema bundled in the package (`spec/v1/capsule-schema.json`). Supports sealed-state conditional validation.
- **`CapsuleVerifier`** — verify capsule integrity (checksum verification) and statistical equivalence between capsule pairs. Statistical verification uses bootstrap confidence intervals on total variation distance (TVD) with a normative seed (12345) and 9999 resamples. Requires `[verify]` extra (numpy + scipy).
- **`CapsuleRedactor`** — scan capsule directories for credential patterns (API tokens, secret keys, high-entropy strings) before sealing. Runs in `block` or `warn` mode.
- **CLI** — six subcommands: `init`, `seal`, `verify`, `inspect`, `open`, `validate`.
- **Spec v1** — open standard at `spec/v1/` (CC-BY-4.0): JSON Schema 2020-12 schema, RFC-style README, conformance fixtures (valid, invalid, secrets, derived, multi-task capsules).
- **RFC 8785 canonical JSON** — capsule IDs are SHA-256 of RFC 8785 (JCS) canonical JSON of `capsule.yaml`, ensuring deterministic identity across platforms and YAML emitters.
- **Merkle digest chain** — `.checksums` → `checksums_digest` → capsule ID forms a complete chain from payload files to manifest identity.
- **GitHub Actions CI** — three jobs: test matrix (Python 3.9/3.11/3.12), wheel smoke test (bundled schema byte-identity), base install (lazy numpy import guard).

### Fixed

- **`marqov-capsule validate`** now accepts a capsule directory (resolving `capsule.yaml` inside it), consistent with `init`/`seal`/`verify`/`inspect`/`open`. Passing a directory without a `capsule.yaml`, or any invalid path, produces a clean error and non-zero exit instead of an unhandled `IsADirectoryError` traceback. `CapsuleValidator.validate_file` guards the same case.

[0.1.0]: https://github.com/marqov-dev/marqov-capsule/releases/tag/v0.1.0
