//! Read-only Pump product-API acquisition.
//!
//! This crate intentionally owns source-edge mechanics, not Pump product semantics. It keeps
//! exact response-body bytes, separates documented routes from observed product routes, and
//! refuses every method other than `GET`. Normalized records are provider assertions derived
//! from those bytes and remain quarantined until an observed schema fingerprint is promoted.

pub mod audit;
pub mod auth;
pub mod auth_session;
pub mod catalog;
pub mod client;
pub mod identity;
pub mod model;
pub mod normalize;
pub mod parity;
pub mod product_identity;
pub mod projection;
pub mod promotion;
pub mod reserves;
pub mod row_projection;
pub mod trust;

pub use audit::{
    ACQUISITION_AUDIT_V1, AcquisitionAuditV1, AuditCheckRecord, AuditFamily, AuditFinding,
    AuditLocus, AuditSeverity, CheckVerdict, NotExaminedV1, OUTCOME_AUDIT_V1, OutcomeAuditV1,
    SuppliedReview, audit_acquisition, audit_fetch_outcome, select_review,
};
pub use auth::{CredentialFileSession, NoSession, SessionMaterial, SessionProvider};
pub use auth_session::{SiwsError, SiwsSession, SiwsSessionProvider, WalletSigner};
pub use catalog::{AccessClass, PaginationKind, RouteId, RouteSpec, Stability, TransportKind};
pub use client::{ClientConfig, PumpApiClient, PumpApiError};
pub use identity::{AcquisitionReservation, IdentityStore};
pub use model::{
    Acquisition, BodyCapture, CoverageGap, CoverageScope, CoverageWindow, FetchOutcome,
    FidelityGap, LogicalRequest, RequestParameters,
};
pub use normalize::{
    Normalization, NormalizedRecord, SchemaRegistry, TaggedScalar, fingerprint_of_shape, normalize,
    normalize_with_row_projection, schema_fingerprint, schema_shape,
};
pub use parity::{ParityInput, ParityReport, compare};
pub use product_identity::{
    IdentityClaimError, PRODUCT_IDENTITY_CLAIM_V1, ProductIdentityClaimV1, product_identity_claim,
};
pub use projection::{
    PARITY_REQUEST_FINGERPRINT_CONTRACT, ParityRequestProjection, parity_request_projection,
};
pub use promotion::{
    AuthDisposition, DirectParityHandoff, MismatchEvidence, ParityInputV2, ParityReportV2,
    ParitySource, PromotionOccurrence, PromotionReportV1, PromotionRunV1, SessionPathDisposition,
    compare_v2, direct_parity_input, evaluate_promotion,
};

pub use reserves::{
    CurveState, OnCurveReserves, ReserveRefusal, curve_state, price_bearing_reserves,
};
pub use row_projection::{
    ROW_PROJECTION_REVIEW_V1, RowProjectionReviewV1, decide_row_projection_trust,
    observed_row_leaves,
};
pub use trust::{
    AuthenticatedPathDecision, SCHEMA_REVIEW_V1, SCHEMA_TRUST_DECISION_V1, SESSION_PATH_NOTE_V1,
    SchemaReviewV1, SchemaTrustDecisionV1, SchemaTrustOutcome, SessionPathNoteV1, TrustError,
    decide_schema_trust, session_path_note,
};

/// Source-native wire contract. A later core adapter maps it into `joshi-evidence` without
/// changing the exact response bytes or conflating this digest with a store-batch digest.
pub const SOURCE_CONTRACT: &str = "joshi.pump_api.acquisition.v1";

/// Versioned route/access and fingerprint policy.
pub const ROUTE_CATALOG: &str = "joshi.pump_api.catalog.2026-08-16.v1";
