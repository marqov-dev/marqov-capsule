# Marqov Capsule Specification v1

This document is the normative specification for the Marqov Capsule format. It defines the structure, digest scheme, lifecycle rules, and verification protocol for reproducible quantum experiment records.

**License:** CC-BY-4.0. Cite as: "Marqov Capsule Specification v1, Marqov, 2026."

---

## 1. Overview

A capsule is a directory-based, tamper-evident record of a quantum computation. It captures what was run, where it ran, and what it produced — in a form that is:

- **Reproducible**: another party can re-execute the same circuit and verify statistical equivalence of results.
- **Portable**: the manifest is self-describing; no proprietary tooling is required to read or re-target it.
- **Immutable once sealed**: the digest chain makes any post-seal modification detectable.

The format intentionally separates concerns: the manifest (`capsule.yaml`) describes the experiment; payload files hold the actual data; the `.checksums` file ties them together cryptographically.

---

## 2. Capsule structure

A capsule is a directory containing:

```
my-capsule/
├── capsule.yaml      # Manifest (required)
├── .checksums        # SHA-256 manifest of payload files (present after sealing)
└── <payload files>   # Any files: results.json, circuit.qasm, environment.txt, etc.
```

### 2.1 `capsule.yaml`

The manifest. A YAML file that conforms to `capsule-schema.json`. It describes the experiment, records task executions, and (after sealing) embeds the checksums digest.

### 2.2 `.checksums`

A newline-delimited UTF-8 text file written at seal time. Each line has the form:

```
sha256:<hex>  <relative-path>
```

— a `sha256:` prefix, 64 lowercase hex characters, exactly two ASCII spaces, then the payload file's capsule-relative path. One entry per payload file; `capsule.yaml` and `.checksums` itself are excluded. Lines are sorted in byte-wise ascending order of the encoded path and terminated by a single `LF`; a capsule with no payload files has a zero-length `.checksums`. Its SHA-256 becomes `checksums_digest` in the manifest. Because these bytes are hashed into the capsule ID, the exact byte grammar is normative — see §5, Layer 1.

### 2.3 Payload files

Any files the capsule author chooses to include: shot count distributions, circuits, environment snapshots, calibration data, etc. There is no required naming convention beyond what the manifest references. Implementers should use standard formats (JSON, OpenQASM, etc.) for interoperability.

---

## 3. Manifest fields

The full schema is in `capsule-schema.json` (JSON Schema 2020-12). Key fields:

### Identity

| Field | Type | Required | Notes |
|---|---|---|---|
| `version` | string | yes | Must be `"1.0.0"` |
| `name` | string | yes | Human-readable experiment name |
| `description` | string | no | Free text |
| `lifecycle_state` | string | yes | One of: `draft`, `runnable`, `sealed`, `archived` |

### Provenance

| Field | Type | Notes |
|---|---|---|
| `created_at` | string (ISO 8601) | When the capsule was created |
| `created_by` | string | Identity of the creator |
| `sealed_at` | string (ISO 8601) | Set automatically at seal time |
| `sealed_by` | string | Identity of the sealer |
| `derived_from` | string (versioned capsule ID) | Capsule ID of a parent capsule (`mqc:1:<hex>`), for provenance chains |

**Important:** timestamps must be stored as ISO 8601 strings (not numeric epoch) so that canonical JSON serialisation is deterministic across implementations (see §5).

### Hardware requirements

`requirements` (required when `lifecycle_state` is `runnable` or later):

| Field | Type | Required | Notes |
|---|---|---|---|
| `paradigm` | array of strings | yes | Values: `gate-based`, `analog`, `classical`, `annealing` |
| `max_qubit_count` | integer ≥ 1 | yes | |
| `gate_set` | array of strings | no | e.g. `["CX", "RZ", "SX"]` |

### Task executions

`task_executions` is an array of execution records. Each has:

| Field | Type | Required | Notes |
|---|---|---|---|
| `task_id` | string (UUID) | yes | Unique per execution |
| `status` | string | yes | `success`, `failed`, or `error` |
| `result_type` | string | yes | `probabilistic` or `deterministic` |
| `backend` | object | yes | See below |
| `verification_settings` | object | if probabilistic | See §6 |
| `start_time` / `end_time` | string (ISO 8601) | no | |
| `wall_time_seconds` | number | no | |
| `cost_usd` | number | no | |
| `job_id` | string | no | Provider-assigned job identifier |

`backend` fields:

| Field | Type | Required |
|---|---|---|
| `provider` | string | yes |
| `name` | string | yes |
| `shots` | integer | yes |

### Digest fields

| Field | Type | Notes |
|---|---|---|
| `checksums_digest` | string | `sha256:<hex>` — SHA-256 of the `.checksums` file bytes |
| `digests` | object | Arbitrary named digests, e.g. `results: sha256:<hex>` |

---

## 4. Lifecycle states

```
draft → runnable → sealed → archived
              ↑___________↑
              (runnable → sealed is the common path;
               draft → sealed is also permitted)
```

| State | Meaning | Manifest mutable? |
|---|---|---|
| `draft` | Being assembled | Yes |
| `runnable` | Ready to submit to a QPU; requirements locked | Requirements fields locked |
| `sealed` | Execution complete; digest chain embedded | No |
| `archived` | Long-term storage | No |

Permitted transitions: `draft → runnable`, `draft → sealed`, `runnable → sealed`, `sealed → archived`. No backward transitions. A compliant implementation must reject any attempt to modify a sealed or archived capsule.

---

## 5. Digest scheme

The digest chain has three layers:

### Layer 1: Payload file digests

For each payload file (excluding `capsule.yaml` and `.checksums`), `.checksums` contains one line:

```
sha256:<hex(SHA-256(file_bytes))>  <relative_path>
```

Because these bytes are hashed into `checksums_digest` and hence the capsule ID, the serialisation is byte-exact and normative:

- **Digest**: the literal prefix `sha256:` followed by exactly 64 lowercase hex characters (`[a-f0-9]{64}`; uppercase MUST NOT be used). A reader MUST reject a line whose algorithm prefix it does not recognise rather than guess. Future spec versions may register additional prefixes (e.g. `sha512:`) without invalidating existing IDs.
- **Separator**: exactly two ASCII space characters (`0x20 0x20`).
- **Path**: the file's capsule-relative path, using `/` as the separator on every platform. It MUST be relative and MUST NOT contain `..` or be absolute. Paths MUST be Unicode NFC-normalised before writing. The bytes `LF` (`%0A`), `CR` (`%0D`), `%` (`%25`), and `\` (`%5C`) — and only those — MUST be percent-encoded (RFC 3986, uppercase hex triplet); a space is left literal, since the fixed two-space separator keeps the line unambiguous.
- **Order**: lines are sorted in byte-wise ascending order of the encoded path (ordinal comparison, not locale- or codepoint-collated).
- **Framing**: UTF-8, no BOM; each line terminated by a single `LF`; the file ends with one trailing `LF`. A capsule with no payload files has a zero-length `.checksums` (whose SHA-256 is the empty-string digest `e3b0c442…b855`).
- **Uniqueness**: each path appears at most once.

### Layer 2: Checksums digest

```
checksums_digest = "sha256:" + hex(SHA-256(.checksums file bytes))
```

This value is embedded in `capsule.yaml` before the capsule ID is computed.

### Layer 3: Capsule ID

```
capsule_id = "mqc:1:" + hex(SHA-256(canonical_json(capsule.yaml)))
```

Canonical JSON follows RFC 8785 (JSON Canonicalization Scheme, JCS):
- Object keys sorted as arrays of UTF-16 code units, compared as unsigned integers (RFC 8785 §3.2.3); note that this order differs from Unicode code-point order for characters outside the Basic Multilingual Plane
- No insignificant whitespace
- Number serialisation per ECMAScript `Number::toString` (RFC 8785 §3.2.2.3)
- UTF-8 encoding

Because `capsule.yaml` is YAML, implementers parse it to a value, then serialise that value as JCS canonical JSON to compute the hash.

The capsule ID is **self-describing**: `mqc:<version>:<64-lowercase-hex>` (namespace : format version : hash) — e.g. `mqc:1:283f9421…`. The `version` names the *whole* derivation procedure (canonicalisation + `.checksums` grammar + hash), so any reader can tell from the ID alone which format produced it (cf. OCI `sha256:…`, Software Heritage `swh:1:…`, IPFS CIDv1). This document defines version `1`.

**Migration policy (normative).** A reader **MUST** parse the `<scheme>:<version>:` prefix and dispatch on the version, and **MUST** reject an unrecognised version rather than guess. A future format version (`mqc:2:…`) **does not invalidate existing IDs** — v1 IDs remain valid v1 identifiers permanently — and conformant tooling **retains prior-version derivations** as read-only paths, so it can recompute and verify any earlier-version capsule. `derived_from` therefore carries a full versioned ID.

RFC 8785 canonicalises an already-valid value; it does not validate. For two independent implementations to agree on the ID of a byte-identical `capsule.yaml`, a conformant implementation MUST additionally enforce, at parse time:

- **YAML typing**: resolve unquoted scalars using the JSON-aligned (YAML 1.2 Core) schema only — `true`/`false`/`null`, decimal integers, JSON-shaped floats. `yes`/`no`/`on`/`off`, hexadecimal/octal/underscored/sexagesimal numbers, and unquoted timestamps MUST read as strings, not be coerced. A language's default "safe" YAML loader is typically YAML 1.1 and MUST NOT be relied on unmodified.
- **Integers**: a leading-zero integer is decimal, never octal. Any integer with absolute value greater than 2⁵³−1 MUST be rejected, or authored as a string — outside that range JSON/JCS interoperability is not guaranteed (RFC 8785 App. D; RFC 8259 §6).
- **Floats**: `NaN` and `±Infinity` MUST cause an error (RFC 8785 §3.2.2.3); `-0` normalises to `0`.
- **Strings and keys**: Unicode NFC-normalised before hashing — JCS does not normalise (RFC 8785 §3.1).
- **Keys**: mapping keys MUST be unique (a duplicate key is an error, not last-wins) and MUST be strings; a non-string key is stringified by the same rule used for the corresponding value type.

**Key constraint:** All timestamp fields (`created_at`, `sealed_at`, `start_time`, `end_time`) must be stored as ISO 8601 strings, and serialised identically (ISO 8601, `T` separator) whether the ID is computed by the sealer or recomputed by a verifier from the written file. Numeric or space-separated timestamps would produce non-deterministic canonical JSON.

---

## 6. Verification

### Integrity verification

A conformant verifier must:

1. Recompute SHA-256 of each payload file and compare against `.checksums`.
2. Recompute SHA-256 of `.checksums` file bytes and compare against `checksums_digest` in the manifest.
3. Recompute the capsule ID from canonical JSON of the manifest and confirm it matches any stored or provided ID.

Any mismatch must be reported as a verification failure.

### Statistical equivalence (probabilistic results)

> **⚠ Under revision — do not implement as written.** The bootstrap CI
> procedure below is retired in the reference implementation: it was
> provably inconsistent for this functional (total variation distance is not
> Hadamard-differentiable at `p = q`, the null under test), and rejected
> byte-identical distributions as non-reproducible from roughly four qubits
> upward. `CapsuleVerifier.verify_statistical` now uses a closed-form
> one-sided upper confidence bound (Jensen + McDiarmid) instead — no
> resampling, no seed, and no `REJECTED` verdict (there is no valid
> construction that lower-bounds true TVD the way the upper bound works, so
> the honest verdict space is `VERIFIED` / `INCONCLUSIVE`). See
> `CapsuleVerifier.verify_statistical` and `_tvd_upper_confidence_bound` in
> `src/marqov_capsule/verifier.py`.
>
> This section's field names (`tvd_threshold`, `ci_level`, `n_resamples`) do
> not match the reference implementation's `verification_settings`
> (`epsilon`, `min_shots`, `tolerance_regime`, `epsilon_drift`) — that
> reconciliation, plus rewriting this section normatively, is tracked
> separately in [#20](https://github.com/marqov-dev/marqov-capsule/issues/20).
> The statistical design itself, its citations, and coverage measurements are
> in
> [`docs/research/2026-08-10-tvd-equivalence-testing.md`](../../docs/research/2026-08-10-tvd-equivalence-testing.md).
> Tracked in [#15](https://github.com/marqov-dev/marqov-capsule/issues/15).
>
> The procedure below is retained only as a record of what v1 originally
> specified, pending #20.

QPU results are shot distributions. Two capsules are statistically equivalent if their distributions are close within a confidence interval. The normative procedure:

1. **Metric**: Total variation distance (TVD) between the two shot distributions.
   ```
   TVD(p, q) = 0.5 * sum(|p_i - q_i|) over all outcomes i
   ```
2. **Bootstrap CI**: 9999 resamples, 95% confidence level, seed **12345** (fixed by this spec for reproducibility).
3. **Verdict**:
   - `VERIFIED`: CI upper bound ≤ threshold specified in `verification_settings`
   - `REJECTED`: CI lower bound > threshold
   - `INCONCLUSIVE`: CI straddles the threshold

`verification_settings` in the task execution record:

| Field | Type | Notes |
|---|---|---|
| `tvd_threshold` | number | Maximum acceptable TVD |
| `ci_level` | number | Confidence level (default 0.95) |
| `n_resamples` | integer | Resamples (default 9999) |

The seed (12345) is fixed by this spec and must not be changed by conformant implementations. This ensures the same capsule pair always yields the same verdict regardless of which implementation performs the check.

---

## 7. Schema

The JSON Schema for `capsule.yaml` is in `capsule-schema.json` in this directory. It uses JSON Schema 2020-12 (`$schema: https://json-schema.org/draft/2020-12/schema`).

The schema is also bundled into the `marqov-capsule` Python package and used for runtime validation. Third-party implementations should validate against the schema before accepting a capsule as conformant.

Schema `$id`: `https://marqov.ai/schemas/capsule/v1/capsule-schema.json`

---

## 8. Conformance

A conformant capsule implementation must:

- Produce `capsule.yaml` that validates against `capsule-schema.json`.
- Compute `.checksums` and `checksums_digest` using the scheme in §5, and serialise `.checksums` using the byte-exact grammar in §5, Layer 1 (two-space separator, lowercase hex, NFC and percent-encoded paths, byte-wise sort, LF framing).
- Refuse to seal a capsule that contains credentials (API keys, tokens, high-entropy secrets). See the reference implementation's `CapsuleRedactor` for the normative pattern list.
- Compute capsule IDs using JCS canonical JSON (RFC 8785), enforcing the parse-time canonicalisation constraints in §5, Layer 3 (JSON-aligned YAML typing, the 2⁵³ integer bound, NFC, unique string keys) before hashing.
- Use seed 12345 for bootstrap TVD CIs.

---

## 9. License

This specification is licensed under [CC-BY-4.0](../../LICENSE-SPEC).

Cite as: **Marqov Capsule Specification v1**, Marqov, 2026. `https://github.com/marqov-dev/marqov-capsule/tree/main/spec/v1`
