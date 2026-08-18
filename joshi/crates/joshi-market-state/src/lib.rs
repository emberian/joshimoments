//! Strict, store-backed point-in-time circulation for market context.
//!
//! Social/product occurrences, lifecycle claims, pool account closures, and marked attention
//! events remain separate stored streams. They meet only in an explicit snapshot query carrying
//! valid-time, knowledge-time, commit, and finalized-chain cuts. This crate is read-only: it has
//! no collector, authentication, wallet, transaction, signing, or submission surface.

#![forbid(unsafe_code)]

mod attention_adapter;
mod lifecycle_adapter;
mod model;
mod pool_adapter;
mod reducer;
#[cfg(feature = "sqlite-store")]
mod store_adapter;

pub use attention_adapter::{AttentionAdapterError, adapt_attention_event, adapt_social_input};
pub use lifecycle_adapter::{LifecycleAdapterError, LifecycleFactContext, adapt_lifecycle_fact};
pub use model::*;
pub use pool_adapter::{PoolAdapterError, adapt_pool_bundle};
pub use reducer::{EffectiveFactReader, MarketStateReducer, ReaderError};
#[cfg(feature = "sqlite-store")]
pub use store_adapter::{StoreArtifactError, snapshot_store_capability};

/// Stored assertion extension contract consumed by this lane.
pub const MARKET_FACT_CONTRACT: &str = "joshi.market-state.fact.v1";

/// Immutable reducer artifact contract produced by this lane.
pub const MARKET_STATE_SNAPSHOT_CONTRACT: &str = "joshi.source_fact_artifact.market_state.v1";

/// This lane cannot express execution authority.
pub const READ_ONLY_AUTHORITY: &str = "read_only_no_execution";

#[cfg(test)]
mod tests;
