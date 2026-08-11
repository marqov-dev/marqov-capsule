# Credential detection for capsule sealing

**Date:** 2026-08-11
**Status:** Research complete. No implementation changes made.
**Issue:** [#18](https://github.com/marqov-dev/marqov-capsule/issues/18) — redactor misses real secrets (hex/lowercase) and false-positives on quantum data
**Closed alongside:** [#33](https://github.com/marqov-dev/marqov-capsule/issues/33) (notebook source cells), [#34](https://github.com/marqov-dev/marqov-capsule/issues/34) (ignore-file trust, credential-bearing files)

---

## Why this document exists

`CapsuleRedactor` gates sealing. It currently produces both false negatives and false positives *from the same mechanism*, which means neither can be fixed by tuning — the architecture is wrong, not the constants.

This records what production scanners actually do, read from their rulesets and source rather than from summaries, so #18 can be implemented against a written rationale instead of invention.

Provenance is tagged throughout, on the same scheme as the [TVD research](2026-08-10-tvd-equivalence-testing.md):

- **[measured]** — simulated here against our own code, reproducible from Appendix A
- **[verified]** — read from the primary source in this session
- **[reported]** — from a research agent claiming a primary read, not independently checked
- **[unverified]** — inference or construction, not established practice

---

## Summary

1. Our 4.5 entropy threshold cannot flag hex. Lowercase hex maxes at 4.0 bits/char and a 64-char token measures ~3.8, so **no pure-hex secret is ever flagged** — and IBM Quantum tokens are 64-char hex. **[measured]**
2. Base64 of a secret and base64 of a float64 statevector are **entropy-indistinguishable**, and the ordering is not even reliable — the payload measured *higher*. No threshold separates them in either direction. **[measured]**
3. **No production scanner uses entropy as a detector.** In gitleaks it is only a filter applied after a regex capture matches; trufflehog applies it only to unverified results. Our arrangement is the one none of them use. **[reported]**
4. Thresholds are charset-specific in practice: detect-secrets ships Base64 at 4.5 and Hex at **3.0**, and computes entropy over the plugin's charset rather than the string's own alphabet. **[verified]**
5. The `PUBLIC_KEY` false positive disappears once a bare name can no longer match — production keyword rules require name **and** operator **and** a captured value **and** entropy. **[reported]**
6. Two gaps have no upstream answer: an IBM Quantum token rule, and any exemption for scientific numerical payloads.

---

## 1. What is wrong now

Measured against `redactor._shannon_entropy` with the shipped threshold of 4.5. **[measured]**

| sample | len | entropy | flagged? |
|---|---|---|---|
| 64-char hex token (IBM-shaped) | 64 | 3.766 | **missed** |
| sha256 digest | 64 | 3.808 | missed *(correctly)* |
| `AKIAIOSFODNN7EXAMPLE` | 20 | 3.684 | **missed** |
| AWS secret (40-char base64) | 40 | 4.228–4.515 | **coin flip** |
| uuid4-shaped | 36 | 3.391 | missed *(correctly)* |
| base64 of 256 random bytes — **a secret** | 344 | 5.867 | flagged |
| base64 of 1024 float64s — **a payload** | 10,924 | 5.911 | **false positive** |
| base64 complex128 statevector — **a payload** | 10,924 | 5.901 | **false positive** |

Theoretical maxima: lowercase hex 4.0, base64 6.0. **A 4.5 threshold is above the hex ceiling**, so the hex miss is structural, not a tuning error.

The AWS row is worth noting separately: a 40-char base64 secret measures anywhere from ~4.2 to ~4.5 depending on the draw, so it straddles the threshold. Detection of that class is a **coin flip per secret**, which is arguably worse than a clean miss — it produces a scanner that appears to work in testing and fails in production about half the time. This is a symptom of the same root cause: entropy alone is being asked to make a decision it cannot make reliably at any threshold.

Side by side, the case that decides the design:

```
base64 secret : 5.8650
base64 payload: 5.9075     <- higher than the secret
```

Entropy cannot separate them. It is not that the margin is thin — the ordering is unreliable.

---

## 2. The architecture: entropy is a filter, never a detector

**gitleaks [reported]** — `detect/detect.go` (~L542) computes entropy *after* a rule's regex has matched, and drops the finding if it falls below that rule's floor. `config/rule.go` documents `Entropy` as "the minimum shannon entropy a regex group must have". There is no standalone high-entropy scan mode.

**trufflehog [reported]** — `pkg/detectors/falsepositives.go`: `FilterResultsWithEntropy` applies only to *determinately unverified* results; verified findings bypass entropy entirely. `pkg/detectors/detectors.go` carries the comment `// TODO improve checks. Shannon entropy did not work well.`

**detect-secrets [verified]** — entropy plugins only consider **quoted** candidates: `re.compile(r'([\'"])([{}]+)(\1)')`. Bare tokens in prose, logs, or data files are never candidates. Unquoted matching exists only for ad-hoc single-string scans.

This is the single biggest divergence from our design, and it explains why our false negatives and false positives have the same root: entropy is doing a job nobody else asks it to do.

---

## 3. Thresholds, split by charset

**[verified]** from `detect_secrets/plugins/high_entropy_strings.py`:

```python
class Base64HighEntropyString(HighEntropyStringsPlugin):
    def __init__(self, limit: float = 4.5)   # string.ascii_letters + digits + '+/' + '\-_' + '='
class HexHighEntropyString(HighEntropyStringsPlugin):
    def __init__(self, limit: float = 3.0)   # string.hexdigits
```

Three details matter more than the numbers:

1. **Entropy is computed over the plugin's charset, not the string's own alphabet** — `for x in self.charset: p_x = float(data.count(x)) / len(data)`. The same string therefore scores differently under each plugin.
2. **Candidates must be quoted** (see §2).
3. The hex plugin **subtracts an all-digit penalty**, `entropy -= 1.2 / math.log(len(data), 2)`, reasoned as: *"when the input is all digits, the number of false positives we get greatly exceeds realistic true positive scenarios."*

**gitleaks' distribution across 222 rules [reported]:** 130 set an entropy floor — `2.0`×49, `3.0`×53, `3.5`×8, `4.0`×14, `4.5`×3. Every hex-charset rule sits at 2.0–3.5; the only three at 4.5 are long base64. `generic-api-key` is 3.5.

---

## 4. False-positive suppression

**[reported]** unless marked.

| Technique | Tool | Detail |
|---|---|---|
| Path allowlists | gitleaks | 36 default path regexes — images, fonts, binaries, lockfiles, `vendor/`, `venv/lib` |
| Per-rule path scoping | gitleaks | `hashicorp-tf-password` only fires in `\.(?:tf\|hcl)$` |
| `targetRules` allowlists | gitleaks | documented use case: *"Our test assets trigger false-positives in a couple rules"* |
| Stopword list | gitleaks | 1,446 entries matched against the extracted secret |
| Placeholder regexes | gitleaks | `^\$[A-Z_]+$`, `^\{\{...\}\}$`, `^%[A-Z_]+%$` |
| Quoted-candidate requirement | detect-secrets **[verified]** | the main reason it survives data files |
| Filter chain | detect-secrets | `is_sequential_string`, `is_potential_uuid`, `is_templated_secret`, `is_indirect_reference`, `is_lock_file`, `is_likely_id_string` |
| Known-shape subtraction | trufflehog | `FalsePositiveSecretPat = [a-f0-9]{40}` — git hashes match the AWS secret shape, so they are subtracted |
| Live verification | trufflehog | `--results=verified`; the primary FP control |

**The closest prior art for our statevector problem** is trufflehog subtracting git hashes from its AWS rule, and detect-secrets' `is_potential_uuid`. Both are the same move: *a recognizable non-secret shape is subtracted from an otherwise-matching rule.* Never an entropy adjustment.

---

## 5. Name patterns, and how `PUBLIC_KEY` is avoided

gitleaks' `generic-api-key` requires, in order: a keyword → ≤20 chars of connective → an assignment operator → optional quotes → **a captured value of 10–150 chars** → a terminator; then entropy ≥ 3.5 on the capture. **[reported]**

The answer to our `PUBLIC_KEY`/`PRIMARY_KEY`/`SORTING_KEY` false positives is three-layered, and **the first layer alone fixes most of it**:

1. **A bare name cannot match.** Name alone is structurally incapable of firing without an operator, a value, and sufficient entropy. Our `\b\w+(_KEY|_SECRET|_TOKEN|...)\b` matches the name on its own — that is the bug.
2. An explicit allowlist: `(?:bucket|foreign|hot|idx|natural|primary|pub(?:lic)?|schema|sequence)[_.-]?key`, plus `key[_.-]?(?:alias|board|code|id|name|pair|ring|size|word)`.
3. Reject captures matching `^[a-zA-Z_.-]+$` — a value with no digits at all is not a secret.

trufflehog's proximity primitive is worth copying directly **[reported]**: `PrefixRegex` requires a keyword within **40 characters** of the capture group.

---

## 6. Value-shape patterns

Prefix-anchored rules have near-zero false-positive rates and should block. **[reported]**, from `gitleaks/config/gitleaks.toml`:

| Credential | Regex |
|---|---|
| AWS access key ID | `\b((?:A3T[A-Z0-9]\|AKIA\|ASIA\|ABIA\|ACCA)[A-Z2-7]{16})\b` |
| GitHub PAT / OAuth / server | `gh[pousr]_[0-9a-zA-Z]{36}` |
| GitHub fine-grained PAT | `github_pat_\w{82}` |
| Google API key | `\b(AIza[\w-]{35})` |
| Stripe | `\b((?:sk\|rk)_(?:test\|live\|prod)_[a-zA-Z0-9]{10,99})` |
| Slack bot | `xoxb-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*` |
| JWT | `\b(ey[a-zA-Z0-9]{17,}\.ey[a-zA-Z0-9/\\_-]{17,}\....)` |
| PEM private key | `(?i)-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----[\s\S-]{64,}?KEY(?: BLOCK)?-----` |

**Important negative results [reported]:** gitleaks has **no** AWS *secret* access key rule (a 40-char base64 blob has no shape), **no** database connection-string rule, and **no** Azure SAS rule. Those are left to keyword proximity or, in trufflehog's case, matched loosely and then *parsed* — its SQL Server detector runs a real connection-string parser and discards the result if `Password == ""`.

---

## 7. Two gaps with no upstream answer

**No tool has an IBM Quantum token rule.** All 902 trufflehog detectors were enumerated; the only IBM entry is `ibmclouduserkey`, which is keyword proximity plus `\b([A-Za-z0-9_-]{44})\b` — not a shape. **[reported]** We have to write this ourselves, using keyword proximity, and explicitly **not** as a bare `\b[a-f0-9]{64}\b`: in this codebase 64-hex is overwhelmingly sha256, and `_DIGEST_LINE_RE` only covers three named field shapes, so a bare rule would fire on every checksum manifest.

**No tool has a scientific-payload exemption**, because nobody else scans capsules of numerical data. The technique to imitate is §4's shape subtraction — not a threshold adjustment.

---

## 8. How these tools describe their guarantees

Relevant to #18's ask to reframe the redactor as best-effort. **[reported]** unless noted.

- **detect-secrets:** regex rules *"may negatively affect the **recall** of your scan"*; the entropy detector *"may require tuning to adjust the scanning precision"*; *"You can adjust both to suit your precision/recall needs."* The tool is framed around containment — accepting that secrets may already be present while preventing the problem from growing.
- **GitHub:** patterns carry an explicit **precision level** (high/medium), and push protection is restricted to *"the most recent token versions that secret scanning can identify **with confidence** … This avoids push protection blocking commits unnecessarily."* The "about secret scanning" page makes no completeness claim at all.
- **trufflehog:** the honesty is in the code — the `Shannon entropy did not work well` TODO, and a `verified`/`unknown` tri-state conceding that unverified findings have unknown truth value.

None of them claim to find every secret. Our docs currently imply a clean scan means no credentials.

---

## 9. Design implications

Not yet approved.

1. **Two tiers.** Tier A (shape rules with distinctive prefixes) **blocks**. Tier B (keyword proximity, entropy) **warns** and never blocks. This is gitleaks' arrangement; ours is the inverse.
2. **Split entropy thresholds by charset** — hex 3.0, base64 4.5 — and compute entropy over the candidate's charset, per §3.
3. **Cap candidate length** at ~150–300 chars, but see the correction below.
4. **Require quoting or assignment context** for entropy candidates.
5. **Replace the bare-name regex** with a name+operator+value+entropy composite, plus the `PUBLIC_KEY` allowlist.
6. **Case-insensitive name rules** — `\bIBM_QUANTUM_TOKEN\b` currently misses `ibm_quantum_token`.
7. **Report the value, redacted, not the name.** A `name_pattern` finding currently reports `m.group(0)` — the variable name — which is not actionable.
8. **Reframe the guarantee** in README and docstrings, per §8.

### A correction to the research

The research concluded that a 150-char cap eliminates the statevector false positives *"with zero recall cost."* That is not right. **[measured]** — a 344-char base64 blob of random bytes is skipped by the same cap, and that is a plausible secret: 256 bytes of key material, or a long JWT.

The cap is still correct, but **only because Tier A shape rules catch the long structured secrets** — PEM blocks, JWTs and prefixed tokens all have regexes, and the cap applies only to the entropy tier. **Ordering matters: the cap is safe after the shape rules exist, not before.** Applied on its own it would quietly lose recall in exchange for the false-positive fix.

---

## 10. Open questions

1. Should Tier B findings block under `--strict`, or never block at all?
2. Is a decode-and-classify exemption for base64 numeric arrays worth the complexity, given that the length cap plus payload-path scoping may cover it? **[unverified]** — no upstream implements this.
3. Should `# capsule:allow` narrow from "suppress everything on this line" to "suppress this finding", matching `#gitleaks:allow`?
4. Does the spec need to say anything about the redactor's guarantees, or is README enough?

---

## Appendix A — reproduction

```python
import base64, os, numpy as np
from marqov_capsule.redactor import _shannon_entropy, _HIGH_ENTROPY_THRESHOLD as T

samples = [
    ("64-char hex (IBM-shaped)", os.urandom(32).hex()),
    ("AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
    ("AWS secret (40 b64)", base64.b64encode(os.urandom(30)).decode()[:40]),
    ("base64 256 random bytes (SECRET)", base64.b64encode(os.urandom(256)).decode()),
    ("base64 1024 float64s (PAYLOAD)",
     base64.b64encode(np.random.randn(1024).tobytes()).decode()),
    ("base64 complex128 statevector (PAYLOAD)",
     base64.b64encode((np.random.randn(512) + 1j * np.random.randn(512)).tobytes()).decode()),
]
for name, s in samples:
    e = _shannon_entropy(s)
    print(f"{name:>42} len={len(s):>6} H={e:.3f} {'FLAG' if e > T else 'missed'}")

# the two that decide the design
sec = _shannon_entropy(base64.b64encode(os.urandom(256)).decode())
pay = _shannon_entropy(base64.b64encode(np.random.randn(1024).tobytes()).decode())
print(f"secret {sec:.4f} vs payload {pay:.4f} — separable? "
      f"{'NO' if abs(sec - pay) < 0.1 else 'yes'}")
```

Requires numpy, so this belongs outside the base-install test path if it is ever automated.

---

## Appendix B — verification status

**Verified here against primary source:** detect-secrets `high_entropy_strings.py` — the 4.5/3.0 defaults, both charsets, charset-scoped entropy computation, and the all-digit penalty formula and its stated reasoning.

**Measured here:** every entropy figure in §1 and the length-cap correction in §9.

**Reported by a research agent claiming a primary read, not independently checked:** gitleaks' `detect.go` entropy placement, the 222-rule threshold distribution, the `generic-api-key` definition and its allowlists, the 1,446-entry stopword list, all value-shape regexes in §6, trufflehog's `FilterResultsWithEntropy` / `PrefixRegex` / `FalsePositiveSecretPat`, the 902-detector enumeration, and the guarantee language in §8.

**Spot-check before adopting:** every regex in §6 should be tested against known-good and known-bad samples before it blocks a seal. A wrong pattern here fails in the expensive direction — it blocks legitimate sealing.
