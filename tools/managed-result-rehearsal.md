# Offline managed-result rehearsal

Run from a checkout with Capsule installed (use a clean environment with
`marqov-capsule==0.1.0` to check the published distribution):

```sh
python -I tools/rehearse_managed_result.py /tmp/managed-result-evidence
```

The destination must be new. The script makes six synthetic records based on
platform contract commit `0bf3db22`: available false, zero, null and Unicode
objects, plus unavailable `unsupported_value` and legacy `not_provided` previews.
Each record keeps the managed envelope, execution receipt and opaque artifact in
separate payload files. Where a sidecar exists, its exact UTF-8 bytes are retained;
legacy missing sidecars are not reconstructed from the display projection.
The binary fixture is deliberately not executable serialized Python.

For every record the script seals, packs, unpacks and verifies using an external
Capsule ID, then checks all payload bytes for equality. Missing artifact bytes,
corrupted bytes, changed tenant references and changed previews after sealing
must all fail integrity verification. The JSON report records the IDs and raw
sidecar hashes. Synthetic receipts carry no authenticated execution authority.

This is a preservation rehearsal, not a production exporter or an import validator.
Capsule can seal arbitrary payload files: it does not understand whether managed
artifact references are complete or belong to a tenant. A platform exporter must
resolve authorized artifacts and validate the receipt/reference/hash/size bindings
before sealing. Incomplete results must be refused at that boundary, even if a
preview is available. Import must verify the trusted Capsule ID and must never
unpickle an artifact to fill a missing preview. Preserving a display does not prove
that its value corresponds to the opaque Python artifact.

No hosted storage, signed observation, deployment, provider execution or end-to-end
platform acceptance is exercised. These checks require the platform lane's later
staging acceptance. This rehearsal requires no package release or schema change.
