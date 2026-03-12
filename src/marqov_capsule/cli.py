"""
Command-line interface for marqov-capsule.

Provides subcommands for scaffolding, sealing, and verifying capsules.

Usage:
    capsule init <name>           Scaffold a new capsule directory
    capsule verify <path>         Verify capsule integrity
    capsule seal <path>           Seal a draft capsule

All commands support --json for structured output (CI pipelines).
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

from marqov_capsule import __version__


def main(argv=None):
    """Entry point for the capsule CLI."""
    parser = argparse.ArgumentParser(
        prog="capsule",
        description="marqov-capsule: Reproducible quantum-classical workflow packaging",
    )
    parser.add_argument(
        "--version", action="version", version=f"marqov-capsule {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- init ---
    init_parser = subparsers.add_parser("init", help="Scaffold a new capsule directory")
    init_parser.add_argument("name", help="Capsule name (kebab-case)")
    init_parser.add_argument(
        "--output-dir", default=".", help="Parent directory (default: current)"
    )
    init_parser.add_argument(
        "--description", default="", help="Capsule description"
    )
    init_parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output JSON instead of human-readable text"
    )

    # --- verify ---
    verify_parser = subparsers.add_parser("verify", help="Verify capsule integrity")
    verify_parser.add_argument("path", help="Path to capsule directory")
    verify_parser.add_argument(
        "--method", choices=["deterministic", "statistical", "verification-only"],
        default=None,
        help="Verification method (default: auto-detect from reproducibility_tier)"
    )
    verify_parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output JSON instead of human-readable text"
    )

    # --- seal ---
    seal_parser = subparsers.add_parser("seal", help="Seal a draft capsule")
    seal_parser.add_argument("path", help="Path to capsule directory")
    seal_parser.add_argument(
        "--no-lock", action="store_true",
        help="Skip environment locking"
    )
    seal_parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output JSON instead of human-readable text"
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "init":
            _cmd_init(args)
        elif args.command == "verify":
            _cmd_verify(args)
        elif args.command == "seal":
            _cmd_seal(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_init(args):
    """Scaffold a new capsule directory."""
    capsule_dir = Path(args.output_dir) / f"{args.name}.capsule"

    if capsule_dir.exists():
        print(f"Error: Directory already exists: {capsule_dir}", file=sys.stderr)
        sys.exit(1)

    capsule_dir.mkdir(parents=True)

    # Create capsule.yaml (draft)
    capsule_data = {
        "version": "1.0.0",
        "name": args.name,
        "description": args.description or f"Capsule: {args.name}",
        "created_at": None,  # Will be set on start
        "created_by": "unknown@example.com",
        "capsule_format_version": __version__,
        "lifecycle_state": "draft",
        "workflow_ref": "workflow.yaml",
        "environment_ref": "environment.yaml",
        "backends_ref": "backends.yaml",
        "sealed_at": None,
        "sealed_by": None,
        "reproducibility_tier": "deterministic",
        "provenance": {
            "run_id": None,
            "git_sha": None,
            "git_repo": None,
            "parent_capsule_id": None,
            "related_capsule_ids": [],
            "custom_metadata": {},
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
            "max_budget_usd": None,
            "estimated_cost_usd": None,
            "actual_cost_usd": None,
            "cost_breakdown": [],
        },
        "execution": {
            "start_time": None,
            "end_time": None,
            "wall_time_seconds": None,
            "total_queue_time_seconds": None,
            "exit_code": None,
            "exit_message": None,
            "num_tasks": None,
            "total_shots": None,
            "carbon_footprint_kg_co2": None,
        },
        "verifications": [],
        "extensions": {},
    }

    with open(capsule_dir / "capsule.yaml", "w") as f:
        yaml.dump(capsule_data, f, default_flow_style=False, sort_keys=False)

    # Create stub files
    _write_stub(capsule_dir / "workflow.yaml", {
        "tasks": [],
        "description": f"Workflow definition for {args.name}",
    })
    _write_stub(capsule_dir / "environment.yaml", {
        "python_version": None,
        "dependencies": [],
        "description": f"Environment for {args.name}",
    })
    _write_stub(capsule_dir / "backends.yaml", {
        "backends": [],
        "description": f"Backend configuration for {args.name}",
    })

    if args.json_output:
        print(json.dumps({"name": args.name, "path": str(capsule_dir)}, indent=2))
    else:
        print(f"Created capsule: {capsule_dir}")
        print(f"  capsule.yaml     - manifest (edit this)")
        print(f"  workflow.yaml    - task DAG")
        print(f"  environment.yaml - dependencies")
        print(f"  backends.yaml    - backend configs")


def _cmd_verify(args):
    """Verify capsule integrity."""
    from marqov_capsule import CapsuleVerifier

    capsule_dir = Path(args.path)
    if not capsule_dir.is_dir():
        print(f"Error: Not a directory: {capsule_dir}", file=sys.stderr)
        sys.exit(1)

    capsule_yaml = capsule_dir / "capsule.yaml"
    if not capsule_yaml.exists():
        print(f"Error: No capsule.yaml in {capsule_dir}", file=sys.stderr)
        sys.exit(1)

    verifier = CapsuleVerifier()

    # Checksum verification
    checksum_result = verifier.verify_checksums(capsule_dir)

    # Load and verify capsule data
    capsule = verifier.load_capsule(str(capsule_yaml))
    verify_result = verifier.verify_capsule(
        capsule,
        method=args.method,
    )

    overall_pass = checksum_result["passed"] and verify_result["verification_passed"]

    if args.json_output:
        output = {
            "path": str(capsule_dir),
            "passed": overall_pass,
            "checksums": checksum_result,
            "verification": verify_result,
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        status = "PASS" if overall_pass else "FAIL"
        print(f"Capsule: {capsule.get('name', 'unknown')}")
        print(f"Path:    {capsule_dir}")
        print(f"Status:  {status}")
        print()

        # Checksums
        if checksum_result["passed"]:
            print("Checksums: PASS")
        else:
            print("Checksums: FAIL")
            if checksum_result.get("mismatched"):
                print(f"  Mismatched: {', '.join(checksum_result['mismatched'])}")
            if checksum_result.get("missing"):
                print(f"  Missing:    {', '.join(checksum_result['missing'])}")

        # Verification
        method = verify_result.get("method", "unknown")
        v_pass = verify_result["verification_passed"]
        print(f"Verification ({method}): {'PASS' if v_pass else 'FAIL'}")

        if verify_result.get("warnings"):
            for w in verify_result["warnings"]:
                print(f"  Warning: {w}")

    sys.exit(0 if overall_pass else 1)


def _cmd_seal(args):
    """Seal a draft capsule."""
    from marqov_capsule import CapsuleBuilder

    capsule_dir = Path(args.path)
    capsule_yaml = capsule_dir / "capsule.yaml"

    if not capsule_yaml.exists():
        print(f"Error: No capsule.yaml in {capsule_dir}", file=sys.stderr)
        sys.exit(1)

    with open(capsule_yaml) as f:
        data = yaml.safe_load(f)

    if data.get("lifecycle_state") == "sealed":
        print("Error: Capsule is already sealed.", file=sys.stderr)
        sys.exit(1)

    # Reconstruct a builder from the existing capsule data
    builder = CapsuleBuilder(
        name=data["name"],
        description=data.get("description", ""),
        creator_version=data.get("creator_version"),
        reproducibility_tier=data.get("reproducibility_tier", "deterministic"),
    )
    builder.start_capsule(
        parameters=data.get("provenance", {}).get("custom_metadata", {}),
        run_id=data.get("provenance", {}).get("run_id"),
    )

    # Preserve any existing extensions
    builder.capsule_data["extensions"] = data.get("extensions", {})

    sealed = builder.seal_capsule(
        exit_code=0,
        exit_message="Sealed via CLI",
        lock_environment=not args.no_lock,
    )

    builder.save_capsule(str(capsule_yaml))

    if args.json_output:
        print(json.dumps({
            "path": str(capsule_dir),
            "lifecycle_state": sealed["lifecycle_state"],
            "sealed_at": sealed.get("sealed_at"),
        }, indent=2))
    else:
        print(f"Sealed: {capsule_dir}")
        print(f"  sealed_at: {sealed.get('sealed_at')}")
        if not args.no_lock:
            print(f"  environment.lock.yaml: generated")

    sys.exit(0)


def _write_stub(path: Path, data: dict):
    """Write a stub YAML file."""
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
