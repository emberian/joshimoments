use crate::{AsOfVector, SceneId, StableString, UtcTimestamp};
use serde::{Deserialize, Serialize};

/// What the operator actually received in one immutable scene.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct WitnessedView<T> {
    /// Query contract name.
    pub contract: StableString,
    /// Query contract version.
    pub version: StableString,
    /// Immutable scene identity.
    pub scene_id: SceneId,
    /// Independent source, projection, chain, and catalog watermarks.
    pub as_of: AsOfVector,
    /// Wall time at which this view was rendered.
    pub witnessed_at: UtcTimestamp,
    /// Versioned query payload.
    pub value: T,
}

/// A later reconstruction that may include evidence unavailable to an earlier scene.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RetrospectiveView<T> {
    /// Query contract name.
    pub contract: StableString,
    /// Query contract version.
    pub version: StableString,
    /// Full evidence/projection watermarks used by the reconstruction.
    pub as_of: AsOfVector,
    /// Named replay/projection build that produced the reconstruction.
    pub replay_build: StableString,
    /// Versioned query payload.
    pub value: T,
}

/// Explicitly paired witnessed and retrospective answers for comparison.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ViewBundle<T> {
    /// What was actually delivered at decision time.
    pub witnessed: WitnessedView<T>,
    /// What a later reconstruction concludes from its named evidence horizon.
    pub retrospective: RetrospectiveView<T>,
}
