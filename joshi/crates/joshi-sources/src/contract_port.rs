//! Private runtime projection seam for the canonical source registry.
//!
//! `joshi-source-registry` owns source policy. This module is intentionally crate-private: a
//! caller cannot author an alternate registry or manually admit a provider. C0 resolves one
//! sealed local fixture contract here. C1/C2 remain disabled until a root-owned integration can
//! project a store-resolved canonical contract and receipt into this seam.

use thiserror::Error;

use crate::{SourceId, provider_plan::ProviderOperation};

pub(crate) const RUNTIME_CONTRACT_PORT_VERSION: &str = "joshi.runtime_source_contract_port.v1";
const SYNTHETIC_SOURCE_KEY: &str = "synthetic.local";
const SYNTHETIC_METHOD_KEY: &str = "emit";
const SYNTHETIC_SOURCE_FINGERPRINT: &str =
    "sha256:9225070e38e092e3c4cdd48744c36f61a32fee85c1170d0edcdbdc278428a6ed";
const SYNTHETIC_METHOD_FINGERPRINT: &str =
    "sha256:b9620e8e7e33a4886382709f8e1bb6a744c65b111d68efce284d900e7b48fdb5";

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
    pub(crate) method_key: &'static str,
    pub(crate) operation: ProviderOperation,
    pub(crate) schema_fingerprint: &'static str,
    pub(crate) max_request_bytes: u64,
    pub(crate) max_response_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct RuntimeSourceContractPort {
    pub(crate) port_version: &'static str,
    pub(crate) source_key: &'static str,
    pub(crate) canonical_contract_fingerprint: &'static str,
    pub(crate) source_id: SourceId,
    pub(crate) enabled: bool,
    pub(crate) kill_switch_enabled: bool,
    pub(crate) credential: RuntimeCredentialAuthority,
    pub(crate) coverage_family: &'static str,
    pub(crate) protection_domain: &'static str,
    pub(crate) method: RuntimeMethodPort,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct AdmittedRuntimeMethod {
    pub(crate) canonical_contract_fingerprint: &'static str,
    pub(crate) source_id: SourceId,
    pub(crate) coverage_family: &'static str,
    pub(crate) protection_domain: &'static str,
    pub(crate) method: RuntimeMethodPort,
}

/// Resolve the only provider contract this crate can currently admit by itself.
pub(crate) fn admit_sealed_c0(
    source_key: &str,
    method_key: &str,
) -> Result<AdmittedRuntimeMethod, RuntimeContractError> {
    let contract = sealed_c0_contract();
    if source_key != contract.source_key || method_key != contract.method.method_key {
        return Err(RuntimeContractError::PendingCanonicalAdmission);
    }
    admit(&contract)
}

fn sealed_c0_contract() -> RuntimeSourceContractPort {
    RuntimeSourceContractPort {
        port_version: RUNTIME_CONTRACT_PORT_VERSION,
        source_key: SYNTHETIC_SOURCE_KEY,
        canonical_contract_fingerprint: SYNTHETIC_SOURCE_FINGERPRINT,
        source_id: SourceId::Other("synthetic_local".to_owned()),
        enabled: true,
        kill_switch_enabled: false,
        credential: RuntimeCredentialAuthority::None,
        coverage_family: "fixture_sequence",
        protection_domain: "local_fixture",
        method: RuntimeMethodPort {
            method_key: SYNTHETIC_METHOD_KEY,
            operation: ProviderOperation::SyntheticEmit,
            schema_fingerprint: SYNTHETIC_METHOD_FINGERPRINT,
            max_request_bytes: 1,
            max_response_bytes: 64 * 1_024 * 1_024,
        },
    }
}

fn admit(
    contract: &RuntimeSourceContractPort,
) -> Result<AdmittedRuntimeMethod, RuntimeContractError> {
    if contract.port_version != RUNTIME_CONTRACT_PORT_VERSION
        || !valid_digest(contract.canonical_contract_fingerprint)
        || !valid_digest(contract.method.schema_fingerprint)
        || contract.method.max_request_bytes == 0
        || contract.method.max_response_bytes == 0
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
        canonical_contract_fingerprint: contract.canonical_contract_fingerprint,
        source_id: contract.source_id.clone(),
        coverage_family: contract.coverage_family,
        protection_domain: contract.protection_domain,
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
        let admitted = admit_sealed_c0("synthetic.local", "emit").unwrap();
        assert!(valid_digest(admitted.canonical_contract_fingerprint));
        assert!(valid_digest(admitted.method.schema_fingerprint));
    }

    #[test]
    fn an_unknown_projection_cannot_be_authored_through_the_port() {
        assert_eq!(
            admit_sealed_c0("helius", "get_transaction"),
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
}
