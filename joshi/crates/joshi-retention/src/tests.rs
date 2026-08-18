use super::*;
use std::collections::BTreeSet;

fn id(value: &str) -> OccurrenceId {
    OccurrenceId::new(value).expect("test id")
}
fn domain() -> DomainId {
    DomainId::new("private/social").expect("test domain")
}
fn set(values: &[&str]) -> BTreeSet<OccurrenceId> {
    values.iter().map(|value| id(value)).collect()
}

fn inventory(replica_bytes: ByteFact, with_derived: bool) -> Inventory {
    let domain = ProtectionDomain::new(domain(), "key-1").expect("domain");
    let origin = InventoryItem {
        item_id: id("origin"),
        kind: InventoryKind::OriginSpool,
        domain_id: domain.domain_id.clone(),
        content_digest: "sha256:origin".into(),
        bytes: ByteFact::Present,
        key_id: "key-1".into(),
        depends_on: BTreeSet::new(),
    };
    let cas = InventoryItem {
        item_id: id("cas"),
        kind: InventoryKind::Cas,
        domain_id: domain.domain_id.clone(),
        content_digest: "sha256:cas".into(),
        bytes: ByteFact::Present,
        key_id: "key-1".into(),
        depends_on: set(&["origin"]),
    };
    let replica = InventoryItem {
        item_id: id("replica"),
        kind: InventoryKind::Replica,
        domain_id: domain.domain_id.clone(),
        content_digest: "sha256:replica".into(),
        bytes: replica_bytes,
        key_id: "key-1".into(),
        depends_on: set(&["origin"]),
    };
    let mut items = vec![origin, cas, replica];
    if with_derived {
        items.push(InventoryItem {
            item_id: id("derived"),
            kind: InventoryKind::DerivedReference,
            domain_id: domain.domain_id.clone(),
            content_digest: "sha256:derived".into(),
            bytes: ByteFact::Present,
            key_id: "key-1".into(),
            depends_on: set(&["origin"]),
        });
    }
    Inventory {
        domains: vec![domain],
        items,
    }
}

fn kernel(replica_bytes: ByteFact, with_derived: bool) -> Kernel {
    let inventory = inventory(replica_bytes, with_derived);
    let witness = InventoryWitness {
        inventory_digest: inventory.exact_digest(),
        cutoff: 1,
        receipt_digest: "sha256:inventory-receipt".into(),
    };
    Kernel::from_verified(inventory, &witness).unwrap()
}

fn tombstone(items: &[&str]) -> Occurrence {
    Occurrence::Tombstone(Tombstone {
        occurrence_id: id("tombstone-occurrence"),
        tombstone_id: TombstoneId::new("tombstone").unwrap(),
        domain_id: domain(),
        item_ids: set(items),
        recorded_at: 1,
    })
}

fn release(items: &[&str]) -> Occurrence {
    Occurrence::Release(Release {
        occurrence_id: id("release-occurrence"),
        release_id: ReleaseId::new("release").unwrap(),
        domain_id: domain(),
        tombstone_id: TombstoneId::new("tombstone").unwrap(),
        scope: ReleaseScope {
            item_ids: set(items),
            catalog_release_digest: "sha256:catalog-release".into(),
            authorization_digest: "sha256:authorization".into(),
        },
        recorded_at: 2,
    })
}

fn request(items: &[&str]) -> Occurrence {
    Occurrence::DeletionRequest(DeletionRequest {
        occurrence_id: id("request-occurrence"),
        request_id: id("request"),
        domain_id: domain(),
        tombstone_id: TombstoneId::new("tombstone").unwrap(),
        release_id: ReleaseId::new("release").unwrap(),
        item_ids: set(items),
        authorization_digest: "sha256:authorization".into(),
        requested_at: 3,
    })
}

#[test]
fn partial_replica_blocks_without_inventing_coverage() {
    let mut kernel = kernel(ByteFact::Unknown, false);
    kernel
        .transition(&tombstone(&["origin", "cas", "replica"]))
        .unwrap();
    kernel
        .transition(&release(&["origin", "cas", "replica"]))
        .unwrap();
    let report = kernel.report(&domain(), &set(&["origin", "cas", "replica"]));
    assert_eq!(report.status, RetentionStatus::Blocked);
    assert!(report.refusals.contains(&Refusal::PartialReplica));
    assert_eq!(report.coverage_effect, CoverageEffect::Unchanged);
}

#[test]
fn export_or_derived_reference_blocks_origin_release() {
    let mut kernel = kernel(ByteFact::Present, true);
    kernel
        .transition(&tombstone(&["origin", "cas", "replica"]))
        .unwrap();
    kernel
        .transition(&release(&["origin", "cas", "replica"]))
        .unwrap();
    let report = kernel.report(&domain(), &set(&["origin"]));
    assert!(report.refusals.contains(&Refusal::OutstandingReference));
    assert!(kernel.transition(&request(&["origin"])).is_err());
}

#[test]
fn exact_retries_are_idempotent_and_changed_bytes_conflict() {
    let mut kernel = kernel(ByteFact::Present, false);
    let occurrence = tombstone(&["origin", "cas", "replica"]);
    assert!(matches!(
        kernel.transition(&occurrence),
        Ok(TransitionOutcome::Applied(_))
    ));
    assert!(matches!(
        kernel.transition(&occurrence),
        Ok(TransitionOutcome::Duplicate(_))
    ));
    let changed = Occurrence::Tombstone(Tombstone {
        recorded_at: 99,
        ..match tombstone(&["origin", "cas", "replica"]) {
            Occurrence::Tombstone(value) => value,
            _ => unreachable!(),
        }
    });
    assert!(matches!(
        kernel.transition(&changed),
        Err(KernelError::IdentityConflict(_))
    ));
}

#[test]
fn stale_receipt_and_incomplete_key_scope_are_refused() {
    let mut kernel = kernel(ByteFact::Present, false);
    kernel
        .transition(&tombstone(&["origin", "cas", "replica"]))
        .unwrap();
    kernel
        .transition(&release(&["origin", "cas", "replica"]))
        .unwrap();
    assert!(
        kernel
            .transition(&request(&["origin", "cas", "replica"]))
            .is_ok()
    );
    let receipt = Occurrence::DeletionReceipt(DeletionReceipt {
        occurrence_id: id("receipt-incomplete"),
        receipt_id: id("receipt-incomplete-id"),
        request_id: id("request"),
        domain_id: domain(),
        item_ids: set(&["origin"]),
        phase: DeletionPhase::KeyDestroyed,
        evidence_digest: "sha256:evidence".into(),
        recorded_at: 4,
    });
    assert_eq!(kernel.transition(&receipt), Err(KernelError::StaleReceipt));
    let stale = Occurrence::DeletionReceipt(DeletionReceipt {
        occurrence_id: id("stale-receipt"),
        receipt_id: id("stale-receipt-id"),
        request_id: id("unknown-request"),
        domain_id: domain(),
        item_ids: set(&["origin", "cas", "replica"]),
        phase: DeletionPhase::BytesDeleted,
        evidence_digest: "sha256:evidence".into(),
        recorded_at: 5,
    });
    assert_eq!(kernel.transition(&stale), Err(KernelError::MissingRequest));
}

#[test]
fn complete_receipt_observes_bytes_and_key_without_action_api() {
    let mut kernel = kernel(ByteFact::Present, false);
    kernel
        .transition(&tombstone(&["origin", "cas", "replica"]))
        .unwrap();
    kernel
        .transition(&release(&["origin", "cas", "replica"]))
        .unwrap();
    kernel
        .transition(&request(&["origin", "cas", "replica"]))
        .unwrap();
    let receipt = Occurrence::DeletionReceipt(DeletionReceipt {
        occurrence_id: id("receipt"),
        receipt_id: id("receipt-id"),
        request_id: id("request"),
        domain_id: domain(),
        item_ids: set(&["origin", "cas", "replica"]),
        phase: DeletionPhase::BytesDeletedAndKeyDestroyed,
        evidence_digest: "sha256:evidence".into(),
        recorded_at: 4,
    });
    let outcome = kernel.transition(&receipt).unwrap();
    let TransitionOutcome::Applied(report) = outcome else {
        panic!("first receipt must apply")
    };
    assert_eq!(report.key_state, KeyState::Erased);
    assert_eq!(report.coverage_effect, CoverageEffect::Unchanged);
}

#[test]
fn crash_between_byte_and_key_facts_is_resumable() {
    let mut kernel = kernel(ByteFact::Present, false);
    kernel
        .transition(&tombstone(&["origin", "cas", "replica"]))
        .unwrap();
    kernel
        .transition(&release(&["origin", "cas", "replica"]))
        .unwrap();
    kernel
        .transition(&request(&["origin", "cas", "replica"]))
        .unwrap();
    let bytes = Occurrence::DeletionReceipt(DeletionReceipt {
        occurrence_id: id("receipt-bytes"),
        receipt_id: id("receipt-bytes-id"),
        request_id: id("request"),
        domain_id: domain(),
        item_ids: set(&["origin", "cas", "replica"]),
        phase: DeletionPhase::BytesDeleted,
        evidence_digest: "sha256:bytes-evidence".into(),
        recorded_at: 4,
    });
    kernel.transition(&bytes).unwrap();
    let report = kernel.report(&domain(), &set(&["origin", "cas", "replica"]));
    assert_eq!(report.completion, CompletionState::BytesOnly);
    let key = Occurrence::DeletionReceipt(DeletionReceipt {
        occurrence_id: id("receipt-key"),
        receipt_id: id("receipt-key-id"),
        request_id: id("request"),
        domain_id: domain(),
        item_ids: set(&["origin", "cas", "replica"]),
        phase: DeletionPhase::KeyDestroyed,
        evidence_digest: "sha256:key-evidence".into(),
        recorded_at: 5,
    });
    kernel.transition(&key).unwrap();
    let report = kernel.report(&domain(), &set(&["origin", "cas", "replica"]));
    assert_eq!(report.completion, CompletionState::BytesAndKey);
}

#[test]
fn occurrence_parser_rejects_unknown_fields_and_noncanonical_bytes() {
    let occurrence = tombstone(&["origin", "cas", "replica"]);
    let bytes = serde_json::to_vec(&occurrence).unwrap();
    assert!(parse_occurrence_exact(&bytes).is_ok());
    let mut value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    value
        .as_object_mut()
        .unwrap()
        .insert("surprise".into(), serde_json::Value::Bool(true));
    let changed = serde_json::to_vec(&value).unwrap();
    assert!(parse_occurrence_exact(&changed).is_err());
}

#[test]
fn unverified_inventory_can_never_qualify_and_secondary_ids_are_immutable() {
    let inventory = inventory(ByteFact::Present, false);
    let mut unverified = Kernel::new(inventory).unwrap();
    unverified
        .transition(&tombstone(&["origin", "cas", "replica"]))
        .unwrap();
    let report = unverified.report(&domain(), &set(&["origin", "cas", "replica"]));
    assert!(report.refusals.contains(&Refusal::UnknownInventory));

    let mut verified = kernel(ByteFact::Present, false);
    verified
        .transition(&tombstone(&["origin", "cas", "replica"]))
        .unwrap();
    let changed_secondary = Occurrence::Tombstone(Tombstone {
        occurrence_id: id("other-occurrence"),
        tombstone_id: TombstoneId::new("tombstone").unwrap(),
        domain_id: domain(),
        item_ids: set(&["origin"]),
        recorded_at: 1,
    });
    assert!(matches!(
        verified.transition(&changed_secondary),
        Err(KernelError::IdentityConflict(_))
    ));
}

#[test]
fn occurrence_clock_cannot_regress() {
    let mut kernel = kernel(ByteFact::Present, false);
    kernel
        .transition(&tombstone(&["origin", "cas", "replica"]))
        .unwrap();
    let earlier = Occurrence::Release(Release {
        occurrence_id: id("earlier-release"),
        release_id: ReleaseId::new("earlier-release-id").unwrap(),
        domain_id: domain(),
        tombstone_id: TombstoneId::new("tombstone").unwrap(),
        scope: ReleaseScope {
            item_ids: set(&["origin", "cas", "replica"]),
            catalog_release_digest: "sha256:catalog".into(),
            authorization_digest: "sha256:authorization".into(),
        },
        recorded_at: 0,
    });
    assert_eq!(
        kernel.transition(&earlier),
        Err(KernelError::ClockRegression)
    );
}
