# marqov-capsule

Open standard and tooling for reproducible quantum experiments.

## What is a capsule?

A capsule is a sealed, tamper-evident record of a quantum computation. It contains a `capsule.yaml` manifest, a `.checksums` file listing SHA-256 digests of every payload file, and the payload files themselves (results, circuits, environment specs, etc.). Once sealed, the manifest embeds a `checksums_digest` and a capsule ID (SHA-256 of canonical JSON of the manifest). The capsule ID is derived from the content, so it names those exact bytes and nothing else — altering a capsule does not change it, it produces a different capsule. Capsules carry no signatures, so this makes them **tamper-evident**, not authenticated: the digest chain detects modification, not forgery.

The format is an open standard (`spec/v1/`, CC-BY-4.0). The Python tooling is Apache 2.0. Both can be used independently.

## Install

Requires Python 3.10+:

```bash
python -m pip install marqov-capsule==0.1.0
```

For offline installation, install a supplied release wheel with
`python -m pip install ./marqov_capsule-0.1.0-py3-none-any.whl`.
The source distribution includes
`spec/v1/` and `examples/`; from its extracted directory, install with
`python -m pip install .`.

## Quick start

```python
import tempfile
from pathlib import Path
from marqov_capsule import CapsuleBuilder

with tempfile.TemporaryDirectory() as tmp:
    capsule_dir = Path(tmp)

    # Write illustrative counts; this example does not execute a backend
    (capsule_dir / "results.json").write_text('{"00": 512, "11": 488}')

    builder = CapsuleBuilder()
    builder.start_capsule(
        name="bell-state-v1",
        description="Illustrative Bell-state record; no backend execution",
        requirements={"paradigm": ["gate-based"], "max_qubit_count": 2},
        created_by="alice@example.com",
    )

    capsule_id = builder.seal(capsule_dir, sealed_by="alice@example.com")
    print(f"Capsule ID: {capsule_id}")
    # → Capsule ID: mqc:1:<64 lowercase hex chars>, derived from the manifest contents
```

`seal()` runs the full sealing sequence: credential scan, `.checksums` generation, lifecycle transition to `sealed`, and `capsule.yaml` write. It returns a versioned capsule ID: `mqc:1:<64 lowercase hex chars>`.

## Runnable SDK demonstration

The source distribution includes `examples/run_bell.py` and
`examples/seal_bell.py`. They run the Marqov SDK local simulator, seal its result
and circuit, verify an archive against a trusted ID, and demonstrate detection
of changed payloads and metadata. Follow `examples/README.md` in the extracted
source distribution. The SDK demo requires Python 3.12+ and no provider credentials.

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

`open` accepts a capsule directory. With `--dest`, it verifies the source and
copies it into a new child directory under the destination. It refuses an
existing child directory rather than merging files into a verified record.
Use `verify` and `unpack` for archives.

An archive must contain one top-level capsule directory with a regular
`capsule.yaml`. Extraction rejects duplicate or Unicode-colliding member names,
ambiguous layouts, and an existing destination capsule directory. Choose a fresh
destination for each extraction.

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

## Result comparison and limitations

Integrity verification checks a recorded experiment's files. It does not prove
scientific correctness, QPU provenance, signer identity, or reproducibility of
an independently executed experiment. Environment capture is author-supplied;
sealing does not automatically recreate or lock an execution environment.

The Python API provides `verify_deterministic` for explicit result equality and
`verify_statistical` for independent count samples. Statistical comparison
requires NumPy/SciPy and a verifier-owned `VerificationPolicy`; untrusted
settings must pass through `policy.resolve`. Its one-sided bound returns
`VERIFIED` or `INCONCLUSIVE`. There is no statistical comparison CLI in this
release. Sampling assumptions and the decision procedure are in spec §6.

The pre-release `verify_capsule`, `compare_capsules`, and
`check_calibration_drift` methods are retired and raise migration errors.
Use `verify_integrity(directory, expected_id=trusted_id)` for artifact integrity;
compare explicit result payloads separately. No calibration-verdict replacement
is provided.

## Spec

The normative capsule format specification lives in `spec/v1/`:

- `spec/v1/README.md` — format overview, digest scheme, lifecycle rules, verification protocol
- `spec/v1/capsule-schema.json` — JSON Schema 2020-12 for `capsule.yaml`
- `spec/v1/CHANGELOG.md` — version history

The schema is bundled into the Python package and used for validation at runtime. The spec is licensed CC-BY-4.0 so it can be cited in papers and implemented independently.

## License

The Python package is licensed under
[Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0).
The specification is licensed under
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).
Both license texts are included in the wheel and source distribution.

## Contributing

Contributions should include tests for changed behavior and a conformance
fixture for format changes. Specification changes follow an RFC review process.
Contact the project at `hello@marqov.ai` for contribution access and support.
