//! One hot lease: promote one subject against an exact resource snapshot, open one filtered
//! subscription for a bounded window under a preregistered finite budget, retain every frame
//! through the durable admission path, settle conservatively, and stop.
//!
//! The four pieces are deliberately separable. [`resources`] reads this machine. [`ledger`] is a
//! pure state machine that turns the source runner's typed outputs into retained frames and exact
//! unobserved intervals. [`run`] owns the one connection and the budget permit. [`retain`] puts
//! both the frames and the intervals into the sole catalog, and [`readback`] reads them out of a
//! reopened one.

pub mod census;
pub mod ledger;
pub mod readback;
pub mod resources;
pub mod retain;
pub mod run;

pub use census::{
    MINT_UNIVERSE_CONTRACT, MintSighting, MintUniverseV1, RetainedPayload, WRAPPED_SOL_MINT,
    census_coverage_id, commit_seq_of, derive_mint_universe,
};
pub use ledger::{
    INGRESS_STOP_HEADROOM_BYTES, LeaseGapV1, LeaseLedger, LeaseSignal, LeaseStop,
    RetainedLeaseFrame, SEVERITY_DEGRADED, SEVERITY_SCOPE_STOPPED,
};
pub use readback::{
    LEASE_READBACK_CONTRACT, LeaseReadbackV1, StoredCoverageGapV1, StoredCoverageWindowV1,
    read_lease,
};
pub use resources::{
    IngressOccupancy, RESOURCE_MEASUREMENT_CONTRACT, ResourceCeilings, ResourceMeasurementV1,
    measure,
};
pub use retain::{
    HOT_LANE_FAMILY, LEASE_RETENTION_CONTRACT, LeaseCommitContext, LeaseRetentionReceiptV1,
    SUBSCRIPTION_METHOD, WEBSOCKET_SOURCE_ID, WEBSOCKET_SOURCE_NAMESPACE, commit_lease,
    utc_from_millis, websocket_source_registration,
};
pub use run::{
    DURABLE_BYTES_PER_INGRESS_BYTE, HotLeaseRun, LEASE_DRAIN_GRACE_MS,
    LEASE_MAX_INGRESS_BYTES_PER_SECOND, LEASE_SETTLEMENT_CONTRACT, LeaseSettlementV1,
    lease_attempt_claim, lease_run_budget, now_millis, run_hot_lease, settle_lease,
};

#[cfg(test)]
mod tests;
