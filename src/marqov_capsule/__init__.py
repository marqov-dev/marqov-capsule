"""marqov-capsule: Standalone capsule format for reproducible workflows."""

__version__ = "1.0.0"

from .archive import content_id, pack_capsule, unpack_capsule
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
    "content_id",
    "pack_capsule",
    "unpack_capsule",
    "__version__",
]
