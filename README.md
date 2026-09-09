# marqov-capsule

Open standard and tooling for reproducible quantum experiments.

## What is a capsule?

A capsule is a sealed, tamper-evident record of a quantum computation. It contains a `capsule.yaml` manifest, a `.checksums` file listing SHA-256 digests of every payload file, and the payload files themselves (results, circuits, environment specs, etc.). Once sealed, the manifest embeds a `checksums_digest` and a capsule ID (SHA-256 of canonical JSON of the manifest). The capsule ID is derived from the content, so it names those exact bytes and nothing else — altering a capsule does not change it, it produces a different capsule. Capsules carry no signatures, so this makes them **tamper-evident**, not authenticated: the digest chain detects modification, not forgery.

The format is an open standard (`spec/v1/`, CC-BY-4.0). The Python tooling is Apache 2.0. Both can be used independently.

## Install

```bash
git clone https://github.com/marqov-dev/marqov-capsule.git
cd marqov-capsule
python -m pip install .
```

The first PyPI release is pending; install from source for now. Requires Python 3.10+.

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
    # → Capsule ID: mqc:1:<64 lowercase hex chars>, derived from the manifest contents
```

`seal()` runs the full sealing sequence: credential scan, `.checksums` generation, lifecycle transition to `sealed`, and `capsule.yaml` write. It returns a versioned capsule ID: `mqc:1:<64 lowercase hex chars>`.

## Runnable SDK demonstration

The [Bell-state example](https://github.com/marqov-dev/marqov-capsule/tree/main/examples) runs the Marqov SDK local simulator, seals its result and circuit, verifies an archive round-trip against a trusted ID, and demonstrates detection of changed payloads and metadata. It needs Python 3.12+ for the SDK, with no provider credentials.

## CLI

The `marqov-capsule` command provides these subcommands:

| Command | Description |
|---|---|
| `marqov-capsule init` | Scaffold a new draft `capsule.yaml` in `DIRECTORY` |
| `marqov-capsule seal` | Seal a draft capsule — scans for credentials, writes checksums, transitions state |
| `marqov-capsule verify` | Verify integrity of a sealed capsule directory **or archive** — all three digest-chain layers, `--id` for the trusted capsule ID |
| `marqov-capsule inspect` | Print a human-readable summary of capsule metadata |
| `marqov-capsule open` | Verify integrity and extract a capsule to a destination directory |
| `marqov-capsule pack` | Pack a sealed capsule directory into a deterministic `.capsule` archive |
| `marqov-capsule unpack` | Restore a capsule directory from an archive |
| `marqov-capsule validate` | Validate a capsule against the JSON Schema without sealing — accepts a capsule directory or a `capsule.yaml` path |

```bash
marqov-capsule init ./bell-state --name bell-state-v1 --paradigm gate-based --qubits 2
# add your payload files to ./bell-state, then:
marqov-capsule seal ./bell-state
marqov-capsule validate ./bell-state
marqov-capsule inspect ./bell-state
marqov-capsule verify ./bell-state
```

Payload files can be laid out however you like — the spec treats any file that
isn't `capsule.yaml` or `.checksums` as payload. The conformance fixtures use
`payload/`, `source/` and `environment/` subdirectories as a convention, but
nothing enforces it.

## Archive format

A sealed capsule packs into a single `.capsule` file — a **deterministic** gzipped tarball. Packing the same capsule twice produces byte-identical output, achieved by sorting members, zeroing entry and gzip timestamps, and fixing permissions.

```bash
marqov-capsule pack ./bell-state -o bell-state.capsule
marqov-capsule verify bell-state.capsule        # verifies without unpacking first
marqov-capsule unpack bell-state.capsule -o ./restored
```

`verify` accepts a directory or an archive interchangeably.

Two different digests are reported, and the distinction matters:

| | Covers | Use it for |
|---|---|---|
| **Capsule ID** | the manifest, which pins `checksums_digest`, which pins every payload byte | **identity** — this is the content address |
| **Payload digest** | only the files listed in `.checksums` | checking the payload set |

`.checksums` deliberately excludes `capsule.yaml`, so two capsules with identical payloads but different manifests — different name, different `sealed_by`, different backend claims — share a payload digest. Only the capsule ID distinguishes them. Name capsules by their capsule ID.

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

**Statistical equivalence testing has no CLI in this release.** Comparing two runs and getting a verdict is the natural companion to sealing. The estimator behind it was miscalibrated badly enough that a distribution compared *against itself* was rejected as non-reproducible from roughly four qubits upward — that's now fixed: `CapsuleVerifier.verify_statistical` uses a closed-form one-sided confidence bound instead of the broken bootstrap, and reports `VERIFIED` / `INCONCLUSIVE`, with no affirmative `REJECTED`. A lower bound on true TVD does exist (triangle inequality: plug-in estimate minus McDiarmid slack minus a one-sample bias term per arm), but it isn't deployed — it depends on the outcome count `K`, and taking `K` from observed support rather than the declared register width fails open, a problem the upper bound's `K`-free slack doesn't share. The one candidate detection tool (a permutation test against the sharp null) measured power as low as 42% at K=256, too weak to carry an affirmative verdict on its own. The implemented procedure is described in spec §6; a statistical CLI remains future work.

The investigation is written up in full, including the candidate replacements that were measured and rejected and why:

- [`docs/research/2026-08-10-tvd-equivalence-testing.md`](https://github.com/marqov-dev/marqov-capsule/blob/main/docs/research/2026-08-10-tvd-equivalence-testing.md) — why the plug-in estimator fails, why the bootstrap cannot be repaired for this functional, and the one-sided bound that does work
- Tracked in [#15](https://github.com/marqov-dev/marqov-capsule/issues/15); conformance and spec review in [#20](https://github.com/marqov-dev/marqov-capsule/issues/20)

Also on the roadmap, with the research already done:

- Credential scanner precision and recall improvements landed in #68; the supporting research is in [`docs/research/2026-08-11-credential-detection.md`](https://github.com/marqov-dev/marqov-capsule/blob/main/docs/research/2026-08-11-credential-detection.md)
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
| `spec/v1/` | [CC-BY-4.0](https://github.com/marqov-dev/marqov-capsule/blob/main/LICENSE-SPEC) | The spec is a citable artifact — CC-BY allows citation in academic work and independent implementations without copyleft restrictions |
| Python package (`src/`) | [Apache 2.0](https://github.com/marqov-dev/marqov-capsule/blob/main/LICENSE-CODE) | Permissive license suitable for use in commercial and research software without viral conditions |

## Contributing

See [CONTRIBUTING.md](https://github.com/marqov-dev/marqov-capsule/blob/main/CONTRIBUTING.md) for dev setup, the RFC evolution process for spec changes, and license terms.
