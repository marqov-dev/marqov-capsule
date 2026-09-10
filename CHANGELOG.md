# Changelog

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
