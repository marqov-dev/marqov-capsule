# Releasing marqov-capsule

Adapted from [`marqov-sdk/RELEASING.md`](https://github.com/marqov-dev/marqov-sdk/blob/main/RELEASING.md),
which is proven. Differences from the SDK are noted inline rather than silently
diverging.

The `v*` tag push to real PyPI is the irreversible step (PyPI never lets a
version be reused), so validate hard and tag last. But **the TestPyPI dry-run
in step 3 is not free either** — it publishes the actual target version
X.Y.Z to TestPyPI, which enforces the same no-reuse rule per file. The
publish step sets `skip-existing: true`, so re-running the dry-run against an
*unchanged* build is idempotent — but if the branch needs a new commit after
a dry-run (e.g. CI turns up something), that build is spent and a fresh dry-run
of the same version will just skip, not verify the new code. Get CI green on
the branch *before* triggering the dry-run (step 3 is ordered that way below),
not just before the tag.

> **How the tag publishes:** pushing a `v*` tag triggers
> `.github/workflows/release.yml`, which builds and publishes to PyPI via
> **OIDC trusted publishing** (`id-token: write` + the `pypi` environment — no
> stored token). Manual "Run workflow" dispatch runs the same build and
> publishes to **TestPyPI** instead. The two paths are gated on
> `github.event_name` (`push` vs. `workflow_dispatch`), not on the ref, so they
> cannot double-fire even if a manual dispatch targets a tag ref — a
> `workflow_dispatch` can never publish to real PyPI, and only an actual tag
> `push` can. (An earlier version of this workflow gated `publish-pypi` on
> `startsWith(github.ref, 'refs/tags/v')` alone, which a `workflow_dispatch`
> run against a tag ref also satisfies — that's fixed now, but if you're
> reading a stale copy of `release.yml`, check the `if:` conditions before
> trusting this paragraph.) If publishing fails at the auth step it is the
> PyPI trusted-publisher config (project / repo / workflow / environment),
> not a token.
>
> *Differs from the SDK:* the version is **static** in `pyproject.toml`, not
> read from `__init__.py`. `release.yml` asserts the built wheel filename
> matches the tag, which is the equivalent guard.

## 0. Scope
- [ ] `git log --oneline vLAST..main` — everything merged since the last tag.
      (For 0.1.0 there is no previous tag: the whole history is in scope.)
- [ ] Confirm what's in vs. still in flight. Unmerged branches and open PRs are
      NOT in the release; don't describe them as if they are.

## 1. Changelog & version
- [ ] CHANGELOG covers every merged user-facing change (cross-check the log).
- [ ] **No changelog block without a matching tag** (`git ls-remote --tags origin`)
      — a dated entry with no tag never shipped; fold it in. *This exact defect
      was found before 0.1.0: a `[0.1.0] — 2026-07-22 "Initial release"` block
      sat above every real change while nothing had ever been published.*
- [ ] For a first release, check the changelog does not read as a diff against a
      predecessor that never existed ("no longer fails on X" implies a shipped X).
- [ ] Credit contributors: `git shortlog -sne vLAST..main`.
- [ ] Bump `version` in `pyproject.toml`.
- [ ] No stale version strings: `git grep '<previous-version>'`.

## 2. Pre-flight
- [ ] Full suite green: `.venv/bin/python -m pytest -q`
- [ ] **Base install green** — the package must work without optional deps:
      ```
      uv venv /tmp/base && uv pip install --python /tmp/base/bin/python -e . pytest
      /tmp/base/bin/python -m pytest tests/ -q
      ```
      Tests needing an optional dependency must **skip**, not fail. Guard them
      per-test, never at module scope — a module-level `importorskip` silently
      widens as tests are appended (see #39).
- [ ] **URLs resolve** — `python tools/check_urls.py` (must exit 0).
      Nothing fetches a prose URL, so no unit test catches a dead one. FAILs
      only on an unambiguous reachability signal (connection actively
      refused, or a TLS cert that doesn't verify) so it can't false-fail a
      release on someone else's outage; a resolver hiccup, timeout, or 4xx
      from an auth-gated API is a WARN — eyeball each.
- [ ] Packaging invariants: `pytest tests/test_packaging.py` — exactly one schema
      ships, it is byte-identical to `spec/v1/`, and no extra advertises an
      unsupported feature.

## 3. Build, inspect, dry-run to TestPyPI

Ordered so the one-shot TestPyPI upload (which burns the real target version,
see above) happens *after* everything cheaper has already passed — not before.

- [ ] Look inside the artifact before any upload:
      ```
      uv build
      python -m zipfile -l dist/*.whl        # wheel contents
      tar tzf dist/*.tar.gz                   # sdist sweep — no strays
      uvx twine check dist/*
      ```
- [ ] Push a `release/X.Y.Z` branch (version bumped, changelog dated).
- [ ] **CI (full suite) green on the branch** — the last free check before
      spending the dry-run's one-shot TestPyPI upload of this version.
- [ ] Dry-run: `gh workflow run release.yml --ref release/X.Y.Z` (TestPyPI only).
- [ ] `gh run watch <id> --exit-status` — build ✅, publish-testpypi ✅,
      publish-pypi skipped.
- [ ] **Validate the PUBLISHED artifact, not just the pipeline** — install
      from TestPyPI and exercise it while you still can (TestPyPI, like PyPI,
      never lets these files be re-uploaded):
      ```
      pip install --index-url https://pypi.org/simple/ \
                  pyyaml jsonschema click jcs
      pip install --index-url https://test.pypi.org/simple/ \
                  --no-deps marqov-capsule==X.Y.Z
      marqov-capsule init ./t --name t --paradigm gate-based --qubits 2
      mkdir -p t/payload && echo '{"counts":{"00":1}}' > t/payload/results.json
      marqov-capsule seal ./t && marqov-capsule pack ./t -o t.capsule
      marqov-capsule verify t.capsule && marqov-capsule unpack t.capsule -o ./r
      ```
      Runtime deps first from real PyPI, then the package itself from TestPyPI
      with `--no-deps` — **not** `--extra-index-url`. TestPyPI and PyPI share
      a namespace pool when merged that way (PyPA's own guidance): a dep like
      `pyyaml`/`click`/`jsonschema`/`jcs` could resolve to a stranger's
      higher-versioned TestPyPI upload instead of the real package, and you'd
      never notice from the install succeeding.

## 4. Cut the release
- [ ] Fast-forward `main` to the release commit and push.
- [ ] **Wait for CI green on `main`** — the last gate before the irreversible step.

### ⚠️ The tag is the point of no return
Pushing a `v*` tag publishes to real PyPI, and **a PyPI version can never be
reused or unpublished.** Tag the exact SHA you validated on TestPyPI, and only
after CI is green on it:

```
git tag -a vX.Y.Z <validated-sha> -m "marqov-capsule X.Y.Z"
git push origin vX.Y.Z
```

- [ ] Watch `release.yml` → `publish-pypi` green.
- [ ] `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file NOTES.md`
- [ ] Verify: PyPI shows X.Y.Z, both licences render, project URLs resolve, and a
      clean-venv `pip install marqov-capsule==X.Y.Z` completes a seal → pack →
      verify round-trip.

## Rollback
- **Before the tag:** nothing has been published — fix forward with a new commit.
  Do **not** force-push the default branch.
- **After the tag:** a PyPI version cannot be unpublished. Ship `X.Y.(Z+1)`.

## Capsule-specific notes

**The spec is the expensive part.** Code ships every release; `spec/v1/` is
CC-BY and meant to be cited and independently implemented. A wrong normative
statement is the one thing that cannot be cheaply undone, so treat spec changes
with more care than code changes.

**Downstream vendors this package by file copy.** Three platform repos carry a
`capsule_builder.py` copy with no dependency declaration and therefore no update
path (#50). Publishing is what unblocks replacing them — a release here is a
security delivery mechanism, not only a milestone.

### The schema `$id` host

`spec/v1/capsule-schema.json` declares:

```json
"$id": "https://marqov.ai/schemas/capsule/v1/capsule-schema.json"
```

This previously read `marqov.dev`, which is not a domain in use — the product
is `marqov.ai` (marketing) and `app.marqov.ai` (application). It originated in
agent-written design docs and propagated into the schema, the spec README and a
test. Corrected before the first tag, because `$id` is the schema's canonical
identity and changing it after publication breaks anyone who pinned it.

`marqov.ai/schemas/…` returns 404 today. A JSON Schema `$id` is an identifier
and need not dereference, so this does not block anything — but serving the
file there is a genuine nice-to-have for a CC-BY spec meant to be implemented
independently. Not on the release critical path.

## Not adopted from the SDK

- **`tests/test_no_private_references.py`** — the SDK's hygiene gate. No
  equivalent here yet; worth adding if this repo ever references private infra.
- **Multiple optional extras.** Capsule has only `dev` after the `[verify]` extra
  was removed in #51, so there is no separate-`--extra`-flags trap to avoid.
- **Push-protection secret scanning** — the SDK relies on this in place of a
  per-release secret grep. On this repository it is **currently disabled**
  (verified via `gh api repos/marqov-dev/marqov-capsule --jq
  '.security_and_analysis'` → `secret_scanning: disabled`,
  `push_protection: disabled`). Worth enabling before adopting the SDK's
  "no per-release grep needed" assumption — doubly so for a project whose own
  product is a credential gate.

## Confirmed prerequisites

Checked, so they don't have to be rediscovered on release day:

- ✅ `pypi` and `testpypi` GitHub Environments both exist.
- ✅ `release.yml` cannot double-fire — `publish-testpypi` requires
  `github.event_name == 'workflow_dispatch'`, `publish-pypi` requires
  **both** `github.event_name == 'push'` **and** a `refs/tags/v` ref. Gating
  `publish-pypi` on the ref alone used to be enough for a `workflow_dispatch`
  run against a tag ref to satisfy it too (`github.ref` is still
  `refs/tags/vX.Y.Z` on a dispatch made against that ref) — fixed by requiring
  `event_name == 'push'`, which a manual dispatch can never be.
- ❓ **PyPI trusted publisher.** Cannot be checked from the repo. For a first
  publish the project does not exist yet, so it needs a *pending publisher* for
  `marqov-capsule` bound to `marqov-dev/marqov-capsule`, workflow `release.yml`,
  environment `pypi` (and a TestPyPI one for the dry-run, environment
  `testpypi`). If missing, the tag fires and OIDC fails at upload.
