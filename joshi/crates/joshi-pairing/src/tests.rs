use super::*;

const OCCURRENCE_FIXTURE: &str = include_str!("../../../fixtures/pairing/ordinary_pairing_v1.json");
const SESSION_FIXTURE: &str = include_str!("../../../fixtures/pairing/session_descriptor_v1.json");

#[derive(Clone)]
struct RepeatEntropy;

impl Entropy for RepeatEntropy {
    fn fill(&mut self, bytes: &mut [u8]) -> Result<(), PairingError> {
        bytes.fill(7);
        Ok(())
    }
}

fn origin(value: &str) -> PairingOrigin {
    PairingOrigin::new(value).unwrap()
}

#[test]
fn issue_consume_authorize_is_one_time_and_redacted() {
    let service_origin = origin("http://127.0.0.1:8787");
    let mut registry = PairingRegistry::new(
        service_origin.clone(),
        1,
        PairingConfig::default(),
        TestEntropy::new(1),
    )
    .unwrap();
    let issued = registry
        .issue(100, vec![PairingScope::CockpitRead])
        .unwrap();
    assert_eq!(issued.code.as_str().len(), 64);
    assert!(!format!("{issued:?}").contains(issued.code.as_str()));
    let exchanged = registry
        .consume(&issued.code, &service_origin, 101)
        .unwrap();
    assert_ne!(issued.code.as_str(), exchanged.capability.as_str());
    assert_eq!(
        registry
            .authorize(
                &exchanged.capability,
                &service_origin,
                PairingScope::CockpitRead,
                102
            )
            .unwrap()
            .session_id,
        exchanged.descriptor.session_id
    );
    assert!(
        registry
            .consume(&issued.code, &service_origin, 103)
            .is_err()
    );
}

#[test]
fn wrong_origin_does_not_consume_and_wrong_codes_are_bounded() {
    let service_origin = origin("http://localhost:8787");
    let wrong_origin = origin("http://127.0.0.1:8787");
    let config = PairingConfig {
        max_failed_attempts: 2,
        ..PairingConfig::default()
    };
    let mut registry =
        PairingRegistry::new(service_origin.clone(), 1, config, TestEntropy::new(4)).unwrap();
    let issued = registry.issue(0, vec![PairingScope::ReplayRead]).unwrap();
    assert!(matches!(
        registry.consume(&issued.code, &wrong_origin, 1),
        Err(PairingError::OriginMismatch)
    ));
    let wrong = SecretCode::from_hex(&"f".repeat(64)).unwrap();
    assert!(matches!(
        registry.consume(&wrong, &service_origin, 2),
        Err(PairingError::InvalidCode)
    ));
    assert!(matches!(
        registry.consume(&wrong, &service_origin, 3),
        Err(PairingError::RateLimited)
    ));
    assert!(registry.consume(&issued.code, &service_origin, 4).is_err());
}

#[test]
fn expiry_revoke_and_restart_invalidate_without_secret_metadata() {
    let service_origin = origin("https://localhost:9443");
    let config = PairingConfig {
        code_ttl_ms: 5,
        session_ttl_ms: 5,
        ..PairingConfig::default()
    };
    let mut registry =
        PairingRegistry::new(service_origin.clone(), 7, config, TestEntropy::new(9)).unwrap();
    let _issued = registry.issue(10, vec![PairingScope::CockpitRead]).unwrap();
    let expired = registry.expire(15).unwrap();
    assert_eq!(expired.len(), 1);
    assert!(format!("{expired:?}").contains("pair-issue-7-1"));
    let next = registry.issue(20, vec![PairingScope::CockpitRead]).unwrap();
    let exchanged = registry.consume(&next.code, &service_origin, 21).unwrap();
    let revoked = registry
        .revoke(
            exchanged.descriptor.session_id.as_str(),
            22,
            "operator_requested",
        )
        .unwrap();
    assert_eq!(revoked.kind, PairingOccurrenceKind::Revoked);
    let again = registry.issue(30, vec![PairingScope::CockpitRead]).unwrap();
    let _ = registry.consume(&again.code, &service_origin, 31).unwrap();
    let occurrences = registry.restart(8, 32).unwrap();
    assert!(
        occurrences
            .iter()
            .all(|occurrence| occurrence.kind == PairingOccurrenceKind::RestartInvalidated)
    );
    assert!(
        registry
            .authorize(
                &SecretCapability::from_bytes(vec![0; 64]),
                &service_origin,
                PairingScope::CockpitRead,
                33
            )
            .is_err()
    );
}

#[test]
fn origin_and_secret_forms_are_strict() {
    assert!(PairingOrigin::new("http://localhost:8787/path").is_err());
    assert!(PairingOrigin::new("http://user@localhost:8787").is_err());
    assert!(SecretCode::from_hex(&"A".repeat(64)).is_err());
    assert!(constant_time_equal(b"abc", b"abc"));
    assert!(!constant_time_equal(b"abc", b"abd"));
}

#[test]
fn deterministic_metadata_fixture_is_strict_and_secret_free() {
    let occurrence = parse_pairing_occurrence(OCCURRENCE_FIXTURE.trim_end().as_bytes()).unwrap();
    occurrence.validate().unwrap();
    assert!(!OCCURRENCE_FIXTURE.contains("capability"));
    assert!(!OCCURRENCE_FIXTURE.contains("secret"));
    let session = parse_pairing_session_descriptor(SESSION_FIXTURE.trim_end().as_bytes()).unwrap();
    assert_eq!(
        session.canonical_bytes().unwrap(),
        SESSION_FIXTURE.trim_end().as_bytes()
    );
}

#[test]
fn clock_rollback_is_refused_at_the_public_adapter_boundary() {
    struct RollbackClock {
        values: std::vec::IntoIter<u64>,
    }

    impl MonotonicClock for RollbackClock {
        fn now_ms(&mut self) -> Result<u64, PairingError> {
            self.values.next().ok_or(PairingError::Entropy)
        }
    }

    let mut registry = PairingRegistry::new(
        origin("https://localhost:9443"),
        1,
        PairingConfig::default(),
        TestEntropy::new(42),
    )
    .unwrap();
    let mut clock = RollbackClock {
        values: vec![100, 99].into_iter(),
    };
    registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    assert!(matches!(
        registry.issue_now(&mut clock, vec![PairingScope::CockpitRead]),
        Err(PairingError::ClockRollback)
    ));
}

#[test]
fn monotonic_clock_adapter_and_duplicate_secret_are_bounded() {
    let service_origin = origin("http://localhost:8787");
    let mut clock = TestClock::new(100);
    let mut registry = PairingRegistry::new(
        service_origin,
        1,
        PairingConfig::default(),
        TestEntropy::new(1),
    )
    .unwrap();
    let issued = registry
        .issue_now(&mut clock, vec![PairingScope::CockpitRead])
        .unwrap();
    assert_eq!(issued.metadata.at_ms, 100);
    let mut duplicate_registry = PairingRegistry::new(
        origin("http://localhost:8787"),
        1,
        PairingConfig::default(),
        RepeatEntropy,
    )
    .unwrap();
    let _ = duplicate_registry
        .issue(0, vec![PairingScope::CockpitRead])
        .unwrap();
    assert!(matches!(
        duplicate_registry.issue(1, vec![PairingScope::CockpitRead]),
        Err(PairingError::DuplicateSecret)
    ));
}

#[test]
fn capacity_rejection_does_not_consume_code_and_occurrences_are_unique() {
    let service_origin = origin("http://localhost:8787");
    let config = PairingConfig {
        max_live_sessions: 1,
        ..PairingConfig::default()
    };
    let mut registry =
        PairingRegistry::new(service_origin.clone(), 1, config, TestEntropy::new(20)).unwrap();
    let first = registry.issue(1, vec![PairingScope::CockpitRead]).unwrap();
    let first_session = registry.consume(&first.code, &service_origin, 2).unwrap();
    let second = registry.issue(3, vec![PairingScope::CockpitRead]).unwrap();
    assert!(matches!(
        registry.consume(&second.code, &service_origin, 4),
        Err(PairingError::RateLimited)
    ));
    registry
        .revoke(first_session.descriptor.session_id.as_str(), 5, "done")
        .unwrap();
    let exchanged = registry.consume(&second.code, &service_origin, 6).unwrap();
    assert_ne!(
        first.metadata.occurrence_id,
        exchanged.occurrence.occurrence_id
    );
}
