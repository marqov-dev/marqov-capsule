# Spec: finish #112 (schema strictness)

Status: reviewed, awaiting David's decision, 2026-10-30, against `origin/main`.

## Already done on main

- `max_qubit_count` minimum is 0, matching the spec prose.
- The sealed-field requirement also applies to `archived` manifests.
- `seal_notes` is declared.

## Still open

1. Unknown keys validate at the root, so `derived_From` silently loses provenance.
   A typo of a required key, such as `lifecycle_State` alone, already fails.
2. `task_executions.items`, `backend` and `verification_settings` accept unknown keys.
3. A sealed manifest with no `created_at` validates.
4. No test checks the README's enum and range tables against the schema.
5. A `runnable` manifest with no `requirements` validates, contradicting the README.
6. The reviewer also reported unconstrained `metrics` keys and a negative `min_shots`.

## Proposal

- **Keep unknown keys legal in v1.** Tightening needs the RFC process in
  CONTRIBUTING.md, and `version` cannot separate old capsules from new ones.
- **Warn at seal** on unknown keys, while a typo can still be fixed. `validate` has
  no warnings channel, so seal is the place.
- **Document** unknown-key tolerance and `extensions` in the spec.
- **Keep `created_at` optional in v1**, and stamp it in `init`, which never writes it.
- **Add the consistency test** from item 4.
- **Decide item 5 separately.** It is a schema tightening, so it follows the RFC
  process unless the README is corrected to match the schema instead.

## Evidence

Independent review, with the main claims reproduced by hand:

- Closing unknown keys: 0 new failures across 1,389 tests, conformance and writers.
- Requiring `created_at`: 58 new failures, including 3 of 4 sealed conformance
  fixtures whose golden IDs are pinned.
- `verify` and `open` never run the schema, so tightening would not break them.
  `validate`, `tools/export_completeness/check.py` and spec §7 readers would reject
  old capsules that carry unknown keys.
- Unknown keys are covered by the capsule ID, so tolerance leaves no integrity gap.

## Not verified

- The current platform writer. The local checkout predates the un-vendor.
- Capsules already in the wild.
