# Migrating from the pre-release verifier API

The first public release does not support the old capsule-level verdict APIs.
Their names remain as migration guards that raise `NotImplementedError`, so a
caller gets an explanation instead of a missing-method error or a false pass.

| Retired call | Why | Supported direction |
|---|---|---|
| `verify_capsule(...)` | Metadata/digest claims could pass without inspecting files; statistical mode could pass after running no tests and used non-rejection as evidence of equivalence | Choose file integrity, explicit deterministic result comparison, or count equivalence below |
| `compare_capsules(...)` | `overall_consistent` depended only on equal manifest names; method/tolerance did not control a result comparison | Verify both artifacts and then compare their selected result payloads |
| `check_calibration_drift(...)` | Missing fidelities defaulted to zero and could produce a successful comparison | No replacement verdict API; validate actual calibration measurements and apply an explicit domain policy |

The old private statistical helpers and tier-dispatch implementation are removed.
This is an intentional pre-release API retirement, not a format change: existing
capsule IDs, archives, schema, and the supported CLI commands are unchanged.

## File integrity

```python
from marqov_capsule import CapsuleVerifier

report = CapsuleVerifier.verify_integrity(
    capsule_directory,
    expected_id=trusted_capsule_id,
)
if report["status"] != "pass" or not report["manifest_authenticated"]:
    raise ValueError("Capsule does not match the trusted ID")
```

Obtain the trusted ID independently of the untrusted artifact. A manifest loaded
with `load_capsule(path)` is only parsed: that helper now uses the capsule YAML
profile and rejects duplicate keys/non-mapping documents. It does not validate
the schema, hash files, or authenticate the manifest.

## Explicit result comparison

For deterministic JSON-compatible results, use
`CapsuleVerifier.verify_deterministic(reference_result, candidate_result)` and
read its `verdict` (`VERIFIED` or `REJECTED`). This compares the supplied data;
it does not verify the files from which the caller obtained it.

For independent count samples, use the supported one-sided bound:

```python
from marqov_capsule import CapsuleVerifier
from marqov_capsule.policy import VerificationPolicy

policy = VerificationPolicy(epsilon=0.02, min_shots=100, alpha=0.05)
settings = policy.resolve(declared_settings)
report = CapsuleVerifier().verify_statistical(
    reference_counts, candidate_counts, settings,
)
equivalence_demonstrated = report["verdict"] == "VERIFIED"
```

The policy belongs to the verifier. Untrusted capsule settings must pass through
`resolve`; the low-level API takes already-resolved settings. Statistical
verification requires NumPy/SciPy and returns `VERIFIED` or `INCONCLUSIVE`.
Do not translate `INCONCLUSIVE` into proof of difference or use a p-value to
override it. The sampling assumptions and decision procedure are in spec §6.
The `calibration_drift` tolerance regime does not inspect calibration data.

## Platform integration

The platform currently uses its own vendored verifier. Retiring these methods
in this package does not patch that copy. An eventual un-vendor change must
replace its call sites with explicit supported operations and make the trusted
ID and policy ownership visible. A mechanical import swap is insufficient.
