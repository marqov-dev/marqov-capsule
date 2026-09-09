# Capsule conference readiness — 2026-09-09

## Decision

Use capsule for a standalone, reproducible demonstration of an experiment
record: execute locally with the released SDK, seal the exported files, pack,
verify against a separately recorded ID, and detect changed results/metadata.
The runnable instructions are in [examples/README.md](../examples/README.md).
The platform migration remains a separate integration project.

This assessment starts from capsule main `1609d3947b9801ea647d86c5e8f0ff7c25ab7913`
and includes the accompanying local changes. They have not been published.

## Work completed in this change

- Added separate SDK execution and capsule packaging scripts. The SDK step
  exports actual local-simulator counts, the circuit, source, and Python/package
  versions. The capsule step keeps its trusted ID outside the payload and tests
  schema validity, archive determinism, extraction, payload tampering, and
  manifest tampering. The source distribution includes the examples.
- Corrected installation instructions: the first PyPI release is still pending.
  Corrected bare-hex ID descriptions to `mqc:1:<64 lowercase hex chars>`.
- Replaced the retired bootstrap spec section with the implemented one-sided
  bound, sampling assumptions, policy trust boundary, and two-verdict procedure.
- Published fixed outputs for six existing fixtures and eight canonicalization
  edge cases. Ordinary-fixture digest checks use independent standard-library
  serialization/hashing; edge-case canonical strings are specified explicitly.
- Fixed issues exposed by the readiness checks: versioned provenance IDs were
  flagged as secrets; digest fields could suppress credential detection for an
  entire line; canonical key normalization could silently discard a colliding
  value. New regressions cover these behaviors. Existing valid fixture IDs stay
  unchanged. Ambiguous manifests now fail instead of acquiring a lossy ID.
- Marked the older platform migration plan as historical and linked this update.

## Validation evidence

All local checks ran on Python 3.12.12:

| Check | Result |
|---|---|
| Full development suite | 304 passed |
| Fresh built-wheel base install, no NumPy | 268 passed, 2 skipped; two existing Click deprecation warnings |
| Build source distribution and wheel from that source distribution | Passed |
| `twine check` on both artifacts | Passed |
| Clean install with published `marqov==0.5.1` | Passed |
| Actual SDK local Bell run, seed 42, 1,000 shots | `00: 503`, `11: 497` |
| Final wheel, base-only packaging of that SDK export | Schema, deterministic archives, round-trip, and both tamper checks passed |
| Diff whitespace check | Passed |

The clean SDK setup was tested separately from the existing SDK checkout.
No cloud execution was performed. The example records environment versions;
it does not claim a complete environment lock or automated re-execution.
This change has not yet run through remote CI or the Python 3.10/3.11 matrix.

## Release gates and issue reconciliation

The GitHub issue list is historical evidence, not a current release checklist.
No issues were closed or rewritten as part of this local change.

| Issue/workstream | Evidence and remaining action |
|---|---|
| #15 statistical estimator | Replacement merged September 7. New spec text describes it. Review the statistical contract; no CLI is promised for 0.1.0. |
| #20 interoperability | Earlier checksum grammar and versioned IDs already landed. This change adds fixed vectors and reconciles statistics. Still needs external/second-language validation, broader path-encoding vectors, and review of the remaining schema/reader contract. |
| #16 authenticity claims | README and demo distinguish content integrity from authenticity. Audit remaining public language; signatures remain outside this demo. |
| #21 / #53 readiness epics | Reconcile each historical checkbox against merged code and these tests; do not mechanically close the epics because CI passes. |
| #7 examples / #9 end-to-end | Standalone local SDK-to-capsule journey is now exercised. This is not evidence that platform-generated capsules interoperate. |
| #35 / #39 / #48 / #61 / #62 / #64 | Remaining inspection, test-coverage, archive, and release-tool issues need issue-by-issue disposition. Not all were audited here. |
| #12 / #1 publication | Use current `RELEASING.md`, not #12's obsolete two-workflow checklist. Verify publisher/environment configuration, review URL results, run TestPyPI validation, obtain release review, then tag. No publish was attempted. |
| #2 / #50 platform adoption | Current GitHub main still vendors the builder and has no capsule dependency. Publish the package before an exact-pin migration; revalidate identity/storage, trusted-ID verification, credential errors, and retry handling. |

One concrete remaining spec/implementation difference: spec §5 requires string
mapping keys, while the Python API preserves legacy typed-key conversion.
The new collision guard prevents value loss but does not remove that permissive
behavior. Resolve the reader compatibility policy before claiming complete
conformance. The new vectors explicitly avoid certifying that extension.

GitHub main for the platform pins SDK 0.5.1; the August migration note's 0.4.0/
0.4.1 discussion is stale. The current SDK declares no capsule dependency.
Neither sibling repository was modified, and no production deployment state
was inferred from these source checks.

## Conference claim and next boundary

The demonstrated claim is: “This archive preserves the files from an SDK
experiment, and a recipient can verify that they match a trusted capsule ID.”
It does not establish QPU provenance, signer identity, scientific correctness,
or statistical replication. A fresh seal includes new timestamps and can have
a different ID; deterministic packing applies to the same sealed directory.

Next review the local change, finish the release-gate dispositions above, and
run the release workflow's preflight. The platform integration needs its own
reviewable change and end-to-end proof before it joins the conference release.

## Follow-up hardening in PR #74

The first commit passed remote CI on Python 3.10/3.11/3.12, minimum dependencies,
base install, and wheel smoke. The follow-up addresses two more readiness gaps:

- #35: `inspect` escapes non-printable metadata, including terminal escape
  sequences, forged newlines, and bidirectional controls. Readable Unicode is
  preserved, and JSON mode round-trips the original values.
- #39: optional numerical dependencies are checked only by the individual tests
  that need them. Eleven previously hidden checksum, deterministic-verification,
  traversal, symlink, and early statistical-return tests now run on base installs.

Follow-up validation: 312 full-suite tests passed; a NumPy-free environment
against the updated source ran 287 tests with 25 individual skips. The increase
in reported skips reflects previously invisible tests now being collected,
not a loss of coverage. Eight new inspect regressions account for the other
increase in base-install passes. Remote CI must also pass on the final commit.
