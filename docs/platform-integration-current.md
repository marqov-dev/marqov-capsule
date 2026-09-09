# Platform capsule integration: current evidence

Audited locally on 2026-09-09 against platform checkout
`3cb28c9b0bdde9500ffca0d0f64bf17b67bdeba3`. The builder and worker had no local
changes. This is source and synthetic-fixture evidence, not a production audit.
The platform checkout contains unrelated ongoing work and was not modified.

## Conference disposition

The standalone SDK export → capsule → trusted-ID verification demonstration
works. Platform-produced capsules are a different legacy format despite also
declaring manifest version `1.0.0`. Do not present a platform download as a
standalone-compatible capsule until its actual delivery path passes integration
tests. Replacing the import alone cannot implement this migration.

## Reproduced boundary

The fixture in `tests/fixtures/platform-legacy/` was produced by the actual
vendored builder using the worker's creation sequence and synthetic Bell data.
Its provenance is recorded in `tests/fixtures/platform-legacy.md`.

| Check | Observed result |
|---|---|
| Legacy YAML checksums, including `capsule.yaml` | Pass in the standalone compatibility reader |
| Full standalone integrity | Fail: manifest has no `checksums_digest` |
| Current manifest schema | Fail: requirements, task status/result type, structured backend and checksum digest are absent or incompatible |
| Rewrite manifest and regenerate its legacy checksum | File checksums pass; full integrity still fails |
| Explicit new standard record from the synthetic result | Same result bytes, valid schema, new trusted content ID, full integrity passes |

The passing reconstruction test uses explicit synthetic gate-based requirements,
provider identity and success status. It is not an automatic converter for
arbitrary platform jobs and does not establish historical authenticity.

## Required platform changes

1. **Separate storage identity from content identity.** In
   `create_capsule_from_job`, `capsule_id` comes from the inserted record's `id`
   and is used for the storage prefix. It is a database identity, not the
   standalone content address. Add a trusted content-ID/format record for newly
   sealed artifacts. The old design's mandatory storage-key rebase is not
   established by this path; preserving existing keys is a design to evaluate.
2. **Map the job contract explicitly.** Supply requirements, UUID task ID,
   status, result type, and backend provider/name/shots. Probabilistic tasks
   require declared verification settings. Derive these from authoritative
   job/backend metadata, including annealing/classical cases; handle missing
   data explicitly rather than guessing from a backend label.
3. **Write payloads before sealing.** Replace the worker's old seal → manifest
   → results → checksum sequence with payload preparation → `seal(directory)`
   → persist returned content ID. Use `from_manifest` only for valid drafts;
   do not assign private builder fields to bypass lifecycle guards. Test retries
   after sealing, upload, and persistence failures.
4. **Consume full verification.** `_handle_capsule_verify` currently invokes
   only `verify_checksums` before optional comparison. Call
   `verify_integrity(..., expected_id=trusted_content_id)` and consume failure
   and `manifest_authenticated`. The existing database UUID cannot substitute
   for a trusted content ID; request-supplied IDs need a separate trust contract.
5. **Retire legacy verdicts.** `_handle_capsule_verify` and
   `run_verification_comparison` call legacy APIs. Decide their user-visible
   disposition and update persisted verdict consumers together. Do not turn
   missing support into a successful reproducibility verdict.
6. **Handle scanner failures.** The new seal can raise `RedactorError`.
   Preserve completed job results and report capsule creation failure
   separately. Test that incomplete records are never advertised as sealed.
7. **Publish, pin, and test the whole path.** Run platform creation,
   upload/download, retry and verification tests against the chosen wheel.
   Include altered results/manifest, absent trusted ID, legacy records, and
   scanner rejection. Library fixtures cannot replace these integration tests.

## Legacy records

Do not infer checksum format solely from manifest `version`: both formats use
`1.0.0`. Identify legacy records explicitly. Preserve original bytes and storage
identity and state their verification capability honestly. Any new standard
record gets a new content ID and an explicit legacy-source reference, without
claiming that a newly computed digest authenticates historical evidence.
Inventory and rollout decisions still require platform-owned data access.

## Local checks

Run `python -m pytest tests/test_platform_compatibility.py -q`. The tests need
only the standalone base package and pytest, with no sibling checkout, worker
import or network access. No production records or releases were changed.
