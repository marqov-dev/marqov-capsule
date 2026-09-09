# marqov-capsule → platform: un-vendor spec & plan

> **2026-09-09 status:** this is a historical migration design, not a current
> release checklist. See [conference readiness](conference-readiness-2026-09-09.md)
> for verified updates. Annealing, scanner improvements, versioned IDs, and the
> replacement statistical bound have landed. Platform main still vendors its
> builder; its SDK pin is now 0.5.1. Revalidate call sites and rollout assumptions
> against the target platform commit before implementing this migration.

**Date:** 2026-08-16 · **Rev 9** (propagates Rev 8's findings: publication prerequisite, paradigm-mapping contract, S3 key migration, pin-lattice)
**Status:** Ready to implement. Open decisions are flagged as such: the rollout model (§9), the credential-scan disposition (§2.3), the statistical disposition (§6), and one **capsule-side blocker** — the schema has no `annealing` paradigm (§2.4).
**Audience:** (1) implementing agent — §0, §4, §5, §9; (2) technical reviewer — §0, §2, §5, §6, §10, §11.
**Capsule state:** PR [#65](https://github.com/marqov-dev/marqov-capsule/pull/65) = squash-merge commit `7cb7cba313cb4b6e880d3d70ba9f942cc8c0dd4a`, on `origin/main`. 239 tests pass; CI green on 3.10/3.11/3.12.

> **History.** Rev 1: "one-line swap" (wrong). Rev 2: builder API hard breaks + ID migration. Rev 3: sealing runs the redactor fail-closed (§2.3). Rev 4: the verify-checksums row, the `annealing` gap (§2.4), sniff-based backfill (§5). Rev 5: trusted-ID ↔ discriminator coupling (§0/§4), verification-is-decorative-today (§2.5), single-pass sniff+corpus scan (§5), `annealing` scope-conditionality. Rev 6: SDK version-skew risk; §2.4 issue ref → #53. Rev 7: verified system architecture §1.1. Rev 8: corrected a stale-branch read (pin `0.4.0`; platform line numbers vs `origin/main` @ `aa08847`). Rev 9: propagated Rev 8's findings — capsule publication as phase-0.5 (§9), paradigm mapping as a versioned format-contract (§4/§11), S3 key scheme resolved conditional→fact (§5), narrowed §2.1, SDK pin-lattice (§7).

---

## 0. Invariants & machine checks (write these first)

| Invariant | Enforcing check | Gate |
|---|---|---|
| No capsule code is vendored | a `check_no_vendored_capsule.py` mirroring the platform's existing `check_no_vendored_marqov.py` (I1/I2/I3, §1.1) in the same CI drift-guard job: bans a re-vendored copy, requires an exact `marqov-capsule==` pin, forbids git/URL — **added in §9 phase 2**, permitted in phase 1 | blocks-merge |
| Capsule identity is never compared across format versions | a `CapsuleId` value object carrying `checksums_format_version`, so a bare-string compare fails type-check; DB `capsule_id` paired with non-null `checksums_format_version` | blocks-merge |
| Manifest authentication is consumed at every verification site | forged-manifest fixture (recomputed `.checksums`+`checksums_digest`) is rejected by the **platform** path, not merely the library (§4 `:553`) — **gated on §5 phase 0: the trusted `expected_id` is the DB row, so this is only as sound as the discriminator backfill** | blocks-merge |
| No statistical *verdict* is produced or persisted | `verify_statistical` / `verify_capsule(method="statistical")` unreachable from worker entry points and has no CLI surface in capsule 0.1.0 (#15) — **the `FutureWarning`-based check this row previously named was deleted along with the miscalibrated estimator it warned about; capsule now emits no warning at all, so a machine check enforcing this row does not currently exist and is open work** | blocks-merge |
| Sealing is idempotent-safe under retry | reaper retry path does not re-enter `seal_capsule` on already-sealed content (§2.2, #59) | blocks-deploy |
| A seal-time `RedactorError` is observable and non-job-fatal | metric + alert on seal-time `RedactorError`, and a defined fallback (not a lost run) — *this is the enforceable form; "never false-positives" is not testable* (§2.3) | blocks-deploy |
| Capsule byte-output is environment-independent | golden-vector: fixed content → fixed ID under varied `cwd`/`TZ`/locale/enum order (§8) | blocks-merge |

---

## 1. Why this exists

The platform carries a vendored copy — `platform/src/capsule_builder.py` (580 lines, ~5 months old) — imported once at `platform/src/platform_worker.py:75` (`origin/main`; re-locate by symbol, §1.1). It misses every security fix since (issue [#50](https://github.com/marqov-dev/marqov-capsule/issues/50)) and still ships the statistical code capsule removed as broken (issue [#15](https://github.com/marqov-dev/marqov-capsule/issues/15)). Goal (issue [#2](https://github.com/marqov-dev/marqov-capsule/issues/2)): delete the copy, depend on the fixed package.

## 1.1 System architecture (verified against `origin/main`, 2026-08-16; platform @ `aa08847`)

> **Line-number caveat.** The first read was of a stale platform branch (164 commits behind `main`); `platform_worker.py` moves fast (it was refactored ~930 lines between that branch and `main`). All line numbers here are `origin/main` @ `aa08847` — **re-locate every call site by symbol (grep), not by line.** `capsule_builder.py` is byte-identical across the two, so the API diff in §4 is unaffected.

`spec/v1` is the contract (`spec/v1/README.md` §2.2/§5 = canonical bytes + ID derivation). Every component that seals or verifies a capsule implements it; the normative claim is identical content → identical bytes → identical IDs across implementations. Breaking it silently fails in the user's hands, not CI.

| Component | Role | Capsule relationship (verified) |
|---|---|---|
| `marqov-capsule` | reference impl + spec home | — |
| capsule CLI | ships in the capsule package | same tree, always in lockstep |
| Marqov platform | server-side seal/verify | **this migration**: vendored `platform/src/capsule_builder.py` → package dep; `pyproject.toml` has **no** capsule dep today |
| `marqov` SDK (`marqov-sdk`) | client library + the platform's quantum core | **no capsule dependency** (all three SDK repos checked) — not a spec implementation today |

**Edges (verified — and different from the assumed diagram):**
- **Platform → SDK is a *runtime* dependency**, not dev-only: `pyproject.toml` pins `marqov==0.4.0` ("The public SDK, from PyPI — exact pin"). The SDK itself is at **`0.4.1`**, so the platform runs one patch behind — a live instance of the version-skew risk (§7). The platform uses the SDK as its quantum core (circuits/backends/transpilation), not to call its own API — legitimate, not the circular-client smell.
- **SDK → platform is an HTTP call** (`marqov/platform/client.py`, `base_url=https://app.marqov.ai`). The SDK is the client and touches capsule **not at all** — so §8(e)'s third leg and the SDK skew concern are **moot unless the SDK starts sealing capsules** (open question, end of section).

**The un-vendor is a proven playbook — the platform already did it for the SDK.** `marqov` was previously vendored and is now an exact PyPI pin enforced by a **drift guard** (`tools/check_no_vendored_marqov.py`, run in CI):
- **I1** no vendored copy reappears (no `sdk/marqov/`, no top-level `marqov/`);
- **I2** a `marqov` dependency is declared;
- **I3** pinned **exactly** (`==0.4.0`) — **not a URL/editable/git pin, and no git/URL dependency may be present at all.**

The capsule un-vendor should **mirror this**: a `check_no_vendored_capsule.py` (capsule I1/I2/I3) in the same CI job. **This is the home §0's invariants and §7's skew check were missing — it already exists.**

**This corrects §7's sequencing.** I3 forbids git/URL deps, so the git-SHA pin I offered as an interim **would fail the platform's own drift guard.** Capsule can only be an **exact-pinned wheel on a resolvable index** (CodeArtifact private wheel, or PyPI) — so **capsule must be published to an index before the platform can un-vendor.** The "no PyPI for a week / git-pin meanwhile" path is not viable under the platform's invariants; a CodeArtifact wheel (`0.1.0+7cb7cba`) is the only interim that satisfies I3.

**Prerequisite answers found while verifying:**
1. **SDK capsule dep** — none. §8(e) stays two-legged (platform + CLI).
2. **Backend → paradigm mapping** — **none exists** in the platform; sourcing `requirements.paradigm` (§4) is greenfield, not a lookup.
3. **`annealing` is live** — `platform/src/dwave_executor.py` runs D-Wave annealing jobs, so §2.4's schema gap is **real** (unless D-Wave is explicitly cut).
4. **S3 embeds `capsule_id`** — `download_capsule_from_s3(team_id, capsule_id, …)` / `upload_capsule_directory_to_s3(…, capsule_id)`, so the rebase (§5) is a **storage-layout** migration, not just a column one.
5. **Re-verification entry points** — the worker `/seal` and `/verify` handlers (`platform_worker.py:553/567/3012`); no separate stored-capsule re-verify path found.

**Open forward question (has a deadline):** if SDK-side sealing is *planned*, does it land before or after the format rebase? After is free; during means a third implementation is written against a mid-migration format. Ask now, not in three weeks.

---

## 2. What we did on capsule (#65), and its compatibility edges

Security fixes #54–#60, determinism #20 (the `.checksums` change that **re-bases every capsule ID**, §5), archive hardening #61. Detail: `docs/research/2026-08-14-checksums-canonicalization.md`.

### 2.1 "Old capsules still verify" is format-only, not content
Old `verify_checksums` used `is_file()` (`capsule_builder.py:219`) — follows symlinks, skips non-regular files — so a symlink-bearing capsule **passed** before and **fails** now (#55/#56).
- **Prerequisite:** a **full** symlink/non-regular scan of the S3 corpus (inventory + member enumeration; no hashing; cheap). A sample cannot support a zero-count claim (§8).
- **User-visible (narrowed by §1.1 finding 5):** the only re-verification paths are the worker `/seal` and `/verify` handlers — **no** stored-capsule re-verify on download or report export. So a legacy symlink capsule fails only on an explicit `/verify`, not silently on the user's next download — a materially smaller blast radius (reconsider the §10 gate). **Confirm `/verify`'s exposure:** if it's externally reachable, §2.5's "verification authenticates/blocks nothing" is a *public* endpoint returning a verdict it doesn't stand behind — the same bucket as §6 option (C).

### 2.2 #59 + the reaper
#59 makes "re-seal already-sealed content" a hard-fail; the reaper retries finalization. **Confirm no reaper retry re-enters `seal_capsule` (lines 509/2785) on already-sealed content.**

### 2.3 Sealing runs the credential scanner, fail-closed
Package `seal_capsule` runs `CapsuleRedactor` as step 1 and **raises `RedactorError` unless `warn_only=True`** (confirmed in `builder.py`; #57). The vendored builder didn't.
- **New failure mode:** a false-positive fails the seal → fails the job at finalization. Payloads (QPU results, param dicts, backend metadata) are high-entropy; the research note (`docs/research/2026-08-11-credential-detection.md` §1) measured base64 statevectors being flagged.
- **The held #18 now matters:** the platform invokes the redactor transitively on **every seal**, so it ships on the *current* false-positive-prone redactor through launch. Earlier "hold #18, no impact" is void.
- **Decision — set `warn_only` explicitly at both seal sites:** (a) `warn_only=True` (log, don't block) until #18 lands; (b) un-hold #18's false-positive fix and ship it so fail-closed is safe; (c) fail-closed + accept risk, only after testing representative real payloads.
- **Cost:** the scan walks contents at seal time — new latency/I/O in the finalization critical section. Size against your largest capsule.

### 2.4 Capsule-side gap: the schema has no `annealing` paradigm
The schema `paradigm` enum is `["gate-based", "analog", "classical"]` — **no `annealing`**. `seal_capsule` requires a schema-valid `paradigm` (§4). So **a D-Wave / annealing workload cannot produce a valid capsule under the current format.** The CLI and schema currently agree (neither offers `annealing`, aligned in the pending quality-batch work under epic #53) — but that alignment went the *wrong* direction: since the product needs annealing, the **schema should have gained the value, not the CLI dropped it.** State that in the capsule-side issue so it isn't re-litigated as "the CLI already decided this."
- **Fix (capsule side):** add `annealing` to the schema enum (schema + a conformance fixture + a spec/CHANGELOG note).
- **Scope:** D-Wave annealing is a **live executor** (`platform/src/dwave_executor.py`, verified §1.1), so this gap is **real — blocks-merge unless D-Wave is explicitly cut from the launch.** If cut, it drops to a post-launch capsule item via the normal spec process.

### 2.5 Verification is decorative in production today
Independent of the swap: the platform calls `verify_checksums` at `:553` and **does not gate on the result** — it returns it to the caller. So the product runs integrity verification that authenticates nothing and blocks nothing *today*, the same shape as §6's untrustworthy-statistics-today. Given the launch narrative rests on reproducibility, this warrants an explicit product decision (does a failed verification block anything, and where?), not just the mechanical fix in §4.

---

## 3. Package API surface

```python
from marqov_capsule import CapsuleBuilder, CapsuleValidator, CapsuleVerifier, CapsuleRedactor, RedactorError
```
- **Deterministic path is numpy-free** (verifier imports numpy lazily via `_require_numpy()`).
- **Statistical path — do not rely on it** (#15; `verify_statistical` is unreachable from worker entry points and unexposed by the CLI; no `FutureWarning` is emitted any more — the estimator it warned about was replaced, not just silenced; `verify_capsule(method=…)` is method-dispatched; `verify_capsule_results` is **absent**).
- Runtime deps: `pyyaml/jsonschema/click/jcs`; numpy/scipy `[dev]`-only; `requires-python = ">=3.10"`.

---

## 4. The un-vendor work — API diff

In-memory model (vendored) → directory-on-disk model (package). This is a flow rewrite.

| Call site (`platform_worker.py`) | Vendored | Package | Verdict |
|---|---|---|---|
| `:75` `verify_capsule_results` import | module fn | **absent** | ❌ remove; §6 |
| `:470` `CapsuleValidator.validate` | `→dict` | `→{"valid": bool, "errors":[{"path","message"}]}` | ✅ compatible |
| `:506–507` `builder._capsule=…; _task_executions=…` | private attrs | same names but skips `start_capsule` init | ⚠️ replace with public API — **`created_at`/`lifecycle_state` feed canonical bytes, so this changes the ID for the same logical run** |
| `:553` `verify_checksums(tmpdir)` | `→dict` | `→{"status":"pass"/"fail", "passed": bool, …}` | ⚠️ Result is a **dict → always truthy**: gate on `["status"]=="pass"`, never truthiness. **Layer-1 only** — checks files vs `.checksums`, does **not** authenticate the manifest, so it gives **no forgery protection** (a recomputed-`.checksums` forgery passes). For #58's value, call `verify_integrity(expected_id=<trusted>)`. **The trusted `expected_id` can only come from the DB `capsule_id` row → this invariant depends on §5's discriminator being correct** (a false-provenance row appears to authenticate and doesn't); the `CapsuleId` object must carry its version *into* the call (verifying a legacy capsule against a new-scheme ID is a guaranteed false failure); and a capsule with **no stored ID** (ingested / out-of-band) has no anchor — decide that path (reject, or fall back to `verify_checksums` with the reduced guarantee stated at the API surface). §2.1 symlink regression is here; the platform doesn't gate on the result today (§2.5). |
| `:509, :2785` `seal_capsule(exit_code=…, exit_message=…)` | in-memory `→dict[str,str]` | `seal_capsule(capsule_dir, sealed_by, notes, warn_only, derived_from)`, writes to disk, **runs redactor** (§2.3), **requires `requirements`** (next row) | ❌ hard break |
| — `requirements.paradigm` / `max_qubit_count` | not required | **required** — `seal_capsule` raises `ValueError` without them | ❗ **must be sourced, not defaulted.** `paradigm`: map from the backend/provider (gate-based: IonQ/Rigetti/IQM/Quantinuum; analog: QuEra; **annealing: D-Wave → blocked, §2.4**), decided explicitly from the backend registry. `max_qubit_count`: the **circuit's demand** (not device capacity). **Both feed canonical bytes → a defaulted/wrong value is baked into the ID permanently.** And because `paradigm` feeds the ID, the **backend→paradigm mapping is part of the format contract — and none exists yet (§1.1 finding 2)**: it must be a versioned, frozen, checked-in table (test: no backend falls through to a default; changing an existing entry is a *format change*, not a config edit). Greenfield design, pre-freeze, unsized (§11). Test: neither field defaulted. |
| — `exit_code` / `exit_message` destination | manifest fields | **no equivalent** → map to `add_task_execution(status=…)` (`success`/`failed`/`error`) and/or `seal_capsule(notes=…)` | ❗ decide explicitly or exit status silently stops being recorded (reproducibility regression) |
| `:2757` `start_capsule(…, created_by, tags)` | has `backends_ref` | adds `requirements`; keeps `created_by`/`tags`; drops `backends_ref` | ✅ compatible — but now populate `requirements` (above) |
| `:2767` `add_task_execution(backend=<str>, queue_time_seconds, shots, outputs)` | `backend: str` + extras | requires `status`, `result_type`, `backend: dict`; **no** `queue_time_seconds`/`shots`/`outputs` | ❌ hard break — backend→object (move `shots` inside), add `status`/`result_type` |
| `:2782` `add_result_digest(result, "results")` | present | present (`builder.py:169`) | ✅ confirmed |

**Staging story:** the directory model needs a worker tmpdir — respect ephemeral-disk limits and clean up on the failure path (incl. the reaper's). **Local-patch check:** diff the vendored file against the capsule commit it was copied from; local patches are silently dropped on delete.

---

## 5. Capsule-ID rebase — a data migration

- **Format discriminator (separate, earlier PR — §9 phase 0).** Add `checksums_format_version`; **populate by sniffing each row's stored `.checksums` (YAML-mapping → legacy; line-format → new)** — **not** a blanket `UPDATE … SET version=1`. A blanket update assumes every ID came from the vendored builder; some may have been sealed by the capsule CLI/SDK directly (QRC spike, Pawsey deliverable) or ingested user-supplied. A blanket write puts false provenance into the exact column whose purpose is provenance, unfalsifiable afterward. The sniff reads each capsule's stored `.checksums` from S3 — **the same enumeration §8(c)'s corpus symlink scan needs, so run it once and emit both** (discriminator value + symlink/non-regular flags). That removes the per-object-read cost objection to sniffing.
- **Ingest path:** if the product accepts user-supplied capsules, ingest must derive the discriminator by sniffing — so ingest needs the discriminator logic **before** the swap, not after.
- **S3 embeds the ID (confirmed, §1.1 finding 4) — the largest unspecified item.** `download/upload_capsule_*(team_id, capsule_id, …)` put `capsule_id` in the object key, and you can't add a discriminator column to a key. So the rebase is a **storage-layout migration** — pick the approach (dual-write, an alias map, or a key scheme that doesn't embed the ID); it's a design decision in the pre-freeze window, currently unsized. **Sniff interaction:** §5's backfill reads each capsule's `.checksums` *by a key containing the ID*, so if the key scheme changes, the sniff runs against the *old* layout and writes results referencing the *new* one — sequence that explicitly. Also enumerate DB rows, cross-references, and cached IDs.
- **Legacy derivation is deleted with the file.** Preserve it as a read-only utility if anything needs an archived capsule's *original* ID, or confirm nothing does. Record any legacy→new relationship in a **dedicated migration/alias field — not `derived_from`, which means capsule lineage (a parent capsule), a different thing.**
- **Rollback** relies on the discriminator column; add it first.
- **Timing:** cheaper before any public corpus exists (§11).

---

## 6. Statistical verification — recommendation

`:567` (`verify_capsule`, `method` defaults to `"statistical"`) and `:2968–3012` (`verify_capsule_results` → `statistical_tests`) ride on #15 machinery.

**Recommendation: (C)** for any externally reachable surface (keep the endpoint, return `unsupported`/`under_revision`) and **(A)** internally (remove the branch). Flip `:567`'s `method` default to `"deterministic"` and **call that out as breaking** for callers that never passed `method`.

**Historical verdicts:** `statistical_tests` may be persisted in job records and rendered by **Report Export v1** — deleting the code retracts neither. Decide flag/suppress/leave (reputational, weeks from launch).

Not independent of §2.3: even a deterministic seal runs the redactor, so the deterministic swap depends on the `warn_only`/#18 call — just not on the statistical one.

---

## 7. Dependency mechanism

**Git/URL dependencies are *prohibited*** by the platform's drift guard (I3, §1.1) — a `git+ssh` pin fails the platform's own CI. Capsule must be an **exact-pinned wheel on a resolvable index** (CodeArtifact, then PyPI), which makes publication a phase-0.5 prerequisite (§9). (Git's drawbacks are now background: BuildKit `--mount=type=ssh`, token leakage into `pip freeze`/lockfiles/layers, and `--require-hashes` incompatibility.)
- **Version string:** use a PEP 440 local/dev id — **`0.1.0+7cb7cba`** (or `0.1.0.dev0`) — do not publish `0.1.0` to CodeArtifact from `7cb7cba` and `0.1.0` to PyPI later from a different tree. **PyPI rejects local versions** (`+7cb7cba`), so the CodeArtifact→PyPI move is a *version change* (`0.1.0+7cb7cba` → `0.1.0`), i.e. a second pin bump — and confirm `check_no_vendored_capsule.py`'s pin regex tolerates the `+local` suffix, or phase 1 fails its own guard on day one.
- **Dependency-confusion:** if CodeArtifact has a PyPI upstream, `marqov-capsule` resolves from either once public — confirm upstream/priority (same class as the OSS release pass).
- **Transitive:** resolve `pyyaml/jsonschema/click/jcs` against existing pins first.
- **Python patch pin:** `extractall(filter=)` fallback is patch-sensitive (3.10.12 / 3.11.4) — pin the base-image patch, assert in CI.
- **Pin-lattice check (the skew check's real scope).** The platform depends on capsule *directly*, and would acquire it *transitively* if the SDK ever adds it — two exact pins that disagree is a hard resolution failure; two that agree is worse (silent, unexamined). Two cheap mitigations: (1) **policy that `marqov-capsule` must not depend on `marqov`** (no cycle); (2) add capsule to whatever check already catches SDK dependency changes. The skew check is therefore a **pin-lattice across capsule / SDK / platform**, not a single pin. Resolve the live instance now (platform `marqov==0.4.0` vs SDK `0.4.1`) and name who owns the bump.
- **No git/URL pin — it fails the platform's own drift guard.** `check_no_vendored_marqov.py` I3 (§1.1) forbids git/URL/editable dependencies, so `marqov-capsule @ git+ssh://…` would fail the platform's CI. Capsule must be an **exact-pinned wheel on a resolvable index** (CodeArtifact `0.1.0+7cb7cba`, or PyPI). **Consequence:** capsule must be published to an index **before** the platform can un-vendor — the "git-pin now, publish later" interim is not available.

---

## 8. Test plan

- **(a)** old-vendored-sealed fixture verifies under the package; a symlink fixture now **fails** (pins §2.1).
- **(b)** golden vectors: fixed content → expected new ID.
- **(c)** a **full** symlink/non-regular corpus scan (§2.1 zero-count) + a *sampled* full re-verification — **one S3 enumeration shared with §5's discriminator sniff**.
- **(d)** determinism vector under varied `cwd`/`TZ`/locale/enum order.
- **(e)** cross-implementation (the point of #20): platform-sealed vs capsule-CLI-sealed on identical content → identical bytes and IDs. **Pin the CLI to `7cb7cba` / `0.1.0+7cb7cba`** in the test; a divergence is a spec bug in whichever side moved. The SDK has **no capsule dependency** (§1.1), so it is not a third implementation today — no third leg needed. *Forward note:* if the SDK ever seals capsules, add SDK-vs-platform and fold it into the pin-lattice check (§7).
- **(f)** forged-manifest fixture rejected by the *platform* verification path (§0 / §4 `:553`).

---

## 9. Sequence & rollout model

**The phase-1 flag is not a boolean.** The two builders differ structurally (in-memory vs directory, different signatures, the `requirements` gate, the redactor, tmpdir staging), so flag-gating means maintaining **two parallel finalization paths** (reaper/error/cleanup duplicated) through phase 1 — a real cost that re-sizes §11. Cheaper: an **adapter** presenting the vendored in-memory call-shape over the package builder, so the flag toggles only the sealing backend; the adapter is a shim the import-linter must permit in phase 1 and reject in phase 2. **If the fleet drains fast and nothing dedupes on ID, option (i) below is the better trade.**

- **(i) Accept the mixed-fleet window** — both schemes are discriminator-tagged; damage bounded to dedup/cache during rollout. Simplest; no dual path.
- **(ii) Two-phase deploy** — phase 1 ships the dependency with the old sealer retained (via flag or adapter); phase 2 flips, deletes the file, adds the import-linter. Clean rollback, at the cost above.

**Sequence:**
0. **Phase 0 (separate PR):** §0 invariants (except import-linter) + §5 discriminator column + **sniff-based** backfill + ingest discriminator logic. Resolve §2.4 (annealing) on the capsule side if D-Wave is in scope.
0.5. **Capsule publication (capsule + infra — new critical-path prerequisite, not platform):** build `marqov-capsule` as an exact-pinned wheel and publish to CodeArtifact, because I3 forbids a git/URL pin (§7). **Gates phase 1** and has its own lead time (CodeArtifact repo config, publish credentials, first-upload verification) — size separately (§11).
1. **Phase 1:** dependency; rewrite `seal_capsule`/`add_task_execution`/private-attr sites (§4); source `requirements`; map `exit_code`; decide `warn_only` (§2.3); switch `:553` to `verify_integrity` + consume auth (§4/§0); keep the old sealer behind flag/adapter.
2. **Phase 2:** flip; delete `capsule_builder.py`; add import-linter. **Rollback checklist must include cleaning up in-flight tmpdir capsule directories stranded by reverting to the in-memory sealer.**
3. Corpus scan + re-verification-path audit (§2.1); statistical disposition (§6).
4. Full test plan (§8); reviewer sign-off on the ID-rebase, redactor, and statistical dispositions.

---

## 10. Risk register

| Risk | Owner | Gate |
|---|---|---|
| Format-discriminator column + **sniff-based** backfill + ingest discriminator | platform | blocks-merge |
| Mixed-fleet / rollback handling | platform | blocks-deploy |
| S3 keys/prefixes embedding `capsule_id` | platform | blocks-deploy |
| Builder API hard breaks (`seal_capsule`, `add_task_execution`, `requirements` gate) | platform impl | blocks-merge |
| **`requirements` sourced wrong → wrong ID baked in permanently** | platform impl | blocks-merge |
| Schema has no `annealing` paradigm — D-Wave capsules can't seal (§2.4) | capsule + product | blocks-merge **if D-Wave in the launch cut**; else post-launch |
| Credential scan fails a job on FP; ships on held-#18 redactor (§2.3) | product + platform | blocks-deploy |
| `:553` layer-1 only → no forgery protection unless switched to `verify_integrity`; trusted ID depends on §5 discriminator (§4) | platform impl | blocks-merge |
| `exit_code` mapping (silent reproducibility loss) | platform impl | blocks-merge |
| Corpus symlinks; user-visible re-verify regression (§2.1) | platform | blocks-deploy |
| Reaper retry re-enters `seal_capsule` (§2.2) | platform | blocks-deploy |
| Statistical features + historical verdicts (§6) | product + reviewer | blocks-deploy |
| Vendored file local patches (§4) | platform impl | blocks-merge |
| CodeArtifact wheel / version string / dependency-confusion (§7) | infra | blocks-merge |
| Version skew: platform/CLI/SDK pin different `marqov-capsule` across a format change (§7) | infra + product | blocks-deploy |
| Worker disk staging for the directory model (§4) | platform impl | blocks-deploy |
| Two-path/adapter cost of the phase-1 flag (§9) | platform impl | informational |
| Python patch-version pin (§7) | infra | informational |

---

## 11. Sizing against the freeze

The binding date is the **feature/scope freeze**, not the flip — a schema change + backfill (phase 0) is exactly what a freeze excludes, and the freeze is earlier. Size phase 0 and phase 1 against the **freeze** calendar.

- **Before the freeze (coupled, recommended):** **phase 0.5 — publish capsule to CodeArtifact** (hard prerequisite, own lead time), phase 0 (discriminator + backfill + ingest; + §2.4 annealing if in scope), the deterministic un-vendor (§4), the `warn_only`/redactor decision (§2.3), and **two unsized greenfield design items now in the critical path — the versioned backend→paradigm mapping (§4) and the S3 key-scheme migration (§5).** These carry the security value and can't be safely separated (the seal path invokes the redactor; the rebase is cheaper pre-corpus). **Those two design items plus the phase-0.5 lead time are the schedule risk — none is sized.**
- **Can follow only if internal:** the statistical disposition (§6). If either stats endpoint is on the launch surface, option (C) must precede the freeze.
- If the two-flow rewrite + migration can't be done well before the freeze, the honest fallback: land the migration + a minimal deterministic swap (`warn_only=True` to de-risk the redactor) before, and the statistical/redactor hardening after. An unsized migration in the critical path during a freeze window is itself the risk — size §9 step 1 explicitly.

---

## 12. References
- **Capsule PR #65** (merged): `7cb7cba313cb4b6e880d3d70ba9f942cc8c0dd4a` (`origin/main`).
- **Issues:** #50 / #2 (vendoring & swap), #15 (statistics), #18 (redactor false-positives — held), #20 (format), #53 (quality epic). New capsule-side item (**needs an issue filed**): add `annealing` to the schema `paradigm` enum, recording in the issue body that the schema should have gained the value rather than the CLI dropping it (§2.4).
- **Capsule docs:** `spec/v1/README.md`; `docs/research/2026-08-14-checksums-canonicalization.md`; `docs/research/2026-08-11-credential-detection.md`; `docs/research/2026-08-10-tvd-equivalence-testing.md`.
- **Platform touch points** (`origin/main` @ `aa08847` — re-locate by symbol, §1.1): `platform/src/capsule_builder.py` (delete); `platform/src/platform_worker.py` — import `:75`; validate `:470`; private-attr writes `:506–507`; `seal_capsule` `:509` & `:2785`; `verify_checksums` `:553`; `verify_capsule` `:567`; `start_capsule` `:2757`; `add_task_execution` `:2767`; `add_result_digest` `:2782`; `verify_capsule_results` `:3012`.
- **Licensing:** capsule is Apache-2.0; confirm the vendored copy left no attribution gap in anything already published.
