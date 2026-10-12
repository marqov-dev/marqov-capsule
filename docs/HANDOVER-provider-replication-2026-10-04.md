# Handover: provider replication — what a capsule has to carry to rerun an experiment

For the agent working on `marqov-capsule`. Design lesson from a finished PennyLane measurement. Nothing here is implemented in this repo. Do not fold it into the 0.1.x integrity work. It is a spec change for how a capsule names a backend so a later execution can match the sealed result as closely as that backend allows.

Evidence lives in `marqov-research`, branch `research/xanadu-e1-verify` (not merged as of this note):

- `research/xanadu-lab/e1/` — experiment, locked environment, committed runs
- `research/xanadu-lab/e1/out/e1_runs.jsonl` — the 1 October 2026 measurements
- `research/xanadu-lab/e1/out/verify_rerun.json` — 3 October rerun, 42/42
- `research/xanadu-lab/e1/verify_rerun.py` — the check that was actually run

---

## 1. The gap

Spec §1 says a capsule is reproducible: another party can re-execute the same circuit and verify statistical equivalence. What ships is narrower, and the README already says so.

`verify` / `verify_integrity` checks the digest chain (payload bytes, `.checksums`, capsule ID). It does not execute anything. `verify_deterministic` hashes two JSON values the caller already has. `verify_statistical` / `compare` tests two count maps with a one-sided TVD bound. Environment capture is a file the author chose to put in the payload. Sealing does not inspect the host.

`task_executions[].backend` is `provider`, `name`, and `shots` (`spec/v1/README.md` §3, `capsule-schema.json`). `shots` is an integer ≥ 1. `result_type` is `probabilistic` or `deterministic`. There is no seed, no position in a random stream, no compiled-binary hash, and no circuit reference. Extra keys are allowed (`additionalProperties` is open on the manifest, and `backend` does not forbid them), so an author can stuff a seed into the YAML today. Nothing in `verify` reads it.

A capsule sealed from a PennyLane run that records only provider, device name, and shots will `verify` cleanly. A later execution of that circuit will draw different samples. The files did not change. The random stream did.

---

## 2. What was measured

One machine: Apple M5, macOS 26.1 arm64, Python 3.12.12, pennylane 0.45.1, pennylane-lightning 0.45.0, pennylane-lightning-kokkos 0.45.0 (CPU wheels), numpy 2.5.3. Devices: `default.qubit`, `lightning.qubit`, `lightning.kokkos`, and `default.tensor` where it applies. No GPU, no MPI, no Linux, no Catalyst, no second PennyLane version.

Circuit: 3 layers of RY plus a CNOT chain, observable a sum of nearest-neighbour ZZ. Shot comparisons used SHA-256 of the full sample array, stored truncated to 16 hex characters in the lab (see §5). Analytic values and gradients were stored as float hex.

Within one device, an integer seed replays a fresh device's 1000-shot array bit for bit, across processes and across `OMP_NUM_THREADS` in {unset, 1, 4, 10}. On 3 October the same file was rerun in two fresh processes. Bit-identical both times: fresh samples at 6 and 14 qubits on all three shot devices, one 20-qubit `lightning.qubit` sample, 6-qubit shot expectations, analytic expectations (including 20 qubits and `default.tensor`), and 6-qubit gradients (adjoint, backprop, parameter-shift). The installed Python, NumPy, PennyLane, and both Lightning `.so` hashes matched the stored record. The checker refuses to run when they do not.

These cases matched only because the rerun also had facts the capsule manifest does not require:

| Fact | Why a rerun changes without it | Where PennyLane 0.45 keeps it |
|---|---|---|
| Device name, requested and resolved | `default.qubit`, `lightning.qubit`, and `lightning.kokkos` do not share a sample stream. Same seed, 0 of 5 seeds matched, at 6, 14, and 20 qubits, including the two Lightning devices against each other. | `dev.name` |
| Seed and seed kind (`int`, `none`, `unsupported`) | Unseeded draws do not repeat. `default.tensor` rejects `seed=`. | Not on any public device surface. Recoverable only while the object is alive, via a private NumPy path, and only when an integer seed was passed. The caller has to write it down. |
| Call index | Successive calls on one device object advance the RNG. In 60/60 devices per cell the three calls differed; the first call equalled a fresh device with the same seed. Replaying call 0 against a stored call 2 fails. | Not stored. The lab kept it as the position in a `hashes` array on the measurement line. |
| Circuit | The result line does not contain the gates or the parameters. Both rerun passes imported `e1_worker.py`. | Not on the device. |
| Plugin version, wheel tag, binary SHA-256 | A different compiled kernel is a different program. The rerun refuses on a hash mismatch instead of reporting a scientific failure. | Not on the device. `importlib.metadata` and a hash of the `.so`. |
| Precision, `diff_method` | Analytic and gradient paths differ in the last digits across methods and dtypes. | `dev.c_dtype` on Lightning only. Differentiation method is on the qnode. |
| Shot count, wire count | They define the stream and the circuit width. | Shots are on the Tracker and `qml.specs` when set. |

Analytic expectations for this circuit were about −0.27, 0.18, and −3.33 at 6, 14, and 20 qubits. Cross-device gaps were ~1e-15 at 6–14 qubits and 1.257e-13 at 20 qubits (`lightning.qubit` against `default.qubit`). An exact comparison fails. A tolerance of 1e-12 passed for that one value. That tolerance is an observation about this circuit on this build. It is not a constant to put in the spec.

Shot noise at 1000 shots sat between about 0.025 and 0.115 mean absolute deviation (maximum 0.24). That swamps the cross-device float gap. A statistical compare of shot expectations will not notice a device change. A bit-exact compare of the sample array will.

`OMP_NUM_THREADS` did nothing to results or median wall time on these macOS wheels. `otool -L` shows `lightning_qubit_ops` and `lightning_kokkos_ops` linked only to `libc++` and `libSystem`. CPU time over wall time stayed near 1. A Linux build linked to OpenMP is a different contract. Record the variable. Do not treat it as inert for every provider build.

---

## 3. What to change in the design

Keep integrity verification as it is. It answers "did these bytes change?" Replication is a second check. It answers "does this provider still produce this result?" A passing integrity check must not be reported as a successful replication.

Add a replication contract on each task execution. `result_type: probabilistic | deterministic` is the wrong axis. A seeded PennyLane shot run is bit-exact given the record, and it is also a draw from a distribution. Hardware shots are distributional even when the device accepts a seed. Suggested mode, orthogonal to integrity:

| `replication.mode` | When | Verdict |
|---|---|---|
| `bit_exact` | Seeded simulator, seed kind `int`, call index known, circuit and binary pinned | Re-execute and compare full SHA-256 of the sample array, or float hex for analytic values and gradients. |
| `analytic_tolerance` | Same circuit, analytic value, comparison across devices or differentiation methods | Exact match may fail. Compare with a verifier-owned tolerance, the same way `VerificationPolicy` owns `epsilon`. |
| `distributional` | Unseeded simulator, or a QPU | Existing TVD procedure. Bit-exact must not be offered. |
| `refuse` | Binary hash, Python, or library version differs from the record; or `seed_kind` is `none` / `unsupported` while mode is `bit_exact` | Do not report REJECTED. The execution was not the recorded program. |

`refuse` is the behaviour the PennyLane checker already has, and it is the one that keeps a wheel upgrade from looking like a physics failure.

Fields the contract needs, beyond `provider` / `name` / `shots`:

- `seed`, `seed_kind`
- `call_index` — integer ≥ 0. A capsule that builds a fresh device per task is call 0. Three calls on one device object are three executions, or one execution with an explicit index. Omitting the index makes only the first draw replicable.
- `circuit` — a payload path (source, OpenQASM, or a canonical tape). The digest chain already hashes payload bytes. The manifest has to point at the circuit or a replicator will re-run whatever code happens to be on the machine. The PennyLane JSON lines do not contain the circuit.
- `artifact` — package version, wheel tag, SHA-256 of the compiled extension when there is one. Mismatch selects mode `refuse`.
- `precision`, `diff_method` — when the result is an expectation or a gradient.
- `threads` — the environment variable that this build actually honours, recorded even when this particular wheel ignored it.

Schema constraint that fights the data: `backend.shots` is required and `minimum: 1`. Analytic expectations and gradients in this experiment have no shots. Recording them as `shots: 1` would make a replicator sample. Allow shots to be absent when the mode is analytic.

Do not hard-code 1e-12. Put analytic tolerance in verifier policy, beside `epsilon`. The sealed capsule may declare a tighter ceiling. It must not be able to widen the verifier's ceiling. That is the rule §6 already uses for statistical epsilon.

Do not require sample arrays from two devices to match. Same seed, different PennyLane device is a different stream. A replicator that treats that as a failed capsule is wrong. The failure mode to report is "recorded device was `lightning.qubit`, rerun device was `lightning.kokkos`."

Store full SHA-256. The lab truncated sample digests to 16 hex characters (`e1_worker.digest`). Fine for that comparison count. The capsule digest grammar is already `sha256:` plus 64 hex characters. Follow that.

---

## 4. Acceptance tests, taken from the rerun

A PennyLane provider adapter is done when a sealed capsule of this circuit, on a machine whose binary hashes match, does all of the following. The lab script `verify_rerun.py` is the oracle for the expected pattern. The numbers below are from `out/verify_rerun.json`.

Must bit-match, twice, in fresh processes:

- Fresh 1000-shot samples, seed 0, at 6 and 14 qubits, on `default.qubit`, `lightning.qubit`, and `lightning.kokkos`.
- One 20-qubit fresh sample on `lightning.qubit`, seed 0.
- Shot expectation at 6 qubits, seed 0, on those three devices.
- Stream calls 0, 1, and 2 on `lightning.qubit` at 6 and 14 qubits, seed 0. Call 2 on `default.qubit` and on `lightning.kokkos` at 6 qubits.
- Analytic expectations at every size each device ran (no 20-qubit `default.tensor`).
- Gradients at 6 qubits for the methods that device supports.

Must not bit-match, and must say why:

- Same seed, samples compared across devices, including `lightning.qubit` against `lightning.kokkos`.
- Call index dropped: first draw compared with the stored third draw.
- Unseeded samples: two fresh processes match neither each other nor the stored draw. Mode `bit_exact` is illegal here.
- Analytic `lightning.qubit` at 20 qubits against the stored `default.qubit` value. Absolute difference was 1.257e-13. Exact fails. A policy tolerance of 1e-12 passes. Integrity verification of the sealed file still passes in every one of these cases. That split is the point.

Must refuse, not reject:

- Lightning `.so` hash, PennyLane version, or Python version differs from the sealed artifact record.

---

## 5. Limits of the evidence

One circuit family, one parameter set per size, one laptop, CPU wheels only. `lightning.gpu`, `lightning.tensor`, MPI, Catalyst `@qjit`, and a second PennyLane version were not run. The cross-device sample mismatch was observed and not explained. Different samplers are the likely cause. Do not write it into the spec as a defect in Lightning.

`default.qubit` worker processes in the original battery peaked near 4 GB RSS while Lightning stayed under 1 GB. The allocating phase was not isolated. Do not treat that as a capsule requirement.

Thread behaviour is for these macOS arm64 wheels. A Linux OpenMP build, a GPU build, and a `@qjit` program need their own rows in the provider table. For `@qjit`, the compiled artifact (Catalyst version and a hash of the lowered program) is part of `artifact`. Re-executing the Python source alone can be a different program.

PennyLane does not keep the seed or the call index on the device. A capsule adapter has to record them at construction and at each call. Reading them back afterwards is private, version-dependent, and absent for some devices. That is an adapter requirement, not a request that PennyLane store them.

---

## 6. What not to do

- Do not make `verify` re-execute. Integrity has to stay offline and has to stay a byte check.
- Do not report a TVD pass as evidence that a seeded simulator was reproduced. The sample order can differ while the histogram still looks close, and the cross-device float error is invisible next to shot noise.
- Do not report an integrity pass as evidence that the experiment will rerun.
- Do not encode the 1e-12 figure, or this circuit, as a universal analytic tolerance.
- Do not require `shots >= 1` on analytic tasks.
- Do not silently substitute a backend and still seal the requested name. The recorded device and the device that actually ran have to be the same field or an explicit pair. A mismatch is a failed replication, and it is also the bug class already called out for other Marqov backends.
