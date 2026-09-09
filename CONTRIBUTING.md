# Contributing

## Development setup

From an authorized repository checkout, install the development dependencies.
Contact `hello@marqov.ai` for contribution access.

```bash
pip install -e ".[dev]"
pytest tests/
```

The `[dev]` extra includes numpy and scipy (needed for statistical verification tests) plus pytest.

## Running tests

```bash
pytest tests/ -v
```

All tests must pass before submitting a PR. If you are adding a new spec feature, add a conformance fixture under `spec/v1/conformance/` alongside the code change.

## License agreement

This repository contains two separately licensed components:

- Contributions to `spec/v1/` are licensed under **CC-BY-4.0**.
- Contributions to the Python package (`src/`) are licensed under **Apache 2.0**.

By submitting a pull request you agree that your contribution may be distributed under these terms.

---

## RFC Evolution Process

Breaking changes to `spec/v1/` follow a public RFC process:
1. Open an issue using the RFC template below.
2. Mandatory public comment period (minimum 2 weeks).
3. Once non-Marqov maintainers exist, spec-breaking changes require sign-off from at least one external maintainer.

## RFC Template

Every spec change proposal MUST include:

**Reproducibility impact:** Does this change affect what can be verified, or how?
Does it alter §7 (verification), §5 (digest scheme), or §4 (credential policy)?

**Portability impact:** Does this change affect what a third party (human or agent)
needs to re-target and re-execute a capsule? Does it introduce any
platform-specific element, non-machine-readable field, or dependency on
the originating implementation?
