"""marqov-capsule — open standard and tooling for reproducible quantum experiments."""

from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.redactor import CapsuleRedactor, RedactorError
from marqov_capsule.validator import CapsuleValidator
from marqov_capsule.verifier import CapsuleVerifier

# The one place the version is declared; pyproject.toml reads it from here.
__version__ = "0.2.4"
__all__ = [
    "CapsuleBuilder",
    "CapsuleValidator",
    "CapsuleRedactor",
    "RedactorError",
    "CapsuleVerifier",
]
