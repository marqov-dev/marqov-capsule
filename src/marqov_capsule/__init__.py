"""marqov-capsule: Standalone capsule format for reproducible workflows."""

__version__ = "1.0.0"

from .builder import CapsuleBuilder
from .verifier import CapsuleVerifier

try:
    from .validator import CapsuleValidator
except ImportError:
    pass  # jsonschema not installed; CapsuleValidator unavailable

__all__ = [
    "CapsuleBuilder",
    "CapsuleVerifier",
    "CapsuleValidator",
    "__version__",
]
