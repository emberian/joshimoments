"""Construction and append-only review functions for research-desk contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..canonical import canonical_json_bytes, qualified_sha256_bytes
from ..errors import CoverageError, ManifestError, TemporalLeakageError
from .contracts import (
    AUTHORITY,
    ArtifactDescriptor,
    ArtifactRole,
    DeskPolicy,
    DispositionKind,
    HumanDisposition,
    ProposalRevision,
    ProposalSpec,
    ResearchProposal,
    _id,
    evidence_closure_digest,
)


def _admit(
    policy: DeskPolicy, descriptors: tuple[ArtifactDescriptor, ...], locked_at: datetime
) -> None:
    policy.validate()
    if not descriptors or len(descriptors) > policy.max_artifacts:
        raise ManifestError("proposal artifact count is outside the declared cap")
    if tuple(item.artifact_id for item in descriptors) != tuple(
        sorted({item.artifact_id for item in descriptors})
    ):
        raise ManifestError("artifact descriptors must be sorted and duplicate-free")
    for item in descriptors:
        item.validate()
        if item.available_at > policy.information_cutoff or item.commit_seq <= 0:
            raise TemporalLeakageError("descriptor exceeds the policy information cutoff")
        if item.available_at > locked_at:
            raise TemporalLeakageError("hypothesis used information unavailable when it was locked")
        if (
            item.coverage_status.value != "complete"
            or item.coverage_ppm < policy.minimum_coverage_ppm
        ):
            raise CoverageError("descriptor does not meet complete coverage cutoff")
        if not set(item.gap_ids).issubset(policy.allowed_gap_ids):
            raise CoverageError("descriptor has a gap outside the policy allowance")
        if item.unit != policy.required_unit:
            raise ManifestError("descriptor unit does not meet policy cutoff")
        if (
            item.topology_id != policy.required_topology_id
            or item.topology_version_id != policy.required_topology_version_id
        ):
            raise ManifestError("descriptor topology does not meet policy cutoff")
        if item.role is ArtifactRole.OUTCOME:
            raise TemporalLeakageError(
                "outcome artifacts cannot enter a locked hypothesis commitment"
            )


def propose(
    policy: DeskPolicy,
    specification: ProposalSpec,
    descriptors: tuple[ArtifactDescriptor, ...],
    *,
    created_at: datetime,
    hypothesis_locked_at: datetime,
) -> ResearchProposal:
    """Return a content-addressed proposal after enforcing point-in-time and resource caps."""

    specification.validate()
    if specification.estimand.unit != policy.required_unit:
        raise ManifestError("estimand unit must equal the policy unit")
    _admit(policy, descriptors, hypothesis_locked_at)
    if created_at < hypothesis_locked_at:
        raise TemporalLeakageError("proposal creation predates its hypothesis commitment")
    if tuple(item.artifact_id for item in descriptors) != specification.artifact_ids:
        raise ManifestError("specification must name every descriptor exactly once")
    admitted_ids = set(specification.artifact_ids)
    for experiment in specification.experiments:
        if not set(experiment.artifact_ids).issubset(admitted_ids):
            raise ManifestError(
                "experiment references an artifact outside the admitted evidence closure"
            )
    if len(specification.experiments) > policy.max_experiments:
        raise ManifestError("proposal exceeds experiment count cap")
    units = sum(item.resource_units for item in specification.experiments)
    if any(
        item.resource_units > policy.max_experiment_units for item in specification.experiments
    ):
        raise ManifestError("an experiment exceeds per-experiment resource cap")
    if units > policy.max_total_experiment_units:
        raise ManifestError("proposal exceeds total resource budget")
    provisional = ResearchProposal(
        proposal_id="research-proposal-pending",
        proposal_digest="sha256:" + "0" * 64,
        policy_id=policy.policy_id,
        policy=policy,
        policy_digest=policy.content_digest(),
        evidence_closure_digest=evidence_closure_digest(descriptors),
        commitment_digest="sha256:" + "0" * 64,
        created_at=created_at,
        hypothesis_locked_at=hypothesis_locked_at,
        specification=specification,
        artifact_descriptors=descriptors,
    )
    commitment_digest = provisional.computed_commitment_digest()
    provisional = ResearchProposal(
        proposal_id="research-proposal-pending",
        proposal_digest="sha256:" + "0" * 64,
        policy_id=policy.policy_id,
        policy=policy,
        policy_digest=policy.content_digest(),
        evidence_closure_digest=evidence_closure_digest(descriptors),
        commitment_digest=commitment_digest,
        created_at=created_at,
        hypothesis_locked_at=hypothesis_locked_at,
        specification=specification,
        artifact_descriptors=descriptors,
    )
    content = provisional.content()
    return ResearchProposal(
        proposal_id=_id("research-proposal", content),
        proposal_digest=qualified_sha256_bytes(canonical_json_bytes(content)),
        policy_id=policy.policy_id,
        policy=policy,
        policy_digest=policy.content_digest(),
        evidence_closure_digest=evidence_closure_digest(descriptors),
        commitment_digest=commitment_digest,
        created_at=created_at,
        hypothesis_locked_at=hypothesis_locked_at,
        specification=specification,
        artifact_descriptors=descriptors,
        authority=AUTHORITY,
    )


@dataclass(frozen=True, slots=True)
class ResearchDeskLedger:
    """A persistent-value ledger: methods return a new ledger and never mutate the prior one."""

    proposals: tuple[ResearchProposal, ...] = ()
    dispositions: tuple[HumanDisposition, ...] = ()
    revisions: tuple[ProposalRevision, ...] = ()

    def validate(self) -> None:
        proposal_ids = tuple(item.proposal_id for item in self.proposals)
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ManifestError("ledger proposals must be append-only and unique")
        for proposal in self.proposals:
            proposal.validate()
        known = set(proposal_ids)
        by_id = {item.proposal_id: item for item in self.proposals}
        disposition_ids = tuple(item.disposition_id for item in self.dispositions)
        if len(set(disposition_ids)) != len(disposition_ids):
            raise ManifestError("ledger dispositions must be append-only and unique")
        for item in self.dispositions:
            item.validate()
            if item.proposal_id not in known:
                raise ManifestError("disposition references an unknown proposal")
            if item.decided_at < by_id[item.proposal_id].created_at:
                raise TemporalLeakageError("human disposition predates the proposal it reviews")
        revision_ids = tuple(item.revision_id for item in self.revisions)
        if len(set(revision_ids)) != len(revision_ids):
            raise ManifestError("ledger revisions must be append-only and unique")
        for item in self.revisions:
            item.validate()
            if item.prior_proposal_id not in known or item.successor_proposal_id not in known:
                raise ManifestError("revision references an unknown proposal")
            prior, successor = by_id[item.prior_proposal_id], by_id[item.successor_proposal_id]
            if item.revised_at < max(prior.created_at, successor.created_at):
                raise TemporalLeakageError("revision predates a proposal it supersedes")
            if prior.commitment_digest != successor.commitment_digest:
                raise ManifestError(
                    "an outcome-sensitive supersession cannot replace frozen policy, budget, "
                    "evidence, or hypothesis"
                )

    def append_proposal(self, proposal: ResearchProposal) -> ResearchDeskLedger:
        self.validate()
        proposal.validate()
        if proposal.proposal_id in {item.proposal_id for item in self.proposals}:
            raise ManifestError("duplicate proposal content is already present")
        return ResearchDeskLedger(
            proposals=(*self.proposals, proposal),
            dispositions=self.dispositions,
            revisions=self.revisions,
        )

    def append_disposition(self, disposition: HumanDisposition) -> ResearchDeskLedger:
        self.validate()
        disposition.validate()
        by_id = {item.proposal_id: item for item in self.proposals}
        if disposition.proposal_id not in by_id:
            raise ManifestError("human disposition requires an existing proposal")
        if disposition.disposition_id in {item.disposition_id for item in self.dispositions}:
            raise ManifestError("duplicate human disposition")
        if disposition.decided_at < by_id[disposition.proposal_id].created_at:
            raise TemporalLeakageError("human disposition predates the proposal it reviews")
        return ResearchDeskLedger(self.proposals, (*self.dispositions, disposition), self.revisions)

    def append_revision(self, revision: ProposalRevision) -> ResearchDeskLedger:
        self.validate()
        revision.validate()
        if revision.revision_id in {item.revision_id for item in self.revisions}:
            raise ManifestError("duplicate revision")
        candidate = ResearchDeskLedger(
            self.proposals, self.dispositions, (*self.revisions, revision)
        )
        candidate.validate()
        return candidate


def human_disposition(
    proposal_id: str,
    disposition: DispositionKind,
    human_id: str,
    decided_at: datetime,
    reason: str,
) -> HumanDisposition:
    """Build a human-authored disposition; the desk never supplies the human identity."""

    record = HumanDisposition(
        disposition_id="human-disposition-pending",
        proposal_id=proposal_id,
        disposition=disposition,
        human_id=human_id,
        decided_at=decided_at,
        reason=reason,
    )
    return HumanDisposition(
        _id("human-disposition", record.content()),
        proposal_id,
        disposition,
        human_id,
        decided_at,
        reason,
    )


def supersession(
    prior_proposal_id: str,
    successor_proposal_id: str,
    human_id: str,
    revised_at: datetime,
    reason: str,
) -> ProposalRevision:
    """Build append-only human supersession metadata; ledger validation enforces commitment lock."""

    record = ProposalRevision(
        revision_id="proposal-revision-pending",
        prior_proposal_id=prior_proposal_id,
        successor_proposal_id=successor_proposal_id,
        human_id=human_id,
        revised_at=revised_at,
        reason=reason,
    )
    return ProposalRevision(
        _id("proposal-revision", record.content()),
        prior_proposal_id,
        successor_proposal_id,
        human_id,
        revised_at,
        reason,
    )
