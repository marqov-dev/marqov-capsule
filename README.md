# marqov-capsule

Open standard and tooling for reproducible quantum experiments.

## What is a capsule?

A capsule is a sealed, tamper-evident record of a quantum computation. It contains a `capsule.yaml` manifest, a `.checksums` file listing SHA-256 digests of every payload file, and the payload files themselves (results, circuits, environment specs, etc.). Once sealed, the manifest embeds a `checksums_digest` and a capsule ID (SHA-256 of canonical JSON of the manifest), making the record immutable and cryptographically verifiable.

The format is an open standard (`spec/v1/`, CC-BY-4.0). The Python tooling is Apache 2.0. Both can be used independently.

## Install

```bash
pip install marqov-capsule
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
| `marqov-capsule verify` | Verify integrity of a sealed capsule — all three digest-chain layers, `--id` for the trusted capsule ID |
| `marqov-capsule inspect` | Print a human-readable summary of capsule metadata |
| `marqov-capsule open` | Verify integrity and extract a capsule to a destination directory |
| `marqov-capsule validate` | Validate a capsule against the JSON Schema without sealing — accepts a capsule directory or a `capsule.yaml` path |

```bash
marqov-capsule init --name bell-state-v1 --paradigm gate-based --qubits 2
marqov-capsule seal .
marqov-capsule validate .
marqov-capsule inspect .
marqov-capsule verify .
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

## Integrity verification

`verify` and `open` check all three layers of the digest chain (spec §6):

1. Each payload file is hashed and compared against `.checksums`, which pins a **closed set** — a file present on disk but absent from `.checksums` is an injected file and fails verification.
2. `.checksums` is hashed and compared against `checksums_digest` in the manifest. This is what makes the capsule tamper-*evident*: editing a payload and re-running `save_checksums` satisfies layer 1, but the manifest still pins the original `.checksums` bytes.
3. The capsule ID is recomputed from the canonical JSON of the manifest and compared against a trusted ID you supply.

```bash
marqov-capsule seal .                 # prints: Sealed: <capsule-id>
marqov-capsule verify . --id <capsule-id>
```

Record the capsule ID at seal time and distribute it out of band. Without `--id` the first two layers still run, but the manifest itself is **unauthenticated** — `capsule.yaml` is deliberately outside `.checksums` (it contains the digest of `.checksums`), so only the capsule ID pins it. `verify` says so explicitly rather than reporting a bare pass.

Note the limit: the digest chain detects modification, not forgery. Anyone who rewrites the payload, `.checksums`, and the manifest together produces a self-consistent capsule with a *different* ID — which is why the trusted ID has to come from somewhere other than the capsule. Capsules carry no signatures, so a capsule ID is only as trustworthy as the channel you received it over.

## Roadmap

**Statistical equivalence testing is not in this release.** Comparing two runs and getting a VERIFIED / REJECTED verdict is the natural companion to sealing, and it is the next thing being built — but the estimator we had was miscalibrated badly enough that a distribution compared *against itself* was rejected from roughly four qubits upward. Shipping it would have meant shipping a verdict that carries no information at realistic problem sizes.

Rather than ship it caveated, it is cut until it is right. The investigation is written up in full, including the four candidate replacements that were measured and rejected and why:

- [`docs/research/2026-08-10-tvd-equivalence-testing.md`](docs/research/2026-08-10-tvd-equivalence-testing.md) — why the plug-in estimator fails, why the bootstrap cannot be repaired for this functional, and the one-sided bound that does work
- Tracked in [#15](https://github.com/marqov-dev/marqov-capsule/issues/15)

Also on the roadmap, with the research already done:

- [#18](https://github.com/marqov-dev/marqov-capsule/issues/18) — credential scanner precision and recall, written up in [`docs/research/2026-08-11-credential-detection.md`](docs/research/2026-08-11-credential-detection.md)
- [#16](https://github.com/marqov-dev/marqov-capsule/issues/16) — capsules carry no signatures, so the digest chain detects modification but not forgery

Contributions welcome on any of these. The research documents are meant to be a starting point rather than a specification — if you disagree with the analysis, the reproduction scripts are in the appendices.

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
