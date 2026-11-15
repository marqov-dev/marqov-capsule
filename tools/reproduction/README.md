# Bounded Bell reproduction

This opt-in local macOS pilot replays the existing Bell example using
marqov 0.5.1 and Capsule 0.2.3. It changes no format, SDK executor, hosted
platform, provider behavior or existing implementation freeze. Python 3.12.16
arm64 is the measured configuration; no other platform is certified.

## Prepare and freeze before simulation

Use a reviewed checkout and an already installed Python interpreter. In an
authorized online preparation step, download the published Capsule 0.2.3 wheel
and use the existing kit tool to collect its complete binary dependency closure:

```sh
python3.12 -m pip download --no-deps --only-binary=:all: \
  --dest bootstrap marqov-capsule==0.2.3
python3.12 -B tools/prepare_conference_kit.py \
  bootstrap/marqov_capsule-0.2.3-py3-none-any.whl /absolute/new-kit
python3.12 -I -B tools/reproduction/freeze_bell_kit.py \
  --kit /absolute/new-kit --source-ref REVIEWED_COMMIT
```

The freeze helper supplies the fixed experiment and analytic reference, copies
reviewed replay/oracle sources, and hashes every kit file and the resolved
interpreter. It refuses to overwrite an existing freeze. Save the printed SHA-256
**outside the kit** in a trusted run receipt before looking at any result. The
`source-ref` is an operator-supplied provenance label, not authenticated metadata.
The prep tool's older SHA256SUMS is superseded by freeze.json. Wheels retain their
own licenses; keep them with the kit. The kit is host/Python-specific.

Use the **trusted checkout's launcher**, rather than execute an untrusted kit's
launcher to verify itself. No trusted hash authenticates the code that consumes
it. Keep checkout sources and kit stable during execution: this pilot does not
provide a filesystem snapshot or adversarial concurrent-write protection.

## Replay offline

The two paths must be disjoint; use a new evidence directory. Every execution
stage runs through macOS sandbox-exec denying network access. The launcher tests
that policy with a literal-address TCP probe requiring EPERM. Dependency installs
use --no-index and --require-hashes, with two newly created venvs, a temporary
empty HOME and minimal credential-free environment.

```sh
python3.12 -I -B tools/reproduction/run_bell_reproduction.py \
  --kit /absolute/new-kit --evidence /absolute/new-evidence \
  --expected-freeze-sha256 DIGEST_FROM_TRUSTED_RECEIPT
```

Each run executes H(0), CNOT(0,1), 1,000 shots and seed 42 in a fresh process.
The standard-library oracle requires the exact circuit/metadata and integer
nonnegative counts, zero 01/10 outcomes and 420–580 counts of 00. This fixed
±80 interval has ideal Bernoulli Hoeffding false-alarm bound at most
2 exp(-12.8), approximately 5.52e-6. It checks the computational distribution;
it cannot distinguish coherent Bell preparation from an incoherent mixture.
Exact normalized counts equality additionally checks replay of the frozen seed.
These correlated reruns are not independent statistical replication and must not
be submitted to Capsule's independent two-sample verifier as if they were.

The existing seal script checks schema, trusted-ID verification after unpacking,
byte-identical repeated packing of each single sealed record and rejection of
payload/manifest tampering. New seals need not have identical timestamps or IDs.
Integrity and analytic correctness remain separate acceptance checks.

## Negative controls and evidence

Remove reference.json from a **separate copied kit**, retaining its original
freeze and external digest. The same launcher must exit 1 at preflight, name
MISSING_REQUIRED_INPUT:reference.json and record zero simulator invocations.
Do not repair the inventory after removing the file. A deliberately constructed
all-00 result must fail ANALYTIC_MISMATCH, even if sealed consistently. Keep these
synthetic controls separate from actual simulator outputs. Regression tests also
cover external-trust replacement, injected files (including nested freeze.json),
symlinks, numeric type confusion, watchdog caps and existing-directory refusal.

The watchdog samples process-group RSS every 0.2s, stops above 4GiB, caps run-tree
disk at 5GiB and exported evidence at 2GiB, checks final disk use even for short
stages, and bounds stages (60s; installation 300s) and total replay (900s).
It kills surviving members of the stage's process group. This is trusted-code
execution, not hostile-code isolation: a process that deliberately escapes its
group is outside that watchdog's guarantee. The standard-library supervisor
remains outside the network sandbox so macOS permits RSS inspection. The source
of the oracle is trusted; no simulator imports run in the supervisor.

RSS/disk caps are sampled limits, not kernel allocation quotas; brief peaks may
be missed. Two-thread environment settings are advisory, not CPU affinity.
Use /usr/bin/time -l around the launcher for additional OS measurements. No GPU
or cloud acceleration is required. Failures stop with logs and a report; no
automatic tolerance, dependency or provider substitutions occur.

Retain raw exports, external trusted IDs and freeze digest, package/import
manifests, source hashes, all logs/receipts, tests, explicit limitations and a
hash-verified backup. A second copy on the same SSD is not disaster recovery.
See `evidence/2026-11-14-bell-pilot/` for the dated PR evidence and historical
November 13 results. Local success does not establish hosted acceptance.
