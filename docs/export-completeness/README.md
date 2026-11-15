# Accepting a complete experiment export

A valid capsule can omit an authored Report or contain an editable source
replacement if that was what the exporter sealed. Integrity verifies the sealed
bytes. This repository-only tool additionally checks a separately reviewed
expected payload inventory. It does not change the capsule format.

## Establish expectations before export

The experiment owner or reviewer supplies a UTF-8 JSON inventory independently
of the exporter. Review it against the intended experiment record, including
submitted source snapshots, all result samples, configuration, authored Report,
figures, analysis, environment and historical references where required.
For example, for a Bell experiment with four runs, list four distinct submitted sources and four distinct
result files; assigning the `result` role to one aggregate does not prove that
four samples were preserved. File roles are reviewer declarations, not semantic
validation or evidence of execution. Linked figures and Report assets must each
be included as files, rather than relying on a live URL.

Do not derive the acceptance inventory from the exported archive itself: that
would bless its omissions. Retain the reviewed inventory and its SHA-256 through
a trusted channel, separately from the delivered export, together with the
expected `mqc:1:` ID. The tool records the inventory file's SHA-256 but does not
authenticate its author or compare it against an independently trusted hash;
that check belongs to the recipient's acceptance process.

## Inventory format

`version` must be integer 1. `required_roles` is a nonempty unique list drawn
from source, result, configuration, report, figure, analysis, reference,
environment and other. Every required role must have at least one file entry.
All listed files are mandatory, including files whose roles are not in that list.
No wildcard, URL resolution, inference or executable expression is supported.

```json
{
  "version": 1,
  "required_roles": ["source", "result", "configuration", "report", "figure"],
  "allow_extra": false,
  "files": [
    {"path": "source/ab.qasm", "role": "source"},
    {"path": "results/ab.json", "role": "result"},
    {"path": "config.json", "role": "configuration"},
    {"path": "report.md", "role": "report"},
    {"path": "figures/bell.png", "role": "figure"}
  ]
}
```

This short example checks presence only and is not a complete four-setting Bell
inventory. For byte identity, add `sha256` (64 lowercase hexadecimal characters,
without a prefix) to each entry from independently retained authoritative bytes.
`size_bytes` is an optional nonnegative integer; size alone does not establish
identity. The report discloses entries without expected hashes. Supplied hashes
must match even when the export has a valid, different trusted seal.

Payload paths must be canonical NFC relative POSIX paths. Duplicate paths,
traversal, drive/colon syntax, backslashes, ASCII controls, root capsule.yaml and
.checksums entries are rejected. Unknown JSON fields, duplicate keys, invalid
hashes and missing role declarations are errors. Inventory files are bounded to
2 MiB and 10,000 entries. Extra sealed payload files fail by default; set
`allow_extra: true` explicitly in the trusted inventory only when intentional.
Extras remain visible in the report even when allowed.

## Run consumer acceptance

From a repository checkout, use a released installed distribution:

```bash
uv venv --python 3.12 dist/acceptance-env
uv pip install --python dist/acceptance-env/bin/python marqov-capsule==0.2.1
mkdir -p dist/acceptance-scratch
# Set TRUSTED_ID to the value received separately through your trusted channel.
dist/acceptance-env/bin/python -I tools/export_completeness/check.py \
  /path/to/export.capsule /path/to/reviewed-inventory.json \
  --id "$TRUSTED_ID" --scratch-dir dist/acceptance-scratch \
  > dist/export-acceptance.json
```

A restored directory is also accepted. For archives, temporary extraction uses a
unique directory beneath the supplied existing session scratch directory and is
removed afterwards. The supported archive reader applies path/layout checks and
its default 1 GiB inflation limit; this tool cannot disable that limit. `open`
is not used because it accepts directories rather than archive files.

Exit 0 means all three gates passed. Exit 1 means export processing, integrity,
schema or completeness failed. Exit 2 means invalid inventory or CLI usage.
Parse `status` and each gate in the JSON report. `schema` and `completeness` remain
null when an earlier gate fails; a null gate is not a pass. Reports belong outside
the capsule directory. The CLI refuses editable installs and requires `python -I`.

## Meaning and limits

Acceptance requires a valid authenticated digest chain, schema-valid manifest,
and every external expectation satisfied. Tests include an archive sealed
without report.md: its integrity passes, but completeness fails with the Report
listed missing. Another test seals replaced source: external source hashing
rejects it despite its internally valid seal.

Acceptance does not prove that source was executed, counts came from a backend,
a rendered Report is equivalent to authored content, figures follow from data,
or a rerun is independent. It does not execute restored code,
fetch links, upload data, re-seal records, or map application identities. A deficient
external inventory can still produce a deficient acceptance result. Keep the
record stable during checking; concurrent writers are not locked or snapshotted.

An exporter still needs to associate each source with its actual job and
preserve the separate authored Report. This tool supplies consumer acceptance,
not a substitute for a complete exporter. Successful reruns remain a separate
downstream check.
