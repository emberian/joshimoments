//! Exact mapping from the frozen G0 schedule to currently executable component fault adapters.
//!
//! This is coverage metadata, not a fault-run result. A mapped point has a concrete adapter and a
//! package test; an unmapped point remains blocked until a root runner executes and binds it.

use crate::{
    g0_inspector_smoke::G0InspectorSmokeFaultPoint, wave5_circulation::CirculationFaultPoint,
    wave5_g0::Wave5G0SourcePublicationFaultPoint,
    wave5_g0_root_evidence::G0FinalRecoveryFaultPoint,
};
use joshi_g0_harness::{CrashPoint, KillPoint};
use joshi_supervisor::FaultPoint;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum G0ExecutableFaultAdapter {
    Supervisor(FaultPoint),
    Catalog(CirculationFaultPoint),
    Component(Wave5G0SourcePublicationFaultPoint),
    Inspector(G0InspectorSmokeFaultPoint),
    FinalRecovery(G0FinalRecoveryFaultPoint),
}

#[must_use]
#[allow(clippy::too_many_lines)] // Keep the frozen one-to-one schedule mapping visibly exhaustive.
pub(crate) const fn fault_adapter(point: CrashPoint) -> G0ExecutableFaultAdapter {
    match point {
        CrashPoint::BeforePreIoReservation => {
            G0ExecutableFaultAdapter::Supervisor(FaultPoint::BeforeAttemptReservation)
        }
        CrashPoint::After(KillPoint::AfterPreIoReservation) => {
            G0ExecutableFaultAdapter::Supervisor(FaultPoint::AfterAttemptReservation)
        }
        CrashPoint::BeforeOriginFsync => {
            G0ExecutableFaultAdapter::Supervisor(FaultPoint::BeforeLocalSpoolAppend)
        }
        CrashPoint::After(KillPoint::AfterOriginFsync) => {
            G0ExecutableFaultAdapter::Supervisor(FaultPoint::AfterLocalSpoolAppend)
        }
        CrashPoint::BeforeStoreReceipt => {
            G0ExecutableFaultAdapter::Catalog(CirculationFaultPoint::BeforeStoreCommit)
        }
        CrashPoint::After(KillPoint::AfterStoreReceipt) => {
            G0ExecutableFaultAdapter::Catalog(CirculationFaultPoint::AfterStoreCommit)
        }
        CrashPoint::BeforeCatalogBinding => {
            G0ExecutableFaultAdapter::Catalog(CirculationFaultPoint::BeforeCatalogBinding)
        }
        CrashPoint::After(KillPoint::AfterCatalogBinding) => {
            G0ExecutableFaultAdapter::Catalog(CirculationFaultPoint::AfterCatalogBinding)
        }
        CrashPoint::BeforeCatalogAck => {
            G0ExecutableFaultAdapter::Catalog(CirculationFaultPoint::BeforeCatalogAck)
        }
        CrashPoint::After(KillPoint::AfterCatalogAck) => {
            G0ExecutableFaultAdapter::Catalog(CirculationFaultPoint::AfterCatalogAck)
        }
        CrashPoint::BeforeSemanticFact => G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforeSemanticFact,
        ),
        CrashPoint::After(KillPoint::AfterSemanticFact) => G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::AfterSemanticFact,
        ),
        CrashPoint::BeforePublicationPrepare => G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforePublicationPrepare,
        ),
        CrashPoint::After(KillPoint::AfterPublicationPrepare) => {
            G0ExecutableFaultAdapter::Component(
                Wave5G0SourcePublicationFaultPoint::AfterPublicationPrepare,
            )
        }
        CrashPoint::BeforePublicationHead => G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforePublicationHead,
        ),
        CrashPoint::After(KillPoint::AfterPublicationHead) => G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::AfterPublicationHead,
        ),
        CrashPoint::BeforePairingExchange => {
            G0ExecutableFaultAdapter::Inspector(G0InspectorSmokeFaultPoint::BeforePairingExchange)
        }
        CrashPoint::After(KillPoint::AfterPairingExchange) => {
            G0ExecutableFaultAdapter::Inspector(G0InspectorSmokeFaultPoint::AfterPairingExchange)
        }
        CrashPoint::BeforeGlassRead => {
            G0ExecutableFaultAdapter::Inspector(G0InspectorSmokeFaultPoint::BeforeGlassRead)
        }
        CrashPoint::After(KillPoint::AfterGlassRead) => {
            G0ExecutableFaultAdapter::Inspector(G0InspectorSmokeFaultPoint::AfterGlassRead)
        }
        CrashPoint::BeforeMemoryAct => {
            G0ExecutableFaultAdapter::Component(Wave5G0SourcePublicationFaultPoint::BeforeMemoryAct)
        }
        CrashPoint::After(KillPoint::AfterMemoryAct) => {
            G0ExecutableFaultAdapter::Component(Wave5G0SourcePublicationFaultPoint::AfterMemoryAct)
        }
        CrashPoint::BeforeMemoryEpisode => G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforeMemoryEpisode,
        ),
        CrashPoint::After(KillPoint::AfterMemoryEpisode) => G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::AfterMemoryEpisode,
        ),
        CrashPoint::BeforeExport => {
            G0ExecutableFaultAdapter::Component(Wave5G0SourcePublicationFaultPoint::BeforeV10Export)
        }
        CrashPoint::After(KillPoint::AfterExport) => {
            G0ExecutableFaultAdapter::Component(Wave5G0SourcePublicationFaultPoint::AfterV10Export)
        }
        CrashPoint::BeforeImport => G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforeImportReadback,
        ),
        CrashPoint::After(KillPoint::AfterImport) => G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::AfterImportReadback,
        ),
        CrashPoint::BeforeStatus => G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforeExportRecoveryReady,
        ),
        CrashPoint::After(KillPoint::AfterStatus) => G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::AfterExportRecoveryReady,
        ),
        CrashPoint::BeforeBackup => {
            G0ExecutableFaultAdapter::FinalRecovery(G0FinalRecoveryFaultPoint::BeforeBackup)
        }
        CrashPoint::After(KillPoint::AfterBackup) => {
            G0ExecutableFaultAdapter::FinalRecovery(G0FinalRecoveryFaultPoint::AfterBackup)
        }
        CrashPoint::BeforeRestore => {
            G0ExecutableFaultAdapter::FinalRecovery(G0FinalRecoveryFaultPoint::BeforeRestore)
        }
        CrashPoint::After(KillPoint::AfterRestore) => {
            G0ExecutableFaultAdapter::FinalRecovery(G0FinalRecoveryFaultPoint::AfterRestore)
        }
        CrashPoint::BeforeReopen => {
            G0ExecutableFaultAdapter::FinalRecovery(G0FinalRecoveryFaultPoint::BeforeReopen)
        }
        CrashPoint::After(KillPoint::AfterReopen) => {
            G0ExecutableFaultAdapter::FinalRecovery(G0FinalRecoveryFaultPoint::AfterReopen)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use joshi_g0_harness::FakeFaultSchedule;

    #[test]
    fn frozen_schedule_maps_every_transition_to_one_executable_adapter() {
        let schedule: FakeFaultSchedule = serde_json::from_slice(include_bytes!(
            "../../../fixtures/g0-fault/fake_fault_schedule.json"
        ))
        .expect("checked schedule fixture");
        schedule.validate().expect("valid schedule");
        assert_eq!(schedule.scenarios.len(), 37);

        let mut mapped = Vec::new();
        for scenario in schedule.scenarios.iter().skip(1) {
            let point = scenario.crash_point.expect("nonbaseline crash point");
            mapped.push((point, fault_adapter(point)));
        }
        assert_eq!(mapped.len(), 36);
        assert_eq!(
            fault_adapter(CrashPoint::BeforePreIoReservation),
            G0ExecutableFaultAdapter::Supervisor(FaultPoint::BeforeAttemptReservation)
        );
        assert_eq!(
            fault_adapter(CrashPoint::After(KillPoint::AfterPreIoReservation)),
            G0ExecutableFaultAdapter::Supervisor(FaultPoint::AfterAttemptReservation)
        );
        assert_eq!(
            fault_adapter(CrashPoint::BeforeOriginFsync),
            G0ExecutableFaultAdapter::Supervisor(FaultPoint::BeforeLocalSpoolAppend)
        );
        assert_eq!(
            fault_adapter(CrashPoint::After(KillPoint::AfterOriginFsync)),
            G0ExecutableFaultAdapter::Supervisor(FaultPoint::AfterLocalSpoolAppend)
        );
    }
}
