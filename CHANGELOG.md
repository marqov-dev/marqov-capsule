# Changelog

## [Unreleased] — 0.1.2

Patch release from the Fable review of 0.1.1 (epic #91). Pure fixes: no
behaviour change for a conformant manifest, and every change ships through a
release pipeline that now runs the test suite before publishing.

### Fixed

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

### Changed

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
