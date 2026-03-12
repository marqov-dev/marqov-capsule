"""
Capsule builder for generating reproducible quantum workflow artifacts.

Creates comprehensive YAML metadata including environment info, parameters,
execution details, QPU calibration data, cost tracking, and cryptographic
digests for deterministic replay of hybrid quantum-classical workflows.
"""

import hashlib
import json
import platform
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import yaml
except ImportError:
    raise ImportError("pyyaml is required. Install with: pip install pyyaml")

try:
    import numpy as np
except ImportError:
    np = None

# Capsule format version — do NOT import from __init__ (circular import).
_VERSION = "1.0.0"

_VALID_TIERS = {"deterministic", "statistical", "verification-only"}


class CapsuleBuilder:
    """
    Builder for creating reproducible quantum workflow Capsules.

    Generates comprehensive YAML metadata that enables deterministic
    replay of hybrid quantum-classical-HPC workflows.

    Lifecycle:
        1. __init__() - Initialize builder
        2. start_capsule() - Start capturing metadata
        3. add_task_execution() - Record each task execution
        4. add_result_digest() - Hash result data
        5. seal_capsule() - Finalize and seal (make immutable)
        6. save_capsule() - Write to disk

    Example:
        >>> builder = CapsuleBuilder(name="vqe-h2")
        >>> builder.start_capsule(parameters={"molecule": "H2"})
        >>> builder.add_task_execution("hamiltonian", backend="local", outputs={...})
        >>> builder.add_task_execution("vqe_step", backend="braket-ionq",
        ...                           outputs={...}, cost_usd=3.55)
        >>> builder.seal_capsule()
        >>> builder.save_capsule("vqe-h2.capsule/capsule.yaml")
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        created_by: Optional[str] = None,
        git_repo: Optional[str] = None,
        git_sha: Optional[str] = None,
        creator_version: Optional[str] = None,
        reproducibility_tier: str = "deterministic",
    ):
        """
        Initialize the Capsule builder.

        Args:
            name: Capsule name (kebab-case recommended)
            description: Brief description of the workflow
            created_by: Email of creator
            git_repo: Git repository URL
            git_sha: Git commit SHA
            creator_version: Version string of the tool creating this capsule
            reproducibility_tier: Reproducibility guarantee level; one of
                "deterministic", "statistical", or "verification-only"
        """
        if reproducibility_tier not in _VALID_TIERS:
            raise ValueError(
                f"reproducibility_tier must be one of {_VALID_TIERS}, got {reproducibility_tier!r}"
            )
        self.name = name
        self.description = description
        self.created_by = created_by or "unknown@example.com"
        self.git_repo = git_repo
        self.git_sha = git_sha
        self.creator_version = creator_version
        self.reproducibility_tier = reproducibility_tier

        self.capsule_data: Dict[str, Any] = {}
        self.task_executions: List[Dict[str, Any]] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.total_cost_usd: float = 0.0
        self.total_shots: int = 0
        self.lifecycle_state: str = "draft"

    def start_capsule(
        self,
        parameters: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        workflow_ref: str = "workflow.yaml",
        environment_ref: str = "environment.yaml",
        backends_ref: str = "backends.yaml",
        max_budget_usd: Optional[float] = None,
    ) -> None:
        """
        Start building a new Capsule.

        Args:
            parameters: Workflow input parameters
            run_id: Unique identifier for this run (auto-generated if None)
            workflow_ref: Path to workflow.yaml
            environment_ref: Path to environment.yaml
            backends_ref: Path to backends.yaml
            max_budget_usd: Maximum budget for this execution
        """
        if run_id is None:
            run_id = str(uuid.uuid4())

        self.start_time = time.time()
        created_at = datetime.now().isoformat() + "Z"

        # Initialize Capsule structure following v1.0 schema
        self.capsule_data = {
            "version": "1.0.0",
            "name": self.name,
            "description": self.description or f"Quantum workflow: {self.name}",
            "created_at": created_at,
            "created_by": self.created_by,
            "capsule_format_version": _VERSION,
            **( {"creator_version": self.creator_version} if self.creator_version is not None else {} ),
            "lifecycle_state": "draft",
            "reproducibility_tier": self.reproducibility_tier,
            "workflow_ref": workflow_ref,
            "environment_ref": environment_ref,
            "backends_ref": backends_ref,
            "sealed_at": None,
            "sealed_by": None,
            "provenance": {
                "run_id": run_id,
                "git_sha": self.git_sha,
                "git_repo": self.git_repo,
                "parent_capsule_id": None,
                "related_capsule_ids": [],
                "custom_metadata": parameters or {},
            },
            "compliance": {
                "regulatory_framework": None,
                "retention_years": None,
                "doi": None,
                "embargo_until": None,
                "approvals": [],
            },
            "digests": {
                "workflow": None,
                "environment": None,
                "backends": None,
                "data": None,
                "results": None,
                "provenance": None,
            },
            "cost": {
                "max_budget_usd": max_budget_usd,
                "estimated_cost_usd": None,
                "actual_cost_usd": 0.0,
                "cost_breakdown": [],
            },
            "execution": {
                "start_time": datetime.fromtimestamp(self.start_time).isoformat() + "Z",
                "end_time": None,
                "wall_time_seconds": None,
                "total_queue_time_seconds": 0.0,
                "exit_code": None,
                "exit_message": None,
                "num_tasks": 0,
                "total_shots": 0,
                "carbon_footprint_kg_co2": None,
            },
            "verifications": [],
            "extensions": {},
        }

        self.lifecycle_state = "draft"

    def add_task_execution(
        self,
        task_id: str,
        backend: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        wall_time_seconds: Optional[float] = None,
        queue_time_seconds: float = 0.0,
        cost_usd: float = 0.0,
        shots: Optional[int] = None,
        outputs: Optional[Dict[str, Any]] = None,
        qpu_calibration: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None,
    ) -> None:
        """
        Record execution of a single task.

        Args:
            task_id: Task identifier (e.g., "vqe_iteration_1")
            backend: Backend used (e.g., "braket-ionq", "local")
            start_time: Task start timestamp
            end_time: Task end timestamp
            wall_time_seconds: Task execution time
            queue_time_seconds: Time spent in queue
            cost_usd: Cost of this task execution
            shots: Number of QPU shots (for quantum tasks)
            outputs: Task output data (will be hashed)
            qpu_calibration: QPU calibration snapshot (for quantum tasks)
            job_id: Backend job identifier
        """
        task_record = {
            "task_id": task_id,
            "backend": backend,
            "start_time": start_time.isoformat() + "Z" if start_time else None,
            "end_time": end_time.isoformat() + "Z" if end_time else None,
            "wall_time_seconds": wall_time_seconds,
            "queue_time_seconds": queue_time_seconds,
            "cost_usd": cost_usd,
        }

        if shots is not None:
            task_record["shots"] = shots
            self.total_shots += shots

        if job_id is not None:
            task_record["job_id"] = job_id

        if qpu_calibration is not None:
            task_record["qpu_calibration"] = qpu_calibration

        if outputs is not None:
            # Compute digest of outputs
            output_digest = self._compute_data_digest(outputs)
            task_record["outputs_digest"] = output_digest

        self.task_executions.append(task_record)

        # Update totals
        self.total_cost_usd += cost_usd
        self.capsule_data["execution"]["num_tasks"] += 1
        self.capsule_data["execution"]["total_queue_time_seconds"] += queue_time_seconds
        self.capsule_data["execution"]["total_shots"] = self.total_shots
        self.capsule_data["cost"]["actual_cost_usd"] = self.total_cost_usd

        # Add to cost breakdown
        if cost_usd > 0:
            self.capsule_data["cost"]["cost_breakdown"].append({
                "task_id": task_id,
                "backend": backend,
                "cost_usd": cost_usd,
                "shots": shots,
                "wall_time_seconds": wall_time_seconds,
            })

    def add_result_digest(
        self,
        data: Any,
        digest_name: str,
        digest_type: str = "deterministic"
    ) -> str:
        """
        Add a cryptographic digest of result data.

        Args:
            data: Result data to hash (numpy array, dict, etc.)
            digest_name: Name for this digest (e.g., "final_energy")
            digest_type: "deterministic" or "statistical"

        Returns:
            SHA256 digest string (format: "sha256:HEX")
        """
        digest = self._compute_data_digest(data)

        # Store in extensions for easy access
        if "result_digests" not in self.capsule_data["extensions"]:
            self.capsule_data["extensions"]["result_digests"] = {}

        self.capsule_data["extensions"]["result_digests"][digest_name] = {
            "digest": digest,
            "type": digest_type,
        }

        return digest

    def add_qpu_calibration(
        self,
        device_arn: str,
        calibration_timestamp: datetime,
        num_qubits: int,
        connectivity: str,
        gate_fidelities: Optional[Dict[str, Any]] = None,
        qubit_properties: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Add QPU calibration snapshot to extensions.

        Args:
            device_arn: Device ARN or identifier
            calibration_timestamp: When calibration was performed
            num_qubits: Number of qubits
            connectivity: Connectivity type (all-to-all, limited, etc.)
            gate_fidelities: Gate fidelity statistics
            qubit_properties: Per-qubit properties (T1, T2, readout error)
        """
        calibration_data = {
            "device_arn": device_arn,
            "calibration_timestamp": calibration_timestamp.isoformat() + "Z",
            "num_qubits": num_qubits,
            "connectivity": connectivity,
        }

        if gate_fidelities is not None:
            calibration_data["gate_fidelities"] = gate_fidelities

        if qubit_properties is not None:
            calibration_data["qubit_properties"] = qubit_properties

        self.capsule_data["extensions"]["qpu_calibration"] = calibration_data

    def seal_capsule(
        self,
        exit_code: int = 0,
        exit_message: str = "Workflow completed successfully",
        sealed_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Seal the Capsule (transition to immutable state).

        Once sealed, the Capsule becomes immutable and ready for verification.

        Args:
            exit_code: Exit code (0 = success, non-zero = failure)
            exit_message: Exit message or error description
            sealed_by: Email of person sealing (defaults to created_by)

        Returns:
            Complete Capsule data dictionary
        """
        if self.start_time is None:
            raise ValueError("Capsule not started. Call start_capsule() first.")

        self.end_time = time.time()
        wall_time = self.end_time - self.start_time

        # Update execution section
        self.capsule_data["execution"]["end_time"] = (
            datetime.fromtimestamp(self.end_time).isoformat() + "Z"
        )
        self.capsule_data["execution"]["wall_time_seconds"] = wall_time
        self.capsule_data["execution"]["exit_code"] = exit_code
        self.capsule_data["execution"]["exit_message"] = exit_message

        # Seal metadata
        self.capsule_data["sealed_at"] = datetime.now().isoformat() + "Z"
        self.capsule_data["sealed_by"] = sealed_by or self.created_by
        self.capsule_data["lifecycle_state"] = "sealed"
        self.lifecycle_state = "sealed"

        # Compute deterministic digests from capsule data (D4).
        # Each digest hashes the actual content stored for that component,
        # falling back to an empty-string digest when no content is present.
        self.capsule_data["digests"]["workflow"] = self._compute_data_digest(
            self.capsule_data.get("workflow", "")
        )
        self.capsule_data["digests"]["environment"] = self._compute_data_digest(
            self.capsule_data.get("environment", "")
        )
        self.capsule_data["digests"]["backends"] = self._compute_data_digest(
            self.capsule_data.get("backends", "")
        )

        # Results digest — hash result_digests extension if present, else empty.
        self.capsule_data["digests"]["results"] = self._compute_data_digest(
            self.capsule_data.get("extensions", {}).get("result_digests", "")
        )

        # Compute provenance digest (hash of execution trace)
        provenance_data = {
            "tasks": self.task_executions,
            "execution": self.capsule_data["execution"],
        }
        self.capsule_data["digests"]["provenance"] = self._compute_data_digest(provenance_data)

        return self.capsule_data

    def save_capsule(
        self,
        filepath: Union[str, Path],
        create_dirs: bool = True
    ) -> None:
        """
        Save the Capsule to a YAML file.

        Args:
            filepath: Path to save the Capsule YAML
            create_dirs: Whether to create parent directories if they don't exist
        """
        if not self.capsule_data:
            raise ValueError("No Capsule data to save. Call seal_capsule() first.")

        filepath = Path(filepath)

        if create_dirs:
            filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w') as f:
            yaml.dump(
                self.capsule_data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        self._generate_checksums(filepath.parent)

    def _generate_checksums(self, capsule_dir: Path) -> None:
        """Generate .checksums manifest for all files in capsule directory."""
        checksums = []
        for filepath in sorted(capsule_dir.rglob("*")):
            if filepath.is_file() and filepath.name != ".checksums":
                rel_path = filepath.relative_to(capsule_dir)
                digest = hashlib.sha256(filepath.read_bytes()).hexdigest()
                checksums.append(f"sha256:{digest}  {rel_path}")
        checksums_path = capsule_dir / ".checksums"
        checksums_path.write_text("\n".join(checksums) + "\n")

    def _compute_data_digest(self, data: Any) -> str:
        """
        Compute SHA256 digest of arbitrary data.

        Args:
            data: Data to hash (numpy array, dict, list, etc.)

        Returns:
            Digest in format "sha256:HEX" (64 hex characters)
        """
        # Handle different data types
        if np is not None and isinstance(data, np.ndarray):
            # NumPy array - convert to bytes
            data_bytes = data.astype(np.float64).tobytes()
        elif isinstance(data, dict):
            # Dictionary - serialize to JSON
            data_bytes = json.dumps(data, sort_keys=True).encode('utf-8')
        elif isinstance(data, (list, tuple)):
            # List/tuple - serialize to JSON
            data_bytes = json.dumps(data).encode('utf-8')
        elif isinstance(data, str):
            # String - encode directly
            data_bytes = data.encode('utf-8')
        elif isinstance(data, bytes):
            # Already bytes
            data_bytes = data
        else:
            # Fallback - convert to string then encode
            data_bytes = str(data).encode('utf-8')

        # Compute SHA256
        digest_hex = hashlib.sha256(data_bytes).hexdigest()
        return f"sha256:{digest_hex}"

    def get_capsule_data(self) -> Dict[str, Any]:
        """
        Get current Capsule data (read-only).

        Returns:
            Capsule data dictionary
        """
        return self.capsule_data.copy()
