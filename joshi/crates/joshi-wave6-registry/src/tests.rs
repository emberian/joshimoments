use joshi_domain::{StableString, ValueDigest, WireU64};

use crate::{
    RegistryError, SemanticCeilingV1, Wave6ProgramRegistrationV1, canonical_bytes, digest_bytes,
    parse_program_registration_exact,
};

const FIXTURE: &[u8] = include_bytes!("../../../fixtures/wave6/program_registration_v1.json");

fn fixture() -> Wave6ProgramRegistrationV1 {
    serde_json::from_slice(FIXTURE).expect("checked-in registration fixture")
}

fn reclose(value: &mut Wave6ProgramRegistrationV1) {
    value.registration_digest =
        digest_bytes(&canonical_bytes(&value.digest_material()).expect("material bytes"))
            .expect("material digest");
}

#[test]
fn exact_fixture_roundtrips_at_unverified_ceiling() {
    let parsed = parse_program_registration_exact(FIXTURE).expect("valid exact fixture");
    assert_eq!(parsed.exact_bytes(), FIXTURE);
    assert_eq!(
        parsed.semantic_ceiling(),
        SemanticCeilingV1::UnverifiedSemanticFixtureOnly
    );
    assert_eq!(parsed.value().consumed_wave5_gates.len(), 0);
    assert_eq!(parsed.value().artifact_kinds.len(), 2);
    assert_eq!(parsed.value().budgets.provider_units, WireU64::new(0));
}

#[test]
fn unknown_and_noncanonical_json_refuse() {
    let mut document: serde_json::Value = serde_json::from_slice(FIXTURE).expect("json");
    document["durableReceipt"] = serde_json::json!({"commitSeq": "99"});
    let mut unknown = serde_json::to_vec(&document).expect("encode");
    unknown.push(b'\n');
    assert!(matches!(
        parse_program_registration_exact(&unknown),
        Err(RegistryError::Json(_))
    ));

    let pretty = serde_json::to_vec_pretty(&fixture()).expect("pretty");
    assert!(matches!(
        parse_program_registration_exact(&pretty),
        Err(RegistryError::NonCanonical)
    ));
}

#[test]
fn digest_and_collection_substitution_refuse() {
    let mut changed = fixture();
    changed.program_family_id = StableString::new("substituted-family").expect("stable");
    let bytes = canonical_bytes(&changed).expect("bytes");
    assert!(matches!(
        parse_program_registration_exact(&bytes),
        Err(RegistryError::DigestMismatch)
    ));

    let mut reordered = fixture();
    reordered.artifact_kinds.reverse();
    reclose(&mut reordered);
    let bytes = canonical_bytes(&reordered).expect("bytes");
    assert!(matches!(
        parse_program_registration_exact(&bytes),
        Err(RegistryError::Collection("artifactKinds"))
    ));
}

#[test]
fn provider_budget_and_missing_prohibition_refuse_even_when_reclosed() {
    let mut provider = fixture();
    provider.budgets.provider_units = WireU64::new(1);
    reclose(&mut provider);
    let bytes = canonical_bytes(&provider).expect("bytes");
    assert!(matches!(
        parse_program_registration_exact(&bytes),
        Err(RegistryError::Policy("budget"))
    ));

    let mut widened = fixture();
    widened
        .prohibited_side_effects
        .retain(|value| value.as_str() != "asset_reservation");
    reclose(&mut widened);
    let bytes = canonical_bytes(&widened).expect("bytes");
    assert!(matches!(
        parse_program_registration_exact(&bytes),
        Err(RegistryError::MissingProhibition("asset_reservation"))
    ));
}

#[test]
fn digest_wire_form_is_strict_lowercase_sha256() {
    let mut malformed = fixture();
    malformed.source_tree_digest =
        ValueDigest::new(format!("sha256:{}", "A".repeat(64))).expect("stable malformed digest");
    reclose(&mut malformed);
    let bytes = canonical_bytes(&malformed).expect("bytes");
    assert!(matches!(
        parse_program_registration_exact(&bytes),
        Err(RegistryError::DigestFormat {
            field: "sourceTreeDigest"
        })
    ));
}
