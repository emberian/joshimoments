use crate::Result;
use joshi_admission::wave5::{
    CollectorRuntimeConfigV1, ExecutionAccountingDocumentV1, Wave5RunReferenceV1,
    Wave5RunRegistrationBytes, Wave5RunRegistrationV1, parse_wave5_run_registration_v1,
    validate_wave5_run_component_documents,
};

pub use joshi_admission::wave5::{
    CollectorRuntimeConfigV1 as CanonicalCollectorRuntimeConfigV1,
    ExecutionAccountingDocumentV1 as CanonicalExecutionAccountingDocumentV1,
    LocalStatusEndpointV1 as LocalStatusEndpoint, ProviderExecutionModeV1 as ProviderExecutionMode,
};

/// Separate exact launch documents. None are credentials. C0 admits their exact local
/// registration; live promotion additionally requires a durable store receipt and remains
/// disabled. The complete six-child closure is required even for C0.
#[derive(Clone, Copy)]
pub struct RuntimeDocumentSet<'a> {
    pub exact_registration: &'a [u8],
    pub exact_build: &'a [u8],
    pub exact_source_tree: &'a [u8],
    pub exact_configuration: &'a [u8],
    pub exact_budget: &'a [u8],
    pub exact_privacy: &'a [u8],
    pub exact_daily_use_surface_profile: &'a [u8],
}

impl RuntimeDocumentSet<'_> {
    pub(crate) fn parse_and_close(
        &self,
    ) -> Result<(
        Wave5RunRegistrationV1,
        Wave5RunReferenceV1,
        CollectorRuntimeConfigV1,
        ExecutionAccountingDocumentV1,
    )> {
        let registration = parse_wave5_run_registration_v1(self.exact_registration)?;
        let documents = Wave5RunRegistrationBytes {
            build: self.exact_build,
            source_tree: self.exact_source_tree,
            configuration: self.exact_configuration,
            budget: self.exact_budget,
            privacy: self.exact_privacy,
            daily_use_surface_profile: self.exact_daily_use_surface_profile,
        };
        registration.validate_exact_documents(documents)?;
        let semantic = validate_wave5_run_component_documents(&registration, documents)?;
        let run = Wave5RunReferenceV1::from_registration(&registration, self.exact_registration)?;
        Ok((registration, run, semantic.configuration, semantic.budget))
    }
}
