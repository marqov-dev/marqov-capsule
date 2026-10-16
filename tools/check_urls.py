#!/usr/bin/env python3
"""Check tracked URL syntax and Marqov hosts; report network availability.

Static policy failures block release. Network failures are inconclusive warnings,
not evidence of domain ownership. Use --offline for the deterministic CI gate.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
URL_RE = re.compile(r"https?://[^\s\"'<>`)]+")
TIMEOUT = 8
MARQOV_HOSTS = {"marqov.ai", "app.marqov.ai"}
# A schema identifier is not a promised downloadable resource.
IDENTIFIERS = {"https://marqov.ai/schemas/capsule/v1/capsule-schema.json"}


def tracked_files(root: Path = ROOT) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    return [os.fsdecode(path) for path in out.stdout.split(b"\0") if path]


def collect(root: Path = ROOT) -> dict[str, set[str]]:
    urls: dict[str, set[str]] = defaultdict(set)
    for path in tracked_files(root):
        try:
            with (root / path).open(encoding="utf-8", errors="replace") as stream:
                text = stream.read()
        except (OSError, IsADirectoryError):
            continue
        for raw in URL_RE.findall(text):
            raw = raw.rstrip(".,;!\\")
            if "[" not in raw:
                raw = raw.rstrip("]")
            urls[raw].add(path)
    return urls


def normalize(url: str) -> str:
    """Validate each extracted URL before any network call; encode Unicode."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("missing HTTP(S) host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("embedded URL credentials are not allowed")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    port = parsed.port  # validates malformed/out-of-range ports
    if ":" in host:
        ipaddress.IPv6Address(host)
        host = "[" + host + "]"
    elif len(host) > 253 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in host.rstrip(".").split(".")
    ):
        raise ValueError("invalid hostname")
    if port is not None:
        host += f":{port}"
    return urlunsplit(
        (
            parsed.scheme,
            host,
            quote(parsed.path, safe="/%:@+~!$&'()*;,=-._"),
            quote(parsed.query, safe="=&?/%:@+~!$'()*;,.-_"),
            "",
        )
    )


def policy_error(url: str) -> str | None:
    host = urlsplit(url).hostname.rstrip(".")
    if "marqov" in host.split(".") and host not in MARQOV_HOSTS:
        return "Marqov host is not in the reviewed allowlist"
    return None


def probe(url: str) -> str | None:
    """Network failures remain warnings; HEAD restrictions retry using GET."""
    for method in ("HEAD", "GET"):
        try:
            with urlopen(
                Request(url, method=method, headers={"User-Agent": "marqov-capsule-link-check"}),
                timeout=TIMEOUT,
            ):
                return None
        except HTTPError as error:
            code = error.code
            error.close()
            if method == "HEAD" and code in {403, 405}:
                continue
            return f"HTTP {code}"
        except (URLError, TimeoutError, OSError, ValueError, UnicodeError) as error:
            return type(error).__name__
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Only check syntax and host policy")
    args = parser.parse_args(argv)
    urls = collect()
    failures = []
    network = []
    for raw, files in sorted(urls.items()):
        try:
            url = normalize(raw)
            reason = policy_error(url)
        except (ValueError, UnicodeError) as error:
            reason = f"invalid URL ({type(error).__name__})"
        if reason:
            failures.append((raw, reason, files))
        elif url not in IDENTIFIERS:
            network.append(url)
    print(f"{len(urls)} distinct URLs in tracked files")
    for raw, reason, files in failures:
        print(f"FAIL: {raw!r}: {reason}; in {', '.join(sorted(files))}")
    if not args.offline:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for url, warning in zip(network, pool.map(probe, network)):
                if warning:
                    print(f"WARN: {url!r}: {warning}; review availability/access manually")
        print("Network results do not establish ownership or release readiness.")
    print(f"Static URL checks: {'FAIL' if failures else 'PASS'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
