# marqov-capsule

A standalone format for packaging reproducible quantum-classical workflows.

## What is a Capsule?

A capsule is a sealed, tamper-evident record of a computational workflow and its results. It captures everything needed to verify that a computation happened correctly and can be reproduced: input parameters, execution metadata, output digests, environment details, and cost tracking.

Capsules follow a lifecycle:

1. **Draft** — created with `capsule init` or `CapsuleBuilder`. Parameters and task executions are recorded.
2. **Sealed** — finalized with `capsule seal` or `seal_capsule()`. Cryptographic digests are computed, the Python environment is locked, and a `.checksums` manifest is generated. Once sealed, a capsule is immutable.
3. **Verified** — checked with `capsule verify` or `CapsuleVerifier`. Checksums detect tampering, digests confirm integrity, and statistical tests can compare results across runs.

### What goes in a capsule

- `capsule.yaml` — the manifest: name, provenance, execution details, digests, cost
- `environment.lock.yaml` — locked Python package versions at seal time
- `.checksums` — SHA256 manifest of all files in the capsule directory
- Referenced files: `workflow.yaml`, `environment.yaml`, `backends.yaml`

### Reproducibility tiers

Not all computations are deterministic. Capsules declare their expected reproducibility level:

- **deterministic** — simulators with controlled randomness. Exact digest matching.
- **statistical** — real QPU results. Verified via Kolmogorov-Smirnov, chi-squared, and energy tolerance tests.
- **verification-only** — metadata integrity checks only. For workflows where re-execution isn't possible.

## Install

```bash
pip install marqov-capsule                # core: build, seal, verify
pip install marqov-capsule[verify]        # + statistical verification (numpy, scipy)
pip install marqov-capsule[validate]      # + schema validation (jsonschema)
```

Or from the private repo:

```bash
pip install git+ssh://git@github.com/marqov-dev/marqov-capsule.git
```

## CLI

```bash
capsule init my-analysis                  # scaffold a new capsule directory
capsule seal my-analysis.capsule/         # seal it (locks environment, generates checksums)
capsule verify my-analysis.capsule/       # verify integrity and checksums
capsule pack my-analysis.capsule/         # pack into a single-file archive
capsule unpack my-analysis.capsule        # extract archive to directory
capsule verify my-analysis.capsule        # verify works on archives too
```

All commands support `--json` for structured output in CI pipelines.

### Archives

A `.capsule` file is a deterministic gzipped tarball. Packing the same directory twice always produces byte-identical archives. This enables content addressing: each capsule gets a permanent ID (SHA256 of the `.checksums` file) regardless of filename.

```bash
capsule pack my-analysis.capsule/ --json
# {"path": "my-analysis.capsule", "content_id": "sha256:abc123..."}
```

## Python API

```python
from marqov_capsule import CapsuleBuilder, CapsuleVerifier

# Build
builder = CapsuleBuilder(
    "my-analysis",
    description="Surface code weight enumerator analysis",
    reproducibility_tier="deterministic",
    creator_version="my-tool-1.0",
)
builder.start_capsule(parameters={"distance": 3})
builder.add_task_execution(
    task_id="main",
    backend="local",
    outputs={"wep": {0: 1, 2: 4, 4: 22, 6: 100, 8: 129}},
)
builder.add_result_digest(
    data={"wep": {0: 1, 2: 4, 4: 22, 6: 100, 8: 129}},
    digest_name="weight_enumerator",
)

# Seal (locks environment, computes all digests)
sealed = builder.seal_capsule(exit_code=0)

# Save (writes capsule.yaml, environment.lock.yaml, .checksums)
builder.save_capsule("my-analysis.capsule/capsule.yaml")

# Verify
verifier = CapsuleVerifier()
capsule = verifier.load_capsule("my-analysis.capsule/capsule.yaml")
result = verifier.verify_capsule(capsule)
print(result["verification_passed"])  # True

# Check for tampering
checksum_result = verifier.verify_checksums("my-analysis.capsule/")
print(checksum_result["passed"])  # True

# Pack into a single-file archive
from marqov_capsule import pack_capsule, unpack_capsule, content_id

archive = pack_capsule("my-analysis.capsule/")  # deterministic gzipped tarball
cid = content_id(archive)                        # sha256:... permanent ID
restored = unpack_capsule(archive, output_dir="./restored/")
```

## Schema

Capsules are validated against a JSON Schema (`v1`). The schema supports forward-compatible minor versions (v1.1, v1.2) and rejects breaking major versions (v2.x) with clear error messages.

The `capsule_format_version` field tracks which version of marqov-capsule created the capsule. An optional `creator_version` field tracks the upstream tool version (e.g., the Marqov platform version).

## Architecture

The package is designed with tiered dependencies:

| Install | Gets you | Dependencies |
|---------|----------|-------------|
| `marqov-capsule` | Build, seal, verify (deterministic) | pyyaml |
| `[verify]` | Statistical verification (KS, chi-squared) | + numpy, scipy |
| `[validate]` | JSON Schema validation | + jsonschema |

All digests are deterministic and content-derived (SHA256). No randomness, no timestamps in digest inputs.
