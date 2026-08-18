export const BRIDGE_PROTOCOL = "joshi.pump-companion.bridge.v2" as const;
export const ACQUISITION_SCHEMA = "joshi.pump-companion.acquisition.v1" as const;
export const GAP_SCHEMA = "joshi.pump-companion.coverage-gap.v1" as const;
export const BATCH_SCHEMA = "joshi.pump_companion.capture_batch" as const;
export const RECEIPT_SCHEMA = "joshi.pump_companion.ingest_receipt" as const;
export const REQUEST_FINGERPRINT_CONTRACT = "pump-request-projection.v1" as const;
export const PARITY_REQUEST_FINGERPRINT_CONTRACT = "pump-parity-request-projection.v2" as const;
export const SOURCE_CLOCK_CONTRACT = "browser-wall-rfc3339-utc-milliseconds.v1" as const;

export const CONFIG_STORAGE_KEY = "pumpCompanionConfigV1" as const;
export const INSTALLATION_STORAGE_KEY = "pumpCompanionInstallationV1" as const;
export const CATALOG_BINDING_STORAGE_KEY = "pumpCompanionCatalogBindingV1" as const;
export const SESSION_STORAGE_KEY = "pumpCompanionSessionV1" as const;
export const RETRY_ALARM = "pump-companion-loopback-retry" as const;

export const LOOPBACK_SINK = "http://127.0.0.1:43119/v1/observations/pump-companion" as const;

export const MAX_SOURCE_BODY_BYTES = 512 * 1024;
export const MAX_RAW_BODY_BYTES = 256 * 1024;
export const MAX_RECORDS_PER_RESPONSE = 100;
export const MAX_QUEUE_ITEMS = 512;
export const MAX_QUEUE_BYTES = 2 * 1024 * 1024;
export const MAX_GAP_ITEMS = 256;
export const MAX_GAP_BYTES = 256 * 1024;
export const MAX_BATCH_ITEMS = 25;
export const MAX_BATCH_BYTES = 256 * 1024;
export const MAX_BATCHES_PER_FLUSH = 4;
export const RETRY_MIN_MS = 1_000;
export const RETRY_MAX_MS = 60_000;
