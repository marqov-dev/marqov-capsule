"""CapsuleRedactor — best-effort credential scan run before sealing a capsule.

This is a **best-effort** scanner, not a guarantee. It is modelled on how
production scanners (gitleaks, trufflehog, detect-secrets) actually work, and
inherits their honest framing: a clean scan means no *known* credential shape
was found — it does not prove the capsule is free of secrets. Regex shape rules
may miss novel or reshaped tokens (recall is bounded); the entropy tier may
require tuning for a given corpus (precision is bounded). See
``docs/research/2026-08-11-credential-detection.md`` for the full rationale.

Two tiers, following the arrangement every upstream scanner uses (#18):

* **Tier A — distinctive shape rules → BLOCK.** Prefix-anchored value shapes
  (AWS ``AKIA…``, GitHub ``ghp_…`` / ``github_pat_…``, Google ``AIza…``, Stripe,
  Slack, JWT, PEM private-key blocks), an IBM Quantum token rule expressed as
  *keyword proximity to a 64-char hex value* (never a bare ``\\b[a-f0-9]{64}\\b``,
  which would fire on every checksum), a small set of high-signal credential
  *name* assignments, and inline SDK constructors handed a literal token. These
  have near-zero false-positive rates and gate the seal.
* **Tier B — keyword proximity + charset-split entropy → WARN.** Entropy is used
  only as a *filter over a keyword/assignment candidate*, never as a standalone
  detector, with charset-specific thresholds (hex 3.0, base64 4.5) computed over
  the candidate's own charset and a length cap. Tier B is reported but never
  blocks — entropy cannot reliably separate a secret from a numerical payload.
"""

from __future__ import annotations

import json
import math
import re
import string
from pathlib import Path
from typing import Any

import yaml

from marqov_capsule._canonical import load_manifest_yaml

# ---------------------------------------------------------------------------
# Tier A — distinctive value-shape rules (block). Prefix-anchored, low FP.
# Regexes adapted from gitleaks' ruleset (research note §6). The captured
# secret is group("val") where present, else group(0).
# ---------------------------------------------------------------------------
_SHAPE_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "aws_access_key_id",
        re.compile(r"\b(?P<val>(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16})\b"),
    ),
    ("github_token", re.compile(r"\b(?P<val>gh[pousr]_[0-9A-Za-z]{36})\b")),
    ("github_fine_grained_pat", re.compile(r"\b(?P<val>github_pat_\w{82})\b")),
    ("google_api_key", re.compile(r"\b(?P<val>AIza[0-9A-Za-z_\-]{35})\b")),
    ("stripe_key", re.compile(r"\b(?P<val>(?:sk|rk)_(?:test|live|prod)_[0-9A-Za-z]{10,99})\b")),
    ("slack_token", re.compile(r"(?P<val>xox[baprs]-[0-9]{10,13}-[0-9A-Za-z-]{10,})")),
    (
        "jwt",
        re.compile(
            r"\b(?P<val>ey[0-9A-Za-z]{10,}\.ey[0-9A-Za-z/\\_-]{10,}\.[0-9A-Za-z/\\_.+-]{5,})"
        ),
    ),
]

# PEM private-key block — a multi-line shape, scanned against the whole file
# rather than line by line (a line-oriented scan never sees BEGIN and END on the
# same line). ``-----BEGIN CERTIFICATE-----`` is not a private key and is left
# to the credential-file filename rule.
#
# BEGIN and END are matched separately and paired by position (see
# ``_iter_private_key_blocks``). A single regex with a lazy ``[\s\S]{16,}?``
# between them re-scanned to end-of-file from every BEGIN that had no END, so
# a file of BEGIN markers cost O(n²): 7 s per 200 KB, hours per 10 MB (#126).
_PEM_BEGIN_RE = re.compile(r"-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----")
_PEM_END_RE = re.compile(r"-----END[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----")
_PEM_MIN_BODY = 16
_PEM_MAX_BLOCK = 64 * 1024  # a PEM body is never more than a few KB

# IBM Quantum token: keyword proximity to a 64-char hex value. There is no
# upstream rule for this shape; expressed as proximity precisely because a bare
# 64-hex rule would match every sha256 in a checksum manifest (research §7).
_HEX64_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
_IBM_KEYWORD_RE = re.compile(r"ibmq?|qiskit|quantum|token|api[_.-]?key", re.IGNORECASE)
_IBM_PROXIMITY = 40  # chars either side, mirroring trufflehog's PrefixRegex

# High-signal credential *names*. A bare name can no longer match: an operator
# and a captured literal value are required (research §5). Case-insensitive, so
# ``ibm_quantum_token`` matches as well as ``IBM_QUANTUM_TOKEN`` (#18).
_KNOWN_NAME_RE = re.compile(
    r"\b(?P<name>IBM_QUANTUM_TOKEN|IBMQ_TOKEN|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|"
    r"GITHUB_TOKEN|AZURE_QUANTUM_[A-Z0-9_]+)\b"
    r"['\"]?\s*[:=]\s*['\"]?(?P<val>[^'\"\n]{1,200})",
    re.IGNORECASE,
)

# Inline SDK constructors handed a *quoted literal* token. ``Service(token=var)``
# (passing a variable read from the environment) is safe and does not match.
#
# Matched in two linear steps (see ``_iter_constructor_literals``): the keyword
# literal is found first, then the text immediately before it is checked for
# an open ``Name(`` within a bounded window. The old single regex,
# ``Name\s*\([^)]*?keyword=``, scanned to end of line from every ``Name(`` that
# had no closing paren — 27 s per 100 KB line of ``IBMQ(`` (#126).
_CONSTRUCTOR_KW_RE = re.compile(
    r"(?:token|credentials?|api_?key|secret)\s*=\s*['\"](?P<val>[^'\"\n]{3,200})['\"]",
    re.IGNORECASE,
)
_CONSTRUCTOR_NAME_RE = re.compile(
    r"(?:QiskitRuntimeService|IBMProvider|IBMQ|AWSSession)\s*$",
    re.IGNORECASE,
)
_CONSTRUCTOR_WINDOW = 300  # chars of argument list allowed before the keyword

# ---------------------------------------------------------------------------
# Tier B — keyword proximity + charset-split entropy (warn, never block).
# ---------------------------------------------------------------------------
# Generic name family: name + operator + value + entropy (research §5), minus an
# allowlist of key-shaped-but-benign names (PUBLIC_KEY / PRIMARY_KEY / …).
_GENERIC_NAME_RE = re.compile(
    r"\b(?P<name>[A-Za-z][A-Za-z0-9]*(?:[_.-][A-Za-z0-9]+)*"
    r"(?:_KEY|_SECRET|_TOKEN|_PASSWORD|_PASSWD|_CREDENTIAL|_CREDENTIALS|_APIKEY|_API_KEY))\b"
    r"['\"]?\s*[:=]\s*['\"]?(?P<val>[^'\"\n]{1,200})",
    re.IGNORECASE,
)
_NAME_ALLOWLIST_RE = re.compile(
    r"^(?:bucket|foreign|hot|idx|natural|primary|pub(?:lic)?|schema|sequence|"
    r"sort(?:ing)?|partition|cluster|composite|shard|index|group)[_.-]?key$"
    r"|key[_.-]?(?:alias|board|code|id|name|pair|ring|size|word|store|space|stroke)$",
    re.IGNORECASE,
)

# Values that are references / placeholders, not embedded secrets.
_VALUE_REJECT_RE = re.compile(
    r"os\.environ|getenv|process\.env|environ\[|\$\{|\$[A-Za-z_]|%[A-Za-z_]+%|<[^>]*>",
    re.IGNORECASE,
)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

_HEX_CHARSET = "0123456789abcdef"
_BASE64_CHARSET = string.ascii_letters + string.digits + "+/=-_"
_HEX_ENTROPY_THRESHOLD = 3.0
_BASE64_ENTROPY_THRESHOLD = 4.5
_MIN_ENTROPY_LEN = 20
_MAX_ENTROPY_LEN = 200  # length cap — safe only because Tier A catches long
#                         structured secrets (PEM/JWT/prefixed); see note §9.

# Backwards-compatible aliases (the research reproduction imports these).
_HIGH_ENTROPY_THRESHOLD = _BASE64_ENTROPY_THRESHOLD
_MIN_ENTROPY_LENGTH = _MIN_ENTROPY_LEN

# Digest / checksum lines — never a secret. Covers named digest fields, any
# algorithm-labelled hash (``sha256:<hex>``, the .checksums manifest format),
# so lowering the hex threshold below the sha256 ceiling cannot fire on them.
_DIGEST_LINE_RE = re.compile(
    r"(?:checksums_digest|derived_from|\w+_digest)\s*[:=]\s*['\"]?(?:sha\d+:)?[0-9a-f]{64}"
    r"|(?:sha1|sha224|sha256|sha384|sha512|blake2[bs]|md5|digest|hash|checksum)"
    r"\s*[:=]\s*['\"]?[0-9a-f]{32,128}",
    re.IGNORECASE,
)

# Versioned provenance IDs are content hashes. Mask only the value, preserving
# offsets and every other field on the line for credential detection.
_DERIVED_ID_RE = re.compile(
    r"\bderived_from['\"]?\s*:\s*['\"]?(?P<id>mqc:[0-9]+:[0-9a-f]{64})(?=['\"\s,}]|$)"
)

# ``# capsule:allow`` — narrowed from "suppress the whole line" to "suppress
# this finding" (like ``#gitleaks:allow``). Matched with or without the space so
# a minified single-line file cannot disable scanning of the rest of the line.
_ALLOW_RE = re.compile(r"#\s*capsule:allow", re.IGNORECASE)

# Build noise. Never worth scanning, and a .capsuleignore may add to this set
# but never remove from it — otherwise a capsule could un-skip nothing useful
# while narrowing scope elsewhere.
_SCAN_SKIP_DEFAULTS = {
    ".git",
    "__pycache__",
    "*.pyc",
    "venv",
    ".venv",
    "node_modules",
}

# Credential-shaped filenames. These were previously in the ignore set, which
# had it exactly backwards: the file was excluded from *scanning* while
# save_checksums still packaged it, so a directory holding .env and deploy.key
# scanned clean and sealed with both inside (#34). Presence is the finding —
# not scanning a secret does not make it absent from the capsule. Extension
# matching is case-insensitive and ``.env`` matches ``.env.local`` etc (#18).
_CREDENTIAL_EXACT_NAMES = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}
_CREDENTIAL_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".bak", ".keystore", ".jks"}


class RedactorError(Exception):
    """Raised when block mode finds credentials."""


def _shannon_entropy(s: str) -> float:
    """Shannon entropy over the string's own alphabet. Retained for reference;
    the tiered detector uses :func:`_charset_entropy` instead."""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((f / n) * math.log2(f / n) for f in freq.values())


def _charset_entropy(s: str, charset: str) -> float:
    """Entropy computed over ``charset`` rather than the string's own alphabet,
    as detect-secrets does. The same string scores differently under the hex
    and base64 charsets, which is why the thresholds are charset-specific."""
    if not s:
        return 0.0
    n = len(s)
    entropy = 0.0
    for x in charset:
        p_x = s.count(x) / n
        if p_x > 0:
            entropy -= p_x * math.log2(p_x)
    return entropy


def _redact_value(value: str) -> str:
    """Report a value without leaking it — a short locating prefix, masked."""
    v = value.strip().strip("'\"").strip()
    if not v:
        return "***"
    if len(v) <= 6:
        return v[:2] + "***"
    return v[:4] + "…" + "*" * min(len(v) - 4, 8)


def _looks_like_digest_line(line: str) -> bool:
    return bool(_DIGEST_LINE_RE.search(line))


def _is_credential_file(rel_path: str) -> bool:
    """Credential-shaped filename check: case-insensitive, ``.env`` family, and
    the credential extensions. Runs independently of the scan-skip ignore set."""
    name = Path(rel_path).name
    lower = name.lower()
    if lower in _CREDENTIAL_EXACT_NAMES:
        return True
    if lower == ".env" or lower.startswith(".env."):
        return True
    return any(lower.endswith(ext) for ext in _CREDENTIAL_EXTENSIONS)


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
    return {line.strip() for line in lines if line.strip() and not line.strip().startswith("#")}


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


def _is_embedded_value(value: str) -> bool:
    """A high-signal credential *name* (IBM_QUANTUM_TOKEN, AWS_*, …) blocks on
    any embedded literal, not only high-entropy ones — the name carries the
    signal. But a reference (``os.environ[...]``) or placeholder is not embedded
    and must not block."""
    v = value.strip().strip("'\"").strip()
    return bool(v) and not _VALUE_REJECT_RE.search(v)


def _plausible_secret_value(value: str) -> bool:
    """A captured value that could be a secret: non-trivial, has a digit, and is
    not an environment reference / placeholder. Rejects ``^[A-Za-z_.-]+$`` — a
    value with no digit at all is not a secret (research §5.3)."""
    v = value.strip().strip("'\"").strip()
    if len(v) < 4 or v.isspace():
        return False
    if _VALUE_REJECT_RE.search(v):
        return False
    if re.fullmatch(r"[A-Za-z_.\-]+", v):
        return False
    return True


def _entropy_reason(candidate: str) -> str | None:
    """Charset-split entropy verdict for a candidate, or None. Returns the
    finding reason so hex and base64 hits are distinguishable in a report."""
    if _UUID_RE.match(candidate) or candidate.isdigit():
        return None
    if re.fullmatch(r"[0-9A-Fa-f]+", candidate):
        if _charset_entropy(candidate.lower(), _HEX_CHARSET) >= _HEX_ENTROPY_THRESHOLD:
            return "high_entropy_hex"
        return None
    if re.fullmatch(r"[A-Za-z0-9+/=_\-]+", candidate):
        # Base64 secrets carry digits; identifier-like names do not.
        if not any(c.isdigit() for c in candidate):
            return None
        if _charset_entropy(candidate, _BASE64_CHARSET) >= _BASE64_ENTROPY_THRESHOLD:
            return "high_entropy_base64"
    return None


def _iter_entropy_candidates(line: str):
    """Yield ``(value, start, end, reason)`` for entropy candidates that appear
    in quoting or assignment context (research §9.4). Maximal tokens only: an
    over-length token (e.g. a base64 statevector) is skipped by the length cap,
    never truncated to its cap-length prefix and matched."""
    # Exclude '=' from the token so an unquoted ``KEY=value`` splits on the
    # operator (rather than merging into one token); base64 padding '=' is
    # immaterial to the entropy score, which is computed over the charset.
    for m in re.finditer(r"[A-Za-z0-9+/_\-]+", line):
        tok = m.group(0)
        if not (_MIN_ENTROPY_LEN <= len(tok) <= _MAX_ENTROPY_LEN):
            continue
        before = line[: m.start()].rstrip()
        if not before or before[-1] not in "'\"=:":
            continue  # not quoted / not an assignment RHS
        reason = _entropy_reason(tok)
        if reason:
            yield tok, m.start(), m.end(), reason


def _iter_private_key_blocks(text: str):
    """Yield ``(start, end)`` spans of PEM private-key blocks, in linear time.

    END markers are located once; each BEGIN is paired with the first END that
    follows it (``bisect``), accepted when the body is at least
    ``_PEM_MIN_BODY`` chars and the whole block at most ``_PEM_MAX_BLOCK``.
    BEGIN markers that fall inside an accepted block are skipped.
    """
    import bisect

    ends = [(m.start(), m.end()) for m in _PEM_END_RE.finditer(text)]
    end_starts = [s for s, _ in ends]
    resume = 0
    for begin in _PEM_BEGIN_RE.finditer(text):
        if begin.start() < resume:
            continue
        i = bisect.bisect_left(end_starts, begin.end() + _PEM_MIN_BODY)
        if i == len(ends):
            return  # no END after this BEGIN: nothing later can match either
        end_start, end_end = ends[i]
        if end_end - begin.start() > _PEM_MAX_BLOCK:
            continue
        yield begin.start(), end_end
        resume = end_end


def _iter_constructor_literals(line: str):
    """Yield keyword matches whose literal sits inside an open SDK constructor
    call: ``Name(`` with no ``)`` between it and the keyword, within
    ``_CONSTRUCTOR_WINDOW`` chars. Linear in the line length."""
    for kw in _CONSTRUCTOR_KW_RE.finditer(line):
        window = line[max(0, kw.start() - _CONSTRUCTOR_WINDOW) : kw.start()]
        open_paren = window.rfind("(")
        if open_paren == -1 or ")" in window[open_paren:]:
            continue
        if _CONSTRUCTOR_NAME_RE.search(window[:open_paren]):
            yield kw


def _finding_allowed(line: str, match_end: int) -> bool:
    """True if a ``# capsule:allow`` annotation suppresses the finding that ends
    at ``match_end``. Scoped to a trailing comment on the same statement: the
    annotation must appear after the match and before any ``,`` — so one literal
    inside a minified JSON value cannot disable a real token elsewhere."""
    tail = line[match_end:]
    comma = tail.find(",")
    region = tail if comma == -1 else tail[:comma]
    return bool(_ALLOW_RE.search(region))


def _scan_text(text: str, filepath: str, *, honor_allow: bool = True) -> list[dict]:
    findings: list[dict] = []

    # Multi-line shape: PEM private-key blocks, scanned across the whole file.
    for start, end in _iter_private_key_blocks(text):
        line_no = text.count("\n", 0, start) + 1
        newline = text.find("\n", start)
        begin_line = text[start : newline if newline != -1 else len(text)]
        if honor_allow and _ALLOW_RE.search(begin_line):
            continue
        findings.append(
            {
                "file": filepath,
                "line": line_no,
                "match": _redact_value(text[start:end]),
                "reason": "private_key_block",
                "blocking": True,
                "tier": "A",
            }
        )

    for i, line in enumerate(text.splitlines(), 1):
        for match in reversed(list(_DERIVED_ID_RE.finditer(line))):
            start, end = match.span("id")
            line = line[:start] + " " * (end - start) + line[end:]
        # Digest values are benign, but other fields on the same line may
        # contain credentials (e.g. compact JSON). Preserve their scan/offsets.
        line = _DIGEST_LINE_RE.sub(lambda m: " " * len(m.group(0)), line)

        # (start, end, finding) for this line, deduped and allow-filtered below.
        candidates: list[tuple[int, int, dict]] = []

        # `add` is called only within this loop iteration, so the `candidates`
        # and `i` it closes over are always the current line's (B023 is a
        # false positive here).
        def add(start: int, end: int, reason: str, value: str, blocking: bool, tier: str):
            candidates.append(  # noqa: B023
                (
                    start,
                    end,
                    {
                        "file": filepath,
                        "line": i,  # noqa: B023
                        "match": _redact_value(value),
                        "reason": reason,
                        "blocking": blocking,
                        "tier": tier,
                    },
                )
            )

        # --- Tier A: distinctive value shapes (block) ---
        for reason, rx in _SHAPE_RULES:
            for m in rx.finditer(line):
                val = m.groupdict().get("val") or m.group(0)
                add(m.start(), m.end(), reason, val, True, "A")

        # --- Tier A: IBM Quantum token = 64-hex + keyword proximity (block) ---
        for m in _HEX64_RE.finditer(line):
            lo = max(0, m.start() - _IBM_PROXIMITY)
            hi = min(len(line), m.end() + _IBM_PROXIMITY)
            if _IBM_KEYWORD_RE.search(line[lo:hi]):
                add(m.start(), m.end(), "ibm_quantum_token", m.group(0), True, "A")

        # --- Tier A: high-signal credential name = literal value (block) ---
        for m in _KNOWN_NAME_RE.finditer(line):
            val = m.group("val")
            if _is_embedded_value(val):
                add(m.start("val"), m.end("val"), "name_pattern", val, True, "A")

        # --- Tier A: SDK constructor handed a literal token (block) ---
        for m in _iter_constructor_literals(line):
            add(m.start("val"), m.end("val"), "constructor_pattern", m.group("val"), True, "A")

        # --- Tier B: generic key-name family + value entropy (warn) ---
        for m in _GENERIC_NAME_RE.finditer(line):
            name = m.group("name")
            if _NAME_ALLOWLIST_RE.search(name):
                continue
            val = m.group("val")
            if not _plausible_secret_value(val):
                continue
            add(m.start("val"), m.end("val"), "name_entropy", val, False, "B")

        # --- Tier B: quoted / assignment entropy candidates (warn) ---
        for val, start, end, reason in _iter_entropy_candidates(line):
            add(start, end, reason, val, False, "B")

        # Dedup overlaps (prefer the blocking finding), then apply allow scoping.
        candidates.sort(key=lambda c: (not c[2]["blocking"], c[0]))
        accepted: list[tuple[int, int]] = []
        for start, end, finding in candidates:
            if any(start < a_end and end > a_start for a_start, a_end in accepted):
                continue
            accepted.append((start, end))
            if honor_allow and _finding_allowed(line, end):
                continue
            findings.append(finding)

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

    def scan(value, cell_index, location):
        # ``line`` counts within the cell source or output being scanned, not
        # within the .ipynb file (which is JSON); ``cell`` (0-based) and
        # ``location`` are what let a reader find it (#100).
        for finding in _scan_text(_joined(value), nb_path):
            finding["cell"] = cell_index
            finding["location"] = location
            findings.append(finding)

    cells = nb.get("cells")
    if not isinstance(cells, list):
        # An int/bool raises on iteration; a string iterates per character.
        # Neither is a notebook (#125).
        return []
    for cell_index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            continue
        scan(cell.get("source"), cell_index, "source")

        outputs = cell.get("outputs")
        if not isinstance(outputs, list):
            continue
        for output_index, output in enumerate(outputs):
            if not isinstance(output, dict):
                continue
            location = f"output[{output_index}]"
            output_type = output.get("output_type", "")
            if output_type == "stream":
                scan(output.get("text"), cell_index, location)
            elif output_type in ("display_data", "execute_result"):
                data = output.get("data")
                if isinstance(data, dict) and "text/plain" in data:
                    scan(data["text/plain"], cell_index, location)
            elif output_type == "error":
                scan(output.get("traceback"), cell_index, location)
                scan(output.get("evalue"), cell_index, location)
    return findings


def finding_location(finding: dict) -> str:
    """Where a finding is, for a message: ``file:line``, or for a notebook
    ``file:cell N:line L`` / ``file:cell N:output[K]:line L``."""
    if "field" in finding:
        return f"{finding['file']}:field {finding['field']}"
    if "cell" not in finding:
        return f"{finding['file']}:{finding['line']}"
    where = f"{finding['file']}:cell {finding['cell']}"
    if finding.get("location", "source") != "source":
        where += f":{finding['location']}"
    return f"{where}:line {finding['line']}"


def _scan_manifest_values(content: str, existing: list[dict]) -> list[dict]:
    """Scan parsed scalar strings with their key context, independent of YAML layout."""
    try:
        manifest = load_manifest_yaml(content)
    except yaml.YAMLError:
        # Dry-run scanning also accepts unfinished drafts; their literal text
        # has already been scanned. Sealing separately enforces valid parsing.
        return []
    findings = []
    seen = {(f["reason"], f["match"]) for f in existing if f["file"] == "capsule.yaml"}

    def visit(value, keys, path):
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, keys + [key], path + [key])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, keys, path + [str(index)])
        elif isinstance(value, str):
            if (
                keys
                and keys[-1] == "derived_from"
                and re.fullmatch(r"mqc:[0-9]+:[0-9a-f]{64}", value)
            ):
                return  # A complete provenance ID is a known content hash.
            representations = [value]
            representations.extend(
                f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}"
                for key in keys
            )
            for representation in representations:
                # An allow-comment inside manifest data is not a source-code
                # annotation and must not disable a credential finding.
                for finding in _scan_text(representation, "capsule.yaml", honor_allow=False):
                    identity = (finding["reason"], finding["match"])
                    if identity in seen:
                        continue
                    seen.add(identity)
                    safe_path = [
                        "[redacted-key]" if _scan_text(p, "key", honor_allow=False) else p
                        for p in path
                    ]
                    finding.update(
                        line=0,
                        field="/"
                        + "/".join(p.replace("~", "~0").replace("/", "~1") for p in safe_path),
                    )
                    findings.append(finding)

    visit(manifest, [], [])
    return findings


# How much of a file is examined to decide it is binary: a NUL byte in the
# first 8 KB, the heuristic git uses.
_BINARY_SNIFF_BYTES = 8192


def _looks_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(_BINARY_SNIFF_BYTES)
    except OSError:
        return False


class CapsuleRedactor:
    """Scan a capsule directory for credentials before sealing.

    Args:
        capsule_dir: Root of the capsule directory.
        mode: "block" (default) raises RedactorError on *blocking* (Tier A /
               credential-file) findings. "warn_only" returns findings without
               raising. Tier B (entropy) findings warn but never block.
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

    def scan(self, overrides: dict[str, str] | None = None) -> dict[str, Any]:
        """Scan all files in capsule_dir for credentials.

        ``overrides`` maps a capsule-relative path to text that is scanned *in
        place of* the on-disk file of that name (or in addition to the tree, if
        no such file exists). The builder uses it to scan the manifest it is
        about to write without first writing it (#57, #121).

        Returns:
            ``has_secrets``, ``findings``, plus ``skipped`` (paths not scanned)
            and ``capsuleignore_patterns`` (what the capsule's own ignore file
            asked for). The last two exist so that narrowing the scan scope is
            visible rather than silent — a .capsuleignore containing ``source``
            would otherwise disable scanning for that whole subtree with no
            indication in the result (#34). ``skipped_binary`` lists files not
            scanned because they are binary: regex-matching a 64 MB array dump
            took 14 s and found nothing, and every scanner this module follows
            skips them — but it is reported, for the same reason (#98).
        """
        all_findings: list[dict] = []
        skipped: list[str] = []
        skipped_binary: list[str] = []
        pending = dict(overrides or {})

        # (relative path, source) where source is a Path to read or the text itself.
        entries: list[tuple[str, Any]] = []
        for file_path in sorted(self.capsule_dir.rglob("*")):
            # Do not follow symlinks — their target may live outside the capsule tree.
            if file_path.is_symlink():
                continue
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(self.capsule_dir).as_posix()
            entries.append((rel, pending.pop(rel) if rel in pending else file_path))
        entries.extend(sorted(pending.items()))

        for rel, source in entries:
            # Credential-shaped filenames are a packaging problem, not a scanning
            # one: the file is going into the capsule whether or not it is read.
            # Checked before the ignore test so .capsuleignore cannot suppress it.
            if _is_credential_file(rel):
                all_findings.append(
                    {
                        "file": rel,
                        "line": 0,
                        "match": rel,
                        "reason": "credential_file",
                        "blocking": True,
                        "tier": "file",
                    }
                )
                continue

            if rel != "capsule.yaml" and _is_ignored(rel, self._ignores):
                skipped.append(rel)
                continue

            if isinstance(source, Path):
                # Notebooks are JSON text and are always scanned.
                if not rel.endswith(".ipynb") and _looks_binary(source):
                    skipped_binary.append(rel)
                    continue
                try:
                    content = source.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
            else:
                content = source

            if rel.endswith(".ipynb"):
                all_findings.extend(_scan_notebook(rel, content))
            else:
                all_findings.extend(_scan_text(content, rel))
                if rel == "capsule.yaml":
                    # YAML layout can separate a credential name from a list
                    # value or wrap a keyword away from its token. Scan each
                    # parsed value with its ancestor keys on unwrapped lines.
                    all_findings.extend(_scan_manifest_values(content, all_findings))

        return {
            "has_secrets": len(all_findings) > 0,
            "findings": all_findings,
            "skipped": skipped,
            "skipped_binary": skipped_binary,
            "capsuleignore_patterns": sorted(self._capsuleignore),
        }

    def scan_and_raise(self, overrides: dict[str, str] | None = None) -> dict[str, Any]:
        """Scan and raise RedactorError if *blocking* secrets are found.

        Only Tier A (distinctive shape) and credential-file findings block the
        seal. Tier B (entropy) findings are returned as warnings but never raise
        — entropy cannot reliably tell a secret from a numerical payload.
        ``overrides`` is passed through to :meth:`scan`.
        """
        result = self.scan(overrides=overrides)
        blocking = [f for f in result["findings"] if f.get("blocking")]
        if blocking and self.mode == "block":
            summary = "; ".join(f"{finding_location(f)} ({f['reason']})" for f in blocking[:5])
            # Remediation has to match the finding. `# capsule:allow` is a
            # line annotation and cannot suppress a whole-file finding, so
            # offering it for a .env would send the user down a dead end.
            credential_files = [f["file"] for f in blocking if f["reason"] == "credential_file"]
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
