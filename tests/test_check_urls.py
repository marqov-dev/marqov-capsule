"""Tests for tools/check_urls.py's classification logic (#62).

`tools/check_urls.py` is a standalone script, not part of the installed
package, so it's loaded by file path here — the same way it's actually
invoked (`python tools/check_urls.py`). All classification tests mock the
network boundary (`_open`) so the suite stays fast, deterministic, and does
not depend on any external host's live behavior — the exact flakiness this
script itself exists to eyeball rather than hard-fail on.
"""
from __future__ import annotations

import importlib.util
import re
import socket
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError

REPO_ROOT = Path(__file__).parent.parent
MODULE_PATH = REPO_ROOT / "tools" / "check_urls.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_urls", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_urls = _load_module()


def _http_error(code: int, url: str = "https://example.com/") -> HTTPError:
    return HTTPError(url, code, f"status {code}", hdrs=None, fp=None)


def _raises(exc: BaseException):
    def _opener(url, method):
        raise exc
    return _opener


class _Resp:
    def close(self):
        pass


# ---------------------------------------------------------------------------
# URL extraction / normalization
# ---------------------------------------------------------------------------

def test_trailing_bang_is_stripped():
    """A URL sitting at the end of a sentence ('...see https://x.com! ...')
    must not carry the punctuation into the checked URL (#62 :52)."""
    urls = check_urls.URL_RE.findall("See https://example.com! for details.")
    assert urls == ["https://example.com!"]
    assert urls[0].rstrip(check_urls.TRAILING_PUNCTUATION) == "https://example.com"


def test_url_regex_stops_at_markdown_delimiters():
    text = "[link](https://example.com/foo) and <https://example.com/bar> then https://example.com/baz, done"
    assert check_urls.URL_RE.findall(text) == [
        "https://example.com/foo",
        "https://example.com/bar",
        "https://example.com/baz",
    ]


# ---------------------------------------------------------------------------
# Malformed URLs must WARN, never crash or false-FAIL (#62 :52)
# ---------------------------------------------------------------------------

def test_malformed_ipv6_does_not_crash():
    bucket, detail = check_urls.check("http://[::1/")
    assert bucket == "warn"


def test_idna_ace_prefix_conflict_does_not_crash():
    bucket, detail = check_urls.check("http://xn--exam\xe9ple.com/")
    assert bucket == "warn"


def test_overlong_idna_label_does_not_crash():
    bucket, detail = check_urls.check("https://" + "a" * 70 + ".example.com/")
    assert bucket == "warn"


def test_url_with_no_host_does_not_crash():
    bucket, detail = check_urls.check("https:///path-only")
    assert bucket == "warn"


def test_url_containing_backslash_is_warn_not_crash():
    """A regex literal or Windows-style path fragment matched by the
    URL-shaped regex is not a URL; flag it rather than mis-report it as a
    dead host. Discovered via this script's own ALLOWLIST patterns matching
    URL_RE when it scans its own source (see check_urls.py's `\\` guard)."""
    bucket, detail = check_urls.check(r"https://github\.com/marqov-dev/marqov-capsule(/.*")
    assert bucket == "warn"
    assert "backslash" in detail


# ---------------------------------------------------------------------------
# Reachability classification — the #62 :57 fix
# ---------------------------------------------------------------------------

def test_dns_failure_is_warn_not_fail(monkeypatch):
    """The core fix: a resolver error is inconclusive (may be transient),
    not a release-blocking FAIL."""
    monkeypatch.setattr(check_urls, "_open", _raises(URLError(socket.gaierror(8, "nope"))))
    bucket, detail = check_urls.check("https://example.com/")
    assert bucket == "warn"
    assert "DNS" in detail


def test_connection_refused_is_fail(monkeypatch):
    """The unambiguous dead-host signal: DNS resolved, but nothing answers
    on the port."""
    monkeypatch.setattr(
        check_urls, "_open", _raises(URLError(ConnectionRefusedError(61, "Connection refused")))
    )
    bucket, detail = check_urls.check("https://example.com/")
    assert bucket == "fail"


def test_tls_certificate_failure_is_fail(monkeypatch):
    err = ssl.SSLCertVerificationError()
    err.verify_message = "hostname mismatch"
    monkeypatch.setattr(check_urls, "_open", _raises(URLError(err)))
    bucket, detail = check_urls.check("https://example.com/")
    assert bucket == "fail"


def test_timeout_is_warn(monkeypatch):
    monkeypatch.setattr(check_urls, "_open", _raises(TimeoutError("timed out")))
    bucket, detail = check_urls.check("https://example.com/")
    assert bucket == "warn"


def test_success_is_ok(monkeypatch):
    monkeypatch.setattr(check_urls, "_open", lambda url, method: _Resp())
    bucket, detail = check_urls.check("https://example.com/")
    assert bucket == "ok"


# ---------------------------------------------------------------------------
# WARN-channel noise reduction — the #62 :62 fix
# ---------------------------------------------------------------------------

def test_generic_404_is_warn(monkeypatch):
    url = "https://example.com/dead-page"
    monkeypatch.setattr(check_urls, "_open", _raises(_http_error(404, url)))
    bucket, detail = check_urls.check(url)
    assert bucket == "warn"
    assert "404" in detail


def test_allowlisted_private_repo_404_is_allow(monkeypatch):
    url = "https://github.com/marqov-dev/marqov-capsule/issues/1"
    monkeypatch.setattr(check_urls, "_open", _raises(_http_error(404, url)))
    bucket, detail = check_urls.check(url)
    assert bucket == "allow"


def test_allowlisted_schema_id_404_is_allow(monkeypatch):
    url = "https://marqov.ai/schemas/capsule/v1/capsule-schema.json"
    monkeypatch.setattr(check_urls, "_open", _raises(_http_error(404, url)))
    bucket, detail = check_urls.check(url)
    assert bucket == "allow"


def test_allowlist_does_not_swallow_unexpected_status(monkeypatch):
    """Allowlisting a URL for 404 must not silence it once it starts
    returning something else — the allowlist tracks a status, not a URL."""
    url = "https://github.com/marqov-dev/marqov-capsule"
    monkeypatch.setattr(check_urls, "_open", _raises(_http_error(500, url)))
    bucket, detail = check_urls.check(url)
    assert bucket == "warn"
    assert "500" in detail


def test_allowlisted_matches_documented_status_only():
    url = "https://github.com/marqov-dev/marqov-capsule/issues/1"
    assert check_urls._allowlisted(url, 404) is not None
    assert check_urls._allowlisted(url, 200) is None


def test_head_405_falls_back_to_get(monkeypatch):
    calls = []

    def _opener(url, method):
        calls.append(method)
        if method == "HEAD":
            raise _http_error(405, url)
        return _Resp()

    monkeypatch.setattr(check_urls, "_open", _opener)
    bucket, detail = check_urls.check("https://example.com/")
    assert calls == ["HEAD", "GET"]
    assert bucket == "ok"


def test_head_403_falls_back_to_get_and_can_still_warn(monkeypatch):
    def _opener(url, method):
        if method == "HEAD":
            raise _http_error(403, url)
        raise _http_error(404, url)

    monkeypatch.setattr(check_urls, "_open", _opener)
    bucket, detail = check_urls.check("https://example.com/blocked")
    assert bucket == "warn"
    assert "404" in detail


def test_allowlisted_status_on_head_does_not_retry_with_get(monkeypatch):
    """No need to spend a second request once the allowlist already
    explains the HEAD result."""
    pattern = re.compile(r"^https://example\.com/$")
    monkeypatch.setattr(check_urls, "ALLOWLIST", [(pattern, frozenset({405}), "test")])
    calls = []

    def _opener(url, method):
        calls.append(method)
        raise _http_error(405, url)

    monkeypatch.setattr(check_urls, "_open", _opener)
    bucket, detail = check_urls.check("https://example.com/")
    assert calls == ["HEAD"]
    assert bucket == "allow"


# ---------------------------------------------------------------------------
# git ls-files: anchored to the repo root, NUL-delimited (#62 :30 / :31)
# ---------------------------------------------------------------------------

def test_tracked_files_anchored_to_repo_root_regardless_of_cwd(monkeypatch, tmp_path):
    """Running the script from an unrelated cwd must not silently scan an
    empty/wrong subtree and exit 0 having checked nothing."""
    monkeypatch.chdir(tmp_path)
    files = check_urls.tracked_files()
    assert any(p.name == "pyproject.toml" for p in files)
    assert all(p.is_absolute() for p in files)


def test_tracked_files_handles_spaces_in_paths(monkeypatch):
    """git ls-files -z + split('\\0'), not .split(), so a tracked path with
    a space in it survives intact instead of being shredded in two."""

    class _Result:
        stdout = "a file.txt\0normal.txt\0"

    def _fake_run(cmd, **kwargs):
        assert cmd[:3] == ["git", "ls-files", "-z"]
        return _Result()

    monkeypatch.setattr(check_urls.subprocess, "run", _fake_run)
    names = [p.name for p in check_urls.tracked_files()]
    assert names == ["a file.txt", "normal.txt"]


# ---------------------------------------------------------------------------
# main(): exit code reflects FAIL only, not WARN/allow
# ---------------------------------------------------------------------------

def test_main_exits_nonzero_only_on_fail(monkeypatch, capsys):
    monkeypatch.setattr(
        check_urls, "collect", lambda: {"https://dead.example/": {REPO_ROOT / "README.md"}}
    )
    monkeypatch.setattr(check_urls, "check", lambda url: ("fail", "connection refused"))
    assert check_urls.main() == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_exits_zero_when_only_warnings(monkeypatch, capsys):
    monkeypatch.setattr(
        check_urls, "collect", lambda: {"https://flaky.example/": {REPO_ROOT / "README.md"}}
    )
    monkeypatch.setattr(check_urls, "check", lambda url: ("warn", "DNS did not resolve"))
    assert check_urls.main() == 0
    out = capsys.readouterr().out
    assert "WARN" in out
    assert "FAIL" not in out
