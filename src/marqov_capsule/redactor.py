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

# Build noise. Never worth scanning, and a .capsuleignore may add to this set
# but never remove from it — otherwise a capsule could un-skip nothing useful
# while narrowing scope elsewhere.
_SCAN_SKIP_DEFAULTS = {
    ".git", "__pycache__", "*.pyc", "venv", ".venv", "node_modules",
}

# Credential-shaped filenames. These were previously in the ignore set, which
# had it exactly backwards: the file was excluded from *scanning* while
# save_checksums still packaged it, so a directory holding .env and deploy.key
# scanned clean and sealed with both inside (#34). Presence is the finding —
# not scanning a secret does not make it absent from the capsule.
_CREDENTIAL_FILE_PATTERNS = {".env", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa", "id_ed25519"}

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
    """Read .capsuleignore patterns. Returns only what the file declared.

    Callers must union this with _SCAN_SKIP_DEFAULTS rather than substituting
    it. Replacing the defaults was the old behaviour and is a trust bug: the
    file lives *inside* the capsule, so a capsule received from someone else
    and re-sealed carries its author's scan scope, not yours (#34).
    """
    ignore_file = capsule_dir / ".capsuleignore"
    if not ignore_file.exists():
        return set()
    try:
        lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return set()
    return {
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("#")
    }


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
        self._capsuleignore = _load_capsuleignore(self.capsule_dir)
        # Union, never substitution: a capsule may widen what is skipped as
        # noise, but the defaults always apply.
        self._ignores = set(_SCAN_SKIP_DEFAULTS) | self._capsuleignore
        #: Patterns this capsule's own .capsuleignore asked for. Public so a
        #: caller can report narrowed scope without paying for a full scan.
        self.capsuleignore_patterns = sorted(self._capsuleignore)

    def scan(self) -> dict[str, Any]:
        """Scan all files in capsule_dir for credentials.

        Returns:
            ``has_secrets``, ``findings``, plus ``skipped`` (paths not scanned)
            and ``capsuleignore_patterns`` (what the capsule's own ignore file
            asked for). The last two exist so that narrowing the scan scope is
            visible rather than silent — a .capsuleignore containing ``source``
            would otherwise disable scanning for that whole subtree with no
            indication in the result (#34).
        """
        all_findings: list[dict] = []
        skipped: list[str] = []

        for file_path in sorted(self.capsule_dir.rglob("*")):
            # Do not follow symlinks — their target may live outside the capsule tree.
            if file_path.is_symlink():
                continue
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(self.capsule_dir))

            # Credential-shaped filenames are a packaging problem, not a scanning
            # one: the file is going into the capsule whether or not it is read.
            # Checked before the ignore test so .capsuleignore cannot suppress it.
            if _is_ignored(rel, _CREDENTIAL_FILE_PATTERNS):
                all_findings.append({
                    "file": rel,
                    "line": 0,
                    "match": rel,
                    "reason": "credential_file",
                })
                continue

            if _is_ignored(rel, self._ignores):
                skipped.append(rel)
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            if file_path.suffix == ".ipynb":
                all_findings.extend(_scan_notebook(rel, content))
            else:
                all_findings.extend(_scan_text(content, rel))

        return {
            "has_secrets": len(all_findings) > 0,
            "findings": all_findings,
            "skipped": skipped,
            "capsuleignore_patterns": sorted(self._capsuleignore),
        }

    def scan_and_raise(self) -> dict[str, Any]:
        """Scan and raise RedactorError if secrets found (block mode)."""
        result = self.scan()
        if result["has_secrets"] and self.mode == "block":
            summary = "; ".join(
                f"{f['file']}:{f['line']} ({f['reason']})"
                for f in result["findings"][:5]
            )
            # Remediation has to match the finding. `# capsule:allow` is a
            # line annotation and cannot suppress a whole-file finding, so
            # offering it for a .env would send the user down a dead end.
            credential_files = [
                f["file"] for f in result["findings"] if f["reason"] == "credential_file"
            ]
            if credential_files:
                advice = (
                    f"Credential-bearing file(s) in the capsule: "
                    f"{', '.join(sorted(set(credential_files)))}. "
                    f"Move them outside the capsule directory — they would otherwise be "
                    f"packaged and sealed inside it."
                )
            else:
                advice = "Remove secrets or annotate with # capsule:allow to suppress."
            raise RedactorError(
                f"Credential patterns found — seal blocked. Findings: {summary}. {advice}"
            )
        return result
