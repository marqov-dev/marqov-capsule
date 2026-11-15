# Integrating capsule records

A capsule integration should preserve the distinction between an application's
record identifier and the `mqc:1:` content ID returned by sealing. Storage keys
can remain application-owned; persist the trusted content ID separately.

## Creation and delivery

1. Map execution metadata explicitly to schema-valid requirements, task status,
   result type, and backend provider/name/shots. Do not infer missing values
   from a display label. Probabilistic tasks require verification settings.
2. Write payload files before calling `CapsuleBuilder.seal(directory)`.
3. Persist the returned content ID through a trusted application channel.
4. Make retries safe across sealing, storage upload and record persistence.
5. Report credential-scan rejection separately from execution success. Preserve
   completed results without advertising an incomplete capsule as sealed.
6. Verify delivered files with `verify_integrity(..., expected_id=trusted_id)`.
   Consume both failure status and manifest authentication before accepting
   the record. File checksums alone do not authenticate a manifest.

Result comparison is separate from file integrity. Compare explicitly selected
payloads only after verifying both records. Apply verifier-owned policy to
statistical settings, and preserve `INCONCLUSIVE` as a distinct outcome.

## Legacy records

Do not infer complete compatibility from a manifest version string alone.
Legacy checksum maps can be readable while the manifest lacks the binding or
schema fields needed for full integrity verification.

Preserve original bytes and application identity. Creating a new standard
record requires explicit metadata mapping and produces a new content ID; that
new digest does not authenticate the historical source. Keep source provenance
in the application's trusted records. Test malformed manifests, changed payloads,
missing trusted IDs, scanner failures and interrupted retries before rollout.
