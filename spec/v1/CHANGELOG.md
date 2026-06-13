# Capsule Specification Changelog

Version history for the Marqov Capsule format specification.

---

## v1.0.0 — 2026-06-13

Initial specification release.

### Schema

- `lifecycle_state` enum: `draft`, `runnable`, `sealed`, `archived`
- `requirements.paradigm` typed as array (not string) — supports multi-paradigm capsules (e.g. gate-based + analog)
- `requirements.max_qubit_count` typed as non-negative integer
- Sealed-state conditional: when `lifecycle_state == "sealed"`, `checksums_digest`, `sealed_at`, and `sealed_by` are required
- Probabilistic task conditional: when `result_type == "probabilistic"`, `verification_settings` is required in the task execution

### Digest scheme

- `.checksums` format: `<sha256hex>  <relative/path>`, one line per file, lexicographic order, excludes `capsule.yaml` and `.checksums` itself
- `checksums_digest`: `sha256:` prefix + SHA-256 of `.checksums` file bytes
- Capsule ID: SHA-256 of RFC 8785 (JCS) canonical JSON of `capsule.yaml`; timestamps must be stored as strings to ensure deterministic canonical form

### Credential policy

- Credential scanning is normative (§4): no API tokens, secret keys, or high-entropy strings may appear in sealed capsule files
- `# capsule:allow` annotation suppresses a line from credential pattern matching

### Verification protocol

- Statistical verification: bootstrap CI on total variation distance (TVD), 9999 resamples, normative seed 12345, 95% CI
- Verdicts: `VERIFIED` (CI upper bound ≤ ε), `REJECTED` (CI lower bound > ε), `INCONCLUSIVE` (otherwise or insufficient shots)
- Deterministic verification: exact digest comparison
