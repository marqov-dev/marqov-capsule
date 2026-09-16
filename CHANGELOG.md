# Changelog

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
