# Changelog

All notable changes to marqov-capsule are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.1.0] — 2026-07-21

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
