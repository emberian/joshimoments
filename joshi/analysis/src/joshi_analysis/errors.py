class AnalysisError(RuntimeError):
    """Base class for fail-closed analysis errors."""


class ManifestError(AnalysisError):
    """The manifest is malformed, self-inconsistent, or unsafe."""


class HashMismatchError(ManifestError):
    """Manifested bytes or logical rows do not match their hashes."""


class SchemaMismatchError(ManifestError):
    """A table does not have the exact manifested domain schema."""


class TemporalLeakageError(ManifestError):
    """An as-known snapshot contains information unavailable at its decision cut."""


class CoverageError(ManifestError):
    """Coverage rows and the manifested coverage account disagree."""


class ImmutableOutputError(AnalysisError):
    """A deterministic run destination already contains different bytes."""
