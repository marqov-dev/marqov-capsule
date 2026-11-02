# Capsule Specification Changelog

Version history for the Marqov Capsule format specification.

---

## Unreleased

Unreleased clarifications and interoperability corrections to manifest parsing and the digest scheme.

### Unknown keys

- §3 now states the existing v1 behaviour: undeclared keys are legal and covered by the capsule ID, `extensions` is the place for implementation-specific data, and writers should warn about undeclared keys before sealing (#112). The schema is unchanged.

### Independent pre-0.2.2 review follow-up

- Explicit `!!null` uses the null grammar instead of discarding arbitrary text.
  All typed scalar constructors require full spelling matches, preventing a
  decoded trailing newline from turning `!!bool "true\n"` into false.
- Reject duplicate version directives and duplicate tag handles in Node, and
  under-indented quoted continuations in Python. Valid indented continuations,
  root flow collections, null variants and distinct tag handles remain covered.
- Add 39 shared accept/reject vectors with stated canonical values, plus
  load-phase and writer round-trip tests. The writer helper now applies the
  same NFC/date/key conversion as canonicalization; this matches the existing
  builder path and refuses key collisions.

These are additional raw spelling restrictions before 0.2.2. Existing ordinary
IDs remain unchanged; do not silently re-seal old stored records to migrate them.
The manifest JSON Schema is unchanged because no JSON value property changes.

### Remaining YAML profile disagreements (#119)

- Normalize CRLF and CR-only manifest line breaks to LF in both readers.
- Reject raw non-printables and NEL/LS/PS consistently, including within quoted
  or block content. The Python writer double-quotes and escapes these scalar
  values, preserving their canonical identity and round-trip semantics.
- Refuse syntax/plain-scalar tabs in Node while retaining quoted/block/comment
  tabs and explicit scalar escapes supported by both readers.
- Reject unknown directives and unsupported YAML versions in Python. Pin
  supported 1.1/1.2 version declarations to the same JSON-aligned typing and
  retain core-tag handles.
- Reject surrogate escapes at parse time in both readers, including paired
  escapes; literal supplementary characters and full scalar escapes remain
  supported. Escaped literal backslash text is distinguished from an escape.
- Add 52 accept/reject vectors with independently stated canonical values.
  Extract the Node manifest reader into an internal module for differential
  probing; it remains a corpus implementation, not a production verifier.

These changes restrict ambiguous YAML spellings and make formerly divergent
CR-only spellings interoperable. No new content-ID scheme, manifest version or
JSON Schema property is introduced; existing ordinary records retain their IDs.
Manifests using the rejected spellings must be reviewed before re-encoding;
never silently re-seal stored records or claim that a new ID authenticates an
old export. Strict raw-text rejection can affect older hand-authored manifests
and older writer output containing literal Unicode line separators.

### Parse-time rules (§5)

Clarifications: each of these was a case the earlier text left open, and on which the Python reference and the independent Node checker gave different answers — so a manifest using one had no single ID. Ordinary manifest identities remain unchanged. The writer now escapes raw NEL/LS/PS characters so their scalar values remain readable under the common profile.

- Mapping keys that are not strings MUST be rejected. The earlier text said both that keys "MUST be strings" and that a non-string key "is stringified"; the second sentence is removed.
- `capsule.yaml` MUST be UTF-8, and an unpaired surrogate MUST be rejected.
- The file MUST be exactly one document, and that document MUST be a mapping.
- Alias nodes MUST be rejected; `<<` is an ordinary key.
- Explicit tags outside the core set MUST be rejected, and explicitly tagged `!!int` / `!!float` / `!!bool` scalars are held to the implicit spellings.
- 25 vectors added to `golden/canonical-edge-cases.json` (23 reject, 2 accept), including `bytes_hex` vectors for files that are not UTF-8 text.

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
