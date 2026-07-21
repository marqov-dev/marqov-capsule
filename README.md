# marqov-capsule

Open standard and tooling for reproducible quantum experiments.

## What is a capsule?

A capsule is a sealed, tamper-evident record of a quantum computation. It contains a `capsule.yaml` manifest, a `.checksums` file listing SHA-256 digests of every payload file, and the payload files themselves (results, circuits, environment specs, etc.). Once sealed, the manifest embeds a `checksums_digest` and a capsule ID (SHA-256 of canonical JSON of the manifest), making the record immutable and cryptographically verifiable.

The format is an open standard (`spec/v1/`, CC-BY-4.0). The Python tooling is Apache 2.0. Both can be used independently.

## Install

```bash
pip install marqov-capsule                  # build, seal, validate, inspect
pip install "marqov-capsule[verify]"        # adds numpy + scipy for statistical verification
```

Requires Python 3.9+.

## Quick start

```python
import tempfile
from pathlib import Path
from marqov_capsule import CapsuleBuilder

with tempfile.TemporaryDirectory() as tmp:
    capsule_dir = Path(tmp)

    # Write a result payload before sealing
    (capsule_dir / "results.json").write_text('{"00": 512, "11": 488}')

    builder = CapsuleBuilder()
    builder.start_capsule(
        name="bell-state-v1",
        description="Two-qubit Bell state on IBM Brisbane",
        requirements={"paradigm": ["gate-based"], "max_qubit_count": 2},
        created_by="alice@example.com",
    )

    capsule_id = builder.seal(capsule_dir, sealed_by="alice@example.com")
    print(f"Capsule ID: {capsule_id}")
    # → Capsule ID: e3b0c44298fc1c149af... (64 hex chars)
```

`seal()` runs the full sealing sequence: credential scan, `.checksums` generation, lifecycle transition to `sealed`, and `capsule.yaml` write. It returns the 64-character hex capsule ID.

## CLI

The `marqov-capsule` command provides six subcommands:

| Command | Description |
|---|---|
| `marqov-capsule init` | Scaffold a new draft `capsule.yaml` in the current directory |
| `marqov-capsule seal` | Seal a draft capsule — scans for credentials, writes checksums, transitions state |
| `marqov-capsule verify` | Verify integrity of a sealed capsule (checksum validation + optional statistical equivalence) |
| `marqov-capsule inspect` | Print a human-readable summary of capsule metadata |
| `marqov-capsule open` | Verify checksums and extract a capsule to a destination directory |
| `marqov-capsule validate` | Validate a capsule against the JSON Schema without sealing — accepts a capsule directory or a `capsule.yaml` path |

```bash
marqov-capsule init --name bell-state-v1 --paradigm gate-based --qubits 2
marqov-capsule seal .
marqov-capsule validate .
marqov-capsule inspect .
marqov-capsule verify . --against /path/to/reference-capsule
```

## Lifecycle

A capsule moves through four states:

| State | Meaning |
|---|---|
| `draft` | Being assembled; manifest may change |
| `runnable` | Ready to execute on a QPU; requirements locked |
| `sealed` | Execution complete; immutable; `checksums_digest` embedded |
| `archived` | Long-term storage; no further modification |

Once sealed, the capsule ID is stable. Any modification to payload files or manifest fields invalidates the digest chain.

## Reproducibility and statistical verification

QPU results are inherently probabilistic — running the same circuit twice produces different shot distributions. The package handles this using bootstrap confidence intervals on total variation distance (TVD):

- **TVD** measures how far apart two probability distributions are (0 = identical, 1 = disjoint).
- A bootstrap CI is computed with 9999 resamples at 95% confidence, using a fixed normative seed (12345) so the same capsule pair always yields the same verdict.
- **Verdict**: `VERIFIED` (CI upper bound below threshold), `REJECTED` (CI lower bound above threshold), or `INCONCLUSIVE`.

Statistical verification requires the `[verify]` extra:

```bash
pip install "marqov-capsule[verify]"
marqov-capsule verify . --against /path/to/reference-capsule
```

## Spec

The normative capsule format specification lives in `spec/v1/`:

- `spec/v1/README.md` — format overview, digest scheme, lifecycle rules, verification protocol
- `spec/v1/capsule-schema.json` — JSON Schema 2020-12 for `capsule.yaml`
- `spec/v1/CHANGELOG.md` — version history

The schema is bundled into the Python package and used for validation at runtime. The spec is licensed CC-BY-4.0 so it can be cited in papers and implemented independently.

## License

This repository contains two separately licensed components:

| Component | License | Reason |
|---|---|---|
| `spec/v1/` | [CC-BY-4.0](LICENSE-SPEC) | The spec is a citable artifact — CC-BY allows citation in academic work and independent implementations without copyleft restrictions |
| Python package (`src/`) | [Apache 2.0](LICENSE-CODE) | Permissive license suitable for use in commercial and research software without viral conditions |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, the RFC evolution process for spec changes, and license terms.
