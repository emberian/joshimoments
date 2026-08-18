//! Versioned protocol and lifecycle semantics.

use joshi_domain::{ObservationId, ProtocolProfileId, StableString, VenueId};

/// Protocol family whose operation graph a profile reproduces.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum ProtocolFamily {
    PumpCurve,
    PumpSwapCanonical,
    PumpSwapNonCanonical,
    MeteoraDlmm,
}

/// Venue lifecycle observed at the state used for a calculation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum VenueLifecycle {
    Trading,
    Complete,
    Migrated,
    Disabled,
    Unknown(StableString),
}

/// Immutable description of the program/source behavior reproduced by one calculator profile.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProtocolProfile {
    pub id: ProtocolProfileId,
    pub venue: VenueId,
    pub family: ProtocolFamily,
    pub program_identity: StableString,
    pub source_revision: StableString,
}

/// Lifecycle value and the exact retained observation supporting it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservedLifecycle {
    pub state: VenueLifecycle,
    pub observation_id: ObservationId,
}
