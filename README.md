# marqov-capsule

Open standard and tooling for reproducible, portable quantum experiments.

**Layer 1 — Open Standard:** `spec/v1/` (CC-BY-4.0)
**Layer 2 — Open Tooling:** `marqov_capsule` Python package (Apache 2.0)

## Install

```bash
pip install marqov-capsule          # base: build + validate
pip install "marqov-capsule[verify]"  # add statistical verification
```

## Quick start

```python
from marqov_capsule import CapsuleBuilder, CapsuleVerifier, CapsuleValidator
```

See `spec/v1/README.md` for the capsule format specification.
