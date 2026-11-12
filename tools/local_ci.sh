#!/usr/bin/env bash
# Local replica of .github/workflows/ci.yml for when hosted CI is unavailable.
#
# Runs every job the workflow runs, each in a fresh uv-managed virtualenv so
# the editable install of the main checkout cannot leak in. The only job it
# cannot replicate is test-windows; it says so in the summary.
#
# Usage:  tools/local_ci.sh [repo-dir] [compare-branch]
#   repo-dir        checkout or worktree to test (default: current directory)
#   compare-branch  base for diff-cover (default: origin/main)
# Env:    LOCAL_CI_HOME  where venvs and build output go (default: a mktemp dir)
#
# Exit status is non-zero if any replicated job fails. Every job runs even if
# an earlier one fails, so one run gives the whole picture.
set -u

REPO="$(cd "${1:-.}" && pwd)"
COMPARE="${2:-origin/main}"
HOME_DIR="${LOCAL_CI_HOME:-$(mktemp -d -t local-ci)}"
mkdir -p "$HOME_DIR"
cd "$REPO"

command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)"; exit 2; }

declare -a RESULTS=()
record() { RESULTS+=("$1	$2"); }

# venv NAME PYTHON  -> creates $HOME_DIR/NAME and prints its python path
venv() {
  local name="$1" py="$2" dir="$HOME_DIR/$1"
  rm -rf "$dir"
  uv venv -q --python "$py" "$dir" || return 1
  echo "$dir/bin/python"
}
pipi() { uv pip install -q --python "$1" "${@:2}"; }

run_job() {
  local name="$1"; shift
  echo
  echo "=================== $name"
  local start=$SECONDS
  if "$@"; then record "$name" "pass ($((SECONDS - start))s)"; else record "$name" "FAIL ($((SECONDS - start))s)"; fi
}

job_lint() {
  local py; py=$(venv lint 3.12) || return 1
  pipi "$py" -e ".[dev]" || return 1
  "$py" -m ruff format --check src tests tools || return 1
  "$py" -m ruff check src tests tools || return 1
  "$py" -m mypy src || return 1
}

job_test() {
  local pyver="$1" with_cov="$2"
  local py; py=$(venv "test-$pyver" "$pyver") || return 1
  pipi "$py" -e ".[dev]" || return 1
  "$py" -c "import json; json.load(open('spec/v1/capsule-schema.json')); print('schema OK')" || return 1
  if [ "$with_cov" = "cov" ]; then
    "$py" -m pytest tests/ -q --tb=short -p no:cacheprovider --cov --cov-report=xml:"$HOME_DIR/coverage.xml" || return 1
    if git rev-parse --verify -q "$COMPARE" >/dev/null; then
      "$py" -m diff_cover.diff_cover_tool "$HOME_DIR/coverage.xml" --compare-branch="$COMPARE" --fail-under=90 || return 1
    else
      echo "diff-cover skipped: $COMPARE not found"
    fi
  else
    "$py" -m pytest tests/ -q --tb=short -p no:cacheprovider || return 1
  fi
  local cli; cli="$(dirname "$py")/marqov-capsule"
  "$cli" --version && "$cli" validate spec/v1/conformance/valid_capsule/capsule.yaml \
    && "$cli" inspect spec/v1/conformance/valid_capsule >/dev/null \
    && "$cli" verify spec/v1/conformance/valid_capsule >/dev/null || return 1
}

job_wheel_smoke() {
  local py; py=$(venv wheel 3.11) || return 1
  local dist="$HOME_DIR/dist"; rm -rf "$dist"
  pipi "$py" build || return 1
  "$py" -m build --outdir "$dist" >/dev/null || return 1
  "$py" tools/check_distribution.py "$dist" || return 1
  local wpy; wpy=$(venv wheel-install 3.11) || return 1
  pipi "$wpy" "$dist"/*.whl || return 1
  "$wpy" -I tools/smoke_distribution.py || return 1
  "$wpy" - <<'EOF' || return 1
import importlib.resources as pkg, pathlib
ref = pkg.files("marqov_capsule.schemas").joinpath("capsule-schema.json")
assert ref.read_bytes() == pathlib.Path("spec/v1/capsule-schema.json").read_bytes(), "bundled schema differs from spec/"
print("Bundled schema: byte-identical to spec copy")
from marqov_capsule import CapsuleValidator
r = CapsuleValidator.validate({'version': '1.0.0', 'name': 'test', 'lifecycle_state': 'draft'})
assert r['valid'] is True, r
print('CapsuleValidator: OK from wheel install')
EOF
}

job_base_install() {
  local py; py=$(venv base 3.11) || return 1
  pipi "$py" -e . || return 1
  "$py" -c "import sys, marqov_capsule; assert 'numpy' not in sys.modules, 'numpy imported at package load'; print('Lazy numpy import: OK')" || return 1
  pipi "$py" pytest || return 1
  "$py" -m pytest tests/ -q -rs -p no:cacheprovider || return 1
  "$py" -m pytest tests/ --collect-only -q -p no:cacheprovider | tail -1
}

job_minimum_versions() {
  local py; py=$(venv minver 3.10) || return 1
  uv pip install -q --python "$py" --resolution lowest-direct -e ".[dev]" || return 1
  uv pip list --python "$py" | grep -iE "^(pyyaml|jsonschema|click|jcs|numpy|scipy|hypothesis|pytest) " || true
  "$py" -m pytest tests/ -q -p no:cacheprovider || return 1
}

job_conformance_node() {
  command -v npm >/dev/null || { echo "npm not found; install Node 22 to replicate this job"; return 1; }
  npm ci --prefix tools/conformance --ignore-scripts --silent || return 1
  npm test --prefix tools/conformance --silent || return 1
}

job_links() {
  local py; py=$(venv links 3.12) || return 1
  "$py" tools/check_urls.py --offline || return 1
}

run_job "lint"                 job_lint
run_job "test (3.10)"          job_test 3.10 nocov
run_job "test (3.11)"          job_test 3.11 nocov
run_job "test (3.12 + cov)"    job_test 3.12 cov
run_job "test (3.13)"          job_test 3.13 nocov
run_job "test (3.14)"          job_test 3.14 nocov
run_job "wheel-smoke"          job_wheel_smoke
run_job "base-install"         job_base_install
run_job "minimum-versions"     job_minimum_versions
run_job "conformance-node"     job_conformance_node
run_job "links"                job_links
record "test-windows" "NOT REPLICATED (needs a Windows runner)"

echo
echo "=================== summary ($REPO @ $(git rev-parse --short HEAD), host $(uname -s))"
printf '%s\n' "${RESULTS[@]}" | column -t -s '	'
if printf '%s\n' "${RESULTS[@]}" | grep -q 'FAIL'; then exit 1; fi
