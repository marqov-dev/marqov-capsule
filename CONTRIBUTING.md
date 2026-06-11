# Contributing

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
