# Synthetic legacy capsule

`platform-legacy/` records an earlier checksum-map format. All IDs, counts and
metadata are synthetic; the fixture's clock is fixed at `2026-09-09T12:00:00Z`.
No provider execution or external service is involved.

This compatibility fixture is not a valid current conformance example. It
includes the manifest in a YAML checksum map and lacks `checksums_digest` in
the manifest. Tests distinguish readable file checksums from full integrity and
exercise explicit reconstruction of a new record from the synthetic result.

Keep explanatory files outside the fixture directory: its checksum list
represents a closed set. Historical generator provenance is maintained privately;
the fixture bytes remain unchanged to preserve their compatibility coverage.
