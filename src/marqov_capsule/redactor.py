"""CapsuleRedactor — scans capsule content for credentials before sealing."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any


# Name-based patterns: env var names and constructor patterns
_NAME_PATTERNS = [
    re.compile(r"\bIBM_QUANTUM_TOKEN\b"),
    re.compile(r"\bAWS_ACCESS_KEY_ID\b"),
    re.compile(r"\bAWS_SECRET_ACCESS_KEY\b"),
    re.compile(r"\bGITHUB_TOKEN\b"),
    re.compile(r"\bAZURE_QUANTUM_\w+\b"),
    re.compile(r"\b\w+(_KEY|_SECRET|_TOKEN|_PASSWORD|_CREDENTIAL)\b"),
    re.compile(r"IBMProvider\s*\(\s*token\s*="),
    re.compile(r"QiskitRuntimeService\s*\(\s*token\s*="),
    re.compile(r"AWSSession\s*\(\s*credentials\s*="),
]

# Spec-defined digest field lines — never flagged by entropy heuristic
_DIGEST_LINE_RE = re.compile(
    r"(?:checksums_digest|derived_from|\w+_digest)\s*:\s*(?:sha256:)?[0-9a-f]{64}"
)

# Default excluded paths (applied when no .capsuleignore present)
_DEFAULT_IGNORES = {
    ".git", "__pycache__", "*.pyc", "venv", ".venv",
    "node_modules", ".env", "*.pem", "*.key",
}

_HIGH_ENTROPY_THRESHOLD = 4.5  # bits/char — applied to strings > 20 chars
_MIN_ENTROPY_LENGTH = 20


class RedactorError(Exception):
    """Raised when block mode finds credentials."""


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((f / n) * math.log2(f / n) for f in freq.values())


def _looks_like_digest_line(line: str) -> bool:
    return bool(_DIGEST_LINE_RE.search(line))


def _load_capsuleignore(capsule_dir: Path) -> set[str]:
    ignore_file = capsule_dir / ".capsuleignore"
    if not ignore_file.exists():
        return set(_DEFAULT_IGNORES)
    patterns = set()
    for line in ignore_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.add(line)
    return patterns


def _is_ignored(rel_path: str, ignores: set[str]) -> bool:
    parts = Path(rel_path).parts
    for pattern in ignores:
        if pattern.startswith("*."):
            ext = pattern[1:]
            if rel_path.endswith(ext):
                return True
        else:
            if pattern in parts or rel_path == pattern:
                return True
    return False


def _scan_text(text: str, filepath: str) -> list[dict]:
    findings = []
    for i, line in enumerate(text.splitlines(), 1):
        # Skip digest-field lines — they contain long hex strings by design
        if _looks_like_digest_line(line):
            continue
        # capsule:allow annotation suppresses ALL pattern matching on this line
        if "# capsule:allow" in line:
            continue
        # Name-based patterns
        for pat in _NAME_PATTERNS:
            m = pat.search(line)
            if m:
                findings.append({
                    "file": filepath,
                    "line": i,
                    "match": m.group(0),
                    "reason": "name_pattern",
                })
                break
        # Entropy heuristic on text values
        tokens = re.findall(r"[A-Za-z0-9+/=_\-]{%d,}" % _MIN_ENTROPY_LENGTH, line)
        for token in tokens:
            if _shannon_entropy(token) > _HIGH_ENTROPY_THRESHOLD:
                findings.append({
                    "file": filepath,
                    "line": i,
                    "match": token[:40] + "...",
                    "reason": "high_entropy",
                })
                break

    return findings


def _joined(value: Any) -> str:
    """nbformat allows multiline fields as either a string or a list of lines."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(v for v in value if isinstance(v, str))
    return ""


def _scan_notebook(nb_path: str, content: str) -> list[dict]:
    """Scan Jupyter notebook source cells and text outputs; skip binary MIME types.

    Source cells matter most: a pasted token lives in the code a researcher wrote,
    not in what it printed. Scanning only `outputs` meant a live token in a code
    cell passed the seal gate that the same line in a .py file would have blocked
    (#33). Error tracebacks are scanned too — they echo the offending line.

    Every field is defensively typed. A notebook is untrusted input and may be
    hand-edited or truncated; a malformed one must scan to nothing, not raise.
    """
    import json as _json
    try:
        nb = _json.loads(content)
    except Exception:
        return []
    if not isinstance(nb, dict):
        return []

    findings = []
    for cell in nb.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        findings.extend(_scan_text(_joined(cell.get("source")), nb_path))

        for output in cell.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            output_type = output.get("output_type", "")
            if output_type == "stream":
                findings.extend(_scan_text(_joined(output.get("text")), nb_path))
            elif output_type in ("display_data", "execute_result"):
                data = output.get("data")
                if isinstance(data, dict) and "text/plain" in data:
                    findings.extend(_scan_text(_joined(data["text/plain"]), nb_path))
            elif output_type == "error":
                findings.extend(_scan_text(_joined(output.get("traceback")), nb_path))
                findings.extend(_scan_text(_joined(output.get("evalue")), nb_path))
    return findings


class CapsuleRedactor:
    """Scan a capsule directory for credentials before sealing.

    Args:
        capsule_dir: Root of the capsule directory.
        mode: "block" (default) raises RedactorError on findings.
               "warn_only" returns findings without raising.
    """

    def __init__(self, capsule_dir: str | Path, mode: str = "block"):
        self.capsule_dir = Path(capsule_dir)
        if mode not in ("block", "warn_only"):
            raise ValueError(f"mode must be 'block' or 'warn_only', got {mode!r}")
        self.mode = mode
        self._ignores = _load_capsuleignore(self.capsule_dir)

    def scan(self) -> dict[str, Any]:
        """Scan all files in capsule_dir for credentials.

        Returns:
            {"has_secrets": bool, "findings": [{"file", "line", "match", "reason"}]}
        """
        all_findings: list[dict] = []

        for file_path in sorted(self.capsule_dir.rglob("*")):
            # Do not follow symlinks — their target may live outside the capsule tree.
            if file_path.is_symlink():
                continue
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(self.capsule_dir))
            if _is_ignored(rel, self._ignores):
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            if file_path.suffix == ".ipynb":
                all_findings.extend(_scan_notebook(rel, content))
            else:
                all_findings.extend(_scan_text(content, rel))

        return {"has_secrets": len(all_findings) > 0, "findings": all_findings}

    def scan_and_raise(self) -> dict[str, Any]:
        """Scan and raise RedactorError if secrets found (block mode)."""
        result = self.scan()
        if result["has_secrets"] and self.mode == "block":
            summary = "; ".join(
                f"{f['file']}:{f['line']} ({f['reason']})"
                for f in result["findings"][:5]
            )
            raise RedactorError(
                f"Credential patterns found — seal blocked. Findings: {summary}. "
                f"Remove secrets or annotate with # capsule:allow to suppress."
            )
        return result
