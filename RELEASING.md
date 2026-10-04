# Releasing marqov-capsule

Release through `.github/workflows/release.yml` using OIDC trusted publishing.
Manual workflow dispatch publishes to TestPyPI. A pushed `v*` tag publishes to
PyPI; a manual dispatch against a tag cannot select production publishing.
The package version is declared once, as `__version__` in
`src/marqov_capsule/__init__.py` (`pyproject.toml` reads it from there), and
must match the tag.

## 1. Prepare the candidate

- Review merged changes, finalize the version and changelog, and record the
  candidate commit. Unmerged work is not part of the release.
- Verify that PyPI and TestPyPI each have a trusted publisher for this package,
  repository, `release.yml`, and their respective `pypi`/`testpypi` environments.
  A first release may require pending-publisher registration.
- Check the production environment's reviewer settings. To match the SDK
  release process, configure its required-reviewer gate before production upload.
- Run the complete test suite, base-install checks and URL review. A private
  repository link is not a usable public documentation link.
- Review actual artifact contents and scan them for secrets and private notes.
  Package publication and GitHub repository publication are separate decisions.

## 2. Build and inspect

Use a fresh output directory so old archives and rehearsal files cannot be
included accidentally:

```bash
uv build --out-dir /tmp/capsule-release-dist
python tools/check_distribution.py /tmp/capsule-release-dist
uvx twine check /tmp/capsule-release-dist/*.whl /tmp/capsule-release-dist/*.tar.gz
uv venv /tmp/capsule-release-acceptance
uv pip install --python /tmp/capsule-release-acceptance/bin/python /tmp/capsule-release-dist/*.whl
/tmp/capsule-release-acceptance/bin/python -I tools/smoke_distribution.py
```

The artifact check inspects source and wheel inventories. Installed-wheel
acceptance checks the bundled schema, CLI round-trip, deterministic archives,
trusted-ID verification and tamper rejection. Both checks run in the release
workflow before artifacts reach a publisher.

## 3. TestPyPI validation

Push the release branch and open its review so CI runs on the candidate. Wait
for all required checks before dispatching the TestPyPI workflow against that
branch. A branch push alone does not trigger the full CI workflow.

```bash
gh workflow run release.yml --ref release/X.Y.Z
gh run watch <run-id> --exit-status
```

Confirm the build and TestPyPI jobs succeeded and production publishing was
skipped. TestPyPI is public; uploading there discloses package contents too.
Use a new candidate version if the artifact changes after upload. The workflow's
`skip-existing` setting does not replace an existing artifact or prove it contains
new changes. Validate the file downloaded from TestPyPI, not just workflow status.

**Validate the PUBLISHED artifact** in a fresh environment, resolving the package
and runtime dependencies from their respective indexes separately:

```
pip install --no-deps --index-url https://test.pypi.org/simple/ \
            marqov-capsule==X.Y.Z
pip install pyyaml click jsonschema jcs rfc3339-validator
marqov-capsule init ./t --name t --paradigm gate-based --qubits 2
mkdir -p t/payload && echo '{"counts":{"00":1}}' > t/payload/results.json
marqov-capsule seal ./t && marqov-capsule pack ./t -o t.capsule
marqov-capsule verify t.capsule && marqov-capsule unpack t.capsule -o ./r
```

Do not combine TestPyPI and PyPI into one dependency-resolution pool with
`--extra-index-url`. Run `tools/smoke_distribution.py` using the TestPyPI-installed
package's Python to check the complete trusted-ID and tamper acceptance path.
The script must come from the matching release checkout.

## 4. Publish to PyPI

Merge the validated release candidate and wait for main CI. Ensure the files
and version still match the candidate tested on TestPyPI; if they changed,
repeat candidate validation. Record the final commit and artifact hashes.

Pushing the tag triggers public production publication:

```bash
git tag -a vX.Y.Z <validated-sha> -m "marqov-capsule X.Y.Z"
git push origin vX.Y.Z
```

Complete the configured environment approval, watch the publishing job, and
create the GitHub release notes. Install the published package in a fresh
environment and repeat acceptance. Confirm package metadata, license texts and
public documentation links are usable.

## Corrections

Before publication, fix and revalidate the candidate. If a TestPyPI artifact
already exists, use a new candidate version for changed bytes. After production
publication, issue a new version for corrections. Do not force-push the default
branch or silently relabel an unvalidated commit as the tested release.
