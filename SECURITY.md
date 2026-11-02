# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately. Do not open a public issue.

- Use GitHub's private vulnerability reporting: the **Report a vulnerability**
  button under the repository's **Security** tab.
- Or email `hello@marqov.ai` with "marqov-capsule security" in the subject.

Include the affected version, a description of the problem, and steps or a
minimal capsule that reproduces it. We aim to acknowledge reports within five
working days and will keep you informed as a fix is prepared. We credit
reporters in the changelog unless you ask us not to.

## Supported versions

Security fixes are made to the latest minor release on PyPI. Older releases
are not patched; upgrade to the current version.

## Scope

In scope: the `marqov-capsule` Python package and CLI, and the capsule format
specification in `spec/v1/`. Issues of particular interest include verification
bypasses (a modified capsule that verifies against its trusted ID), unsafe
archive extraction, manifest parser denial of service, and credential-scan
evasion in the sealing step.

Out of scope, because the project documents them as limits:

- Capsules carry no signatures. A capsule ID is tamper-evident, not
  authenticated; a trusted ID must arrive through a channel separate from the
  artifact.
- Integrity does not establish QPU provenance or scientific correctness, and
  environment snapshots are author-supplied.
- The credential scanner is best-effort and is not a guarantee that a capsule
  contains no secrets.
