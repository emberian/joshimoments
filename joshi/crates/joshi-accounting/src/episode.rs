use std::collections::BTreeMap;

use thiserror::Error;

use crate::amount::AtomQty;
use crate::model::{EffectKey, EpisodeKey};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EpisodePhase {
    OpenFlat,
    Invested,
    WatchingFlat,
    Closed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EpochStatus {
    Open,
    Closed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InventoryEpoch {
    pub index: u32,
    pub status: EpochStatus,
    pub opened_by: EffectKey,
    pub closed_by: Option<EffectKey>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EpisodeProjection {
    pub id: EpisodeKey,
    pub phase: EpisodePhase,
    pub attributed_quantity: AtomQty,
    pub epochs: Vec<InventoryEpoch>,
}

impl EpisodeProjection {
    fn new(id: EpisodeKey) -> Self {
        Self {
            id,
            phase: EpisodePhase::OpenFlat,
            attributed_quantity: AtomQty::ZERO,
            epochs: Vec::new(),
        }
    }

    #[must_use]
    pub fn current_epoch_index(&self) -> Option<u32> {
        self.epochs.last().map(|epoch| epoch.index)
    }

    /// Records an attributed post-effect quantity without changing ledger truth.
    ///
    /// # Errors
    ///
    /// Returns an error for a closed episode, inconsistent epoch state, or epoch-counter overflow.
    pub fn observe_inventory(
        &mut self,
        effect: EffectKey,
        quantity_after: AtomQty,
    ) -> Result<(), EpisodeError> {
        if self.phase == EpisodePhase::Closed {
            return Err(EpisodeError::ClosedEpisode(self.id.to_string()));
        }
        let was_flat = self.attributed_quantity == AtomQty::ZERO;
        let now_flat = quantity_after == AtomQty::ZERO;

        match (was_flat, now_flat) {
            (true, false) => {
                let index = u32::try_from(self.epochs.len())
                    .ok()
                    .and_then(|value| value.checked_add(1))
                    .ok_or(EpisodeError::TooManyEpochs)?;
                self.epochs.push(InventoryEpoch {
                    index,
                    status: EpochStatus::Open,
                    opened_by: effect,
                    closed_by: None,
                });
                self.phase = EpisodePhase::Invested;
            }
            (false, true) => {
                let epoch = self
                    .epochs
                    .last_mut()
                    .ok_or_else(|| EpisodeError::MissingEpoch(self.id.to_string()))?;
                if epoch.status != EpochStatus::Open {
                    return Err(EpisodeError::MissingEpoch(self.id.to_string()));
                }
                epoch.status = EpochStatus::Closed;
                epoch.closed_by = Some(effect);
                self.phase = EpisodePhase::OpenFlat;
            }
            (false, false) => self.phase = EpisodePhase::Invested,
            (true, true) => {}
        }

        self.attributed_quantity = quantity_after;
        Ok(())
    }

    /// Marks continued attention while attributed inventory is exactly zero.
    ///
    /// # Errors
    ///
    /// Returns an error if the episode is closed or not flat.
    pub fn continue_watching_flat(&mut self) -> Result<(), EpisodeError> {
        if self.phase == EpisodePhase::Closed {
            return Err(EpisodeError::ClosedEpisode(self.id.to_string()));
        }
        if self.attributed_quantity != AtomQty::ZERO {
            return Err(EpisodeError::NotFlat(self.id.to_string()));
        }
        self.phase = EpisodePhase::WatchingFlat;
        Ok(())
    }

    /// Closes the operator episode independently from inventory history.
    ///
    /// # Errors
    ///
    /// Returns an error if the episode is already closed.
    pub fn close(&mut self) -> Result<(), EpisodeError> {
        if self.phase == EpisodePhase::Closed {
            return Err(EpisodeError::ClosedEpisode(self.id.to_string()));
        }
        self.phase = EpisodePhase::Closed;
        Ok(())
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct EpisodeBook {
    episodes: BTreeMap<EpisodeKey, EpisodeProjection>,
}

impl EpisodeBook {
    /// Begins a new operator episode in the open-flat phase.
    ///
    /// # Errors
    ///
    /// Returns an error when the episode ID already exists.
    pub fn begin(&mut self, id: EpisodeKey) -> Result<(), EpisodeError> {
        if self.episodes.contains_key(&id) {
            return Err(EpisodeError::DuplicateEpisode(id.to_string()));
        }
        self.episodes.insert(id.clone(), EpisodeProjection::new(id));
        Ok(())
    }

    #[must_use]
    pub fn get(&self, id: &EpisodeKey) -> Option<&EpisodeProjection> {
        self.episodes.get(id)
    }

    /// Returns a mutable existing episode projection.
    ///
    /// # Errors
    ///
    /// Returns an error when the episode ID is unknown.
    pub fn get_mut(&mut self, id: &EpisodeKey) -> Result<&mut EpisodeProjection, EpisodeError> {
        self.episodes
            .get_mut(id)
            .ok_or_else(|| EpisodeError::UnknownEpisode(id.to_string()))
    }
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum EpisodeError {
    #[error("duplicate episode: {0}")]
    DuplicateEpisode(String),
    #[error("unknown episode: {0}")]
    UnknownEpisode(String),
    #[error("episode is already closed: {0}")]
    ClosedEpisode(String),
    #[error("episode is not flat: {0}")]
    NotFlat(String),
    #[error("episode has nonzero inventory without an open epoch: {0}")]
    MissingEpoch(String),
    #[error("episode epoch counter overflow")]
    TooManyEpochs,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn flat_watch_and_reentry_stay_one_episode_but_start_new_epoch() {
        let episode_id = EpisodeKey::new("episode-a").unwrap();
        let mut episodes = EpisodeBook::default();
        episodes.begin(episode_id.clone()).unwrap();
        let episode = episodes.get_mut(&episode_id).unwrap();
        episode
            .observe_inventory(EffectKey::new("buy-1").unwrap(), AtomQty::new(1_000))
            .unwrap();
        episode
            .observe_inventory(EffectKey::new("sell-1").unwrap(), AtomQty::ZERO)
            .unwrap();
        episode.continue_watching_flat().unwrap();
        assert_eq!(episode.phase, EpisodePhase::WatchingFlat);
        episode
            .observe_inventory(EffectKey::new("buy-2").unwrap(), AtomQty::new(200))
            .unwrap();

        assert_eq!(episode.phase, EpisodePhase::Invested);
        assert_eq!(episode.current_epoch_index(), Some(2));
        assert_eq!(episode.epochs[0].status, EpochStatus::Closed);
        assert_eq!(episode.epochs[1].status, EpochStatus::Open);
    }
}
