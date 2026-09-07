#!/usr/bin/env python3
"""Check that every URL in tracked files resolves.

Nothing fetches a prose URL, so no unit test catches a dead one — it ships and
a reader finds it. This is the class of defect that put `platform.marqov.com`
into marqov-sdk 0.3.0.

Three buckets:

- **FAIL** — an actual reachability/ownership signal says the host is dead:
  the connection was actively refused (DNS resolved, nothing is listening),
  or the TLS certificate does not verify. This is deliberately narrow so the
  gate cannot false-FAIL a release on an outage.
- **WARN** — anything inconclusive: DNS resolution failure (may be a
  transient resolver hiccup, not a dead domain), a timeout, or an HTTP error
  status. Eyeball these rather than letting the gate block a tag on one.
  Known-expected non-2xx responses (private-repo 404s, the canonical schema
  `$id`) are called out separately so they don't bury a real WARN.
- **OK** — 2xx, or a documented allowlisted status. Not printed.

A single malformed extracted URL (bad IPv6 literal, unencodable IDNA host,
stray trailing punctuation swept in by the regex, ...) is normalized where
possible and otherwise reported as WARN — it never crashes the run or
poisons the FAIL count for the rest of the URLs.

Usage:  python tools/check_urls.py        # exit 0 = no confirmed-dead hosts
"""
from __future__ import annotations

import re
import socket
import ssl
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent

URL_RE = re.compile(r"https?://[^\s\"'<>)\]`,]+")
# Sentence/markup punctuation the regex can sweep in when a URL sits at the
# end of a clause ("see https://example.com!"). `)]}>` etc. never appear —
# they're excluded from URL_RE's character class itself.
TRAILING_PUNCTUATION = ".,;:!?\\"
TIMEOUT = 8

# URLs known to legitimately answer with a non-2xx status, so a human
# reviewing WARN output isn't retreading old, already-understood ground.
# Matched against the full URL; only suppresses the *documented* status —
# any other status still WARNs normally.
ALLOWLIST: list[tuple[re.Pattern[str], frozenset[int], str]] = [
    (
        re.compile(r"^https://github\.com/marqov-dev/marqov-capsule(/.*)?$"),
        frozenset({404}),
        "private repo — unauthenticated requests always 404",
    ),
    (
        re.compile(r"^https://marqov\.ai/schemas/capsule/v1/capsule-schema\.json$"),
        frozenset({404}),
        "canonical $id, not required to dereference (see RELEASING.md)",
    ),
]


def tracked_files() -> list[Path]:
    """Every git-tracked file, as absolute paths, regardless of cwd."""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [REPO_ROOT / p for p in out.stdout.split("\0") if p]


def collect() -> dict[str, set[Path]]:
    urls: dict[str, set[Path]] = defaultdict(set)
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in URL_RE.findall(text):
            normalized = raw.rstrip(TRAILING_PUNCTUATION)
            if normalized:
                urls[normalized].add(path)
    return urls


def _allowlisted(url: str, status: int) -> str | None:
    """The allowlist reason if `status` is the documented-expected outcome
    for `url`, else None."""
    for pattern, expected, reason in ALLOWLIST:
        if status in expected and pattern.match(url):
            return reason
    return None


def _open(url: str, method: str):
    return urlopen(Request(url, method=method, headers={"User-Agent": "curl/8"}), timeout=TIMEOUT)


def _classify_http_error(url: str, e: HTTPError) -> tuple[str, str]:
    reason = _allowlisted(url, e.code)
    if reason is not None:
        return "allow", f"HTTP {e.code} ({reason})"
    return "warn", f"HTTP {e.code}"


def _classify_connect_error(e: BaseException) -> tuple[str, str]:
    """Map a request-layer failure to a bucket. Only signals that actually
    demonstrate something about the host's reachability/ownership FAIL;
    everything else — including DNS failure, which could be a transient
    resolver hiccup rather than a dead domain — is inconclusive (WARN)."""
    reason = e.reason if isinstance(e, URLError) else e
    if isinstance(reason, socket.gaierror):
        return "warn", "DNS did not resolve (may be a transient resolver failure — inconclusive)"
    if isinstance(reason, ConnectionRefusedError):
        return "fail", "connection refused — host resolves but nothing answers on the port"
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "fail", f"TLS certificate does not verify ({reason.verify_message})"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "warn", "connection timed out (transient — inconclusive)"
    return "warn", type(reason).__name__


def check(url: str) -> tuple[str, str]:
    """Classify one URL. Returns (bucket, detail); bucket is one of
    'ok' | 'allow' | 'warn' | 'fail'. Never raises — a malformed URL is a
    WARN about that URL, not a crash of the whole run."""
    if "\\" in url:
        # Backslash is not a valid URI character (RFC 3986) — the regex
        # picked up something that only *looks* like a URL, most often a
        # regex literal or Windows-style path fragment sitting in source
        # code (this file's own ALLOWLIST patterns being the prime example
        # of a URL-shaped string that isn't a URL).
        return "warn", "contains a literal backslash — not a valid URI, likely a mis-extracted match"
    try:
        host = urlparse(url).hostname
    except ValueError as e:
        return "warn", f"unparseable URL ({e})"
    if not host:
        return "warn", "no host found in URL"
    try:
        host.encode("idna")
    except UnicodeError as e:
        return "warn", f"host is not a valid hostname ({e}) — likely a mis-extracted URL"

    try:
        resp = _open(url, "HEAD")
    except HTTPError as e:
        if e.code not in (403, 405) or _allowlisted(url, e.code) is not None:
            return _classify_http_error(url, e)
        # Some servers reject HEAD outright; a real GET tells us more.
        try:
            resp = _open(url, "GET")
        except HTTPError as e2:
            return _classify_http_error(url, e2)
        except Exception as e2:  # noqa: BLE001 - one bad URL must not kill the run
            return _classify_connect_error(e2)
    except Exception as e:  # noqa: BLE001 - one bad URL must not kill the run
        return _classify_connect_error(e)

    resp.close()
    return "ok", ""


def main() -> int:
    urls = collect()
    allow: list[tuple[str, str]] = []
    warn: list[tuple[str, str]] = []
    fail: list[tuple[str, str, set[Path]]] = []

    for url in sorted(urls):
        bucket, detail = check(url)
        if bucket == "allow":
            allow.append((url, detail))
        elif bucket == "warn":
            warn.append((url, detail))
        elif bucket == "fail":
            fail.append((url, detail, urls[url]))

    print(f"{len(urls)} distinct URLs in tracked files")
    if allow:
        print(f"\nAllowlisted ({len(allow)}) — known-expected, no action needed:")
        for url, detail in allow:
            print(f"  {url}\n      {detail}")
    if warn:
        print(f"\nWARN — inconclusive, eyeball these ({len(warn)}):")
        for url, detail in warn:
            print(f"  {url}\n      {detail}")
    if fail:
        print(f"\nFAIL — confirmed dead ({len(fail)}):")
        for url, detail, where in fail:
            rel = ", ".join(sorted(str(p.relative_to(REPO_ROOT)) for p in where))
            print(f"  {url}\n      {detail}\n      in: {rel}")
        return 1
    print("\nNo dead hosts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
