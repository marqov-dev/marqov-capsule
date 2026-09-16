"""marqov-capsule — open standard and tooling for reproducible quantum experiments."""
from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.validator import CapsuleValidator
from marqov_capsule.redactor import CapsuleRedactor, RedactorError

try:
    from marqov_capsule.verifier import CapsuleVerifier
    _verifier_available = True
except ImportError:
    _verifier_available = False

__version__ = "0.1.1"
__all__ = ["CapsuleBuilder", "CapsuleValidator", "CapsuleRedactor", "RedactorError"]
if _verifier_available:
    __all__.append("CapsuleVerifier")
