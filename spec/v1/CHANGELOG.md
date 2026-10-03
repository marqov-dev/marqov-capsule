# Capsule Specification Changelog

Version history for the Marqov Capsule format specification.

---

## Unreleased

Clarifications to the digest scheme and manifest canonicalization ahead of the first tag, making the format byte-reproducible across independent implementations.

### Verification and conformance

- Added independent Node checks of the published YAML/digest corpus and fixed path-encoding vectors; no digest-format change.

- Replaced the retired bootstrap procedure in §6 with the implemented one-sided TVD upper bound, `VERIFIED` / `INCONCLUSIVE` decisions, and verifier-owned policy resolution. No statistical CLI was added.
- Published fixed golden outputs alongside the conformance corpus, with reference and independent standard-library checks.

### Schema

- `requirements.max_qubit_count` minimum is now `0`, matching §3 ("Zero supports classical-only workloads"); the schema previously required `1` and rejected the classical capsules the prose allows.
- The sealed-field requirement (`requirements`, `checksums_digest`, `sealed_at`, `sealed_by`) now applies to `archived` manifests as well as `sealed` ones; an archived manifest previously escaped it.
- Added the optional `seal_notes` string, which the reference implementation has always been able to write.
- Added `annealing` to the `requirements.paradigm` enum (now `gate-based`, `analog`, `classical`, `annealing`) so quantum-annealing workloads (e.g. D-Wave) can produce schema-valid capsules. The CLI already advertised `annealing`; this resolves the mismatch by extending the schema (the value the product needs) rather than dropping it from the CLI.

### Digest scheme

- **`.checksums` line format is `sha256:<hex>  <relative/path>`**, with the `sha256:` algorithm prefix — superseding the v1.0.0 entry's prefix-less `<sha256hex>  <path>`, which disagreed with §2.2/§5 of the spec. The reference implementation previously emitted a YAML mapping; it now emits this line format.
- Pinned the byte-exact `.checksums` grammar (§5, Layer 1): two-space separator, lowercase hex, `/` path separator, Unicode NFC, narrow percent-encoding of `LF`/`CR`/`%`/`\`, byte-wise path sort, LF framing with a trailing newline, and a zero-length file for an empty payload.
- **Capsule IDs re-base.** Because `checksums_digest` is the SHA-256 of the `.checksums` bytes, this format change alters every capsule ID. Done before the first public tag, while no ID is published; capsules sealed under the old YAML-mapping form still verify, as the verifier reads both.
- **Capsule ID is now self-describing: `mqc:1:<hex>`** (namespace : format-version : hash), not a bare 64-hex string. A reader MUST dispatch on the version and reject unrecognised versions; a future format change (`mqc:2:…`) does not invalidate v1 IDs, and tools retain prior-version derivations (§5, Layer 3). `derived_from` carries the versioned form and its schema pattern widened to `^mqc:[0-9]+:[0-9a-f]{64}$`.

### Canonicalization

- Pinned parse-time conformance rules (§5, Layer 3): JSON-aligned (YAML 1.2 Core) scalar typing, decimal-only integers bounded to 2⁵³−1, `NaN`/`Infinity` rejected, `-0`→`0`, NFC on string values and keys, and unique string mapping keys.
- Corrected the key-ordering description to UTF-16 code units per RFC 8785 §3.2.3 (was "code point order").

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

  > **Superseded.** The bootstrap CI above was provably miscalibrated and is retired in the reference implementation, along with the affirmative `REJECTED` verdict. See the current procedure in `spec/v1/README.md` §6.
