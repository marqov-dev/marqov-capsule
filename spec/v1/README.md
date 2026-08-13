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

A newline-delimited text file written at seal time. Each line has the form:

```
sha256:<hex>  <relative-path>
```

One entry per payload file. `capsule.yaml` and `.checksums` itself are excluded. The file is sorted lexicographically by path. Its SHA-256 hash becomes `checksums_digest` in the manifest.

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
| `derived_from` | string (64 hex) | Capsule ID of a parent capsule, for provenance chains |

**Important:** timestamps must be stored as ISO 8601 strings (not numeric epoch) so that canonical JSON serialisation is deterministic across implementations (see §5).

### Hardware requirements

`requirements` (required when `lifecycle_state` is `runnable` or later):

| Field | Type | Required | Notes |
|---|---|---|---|
| `paradigm` | array of strings | yes | Values: `gate-based`, `analog`, `classical` |
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

For each payload file (excluding `capsule.yaml` and `.checksums`):

```
sha256:<hex(SHA-256(file_bytes))>  <relative_path>
```

Lines are sorted lexicographically by path. Written to `.checksums`.

### Layer 2: Checksums digest

```
checksums_digest = "sha256:" + hex(SHA-256(.checksums file bytes))
```

This value is embedded in `capsule.yaml` before the capsule ID is computed.

### Layer 3: Capsule ID

```
capsule_id = hex(SHA-256(canonical_json(capsule.yaml)))
```

Canonical JSON follows RFC 8785 (JSON Canonicalization Scheme, JCS):
- Keys sorted lexicographically (Unicode code point order)
- No insignificant whitespace
- IEEE 754 number serialisation
- UTF-8 encoding

Because `capsule.yaml` is YAML, implementers must parse it to a dict, then serialise that dict as JCS canonical JSON to compute the ID. The capsule ID is a 64-character lowercase hex string.

**Key constraint:** All timestamp fields (`created_at`, `sealed_at`, `start_time`, `end_time`) must be stored as ISO 8601 strings. Numeric timestamps would produce non-deterministic canonical JSON across implementations with different float precision.

---

## 6. Verification

### Integrity verification

A conformant verifier must:

1. Recompute SHA-256 of each payload file and compare against `.checksums`.
2. Recompute SHA-256 of `.checksums` file bytes and compare against `checksums_digest` in the manifest.
3. Recompute the capsule ID from canonical JSON of the manifest and confirm it matches any stored or provided ID.

Any mismatch must be reported as a verification failure.

### Statistical equivalence (probabilistic results)

> **⚠ Under revision — do not implement.** The procedure below is miscalibrated
> and is being replaced. The plug-in TVD estimator carries a noise floor of
> `√((K−1)/πn)`, and the percentile bootstrap prescribed here is displaced upward
> by it rather than corrected downward, so a distribution compared **against
> itself** is rejected from roughly four qubits upward. The bootstrap is also
> provably inconsistent for this functional: total variation distance is not
> Hadamard-differentiable at `p = q`, which is exactly the null being tested.
>
> The reference implementation does **not** ship this in v0.1.0. Independent
> implementers should not build against it until it is revised. Analysis,
> measurements, and four evaluated replacements:
> [`docs/research/2026-08-10-tvd-equivalence-testing.md`](../../docs/research/2026-08-10-tvd-equivalence-testing.md).
> Tracked in [#15](https://github.com/marqov-dev/marqov-capsule/issues/15).
>
> Retained here only as a record of what v1 originally specified.

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
- Compute `.checksums` and `checksums_digest` using the scheme in §5.
- Refuse to seal a capsule that contains credentials (API keys, tokens, high-entropy secrets). See the reference implementation's `CapsuleRedactor` for the normative pattern list.
- Compute capsule IDs using JCS canonical JSON (RFC 8785).
- Use seed 12345 for bootstrap TVD CIs.

---

## 9. License

This specification is licensed under [CC-BY-4.0](../../LICENSE-SPEC).

Cite as: **Marqov Capsule Specification v1**, Marqov, 2026. `https://github.com/marqov-dev/marqov-capsule/tree/main/spec/v1`
