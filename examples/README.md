# Quantum Week: a portable experiment record

## Prepare an offline kit (repository checkout only)

This optional preparation tool is available in a repository checkout, not in
the wheel or source distribution. The two demonstration scripts below are
included in the source distribution and can be run directly.

While online on the demonstration machine, build a capsule wheel and collect
the SDK and dependency wheels using Python 3.12+ with pip installed:

```bash
uv build
python3.12 tools/prepare_conference_kit.py dist/marqov_capsule-0.2.4-py3-none-any.whl dist/conference-kit
```

Use a new kit directory each time. The kit contains the two scripts below,
all dependency wheels, hash-pinned installation requirements, platform/version
metadata, licenses and a runbook. Follow its README to install and demonstrate
with `--no-index` and `--require-hashes`. The target must already have compatible
Python installed. Build a separate kit for a different OS, architecture or
Python minor version. Generated kits stay under ignored `dist/`.

## Run the experiment

Run a real two-qubit Bell experiment with the Marqov SDK's local simulator,
then seal its counts, circuit, source, and environment versions into a capsule.
No provider credentials, account, network execution, or QPU fees are needed.

From a repository checkout or the extracted source distribution, using Python 3.12+:

```bash
python3.12 -m venv /tmp/marqov-capsule-demo-env
/tmp/marqov-capsule-demo-env/bin/python -m pip install marqov-capsule==0.2.4 marqov==0.5.1
/tmp/marqov-capsule-demo-env/bin/python examples/run_bell.py /tmp/bell-export
/tmp/marqov-capsule-demo-env/bin/python examples/seal_bell.py /tmp/bell-export /tmp/bell-demo
```

Use new output directories on each run; scripts refuse to overwrite existing
ones. Both packages are installed from PyPI. The SDK and capsule steps may also
run in separate environments.

The second script checks schema validity, seals and packs the export twice,
checks byte-identical archives, extracts and verifies against the recorded ID,
then changes a payload and a manifest in separate copies. Both must fail.
It leaves the original archive intact and writes a machine-readable `report.json`.

To demonstrate verification interactively in the installed environment:

```bash
marqov-capsule inspect /tmp/bell-demo/bell-state
marqov-capsule verify /tmp/bell-demo/bell-state.capsule --id "$(cat /tmp/bell-demo/trusted-id.txt)"
marqov-capsule verify /tmp/bell-demo/tampered --id "$(cat /tmp/bell-demo/trusted-id.txt)"
```

The last command should exit 1. Share the recorded ID through a trusted channel
separate from the archive. Here the local `trusted-id.txt` models that channel;
shipping it alongside an archive does not itself establish trust.

Suggested narration: “This is the circuit and result from a local SDK run.
The capsule preserves those files and records their identity. Another person
can unpack it and check that the contents match the ID I gave them. Changing
the result or the experiment description fails that check.”

This demonstrates integrity and portability of the record, not signatures,
QPU provenance, automatic environment recreation, or statistical replication.
The fixed sampling seed makes the example convenient to repeat; each new seal
has fresh timestamps and therefore a new ID. Only repeated packing of the same
sealed directory is promised to produce identical archive bytes.

## Fresh-environment replay pilot

For two isolated, network-denied replays with a separately trusted dependency
freeze, an independent analytic oracle and resource receipts, see
[`tools/reproduction/README.md`](../tools/reproduction/README.md) in the checkout.
This macOS pilot is separate from hosted Capsule acceptance.
