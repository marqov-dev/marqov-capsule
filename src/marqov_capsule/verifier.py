"""CapsuleVerifier — integrity verification and equivalence testing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import warnings
from numbers import Integral
from pathlib import Path
from typing import Any, NoReturn, Optional, Union

import yaml

from marqov_capsule._canonical import compute_capsule_id, load_manifest_yaml, parse_capsule_id
from marqov_capsule.builder import MAX_CHECKSUM_PATH_BYTES, UNCHECKSUMMED_ROOT_FILES, _checksum_path
from marqov_capsule.policy import resolve_alpha


def _is_within_root(rel_path: str, root: Path) -> bool:
    """True if ``root / rel_path`` stays inside ``root``.

    Rejects absolute paths and ``..`` escapes. Uses lexical normalisation
    anchored at an *absolute* root (not bare ``normpath``) so the check is
    independent of symlinks — those are handled separately by the caller — and
    so a capsule addressed as ``.`` does not false-alarm (#60): bare
    ``normpath('.')`` stays ``'.'`` while ``normpath('./rel')`` becomes ``rel``,
    which never shares the ``'.'`` prefix.
    """
    if os.path.isabs(rel_path):
        return False
    root_str = os.path.abspath(str(root))
    full = os.path.abspath(os.path.join(root_str, rel_path))
    return full == root_str or full.startswith(root_str + os.sep)


# Upper bound on a .checksums path, in bytes. Longer than any real filesystem
# allows (PATH_MAX is 4096 on Linux, 1024 on macOS), so a legitimate capsule
# never hits it; it exists so a hostile entry is rejected at parse time rather
# than by the OS mid-check (#123).
_MAX_CHECKSUM_PATH_BYTES = MAX_CHECKSUM_PATH_BYTES
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")

# Spec §5 Layer 1: one "sha256:<64 lowercase hex>  <path>" line per payload file.
_CHECKSUM_LINE_RE = re.compile(r"sha256:[0-9a-f]{64}  (.+)")
# What an attempt at the normative form looks like, however badly framed: an
# algorithm-prefixed hex token at the start (after a BOM or blank lines). Such
# a file is held to the grammar, never handed to the legacy YAML reader.
_NORMATIVE_ATTEMPT_RE = re.compile(r"\ufeff?\s*[A-Za-z0-9]+:[0-9A-Fa-f]{8,}\s")
_PATH_ESCAPES = {"%25": "%", "%5C": "\\", "%0A": "\n", "%0D": "\r"}

# The capsule ID format version this implementation computes and can compare.
_SUPPORTED_ID_VERSION = 1
_MAX_SAMPLE_SHOTS = 2**53 - 1


def _normalise_counts(counts: dict, name: str) -> dict[str, int]:
    """Accept integral scalar types, with totals safe for float diagnostics."""
    if not isinstance(counts, dict):
        raise ValueError(
            f"{name} must be a mapping of string outcomes to non-negative integer counts"
        )
    normalised = {}
    total = 0
    for outcome, count in counts.items():
        if not isinstance(outcome, str):
            raise ValueError(f"{name} outcomes must be strings")
        if isinstance(count, bool) or not isinstance(count, Integral) or count < 0:
            raise ValueError(f"{name} counts must be non-negative integers (excluding booleans)")
        count = int(count)
        total += count
        if total > _MAX_SAMPLE_SHOTS:
            raise ValueError(f"{name} total shots exceed the supported maximum {_MAX_SAMPLE_SHOTS}")
        normalised[outcome] = count
    return normalised


class _ChecksumsGrammarError(ValueError):
    """A ``.checksums`` line that is not in the normative grammar (#108)."""

    def __init__(self, line_no: int, reason: str):
        super().__init__(f"line {line_no}: {reason}")


def _parse_normative_checksums(raw: str) -> dict[str, str]:
    """Parse the normative ``.checksums`` text into ``{decoded path: digest}``.

    Byte-exact per spec §5: no BOM, every line LF-terminated, no blank lines,
    a ``sha256:`` prefix with 64 lowercase hex characters, exactly two spaces,
    then the canonically percent-encoded path. An empty payload is the
    zero-byte file. Raises ``_ChecksumsGrammarError`` naming the first
    offending line.
    """
    expected: dict[str, str] = {}
    if raw == "":
        return expected
    if raw.startswith("\ufeff"):
        raise _ChecksumsGrammarError(1, "byte order mark is not permitted")
    lines = raw.split("\n")
    terminated = lines[-1] == ""
    if terminated:
        lines.pop()
    for line_no, line in enumerate(lines, start=1):
        if not line:
            raise _ChecksumsGrammarError(line_no, "blank line")
        m = _CHECKSUM_LINE_RE.fullmatch(line)
        if m is None:
            token = line.split(" ", 1)[0]
            algorithm, sep, digest = token.partition(":")
            if not sep or algorithm != "sha256":
                raise _ChecksumsGrammarError(
                    line_no,
                    f"unrecognised digest algorithm prefix {algorithm[:20]!r} (expected 'sha256')",
                )
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise _ChecksumsGrammarError(line_no, "digest must be 64 lowercase hex characters")
            # A CR or other control character also lands here: '.' does not
            # match a line break, and the path check below would reject it.
            if _CONTROL_CHAR_RE.search(line):
                raise _ChecksumsGrammarError(
                    line_no, "control character (lines end with a single LF)"
                )
            raise _ChecksumsGrammarError(
                line_no, "digest and path must be separated by exactly two spaces"
            )
        name = m.group(1)
        # The writer percent-encodes LF/CR and never emits any other control
        # character; a raw one here is a file the reference writer did not
        # produce. Reject at parse time, before the path reaches any
        # filesystem call — a NUL byte makes lstat() raise rather than fail (#123).
        if _CONTROL_CHAR_RE.search(name):
            raise _ChecksumsGrammarError(line_no, "control character (lines end with a single LF)")
        if len(name.encode("utf-8")) > _MAX_CHECKSUM_PATH_BYTES:
            raise _ChecksumsGrammarError(line_no, "path is too long")
        decoded = re.sub(r"%[0-9A-Fa-f]{2}", lambda m: _PATH_ESCAPES.get(m[0], m[0]), name)
        # Re-encoding rejects unknown/lowercase escapes and NFC ambiguity
        # without recursively decoding literal % sequences.
        if _checksum_path(decoded) != name:
            raise _ChecksumsGrammarError(line_no, "path is not in canonical encoded form")
        if decoded in expected:
            raise _ChecksumsGrammarError(line_no, "duplicate path")
        expected[decoded] = line[:71]
    if not terminated:
        raise _ChecksumsGrammarError(len(lines), "missing the final LF")
    return expected


def _require_numpy():
    try:
        import numpy as np
        import scipy.stats as ss

        return np, ss
    except ImportError:
        raise ImportError(
            "Statistical verification requires numpy and scipy: pip install numpy scipy"
        )


def _tvd_point(ref_counts: dict, new_counts: dict, n_ref: int, n_new: int) -> float:
    """Plug-in total variation distance between two count distributions.

    ``n_ref``/``n_new`` are passed in rather than recomputed here: callers
    already have the shot totals (and, in ``verify_statistical``, have
    already checked them against ``min_shots``), so this stays pure
    arithmetic on numbers the caller derived once.
    """
    np, _ = _require_numpy()
    all_keys = sorted(set(ref_counts) | set(new_counts))
    ref_probs = np.array([ref_counts.get(k, 0) / n_ref for k in all_keys])
    new_probs = np.array([new_counts.get(k, 0) / n_new for k in all_keys])
    return float(0.5 * np.sum(np.abs(ref_probs - new_probs)))


def _tvd_upper_confidence_bound(
    ref_counts: dict,
    new_counts: dict,
    alpha: float = 0.05,
):
    """One-sided (1-alpha) upper confidence bound on the true TVD.

    Closed-form, no resampling. Two steps, each rigorous on its own:

    1. The plug-in TVD estimator is upward-biased: TV(p,q) <= E[TVD(p_hat,q_hat)]
       by Jensen's inequality (|.| is convex).
    2. TVD(p_hat,q_hat) concentrates around its mean within
       sqrt((log(1/alpha)/2) * (1/n_ref + 1/n_new)) with probability >= 1-alpha,
       by McDiarmid's *one-sided* bounded-difference inequality (a single sample
       moves two probability coordinates by 1/n, halved by the 1/2 in TVD, so
       the bounded difference is 1/n per arm).

    Chaining the two gives P(TV(p,q) <= tvd_point + t) >= 1-alpha. The slack is
    independent of the number of outcomes K, so this is valid (if conservative)
    at any K, unlike the bootstrap it replaces — TVD is not Hadamard-
    differentiable at p=q, which is fatal to bootstrap consistency at exactly
    the null this function is used to test.

    Uses log(1/alpha), not log(2/alpha): the two-sided constant would silently
    under-report the true one-sided error rate.

    The returned bound is clamped to 1.0. TV(p,q) <= 1 deterministically for
    every pair of distributions, so intersecting the McDiarmid bound with that
    known constraint is always valid: it can only ever fire when the raw
    tvd_point + slack already exceeded 1.0, in which case the true value was
    already known to lie in [0, 1] with certainty, so tightening to 1.0 loses
    no coverage — it only removes a number (e.g. 1.17) that conveys nothing a
    bound of 1.0 does not. This keeps the (1-alpha) coverage guarantee while
    matching the schema's declared ``maximum: 1.0`` for this metric.

    See docs/research/2026-08-10-tvd-equivalence-testing.md §5 for the full
    derivation, coverage measurements, and citations.
    """
    np, _ = _require_numpy()
    n_ref = sum(ref_counts.values())
    n_new = sum(new_counts.values())
    tvd_point = _tvd_point(ref_counts, new_counts, n_ref, n_new)
    slack = float(np.sqrt((np.log(1.0 / alpha) / 2.0) * (1.0 / n_ref + 1.0 / n_new)))
    return tvd_point, min(tvd_point + slack, 1.0)


def _compute_chi_squared_p(ref_counts: dict, new_counts: dict):
    """Chi-squared diagnostic only — never verdict-changing.

    Returns None when cell counts are insufficient for a valid test.
    """
    np, ss = _require_numpy()
    all_keys = sorted(set(ref_counts) | set(new_counts))
    n_ref = sum(ref_counts.values())
    n_new = sum(new_counts.values())
    # Scale the candidate to the reference total BEFORE the continuity
    # correction. Correcting first and scaling after inflates the candidate's
    # total by 0.5*K*(n_ref/n_new - 1), so for unequal shot counts the two
    # totals disagree and scipy rejects the input outright — taking a
    # verdict-irrelevant diagnostic down with it.
    ref_obs = np.array([ref_counts.get(k, 0) for k in all_keys], dtype=float) + 0.5
    new_raw = np.array([new_counts.get(k, 0) for k in all_keys], dtype=float)
    new_scaled = new_raw * (n_ref / n_new) + 0.5
    if np.all(ref_obs >= 5) and np.all(new_scaled >= 5):
        try:
            _, p_value = ss.chisquare(new_scaled, f_exp=ref_obs)
        except ValueError:
            # This is a diagnostic hint that never changes the verdict; it must
            # never be the reason a verification fails to return one.
            return None
        return float(p_value)
    return None


_ENERGY_DISTANCE_MAX_OUTCOMES = 2000  # n×n doubles above this is ~800 MB


def _compute_energy_distance(ref_counts: dict, new_counts: dict):
    """Energy distance using normalised Hamming distance on bitstrings (diagnostic only).

    Uses: 2·E[d(X,Y)] - E[d(X,X')] - E[d(Y,Y')]
    where d is Hamming distance normalised by string length.

    Returns None when unique outcomes > _ENERGY_DISTANCE_MAX_OUTCOMES (OOM guard).
    """
    np, _ = _require_numpy()
    all_keys = sorted(set(ref_counts) | set(new_counts))
    if not all_keys:
        return None
    if len(all_keys) > _ENERGY_DISTANCE_MAX_OUTCOMES:
        return None

    n_ref = sum(ref_counts.values())
    n_new = sum(new_counts.values())
    ref_probs = np.array([ref_counts.get(k, 0) / n_ref for k in all_keys])
    new_probs = np.array([new_counts.get(k, 0) / n_new for k in all_keys])

    key_len = max(len(k) for k in all_keys) or 1
    n = len(all_keys)

    # Build pairwise normalised Hamming distance matrix
    d = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                d[i, j] = sum(a != b for a, b in zip(all_keys[i], all_keys[j])) / key_len

    e_pq = float(ref_probs @ d @ new_probs)
    e_pp = float(ref_probs @ d @ ref_probs)
    e_qq = float(new_probs @ d @ new_probs)
    return 2.0 * e_pq - e_pp - e_qq


def _check_entry(
    rel_path, expected_digest, capsule_path, resolved_root, actual_paths, colliding_paths
):
    """Check one ``.checksums`` entry against the filesystem.

    Returns ``(kind, record)`` where ``kind`` is one of ``match``,
    ``mismatch``, ``missing``, ``symlink``, ``invalid`` or ``colliding`` and
    ``record`` is the per-file detail dict (``None`` for ``colliding``).
    Raises ``OSError``/``ValueError`` for a path the OS refuses outright (an
    embedded NUL, a component past NAME_MAX); the caller records that as an
    ``invalid`` entry (#123).
    """

    def record(error=None, actual=None, match=False):
        detail = {"expected": expected_digest, "actual": actual, "match": match}
        if error:
            detail["error"] = error
        return detail

    # Reject keys that escape the capsule root (absolute or ``..``) before
    # touching the filesystem — a crafted .checksums must not read outside.
    if not _is_within_root(rel_path, capsule_path):
        return "invalid", record("path escapes capsule root")
    normalized = unicodedata.normalize("NFC", rel_path)
    if normalized in colliding_paths:
        return "colliding", None
    file_path = actual_paths.get(normalized, capsule_path / rel_path)
    # Never dereference symlinks — the target may live outside the capsule.
    if file_path.is_symlink():
        return "symlink", record("symlink not permitted")
    # The lexical check above is symlink-blind: a *parent* directory that
    # is itself a symlink pointing outside the capsule would let a crafted
    # key read an arbitrary file (#54). Resolve real paths and confirm
    # containment against the resolved root BEFORE any read.
    try:
        resolved = file_path.resolve()
    except (OSError, RuntimeError):
        resolved = None
    if resolved is None or not resolved.is_relative_to(resolved_root):
        return "invalid", record("path escapes capsule root")
    if not file_path.exists():
        return "missing", record()
    if not file_path.is_file():
        return "invalid", record("not a regular file")
    try:
        actual = "sha256:" + hashlib.sha256(file_path.read_bytes()).hexdigest()
    except OSError:
        return "invalid", record("payload could not be read")
    match = actual == expected_digest
    return ("match" if match else "mismatch"), record(actual=actual, match=match)


class CapsuleVerifier:
    """Verify capsule integrity and equivalence."""

    def __init__(self, schema_path: Optional[Path] = None):
        """
        Args:
            schema_path: Deprecated and ignored. The verifier never validated
                against it; schema validation is ``CapsuleValidator``'s job.
        """
        if schema_path is not None:
            warnings.warn(
                "CapsuleVerifier(schema_path=...) is ignored and will be removed: "
                "the verifier does not validate against a schema; use "
                "CapsuleValidator.validate().",
                DeprecationWarning,
                stacklevel=2,
            )

    # -------------------------------------------------------------------------
    # New API (Task 7): closed-form upper confidence bound on TVD
    # -------------------------------------------------------------------------

    def verify_statistical(
        self,
        ref_counts: dict,
        new_counts: dict,
        verification_settings: dict,
    ) -> dict[str, Any]:
        """One-sided upper-confidence-bound equivalence test on TVD (#15).

        Certifies equivalence within tolerance; it does not — and cannot,
        rigorously, from this construction — assert that two distributions
        differ. There is no valid ``REJECTED`` verdict here — the verdict
        space stays VERIFIED / INCONCLUSIVE. That is not because no lower
        bound on the true TVD exists: the triangle inequality gives one
        (the plug-in estimate minus the McDiarmid slack minus a one-sample
        bias bound per arm), and it is valid. It is not deployed because,
        unlike the upper bound (Jensen + McDiarmid, see
        ``_tvd_upper_confidence_bound``, whose slack is free of the outcome
        count), that lower bound's slack depends on the number of outcomes
        K — and taking K from the observed support rather than the declared
        register width fails open, exactly the failure mode this project's
        threat model flags for verifier-side parameters. Separately, the one
        candidate detection tool, a permutation test against the sharp null,
        has measured power as low as 42% at K=256 outcomes — too weak to
        carry an affirmative verdict on its own.
        A low ``chi_squared_p_value`` is surfaced as a diagnostic hint only;
        it never changes the verdict.

        This replaces a bootstrap CI that was provably miscalibrated: TVD is
        not Hadamard-differentiable at ``p = q``, which is fatal to bootstrap
        consistency at exactly the null this function tests. The bootstrap
        rejected byte-identical distributions as non-reproducible from roughly
        four qubits upward. Full analysis, citations, and coverage
        measurements: ``docs/research/2026-08-10-tvd-equivalence-testing.md``.

        Decision matrix as implemented:
          - either arm has zero shots → INCONCLUSIVE
          - shots < min_shots         → INCONCLUSIVE
          - tvd_ucb <= epsilon        → VERIFIED
          - else                      → INCONCLUSIVE

        ``alpha`` (the confidence-bound error rate) is read only from the
        resolved settings, never trusted raw from a capsule's declaration —
        see ``marqov_capsule.policy`` — and a malformed value falls back to
        the default rather than crashing or silently widening the error rate.

        Raises ValueError for non-mapping samples, non-string outcome labels,
        or counts that are not non-negative integers (booleans excluded).
        """
        min_shots = verification_settings.get("min_shots", 100)
        tolerance_regime = verification_settings.get("tolerance_regime", "strict")
        epsilon = verification_settings.get("epsilon", 0.02)

        if tolerance_regime == "calibration_drift":
            epsilon = verification_settings.get("epsilon_drift", 0.08)

        alpha = resolve_alpha(verification_settings.get("alpha"))

        ref_counts = _normalise_counts(ref_counts, "ref_counts")
        new_counts = _normalise_counts(new_counts, "new_counts")

        n_ref = sum(ref_counts.values())
        n_new = sum(new_counts.values())

        if n_ref == 0 or n_new == 0:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": "one or both arms have zero shots; TVD is undefined",
                "metrics": {
                    "epsilon_used": epsilon,
                    "shots_ref": n_ref,
                    "shots_new": n_new,
                    "min_shots": min_shots,
                },
            }

        total_shots = min(n_ref, n_new)

        if total_shots < min_shots:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": f"shots ({total_shots}) below min_shots ({min_shots}); declined without computing a confidence bound",
                "metrics": {
                    "epsilon_used": epsilon,
                    "shots_ref": n_ref,
                    "shots_new": n_new,
                    "min_shots": min_shots,
                },
            }

        tvd_point, tvd_ucb = _tvd_upper_confidence_bound(ref_counts, new_counts, alpha=alpha)
        chi2_p = _compute_chi_squared_p(ref_counts, new_counts)
        energy_dist = _compute_energy_distance(ref_counts, new_counts)

        metrics: dict[str, Any] = {
            "total_variation_distance": tvd_point,
            "tvd_ucb": tvd_ucb,
            "alpha": alpha,
            "epsilon_used": epsilon,
            "shots_ref": n_ref,
            "shots_new": n_new,
        }
        if chi2_p is not None:
            metrics["chi_squared_p_value"] = chi2_p
        if energy_dist is not None:
            metrics["energy_distance"] = energy_dist

        if tvd_ucb <= epsilon:
            verdict = "VERIFIED"
            reason = f"tvd_ucb ({tvd_ucb:.4f}) <= epsilon ({epsilon})"
        else:
            verdict = "INCONCLUSIVE"
            reason = f"tvd_ucb ({tvd_ucb:.4f}) > epsilon ({epsilon}); TVD = {tvd_point:.4f}; equivalence not demonstrated"

        return {
            "verdict": verdict,
            "reason": reason,
            "metrics": metrics,
        }

    @staticmethod
    def verify_deterministic(
        ref_data: Any,
        new_data: Any,
    ) -> dict[str, Any]:
        """Digest equality for deterministic (classical) results."""

        def _digest(obj):
            s = json.dumps(obj, sort_keys=True, default=str)
            return "sha256:" + hashlib.sha256(s.encode()).hexdigest()

        ref_digest = _digest(ref_data)
        new_digest = _digest(new_data)
        match = ref_digest == new_digest
        return {
            "verdict": "VERIFIED" if match else "REJECTED",
            "ref_digest": ref_digest,
            "new_digest": new_digest,
        }

    # -------------------------------------------------------------------------
    # Checksum verification
    # -------------------------------------------------------------------------

    @staticmethod
    def verify_checksums(capsule_dir: Union[str, Path]) -> dict[str, Any]:
        """Verify SHA-256 checksums for all files in capsule directory.

        Returns a dict with:
          - ``status``: ``"pass"`` or ``"fail"``
          - ``files``: per-file match details (new API)
          - ``passed``: bool alias for backwards compatibility
          - ``mismatched``: list of mismatched relative paths (backwards compat)
          - ``missing``: list of missing relative paths (backwards compat)
        """
        capsule_path = Path(capsule_dir)
        checksums_file = capsule_path / ".checksums"
        if checksums_file.is_symlink() or not checksums_file.is_file():
            return {
                "status": "fail",
                "passed": False,
                "error": ".checksums missing or not a regular file",
                "files": {},
                "mismatched": [],
                "missing": [],
                "extra": [],
            }

        # .checksums is untrusted input: malformed bytes must produce a FAIL
        # verdict, never an uncaught traceback out of the verifier (#61).
        try:
            raw = checksums_file.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            return {
                "status": "fail",
                "passed": False,
                "error": ".checksums could not be read as text",
                "files": {},
                "mismatched": [],
                "missing": [],
                "extra": [],
            }
        # Two forms are readable. The normative line format (spec §5) is held
        # to its grammar byte for byte, and a violation is reported as a
        # grammar error naming the line — not as a payload mismatch, which
        # sends the reader looking at the wrong file (#108). The pre-1.0 YAML
        # mapping of literal paths to digests stays readable because
        # marqov-platform's vendored builder still writes it.
        checksums_format = "normative"
        expected: Any = None
        if raw != "" and not _NORMATIVE_ATTEMPT_RE.match(raw):
            # A legal filename containing ': ' can make a checksum line look
            # like a YAML mapping, hence the framing check before this branch.
            try:
                legacy = yaml.safe_load(raw)
            except Exception:
                legacy = None
            if isinstance(legacy, dict):
                expected = legacy
                checksums_format = "legacy-yaml"
        if expected is None:
            try:
                expected = _parse_normative_checksums(raw)
            except _ChecksumsGrammarError as exc:
                return {
                    "status": "fail",
                    "passed": False,
                    "error": f".checksums is malformed: grammar error at {exc}",
                    "format": checksums_format,
                    "files": {},
                    "mismatched": [],
                    "missing": [],
                    "extra": [],
                }

        # Resolve the capsule root once, up front. Every checksummed file must
        # resolve to a real path *inside* this, or it is rejected before any read.
        resolved_root = capsule_path.resolve()

        files: dict[str, dict] = {}
        mismatched: list[str] = []
        missing: list[str] = []
        invalid: list[str] = []
        symlinks: list[str] = []
        all_match = True

        # Filesystems may expose decomposed Unicode names even though the
        # format names paths in NFC. Map to actual directory entries, rejecting
        # collisions rather than choosing one of two identically named payloads.
        actual_paths = {}
        colliding_paths = set()
        for fp in capsule_path.rglob("*"):
            normalized = unicodedata.normalize("NFC", fp.relative_to(capsule_path).as_posix())
            if normalized in actual_paths:
                colliding_paths.add(normalized)
            actual_paths[normalized] = fp
        if colliding_paths:
            invalid.extend(sorted(colliding_paths))
            all_match = False
        normalized_expected = set()
        for path in expected:
            if isinstance(path, str):
                normalized = unicodedata.normalize("NFC", path)
                if normalized in normalized_expected:
                    invalid.append(normalized)
                    all_match = False
                normalized_expected.add(normalized)

        for rel_path, expected_digest in expected.items():
            # Keys must be strings; a non-string mapping key (e.g. YAML null or a
            # nested list) must fail, never raise from a path operation (#61).
            if not isinstance(rel_path, str):
                files[str(rel_path)] = {
                    "expected": expected_digest,
                    "actual": None,
                    "match": False,
                    "error": "non-string .checksums key",
                }
                invalid.append(str(rel_path))
                all_match = False
                continue
            # Every filesystem call below can raise on a hostile path — an
            # embedded NUL (ValueError from lstat), a component past NAME_MAX
            # or a total past PATH_MAX (OSError from resolve). The legacy YAML
            # branch has no parse-time path check, so guard here as well:
            # any such entry is invalid, never a traceback (#123).
            try:
                outcome = _check_entry(
                    rel_path,
                    expected_digest,
                    capsule_path,
                    resolved_root,
                    actual_paths,
                    colliding_paths,
                )
            except (OSError, ValueError):
                files[rel_path] = {
                    "expected": expected_digest,
                    "actual": None,
                    "match": False,
                    "error": "path could not be checked",
                }
                invalid.append(rel_path)
                all_match = False
                continue
            kind, record = outcome
            if record is not None:
                files[rel_path] = record
            if kind == "match":
                continue
            all_match = False
            if kind == "mismatch":
                mismatched.append(rel_path)
            elif kind == "missing":
                missing.append(rel_path)
            elif kind == "symlink":
                symlinks.append(rel_path)
            elif kind == "invalid":
                invalid.append(rel_path)
            # kind == "colliding": already reported via colliding_paths above

        # Walk the tree once: collect every on-disk entry (for "extra") and flag
        # any symlink anywhere in the capsule — symlinks are an exfiltration
        # vector. The closed set is enforced over ALL entry types, not just
        # regular files: a FIFO/socket/device node injected into a sealed capsule
        # must not slip past the check by failing ``is_file()`` (#56).
        actual_files = set()
        for fp in capsule_path.rglob("*"):
            rel = fp.relative_to(capsule_path).as_posix()
            if fp.is_symlink():
                if rel not in symlinks:
                    symlinks.append(rel)
                    all_match = False
                continue
            if fp.is_dir():
                continue
            if rel not in UNCHECKSUMMED_ROOT_FILES:
                actual_files.add(unicodedata.normalize("NFC", rel))
        # .checksums pins a *closed* set: anything on disk but not listed is an
        # injected file. It leaves checksums_digest and the capsule ID intact,
        # so no other layer can catch it (#17).
        expected_paths = {unicodedata.normalize("NFC", p) for p in expected if isinstance(p, str)}
        extra = sorted(actual_files - expected_paths)
        if extra:
            all_match = False

        return {
            "status": "pass" if all_match else "fail",
            "passed": all_match,
            "format": checksums_format,
            "files": files,
            "mismatched": mismatched,
            "missing": missing,
            "invalid": invalid,
            "symlinks": symlinks,
            "extra": extra,
        }

    @staticmethod
    def verify_integrity(
        capsule_dir: Union[str, Path],
        expected_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Full spec §6 integrity check — all three layers.

        1. payload files vs ``.checksums`` (delegated to :meth:`verify_checksums`)
        2. ``SHA-256(.checksums bytes)`` vs ``checksums_digest`` in the manifest
        3. recomputed capsule ID vs ``expected_id``, when the caller supplies one

        Layer 1 alone is not tamper-evidence: anyone who edits a payload file can
        re-run ``save_checksums`` and pass. Layer 2 catches that, because the
        manifest pins the original ``.checksums`` bytes. Layer 3 catches edits to
        the manifest itself, which is deliberately outside ``.checksums``.

        Without ``expected_id`` the manifest is *unauthenticated* — nothing on
        disk can attest to it, since a tamperer who rewrites the whole chain
        produces a self-consistent capsule with a different ID. Callers should
        record ``capsule_id`` at seal time and pass it back here.
        """
        capsule_path = Path(capsule_dir)
        errors: list[str] = []

        # Layer 3 input. Spec §5: a reader parses the <scheme>:<version>: prefix
        # and dispatches on the version; it never compares an ID it cannot
        # parse, or one of a version it does not compute (#114).
        expected_id_usable = expected_id is not None
        if expected_id is not None:
            try:
                id_version, _ = parse_capsule_id(expected_id)
            except (ValueError, TypeError):
                expected_id_usable = False
                errors.append(
                    f"expected ID {expected_id!r} is not a capsule ID "
                    "(expected mqc:<version>:<64 lowercase hex>)"
                )
            else:
                if id_version != _SUPPORTED_ID_VERSION:
                    expected_id_usable = False
                    errors.append(
                        f"capsule ID version {id_version} is not supported by this "
                        f"implementation (it computes version {_SUPPORTED_ID_VERSION})"
                    )

        checksums = CapsuleVerifier.verify_checksums(capsule_path)
        if checksums["status"] != "pass":
            errors.append("payload does not match .checksums")

        checksums_digest_match: Optional[bool] = None
        capsule_id: Optional[str] = None
        capsule_id_match: Optional[bool] = None
        if expected_id is not None and not expected_id_usable:
            capsule_id_match = False

        manifest_path = capsule_path / "capsule.yaml"
        manifest: Optional[dict] = None
        if manifest_path.is_symlink() or not manifest_path.is_file():
            errors.append(
                "capsule.yaml missing or not a regular file — no manifest to anchor .checksums to"
            )
        else:
            # The manifest is untrusted input: a corrupt or hostile one must fail
            # verification, never raise out of the verifier.
            try:
                parsed = load_manifest_yaml(manifest_path.read_text(encoding="utf-8"))
            except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
                errors.append(f"capsule.yaml could not be parsed: {exc.__class__.__name__}")
            else:
                if isinstance(parsed, dict):
                    manifest = parsed
                else:
                    errors.append("capsule.yaml is not a YAML mapping")

        if manifest is not None:
            # Layer 2 — manifest → .checksums binding
            declared = manifest.get("checksums_digest")
            checksums_file = capsule_path / ".checksums"
            if declared is None:
                errors.append("manifest has no checksums_digest — capsule is not sealed")
            elif checksums_file.is_symlink() or not checksums_file.is_file():
                checksums_digest_match = False
                errors.append(
                    ".checksums missing or not a regular file but manifest declares checksums_digest"
                )
            else:
                try:
                    actual = "sha256:" + hashlib.sha256(checksums_file.read_bytes()).hexdigest()
                except OSError:
                    checksums_digest_match = False
                    errors.append(".checksums could not be read to verify checksums_digest")
                else:
                    checksums_digest_match = actual == declared
                    if not checksums_digest_match:
                        errors.append(
                            f"checksums_digest mismatch: manifest declares {declared}, "
                            f".checksums hashes to {actual}"
                        )

            # Layer 3 — manifest identity. The manifest is untrusted: a value
            # that cannot be RFC 8785 canonicalised (NaN, non-string keys, …)
            # must fail verification, never raise out of the verifier (#61).
            try:
                capsule_id = compute_capsule_id(manifest)
            except Exception as exc:
                errors.append(f"capsule ID could not be computed: {exc.__class__.__name__}")
            else:
                if expected_id_usable:
                    capsule_id_match = capsule_id == expected_id
                    if not capsule_id_match:
                        errors.append(
                            f"capsule ID mismatch: expected {expected_id}, recomputed {capsule_id}"
                        )

        authenticated = capsule_id_match is True
        # Surface the authentication state for machine consumers. Without a
        # trusted --id the manifest is unauthenticated even when every other
        # layer passes; text mode already prints this note, so JSON must carry
        # it too or a CI gate reading `status` alone accepts a forgery (#58).
        warning = None
        if not authenticated:
            warning = (
                "manifest is not authenticated — nothing on disk can attest to it; "
                "pass --id <trusted-id> to verify layer 3 (spec §6)"
            )

        return {
            "status": "fail" if errors else "pass",
            "checksums": checksums,
            "checksums_digest_match": checksums_digest_match,
            "capsule_id": capsule_id,
            "capsule_id_match": capsule_id_match,
            "manifest_authenticated": authenticated,
            "warning": warning,
            "errors": errors,
        }

    # -------------------------------------------------------------------------
    # Pre-release legacy API migration guards
    # -------------------------------------------------------------------------

    def load_capsule(self, filepath: Union[str, Path]) -> dict[str, Any]:
        """Parse a manifest using the capsule YAML profile; does not verify it."""
        manifest = load_manifest_yaml(Path(filepath).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("capsule.yaml must be a YAML mapping")
        return manifest

    def verify_capsule(
        self,
        capsule: dict[str, Any],
        method: Optional[str] = None,
        reference_results: Optional[dict[str, Any]] = None,
        tolerance: float = 0.01,
        significance_level: float = 0.05,
    ) -> NoReturn:
        """Retired legacy verdict API; retained only for a clear migration error.

        Metadata presence and non-rejection of a statistical null do not prove
        integrity or equivalence. Do not map the old boolean to a new verdict.
        """
        raise NotImplementedError(
            "verify_capsule() was retired before 0.1.0: use "
            "verify_integrity(directory, expected_id=trusted_id) for file integrity, "
            "verify_deterministic(ref_data, new_data) for explicit result equality, "
            "or verify_statistical(ref_counts, new_counts, policy.resolve(declared)) "
            "with a verifier-owned VerificationPolicy for count equivalence. "
            "Metadata alone cannot establish any of these guarantees."
        )

    def check_calibration_drift(
        self,
        capsule1: dict[str, Any],
        capsule2: dict[str, Any],
        max_fidelity_drift: float = 0.01,
    ) -> NoReturn:
        """Retired: missing fidelity values formerly compared equal as zero."""
        raise NotImplementedError(
            "check_calibration_drift() was retired before 0.1.0. "
            "No replacement calibration-verdict API is provided; compare explicit, "
            "validated calibration measurements with a domain-specific policy. "
            "A statistical calibration_drift tolerance is not a calibration check."
        )

    def compare_capsules(
        self,
        capsule1_path: Union[str, Path],
        capsule2_path: Union[str, Path],
        method: str = "statistical",
        tolerance: float = 0.01,
    ) -> NoReturn:
        """Retired: overall_consistent formerly meant only equal manifest names."""
        raise NotImplementedError(
            "compare_capsules() was retired before 0.1.0: verify each directory "
            "with verify_integrity and its independently trusted ID, then compare "
            "explicit result data with verify_deterministic or verify_statistical. "
            "Matching capsule names do not establish consistency."
        )
