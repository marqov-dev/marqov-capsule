"""CapsuleBuilder — constructs and seals capsule.yaml manifests."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import os
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from marqov_capsule._canonical import (
    coerce_for_canonical,
    compute_capsule_id,
    dump_manifest_yaml,
    load_manifest_yaml,
)
from marqov_capsule.redactor import CapsuleRedactor
from marqov_capsule.validator import CapsuleValidator

# Root-level files deliberately left out of .checksums: .checksums cannot hash
# itself, and capsule.yaml embeds the digest of .checksums (it is covered by the
# capsule ID instead). Matched against the path relative to the capsule root, not
# the basename — payload/capsule.yaml is ordinary payload and must be hashed.
# CapsuleVerifier imports this so the seal and verify sides cannot drift: a file
# one side skips and the other flags is either a false failure or a blind spot.
UNCHECKSUMMED_ROOT_FILES = frozenset({".checksums", "capsule.yaml"})
MAX_CHECKSUM_PATH_BYTES = 4096

# Lifecycle states that a capsule can never be sealed out of. Sealing is a
# one-way transition (spec §4: draft/runnable -> sealed -> archived, no
# backward moves); re-sealing one of these would mint a fresh ID over mutated
# content while presenting the result as an original seal.
_TERMINAL_STATES = frozenset({"sealed", "archived"})

# Manifest fields that describe one particular seal or one particular run. A
# capsule derived from a sealed parent starts without them: it has not been
# sealed, and it has not run.
_NOT_INHERITED = frozenset({
    "checksums_digest", "sealed_at", "sealed_by", "seal_notes", "derived_from",
    "num_tasks", "wall_time_seconds", "actual_cost_usd", "total_shots",
    "exit_code", "exit_message",
})


def _checksum_path(rel: str) -> str:
    """Return the spec-canonical form of a payload path for the ``.checksums`` file.

    The path is NFC-normalised (so a decomposed vs precomposed filename hashes to
    one value, §2.2/§5) and then a minimal, unambiguous set of bytes is
    percent-encoded with UPPERCASE triplets — only the four that would otherwise
    break the line grammar or the ``/`` separator:

      * ``%``  -> ``%25``  (must go first, so an existing ``%`` is not aliased)
      * ``\\`` -> ``%5C``  (a literal backslash in a filename, not a separator)
      * ``\\n`` -> ``%0A`` and ``\\r`` -> ``%0D``  (would split the line)

    Spaces are left literal (the field separator is two spaces, and paths may
    legitimately contain single spaces); ``/`` separators are preserved.
    """
    rel = unicodedata.normalize("NFC", rel)
    rel = rel.replace("%", "%25")
    rel = rel.replace("\\", "%5C")
    rel = rel.replace("\n", "%0A")
    rel = rel.replace("\r", "%0D")
    if any(ord(char) < 32 or ord(char) == 127 for char in rel):
        raise ValueError("payload path contains an unsupported control character")
    if len(rel.encode("utf-8")) > MAX_CHECKSUM_PATH_BYTES:
        raise ValueError("encoded payload path is too long for the checksum format")
    return rel


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a same-directory temp file and ``os.replace``.

    Either the complete new content lands at ``path`` or the previous bytes are
    left untouched. A plain ``open(path, "w")`` truncates first and writes
    second, so any failure in between — serialisation raising, disk full — left
    a zero-byte manifest where the user's draft used to be (#121).
    """
    _atomic_write_bytes(path, text.encode("utf-8"))


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace a file only after its complete new bytes have been written."""
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        # mkstemp creates 0600; give the manifest the ordinary umask-derived mode.
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp_name, 0o666 & ~umask)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


class CapsuleStateError(RuntimeError):
    """Raised when an operation is illegal for the capsule's lifecycle state.

    A subclass of RuntimeError so existing ``except RuntimeError`` handlers keep
    working, while callers that want to react specifically (e.g. the CLI, which
    turns it into a clean non-zero exit) can catch it by name.
    """


class CapsuleValidationError(ValueError):
    """Raised when a manifest about to be sealed does not validate against the schema.

    Spec §8: a conformant implementation produces a ``capsule.yaml`` that
    validates against ``capsule-schema.json``. A subclass of ValueError so
    callers already handling "this draft cannot be sealed" keep working;
    ``errors`` carries the validator's ``{"path", "message"}`` list (#111).
    """

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        detail = "; ".join(f"{e['path']}: {e['message']}" for e in errors)
        super().__init__(f"manifest does not validate against the capsule schema: {detail}")


class _ClassOrInstanceMethod:
    """Bind ``derive`` so both ``CapsuleBuilder.derive(manifest)`` and
    ``builder.derive()`` (deriving from the builder's own manifest) work."""

    def __init__(self, func):
        self._func = func
        self.__doc__ = func.__doc__

    def __get__(self, obj, cls):
        if obj is None:
            return lambda manifest: self._func(cls, manifest)
        return lambda: self._func(cls, obj._capsule)


class CapsuleBuilder:
    """Build reproducible capsule YAML manifests following the Marqov Capsule v1 standard."""

    def __init__(self):
        self._capsule: dict[str, Any] = {}
        self._task_executions: list[dict[str, Any]] = []
        self._sealed = False
        self._sealed_text: Optional[str] = None
        #: The credential scan result from the most recent ``seal_capsule``
        #: (``findings``, ``skipped``, ``capsuleignore_patterns``). ``seal()``
        #: returns only the ID, so this is how a caller — the CLI in
        #: particular — learns what a ``warn_only`` seal let through (#105).
        self.scan_result: Optional[dict[str, Any]] = None

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> "CapsuleBuilder":
        """Load an existing draft manifest into a new builder.

        Used by the CLI `seal` command which reads a capsule.yaml written by
        `init` or by hand. Deep-copies the dict so subsequent mutations don't
        alias the caller's data.
        """
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a mapping")
        b = cls()
        b._capsule = copy.deepcopy(manifest)
        # A hand-edited draft may leave a container key empty (YAML null) or
        # give it the wrong shape. Null reads as "none yet"; a wrong type is
        # an error the CLI turns into a clean exit, not a traceback (#95).
        for key, kind in (("task_executions", list), ("digests", dict), ("extensions", dict),
                          ("parameters", dict), ("requirements", dict)):
            value = b._capsule.get(key)
            if value is None:
                if key in b._capsule and key != "requirements":
                    b._capsule[key] = kind()
            elif not isinstance(value, kind):
                raise ValueError(
                    f"'{key}' must be a {'list' if kind is list else 'mapping'}, "
                    f"got {type(value).__name__}"
                )
        b._task_executions = list(b._capsule.get("task_executions") or [])
        return b

    @_ClassOrInstanceMethod
    def derive(cls, manifest: dict[str, Any]) -> "CapsuleBuilder":
        """Start a new draft from a sealed (or archived) capsule.

        A sealed capsule rejects modification (spec §4); this is the way to
        continue from one. The draft keeps the parent's descriptive fields
        (name, parameters, requirements, tags, …), starts with no task
        executions or digests, and records the parent's capsule ID in
        ``derived_from``. Raises ValueError if the parent is not sealed: a
        draft has no stable ID to point at.
        """
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a mapping")
        if manifest.get("lifecycle_state") not in _TERMINAL_STATES:
            raise ValueError("derive() needs a sealed or archived parent capsule")
        parent_id = compute_capsule_id(manifest)
        draft = {k: copy.deepcopy(v) for k, v in manifest.items() if k not in _NOT_INHERITED}
        draft["lifecycle_state"] = "draft"
        draft["created_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        draft["task_executions"] = []
        draft["digests"] = {}
        draft["derived_from"] = parent_id
        return cls.from_manifest(draft)

    def _require_mutable(self) -> None:
        """Refuse to modify a sealed or archived capsule (spec §4, #107)."""
        state = self._capsule.get("lifecycle_state")
        if state in _TERMINAL_STATES:
            raise CapsuleStateError(
                f"Cannot modify a capsule in '{state}' state. Use "
                "CapsuleBuilder.derive() to start a new draft from it."
            )

    def seal(self, capsule_dir: str | Path, sealed_by: Optional[str] = None,
             warn_only: bool = False, derived_from: Optional[str] = None,
             validate: bool = True) -> str:
        """Full sealing sequence: credential scan → checksums → transition → save → ID.

        This is the one-call path for the CLI. Returns the versioned capsule ID
        (mqc:1:<64 lowercase hex chars>), recomputed from the manifest bytes
        actually written to disk — so it is by construction the ID any verifier
        will recompute from the file, not an in-memory value that might
        serialise differently (#92).
        Raises RedactorError if secrets are found and warn_only is False.
        Raises CapsuleValidationError if the sealed manifest would not validate
        against the schema, unless ``validate=False``.
        """
        self._require_mutable()
        checksums_path = Path(capsule_dir) / ".checksums"
        if checksums_path.is_symlink() or (checksums_path.exists() and not checksums_path.is_file()):
            raise ValueError(".checksums must be a regular file")
        previous_checksums = checksums_path.read_bytes() if checksums_path.exists() else None
        previous_state = (copy.deepcopy(self._capsule), self._sealed, self._sealed_text, self.scan_result)
        self.seal_capsule(capsule_dir, sealed_by=sealed_by, warn_only=warn_only,
                          derived_from=derived_from, validate=validate)
        try:
            path = self.save_capsule(Path(capsule_dir) / "capsule.yaml")
        except Exception:
            # Restore the draft and its original checksum file so one-call
            # sealing can be retried after a failed atomic manifest write.
            self._capsule, self._sealed, self._sealed_text, self.scan_result = previous_state
            self._task_executions = self._capsule.get("task_executions", [])
            if previous_checksums is None:
                checksums_path.unlink()
            else:
                _atomic_write_bytes(checksums_path, previous_checksums)
            raise
        written = load_manifest_yaml(path.read_text(encoding="utf-8"))
        return compute_capsule_id(written)

    def start_capsule(
        self,
        name: str,
        description: str = "",
        parameters: Optional[dict[str, Any]] = None,
        requirements: Optional[dict[str, Any]] = None,
        run_id: Optional[str] = None,
        workflow_ref: Optional[str] = None,
        environment_ref: Optional[str] = None,
        max_budget_usd: Optional[float] = None,
        created_by: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> "CapsuleBuilder":
        """Initialise a new capsule manifest."""
        self._capsule = {
            "version": "1.0.0",
            "name": name,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "created_by": created_by or "marqov-capsule",
            "lifecycle_state": "draft",
            "run_id": run_id,
            "parameters": copy.deepcopy(parameters) if parameters is not None else {},
            "workflow_ref": workflow_ref,
            "environment_ref": environment_ref,
            "max_budget_usd": max_budget_usd,
            "tags": copy.deepcopy(tags) if tags is not None else [],
            "requirements": copy.deepcopy(requirements),
            "task_executions": [],
            "digests": {},
            "extensions": {},
        }
        self._task_executions = []
        self._sealed = False
        self._sealed_text = None
        self.scan_result = None
        return self

    def add_task_execution(
        self,
        task_id: str,
        status: str,
        result_type: str,
        backend: dict[str, Any],
        verification_settings: Optional[dict[str, Any]] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        wall_time_seconds: Optional[float] = None,
        cost_usd: Optional[float] = None,
        job_id: Optional[str] = None,
    ) -> "CapsuleBuilder":
        """Record a task execution."""
        self._require_mutable()
        execution: dict[str, Any] = {
            "task_id": task_id,
            "status": status,
            "result_type": result_type,
            "backend": copy.deepcopy(backend),
        }
        if verification_settings:
            execution["verification_settings"] = copy.deepcopy(verification_settings)
        if start_time:
            execution["start_time"] = start_time
        if end_time:
            execution["end_time"] = end_time
        if wall_time_seconds is not None:
            execution["wall_time_seconds"] = wall_time_seconds
        if cost_usd is not None:
            execution["cost_usd"] = cost_usd
        if job_id:
            execution["job_id"] = job_id

        self._task_executions.append(execution)
        self._capsule["task_executions"] = self._task_executions
        return self

    def add_result_digest(
        self,
        data: Any,
        digest_name: str = "results",
    ) -> "CapsuleBuilder":
        """Add a SHA-256 digest of result data to the digests block."""
        self._require_mutable()
        import json as _json
        if isinstance(data, dict):
            data_str = _json.dumps(data, sort_keys=True, default=str)
        else:
            data_str = str(data)
        digest = hashlib.sha256(data_str.encode()).hexdigest()
        self._capsule.setdefault("digests", {})[digest_name] = f"sha256:{digest}"
        return self

    def seal_capsule(
        self,
        capsule_dir: str | Path,
        sealed_by: Optional[str] = None,
        notes: str = "",
        warn_only: bool = False,
        derived_from: Optional[str] = None,
        validate: bool = True,
    ) -> dict[str, Any]:
        """Seal the capsule following spec §5 sealing order.

        Sealing order:
          1. Prepare checksums and the complete sealed manifest in memory.
          2. Validate and credential-scan before writing or changing state.
          3. Write .checksums, excluding .checksums and capsule.yaml.
          4. Commit the sealed manifest and its independent snapshot.
          (Caller must call save_capsule() after this to write capsule.yaml.)

        Returns redactor scan result dict.
        Raises CapsuleStateError if the capsule is already sealed or archived.
        Raises ValueError if requirements not set.
        Raises CapsuleValidationError if the manifest, as it would be sealed,
        does not validate against the schema (spec §8) and ``validate`` is True.
        Raises RedactorError if secrets found and not warn_only.
        """
        # Lifecycle gate: sealing is one-way. Refuse to re-seal a capsule that is
        # already sealed/archived — otherwise re-running seal on mutated content
        # silently mints a new ID and a fresh checksums_digest/sealed_at, which
        # contradicts the immutability guarantee. This is checked against the
        # manifest's own lifecycle_state (not the transient _sealed flag) so the
        # CLI/from_manifest path and the in-process path enforce it identically. (#59)
        state = self._capsule.get("lifecycle_state")
        if state in _TERMINAL_STATES:
            raise CapsuleStateError(
                f"Cannot seal a capsule already in '{state}' state: sealing is a "
                "one-way transition and re-sealing would mint a new ID over "
                "possibly-mutated content. Start from a fresh draft to create a "
                "derived capsule."
            )

        req = self._capsule.get("requirements")
        if not req or "paradigm" not in req or "max_qubit_count" not in req:
            raise ValueError(
                "requirements with 'paradigm' and 'max_qubit_count' must be set before sealing"
            )

        capsule_path = Path(capsule_dir)

        # Assemble the complete prospective manifest in memory so metadata
        # supplied at seal time receives the same scan as existing fields.
        # Canonicalization, validation and scanning must leave the draft and
        # files untouched on refusal.
        candidate = coerce_for_canonical(self._capsule)
        sealed_by = sealed_by or "marqov-capsule"
        sealed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        candidate.update(lifecycle_state="sealed", sealed_at=sealed_at, sealed_by=sealed_by,
                         checksums_digest="sha256:" + "0" * 64)
        if derived_from is not None:
            candidate["derived_from"] = derived_from
        if notes:
            candidate["seal_notes"] = notes
        if validate:
            # Validate the manifest as it will be sealed, before the scan and
            # before anything is written: the seal fields are filled in with
            # their real values, the digest with a well-formed stand-in (#111).
            result = CapsuleValidator.validate(candidate)
            if not result["valid"]:
                raise CapsuleValidationError(result["errors"])

        checksums_bytes = self._checksums_bytes(capsule_path)
        candidate["checksums_digest"] = "sha256:" + hashlib.sha256(checksums_bytes).hexdigest()
        manifest_text = dump_manifest_yaml(coerce_for_canonical(candidate))

        # Step 1: credential scan (payload files + exactly the sealed manifest
        # representation that save_capsule will write).
        redactor = CapsuleRedactor(capsule_path, mode="warn_only" if warn_only else "block")
        scan_result = redactor.scan_and_raise(overrides={"capsule.yaml": manifest_text})

        # Step 2: checksums (excludes .checksums and capsule.yaml)
        _atomic_write_bytes(capsule_path / ".checksums", checksums_bytes)
        self._capsule = candidate
        self._sealed_text = manifest_text
        self._sealed = True
        self.scan_result = scan_result
        return scan_result

    def save_capsule(self, filepath: str | Path) -> Path:
        """Write capsule.yaml to disk.

        Serialises the same coerced form used to compute the capsule ID
        (``coerce_for_canonical``): datetimes are written as their ISO 8601
        string, not as a raw YAML timestamp. Otherwise the on-disk value
        (``2026-06-11 00:00:00``, space-separated, read back as a string) would
        disagree with the ID computed from ``datetime.isoformat()`` (``T``
        separator), so a verifier recomputing the ID from the file would never
        match the ID the sealer published. (#20)
        """
        # The builder that performed the seal writes the sealed manifest; a
        # builder holding a manifest that was already sealed when it was loaded
        # has nothing it may write (#107).
        if not self._sealed:
            self._require_mutable()
        text = self._serialise()
        if self._sealed and text != self._sealed_text:
            raise CapsuleStateError("Cannot write a modified sealed manifest. Use CapsuleBuilder.derive().")
        path = Path(filepath)
        if path.is_dir() or not path.suffix:
            path = path / "capsule.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Serialise fully before touching the file, then replace atomically, so
        # a failure anywhere leaves the previous bytes in place (#121).
        _atomic_write_text(path, text)
        return path

    def _serialise(self) -> str:
        """The manifest as the YAML text ``save_capsule`` writes.

        Uses the coerced (ID-computing) form and the profile-aware dumper, so
        what ``load_manifest_yaml`` reads back is the value the ID was computed
        from (#20, #92).
        """
        return dump_manifest_yaml(coerce_for_canonical(self._capsule))

    def save_checksums(self, capsule_dir: str | Path) -> Path:
        """Compute and write .checksums for all files except .checksums and capsule.yaml.

        Emits the normative spec format (§2.2/§5): newline-delimited
        ``sha256:<hex>  <relative-path>`` lines (two-space separator), sorted
        lexicographically by path, one line per payload file. Because
        ``checksums_digest`` is the SHA-256 of these exact bytes, this is the
        interoperable form a third-party implementation reads — the previous
        YAML-mapping form produced a different digest, hence a different capsule
        ID, for the identical payload set. (#20)

        Raises CapsuleStateError (a RuntimeError) if called after seal_capsule(), or on
        a loaded sealed manifest — rewriting .checksums would make the embedded
        checksums_digest stale and silently break the Merkle chain.
        """
        if self._sealed:
            raise CapsuleStateError(
                "Cannot rewrite .checksums after sealed state: checksums_digest would become stale. "
                "Use CapsuleBuilder.derive() to start a new draft if payload files have changed."
            )
        self._require_mutable()
        capsule_path = Path(capsule_dir)
        checksums_path = capsule_path / ".checksums"
        _atomic_write_bytes(checksums_path, self._checksums_bytes(capsule_path))
        return checksums_path

    @staticmethod
    def _checksums_bytes(capsule_path: Path) -> bytes:
        """Prepare checksums without writing, including all path checks."""
        entries: list[tuple[str, str]] = []
        encoded_paths: set[str] = set()
        for file_path in sorted(capsule_path.rglob("*")):
            # Refuse entries the verifier cannot accept, without following or
            # reading them. FIFOs in particular must never reach the scanner.
            if file_path.is_symlink():
                raise ValueError("capsule entries must not be symlinks")
            if not file_path.is_file() and not file_path.is_dir():
                raise ValueError("capsule entries must be regular files or directories")
            if file_path.is_file():
                # as_posix() gives the '/'-separated relative path on every OS;
                # the root exclusion is by that relative name, not the basename.
                rel = file_path.relative_to(capsule_path).as_posix()
                if rel in UNCHECKSUMMED_ROOT_FILES:
                    continue
                encoded = _checksum_path(rel)
                if encoded in encoded_paths:
                    raise ValueError("payload paths collide after Unicode normalization")
                encoded_paths.add(encoded)
                digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
                entries.append((encoded, f"sha256:{digest}"))
        # Spec §5: one "sha256:<hex>  <path>" line per file, sorted byte-wise by
        # the (encoded) path. Empty (no payload files) is a zero-byte file, whose
        # digest still pins "no payload".
        entries.sort(key=lambda e: e[0].encode("utf-8"))
        lines = [f"{digest}  {path}\n" for path, digest in entries]
        # Bytes, not text mode: text mode would turn each LF into CRLF on
        # Windows, which is neither the normative framing nor the same digest.
        return "".join(lines).encode("utf-8")

    def to_yaml(self) -> str:
        return self._serialise()

    def to_dict(self) -> dict[str, Any]:
        """Return an independent snapshot; editing it does not change the builder."""
        return copy.deepcopy(self._capsule)
