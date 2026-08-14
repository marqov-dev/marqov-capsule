#!/usr/bin/env python3
"""Check that every URL in tracked files resolves.

Nothing fetches a prose URL, so no unit test catches a dead one — it ships and
a reader finds it. This is the class of defect that put `platform.marqov.com`
into marqov-sdk 0.3.0.

Fails only on **non-resolving hosts** (DNS failure), which is the unambiguous
signal. A 4xx from an auth-gated API, or a transient timeout, is a WARN — eyeball
those rather than letting an outage on release day block a tag.

Usage:  python tools/check_urls.py        # exit 0 = no dead hosts
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
from collections import defaultdict
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

URL_RE = re.compile(r"https?://[^\s\"'<>)\]`,]+")
TIMEOUT = 8


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return out.stdout.split()


def collect() -> dict[str, set[str]]:
    urls: dict[str, set[str]] = defaultdict(set)
    for path in tracked_files():
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except (OSError, IsADirectoryError):
            continue
        for raw in URL_RE.findall(text):
            urls[raw.rstrip(".,;\\")].add(path)
    return urls


def main() -> int:
    urls = collect()
    dead: list[tuple[str, set[str]]] = []
    warn: list[tuple[str, str]] = []

    for url in sorted(urls):
        host = urlparse(url).hostname
        if not host:
            continue
        try:
            socket.getaddrinfo(host, None)
        except socket.gaierror:
            dead.append((url, urls[url]))
            continue
        try:
            urlopen(Request(url, method="HEAD", headers={"User-Agent": "curl/8"}), timeout=TIMEOUT)
        except HTTPError as e:
            warn.append((url, f"HTTP {e.code}"))
        except (URLError, TimeoutError, OSError) as e:
            warn.append((url, type(e).__name__))

    print(f"{len(urls)} distinct URLs in tracked files")
    if warn:
        print(f"\nWARN — resolves but non-200 ({len(warn)}), eyeball these:")
        for url, why in warn:
            print(f"  {why:>12}  {url}")
    if dead:
        print(f"\nFAIL — host does not resolve ({len(dead)}):")
        for url, where in dead:
            print(f"  {url}\n      in: {', '.join(sorted(where))}")
        return 1
    print("\nNo dead hosts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
