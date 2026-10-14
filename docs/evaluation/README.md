# Capsule preservation evaluation

This repository-only harness evaluates released Capsule byte preservation and
local processing cost across five synthetic record shapes and nine bounded
file-count/payload-size conditions. It requires only Capsule's base dependencies;
no SDK, provider account, network execution or quantum backend is used.
It is not included in the wheel or source distribution.

## Run against the release

From a checkout, install the published package in a separate environment:

```bash
uv venv --python 3.12 dist/evaluation-env
uv pip install --python dist/evaluation-env/bin/python marqov-capsule==0.2.1
dist/evaluation-env/bin/python -I tools/evaluation/run.py dist/evaluation-0.2.1 --repeats 3
```

Choose a new evidence directory for every run. Existing directories are refused,
even when empty. Use `--repeats 1` for a quicker smoke run; the limit is five.
The CLI requires isolated Python and refuses editable package installations.
It records installed versions, architecture, Python, OS and the harness SHA-256.
To evaluate another release, install that version and retain its report separately.
No timing threshold determines correctness or CI success.

## Corpus and correctness gates

Bell and GHZ fixtures contain small QASM sources and invented counts. A
parameter-sweep fixture contains a single illustrative RY source, three settings
and three invented result files. A classical fixture preserves source, a JSON
result and Unicode text. A multi-result fixture preserves two count files and an
authored Markdown report. These files are preservation inputs, not scientific
results: the harness neither executes nor validates their circuit semantics.

Each record must pass manifest schema validation and trusted-ID integrity
verification. Repeated packing of the same sealed directory must produce identical
archive bytes. The restored complete file inventory, including manifest and
checksums, must match the sealed directory byte for byte, and restored integrity
must pass against the original ID. Six separate negative copies per record must
fail: changed, missing and extra payloads; a changed manifest; changed checksums;
and a different well-formed trusted ID. The suite therefore requires 30 refusals.
Failures raise an error and preserve partial evidence; no success report is written.

The harness tests payload closure after sealing. An exporter omitting a required
Report *before* sealing can still produce a valid capsule; independent expected
inventory checks remain the exporter's responsibility. Including the synthetic
Report demonstrates byte preservation, not platform Report export readiness.

## Measurement protocol

The scaling matrix crosses 1, 16 and 128 files with 0, 65,536 and 1,048,576 total
payload bytes. Total bytes stay fixed while file count changes. Empty files are
intentional at zero bytes. The data comes from seeded Python pseudorandom bytes,
rather than all-zero data that would measure unusually favorable compression.
The generator is deterministic for the tested Python implementation; report
inventories retain fingerprints for checking records between environments.

Three sequential trials per condition are the default. Each trial creates a new
record; fresh sealing timestamps mean its content ID may differ. Timings use
`perf_counter_ns` around seal, directory verification, first packing and unpacking.
They exclude fixture generation, the separate schema check, second packing,
restored verification and tamper copies. Sealing includes the package's normal
validation and credential scan. Report raw trial values and medians; archive,
payload and complete sealed-directory byte sizes are also retained.

This is a warm-process, uncontrolled-cache measurement. It does not measure
cold-cache throughput, peak memory, concurrent writers, crash recovery, remote
storage or service latency. Archive size can be smaller than payload size because
of compression; a negative archive-minus-payload difference is not negative
metadata overhead. Compare full measured sizes rather than treating that
subtraction as format overhead.

## Evidence and research use

The output contains all fixture files, sealed directories, archives, restored
records, negative copies and `report.json`. Generated evidence stays in ignored
`dist/`. Keep the full report and harness revision with each experiment. The
committed baseline summary is descriptive; it is not a performance requirement.

Before broader paper claims, expand the corpus with actual independently supplied
records, evaluate multiple machines and OS/architectures, review statistical
comparison assumptions separately, and test a real interoperability mapping.
This suite provides no author signatures, backend provenance, restored execution
environment, independent replication, or proof of quantum correctness.
