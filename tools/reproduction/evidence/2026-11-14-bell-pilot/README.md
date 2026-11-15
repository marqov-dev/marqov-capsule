# Bell pilot review evidence — 14 November 2026

The reviewed launcher completed two actual local SDK simulator runs, in fresh
venvs with the same 78 hash-pinned wheels used on 13 November. Each produced
`00:503, 11:497` from 1,000 shots/seed 42, passed the independent analytic
oracle, and passed the original Capsule round-trip/tampering checks. The reviewed
run took **57.77s**, with OS-reported maximum RSS **249,102,336 bytes (237.6MiB)**
and maximum measured run-tree size **1,251,747,599 bytes (1.17GiB)**.

The hardware inventory is a Mac Studio/M5 Max/64GB, arm64, macOS 27.2.1 build
26B131 with CPython 3.12.16. GPU use was neither required nor benchmarked.

## Review findings fixed

- The launcher now requires the separately retained trusted freeze digest; a
  rewritten self-consistent inventory cannot replace the external trust anchor.
  Launch it from a trusted checkout, not from an untrusted kit verifying itself.
- Final time/disk checks catch short-lived children that exit between polls.
- Nested unlisted freeze.json files and symlinks fail preflight; overlapping
  kit/evidence paths are refused.
- The oracle distinguishes integer circuit/reference values from bool/float
  values that Python equality would otherwise accept.
- The offline freeze helper and operator runbook make kit preparation repeatable.

The scientific oracle, interval [420,580], seed, shots, two-qubit circuit and
78 wheel bytes were fixed before the rerun; no acceptance criterion was widened.
The November 13 originals were preserved unchanged. Their 52-test result,
52.92s runtime and pre-simulation /bin/ps failure are historical, separately
labelled evidence, not this review's current figures. Across both dates there
were four actual simulator calls; deliberate negative controls are not extra
scientific observations or platform traces.

## Validation

- Full CPython 3.12.16 suite: **1,541 passed, 3 skipped**, 2 existing Click
  deprecation warnings. Skips: two installed-only CLI consumer checks, plus an
  NFC/NFD collision check which this macOS filesystem aliases. No skip is
  represented as a pass; installed CLI/release acceptance remains distinct.
- Reproduction regressions: **48 passed**, 199/209 executable statements
  covered (95.2%); 93% combined statement/branch coverage.
- Ruff 0.14.0: repository lint and formatting passed. Mypy 1.18.2:
  22 source files passed. Source has no changes under src/ relative to the
  reviewed main d74aadcaf1f20992c446764f45fd38b09df7427d.
- Negative control: missing reference.json failed at preflight with zero
  simulator calls. A consistently sealed all-00 result passed integrity yet
  failed ANALYTIC_MISMATCH. Payload/manifest mutations failed in both runs.

## Evidence map and provenance

`summary.json`, `replay-report.json`, both results, circuit, both Capsule
verification reports, and the two negative-control reports carry the observed
outcomes. `stage-receipts.json` retains measurements/exit status with local
command paths omitted. `freeze.json`, `requirements.txt` and `source-hashes.json`
pin all kit bytes, interpreter and reviewed code; `SHA256SUMS` covers this
published evidence directory. An operator-supplied local commit label is not
itself an authenticated source attestation; use the source file hashes to match
this PR's runtime sources.

Trusted freeze SHA-256 recorded before rerun:
`efdbbee517834a4d60da175209266b05aa0144de2f5f74b1e9e8a48e83e34b21`.
The raw wheel kit, full machine-specific logs/install manifests, archives and
local backup remain in the originating chat's retained outputs/work directories.
Their November 13 archive receipts are retained locally; this PR publishes the
small reviewable results/hash receipts rather than dependency binaries or machine
identifiers. The original November 13 freeze digest is in the historical summary.
No credentials, hardware serials/UUIDs or user-home paths are included here.

## Limits and freezes

This measures the Bell computational-basis distribution and repeatability of one
frozen seed. It does not prove Bell-state coherence or independent statistical
replication; the two-sample statistical verifier is deliberately not used.
The RSS/disk watchdog is sampled, thread settings are advisory, and only
members of the stage process group are cleaned up; this is not hostile-code
containment. Sources/kit must remain stable during the run. Every executed stage
is network-denied; the trusted standard-library supervisor stays outside the
sandbox to inspect process-group RSS.

A hash-verified copy/restore on the same SSD is not off-machine disaster recovery.
No paid/model/QPU/provider execution, platform deployment, training, recurring job
or freeze lift occurred. Local results do not establish hosted Capsule, Linux,
release or partner acceptance. Platform#3273 remains in review pending this PR;
the Studio epic remains open for its other operating milestones.
