"""Read-only local intelligence services for shitcoims.

This package intentionally has no dependency on Sentinel's executor,
transaction signer, or wallet keypair modules.
"""

from .config import IntelligenceConfig, IntelligenceConfigError, load_intelligence_config
from .models import (
    Cursor,
    Feature,
    Finality,
    HealthStatus,
    Observation,
    RawBlob,
    Source,
    SourceHealth,
    StoredObservation,
    WatchEntry,
    Watchlist,
    request_fingerprint,
)
from .storage import (
    CursorConflict,
    ImmutableConflict,
    InsertResult,
    IntelligenceStorageError,
    IntelligenceStore,
    ObservationPage,
    RawBlobInsertResult,
    SingleWriter,
    StorageQuotaExceeded,
    StorageSummary,
    WriterQueueFull,
)

__all__ = [
    "Cursor",
    "CursorConflict",
    "Feature",
    "Finality",
    "HealthStatus",
    "ImmutableConflict",
    "InsertResult",
    "IntelligenceConfig",
    "IntelligenceConfigError",
    "IntelligenceStorageError",
    "IntelligenceStore",
    "Observation",
    "ObservationPage",
    "RawBlob",
    "RawBlobInsertResult",
    "SingleWriter",
    "Source",
    "SourceHealth",
    "StorageQuotaExceeded",
    "StorageSummary",
    "StoredObservation",
    "WatchEntry",
    "Watchlist",
    "WriterQueueFull",
    "load_intelligence_config",
    "request_fingerprint",
]
