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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum G0ExecutableFaultAdapter {
    Catalog(CirculationFaultPoint),
    Component(Wave5G0SourcePublicationFaultPoint),
    Inspector(G0InspectorSmokeFaultPoint),
    FinalRecovery(G0FinalRecoveryFaultPoint),
}

#[must_use]
#[allow(clippy::too_many_lines)] // Keep the frozen one-to-one schedule mapping visibly exhaustive.
pub(crate) const fn fault_adapter(point: CrashPoint) -> Option<G0ExecutableFaultAdapter> {
    match point {
        CrashPoint::BeforeStoreReceipt => Some(G0ExecutableFaultAdapter::Catalog(
            CirculationFaultPoint::BeforeStoreCommit,
        )),
        CrashPoint::After(KillPoint::AfterStoreReceipt) => Some(G0ExecutableFaultAdapter::Catalog(
            CirculationFaultPoint::AfterStoreCommit,
        )),
        CrashPoint::BeforeCatalogBinding => Some(G0ExecutableFaultAdapter::Catalog(
            CirculationFaultPoint::BeforeCatalogBinding,
        )),
        CrashPoint::After(KillPoint::AfterCatalogBinding) => Some(
            G0ExecutableFaultAdapter::Catalog(CirculationFaultPoint::AfterCatalogBinding),
        ),
        CrashPoint::BeforeCatalogAck => Some(G0ExecutableFaultAdapter::Catalog(
            CirculationFaultPoint::BeforeCatalogAck,
        )),
        CrashPoint::After(KillPoint::AfterCatalogAck) => Some(G0ExecutableFaultAdapter::Catalog(
            CirculationFaultPoint::AfterCatalogAck,
        )),
        CrashPoint::BeforeSemanticFact => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforeSemanticFact,
        )),
        CrashPoint::After(KillPoint::AfterSemanticFact) => {
            Some(G0ExecutableFaultAdapter::Component(
                Wave5G0SourcePublicationFaultPoint::AfterSemanticFact,
            ))
        }
        CrashPoint::BeforePublicationPrepare => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforePublicationPrepare,
        )),
        CrashPoint::After(KillPoint::AfterPublicationPrepare) => {
            Some(G0ExecutableFaultAdapter::Component(
                Wave5G0SourcePublicationFaultPoint::AfterPublicationPrepare,
            ))
        }
        CrashPoint::BeforePublicationHead => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforePublicationHead,
        )),
        CrashPoint::After(KillPoint::AfterPublicationHead) => {
            Some(G0ExecutableFaultAdapter::Component(
                Wave5G0SourcePublicationFaultPoint::AfterPublicationHead,
            ))
        }
        CrashPoint::BeforePairingExchange => Some(G0ExecutableFaultAdapter::Inspector(
            G0InspectorSmokeFaultPoint::BeforePairingExchange,
        )),
        CrashPoint::After(KillPoint::AfterPairingExchange) => Some(
            G0ExecutableFaultAdapter::Inspector(G0InspectorSmokeFaultPoint::AfterPairingExchange),
        ),
        CrashPoint::BeforeGlassRead => Some(G0ExecutableFaultAdapter::Inspector(
            G0InspectorSmokeFaultPoint::BeforeGlassRead,
        )),
        CrashPoint::After(KillPoint::AfterGlassRead) => Some(G0ExecutableFaultAdapter::Inspector(
            G0InspectorSmokeFaultPoint::AfterGlassRead,
        )),
        CrashPoint::BeforeMemoryAct => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforeMemoryAct,
        )),
        CrashPoint::After(KillPoint::AfterMemoryAct) => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::AfterMemoryAct,
        )),
        CrashPoint::BeforeMemoryEpisode => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforeMemoryEpisode,
        )),
        CrashPoint::After(KillPoint::AfterMemoryEpisode) => {
            Some(G0ExecutableFaultAdapter::Component(
                Wave5G0SourcePublicationFaultPoint::AfterMemoryEpisode,
            ))
        }
        CrashPoint::BeforeExport => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforeV10Export,
        )),
        CrashPoint::After(KillPoint::AfterExport) => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::AfterV10Export,
        )),
        CrashPoint::BeforeImport => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforeImportReadback,
        )),
        CrashPoint::After(KillPoint::AfterImport) => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::AfterImportReadback,
        )),
        CrashPoint::BeforeStatus => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::BeforeExportRecoveryReady,
        )),
        CrashPoint::After(KillPoint::AfterStatus) => Some(G0ExecutableFaultAdapter::Component(
            Wave5G0SourcePublicationFaultPoint::AfterExportRecoveryReady,
        )),
        CrashPoint::BeforeBackup => Some(G0ExecutableFaultAdapter::FinalRecovery(
            G0FinalRecoveryFaultPoint::BeforeBackup,
        )),
        CrashPoint::After(KillPoint::AfterBackup) => Some(G0ExecutableFaultAdapter::FinalRecovery(
            G0FinalRecoveryFaultPoint::AfterBackup,
        )),
        CrashPoint::BeforeRestore => Some(G0ExecutableFaultAdapter::FinalRecovery(
            G0FinalRecoveryFaultPoint::BeforeRestore,
        )),
        CrashPoint::After(KillPoint::AfterRestore) => Some(
            G0ExecutableFaultAdapter::FinalRecovery(G0FinalRecoveryFaultPoint::AfterRestore),
        ),
        CrashPoint::BeforeReopen => Some(G0ExecutableFaultAdapter::FinalRecovery(
            G0FinalRecoveryFaultPoint::BeforeReopen,
        )),
        CrashPoint::After(KillPoint::AfterReopen) => Some(G0ExecutableFaultAdapter::FinalRecovery(
            G0FinalRecoveryFaultPoint::AfterReopen,
        )),
        CrashPoint::BeforePreIoReservation
        | CrashPoint::BeforeOriginFsync
        | CrashPoint::After(KillPoint::AfterPreIoReservation | KillPoint::AfterOriginFsync) => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use joshi_g0_harness::FakeFaultSchedule;

    #[test]
    fn frozen_schedule_has_exactly_thirty_two_mapped_and_four_blocked_faults() {
        let schedule: FakeFaultSchedule = serde_json::from_slice(include_bytes!(
            "../../../fixtures/g0-fault/fake_fault_schedule.json"
        ))
        .expect("checked schedule fixture");
        schedule.validate().expect("valid schedule");
        assert_eq!(schedule.scenarios.len(), 37);

        let mut mapped = Vec::new();
        let mut blocked = Vec::new();
        for scenario in schedule.scenarios.iter().skip(1) {
            let point = scenario.crash_point.expect("nonbaseline crash point");
            if fault_adapter(point).is_some() {
                mapped.push(point);
            } else {
                blocked.push(point);
            }
        }
        assert_eq!(mapped.len(), 32);
        assert_eq!(
            blocked,
            vec![
                CrashPoint::BeforePreIoReservation,
                CrashPoint::BeforeOriginFsync,
                CrashPoint::After(KillPoint::AfterPreIoReservation),
                CrashPoint::After(KillPoint::AfterOriginFsync),
            ]
        );
    }
}
