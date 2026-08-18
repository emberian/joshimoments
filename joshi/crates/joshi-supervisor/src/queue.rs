use crate::{PendingSegment, QueueClass, QueueLimits};
use std::collections::VecDeque;

pub(crate) struct BoundedQueue {
    limits: QueueLimits,
    records: usize,
    bytes: u64,
    items: VecDeque<PendingSegment>,
}

impl BoundedQueue {
    pub(crate) fn new(limits: QueueLimits) -> Self {
        Self {
            limits,
            records: 0,
            bytes: 0,
            items: VecDeque::new(),
        }
    }

    // Returning the owned record unchanged is part of the saturation contract; boxing it merely
    // to shrink an internal error would add an allocation on the hottest bounded path.
    #[allow(clippy::result_large_err)]
    pub(crate) fn try_push(
        &mut self,
        item: PendingSegment,
    ) -> std::result::Result<(), PendingSegment> {
        let (record_limit, byte_limit) = match item.class {
            QueueClass::Evidence => (self.limits.evidence_records(), self.limits.evidence_bytes()),
            QueueClass::Control => (self.limits.maximum_records, self.limits.maximum_bytes),
        };
        let after_records = self.records.saturating_add(1);
        let Some(after_bytes) = self.bytes.checked_add(item.exact_entry_bytes) else {
            return Err(item);
        };
        if after_records > record_limit || after_bytes > byte_limit {
            return Err(item);
        }
        self.records = after_records;
        self.bytes = after_bytes;
        self.items.push_back(item);
        Ok(())
    }

    pub(crate) fn front(&self) -> Option<&PendingSegment> {
        self.items.front()
    }

    pub(crate) fn pop_front(&mut self) -> Option<PendingSegment> {
        let item = self.items.pop_front()?;
        self.records = self.records.saturating_sub(1);
        self.bytes = self.bytes.saturating_sub(item.exact_entry_bytes);
        Some(item)
    }

    pub(crate) const fn records(&self) -> usize {
        self.records
    }

    pub(crate) const fn bytes(&self) -> u64 {
        self.bytes
    }

    pub(crate) const fn limits(&self) -> QueueLimits {
        self.limits
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        AttemptKind, AttemptReservation, GenerationId, OperationKey, ProtectionProfile,
        ReservationId, SourceKey,
    };
    use joshi_domain::{OpenVariant, SourceId, UtcTimestamp};
    use joshi_evidence::{Boundary, CoverageScope};
    use joshi_spool::{GapRecord, ProtectionDomainId, SpoolEntry};

    fn item(id: &str, class: QueueClass, padding: usize) -> PendingSegment {
        let at: UtcTimestamp = "2026-08-17T12:00:00.000000Z".parse().unwrap();
        let scope = CoverageScope {
            source_id: SourceId::new("fixture.source").unwrap(),
            family: OpenVariant::known("fixture").unwrap(),
            subject: None,
        };
        let reservation = AttemptReservation {
            contract: crate::SUPERVISOR_CONTRACT_VERSION.into(),
            reservation_id: ReservationId::new(id).unwrap(),
            installation_id: "inst-00000000000000000000000000000000".into(),
            source_key: SourceKey::new("fixture").unwrap(),
            operation_key: OperationKey::new("poll").unwrap(),
            generation: GenerationId::new(1),
            attempt_ordinal: 1,
            kind: AttemptKind::Poll,
            scope: scope.clone(),
            lower: Boundary::Wall { value: at },
            protection: ProtectionProfile::PublicIntegrity {
                domain: ProtectionDomainId::new("public-fixture").unwrap(),
            },
            run: None,
            execution_claim: None,
            provider_plan: None,
            reserved_at: at,
            authority: crate::AUTHORITY_CEILING.into(),
        };
        let entry = SpoolEntry::Gap(GapRecord {
            gap_id: format!("gap-{id}-{}", "x".repeat(padding)),
            scope,
            lower: Boundary::Wall { value: at },
            upper: None,
            reason: OpenVariant::known("fixture").unwrap(),
            detected_at: at,
            related_segment_id: None,
        });
        PendingSegment::new(reservation, entry, class).unwrap()
    }

    #[test]
    fn control_reserve_remains_after_evidence_capacity_is_full() {
        let limits = QueueLimits {
            maximum_records: 3,
            maximum_bytes: 10_000,
            control_reserve_records: 1,
            control_reserve_bytes: 1_000,
        };
        let mut queue = BoundedQueue::new(limits);
        // Use control-shaped entries but reclassifying them as evidence is intentionally refused by
        // PendingSegment, so this test changes the class after construction to isolate queue math.
        let mut first = item("first", QueueClass::Control, 0);
        first.class = QueueClass::Evidence;
        let mut second = item("second", QueueClass::Control, 0);
        second.class = QueueClass::Evidence;
        let mut third = item("third", QueueClass::Control, 0);
        third.class = QueueClass::Evidence;
        assert!(queue.try_push(first).is_ok());
        assert!(queue.try_push(second).is_ok());
        assert!(queue.try_push(third).is_err());
        assert!(queue.try_push(item("gap", QueueClass::Control, 0)).is_ok());
    }

    #[test]
    fn a_single_oversized_item_is_returned_unchanged() {
        let mut queue = BoundedQueue::new(QueueLimits {
            maximum_records: 3,
            maximum_bytes: 512,
            control_reserve_records: 1,
            control_reserve_bytes: 128,
        });
        let oversized = item("oversized", QueueClass::Control, 1_000);
        let expected = oversized.reservation.reservation_id.clone();
        let returned = queue.try_push(oversized).unwrap_err();
        assert_eq!(returned.reservation.reservation_id, expected);
        assert_eq!(queue.records(), 0);
    }
}
