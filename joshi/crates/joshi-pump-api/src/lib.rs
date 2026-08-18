//! Read-only Pump product-API acquisition.
//!
//! This crate intentionally owns source-edge mechanics, not Pump product semantics. It keeps
//! exact response-body bytes, separates documented routes from observed product routes, and
//! refuses every method other than `GET`. Normalized records are provider assertions derived
//! from those bytes and remain quarantined until an observed schema fingerprint is promoted.

pub mod auth;
pub mod catalog;
pub mod client;
pub mod identity;
pub mod model;
pub mod normalize;
pub mod parity;
pub mod projection;
pub mod promotion;

pub use auth::{CredentialFileSession, NoSession, SessionMaterial, SessionProvider};
pub use catalog::{AccessClass, PaginationKind, RouteId, RouteSpec, Stability, TransportKind};
pub use client::{ClientConfig, PumpApiClient, PumpApiError};
pub use identity::{AcquisitionReservation, IdentityStore};
pub use model::{
    Acquisition, BodyCapture, CoverageGap, CoverageScope, CoverageWindow, FetchOutcome,
    FidelityGap, LogicalRequest, RequestParameters,
};
pub use normalize::{Normalization, NormalizedRecord, SchemaRegistry, TaggedScalar, normalize};
pub use parity::{ParityInput, ParityReport, compare};
pub use projection::{
    PARITY_REQUEST_FINGERPRINT_CONTRACT, ParityRequestProjection, parity_request_projection,
};
pub use promotion::{
    AuthDisposition, DirectParityHandoff, MismatchEvidence, ParityInputV2, ParityReportV2,
    ParitySource, PromotionOccurrence, PromotionReportV1, PromotionRunV1, SessionPathDisposition,
    compare_v2, direct_parity_input, evaluate_promotion,
};

/// Source-native wire contract. A later core adapter maps it into `joshi-evidence` without
/// changing the exact response bytes or conflating this digest with a store-batch digest.
pub const SOURCE_CONTRACT: &str = "joshi.pump_api.acquisition.v1";

/// Versioned route/access and fingerprint policy.
pub const ROUTE_CATALOG: &str = "joshi.pump_api.catalog.2026-08-16.v1";
