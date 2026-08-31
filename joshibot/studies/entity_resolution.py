"""Signal #2 — funding-tree entity resolution: which wallets are the SAME ACTOR.

PROGRAM.md §4 ranks this second and calls it a prerequisite for signals #1, #4, #5, #6 and #7,
because a study that splits train/test *before* collapsing wallets to entities lets one actor
straddle both sides (§3 rule 2). The number that motivates it: **36.5% of token supply is held by
coordinated accounts disguised as independent** (MELT, arXiv:2602.13480), and raw top-10 holder
share is a known anti-signal — 98.7% of launches have a dev buy. The computable quantity is the
**bundle-adjusted minus naive top-10 delta**, +24pp on high-risk tokens against +6pp on low-risk
ones, and that delta does not exist until wallets are resolved to entities.

Three independent linkage sources, union-merged per MELT's recipe:

1. ``co_signing`` — accounts that JOINTLY SIGN one transaction must all have supplied private
   keys, so they are the same actor. ~6.5% of holders / 9.2% of supply in MELT.
2. ``shared_first_funder`` — a Solana account needs a rent deposit to exist, so accounts funded
   by the same address likely share an owner. MELT's most productive source (~22.6% of holders /
   28.2% of supply) and the weakest per link, because exchange withdrawals look identical.
3. ``jito_bundle`` — insiders use Jito for atomic multi-wallet execution. Bundle IDs are **not on
   chain**; MELT crawled the Jito Explorer for them, and ``shitcoims_tape.backfill`` already
   quarantines them in a sidecar. Implemented here against that sidecar shape; it has zero rows
   in this environment, which is reported as zero rather than hidden.

Six decisions are load-bearing.

**Co-signing requires SIGNERS, not co-occurrence.** A tape ``Trade`` carries one wallet and no
``fee_payer`` (SWARM.md Track B gap 2, confirmed absent), so "both wallets moved in one
signature" cannot distinguish a co-signer from a passive airdrop recipient. Merging on
co-occurrence would fuse a duster with its victims — and the live store is **88.5% inbound dust**.
Unsigned co-occurrence is therefore refused by default and only counted; ``allow_unsigned`` exists
so the report can quote what it would have cost.

**A funder is not a controller.** CEX hot wallets, faucets and airdrop contracts fund thousands of
unrelated users. Exclusion is structural first and curated second: any funder whose FAN-OUT (count
of distinct wallets whose *first* funding it paid) reaches ``hub_degree`` is dropped as a linkage
source, and an operator address list is layered on top. The curated list is empty by default on
purpose — an unverifiable hard-coded "this is Binance" is the same disease as a fabricated cost
basis, so the default mechanism is the one that is measurable from the data.

**Degree capping alone does not stop a super-cluster, and the tests prove it.** A chain of
degree-2 funders (a funds b, b funds c, …) passes every local check and still union-finds into one
blob. So a global tripwire sits after the merge: a component at or above ``supercluster_min_size``
that also holds ``supercluster_share`` of all known wallets is SUPPRESSED — no links emitted for
it, the wallets counted, the verdict changed. Suppressed wallets are absent from the output rather
than emitted as singletons, because emitting them as singletons would silently assert independence
we do not have.

**Union-find is right HERE and wrong for signal #1.** PROGRAM.md §4.1 rejects connected components
for the SVN co-occurrence network, where they swallow 99.6% of the graph. That is a statement about
a *statistical* co-occurrence graph, whose edges are noisy by construction. Funding and co-signing
edges are near-deterministic facts about key custody, and §1.5 endorses union-find over funding
relations by name. The blob risk is real all the same, which is what the tripwire is for.

**Confidence is a stated prior, never a measurement.** There is no ground truth for wallet
ownership on Solana and none of these heuristics has published precision or recall against one.
:data:`METHOD_CONFIDENCE` encodes how much key-custody evidence each source carries, and the report
says plainly that it is unvalidated. Treat every cluster as a CANDIDATE.

**One ``EntityLink`` per (wallet, method).** The frozen dataclass carries a single ``method``
string, and PROGRAM.md needs downstream studies to report which heuristic did the work — co-signing
and shared-funder have different false-positive profiles. A wallet merged by two sources therefore
emits two records with the SAME ``entity_id``, and a study that wants "only the co-signing
clusters" filters on ``method`` without losing the merge.

Deterministic, offline, read-only. No network at run time; the store is opened read-only from a
copy, exactly as ``studies/callout_flow.py`` does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from solders.pubkey import Pubkey

from shitcoims_tape.backfill import (
    BackfillError,
    BackfillReport,
    load_intelligence_wallet_transactions,
    strict_pubkey,
)
from shitcoims_tape.schema import (
    EntityLink,
    EventKind,
    TapeError,
    Trade,
    event_from_json,
)

# ---------------------------------------------------------------------------------------------
# Method names and their confidences. Declared here so the hypothesis family is countable and so
# the priors are in one auditable place rather than sprinkled through the merge code.
# ---------------------------------------------------------------------------------------------

CO_SIGNING = "co_signing"
SHARED_FIRST_FUNDER = "shared_first_funder"
JITO_BUNDLE = "jito_bundle"
SINGLETON = "singleton"
#: Refused by default. "X paid the fee on a transaction that moved Y's balance" is the only
#: linkage-shaped relation the live intelligence store can express, and on that store 1,062 of
#: 1,208 such rows are inbound token dust with no SOL movement. It is a spam relation, not a
#: custody relation, and promoting it is documented as invalid for inference.
SPONSOR_UNVERIFIED = "sponsor_unverified"
#: Refused by default. Two wallets moving in one signature without a signer set: the airdrop
#: sender and its recipient look exactly like two co-signers.
CO_OCCURRENCE_UNSIGNED = "co_occurrence_unsigned"

#: **Unvalidated priors, not measured precision.** There is no ground-truth ownership labelling
#: for Solana wallets, so these encode how much *key custody* each observation implies:
#: a joint signature is near-definitional, a shared bundle is atomic co-execution by one
#: submitter, a shared funder is a correlation that exchanges reproduce for free.
METHOD_CONFIDENCE: dict[str, float] = {
    CO_SIGNING: 0.95,
    JITO_BUNDLE: 0.80,
    SHARED_FIRST_FUNDER: 0.60,
    SPONSOR_UNVERIFIED: 0.20,
    CO_OCCURRENCE_UNSIGNED: 0.20,
    SINGLETON: 1.0,
}

#: Fan-out at which a funder stops being evidence of control. §3 rule 7: reported with every
#: number, and :func:`hub_degree_sensitivity` sweeps it so the reader sees the whole curve.
DEFAULT_HUB_DEGREE = 25

#: A Jito bundle holds at most 5 transactions — a PROTOCOL fact, not a tuned threshold. More than
#: five distinct wallets under one bundle id means the mapping is wrong or the bundle is a shared
#: relay, and either way it is not one actor.
DEFAULT_MAX_BUNDLE_WALLETS = 5

#: The super-cluster tripwire. Both conditions must hold: an absolute floor so a 2-of-4 merge on a
#: tiny fixture never trips, and a share so growth in the corpus does not silently disarm it.
DEFAULT_SUPERCLUSTER_MIN_SIZE = 50
DEFAULT_SUPERCLUSTER_SHARE = 0.05

#: Evidence strings per (wallet, method) record. Bounded so one hub-adjacent wallet cannot emit a
#: megabyte of provenance; the count is reported so truncation is visible.
MAX_EVIDENCE = 8

VERDICT_OK = "RESOLVED"
VERDICT_NO_LINKS = "NO-LINKS-AT-THIS-N"
VERDICT_SUPERCLUSTER = "SUPER-CLUSTER-SUPPRESSED"


class EntityResolutionError(RuntimeError):
    """The resolver cannot proceed on this input. Fail closed rather than emit a wrong entity."""


# ---------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FundingEdge:
    """One native-SOL funding transfer: ``funder`` paid ``funded``.

    ``slot`` is the ordering key because it is the chain's own total order and is present even
    when an RPC omits ``block_time``. First-funder is decided by ``(slot, signature)``, which is
    deterministic under any input ordering — see ``test_first_funder_is_the_earliest_by_slot``.
    """

    funder: str
    funded: str
    lamports: int
    signature: str
    slot: int
    block_time: int | None = None

    @property
    def order_key(self) -> tuple[int, str]:
        return (self.slot, self.signature)


@dataclass(frozen=True, slots=True)
class CoSignature:
    """The signer set of one transaction. Every signer supplied a private key."""

    signature: str
    signers: tuple[str, ...]
    slot: int = 0


@dataclass(frozen=True, slots=True)
class BundleRow:
    """Jito bundle membership, in the shape ``shitcoims_tape.backfill`` already quarantines.

    Bundle ids are NOT on chain. This is a sidecar record and is never tape.
    """

    bundle_id: str
    signature: str
    bundle_index: int | None = None


@dataclass(frozen=True, slots=True)
class SponsorEdge:
    """``payer`` paid the fee on a transaction that moved ``subject``'s balance.

    Not a funding edge. Kept as a separate type so it cannot be mistaken for one at a call site.
    """

    payer: str
    subject: str
    signature: str
    moved_sol: bool
    inbound_token: bool


@dataclass(frozen=True, slots=True)
class LinkInputs:
    """Everything the resolver reads, already parsed and validated."""

    funding: tuple[FundingEdge, ...] = ()
    cosignatures: tuple[CoSignature, ...] = ()
    bundles: tuple[BundleRow, ...] = ()
    sponsors: tuple[SponsorEdge, ...] = ()
    rejected_rows: int = 0


@dataclass(frozen=True, slots=True)
class TapeIndex:
    """What the tape contributes: the wallet universe, signature membership, and holdings.

    ``holdings`` is ``mint -> wallet -> raw base units``, summed from ``token_delta_raw``. Raw
    amounts stay integral end to end (schema.py's f64 cliff); only the final share is a float.
    """

    wallets: frozenset[str]
    signature_wallets: Mapping[str, frozenset[str]]
    holdings: Mapping[str, Mapping[str, int]]
    trades: int = 0
    negative_balances: int = 0


def load_tape(path: Path) -> TapeIndex:
    """Read a tape JSONL through the frozen contract's own reader.

    A malformed line is fatal, not skipped: the recorder writes this file, so a line it cannot
    read back is a defect in our own instrument rather than a third party's archive.
    """
    wallets: set[str] = set()
    signature_wallets: dict[str, set[str]] = defaultdict(set)
    holdings: dict[str, dict[str, int]] = defaultdict(dict)
    trades = 0
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                event = event_from_json(json.loads(text))
            except (TapeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise EntityResolutionError(f"{path.name}:{number} is not a tape event: {exc}") from exc
            if event.kind is not EventKind.TRADE:
                continue
            body = event.body
            if not isinstance(body, Trade):
                continue
            trades += 1
            wallets.add(body.wallet)
            if event.chain is not None:
                signature_wallets[event.chain.signature].add(body.wallet)
            per_mint = holdings[body.mint]
            per_mint[body.wallet] = per_mint.get(body.wallet, 0) + body.token_delta_raw
    negative = 0
    clean: dict[str, dict[str, int]] = {}
    for mint, per_wallet in holdings.items():
        row: dict[str, int] = {}
        for wallet, amount in per_wallet.items():
            if amount < 0:
                # We saw a sell whose matching buy is outside the tape. Clamping to zero is the
                # only non-fabricating choice; counting it is what keeps the omission visible.
                negative += 1
                continue
            if amount > 0:
                row[wallet] = amount
        if row:
            clean[mint] = row
    return TapeIndex(
        wallets=frozenset(wallets),
        signature_wallets={sig: frozenset(members) for sig, members in signature_wallets.items()},
        holdings=clean,
        trades=trades,
        negative_balances=negative,
    )


def load_links(path: Path) -> LinkInputs:
    """Read the linkage sidecar. JSONL, one row per fact, ``kind`` selecting the shape.

    Accepted rows::

        {"kind": "funding", "funder": ..., "funded": ..., "lamports": "...", "slot": n,
         "signature": ..., "block_time": n?}
        {"kind": "signers", "signature": ..., "signers": [...], "slot": n?}
        {"kind": "bundle",  "signature": ..., "bundle_id": ..., "bundle_index": n?}

    A row carrying ``bundle_id`` with no ``kind`` is accepted as a bundle, which is exactly what
    ``shitcoims_tape.backfill.load_melt`` writes to its sidecar — so MELT's crawled traces import
    with no translation step and no second format to keep in sync.

    Rows that fail address validation are COUNTED, not repaired: base58 is case-sensitive and a
    mangled address names a different account or none.
    """
    funding: list[FundingEdge] = []
    cosignatures: list[CoSignature] = []
    bundles: list[BundleRow] = []
    rejected = 0
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise EntityResolutionError(f"{path.name}:{number} is not valid JSON") from exc
            if not isinstance(row, Mapping):
                rejected += 1
                continue
            kind = str(row.get("kind") or ("bundle" if row.get("bundle_id") else "")).strip()
            try:
                if kind == "funding":
                    funding.append(_funding_row(row))
                elif kind == "signers":
                    cosignatures.append(_signers_row(row))
                elif kind == "bundle":
                    bundles.append(_bundle_row(row))
                else:
                    rejected += 1
            except (BackfillError, KeyError, TypeError, ValueError):
                rejected += 1
    return LinkInputs(
        funding=tuple(funding),
        cosignatures=tuple(cosignatures),
        bundles=tuple(bundles),
        rejected_rows=rejected,
    )


def _amount(value: Any, *, field_name: str) -> int:
    """Parse a raw lamport amount. A float is refused — schema.py's f64 rule applies off-tape too."""
    if isinstance(value, bool | float):
        raise ValueError(f"{field_name} must be an integer or decimal string, never a float")
    return int(value)


def _funding_row(row: Mapping[str, Any]) -> FundingEdge:
    return FundingEdge(
        funder=strict_pubkey(row["funder"], field="funder"),
        funded=strict_pubkey(row["funded"], field="funded"),
        lamports=_amount(row.get("lamports", 0), field_name="lamports"),
        signature=str(row["signature"]),
        slot=int(row["slot"]),
        block_time=int(row["block_time"]) if row.get("block_time") else None,
    )


def _signers_row(row: Mapping[str, Any]) -> CoSignature:
    raw = row.get("signers") or []
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise ValueError("signers must be a list")
    signers = tuple(sorted({strict_pubkey(value, field="signer") for value in raw}))
    return CoSignature(signature=str(row["signature"]), signers=signers, slot=int(row.get("slot") or 0))


def _bundle_row(row: Mapping[str, Any]) -> BundleRow:
    index = row.get("bundle_index")
    return BundleRow(
        bundle_id=str(row["bundle_id"]),
        signature=str(row["signature"]),
        bundle_index=int(index) if index is not None else None,
    )


def load_exchanges(path: Path) -> frozenset[str]:
    """Operator-supplied exchange / faucet / airdrop addresses, one per line or as JSONL.

    Deliberately a FILE and not a constant. A hard-coded "this address is Binance" that nobody in
    this environment can verify is an unfalsifiable assertion in the middle of a merge rule, and
    the structural fan-out test is the mechanism that has to carry the weight anyway. Comments
    (``#``) are allowed so an operator can record where each address came from.
    """
    addresses: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.split("#", 1)[0].strip()
            if not text:
                continue
            if text.startswith("{"):
                row = json.loads(text)
                text = str(row.get("address") or "")
                if not text:
                    continue
            addresses.add(strict_pubkey(text, field="exchange_address"))
    return frozenset(addresses)


# ---------------------------------------------------------------------------------------------
# The intelligence store — read through the audited importer, never raw
# ---------------------------------------------------------------------------------------------


def store_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """``wallet_transaction`` rows in the shape ``backfill``'s importer expects."""
    rows = connection.execute(
        "SELECT subject_id, observed_at, emitted_at, payload_json FROM observations "
        "WHERE kind='wallet_transaction' ORDER BY sequence"
    ).fetchall()
    return [
        {
            "subject_id": subject_id,
            "observed_at": observed_at,
            "emitted_at": emitted_at,
            "payload": json.loads(payload_json),
        }
        for subject_id, observed_at, emitted_at, payload_json in rows
    ]


def store_tape_index(rows: Sequence[Mapping[str, Any]]) -> tuple[TapeIndex, BackfillReport]:
    """Normalise store rows into a :class:`TapeIndex` using the audited importer.

    The importer is what un-inverts the store's two clocks (``emitted_at`` is BLOCK time for
    chain rows, the reverse of its social rows) and what refuses multi-leg rows rather than
    splitting one SOL delta across legs. Reading the store raw here would fork both decisions.
    """
    wallets: set[str] = set()
    signature_wallets: dict[str, set[str]] = defaultdict(set)
    holdings: dict[str, dict[str, int]] = defaultdict(dict)
    trades = 0
    report: BackfillReport | None = None
    for item in load_intelligence_wallet_transactions(rows):
        if isinstance(item, BackfillReport):
            report = item
            continue
        body = item.body
        if not isinstance(body, Trade):
            continue
        trades += 1
        wallets.add(body.wallet)
        if item.chain is not None:
            signature_wallets[item.chain.signature].add(body.wallet)
        per_mint = holdings[body.mint]
        per_mint[body.wallet] = per_mint.get(body.wallet, 0) + body.token_delta_raw
    if report is None:  # pragma: no cover - the importer always yields a final report
        raise EntityResolutionError("the intelligence importer produced no report")
    clean = {
        mint: {wallet: amount for wallet, amount in per_wallet.items() if amount > 0}
        for mint, per_wallet in holdings.items()
    }
    negative = sum(1 for per in holdings.values() for amount in per.values() if amount < 0)
    return (
        TapeIndex(
            wallets=frozenset(wallets),
            signature_wallets={sig: frozenset(m) for sig, m in signature_wallets.items()},
            holdings={mint: row for mint, row in clean.items() if row},
            trades=trades,
            negative_balances=negative,
        ),
        report,
    )


def sponsor_edges_from_store(rows: Iterable[Mapping[str, Any]]) -> list[SponsorEdge]:
    """The fee-payer graph, read RAW and on purpose.

    The tape contract has no ``fee_payer`` field — SWARM.md Track B names its absence as gap (2)
    and this is why it matters: the payer is the only counterparty identity the store carries, and
    it is *not* on the tape. Reading it raw here, in one clearly-labelled function that returns a
    type which is not a :class:`FundingEdge`, is the honest way to surface an out-of-contract
    field without quietly widening the contract.

    ``moved_sol`` and ``inbound_token`` are carried so the report can separate "someone sponsored
    a transaction that moved my SOL" from "someone sprayed a token at me and paid for it".
    """
    edges: list[SponsorEdge] = []
    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, Mapping) or payload.get("succeeded") is False:
            continue
        payer = payload.get("fee_payer")
        subject = row.get("subject_id")
        if not payer or not subject or payer == subject:
            continue
        legs = [
            leg
            for leg in (payload.get("token_deltas") or [])
            if isinstance(leg, Mapping) and int(leg.get("raw_delta") or 0) > 0
        ]
        try:
            edges.append(
                SponsorEdge(
                    payer=strict_pubkey(payer, field="fee_payer"),
                    subject=strict_pubkey(subject, field="subject"),
                    signature=str(payload.get("signature") or ""),
                    moved_sol=int(payload.get("sol_delta_lamports") or 0) != 0,
                    inbound_token=bool(legs),
                )
            )
        except BackfillError:
            continue
    return edges


# ---------------------------------------------------------------------------------------------
# Stage 1 — first funders
# ---------------------------------------------------------------------------------------------


def first_funders(edges: Sequence[FundingEdge]) -> dict[str, FundingEdge]:
    """The EARLIEST inbound funding per wallet, by ``(slot, signature)``.

    Only the first one can be the rent deposit that brought the account into existence; later
    transfers are ordinary payments and carry no custody implication. Self-funding is dropped —
    a wallet topping itself up says nothing about who owns it.
    """
    best: dict[str, FundingEdge] = {}
    for edge in edges:
        if edge.funder == edge.funded:
            continue
        current = best.get(edge.funded)
        if current is None or edge.order_key < current.order_key:
            best[edge.funded] = edge
    return best


def funder_fanout(first: Mapping[str, FundingEdge]) -> dict[str, int]:
    """Distinct wallets each funder brought into existence. The CEX test statistic."""
    counts: dict[str, int] = defaultdict(int)
    for edge in first.values():
        counts[edge.funder] += 1
    return dict(counts)


def hub_funders(
    first: Mapping[str, FundingEdge],
    *,
    hub_degree: int = DEFAULT_HUB_DEGREE,
    exchanges: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Funders that are NOT evidence of control.

    Two rules, in this order:

    1. **Curated** — the operator's exchange / faucet / airdrop list. Complete lists do not exist,
       so this is a supplement, never the mechanism.
    2. **Structural** — fan-out at or above ``hub_degree``. This is the rule that has to work, and
       it is measurable from the data with no external labelling. MELT's instruction to "exclude
       CEX funding addresses" is realised here as a degree test precisely because their outflows
       are user withdrawals: an exchange funds unrelated strangers at scale, an operator funds a
       handful of their own wallets.

    Its limits are stated rather than hoped for: a *small* sprayer (fan-out 2 or 3) passes, and a
    chain of such funders still builds a blob. That is what the tripwire in :func:`resolve` is for,
    and ``test_funding_chain_of_low_degree_funders_is_suppressed`` is the proof it is needed.
    """
    if hub_degree < 2:
        raise EntityResolutionError("hub_degree must be at least 2; 1 would exclude every funder")
    fanout = funder_fanout(first)
    return frozenset(
        funder
        for funder in fanout
        if funder in exchanges or fanout[funder] >= hub_degree
    )


# ---------------------------------------------------------------------------------------------
# Stage 2 — candidate links, one function per source
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Link:
    """One asserted same-actor relation, with the evidence that justified it."""

    left: str
    right: str
    method: str
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.left == self.right:
            raise EntityResolutionError("a link must join two distinct wallets")


def _pairs(members: Sequence[str]) -> Iterator[tuple[str, str]]:
    """Star topology, not the clique: n-1 edges are enough for union-find and keep the output
    linear in group size rather than quadratic. The resulting component is identical."""
    ordered = sorted(set(members))
    anchor = ordered[0]
    for other in ordered[1:]:
        yield (anchor, other)


def funding_links(
    first: Mapping[str, FundingEdge], *, excluded: frozenset[str]
) -> list[Link]:
    """Wallets sharing a surviving first funder are the same candidate actor."""
    groups: dict[str, list[str]] = defaultdict(list)
    for wallet, edge in sorted(first.items()):
        if edge.funder in excluded:
            continue
        groups[edge.funder].append(wallet)
    links: list[Link] = []
    for funder, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        for left, right in _pairs(members):
            links.append(
                Link(
                    left=left,
                    right=right,
                    method=SHARED_FIRST_FUNDER,
                    evidence=(
                        f"first_funder={funder}",
                        f"sig={first[left].signature}",
                        f"sig={first[right].signature}",
                    ),
                )
            )
    return links


def cosigning_links(
    cosignatures: Sequence[CoSignature],
    *,
    hub_degree: int = DEFAULT_HUB_DEGREE,
    exchanges: frozenset[str] = frozenset(),
) -> tuple[list[Link], frozenset[str]]:
    """Joint signers are the same actor. Returns ``(links, relay_hubs)``.

    The same fan-out logic applies here: a fee-paying relayer or paymaster co-signs with every
    customer it serves, so a signer reaching ``hub_degree`` distinct co-signers is dropped as a
    service rather than an owner. Without this one relayer merges its entire customer base.
    """
    degree: dict[str, set[str]] = defaultdict(set)
    for row in cosignatures:
        if len(row.signers) < 2:
            continue
        for signer in row.signers:
            degree[signer].update(other for other in row.signers if other != signer)
    hubs = frozenset(
        signer
        for signer, others in degree.items()
        if signer in exchanges or len(others) >= hub_degree
    )
    links: list[Link] = []
    for row in sorted(cosignatures, key=lambda item: (item.slot, item.signature)):
        members = [signer for signer in row.signers if signer not in hubs]
        if len(members) < 2:
            continue
        for left, right in _pairs(members):
            links.append(
                Link(
                    left=left,
                    right=right,
                    method=CO_SIGNING,
                    evidence=(f"sig={row.signature}", f"signers={len(row.signers)}"),
                )
            )
    return links, hubs


def bundle_links(
    bundles: Sequence[BundleRow],
    signature_wallets: Mapping[str, frozenset[str]],
    *,
    max_bundle_wallets: int = DEFAULT_MAX_BUNDLE_WALLETS,
) -> tuple[list[Link], int]:
    """Wallets whose transactions share a Jito bundle id. Returns ``(links, refused_bundles)``.

    Bundle ids are not on chain, so this reads the sidecar and resolves each signature back to
    wallets through the tape. ``max_bundle_wallets`` defaults to the protocol's own cap of five
    transactions per bundle: more distinct wallets than that means the signature map is wrong or
    the bundle is a shared relay, and neither is one actor.
    """
    if max_bundle_wallets < 2:
        raise EntityResolutionError("max_bundle_wallets must be at least 2")
    members: dict[str, set[str]] = defaultdict(set)
    signatures: dict[str, set[str]] = defaultdict(set)
    for row in bundles:
        wallets = signature_wallets.get(row.signature)
        if not wallets:
            continue
        members[row.bundle_id].update(wallets)
        signatures[row.bundle_id].add(row.signature)
    links: list[Link] = []
    refused = 0
    for bundle_id, wallets in sorted(members.items()):
        if len(wallets) < 2:
            continue
        if len(wallets) > max_bundle_wallets:
            refused += 1
            continue
        for left, right in _pairs(sorted(wallets)):
            links.append(
                Link(
                    left=left,
                    right=right,
                    method=JITO_BUNDLE,
                    evidence=(f"bundle={bundle_id}", f"txs={len(signatures[bundle_id])}"),
                )
            )
    return links, refused


def unsigned_cooccurrence_links(
    signature_wallets: Mapping[str, frozenset[str]],
) -> list[Link]:
    """Two wallets moving in one signature, with NO signer evidence. Refused by default.

    Present so the report can quote what accepting it would cost. On an account-model chain this
    relation is not Bitcoin's multi-input co-spend: a transfer puts sender and recipient in the
    same transaction while only one of them holds a key, so the airdrop sprayer and its 581
    victims are indistinguishable from a co-signing ring.
    """
    links: list[Link] = []
    for signature, wallets in sorted(signature_wallets.items()):
        if len(wallets) < 2:
            continue
        for left, right in _pairs(sorted(wallets)):
            links.append(
                Link(
                    left=left,
                    right=right,
                    method=CO_OCCURRENCE_UNSIGNED,
                    evidence=(f"sig={signature}", f"wallets={len(wallets)}"),
                )
            )
    return links


def sponsor_links(edges: Sequence[SponsorEdge]) -> list[Link]:
    """Wallets sponsored by the same fee payer. Refused by default; see :data:`SPONSOR_UNVERIFIED`."""
    groups: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        groups[edge.payer].add(edge.subject)
    links: list[Link] = []
    for payer, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        for left, right in _pairs(sorted(members)):
            links.append(
                Link(
                    left=left,
                    right=right,
                    method=SPONSOR_UNVERIFIED,
                    evidence=(f"fee_payer={payer}",),
                )
            )
    return links


# ---------------------------------------------------------------------------------------------
# Stage 3 — union-merge
# ---------------------------------------------------------------------------------------------


class UnionFind:
    """Union by size with path compression. Deterministic: the entity id is derived from the
    sorted member set afterwards, so it never depends on the order unions were applied in."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._size: dict[str, int] = {}

    def add(self, item: str) -> None:
        if item not in self._parent:
            self._parent[item] = item
            self._size[item] = 1

    def find(self, item: str) -> str:
        self.add(item)
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a == b:
            return
        if self._size[a] < self._size[b] or (self._size[a] == self._size[b] and b < a):
            a, b = b, a
        self._parent[b] = a
        self._size[a] += self._size[b]

    def components(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for item in self._parent:
            out[self.find(item)].append(item)
        return {root: sorted(members) for root, members in out.items()}


def entity_id_for(members: Sequence[str]) -> str:
    """Content-addressed entity id: stable across runs, orderings and corpus growth of the
    unrelated parts. Changing membership changes the id, which is correct — it is a different
    claim about the world and must not silently inherit the old one's identity."""
    payload = "\n".join(sorted(members)).encode("utf-8")
    return "e" + hashlib.sha256(payload).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------
# The resolution
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Resolution:
    verdict: str
    reason: str
    links: tuple[EntityLink, ...]
    #: n at every stage, so the report never has to re-derive a denominator.
    stages: Mapping[str, Any] = field(default_factory=dict)
    cluster_sizes: Mapping[str, int] = field(default_factory=dict)
    params: Mapping[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def assignment(self) -> dict[str, str]:
        """``wallet -> entity_id``. One entry per wallet however many methods merged it."""
        return {link.wallet: link.entity_id for link in self.links}

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "n_links": len(self.links),
            "stages": dict(self.stages),
            "cluster_sizes": dict(self.cluster_sizes),
            "params": dict(self.params),
            "notes": list(self.notes),
        }


def resolve(
    tape: TapeIndex,
    inputs: LinkInputs,
    *,
    hub_degree: int = DEFAULT_HUB_DEGREE,
    max_bundle_wallets: int = DEFAULT_MAX_BUNDLE_WALLETS,
    exchanges: frozenset[str] = frozenset(),
    supercluster_min_size: int = DEFAULT_SUPERCLUSTER_MIN_SIZE,
    supercluster_share: float = DEFAULT_SUPERCLUSTER_SHARE,
    allow_unsigned_cooccurrence: bool = False,
    trust_sponsor_edges: bool = False,
    include_singletons: bool = True,
) -> Resolution:
    """Union-merge the surviving links and emit ``EntityLink`` records.

    Emits ONE record per (wallet, method): the frozen dataclass carries a single ``method`` and
    PROGRAM.md requires downstream studies to report which heuristic did the work.
    """
    # The wallet universe is the set of wallets under STUDY, not every address that ever appears.
    # A funder is included only if it also trades or signs: a CEX hot wallet is a counterparty, and
    # emitting it as its own entity would put an exchange in a train/test fold.
    wallets: set[str] = set(tape.wallets)
    wallets.update(edge.funded for edge in inputs.funding)
    for row in inputs.cosignatures:
        wallets.update(row.signers)
    if trust_sponsor_edges:
        for sponsor_edge in inputs.sponsors:
            wallets.update({sponsor_edge.payer, sponsor_edge.subject})

    first = first_funders(inputs.funding)
    excluded = hub_funders(first, hub_degree=hub_degree, exchanges=exchanges)
    links: list[Link] = funding_links(first, excluded=excluded)
    cosign, relay_hubs = cosigning_links(
        inputs.cosignatures, hub_degree=hub_degree, exchanges=exchanges
    )
    links.extend(cosign)
    bundle, refused_bundles = bundle_links(
        inputs.bundles, tape.signature_wallets, max_bundle_wallets=max_bundle_wallets
    )
    links.extend(bundle)

    unsigned = unsigned_cooccurrence_links(tape.signature_wallets)
    sponsor = sponsor_links(inputs.sponsors)
    notes: list[str] = []
    if allow_unsigned_cooccurrence:
        links.extend(unsigned)
        notes.append(
            "INFERENCE INVALID: unsigned co-occurrence accepted; a transfer puts sender and "
            "recipient in one transaction while only one holds a key"
        )
    if trust_sponsor_edges:
        links.extend(sponsor)
        notes.append(
            "INFERENCE INVALID: fee-payer sponsorship accepted; on the live store 1,062 of 1,208 "
            "such rows are inbound token dust with no SOL movement"
        )

    union = UnionFind()
    for wallet in wallets:
        union.add(wallet)
    for link in links:
        union.add(link.left)
        union.add(link.right)
        union.union(link.left, link.right)
    components = union.components()

    total_wallets = max(len(wallets), 1)
    largest = max((len(members) for members in components.values()), default=0)
    suppressed: set[str] = set()
    for members in components.values():
        if len(members) >= supercluster_min_size and len(members) / total_wallets >= supercluster_share:
            suppressed.update(members)

    evidence: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for link in links:
        for wallet in (link.left, link.right):
            evidence[wallet][link.method].extend(link.evidence)

    out: list[EntityLink] = []
    merged_wallets: set[str] = set()
    for members in sorted(components.values()):
        if members[0] in suppressed:
            continue
        entity = entity_id_for(members)
        if len(members) == 1:
            if include_singletons:
                out.append(
                    EntityLink(
                        wallet=members[0],
                        entity_id=entity,
                        method=SINGLETON,
                        confidence=METHOD_CONFIDENCE[SINGLETON],
                        evidence=(),
                    )
                )
            continue
        merged_wallets.update(members)
        for wallet in members:
            for method in sorted(evidence.get(wallet, {})):
                seen = list(dict.fromkeys(evidence[wallet][method]))
                truncated = len(seen) - MAX_EVIDENCE
                trimmed = tuple(seen[:MAX_EVIDENCE]) + (
                    (f"+{truncated}_more",) if truncated > 0 else ()
                )
                out.append(
                    EntityLink(
                        wallet=wallet,
                        entity_id=entity,
                        method=method,
                        confidence=METHOD_CONFIDENCE[method],
                        evidence=trimmed,
                    )
                )

    sizes = sorted(len(members) for members in components.values() if len(members) > 1)
    cluster_sizes: dict[str, int] = defaultdict(int)
    for size in sizes:
        cluster_sizes[str(size)] += 1

    stages = {
        "wallets_known": len(wallets),
        "tape_trades": tape.trades,
        "tape_signatures": len(tape.signature_wallets),
        "tape_negative_balances_clamped": tape.negative_balances,
        "sidecar_rows_rejected": inputs.rejected_rows,
        "funding_edges": len(inputs.funding),
        "wallets_with_a_first_funder": len(first),
        "distinct_first_funders": len(funder_fanout(first)),
        "funders_excluded_as_hubs": len(excluded),
        "cosignature_rows": len(inputs.cosignatures),
        "cosigning_relay_hubs_excluded": len(relay_hubs),
        "bundle_rows": len(inputs.bundles),
        "bundles_refused_over_cap": refused_bundles,
        "links_shared_first_funder": sum(1 for link in links if link.method == SHARED_FIRST_FUNDER),
        "links_co_signing": sum(1 for link in links if link.method == CO_SIGNING),
        "links_jito_bundle": sum(1 for link in links if link.method == JITO_BUNDLE),
        "links_unsigned_cooccurrence_available": len(unsigned),
        "links_sponsor_available": len(sponsor),
        "merged_wallets": len(merged_wallets),
        "entities_multi_wallet": len(sizes),
        "largest_cluster": largest,
        "suppressed_supercluster_wallets": len(suppressed),
        "emitted_records": len(out),
    }
    params = {
        "hub_degree": hub_degree,
        "max_bundle_wallets": max_bundle_wallets,
        "exchange_list_size": len(exchanges),
        "supercluster_min_size": supercluster_min_size,
        "supercluster_share": supercluster_share,
        "allow_unsigned_cooccurrence": allow_unsigned_cooccurrence,
        "trust_sponsor_edges": trust_sponsor_edges,
        "include_singletons": include_singletons,
        "method_confidence": dict(METHOD_CONFIDENCE),
        "confidence_is": "an unvalidated prior over key custody, NOT measured precision",
    }

    if suppressed:
        verdict = VERDICT_SUPERCLUSTER
        reason = (
            f"a component of {largest} wallets is >= {supercluster_min_size} and holds "
            f">= {supercluster_share:.0%} of the {total_wallets} known wallets; its links are "
            "SUPPRESSED rather than emitted, because a merge that size is a hub artefact"
        )
    elif not sizes:
        verdict = VERDICT_NO_LINKS
        reason = (
            "no linkage source produced a surviving edge: this is a NULL, and it is a statement "
            "about the corpus, not about whether coordinated wallets exist"
        )
    else:
        verdict = VERDICT_OK
        reason = f"{len(sizes)} multi-wallet entities over {len(merged_wallets)} wallets"

    return Resolution(
        verdict=verdict,
        reason=reason,
        links=tuple(out),
        stages=stages,
        cluster_sizes=dict(sorted(cluster_sizes.items(), key=lambda kv: int(kv[0]))),
        params=params,
        notes=tuple(notes),
    )


def hub_degree_sensitivity(
    tape: TapeIndex, inputs: LinkInputs, *, grid: Sequence[int], **kwargs: Any
) -> list[dict[str, Any]]:
    """§3 rule 7: the same corpus at every threshold, so the knob's effect is visible.

    The NFT wash-trading literature produced estimates from 0.12% to 94.5% on one market purely
    by moving knobs. Reporting one threshold without its curve is how that happens.
    """
    out: list[dict[str, Any]] = []
    for degree in grid:
        resolution = resolve(tape, inputs, hub_degree=degree, **kwargs)
        stages = resolution.stages
        out.append(
            {
                "hub_degree": degree,
                "verdict": resolution.verdict,
                "funders_excluded_as_hubs": stages["funders_excluded_as_hubs"],
                "merged_wallets": stages["merged_wallets"],
                "entities_multi_wallet": stages["entities_multi_wallet"],
                "largest_cluster": stages["largest_cluster"],
                "suppressed_supercluster_wallets": stages["suppressed_supercluster_wallets"],
            }
        )
    return out


# ---------------------------------------------------------------------------------------------
# The payoff — bundle-adjusted minus naive top-10 concentration
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConcentrationRow:
    """Per-mint top-10 concentration, naive and entity-adjusted.

    The delta is the signal MELT's ablation isolates: dropping holding concentration alone costs
    0.0036 AUPRC, dropping bundle statistics alone costs 0.0278, dropping BOTH costs 0.0461 —
    more than the sum. Raw concentration is near-worthless until it is read against the
    bundle-adjusted baseline.
    """

    mint: str
    holders: int
    entities: int
    total_raw: int
    naive_top10_raw: int
    adjusted_top10_raw: int

    @property
    def naive_share(self) -> float:
        return self.naive_top10_raw / self.total_raw if self.total_raw else 0.0

    @property
    def adjusted_share(self) -> float:
        return self.adjusted_top10_raw / self.total_raw if self.total_raw else 0.0

    @property
    def delta_pp(self) -> float:
        return 100.0 * (self.adjusted_share - self.naive_share)

    def to_json(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "holders": self.holders,
            "entities": self.entities,
            "total_raw": str(self.total_raw),
            "naive_top10_share": self.naive_share,
            "adjusted_top10_share": self.adjusted_share,
            "delta_pp": self.delta_pp,
        }


def top10_delta(
    holdings: Mapping[str, Mapping[str, int]],
    assignment: Mapping[str, str],
    *,
    k: int = 10,
) -> list[ConcentrationRow]:
    """Bundle-adjusted minus naive top-k share, per mint.

    Raw amounts stay integers throughout; only the share is a float, and it is computed once at
    the end. A wallet with no entity assignment is its own entity — absence of a link is not
    evidence of a merge, and defaulting it into some catch-all would invent concentration.
    """
    if k < 1:
        raise EntityResolutionError("k must be positive")
    rows: list[ConcentrationRow] = []
    for mint, per_wallet in sorted(holdings.items()):
        balances = {wallet: amount for wallet, amount in per_wallet.items() if amount > 0}
        if not balances:
            continue
        total = sum(balances.values())
        naive = sum(sorted(balances.values(), reverse=True)[:k])
        grouped: dict[str, int] = defaultdict(int)
        for wallet, amount in balances.items():
            grouped[assignment.get(wallet, wallet)] += amount
        adjusted = sum(sorted(grouped.values(), reverse=True)[:k])
        rows.append(
            ConcentrationRow(
                mint=mint,
                holders=len(balances),
                entities=len(grouped),
                total_raw=total,
                naive_top10_raw=naive,
                adjusted_top10_raw=adjusted,
            )
        )
    return rows


# ---------------------------------------------------------------------------------------------
# Calibration against a PLANTED world
#
# There is no ground truth for wallet ownership on Solana, so the only falsifiable number this
# lane can produce is recovery against a generator whose truth we wrote down. That is strictly
# weaker than validation — it measures the resolver against our own model of how coordinated
# actors fund wallets, not against the world — and the report says so in those words. It is still
# worth having, because it turns "the CEX rule costs recall" from an intuition into an exchange
# rate you can read off, and because a resolver that cannot recover a world it was handed has no
# business being pointed at the real one.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlantedWorld:
    tape: TapeIndex
    inputs: LinkInputs
    truth: Mapping[str, str]
    params: Mapping[str, Any]


def _address(counter: list[int]) -> str:
    counter[0] += 1
    return str(Pubkey(counter[0].to_bytes(32, "big")))


def _signature_from_index(index: int) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number, digits = index + 1, ""
    while number:
        digits = alphabet[number % 58] + digits
        number //= 58
    return digits.rjust(70, "1")


def simulate(
    *,
    seed: int,
    n_entities: int = 40,
    wallets_per_entity: int = 6,
    n_independent: int = 400,
    cex_withdrawal_rate: float = 0.30,
    cosign_rate: float = 0.5,
    bundle_rate: float = 0.5,
) -> PlantedWorld:
    """A world whose entity structure we know, because we wrote it.

    The generative model, stated so the number below is interpretable:

    * ``n_entities`` actors, each with ``wallets_per_entity`` wallets funded from that actor's own
      treasury — unless the wallet was instead funded straight from the exchange hub, which
      happens with probability ``cex_withdrawal_rate``. Those wallets are UNLINKABLE by the
      funding source on purpose: that is the recall the CEX rule costs, and pretending otherwise
      would be tuning the generator to flatter the resolver.
    * A fraction ``cosign_rate`` of actors also co-sign one transaction across two of their
      wallets, and ``bundle_rate`` submit one Jito bundle — the two sources that can recover an
      actor the funding rule lost.
    * ``n_independent`` unrelated wallets, funded individually or from the same exchange hub.
    """
    rng = random.Random(seed)
    counter = [0]
    hub = _address(counter)
    truth: dict[str, str] = {}
    funding: list[FundingEdge] = []
    cosignatures: list[CoSignature] = []
    bundles: list[BundleRow] = []
    signature_wallets: dict[str, frozenset[str]] = {}
    slot = 0
    sig_index = 0

    def next_signature() -> str:
        nonlocal sig_index
        sig_index += 1
        return _signature_from_index(sig_index)

    for entity in range(n_entities):
        treasury = _address(counter)
        members: list[str] = []
        for _ in range(wallets_per_entity):
            wallet = _address(counter)
            members.append(wallet)
            truth[wallet] = f"actor-{entity}"
            slot += 1
            funder = hub if rng.random() < cex_withdrawal_rate else treasury
            funding.append(
                FundingEdge(
                    funder=funder,
                    funded=wallet,
                    lamports=2_039_280,
                    signature=next_signature(),
                    slot=slot,
                )
            )
        if rng.random() < cosign_rate and len(members) >= 2:
            pair = rng.sample(members, 2)
            slot += 1
            cosignatures.append(
                CoSignature(signature=next_signature(), signers=tuple(sorted(pair)), slot=slot)
            )
        if rng.random() < bundle_rate and len(members) >= 2:
            chosen = rng.sample(members, min(len(members), DEFAULT_MAX_BUNDLE_WALLETS))
            bundle_id = f"bundle-{entity}"
            for wallet in chosen:
                signature = next_signature()
                signature_wallets[signature] = frozenset({wallet})
                bundles.append(BundleRow(bundle_id=bundle_id, signature=signature))
    for solo in range(n_independent):
        wallet = _address(counter)
        truth[wallet] = f"solo-{solo}"
        slot += 1
        funder = hub if rng.random() < cex_withdrawal_rate else _address(counter)
        funding.append(
            FundingEdge(
                funder=funder,
                funded=wallet,
                lamports=2_039_280,
                signature=next_signature(),
                slot=slot,
            )
        )
    tape = TapeIndex(
        wallets=frozenset(truth), signature_wallets=signature_wallets, holdings={}, trades=0
    )
    return PlantedWorld(
        tape=tape,
        inputs=LinkInputs(
            funding=tuple(funding), cosignatures=tuple(cosignatures), bundles=tuple(bundles)
        ),
        truth=truth,
        params={
            "seed": seed,
            "n_entities": n_entities,
            "wallets_per_entity": wallets_per_entity,
            "n_independent": n_independent,
            "cex_withdrawal_rate": cex_withdrawal_rate,
            "cosign_rate": cosign_rate,
            "bundle_rate": bundle_rate,
            "hub_fanout": sum(1 for edge in funding if edge.funder == hub),
        },
    )


def pairwise_scores(
    assignment: Mapping[str, str], truth: Mapping[str, str]
) -> dict[str, Any]:
    """Pairwise precision/recall against a planted truth.

    PAIRS, not wallets: entity resolution is a clustering problem and per-wallet accuracy is
    meaningless here — every wallet is trivially "correct" as a singleton at this base rate,
    which is the same disease as reporting accuracy at a 98% base rate (§3 rule 5). A wallet the
    resolver declined to place (a suppressed super-cluster) is scored as a singleton and counted
    separately, so refusing to answer costs recall rather than being silently excused.
    """
    cells: dict[tuple[str, str], int] = defaultdict(int)
    predicted: dict[str, int] = defaultdict(int)
    actual: dict[str, int] = defaultdict(int)
    unassigned = 0
    for wallet, true_entity in truth.items():
        pred = assignment.get(wallet)
        if pred is None:
            unassigned += 1
            pred = f"unassigned:{wallet}"
        cells[(pred, true_entity)] += 1
        predicted[pred] += 1
        actual[true_entity] += 1

    def pairs(count: int) -> int:
        return count * (count - 1) // 2

    true_positive = sum(pairs(count) for count in cells.values())
    predicted_pairs = sum(pairs(count) for count in predicted.values())
    actual_pairs = sum(pairs(count) for count in actual.values())
    precision = true_positive / predicted_pairs if predicted_pairs else 1.0
    recall = true_positive / actual_pairs if actual_pairs else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "wallets": len(truth),
        "unassigned_wallets": unassigned,
        "true_pairs": actual_pairs,
        "predicted_pairs": predicted_pairs,
        "true_positive_pairs": true_positive,
        "false_positive_pairs": predicted_pairs - true_positive,
        "false_negative_pairs": actual_pairs - true_positive,
        "pair_precision": precision,
        "pair_recall": recall,
        "pair_f1": f1,
    }


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------


def _load_store(path: Path) -> tuple[TapeIndex, BackfillReport, list[SponsorEdge]]:
    if not path.exists():
        raise EntityResolutionError(f"no store at {path}; copy it first, the daemon holds a lock")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = store_rows(connection)
    finally:
        connection.close()
    tape, report = store_tape_index(rows)
    return tape, report, sponsor_edges_from_store(rows)


def _empty_tape() -> TapeIndex:
    return TapeIndex(wallets=frozenset(), signature_wallets={}, holdings={})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tape", type=Path, default=None, help="tape JSONL (TapeEvent lines)")
    parser.add_argument("--links", type=Path, default=None, help="linkage sidecar JSONL")
    parser.add_argument("--store", type=Path, default=None, help="COPY of intelligence.sqlite3")
    parser.add_argument("--exchanges", type=Path, default=None, help="operator CEX/faucet list")
    parser.add_argument("--out", type=Path, default=None, help="EntityLink JSONL output")
    parser.add_argument("--hub-degree", type=int, default=DEFAULT_HUB_DEGREE)
    parser.add_argument("--max-bundle-wallets", type=int, default=DEFAULT_MAX_BUNDLE_WALLETS)
    parser.add_argument("--supercluster-min-size", type=int, default=DEFAULT_SUPERCLUSTER_MIN_SIZE)
    parser.add_argument("--supercluster-share", type=float, default=DEFAULT_SUPERCLUSTER_SHARE)
    parser.add_argument("--no-singletons", action="store_true")
    parser.add_argument(
        "--allow-unsigned-cooccurrence",
        action="store_true",
        help="merge wallets that merely co-occur in a signature. INVALID for inference.",
    )
    parser.add_argument(
        "--trust-sponsor-edges",
        action="store_true",
        help="merge wallets sharing a fee payer. INVALID for inference; dust looks identical.",
    )
    parser.add_argument("--sensitivity", action="store_true", help="sweep hub-degree and report")
    parser.add_argument(
        "--simulate",
        type=int,
        default=None,
        metavar="SEED",
        help="ignore all inputs and calibrate against a PLANTED world with the given seed",
    )
    args = parser.parse_args(argv)

    if args.simulate is not None:
        world = simulate(seed=args.simulate)
        resolution = resolve(
            world.tape,
            world.inputs,
            hub_degree=args.hub_degree,
            max_bundle_wallets=args.max_bundle_wallets,
        )
        print(
            json.dumps(
                {
                    "calibration": "PLANTED WORLD, not ground truth: this measures the resolver "
                    "against our own model of how coordinated actors fund wallets",
                    "world": dict(world.params),
                    "resolution": resolution.to_json(),
                    "scores": pairwise_scores(resolution.assignment, world.truth),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0

    tape = _empty_tape()
    sponsors: list[SponsorEdge] = []
    store_report: BackfillReport | None = None
    if args.tape is not None:
        tape = load_tape(args.tape)
    if args.store is not None:
        store_tape, store_report, sponsors = _load_store(args.store)
        tape = TapeIndex(
            wallets=tape.wallets | store_tape.wallets,
            signature_wallets={**dict(tape.signature_wallets), **dict(store_tape.signature_wallets)},
            holdings={**dict(tape.holdings), **dict(store_tape.holdings)},
            trades=tape.trades + store_tape.trades,
            negative_balances=tape.negative_balances + store_tape.negative_balances,
        )
    inputs = load_links(args.links) if args.links is not None else LinkInputs()
    inputs = LinkInputs(
        funding=inputs.funding,
        cosignatures=inputs.cosignatures,
        bundles=inputs.bundles,
        sponsors=tuple(sponsors),
        rejected_rows=inputs.rejected_rows,
    )
    exchanges = load_exchanges(args.exchanges) if args.exchanges is not None else frozenset()

    resolution = resolve(
        tape,
        inputs,
        hub_degree=args.hub_degree,
        max_bundle_wallets=args.max_bundle_wallets,
        exchanges=exchanges,
        supercluster_min_size=args.supercluster_min_size,
        supercluster_share=args.supercluster_share,
        allow_unsigned_cooccurrence=args.allow_unsigned_cooccurrence,
        trust_sponsor_edges=args.trust_sponsor_edges,
        include_singletons=not args.no_singletons,
    )
    payload = resolution.to_json()
    payload["concentration"] = [
        row.to_json() for row in top10_delta(tape.holdings, resolution.assignment)
    ]
    if store_report is not None:
        payload["store_import"] = store_report.to_json()
        payload["sponsor_edges"] = {
            "rows": len(sponsors),
            "distinct_payers": len({edge.payer for edge in sponsors}),
            "pure_inbound_token_no_sol": sum(
                1 for edge in sponsors if edge.inbound_token and not edge.moved_sol
            ),
        }
    if args.sensitivity:
        payload["hub_degree_sensitivity"] = hub_degree_sensitivity(
            tape,
            inputs,
            grid=(2, 3, 5, 10, 25, 50, 100),
            exchanges=exchanges,
            allow_unsigned_cooccurrence=args.allow_unsigned_cooccurrence,
            trust_sponsor_edges=args.trust_sponsor_edges,
        )
    if args.allow_unsigned_cooccurrence or args.trust_sponsor_edges:
        payload["INFERENCE_INVALID"] = "a refused linkage source was enabled"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as handle:
            for link in resolution.links:
                handle.write(json.dumps(link.to_json(), sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
