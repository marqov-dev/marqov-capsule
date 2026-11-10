# Changelog

## [Unreleased]

### Fixed

- On Python 3.14, `verify_checksums` reported a `.checksums` entry whose name
  the OS refuses (a component past NAME_MAX) as `missing` instead of `invalid`.
  The verdict was already `fail`; the entry is now classified as on 3.10–3.13.

### Changed

- CI and the package classifiers now cover Python 3.13 and 3.14.

## [0.2.3] — 2026-11-05

### Added

- `seal` and `seal --dry-run` name manifest keys the v1 schema does not declare,
  on stderr and as `unknown_keys` in `--json` output. They stay legal, so sealing
  still succeeds; `CapsuleValidator.unknown_keys()` exposes the check (#112).

### Changed

- `init` records `created_at` in the draft manifest (#112).

### Fixed

- `seal --dry-run` and `CapsuleRedactor.scan()` no longer raise on a
  `capsule.yaml` that does not parse. The scan keeps its findings from the
  literal text, and `--dry-run` stays at exit 0 but names the problem instead of
  saying "no issues found", for an empty, non-mapping or non-UTF-8 manifest too;
  `--json` gains `manifest_error` and reports `status: warnings`.
- Manifest parse errors from `seal`, `inspect`, `pack` and `validate` give the
  line and column, or only the error type, rather than quoting the source, which
  could print a credential whole. Schema errors from `validate`, and from `seal`
  on the same path, replace the rejected value with `<value>`.

### Documentation

- The repository is prepared for public release: open contribution guidance,
  `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue templates, a root `LICENSE`, and
  Source, Issues and Changelog project URLs (#148).
- The README lists known limitations (#151) and how many shots a `VERIFIED`
  verdict needs (#85).

## [0.2.2] — 2026-10-21

### Added

- A `lint` CI job (ruff format and lint, mypy on `src/`, a typed CLI package)
  and a changed-lines coverage check on pull requests; the repository is
  formatted to a 100-character line length (#139). A local replica of the CI
  workflow, `tools/local_ci.sh`, for qualifying changes when hosted CI is
  unavailable (#142).
- Twenty-eight tests from a mutation-testing pass over `_canonical.py`,
  `verifier.py` and `redactor.py`: seventeen pin guards that could previously
  be removed with the suite still green (checksum verdicts for missing or
  undecodable `.checksums`, non-string and NFC-duplicate legacy keys, the
  `# capsule:allow` scope, notebook and directory scans continuing past
  malformed or skipped entries, `verify_deterministic` key-order
  independence), and eleven pin the `verify_checksums` result contract (#140).
  The mutation baseline and per-function scores are in
  `docs/MUTATION-REPORT-2026-10-15.md`.

### Fixed

- Address independent pre-0.2.2 review: reject invalid explicit null spellings
  and trailing-newline bool/int/float spellings, duplicate YAML/TAG directives,
  and under-indented quoted continuations consistently across readers. Add 39
  shared vectors and load-phase/writer regressions. The direct writer helper
  now applies the same canonical-ready conversion as builder serialization,
  rejecting collisions rather than emitting unreadable typed keys.

- Align Python and the independent Node corpus reader on manifest line breaks,
  syntax tabs, directives, raw non-printables and Unicode surrogate escapes
  (#119). Add 52 shared accept/reject vectors and writer round-trip checks.
  NEL/LS/PS scalar values are now emitted as escapes. Older manifests using
  newly rejected raw spellings need explicit review; no stored record is
  rewritten and ordinary content IDs remain unchanged. See spec §5 and its
  changelog for the supported common profile and compatibility limits.

## [0.2.1] — 2026-10-07

### Fixed

- Scan the complete prospective sealed manifest, including `sealed_by`,
  `seal_notes` and `derived_from`, before writing checksums or changing builder
  state. Blocked scans preserve the existing draft and checksum file;
  `warn_only` findings include secrets in seal-time metadata.
- Reject invalid count samples at the statistical Python API boundary before
  calculating totals or issuing a verdict. Counts must be non-negative integers,
  excluding booleans, with string outcome labels. Empty and zero-shot samples
  remain `INCONCLUSIVE`.
- Deep-copy nested builder inputs and exported dictionaries so caller mutations
  cannot change a sealed record. Refuse to write a manifest changed after sealing.
- Refuse payload filenames with unsupported ASCII control characters before
  writing checksums or sealing. The existing percent encoding of LF and CR
  remains supported.
- Correct the README to document the implemented statistical `compare` CLI.
- Keep the root manifest in credential-scan scope even when `.capsuleignore`
  patterns match it. Scan parsed manifest values with their key context so
  YAML list layout and line wrapping cannot hide known credential patterns.
- Accept NumPy and other `numbers.Integral` count scalars by normalizing them
  to Python integers, still rejecting booleans. Cap each sample's total shots
  at 2^53−1 and report invalid/oversized samples as clean CLI errors.
- Compare the sealed manifest's serialized snapshot rather than Python value
  equality, which treats `True`, `1` and `1.0` as equal.
- Write checksum files atomically. If the manifest write fails during one-call
  sealing, restore the draft and its previous checksums so sealing can be retried.
  The CLI reports I/O errors without a traceback.
- Refuse symlinks, non-regular files and checksum paths longer than 4,096 encoded
  UTF-8 bytes before sealing, matching verifier limits.

## [0.2.0] — 2026-10-06

From the Fable review of 0.1.1 (epic #91). The fixes carry no behaviour change
for a conformant manifest. The entries under "Changed" marked in bold refuse an
input, or report one differently, that 0.1.x accepted — hence the minor
version. Every change ships through a release pipeline that now runs the test
suite before publishing.

### Changed

- **A manifest key that is not a string is a parse error.** `1:`, `true:` and
  `~:` used to load and be stringified; an unquoted `00:` silently became
  `"0"`. Quote the key. In-memory dicts passed to the builder are unaffected.
  (#119)
- `compute_capsule_id` raises `ValueError` for anything that is not a mapping;
  an empty or list-shaped document no longer has an ID. (#119)

- **Sealing validates the manifest against the schema.** `seal` / `seal_capsule`
  raise `CapsuleValidationError` (a `ValueError` carrying the validator's
  `errors`) before anything is scanned or written, as spec §8 requires. The
  CLI lists each error and exits 1. Escape hatch: `validate=False` /
  `seal --no-validate`. `init` rejects an unknown `--paradigm` and a negative
  `--qubits` as usage errors. (#111)
- **Sealed and archived capsules are immutable.** `add_task_execution`,
  `add_result_digest`, `save_capsule` and `save_checksums` raise
  `CapsuleStateError` on a manifest loaded in a terminal state (spec §4).
  `CapsuleBuilder.derive()` starts a new draft from a sealed parent with
  `derived_from` set. (#107)
- **`.checksums` is read by its normative grammar.** A missing final LF, blank
  line, BOM, CR, unrecognised algorithm prefix, uppercase or short digest, or
  wrong separator is a grammar error naming the line, not a payload mismatch.
  A lone newline is no longer an empty payload. Results carry `format`
  (`normative` or `legacy-yaml`); the legacy YAML mapping stays readable
  because marqov-platform's vendored builder still writes it. (#108)
- **`--id` is parsed.** `verify_integrity` reports a malformed expected ID, or
  one of an unsupported format version, as such instead of as a mismatch; the
  `verify` and `open` commands treat a malformed `--id` as a usage error
  (exit 2). (#114)
- **`pack` refuses to replace an existing archive** (`FileExistsError`) unless
  `overwrite=True` / `--force`, and refuses a directory whose manifest is not
  `sealed` or `archived`. (#106)
- **Archives are size-bounded.** `unpack_capsule` refuses an archive that
  inflates past `max_bytes` (default 1 GiB, `None` to disable) before writing
  anything; a `.checksums` member over 16 MiB is refused.
- **Binary files are not credential-scanned.** A file with a NUL byte in its
  first 8 KB is skipped and listed under `skipped_binary`, which `seal`
  prints. Notebook findings carry `cell` and `location`, and messages read
  `n.ipynb:cell 1:line 2`. (#98, #100)
- Schema: `max_qubit_count` minimum is 0; `archived` manifests need the sealed
  fields; `seal_notes` is declared. (#112, in part)
- `CapsuleVerifier(schema_path=...)` is deprecated and ignored; it never
  validated anything. (#102)
- The version is declared once, in `marqov_capsule/__init__.py`;
  `pyproject.toml` reads it. (#104)
- Release workflow runs the test suite before `build`, so a `v*` tag cannot
  publish untested code; both workflows declare read-only token permissions.
  (#115)
- Test suite: module-level `importorskip` replaced by fixtures so a base
  install runs every numpy-independent test (collection count is identical
  with and without the `[dev]` extra); a self-check fails on the pattern.
  Six previously untested guards are pinned by mutation-proven tests; four
  tests that passed for the wrong reason are fixed. `hypothesis` added to the
  `[dev]` extra for a loader tripwire. (#116, #117, #118)
- Golden vector `below-min-shots-asymmetric` added to
  `spec/v1/conformance/golden/statistical-cases.json` (30 Node vectors).

### Fixed

- Node conformance checker: an explicit finite `!!float` is no longer
  rejected; input is decoded as strict UTF-8; unpaired surrogates, non-core
  tags, non-decimal `!!int` and non-mapping documents are rejected. It now
  checks 55 vectors. (#120)
- CONTRIBUTING cites the right spec sections. (#109)

- **Sealed IDs are reproducible from disk.** The manifest writer quoted for
  YAML 1.1 while the loader typed with the YAML 1.2 / JSON profile, so an
  exponent-shaped string (`1e5`, `1e-3`) was written bare and read back as a
  float: the ID the sealer published could not be recomputed from the file,
  and `init --name 1e-3` silently coerced the name. Manifests are now written
  with a dumper that quotes for the union of both profiles, and `seal()`
  returns the ID recomputed from the bytes it wrote. (#92)
- **A failed seal leaves the draft untouched.** `capsule.yaml` is serialised
  fully before anything is written and replaced atomically; the draft is no
  longer rewritten before the credential scan, so a blocked seal keeps a
  hand-edited draft byte for byte. (#121)
- **Manifest loader fails closed.** Aliases are rejected (a 350-byte
  "billion laughs" manifest stalled `verify`/`validate`/`inspect`/`pack` for
  minutes), nesting is capped, explicit tags outside the YAML core set are
  rejected, tagged `!!int`/`!!float`/`!!bool` scalars are held to the 1.2
  grammar, and any residual exception is re-raised as a `YAMLError` so every
  caller reports a verdict instead of a traceback. (#110, #122, #93)
- `verify_checksums` no longer raises on a `.checksums` path containing a
  control character or exceeding 4096 bytes. (#123)
- `payload_digest(archive)` reads the root `.checksums`, not the first member
  of that name in byte order, so `pack` reports the right digest when a payload
  subdirectory sorting before `.` carries its own `.checksums`. (#94)
- Archive layer: a truncated gzip stream and a `.checksums` member that is a
  link or directory raise `ValueError` instead of `EOFError`, `KeyError` or
  `RecursionError`; `unpack`/`pack` exit 1 with a message in text and `--json`
  modes. (#124, #96)
- `seal --warn-only` prints every finding it sealed past (and Tier B entropy
  warnings are printed in the default mode too); `--json` carries `findings`.
  (#105)
- A malformed notebook (`cells`/`outputs` not a list) scans to nothing instead
  of raising out of `seal`. (#125)
- Two redactor rules were quadratic (PEM block, SDK constructor): 1 MB of
  pathological input now scans in well under a second. (#126)
- `seal`, `inspect` and `pack` share one manifest loader and exit 1 cleanly on
  an empty, unparsable or non-mapping `capsule.yaml`; a null
  `task_executions:` reads as empty and a wrongly typed container is an
  error, not a traceback. (#95)
- `open . --dest X` extracts to `X/<real directory name>`. (#97)
- `compare` rejects out-of-range `--alpha`, `--epsilon` and `--min-shots` as
  usage errors (exit 2); `VerificationPolicy` validates its own ranges. (#99)
- `init` prints the directory it was given in the next-step hint and lists
  `classical` among the paradigms; README gains the `compare` row. (#109)
- Capsule-relative paths use `/` on every OS in the verifier's closed-set walk
  and the redactor, and `.checksums` is written as bytes, so Windows neither
  reports nested payload files as extra nor writes CRLF framing; `compare`
  reads counts as UTF-8 and reports a file that is not. CI gains a macOS leg
  and a non-blocking Windows leg. (#113, #103, #115)

## [0.1.1] — 2026-09-16

Patch release. Fixes a crash on a routine comparison workflow and adds the
first user-facing access to count-equivalence testing.

### Fixed

- `verify_statistical` raised `ValueError` whenever the two arms had different
  shot counts, so comparing a re-run at a different shot count failed outright.
  The chi-squared diagnostic applied its continuity correction before rescaling
  the candidate arm, leaving the two totals unequal. It is now scaled before
  correction, and guarded so a diagnostic — which never affects a verdict —
  can no longer prevent one being returned.

### Added

- `marqov-capsule compare REF NEW` tests whether two count samples are
  equivalent within a tolerance, using the one-sided upper confidence bound.
  Exits 0 for `VERIFIED`, 3 for `INCONCLUSIVE`, 1 on error. `INCONCLUSIVE`
  reports which condition produced it, distinguishing a sample-size limit from
  evidence of a difference. Requires NumPy and SciPy; a base install reports
  that rather than failing obscurely.
- Golden vectors for specification section 6 at
  `spec/v1/conformance/golden/statistical-cases.json`, with expected values
  derived from the normative formula rather than from this implementation.
  Conformant implementations are now required to match them. The Node
  conformance checker covers them independently, 18 vectors to 29.

### Notes

- `compare` evaluates the result files it is given; it does not verify the
  capsules they came from. Use `verify` for integrity.
- Comparing capsules directly is still unavailable: the specification does not
  yet state where results live inside a capsule.

## [0.1.0] — 2026-09-10

First public release of the capsule format and Python tooling.

### Capabilities

- Build, validate and seal experiment records with a versioned `mqc:1:` content ID.
- Verify the complete digest chain against a separately supplied trusted ID.
- Create deterministic archives; inspect, verify and extract recorded experiments.
- Validate manifests against the bundled JSON Schema 2020-12.
- Scan for credential patterns before sealing.
- Provide deterministic-result and statistical count-comparison Python APIs.
- Include specification, conformance vectors and local SDK demonstration scripts
  in the source distribution.

### Validation and delivery

- Reject invalid UUIDs/timestamps, non-JSON manifest values, unsafe integers,
  cycles, duplicate keys and Unicode normalization collisions.
- Enforce closed checksum sets and canonical encoded paths. Reject symlinked
  metadata, nonregular payloads and unreadable verification inputs.
- Reject ambiguous archive layouts and duplicate or Unicode-colliding members;
  require fresh destination capsule directories for copying and extraction.
- Gate release uploads on artifact inventories, metadata checks and isolated
  installed-wheel acceptance. Source archives include only selected source paths.
- Supply an offline demonstration kit builder in repository checkouts.

### Compatibility and limits

- The pre-release `verify_capsule`, `compare_capsules` and
  `check_calibration_drift` APIs are retired. They raise explicit migration
  errors. Supported file-integrity and explicit result-comparison APIs remain.
- Statistical comparison uses a one-sided bound and returns `VERIFIED` or
  `INCONCLUSIVE`; no statistical CLI or calibration-verdict API is provided.
- Legacy YAML checksum maps remain readable, but checksum success alone does
  not establish full integrity or compatibility with the current schema.
- Capsules carry no signatures. A trusted content ID must arrive independently
  of the artifact. Integrity does not establish QPU provenance or scientific
  correctness. Environment snapshots are author-supplied.
