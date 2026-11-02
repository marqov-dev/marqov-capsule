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

Environment capture is explicit in this release: authors provide environment
snapshots as payload files; sealing does not inspect the host or automatically
create an environment lock. The SDK example records versions but does not claim
a fully restorable environment.

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

The manifest version is pinned to `1.0.0` in this release. A validator does not
assume that future minor versions are compatible: accepting another version
requires an explicitly supported schema. This manifest version is distinct from
the `mqc:1:` digest-procedure version.

### Provenance

| Field | Type | Notes |
|---|---|---|
| `created_at` | string (ISO 8601) | When the capsule was created |
| `created_by` | string | Identity of the creator |
| `sealed_at` | string (ISO 8601) | Set automatically at seal time |
| `sealed_by` | string | Identity of the sealer |
| `seal_notes` | string | Free-text note recorded by the sealer |
| `derived_from` | string (versioned capsule ID) | Capsule ID of a parent capsule (`mqc:1:<hex>`), for provenance chains |

**Important:** timestamps must be stored as ISO 8601 strings (not numeric epoch) so that canonical JSON serialisation is deterministic across implementations (see §5).

### Hardware requirements

`requirements` (required when `lifecycle_state` is `runnable` or later):

| Field | Type | Required | Notes |
|---|---|---|---|
| `paradigm` | array of strings | yes | Values: `gate-based`, `analog`, `classical`, `annealing` |
| `max_qubit_count` | integer ≥ 0 | yes | Zero supports classical-only workloads |
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

### Extensions and unknown keys

`extensions` is an object for implementation-specific data. Its contents are not
interpreted by this specification.

A key this specification does not declare is not an error in v1, at the manifest
root or in a task execution, `backend` or `verification_settings`. Such a key is
part of the manifest, so it is covered by the capsule ID, but it carries no
defined meaning and verifiers ignore it. New data SHOULD go under `extensions`.
Writers SHOULD warn about undeclared keys before sealing, because a misspelled
optional field such as `derived_From` validates and records nothing under the
name readers look for.

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

Other ASCII control characters (U+0000–U+001F except the encoded LF and CR,
and U+007F) are unsupported in payload paths. Writers must refuse these paths
before sealing; readers reject their raw occurrence in checksum entries.
The encoded UTF-8 path must not exceed 4,096 bytes. The reference writer
refuses symlinks and non-regular filesystem entries rather than producing a
record its verifier would reject.

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
- **Keys**: mapping keys MUST be unique (a duplicate key is an error, not last-wins) and MUST be strings. A key the typing rule above resolves to anything else (`1:`, `true:`, `~:`, `1.5:`) MUST be rejected; authors quote it. (An unquoted `00:` is the integer 0, so stringifying keys would silently turn the outcome label `00` into `0`.)
- **Encoding**: `capsule.yaml` MUST be UTF-8. A file that does not decode as UTF-8 MUST be rejected, not decoded with replacement characters. A string or key containing an unpaired surrogate code point — reachable through a `"\uD800"`-style escape — MUST be rejected.
- **Document**: the file MUST contain exactly one YAML document, and that document MUST be a mapping. An empty file, a comment-only file, a sequence, a bare scalar and a multi-document stream have no capsule ID.
- **Aliases**: an alias node (`*name`) MUST be rejected. Aliases have no JSON representation, and a small aliased document can expand to an arbitrarily large value. A `<<` key is an ordinary string key; it is never interpreted as a merge.
- **Explicit tags**: only the core tags `!!str`, `!!int`, `!!float`, `!!bool`, `!!null`, `!!map` and `!!seq` may appear. Any other tag — `!!timestamp`, `!!binary`, `!!set`, `!!omap`, `!!pairs`, or a local `!tag` — MUST be rejected. A scalar explicitly tagged `!!int`, `!!float`, `!!bool` or `!!null` MUST use a complete spelling the typing rule above accepts for that type; `!!float` also accepts decimal integer spellings such as `!!float 1`. Thus `!!bool yes`, `!!int 0o17`, `!!float .nan`, `!!null foo` and tagged scalars with trailing whitespace or decoded line breaks are errors. Explicit null accepts only `~`, `null`, `Null`, `NULL` or the empty scalar.

- **Transport line breaks**: LF, CRLF and CR-only MUST be interpreted as the same YAML line breaks, including within quoted and block scalars. Normalize CRLF and CR to LF before parsing. This rule is for `capsule.yaml`; the checksum file still requires its byte-exact LF grammar.
- **Raw characters**: C0 controls other than TAB/LF/CR, DEL and C1 controls (U+007F–U+009F), raw U+2028/U+2029, raw surrogate code points and U+FFFE/U+FFFF MUST be rejected. NEL/LS/PS have incompatible YAML 1.1/1.2 line-break interpretations. To preserve these scalar values, use double-quoted escapes such as `\N`, `\L`, `\P`, `\x7F` or `\0`; their decoded values remain JSON strings. These restrictions apply to the raw document, including comments and quoted/block content.
- **Tabs**: a raw TAB is permitted inside quoted scalar content, block scalar content and comments. It MUST NOT be used in indentation, token separation or plain scalars. A double-quoted `\t` escape is permitted. This is the common supported profile, not unrestricted YAML 1.2 whitespace syntax.
- **Directives**: only `%YAML` and `%TAG` directives are supported. `%YAML` may specify 1.1 or 1.2; neither changes this profile's JSON-aligned typing. Other versions and unknown directives MUST be rejected. A document may have at most one `%YAML` directive, and each `%TAG` handle may be declared only once, even if repeated declarations are identical. Tags reached through a `%TAG` handle remain subject to the core-tag restriction above.
- **Unicode escapes**: `\uD800`–`\uDFFF` and `\U0000D800`–`\U0000DFFF` MUST be rejected, even when adjacent escapes form a UTF-16 surrogate pair. Authors use a literal Unicode scalar (for example `😀`) or a full scalar escape (`\U0001F600`). Literal backslash text, such as a double-quoted `\\uD800`, is not a surrogate escape and remains permitted.

- **Quoted continuations**: nonempty continuation lines, including a line containing only the closing quote, MUST begin with at least one ASCII space beyond the indentation of their enclosing block mapping or sequence. Blank lines may be empty. Escaped physical line breaks follow the same indentation rule. A root flow collection has no enclosing block and may continue at column zero. This profile does not adopt PyYAML's relaxed block continuation indentation.

Every rule in this list has accept or reject vectors in `conformance/golden/canonical-edge-cases.json`. A reject vector is a manifest for which a conformant implementation MUST NOT produce a capsule ID.

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

This optional procedure describes the reference implementation's current
`CapsuleVerifier.verify_statistical` API, which the `marqov-capsule compare`
command exposes for two supplied count samples.
Integrity verification and statistical equivalence are separate checks: a
statistical verdict does not authenticate either input capsule.

Inputs are two count mappings over the same outcome alphabet, with non-negative
integer counts. The statistical guarantee assumes independent samples within
and between the two runs from fixed underlying distributions. Reusing the same
samples in both arms does not establish independent replication.

The reference Python API accepts integral scalar types and converts them to
Python integers. It refuses booleans and sample totals above 2^53−1 shots before
computing floating-point diagnostics.

Acceptance settings belong to the verifier. Callers MUST resolve untrusted
capsule declarations through `VerificationPolicy.resolve` (or an equivalent
policy) before passing settings to the low-level statistical API. That API
accepts already-trusted settings; it does not establish their provenance.

| Setting | Default | Resolution |
|---|---|---|
| `epsilon` | 0.02 | Strict TVD ceiling; a usable capsule declaration may only lower it |
| `epsilon_drift` | 0.08 | Alternative ceiling, used only when the verifier opts into a declared `calibration_drift` regime |
| `min_shots` | 100 | Minimum shots in each arm; taken only from verifier policy |
| `alpha` | 0.05 | One-sided error rate, strictly between 0 and 1; taken only from verifier policy |
| `tolerance_regime` | `strict` | A declared `calibration_drift` is honored only with policy `honor_calibration_drift=True` |

For an accepted drift regime, the effective tolerance is the smaller of the
policy's drift ceiling and a usable declared `epsilon_drift`; otherwise use
the strict ceiling and declared `epsilon`. Missing or unusable declarations
fall back to the policy ceiling. Policy resolution returns regime `strict`
with the already-resolved tolerance, so downstream code does not widen it again.
The reference API falls back to `alpha=0.05` for a malformed resolved alpha.

For shot totals `n` and `m`, and empirical frequencies `p_hat` and `q_hat`:

```text
tvd_point = 0.5 * sum(abs(p_hat[i] - q_hat[i]))
slack = sqrt(0.5 * ln(1 / alpha) * (1 / n + 1 / m))
tvd_ucb = min(1, tvd_point + slack)
```

Sum over the union of observed outcomes, using zero for absent counts.
This is a one-sided upper confidence bound on true TVD with coverage at least
`1-alpha` under the sampling assumptions. The bound uses no resampling or seed.
The stated sampling assumptions are required for this coverage guarantee.

The decision procedure is:

1. Either arm has zero shots: `INCONCLUSIVE`, without computing TVD.
2. Either arm has fewer than `min_shots`: `INCONCLUSIVE`, without computing a bound.
3. `tvd_ucb <= epsilon`: `VERIFIED` within the resolved tolerance.
4. Otherwise: `INCONCLUSIVE`.

There is no affirmative `REJECTED` verdict in this procedure. An inconclusive
result does not prove that the underlying distributions differ. Diagnostic
chi-squared p-values and energy distance never change the verdict.

When the bound is computed, reports include `total_variation_distance`,
`tvd_ucb`, `alpha`, `epsilon_used`, `shots_ref`, and `shots_new`. Early returns
include shot totals, the tolerance, and minimum-shot requirement. Retired
`ci_level`, `n_resamples`, bootstrap confidence intervals, and RNG seed fields
have no role in this procedure.

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
- If statistical equivalence is implemented, use the policy boundary and decision procedure in §6, and match the published [section 6 vectors](conformance/golden/statistical-cases.json). Those vectors carry an absolute tolerance for float comparison; exact bit equality is not required, since `ln` and `sqrt` differ in their last bits across languages and platforms.
- Match the published [golden vectors](conformance/README.md). These are fixed expected outputs, not outputs regenerated during tests.

---

## 9. License

This specification is licensed under [CC-BY-4.0](../../LICENSE-SPEC).

Cite as: **Marqov Capsule Specification v1**, Marqov, 2026. Distributed in
the `marqov-capsule` source archive under `spec/v1/`; record the package version
when citing a specific revision.
