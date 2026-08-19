//! Private runtime projection seam for the canonical source registry.
//!
//! `joshi-source-registry` owns source policy. This module is intentionally crate-private: a
//! caller cannot author an alternate registry or manually admit a provider. C0 resolves one
//! sealed local fixture contract here. C1 rederives one canonical credential-free public-Solana
//! declaration but remains validation-only; C2 has no admitted projection. Provider I/O remains
//! disabled until the root-owned runtime consumes a store-resolved registration and reservation.

use joshi_source_registry::{
    AbsenceSemantics, AccessClass, BillingUnit, Commitment, CredentialAuthority, FinalityPolicy,
    MethodKind, PUBLIC_SOLANA_MAINNET_SOURCE_ID, PUBLIC_SOLANA_SIGNATURES_METHOD_KEY,
    ProtectionClass, RetentionClass, SourceStatus, ZeroPriceAttestation,
    public_solana_mainnet_contract,
};
use thiserror::Error;

use crate::{
    SourceId,
    provider_plan::{
        PUBLIC_SOLANA_SIGNATURES_METHOD_SCHEMA_FINGERPRINT,
        PUBLIC_SOLANA_SOURCE_CONTRACT_FINGERPRINT, ProviderOperation,
        SEALED_C0_METHOD_SCHEMA_FINGERPRINT, SEALED_C0_SOURCE_CONTRACT_FINGERPRINT,
    },
};

pub(crate) const RUNTIME_CONTRACT_PORT_VERSION: &str = "joshi.runtime_source_contract_port.v2";
const SYNTHETIC_SOURCE_KEY: &str = "synthetic.local";
const SYNTHETIC_METHOD_KEY: &str = "emit";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RuntimeCredentialAuthority {
    None,
    ReadOnlyApi,
    WalletBearingSigning,
    TransactionExecution,
}

const ADMITTED_AUTHORITIES: [RuntimeCredentialAuthority; 2] = [
    RuntimeCredentialAuthority::None,
    RuntimeCredentialAuthority::ReadOnlyApi,
];
const FORBIDDEN_AUTHORITIES: [RuntimeCredentialAuthority; 2] = [
    RuntimeCredentialAuthority::WalletBearingSigning,
    RuntimeCredentialAuthority::TransactionExecution,
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct RuntimeMethodPort {
    pub(crate) method_key: String,
    pub(crate) operation: ProviderOperation,
    pub(crate) schema_fingerprint: String,
    pub(crate) max_request_bytes: u64,
    pub(crate) max_response_bytes: u64,
    pub(crate) max_attempts: u64,
    pub(crate) max_provider_credits_per_request: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct RuntimeSourceContractPort {
    pub(crate) port_version: &'static str,
    pub(crate) source_key: String,
    pub(crate) canonical_contract_fingerprint: String,
    pub(crate) source_id: SourceId,
    pub(crate) enabled: bool,
    pub(crate) kill_switch_enabled: bool,
    pub(crate) credential: RuntimeCredentialAuthority,
    pub(crate) coverage_family: String,
    pub(crate) protection_domain: String,
    pub(crate) method: RuntimeMethodPort,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct AdmittedRuntimeMethod {
    pub(crate) canonical_contract_fingerprint: String,
    pub(crate) source_id: SourceId,
    pub(crate) coverage_family: String,
    pub(crate) protection_domain: String,
    pub(crate) method: RuntimeMethodPort,
}

/// Resolve one built-in source declaration without accepting a caller-authored projection.
pub(crate) fn admit_runtime_method(
    source_key: &str,
    method_key: &str,
) -> Result<AdmittedRuntimeMethod, RuntimeContractError> {
    let contract = if source_key == SYNTHETIC_SOURCE_KEY && method_key == SYNTHETIC_METHOD_KEY {
        sealed_c0_contract()
    } else if source_key == PUBLIC_SOLANA_MAINNET_SOURCE_ID
        && method_key == PUBLIC_SOLANA_SIGNATURES_METHOD_KEY
    {
        public_solana_contract_port()?
    } else {
        return Err(RuntimeContractError::PendingCanonicalAdmission);
    };
    admit(&contract)
}

fn sealed_c0_contract() -> RuntimeSourceContractPort {
    RuntimeSourceContractPort {
        port_version: RUNTIME_CONTRACT_PORT_VERSION,
        source_key: SYNTHETIC_SOURCE_KEY.to_owned(),
        canonical_contract_fingerprint: SEALED_C0_SOURCE_CONTRACT_FINGERPRINT.to_owned(),
        source_id: SourceId::Other("synthetic_local".to_owned()),
        enabled: true,
        kill_switch_enabled: false,
        credential: RuntimeCredentialAuthority::None,
        coverage_family: "fixture_sequence".to_owned(),
        protection_domain: "local_fixture".to_owned(),
        method: RuntimeMethodPort {
            method_key: SYNTHETIC_METHOD_KEY.to_owned(),
            operation: ProviderOperation::SyntheticEmit,
            schema_fingerprint: SEALED_C0_METHOD_SCHEMA_FINGERPRINT.to_owned(),
            max_request_bytes: 1,
            max_response_bytes: 64 * 1_024 * 1_024,
            max_attempts: 1,
            max_provider_credits_per_request: 0,
        },
    }
}

fn public_solana_contract_port() -> Result<RuntimeSourceContractPort, RuntimeContractError> {
    let source =
        public_solana_mainnet_contract().map_err(|_| RuntimeContractError::InvalidProjection)?;
    let source_fingerprint = source
        .schema_fingerprint
        .as_ref()
        .ok_or(RuntimeContractError::InvalidProjection)?;
    let method = source
        .methods
        .iter()
        .find(|method| method.key.as_str() == PUBLIC_SOLANA_SIGNATURES_METHOD_KEY)
        .ok_or(RuntimeContractError::InvalidProjection)?;
    if source.source_id.as_str() != PUBLIC_SOLANA_MAINNET_SOURCE_ID
        || source.status != SourceStatus::Enabled
        || source.access != AccessClass::UnauthenticatedPublic
        || source.credential != CredentialAuthority::None
        || source.protection != ProtectionClass::Public
        || source.retention != RetentionClass::Public
        || source.kill_switch.enabled
        || source_fingerprint.as_str() != PUBLIC_SOLANA_SOURCE_CONTRACT_FINGERPRINT
        || method.kind != MethodKind::HttpPostReadOnly
        || method.commitment != Commitment::Finalized
        || method.finality != FinalityPolicy::RequireFinalized
        || method.absence != AbsenceSemantics::NeverProvesAbsence
        || method.billing.unit != BillingUnit::Request
        || method.billing.minor_units_per_unit != 0
        || method.billing.currency.is_some()
        || method.billing.asset_id.is_some()
        || method.billing.zero_price_attestation != ZeroPriceAttestation::DocumentedPublicSurface
        || method.schema_fingerprint.digest.as_str()
            != PUBLIC_SOLANA_SIGNATURES_METHOD_SCHEMA_FINGERPRINT
    {
        return Err(RuntimeContractError::InvalidProjection);
    }
    Ok(RuntimeSourceContractPort {
        port_version: RUNTIME_CONTRACT_PORT_VERSION,
        source_key: source.source_id.as_str().to_owned(),
        canonical_contract_fingerprint: source_fingerprint.as_str().to_owned(),
        source_id: SourceId::SolanaPublicHttp,
        enabled: true,
        kill_switch_enabled: false,
        credential: RuntimeCredentialAuthority::None,
        coverage_family: "wallet_signature_page".to_owned(),
        protection_domain: "public_chain_evidence".to_owned(),
        method: RuntimeMethodPort {
            method_key: method.key.as_str().to_owned(),
            operation: ProviderOperation::SolanaSignaturesForAddress,
            schema_fingerprint: method.schema_fingerprint.digest.as_str().to_owned(),
            max_request_bytes: method.max_request_bytes,
            max_response_bytes: method.max_response_bytes,
            max_attempts: u64::from(source.retry.max_attempts),
            max_provider_credits_per_request: 0,
        },
    })
}

fn admit(
    contract: &RuntimeSourceContractPort,
) -> Result<AdmittedRuntimeMethod, RuntimeContractError> {
    if contract.port_version != RUNTIME_CONTRACT_PORT_VERSION
        || contract.source_key.is_empty()
        || !valid_digest(&contract.canonical_contract_fingerprint)
        || contract.method.method_key.is_empty()
        || !valid_digest(&contract.method.schema_fingerprint)
        || contract.method.max_request_bytes == 0
        || contract.method.max_response_bytes == 0
        || contract.method.max_attempts == 0
        || contract.coverage_family.is_empty()
        || contract.protection_domain.is_empty()
    {
        return Err(RuntimeContractError::InvalidProjection);
    }
    if !contract.enabled {
        return Err(RuntimeContractError::SourceDisabled);
    }
    if contract.kill_switch_enabled {
        return Err(RuntimeContractError::KillSwitchEnabled);
    }
    if !ADMITTED_AUTHORITIES.contains(&contract.credential) {
        debug_assert!(FORBIDDEN_AUTHORITIES.contains(&contract.credential));
        return if contract.credential == RuntimeCredentialAuthority::WalletBearingSigning {
            Err(RuntimeContractError::WalletBearingCredential)
        } else {
            Err(RuntimeContractError::TransactionAuthority)
        };
    }
    Ok(AdmittedRuntimeMethod {
        canonical_contract_fingerprint: contract.canonical_contract_fingerprint.clone(),
        source_id: contract.source_id.clone(),
        coverage_family: contract.coverage_family.clone(),
        protection_domain: contract.protection_domain.clone(),
        method: contract.method.clone(),
    })
}

fn valid_digest(value: &str) -> bool {
    value.strip_prefix("sha256:").is_some_and(|hex| {
        hex.len() == 64
            && hex
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    })
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub(crate) enum RuntimeContractError {
    #[error("runtime source projection is invalid")]
    InvalidProjection,
    #[error("provider disabled pending canonical source-registry admission")]
    PendingCanonicalAdmission,
    #[error("source is disabled")]
    SourceDisabled,
    #[error("source kill switch is enabled")]
    KillSwitchEnabled,
    #[error("wallet-bearing credential is not admitted to the read-only collector")]
    WalletBearingCredential,
    #[error("transaction authority is not admitted to the read-only collector")]
    TransactionAuthority,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn c0_contract_is_sealed_and_uses_real_digest_shapes() {
        let admitted = admit_runtime_method("synthetic.local", "emit").unwrap();
        assert!(valid_digest(&admitted.canonical_contract_fingerprint));
        assert!(valid_digest(&admitted.method.schema_fingerprint));
    }

    #[test]
    fn an_unknown_projection_cannot_be_authored_through_the_port() {
        assert_eq!(
            admit_runtime_method("helius", "get_transaction"),
            Err(RuntimeContractError::PendingCanonicalAdmission)
        );
    }

    #[test]
    fn wallet_and_transaction_authority_are_fail_closed() {
        let mut contract = sealed_c0_contract();
        contract.credential = RuntimeCredentialAuthority::WalletBearingSigning;
        assert_eq!(
            admit(&contract),
            Err(RuntimeContractError::WalletBearingCredential)
        );
        contract.credential = RuntimeCredentialAuthority::TransactionExecution;
        assert_eq!(
            admit(&contract),
            Err(RuntimeContractError::TransactionAuthority)
        );
    }

    #[test]
    fn status_and_kill_switch_are_rechecked_at_admission() {
        let mut contract = sealed_c0_contract();
        contract.enabled = false;
        assert_eq!(admit(&contract), Err(RuntimeContractError::SourceDisabled));
        contract.enabled = true;
        contract.kill_switch_enabled = true;
        assert_eq!(
            admit(&contract),
            Err(RuntimeContractError::KillSwitchEnabled)
        );
    }

    #[test]
    fn uppercase_or_short_fingerprints_are_rejected() {
        assert!(!valid_digest("sha256:abc"));
        assert!(!valid_digest(
            "sha256:9225070E38E092E3C4CDD48744C36F61A32FEE85C1170D0EDCDBDC278428A6ED"
        ));
    }

    #[test]
    fn public_solana_projection_is_rederived_from_the_canonical_registry() {
        let admitted = admit_runtime_method(
            PUBLIC_SOLANA_MAINNET_SOURCE_ID,
            PUBLIC_SOLANA_SIGNATURES_METHOD_KEY,
        )
        .unwrap();
        assert_eq!(admitted.source_id, SourceId::SolanaPublicHttp);
        assert_eq!(
            admitted.canonical_contract_fingerprint,
            PUBLIC_SOLANA_SOURCE_CONTRACT_FINGERPRINT
        );
        assert_eq!(
            admitted.method.schema_fingerprint,
            PUBLIC_SOLANA_SIGNATURES_METHOD_SCHEMA_FINGERPRINT
        );
        assert_eq!(admitted.method.max_attempts, 3);
        assert_eq!(admitted.method.max_provider_credits_per_request, 0);
    }
}
