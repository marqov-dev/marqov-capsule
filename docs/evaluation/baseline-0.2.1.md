# Released 0.2.1 preservation baseline

Measured on 13 October 2026 against the installed production PyPI package. All
five synthetic records and 30 negative cases passed on each environment, as did
all nine scaling conditions with three trials each. This is local preservation
evidence, not quantum execution or independent recipient acceptance.

Both environments are on the same physical Mac; the Linux run is a Docker
container, not a second machine. OS, Python and dependency differences confound
a direct speed comparison. Timings are warm-process medians in milliseconds;
raw trials and complete generated records are retained separately in `dist/`.

## macOS

Python 3.13.13, Darwin arm64; harness SHA-256
`a42c722c35ae58c87c370187391e9a3c67b6ec078547aae8b6cb7ad62b2bc9b5`.

| Payload files | Payload bytes | Archive bytes, trial 1 | Seal ms | Verify ms | Pack ms | Unpack ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 590 | 2.586 | 1.776 | 1.270 | 0.784 |
| 1 | 65536 | 66379 | 4.349 | 0.959 | 1.947 | 1.059 |
| 1 | 1048576 | 1049699 | 4.107 | 1.283 | 20.057 | 2.632 |
| 16 | 0 | 756 | 5.407 | 1.749 | 1.568 | 2.551 |
| 16 | 65536 | 67723 | 4.307 | 2.010 | 2.458 | 2.846 |
| 16 | 1048576 | 1052407 | 5.324 | 2.638 | 19.052 | 6.720 |
| 128 | 0 | 1713 | 14.971 | 13.237 | 8.835 | 22.647 |
| 128 | 65536 | 74534 | 21.050 | 15.055 | 10.601 | 24.830 |
| 128 | 1048576 | 1060859 | 12.312 | 11.628 | 28.854 | 29.063 |

## Linux container

Python 3.12.15, Linux aarch64; harness SHA-256
`a42c722c35ae58c87c370187391e9a3c67b6ec078547aae8b6cb7ad62b2bc9b5`.

| Payload files | Payload bytes | Archive bytes, trial 1 | Seal ms | Verify ms | Pack ms | Unpack ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 591 | 6.413 | 3.098 | 2.628 | 2.993 |
| 1 | 65536 | 66382 | 6.827 | 2.389 | 4.274 | 2.903 |
| 1 | 1048576 | 1049701 | 7.110 | 3.647 | 22.637 | 8.314 |
| 16 | 0 | 755 | 13.021 | 6.284 | 5.776 | 13.037 |
| 16 | 65536 | 67724 | 11.005 | 6.279 | 7.517 | 12.260 |
| 16 | 1048576 | 1052404 | 14.318 | 9.301 | 27.597 | 19.448 |
| 128 | 0 | 1713 | 55.736 | 28.908 | 22.691 | 73.108 |
| 128 | 65536 | 74534 | 52.277 | 28.816 | 25.072 | 70.893 |
| 128 | 1048576 | 1060861 | 45.881 | 29.842 | 47.391 | 83.856 |

## Interpretation limits

The zero-byte condition measures metadata and file-count handling, not absence
of payload entries. One-mebibyte records test a small bounded volume; they say
nothing about near-limit archives or production workloads. No threshold or
broad performance claim is inferred. See README.md for the method and exclusions.

Linux image: `python@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`.
