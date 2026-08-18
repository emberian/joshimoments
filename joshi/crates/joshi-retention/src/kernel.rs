use crate::model::{
    ByteFact, CompletionState, DeletionPhase, DeletionReceipt, DeletionRequest, DomainId,
    Inventory, InventoryItem, InventoryKind, KeyState, Occurrence, OccurrenceId, ProtectionDomain,
    Refusal, Release, RetentionReport, RetentionStatus, Tombstone, occurrence_digest,
};
use std::collections::{BTreeMap, BTreeSet};
use thiserror::Error;

#[cfg(test)]
use crate::model::InventoryWitness;

/// Errors that prevent an occurrence from entering the authenticated prefix.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum KernelError {
    #[error("invalid inventory: {0}")]
    InvalidInventory(String),
    #[error("occurrence identity conflict: {0}")]
    IdentityConflict(OccurrenceId),
    #[error("unknown inventory item: {0}")]
    UnknownItem(OccurrenceId),
    #[error("unknown protection domain: {0}")]
    UnknownDomain(DomainId),
    #[error("occurrence has the wrong protection domain")]
    DomainMismatch,
    #[error("occurrence does not close its item set")]
    ItemSetMismatch,
    #[error("release is not covered by a tombstone")]
    MissingTombstone,
    #[error("request is not covered by a release")]
    MissingRelease,
    #[error("receipt has no matching request")]
    MissingRequest,
    #[error("receipt is stale or the request was not eligible")]
    StaleReceipt,
    #[error("key is already erased")]
    KeyAlreadyErased,
    #[error("key erasure does not cover the whole protection domain")]
    KeyScopeIncomplete,
    #[error("receipt phase is not valid for this request")]
    InvalidPhase,
    #[error("occurrence clock regressed")]
    ClockRegression,
}

/// Result of appending one occurrence. Replaying exact bytes is intentionally idempotent.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TransitionOutcome {
    Applied(RetentionReport),
    Duplicate(RetentionReport),
}

/// Compatibility alias for callers that name a state-machine step a transition.
pub type Transition = TransitionOutcome;

/// A pure append-only transition kernel. It does not own or mutate any physical storage.
#[derive(Clone, Debug)]
pub struct Kernel {
    domains: BTreeMap<DomainId, ProtectionDomain>,
    items: BTreeMap<OccurrenceId, InventoryItem>,
    occurrences: BTreeMap<OccurrenceId, (String, Occurrence)>,
    tombstones: BTreeMap<crate::model::TombstoneId, Tombstone>,
    releases: BTreeMap<crate::model::ReleaseId, Release>,
    requests: BTreeMap<OccurrenceId, DeletionRequest>,
    receipts: BTreeMap<OccurrenceId, DeletionReceipt>,
    observed_bytes: BTreeMap<OccurrenceId, ByteFact>,
    verified_inventory: bool,
    last_recorded_at: u64,
}

impl Kernel {
    /// Creates a kernel from a complete inventory snapshot.
    ///
    /// # Errors
    ///
    /// Returns an error if domains or inventory items are duplicated, unknown, or bound to a
    /// different key than their protection domain.
    pub fn new(inventory: Inventory) -> Result<Self, KernelError> {
        Self::new_inner(inventory, false)
    }

    /// Creates a qualified kernel from a store-produced exact inventory witness.
    ///
    /// # Errors
    ///
    /// Returns an error if the witness digest does not match the inventory or its receipt digest
    /// is absent. Without this witness, [`Kernel::new`] intentionally reports unknown closure.
    #[cfg(test)]
    pub(crate) fn from_verified(
        inventory: Inventory,
        witness: &InventoryWitness,
    ) -> Result<Self, KernelError> {
        if witness.inventory_digest != inventory.exact_digest() || witness.receipt_digest.is_empty()
        {
            return Err(KernelError::InvalidInventory(
                "inventory witness mismatch".into(),
            ));
        }
        Self::new_inner(inventory, true)
    }

    fn new_inner(inventory: Inventory, verified_inventory: bool) -> Result<Self, KernelError> {
        let mut domains = BTreeMap::new();
        for domain in inventory.domains {
            if domains.insert(domain.domain_id.clone(), domain).is_some() {
                return Err(KernelError::InvalidInventory("duplicate domain".into()));
            }
        }
        let mut items = BTreeMap::new();
        let mut observed_bytes = BTreeMap::new();
        for item in inventory.items {
            let Some(domain) = domains.get(&item.domain_id) else {
                return Err(KernelError::UnknownDomain(item.domain_id));
            };
            if item.key_id != domain.key_id || item.content_digest.is_empty() {
                return Err(KernelError::InvalidInventory(
                    "item key or digest does not match its protection domain".into(),
                ));
            }
            if items.insert(item.item_id.clone(), item.clone()).is_some() {
                return Err(KernelError::InvalidInventory(
                    "duplicate inventory item".into(),
                ));
            }
            observed_bytes.insert(item.item_id.clone(), item.bytes);
        }
        for item in items.values() {
            for dependency in &item.depends_on {
                if !items.contains_key(dependency) && verified_inventory {
                    return Err(KernelError::InvalidInventory(
                        "verified inventory has an unknown dependency".into(),
                    ));
                }
            }
        }
        if has_dependency_cycle(&items) {
            return Err(KernelError::InvalidInventory(
                "inventory dependency cycle".into(),
            ));
        }
        Ok(Self {
            domains,
            items,
            occurrences: BTreeMap::new(),
            tombstones: BTreeMap::new(),
            releases: BTreeMap::new(),
            requests: BTreeMap::new(),
            receipts: BTreeMap::new(),
            observed_bytes,
            verified_inventory,
            last_recorded_at: 0,
        })
    }

    /// Appends one occurrence, validating all references before changing state.
    ///
    /// An exact retry returns [`TransitionOutcome::Duplicate`]. A changed payload with the same
    /// occurrence ID is an identity conflict. No method in this type performs a physical action.
    ///
    /// # Errors
    ///
    /// Returns an error if references, tombstone/release closure, request eligibility, or receipt
    /// phase validation fails.
    pub fn transition(
        &mut self,
        occurrence: &Occurrence,
    ) -> Result<TransitionOutcome, KernelError> {
        let id = occurrence.occurrence_id().clone();
        let digest = occurrence_digest(occurrence);
        if let Some((existing_digest, _)) = self.occurrences.get(&id) {
            if existing_digest == &digest {
                return Ok(TransitionOutcome::Duplicate(
                    self.report_for_occurrence(occurrence),
                ));
            }
            return Err(KernelError::IdentityConflict(id));
        }
        if occurrence_time(occurrence) < self.last_recorded_at {
            return Err(KernelError::ClockRegression);
        }
        self.check_secondary_identity(occurrence)?;
        self.validate(occurrence)?;
        self.apply(occurrence.clone());
        self.occurrences.insert(id, (digest, occurrence.clone()));
        self.last_recorded_at = occurrence_time(occurrence);
        Ok(TransitionOutcome::Applied(
            self.report_for_occurrence(occurrence),
        ))
    }

    /// Computes the current closure report for a domain and item set.
    #[must_use]
    #[allow(clippy::too_many_lines)]
    pub fn report(
        &self,
        domain_id: &DomainId,
        item_ids: &BTreeSet<OccurrenceId>,
    ) -> RetentionReport {
        let mut refusals = BTreeSet::new();
        let mut key_state = self
            .domains
            .get(domain_id)
            .map_or(KeyState::Unknown, |d| d.key_state);
        if !self.domains.contains_key(domain_id) {
            refusals.insert(Refusal::UnknownInventory);
        }
        if !self.verified_inventory {
            refusals.insert(Refusal::UnknownInventory);
        }
        for item_id in item_ids {
            let Some(item) = self.items.get(item_id) else {
                refusals.insert(Refusal::UnknownInventory);
                continue;
            };
            if &item.domain_id != domain_id {
                refusals.insert(Refusal::DomainMismatch);
                continue;
            }
            match self
                .observed_bytes
                .get(item_id)
                .copied()
                .unwrap_or(ByteFact::Unknown)
            {
                ByteFact::Unknown => {
                    if item.kind == InventoryKind::Replica {
                        refusals.insert(Refusal::PartialReplica);
                    } else {
                        refusals.insert(Refusal::UnknownInventory);
                    }
                }
                ByteFact::Present | ByteFact::Absent => {}
            }
            if self.has_live_reverse_reference(item_id, item_ids) {
                refusals.insert(Refusal::OutstandingReference);
            }
            for dependency in &item.depends_on {
                if item_ids.contains(dependency) {
                    continue;
                }
                match self.observed_bytes.get(dependency).copied() {
                    Some(ByteFact::Present | ByteFact::Unknown) => {
                        refusals.insert(Refusal::OutstandingDependency);
                    }
                    Some(ByteFact::Absent) => {}
                    None => {
                        refusals.insert(Refusal::UnknownInventory);
                    }
                }
            }
        }
        if self.find_tombstone(domain_id, item_ids).is_none() {
            refusals.insert(Refusal::MissingTombstone);
        }
        if self.find_release(domain_id, item_ids).is_none() {
            refusals.insert(Refusal::MissingRelease);
        }
        let request_id = self
            .requests
            .values()
            .find(|request| request.domain_id == *domain_id && request.item_ids == *item_ids)
            .map(|request| request.request_id.clone());
        let mut observed_phases = BTreeSet::new();
        for receipt in self
            .receipts
            .values()
            .filter(|receipt| receipt.domain_id == *domain_id && receipt.item_ids == *item_ids)
        {
            if receipt.phase != DeletionPhase::Requested {
                observed_phases.insert(receipt.phase);
            }
            if matches!(
                receipt.phase,
                DeletionPhase::KeyDestroyed | DeletionPhase::BytesDeletedAndKeyDestroyed
            ) {
                key_state = KeyState::Erased;
            }
        }
        if key_state == KeyState::Erased && observed_phases.is_empty() {
            refusals.insert(Refusal::KeyAlreadyErased);
        }
        let bytes_absent = !item_ids.is_empty()
            && item_ids
                .iter()
                .all(|item_id| self.observed_bytes.get(item_id) == Some(&ByteFact::Absent));
        let key_erased = key_state == KeyState::Erased;
        let completion = match (bytes_absent, key_erased) {
            (false, false) => CompletionState::Neither,
            (true, false) => CompletionState::BytesOnly,
            (false, true) => CompletionState::KeyOnly,
            (true, true) => CompletionState::BytesAndKey,
        };
        let status = if !refusals.is_empty() {
            RetentionStatus::Blocked
        } else if !observed_phases.is_empty() {
            RetentionStatus::Observed
        } else {
            RetentionStatus::Eligible
        };
        RetentionReport {
            status,
            domain_id: domain_id.clone(),
            item_ids: item_ids.clone(),
            refusals,
            key_state,
            coverage_effect: crate::model::CoverageEffect::Unchanged,
            request_id,
            observed_phases,
            completion,
        }
    }

    /// Returns all accepted occurrences in deterministic occurrence-ID order.
    pub fn occurrences(&self) -> impl Iterator<Item = &Occurrence> {
        self.occurrences.values().map(|(_, occurrence)| occurrence)
    }

    fn validate(&self, occurrence: &Occurrence) -> Result<(), KernelError> {
        match occurrence {
            Occurrence::Tombstone(value) => self.validate_tombstone(value),
            Occurrence::Release(value) => self.validate_release(value),
            Occurrence::DeletionRequest(value) => self.validate_request(value),
            Occurrence::DeletionReceipt(value) => self.validate_receipt(value),
        }
    }

    fn validate_tombstone(&self, value: &Tombstone) -> Result<(), KernelError> {
        self.validate_items(&value.domain_id, &value.item_ids)?;
        if value.item_ids.is_empty() {
            return Err(KernelError::ItemSetMismatch);
        }
        Ok(())
    }

    fn validate_release(&self, value: &Release) -> Result<(), KernelError> {
        self.validate_items(&value.domain_id, &value.scope.item_ids)?;
        let Some(tombstone) = self.tombstones.get(&value.tombstone_id) else {
            return Err(KernelError::MissingTombstone);
        };
        if tombstone.domain_id != value.domain_id
            || !tombstone.item_ids.is_superset(&value.scope.item_ids)
        {
            return Err(KernelError::MissingTombstone);
        }
        if value.scope.catalog_release_digest.is_empty()
            || value.scope.authorization_digest.is_empty()
        {
            return Err(KernelError::ItemSetMismatch);
        }
        Ok(())
    }

    fn validate_request(&self, value: &DeletionRequest) -> Result<(), KernelError> {
        self.validate_items(&value.domain_id, &value.item_ids)?;
        let Some(tombstone) = self.tombstones.get(&value.tombstone_id) else {
            return Err(KernelError::MissingTombstone);
        };
        if tombstone.domain_id != value.domain_id
            || !tombstone.item_ids.is_superset(&value.item_ids)
        {
            return Err(KernelError::MissingTombstone);
        }
        let Some(release) = self.releases.get(&value.release_id) else {
            return Err(KernelError::MissingRelease);
        };
        if release.domain_id != value.domain_id
            || !release.scope.item_ids.is_superset(&value.item_ids)
            || release.tombstone_id != value.tombstone_id
            || release.scope.authorization_digest != value.authorization_digest
        {
            return Err(KernelError::MissingRelease);
        }
        let report = self.report(&value.domain_id, &value.item_ids);
        if report.status != RetentionStatus::Eligible || report.key_state != KeyState::Present {
            return Err(KernelError::StaleReceipt);
        }
        if value.authorization_digest.is_empty() {
            return Err(KernelError::ItemSetMismatch);
        }
        Ok(())
    }

    fn validate_receipt(&self, value: &DeletionReceipt) -> Result<(), KernelError> {
        let Some(request) = self.requests.get(&value.request_id) else {
            return Err(KernelError::MissingRequest);
        };
        if request.domain_id != value.domain_id || request.item_ids != value.item_ids {
            return Err(KernelError::StaleReceipt);
        }
        if !value.evidence_digest.starts_with("sha256:") {
            return Err(KernelError::StaleReceipt);
        }
        for receipt in self
            .receipts
            .values()
            .filter(|receipt| receipt.request_id == value.request_id)
        {
            if receipt.phase == value.phase {
                return Err(KernelError::StaleReceipt);
            }
            let allowed_progression = matches!(
                (receipt.phase, value.phase),
                (DeletionPhase::Requested, _)
                    | (
                        DeletionPhase::BytesDeleted,
                        DeletionPhase::KeyDestroyed | DeletionPhase::BytesDeletedAndKeyDestroyed,
                    )
            );
            if !allowed_progression {
                return Err(KernelError::InvalidPhase);
            }
        }
        if matches!(
            value.phase,
            DeletionPhase::KeyDestroyed | DeletionPhase::BytesDeletedAndKeyDestroyed
        ) && self.domain_item_ids(&value.domain_id) != value.item_ids
        {
            return Err(KernelError::KeyScopeIncomplete);
        }
        if self
            .domains
            .get(&value.domain_id)
            .map(|domain| domain.key_state)
            == Some(KeyState::Erased)
        {
            return Err(KernelError::KeyAlreadyErased);
        }
        Ok(())
    }

    fn validate_items(
        &self,
        domain_id: &DomainId,
        item_ids: &BTreeSet<OccurrenceId>,
    ) -> Result<(), KernelError> {
        if !self.domains.contains_key(domain_id) {
            return Err(KernelError::UnknownDomain(domain_id.clone()));
        }
        for item_id in item_ids {
            let Some(item) = self.items.get(item_id) else {
                return Err(KernelError::UnknownItem(item_id.clone()));
            };
            if item.domain_id != *domain_id {
                return Err(KernelError::DomainMismatch);
            }
        }
        Ok(())
    }

    fn apply(&mut self, occurrence: Occurrence) {
        match occurrence {
            Occurrence::Tombstone(value) => {
                self.tombstones.insert(value.tombstone_id.clone(), value);
            }
            Occurrence::Release(value) => {
                self.releases.insert(value.release_id.clone(), value);
            }
            Occurrence::DeletionRequest(value) => {
                self.requests.insert(value.request_id.clone(), value);
            }
            Occurrence::DeletionReceipt(value) => {
                if matches!(
                    value.phase,
                    DeletionPhase::BytesDeleted | DeletionPhase::BytesDeletedAndKeyDestroyed
                ) {
                    for item_id in &value.item_ids {
                        self.observed_bytes
                            .insert(item_id.clone(), ByteFact::Absent);
                    }
                }
                if matches!(
                    value.phase,
                    DeletionPhase::KeyDestroyed | DeletionPhase::BytesDeletedAndKeyDestroyed
                ) && let Some(domain) = self.domains.get_mut(&value.domain_id)
                {
                    domain.key_state = KeyState::Erased;
                }
                self.receipts.insert(value.receipt_id.clone(), value);
            }
        }
    }

    fn report_for_occurrence(&self, occurrence: &Occurrence) -> RetentionReport {
        let (domain_id, item_ids) = match occurrence {
            Occurrence::Tombstone(value) => (&value.domain_id, &value.item_ids),
            Occurrence::Release(value) => (&value.domain_id, &value.scope.item_ids),
            Occurrence::DeletionRequest(value) => (&value.domain_id, &value.item_ids),
            Occurrence::DeletionReceipt(value) => (&value.domain_id, &value.item_ids),
        };
        self.report(domain_id, item_ids)
    }

    fn find_tombstone(
        &self,
        domain_id: &DomainId,
        item_ids: &BTreeSet<OccurrenceId>,
    ) -> Option<&Tombstone> {
        self.tombstones
            .values()
            .find(|value| value.domain_id == *domain_id && value.item_ids.is_superset(item_ids))
    }

    fn find_release(
        &self,
        domain_id: &DomainId,
        item_ids: &BTreeSet<OccurrenceId>,
    ) -> Option<&Release> {
        self.releases.values().find(|value| {
            value.domain_id == *domain_id && value.scope.item_ids.is_superset(item_ids)
        })
    }

    fn domain_item_ids(&self, domain_id: &DomainId) -> BTreeSet<OccurrenceId> {
        self.items
            .values()
            .filter(|item| item.domain_id == *domain_id)
            .map(|item| item.item_id.clone())
            .collect()
    }

    fn has_live_reverse_reference(
        &self,
        item_id: &OccurrenceId,
        selected: &BTreeSet<OccurrenceId>,
    ) -> bool {
        self.items.values().any(|item| {
            item.depends_on.contains(item_id)
                && !selected.contains(&item.item_id)
                && self.observed_bytes.get(&item.item_id) != Some(&ByteFact::Absent)
        })
    }

    fn check_secondary_identity(&self, occurrence: &Occurrence) -> Result<(), KernelError> {
        let conflict = match occurrence {
            Occurrence::Tombstone(value) => self
                .tombstones
                .get(&value.tombstone_id)
                .is_some_and(|old| old != value),
            Occurrence::Release(value) => self
                .releases
                .get(&value.release_id)
                .is_some_and(|old| old != value),
            Occurrence::DeletionRequest(value) => self
                .requests
                .get(&value.request_id)
                .is_some_and(|old| old != value),
            Occurrence::DeletionReceipt(value) => self
                .receipts
                .get(&value.receipt_id)
                .is_some_and(|old| old != value),
        };
        if conflict {
            Err(KernelError::IdentityConflict(
                occurrence.occurrence_id().clone(),
            ))
        } else {
            Ok(())
        }
    }
}

fn occurrence_time(occurrence: &Occurrence) -> u64 {
    match occurrence {
        Occurrence::Tombstone(value) => value.recorded_at,
        Occurrence::Release(value) => value.recorded_at,
        Occurrence::DeletionRequest(value) => value.requested_at,
        Occurrence::DeletionReceipt(value) => value.recorded_at,
    }
}

fn has_dependency_cycle(items: &BTreeMap<OccurrenceId, InventoryItem>) -> bool {
    fn visit(
        id: &OccurrenceId,
        items: &BTreeMap<OccurrenceId, InventoryItem>,
        visiting: &mut BTreeSet<OccurrenceId>,
        visited: &mut BTreeSet<OccurrenceId>,
    ) -> bool {
        if visiting.contains(id) {
            return true;
        }
        if !visited.insert(id.clone()) {
            return false;
        }
        visiting.insert(id.clone());
        let cycle = items.get(id).is_some_and(|item| {
            item.depends_on.iter().any(|dependency| {
                items.contains_key(dependency) && visit(dependency, items, visiting, visited)
            })
        });
        visiting.remove(id);
        cycle
    }

    let mut visiting = BTreeSet::new();
    let mut visited = BTreeSet::new();
    items
        .keys()
        .any(|id| visit(id, items, &mut visiting, &mut visited))
}
