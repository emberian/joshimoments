//! Deterministic bin chunk plans under an observation-bound protocol constraint.

use joshi_domain::{ObservationId, ProtocolProfileId};
use thiserror::Error;

use crate::q64::BinId;

/// Maximum bin items admitted by one externally verified profile operation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ChunkConstraint {
    pub profile_id: ProtocolProfileId,
    pub source_observation_id: ObservationId,
    max_bin_items: u16,
}

impl ChunkConstraint {
    /// Creates a nonzero constraint. This value must come from an adapter/profile observation;
    /// the semantic kernel does not hardcode a UI or transaction limit.
    ///
    /// # Errors
    ///
    /// Refuses zero items per chunk.
    pub fn new(
        profile_id: ProtocolProfileId,
        source_observation_id: ObservationId,
        max_bin_items: u16,
    ) -> Result<Self, ChunkError> {
        if max_bin_items == 0 {
            Err(ChunkError::ZeroLimit)
        } else {
            Ok(Self {
                profile_id,
                source_observation_id,
                max_bin_items,
            })
        }
    }

    #[must_use]
    pub const fn max_bin_items(&self) -> u16 {
        self.max_bin_items
    }
}

/// One contiguous slice of the caller's ordered bin list.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BinChunk {
    pub first_input_index: usize,
    pub end_input_index_exclusive: usize,
    pub bin_ids: Vec<BinId>,
}

/// Chunk-planning failure.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum ChunkError {
    #[error("chunk limit is zero")]
    ZeroLimit,
    #[error("bin list is not strictly ordered")]
    UnorderedBins,
}

/// Splits a strictly ordered list without dropping or reordering bins.
///
/// # Errors
///
/// Refuses duplicate or unordered input bins.
pub fn chunk_bin_ids(
    bin_ids: &[BinId],
    constraint: &ChunkConstraint,
) -> Result<Vec<BinChunk>, ChunkError> {
    if bin_ids.windows(2).any(|window| window[0] >= window[1]) {
        return Err(ChunkError::UnorderedBins);
    }
    let width = usize::from(constraint.max_bin_items);
    Ok(bin_ids
        .chunks(width)
        .enumerate()
        .map(|(chunk_index, values)| {
            let first_input_index = chunk_index * width;
            BinChunk {
                first_input_index,
                end_input_index_exclusive: first_input_index + values.len(),
                bin_ids: values.to_vec(),
            }
        })
        .collect())
}
