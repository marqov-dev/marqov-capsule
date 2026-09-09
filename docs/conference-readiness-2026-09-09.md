# Capsule demonstration scope

The demonstrated workflow executes a Bell experiment with the SDK's local
simulator, records counts/circuit/source/environment versions, seals the files,
packs a deterministic archive and verifies it against a separately recorded ID.
Changing the payload or manifest fails trusted-ID verification.

See `examples/README.md` for setup and invocation. The source distribution
contains the two demonstration scripts. Repository checkouts also provide an
optional offline kit preparation tool.

This demonstrates integrity and portability of an experiment record. It does
not claim QPU provenance, signatures, automatic environment recreation or
statistical replication. Each new seal has a fresh timestamp and may have a
new ID; repeated packing of the same sealed directory is byte-identical.

Validation covers supported Python versions, minimum dependencies, base-wheel
installation, independent canonicalization/checksum vectors, artifact inventories
and an isolated installed-wheel CLI journey. Host-specific offline kits must be
rebuilt and rehearsed on the intended Python version, OS and architecture.
