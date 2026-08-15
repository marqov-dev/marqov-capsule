# The `.checksums` format and manifest canonicalization

**Date:** 2026-08-14
**Status:** Research complete. Decision recorded (code → spec). Implementation partially landed on a branch; two blocking bugs open before merge.
**Issue:** [#20](https://github.com/marqov-dev/marqov-capsule/issues/20) — spec ≠ implementation; not interoperable
**Related:** [#53](https://github.com/marqov-dev/marqov-capsule/issues/53) (code-quality epic), [#16](https://github.com/marqov-dev/marqov-capsule/issues/16) (authenticity), [#11](https://github.com/marqov-dev/marqov-capsule/issues/11) (preprint)

---

## Why this document exists

The reference implementation was writing `.checksums` in a format its own normative spec does not describe — a YAML mapping, where the spec (§2.2, §5) specifies newline-delimited `sha256:<hex>  <path>` lines. Because the capsule ID chains through `SHA-256(.checksums bytes)`, a different serialization is a different `checksums_digest`, hence a different capsule ID, for a byte-identical payload set. A second implementation written from the published spec would disagree with the reference implementation on the identity of the same capsule — the one property a content-addressed format cannot get wrong.

Reconciling that forces a decision (change the code, or change the spec) and then a series of wire-format and canonicalization questions that, left implicit, are silent interoperability splits. This record captures the decision, the exact rules that follow from it, the prior art they rest on, and — recorded deliberately — **two determinism bugs that a green test suite did not catch**, because the fix was verified only against inputs that happened not to trigger them.

Provenance is tagged throughout, on the same scheme as the [TVD](2026-08-10-tvd-equivalence-testing.md) and [credential-detection](2026-08-11-credential-detection.md) notes:

- **[measured]** — reproduced in this investigation against the code, from Appendix A
- **[verified]** — read from the primary source in this session
- **[reported]** — from a research agent claiming a primary read (URL + quote), not independently checked; **must be checked against primary text before entering the normative spec**
- **[unverified]** — inference or construction, not established practice

---

## Summary

1. **Decision: reconcile code → spec, now.** The spec is the normative artifact third parties implement against; the reference implementation should conform to it, not the reverse. The line format is also the industry standard (BagIt/RFC 8493, `sha256sum`, OCI). It is pre-1.0 and **nothing has been published**, so re-basing every capsule ID costs four in-repo fixtures today and is unbounded to change after a public tag.
2. **The format switch re-bases every capsule ID.** Old (YAML-mapping) and new (line-format) `.checksums` hash to different `checksums_digest` values. Four conformance fixtures (8 files) were regenerated; all verify clean three-layer. No test hard-codes fixture IDs. **[measured]**
3. **Keep the `sha256:` prefix and lowercase hex; freeze the grammar, not the algorithm.** Every algorithm-agile scheme surveyed puts the algorithm in-band as a prefix; hex avoids base64's case-fold and padding-ambiguity surfaces. **[reported]**
4. **The line grammar needs edge-case rules to be byte-reproducible:** NFC normalization, narrow percent-encoding, LF-only terminators, byte-wise sort — most of which BagIt leaves loose because a BagIt manifest is never itself hashed. **[reported]**
5. **Two live determinism bugs remain in the branch** (Appendix A): a leading-zero integer is re-interpreted as octal (or crashes), and an integer past 2⁵³ is silently rounded through `float()` by the JCS library. Both silently change or corrupt the capsule ID. **[measured]**
6. **RFC 8785 (JCS) is a canonicalizer, not a validator.** It inherits ECMAScript number semantics and is explicitly silent on Unicode normalization and duplicate keys. A conformant implementation must add a numeric-range guard, NFC, and duplicate-key rejection itself. **[reported]**, corroborated by finding 5 **[measured]**
7. **Prior art to cite in the spec and preprint:** RO-Crate (the packaging precedent a reviewer will demand), SWHID/ISO 18670 (intrinsic-hash identity), BagIt/RFC 8493 (the `.checksums` lineage), in-toto/SLSA/Sigstore (the signing path, #16). **[reported]**

---

## 1. The decision: code → spec

Two directions could reconcile the mismatch:

- **Code → spec** — change the builder to emit the spec's line format. Cost: every capsule ID computed under the old YAML-mapping format changes. In-repo that is four fixtures; externally it is nothing, because nothing is published.
- **Spec → code** — rewrite the spec to document the YAML-mapping format the code already emitted. Cost: zero ID churn, but it promotes an accidental implementation detail (PyYAML's dict dumper output) into a normative standard that independent implementers must reproduce byte-for-byte — and a YAML mapping is a poor thing to content-address, because YAML has many legal spellings of the same mapping (key order, quoting, block vs flow).

**Decision: code → spec.** The line format is correct on the merits (emitter-independent, one legal spelling once sort and separators are fixed), it is what the published spec already says, and the transition is cheap now and irreversible later. This is a "fix it before the concrete sets" decision, and the concrete is not set: the repo is private, `0.1.0` is unreleased, and no capsule ID has been cited anywhere (confirmed with the maintainer). The verifier retains the ability to read the legacy YAML-mapping form, so capsules already sealed continue to verify; only new seals get the new ID. **[measured]** — the four regenerated fixtures verify clean three-layer with their new IDs.

The one condition that would reverse this — capsule IDs already published somewhere immutable (a preprint, a DOI) — does not hold today. If any capsule ID is ever published before v1 is tagged, this decision must be revisited.

---

## 2. The `.checksums` wire grammar

The grammar below is grounded in BagIt/RFC 8493 (line form and percent-encoding), GNU coreutils `sha256sum` (fixed-width separator, filename escaping), the OCI image spec (lowercase-hex requirement), and Git (byte-wise path sort). All rows are **[reported]** from the grammar research pass unless noted; the "Branch" column is the state of the determinism branch (`agent-a47fd0b0`) as of this note.

| Rule | Requirement | Basis | Branch |
|---|---|---|---|
| Line form | `sha256:<64 lowercase hex>` + two ASCII spaces + `<relative-path>` + LF | BagIt line form; coreutils fixed-width field | have |
| Prefix | `sha256:` on every line | OCI `algorithm ":" encoded` | have |
| Hex case | Lowercase only, `[a-f0-9]{64}` | OCI: "`[A-F]` MUST NOT be used" (diverges from BagIt's case-insensitivity) | have |
| Path separator | Forward slash `/` only | BagIt §2.1.3 | have |
| Sort | Byte-wise (ordinal) ascending on the encoded path | Git `tree.c` `base_name_compare` (memcmp) | have* |
| Encoding | UTF-8, no BOM | BagIt §2.3 (tightened from SHOULD to MUST) | have |
| Terminator | LF only; single trailing LF | tightened from BagIt's CR/LF/CRLF | have |
| Empty payload | Zero-length file (SHA-256 = empty-string digest `e3b0c442…b855`) | defines what BagIt's ABNF leaves out | have |
| **Unicode** | **NFC** normalization of the path before writing | marqov-original — BagIt §6.1.1 only tolerates at compare time | **add** |
| **Special chars** | Percent-encode only `%0A` `%0D` `%25` `%5C`, uppercase triplet; spaces stay literal | BagIt narrow encode-set + RFC 3986 §2.1 | **add** |
| Duplicates / scope | Each path once; relative; no `..`, no absolute | BagIt §2.1.3 | have |

`have*` — the branch uses Python `sorted()`, which equals byte-wise order for UTF-8 **once NFC is applied** (UTF-8 preserves code-point order under byte comparison). So the sort rule and the NFC rule are linked: add NFC and the existing sort is conformant.

**Why NFC is a MUST here, not a SHOULD.** BagIt tolerates normalization drift at compare time because a bag's identity is never derived from its manifest bytes. Ours is — `capsule_id` chains through `SHA-256(.checksums)` — so a path written `é` (NFC, U+00E9) versus `e`+combining-accent (NFD) produces two different capsule IDs for a visually identical file, invisible to a human diffing the files. The ambiguity must be removed at write time. This rule is **[unverified]** as precedent — no surveyed standard actually mandates a normalization form; it is a marqov-capsule-original decision justified by analogy to BagIt's own diagnosis of the problem (RFC 8493 §6.1.1.2).

---

## 3. Digest string and algorithm agility

Surveyed OCI, W3C SRI, Go `h1:`, npm/SSRI, Python wheel `RECORD`, multihash, and Nix. **[reported]**

- **Keep the `sha256:` prefix.** Every algorithm-agile scheme puts the algorithm in-band as a string prefix (OCI `alg:hex`, SRI `alg-b64`, Go `h1:`). The one outlier — Nix's historically bare base32 store hash — is currently retrofitting a tag back in (`--sri`, the `nix32` rename). Dropping the prefix walks into the hole Nix is climbing out of.
- **Keep hex for the per-file digest body.** Hex has no case-fold surface (OCI mandates lowercase for exactly this reason), none of base64's padding ambiguity (a real, cited gap in the SRI grammar, `*2("=")` with no length cross-check), diffs cleanly, and matches `sha256sum`/`openssl` output — which matters for a format a scientist may re-derive by hand.
- **Freeze the grammar, not the algorithm.** Adopt OCI's `algorithm ":" encoded` shape and validate the algorithm↔length pairing (sha256 → 64 hex). Adding `sha512:`/`blake3:` later becomes a registry addition; existing IDs stay valid.
- **State the migration policy in prose** (Go's `go.sum` precedent): additional algorithms may be registered in a future spec version without invalidating existing IDs, and **readers MUST reject an unrecognized algorithm prefix rather than guess.** The string format alone does not guarantee agility; the stated policy does.
- **Skip multihash/multibase.** It requires resolving two external, independently-versioned registries — disproportionate for a small closed algorithm set.

Nuance for later: the two digest sites — the per-file `.checksums` lines and the aggregate `checksums_digest` — need not share an encoding (Go uses hex per-file, base64 for its aggregate `h1:` token). Keep both hex now for consistency; revisit only if `checksums_digest` ever becomes a short user-facing identifier. Go's `h1:` is the closest existing analog to `checksums_digest` (a digest of a manifest of per-file digests) and is worth studying for its aggregation discipline.

---

## 4. Manifest canonicalization — conformance rules

RFC 8785 (JCS) is the right base choice for a small, human-authored YAML manifest: its canonical form is inspectable JSON text, trivially re-implementable from a spec, and it is what a scientist reading `capsule.yaml` would expect to correspond to the ID. Canonical CBOR (RFC 8949 §4.2 / dag-cbor) would fix the integer problem structurally but sacrifices that inspectability and reintroduces its own profile-writing burden (map-key type, float width, NaN/−0 policy). **Keep JCS + SHA-256 + an explicit numeric-range guard.** **[reported]**

But JCS is a *canonicalizer, not a validator*: it inherits ECMAScript number semantics, is explicitly silent on Unicode normalization (§3.1), and assumes duplicate-free input (§3.1) rather than resolving duplicates. Two independent implementations reading the same `capsule.yaml` diverge unless the manifest spec closes these itself:

| Hazard | What a conformant implementation MUST do |
|---|---|
| Large ints (>2⁵³−1) | Reject at load, or require string authoring (RFC 8785 App. D). Never let a bare oversized int reach JCS — see Bug 2. |
| Leading-zero ints | Construct as decimal, not octal — fix at the constructor, not only the resolver. See Bug 1. |
| NaN / Infinity | MUST error (JCS §3.2.2.3). The current float regex already excludes `.inf`/`.nan` textual forms — correct. |
| Negative zero | Normalize `-0.0` → `0` (JCS App. B). The WebPKI `jcs` library applies this. |
| Unicode of strings and keys | Mandate NFC before hashing — JCS §3.1 does not normalize. Applies to string values and keys, not only paths. |
| Duplicate keys | The YAML loader MUST reject them (many keep the last silently); JCS/JSON leaves the outcome undefined (RFC 8259 §4). |
| Non-string keys | Define one exact stringification and use the same routine for keys and values — the current `_stringify_key` uses Python `repr()` for float keys instead of the ES6 formatter (latent divergence). |

One correction to the spec text itself: §5 currently says JCS sorts keys in "Unicode code point order." RFC 8785 §3.2.3 sorts by **UTF-16 code units**, which differs for astral-plane characters (they sort by surrogate-pair value). The spec should quote the RFC rather than paraphrase it. **[reported]**

The ecosystem reality that makes the spec text load-bearing: most languages' idiomatic "safe" YAML loaders (PyYAML `SafeLoader`, Ruby Psych, older js-yaml) still default to YAML 1.1 typing, so a second implementation reaching for its language's default loader will resolve `yes`/`on`/`0x1A`/`12:30`/`1_000` differently than a Python implementation with hand-restricted resolvers — a different in-memory value, hence a different ID, from byte-identical input. The spec must pin the exact JSON-aligned (Core Schema) resolver set as a conformance requirement, not merely say "use YAML 1.2." **[reported]**

---

## 5. Two determinism bugs found after the pilot

Both are **[measured]** — reproduced directly against the determinism branch in Appendix A. Neither was caught by the branch's 19 new tests, because no test fed the triggering input. The lesson is not "the pilot failed"; it is that **adversarial numeric inputs belong in the determinism suite**, and the tests that would have caught these are part of the fix.

**Bug 1 — the int resolver was fixed, the int constructor was not.** The custom loader restricts which scalars get *tagged* `int` (a decimal-only regex, correctly dropping YAML 1.1 hex/octal). But it never overrides `construct_yaml_int`, inherited from PyYAML, which still runs 1.1-era logic (`value[0] == '0'` → base-8). So the tag is right and the value construction is wrong:

```
load_manifest_yaml('mode: 0755')  ->  {'mode': 493}     # silent octal reinterpretation
load_manifest_yaml('zip: 08540')  ->  ValueError: invalid literal for int() with base 8
load_manifest_yaml('id: 007')     ->  {'id': 7}          # leading zeros silently dropped
```

An ordinary leading-zero decimal (a Unix mode, a US ZIP, a zero-padded ID) is silently corrupted or crashes, contradicting the loader's own "decimal only" docstring. Fix at the constructor level so decimal-only holds end to end.

**Bug 2 — no integer-magnitude guard; JCS rounds through `float()`.** The int regex has no magnitude bound, so an arbitrary-precision Python `int` reaches the `jcs` library, whose number path formats every integer via `float(value)` — an IEEE-754 double:

```
canonical_bytes({'n': 9007199254740993})     ->  b'{"n":9007199254740992}'
canonical_bytes({'n': 9007199254740995})     ->  b'{"n":9007199254740996}'
canonical_bytes({'n': 12345678901234567890}) ->  b'{"n":12345678901234567000}'
```

Two distinct manifest integers canonicalize to wrong (or colliding) values, no error raised anywhere. This is exactly the case RFC 8785 Appendix D anticipates ("numbers that do not have a natural place in the current JSON ecosystem MUST be wrapped using the JSON string type"). Fix: reject any integer with `abs(x) > 2⁵³−1` at load (fail closed), or require it be authored as a string — never rely on a JCS library's silent rounding.

---

## 6. Prior art and references

For the spec's references section and the preprint (#11), ranked by how load-bearing the citation is. All **[reported]** from the prior-art research pass; verify each primary before it enters the normative spec.

1. **RO-Crate** — the must-cite. Same end-to-end problem (a directory + self-describing manifest as a citable research object); its spec explicitly defers checksums to BagIt/OCFL, so marqov-capsule is "RO-Crate's manifest role + BagIt's integrity role, fused." A reviewer in this field will expect the comparison.
2. **Software Heritage SWHID** (ISO/IEC 18670:2025) — legitimizes the core bet: intrinsic content-hash as identity, no central registry. The strongest citation for defending `capsule_id` in a peer-reviewed venue.
3. **BagIt / RFC 8493** — the direct precedent for `.checksums`; its `manifest-sha256.txt` is `checksum  path` lines. Cite as the format's lineage.
4. **in-toto + SLSA + Sigstore/cosign** — the signing path (#16): sign the existing `capsule_id` (in-toto binds an attestation to an artifact by digest; cosign is detached-signature-by-digest), turning "tamper-evident" into "authenticated" with near-zero format change.
5. **RFC 8785 / 8259 / 8949** — the canonicalization foundation; already the basis of `canonical_json()` but currently an unstated dependency. Must be an explicit, precise citation.
6. **OCI image-spec** — source of the `algorithm:encoded` digest grammar; also a compatible content-addressed distribution transport (alternative to the bespoke `.capsule` tarball).
7. **W3C PROV-O, Frictionless, DataCite/Zenodo, Nix** — supporting cites for a provenance graph, a minimal-descriptor comparison, the extrinsic-DOI story, and reproducible-build content addressing.

Capability gaps the survey surfaced, as candidate roadmap issues (future work, not part of this fix): signing/attestation (#16); a provenance DAG to replace the single-parent `derived_from`; an extrinsic-identifier (DOI) story; OCI-artifact distribution; SLSA-style graduated trust levels; SWHID-style qualified identifiers (`capsule_id#task_id`).

---

## 7. Design implications

Recorded as the conclusion the evidence supports. The spec edits proposed alongside this note (`spec/v1/README.md` §2.2, §5, §8; `CHANGELOG.md`) encode rules 2–4 below; the code punch-list is tracked under epic #53.

1. **Ship code → spec** (§1). The determinism branch already emits the line format; keep it.
2. **Land the `.checksums` grammar rules** (§2): add NFC normalization and narrow percent-encoding to `save_checksums`; the rest is already conformant.
3. **Land the canonicalization guards** (§4): decimal-only int construction (Bug 1), a `±2⁵³−1` integer bound (Bug 2), NFC on string values and keys, duplicate-key rejection, and a single stringification routine shared by keys and values.
4. **Correct the spec's canonicalization prose** (§4): "UTF-16 code units" per RFC 8785 §3.2.3, not "code point order"; pin the JSON-aligned YAML resolver set as a conformance requirement.
5. **Add adversarial numeric tests** to the determinism suite: leading-zero ints, `±2⁵³` boundary, NFC-vs-NFD keys and paths, duplicate keys, a non-string key.
6. **Reconcile the CHANGELOG** to the README (`sha256:` prefix on the `.checksums` line — the CHANGELOG omits it).

---

## 8. Open questions

1. Should the spec define a normative percent-encoding for backslash (`%5C`) — extending BagIt's set — or forbid backslashes in payload paths outright? BagIt leaves `\` literal; we add `%5C` to avoid a second escape convention, but a hard ban is simpler if no legitimate payload needs it.
2. Should oversized integers (`>2⁵³−1`) be a hard load-time rejection, or silently string-wrapped per RFC 8785 App. D? Rejection is safer (fail closed) but less forgiving to authors; wrapping changes the type a verifier sees.
3. Is NFC the right normalization form, or NFKC? NFC preserves visual distinctions NFKC folds away; NFC is the conservative choice, but the trade-off should be stated.
4. Does the aggregate `checksums_digest` ever need a compact (base64) encoding, or does it stay hex forever? Deferred until it becomes user-facing.

---

## Appendix A — reproduction

Run against the determinism branch (`agent-a47fd0b0`) with the project venv. Reproduces both bugs in §5. **[measured]** in this session.

```python
from marqov_capsule._canonical import load_manifest_yaml, canonical_bytes

# Bug 1 — leading-zero int constructed as octal (or crash)
for src in ["mode: 0755", "zip: 08540", "id: 007"]:
    try:
        print(f"{src!r:18} -> {load_manifest_yaml(src)!r}")
    except Exception as e:
        print(f"{src!r:18} -> {type(e).__name__}: {e}")
# mode: 0755  -> {'mode': 493}
# zip: 08540  -> ValueError: invalid literal for int() with base 8: '08540'
# id: 007     -> {'id': 7}

# Bug 2 — big int silently rounded through float() by the jcs library
for n in [9007199254740993, 9007199254740995, 12345678901234567890]:
    print(n, "->", canonical_bytes({"n": n}))
# 9007199254740993     -> b'{"n":9007199254740992}'
# 9007199254740995     -> b'{"n":9007199254740996}'
# 12345678901234567890 -> b'{"n":12345678901234567000}'
```

---

## Appendix B — verification status

**Measured here (reproduced against the code this session):** both determinism bugs in §5 / Appendix A; the four regenerated conformance fixtures verifying clean three-layer with their new IDs (§1, §2).

**Reported by research agents claiming a primary read (URL + quote), not independently checked when this note was written — the load-bearing normative claims were verified against primary text on 2026-08-16 (see below):** all grammar rules in §2 (RFC 8493, RFC 3986 §2.1, coreutils `cksum.c`, OCI `descriptor.md`, Git `tree.c`); the digest-encoding survey in §3 (OCI, SRI/CSP2, Go `go.sum`/dirhash, npm SSRI, PyPA wheel RECORD, multiformats, Nix source); the canonicalization limits in §4 (RFC 8785 §3.1/§3.2.2.3/App. B/App. D, RFC 8259 §4/§6, RFC 8949 §4.2, dag-cbor, YAML 1.2.2 Core Schema); the prior-art survey in §6.

**Unverified — marqov-capsule-original, not precedent-derived:** the NFC mandate (§2), justified by analogy to BagIt §6.1.1's diagnosis rather than by any standard that actually mandates a normalization form.

**Verified (2026-08-16):** the ten load-bearing claims that became normative MUSTs in `spec/v1/README.md` §2.2/§5 were checked against primary source text (RFC 8785 §3.2.3, §3.2.2.3, App. B, App. D, §3.1; RFC 8259 §6; OCI `descriptor.md`; RFC 8493 §2.1.3; RFC 3986 §2.1) — **all ten CONFIRMED** with located verbatim quotes. Two wording nuances were folded into the spec: the UTF-16-vs-code-point divergence is stated as an implementer's note rather than attributed to RFC 8785 (which does not state it verbatim), and RFC 3986 §2.1's uppercase-hex guidance is an ordinary-English "should" (not an RFC 2119 SHOULD) — marqov-capsule pins uppercase as its own MUST for determinism. The broader §3 encoding survey and §6 prior-art items were not each re-verified and remain [reported].
