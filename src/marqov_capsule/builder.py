"""CapsuleBuilder — constructs and seals capsule.yaml manifests."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from marqov_capsule._canonical import compute_capsule_id
from marqov_capsule.redactor import CapsuleRedactor

# Root-level files deliberately left out of .checksums: .checksums cannot hash
# itself, and capsule.yaml embeds the digest of .checksums (it is covered by the
# capsule ID instead). Matched against the path relative to the capsule root, not
# the basename — payload/capsule.yaml is ordinary payload and must be hashed.
# CapsuleVerifier imports this so the seal and verify sides cannot drift: a file
# one side skips and the other flags is either a false failure or a blind spot.
UNCHECKSUMMED_ROOT_FILES = frozenset({".checksums", "capsule.yaml"})


class CapsuleBuilder:
    """Build reproducible capsule YAML manifests following the Marqov Capsule v1 standard."""

    def __init__(self):
        self._capsule: dict[str, Any] = {}
        self._task_executions: list[dict[str, Any]] = []
        self._sealed = False

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> "CapsuleBuilder":
        """Load an existing draft manifest into a new builder.

        Used by the CLI `seal` command which reads a capsule.yaml written by
        `init` or by hand. Deep-copies the dict so subsequent mutations don't
        alias the caller's data.
        """
        import copy
        b = cls()
        b._capsule = copy.deepcopy(manifest)
        b._task_executions = list(b._capsule.get("task_executions", []))
        return b

    def seal(self, capsule_dir: str | Path, sealed_by: Optional[str] = None,
             warn_only: bool = False, derived_from: Optional[str] = None) -> str:
        """Full sealing sequence: credential scan → checksums → transition → save → ID.

        This is the one-call path for the CLI. Returns the capsule ID (64 hex chars).
        Raises RedactorError if secrets are found and warn_only is False.
        """
        self.seal_capsule(capsule_dir, sealed_by=sealed_by, warn_only=warn_only,
                          derived_from=derived_from)
        self.save_capsule(Path(capsule_dir) / "capsule.yaml")
        return compute_capsule_id(self._capsule)

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
            "parameters": parameters or {},
            "workflow_ref": workflow_ref,
            "environment_ref": environment_ref,
            "max_budget_usd": max_budget_usd,
            "tags": tags or [],
            "requirements": requirements,
            "task_executions": [],
            "digests": {},
            "extensions": {},
        }
        self._task_executions = []
        self._sealed = False
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
        execution: dict[str, Any] = {
            "task_id": task_id,
            "status": status,
            "result_type": result_type,
            "backend": backend,
        }
        if verification_settings:
            execution["verification_settings"] = verification_settings
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
        import json as _json
        if isinstance(data, dict):
            data_str = _json.dumps(data, sort_keys=True, default=str)
        else:
            data_str = str(data)
        digest = hashlib.sha256(data_str.encode()).hexdigest()
        self._capsule["digests"][digest_name] = f"sha256:{digest}"
        return self

    def seal_capsule(
        self,
        capsule_dir: str | Path,
        sealed_by: Optional[str] = None,
        notes: str = "",
        warn_only: bool = False,
        derived_from: Optional[str] = None,
    ) -> dict[str, Any]:
        """Seal the capsule following spec §5 sealing order.

        Sealing order:
          1. Credential scan via CapsuleRedactor.
          2. save_checksums() — excludes .checksums and capsule.yaml.
          3. checksums_digest = SHA-256 of .checksums file bytes.
          4. Embed checksums_digest (and derived_from if provided) in manifest.
          5. Transition lifecycle_state → sealed.
          (Caller must call save_capsule() after this to write capsule.yaml.)

        Returns redactor scan result dict.
        Raises ValueError if requirements not set.
        Raises RedactorError if secrets found and not warn_only.
        """
        req = self._capsule.get("requirements")
        if not req or "paradigm" not in req or "max_qubit_count" not in req:
            raise ValueError(
                "requirements with 'paradigm' and 'max_qubit_count' must be set before sealing"
            )

        capsule_path = Path(capsule_dir)

        # Step 1: credential scan
        redactor = CapsuleRedactor(capsule_path, mode="warn_only" if warn_only else "block")
        scan_result = redactor.scan_and_raise()

        # Step 2: checksums (excludes .checksums and capsule.yaml)
        self.save_checksums(capsule_path)

        # Step 3: checksums_digest
        checksums_bytes = (capsule_path / ".checksums").read_bytes()
        checksums_digest = "sha256:" + hashlib.sha256(checksums_bytes).hexdigest()

        # Step 4: embed in manifest
        self._capsule["checksums_digest"] = checksums_digest
        if derived_from is not None:
            self._capsule["derived_from"] = derived_from

        # Step 5: lifecycle transition
        self._capsule["lifecycle_state"] = "sealed"
        self._capsule["sealed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._capsule["sealed_by"] = sealed_by or "marqov-capsule"
        if notes:
            self._capsule["seal_notes"] = notes

        self._sealed = True
        return scan_result

    def save_capsule(self, filepath: str | Path) -> Path:
        """Write capsule.yaml to disk."""
        path = Path(filepath)
        if path.is_dir() or not path.suffix:
            path = path / "capsule.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self._capsule, f, default_flow_style=False, sort_keys=False)
        return path

    def save_checksums(self, capsule_dir: str | Path) -> Path:
        """Compute and write .checksums for all files except .checksums and capsule.yaml.

        Raises RuntimeError if called after seal_capsule() — rewriting .checksums would
        make the embedded checksums_digest stale and silently break the Merkle chain.
        """
        if self._sealed:
            raise RuntimeError(
                "Cannot rewrite .checksums after sealed state: checksums_digest would become stale. "
                "Call seal_capsule() again if payload files have changed."
            )
        capsule_path = Path(capsule_dir)
        checksums: dict[str, str] = {}
        for file_path in sorted(capsule_path.rglob("*")):
            # Never follow symlinks — hashing a link would enroll an outside file's
            # content into this capsule (exfiltration when re-sealing a received capsule).
            if file_path.is_symlink():
                continue
            if file_path.is_file():
                rel = str(file_path.relative_to(capsule_path))
                if rel in UNCHECKSUMMED_ROOT_FILES:
                    continue
                digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
                checksums[rel] = f"sha256:{digest}"
        checksums_path = capsule_path / ".checksums"
        with open(checksums_path, "w") as f:
            yaml.dump(checksums, f, default_flow_style=False, sort_keys=True)
        return checksums_path

    def to_yaml(self) -> str:
        return yaml.dump(self._capsule, default_flow_style=False, sort_keys=False)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._capsule)
