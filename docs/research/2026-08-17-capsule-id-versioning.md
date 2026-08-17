# Versioning the capsule ID string (future-proofing for a v2 format)

**Date:** 2026-08-17
**Status:** **Accepted — implemented** (branch `feat/versioned-capsule-id` / #69), landed in the `0.1.0` release-candidate window before the format freezes. Chosen form: `mqc:1:<hex>`.
**Related:** [#20](https://github.com/marqov-dev/marqov-capsule/issues/20) (format), [#12](https://github.com/marqov-dev/marqov-capsule/issues/12) (first publish), `docs/research/2026-08-14-checksums-canonicalization.md`, `docs/platform-unvendor-plan.md` (§0 `CapsuleId`, §5 discriminator).

---

## Why this document exists

A capsule ID is currently a **bare 64-hex string** — `hex(SHA-256(canonical_json(capsule.yaml)))` — with no marker of which format produced it. That is fine while there is exactly one format. It becomes a permanent problem the moment a **v2** changes the ID derivation (a different `.checksums` grammar, canonicalization, or hash), because the same content then has two different IDs and **bare-hex-v1 and bare-hex-v2 are indistinguishable strings**. This note records the problem, the recommended fix (make the ID self-describing), and exactly where it touches the code, spec, and platform — so it can be decided during the RC rather than regretted after `0.1.0`.

The framing that matters: **a v2 does not, and cannot, convert v1 IDs into v2 IDs** (a v2 ID is a hash of different bytes). Reverse compatibility means v1 IDs stay first-class forever (verifiable, resolvable, referenceable) and v2 tooling still fully handles v1 artifacts — the same model as Git's SHA‑1 → SHA‑256 transition (dual-format, both IDs retained, a translation table between them). Nothing is lost; a new format is added alongside.

---

## The core proposal: version the ID string

Give the capsule ID an **intrinsic version prefix**, so any tool can tell — from the ID alone, without the manifest — which derivation produced it. The ID travels detached from the manifest (DB rows, S3 keys, `derived_from` links, citations), so the manifest's `version` field is *not* sufficient; the version must be in the ID string itself.

Precedent (every mature content-addressed system does this):
- OCI: `sha256:<hex>` (algorithm in the digest)
- Software Heritage: `swh:1:cnt:<hex>` (scheme : version : type : hash)
- IPFS: CIDv1 is fully self-describing — and **CIDv0 being a *bare* base58 hash is exactly the mistake we would be repeating**; CIDv1 exists because un-versioned IDs became un-disambiguatable.

**Recommended form:** `mqc:1:<64-lowercase-hex>` — e.g. `mqc:1:283f9421…511a`.
- `mqc` — namespace (marqov-capsule), so an ID is self-identifying out of context.
- `1` — the **format version of the whole ID-derivation procedure** (canonicalization + `.checksums` grammar + hash). If *any* of those change, it's `mqc:2:…`. A single version number covering the whole procedure is simpler than tagging algorithm and format separately, and `checksums_digest` already carries its own `sha256:` algorithm tag.

**Rejected alternatives:**
- Bare hex (status quo) — the trap above.
- `sha256:<hex>` (algorithm-only, OCI-style) — insufficient: the *format* (canonicalization/`.checksums`) can change while still using SHA-256, so an algorithm tag doesn't disambiguate a format change.
- Rely on the manifest `version` field — the ID travels alone; you don't have the manifest when all you hold is the ID.

---

## Where it touches (the concrete change)

| Site | Change |
|---|---|
| `spec/v1/README.md` §5 Layer 3 | Define `capsule_id = "mqc:1:" + hex(SHA-256(canonical_json(...)))`. Add the migration policy prose (below). |
| `src/marqov_capsule/_canonical.py` `compute_capsule_id` | Prepend `"mqc:1:"` to the hex output — a one-line change. |
| `capsule-schema.json` (both copies) | `derived_from` pattern `^[0-9a-f]{64}$` → `^mqc:[0-9]+:[0-9a-f]{64}$` so a versioned parent ID validates. Keep the two copies byte-identical (`test_bundled_schema_is_byte_identical_to_the_spec`). |
| `src/marqov_capsule/verifier.py` | `verify_integrity(expected_id=…)` parses the `mqc:<v>:` prefix and routes to the matching derivation; a version it doesn't recognise is a clean FAIL, not a crash. |
| Conformance fixtures + tests | The four fixtures' recorded IDs (and any hardcoded test IDs) gain the `mqc:1:` prefix. Same regeneration as the `.checksums` rebase; do it in the same RC window. |
| **Platform (downstream)** | The DB `capsule_id` column and S3 keys store `mqc:1:<hex>`. This **subsumes most of the platform plan's §5 discriminator-column need** — the version is now intrinsic to the ID, so a stored ID is self-describing (a separate column stays useful only for indexing/queries, not for disambiguation). |

### Migration policy to state in the v1 spec now
Declaring the policy in v1 is what makes a future v2 orderly (the same lesson as Go's `go.sum` writing its `h1 → h2` policy up front):
1. A capsule ID is `<scheme>:<version>:<hash>`; readers **MUST** parse and dispatch on the version, and **MUST** reject an unrecognised version rather than guess.
2. A new format version **does not invalidate existing IDs** — v1 IDs remain valid v1 identifiers permanently.
3. Conformant tooling **retains prior derivations** as read-only paths, so it can recompute and verify any earlier-version capsule (dual derivation).

---

## The four mechanisms of an eventual v2 transition (enabled by the above)

1. **Dual derivation.** v2 tools keep the v1 ID-computation + v1 verifier as a permanent read-only path — a v2 tool can recompute and verify any v1 capsule. Never delete the old derivation. (Generalises the platform plan's "don't delete the legacy derivation" note.)
2. **Version-tagged IDs** (this proposal) so v1 and v2 never collide and every tool routes by prefix.
3. **An equivalence record at migration.** When a v1 capsule is re-sealed under v2, the v2 capsule records "supersedes `mqc:1:<hex>`" in a **dedicated field — not `derived_from`** (which means experimental lineage). That gives a v1↔v2 alias map, so anything holding a v1 ID can find its v2 form.
4. **Additive, never replacing.** v2 ships alongside v1; publishing v2 breaks/invalidates no v1 capsule.

---

## Cost / tradeoffs

- **It is a format change** — it changes every ID *string* (adds the `mqc:1:` prefix; the underlying hash is unchanged). So it must land **before `0.1.0` is published**; in the RC window it is nearly free, after publication it is a v2-scale break.
- Re-touches the four conformance fixtures and any hardcoded IDs (same as the `.checksums` rebase — cheap while unpublished).
- `derived_from` regex widens; string length goes from 64 to ~70 chars.
- Slight ongoing verbosity in logs/keys — the standard, accepted cost of self-describing IDs (OCI/SWHID/CID all pay it).

## Open questions

1. Scheme spelling: `mqc:1:<hex>` vs `capsule:1:<hex>` vs a SWHID-style `mqc:1:cap:<hex>` (leaving room for sub-part identifiers, e.g. a task execution within a capsule — cf. SWHID qualifiers). Recommend the simplest, `mqc:1:<hex>`, unless sub-part addressing is wanted at v1.
2. Should `checksums_digest` and the per-file `.checksums` digests also gain a format-version, or is their existing `sha256:` algorithm tag enough? (Likely enough — they are internal to a single capsule whose ID already carries the version.)
3. Does the platform want the intrinsic ID version to *replace* the plan's `checksums_format_version` column, or keep both (column for indexing)?
4. Decide during the RC: this note is a prerequisite input to whether `0.1.0` ships bare-hex or `mqc:1:` IDs.
