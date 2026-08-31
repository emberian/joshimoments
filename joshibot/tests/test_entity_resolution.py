"""Tests for the entity RESOLVER, not for any finding it produces.

The finding on the live store is a null (no linkage source has a single surviving edge), and a
null is only worth reporting if the instrument that produced it can be shown to work. So the
positive tests are paired with **teeth tests**: the same scenario re-run against a deliberately
weakened resolver, asserting the guard was doing real work. A test that passes for a broken
resolver has no content, and this repo has already shipped one vacuous green check.

Three scenario families:

* ``PLANTED`` — wallets that ARE one actor, by each of the three linkage sources. The resolver
  must merge them.
* ``INDEPENDENT`` — wallets that are not. The resolver must not merge them. This is the
  false-positive control, and it is the half that decides whether the output means anything.
* ``HUB`` — an exchange-shaped address funding thousands of unrelated strangers, and a chain of
  small sprayers that no degree rule can catch. Collapsing either into one giant entity is the
  classic super-cluster failure; ``test_cex_hub_*`` and
  ``test_chained_sources_build_a_supercluster_that_is_suppressed`` are the two that matter most.
"""

from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

from shitcoims_tape.schema import EntityLink
from studies.entity_resolution import (
    CO_OCCURRENCE_UNSIGNED,
    CO_SIGNING,
    DEFAULT_MAX_BUNDLE_WALLETS,
    METHOD_CONFIDENCE,
    SHARED_FIRST_FUNDER,
    SINGLETON,
    SPONSOR_UNVERIFIED,
    VERDICT_NO_LINKS,
    VERDICT_OK,
    VERDICT_SUPERCLUSTER,
    BundleRow,
    CoSignature,
    EntityResolutionError,
    FundingEdge,
    LinkInputs,
    TapeIndex,
    entity_id_for,
    first_funders,
    hub_degree_sensitivity,
    hub_funders,
    load_exchanges,
    load_links,
    load_tape,
    pairwise_scores,
    resolve,
    simulate,
    sponsor_edges_from_store,
    store_tape_index,
    top10_delta,
)

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def address(index: int) -> str:
    """A real 32-byte key. The tape contract DECODES addresses, so alphabet-only strings fail."""
    return str(Pubkey(index.to_bytes(32, "big")))


def signature(index: int) -> str:
    """A base58 signature of legal length, unique per index (right-aligned, so no prefix collides)."""
    number, digits = index + 1, ""
    while number:
        digits = _B58[number % 58] + digits
        number //= 58
    return digits.rjust(70, "1")


def funding(funder: int, funded: int, *, slot: int, sig: int | None = None) -> FundingEdge:
    return FundingEdge(
        funder=address(funder),
        funded=address(funded),
        lamports=2_039_280,
        signature=signature(sig if sig is not None else funded),
        slot=slot,
    )


def tape_of(wallets: list[int], **kwargs: object) -> TapeIndex:
    return TapeIndex(
        wallets=frozenset(address(index) for index in wallets),
        signature_wallets=kwargs.get("signature_wallets", {}),  # type: ignore[arg-type]
        holdings=kwargs.get("holdings", {}),  # type: ignore[arg-type]
    )


EMPTY = TapeIndex(wallets=frozenset(), signature_wallets={}, holdings={})


def entity_of(resolution: object, index: int) -> str | None:
    return resolution.assignment.get(address(index))  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------------------------
# PLANTED — each source must merge what it is supposed to merge
# ---------------------------------------------------------------------------------------------


def test_planted_same_entity_wallets_are_merged_by_shared_first_funder() -> None:
    edges = [funding(900, 1, slot=10), funding(900, 2, slot=11), funding(900, 3, slot=12)]
    resolution = resolve(tape_of([1, 2, 3]), LinkInputs(funding=tuple(edges)))

    assert resolution.verdict == VERDICT_OK
    assert entity_of(resolution, 1) == entity_of(resolution, 2) == entity_of(resolution, 3)
    assert resolution.stages["merged_wallets"] == 3
    assert resolution.cluster_sizes == {"3": 1}
    methods = {link.method for link in resolution.links}
    assert methods == {SHARED_FIRST_FUNDER}


def test_planted_cosigners_are_merged() -> None:
    rows = [CoSignature(signature=signature(1), signers=(address(1), address(2)), slot=5)]
    resolution = resolve(tape_of([1, 2, 3]), LinkInputs(cosignatures=tuple(rows)))

    assert entity_of(resolution, 1) == entity_of(resolution, 2)
    assert entity_of(resolution, 3) != entity_of(resolution, 1)
    assert {link.method for link in resolution.links if link.method != SINGLETON} == {CO_SIGNING}


def test_planted_jito_bundle_is_merged_through_the_tape() -> None:
    # Bundle ids are not on chain: the sidecar names signatures, and the tape maps them to wallets.
    signature_wallets = {
        signature(1): frozenset({address(1)}),
        signature(2): frozenset({address(2)}),
    }
    tape = TapeIndex(
        wallets=frozenset({address(1), address(2)}),
        signature_wallets=signature_wallets,
        holdings={},
    )
    bundles = (
        BundleRow(bundle_id="bundle-a", signature=signature(1), bundle_index=0),
        BundleRow(bundle_id="bundle-a", signature=signature(2), bundle_index=1),
    )
    resolution = resolve(tape, LinkInputs(bundles=bundles))

    assert entity_of(resolution, 1) == entity_of(resolution, 2)
    assert resolution.stages["links_jito_bundle"] == 1


def test_a_wallet_merged_by_two_sources_emits_one_record_per_method() -> None:
    """``method`` is load-bearing: co-signing and shared-funder have different FP profiles, so a
    downstream study must be able to report which heuristic did the work."""
    edges = (funding(900, 1, slot=1), funding(900, 2, slot=2))
    rows = (CoSignature(signature=signature(7), signers=(address(1), address(2))),)
    resolution = resolve(tape_of([1, 2]), LinkInputs(funding=edges, cosignatures=rows))

    records = [link for link in resolution.links if link.wallet == address(1)]
    assert {record.method for record in records} == {SHARED_FIRST_FUNDER, CO_SIGNING}
    assert len({record.entity_id for record in records}) == 1
    assert {record.confidence for record in records} == {
        METHOD_CONFIDENCE[SHARED_FIRST_FUNDER],
        METHOD_CONFIDENCE[CO_SIGNING],
    }


# ---------------------------------------------------------------------------------------------
# INDEPENDENT — the false-positive control
# ---------------------------------------------------------------------------------------------


def test_independent_wallets_are_not_merged() -> None:
    """200 wallets, 200 distinct funders, no co-signing, no bundles. Nothing may merge."""
    edges = tuple(funding(10_000 + index, index, slot=index) for index in range(200))
    resolution = resolve(tape_of(list(range(200))), LinkInputs(funding=edges))

    assert resolution.verdict == VERDICT_NO_LINKS
    assert resolution.stages["merged_wallets"] == 0
    assert resolution.stages["largest_cluster"] == 1
    assert resolution.cluster_sizes == {}
    assert {link.method for link in resolution.links} == {SINGLETON}
    assert len({link.entity_id for link in resolution.links}) == 200


def test_self_funding_is_not_a_link() -> None:
    edges = (funding(1, 1, slot=1), funding(2, 2, slot=2))
    resolution = resolve(tape_of([1, 2]), LinkInputs(funding=edges))
    assert resolution.stages["wallets_with_a_first_funder"] == 0
    assert entity_of(resolution, 1) != entity_of(resolution, 2)


def test_a_single_child_funder_produces_no_link() -> None:
    edges = (funding(900, 1, slot=1),)
    resolution = resolve(tape_of([1]), LinkInputs(funding=edges))
    assert resolution.stages["links_shared_first_funder"] == 0


# ---------------------------------------------------------------------------------------------
# HUB — the super-cluster failure mode, in both of its shapes
# ---------------------------------------------------------------------------------------------


HUB = 999_999
HUB_CHILDREN = 2_000


def _cex_hub_inputs() -> LinkInputs:
    """One address funding 2,000 unrelated strangers: an exchange withdrawal wallet."""
    return LinkInputs(
        funding=tuple(funding(HUB, index, slot=index) for index in range(1, HUB_CHILDREN + 1))
    )


def test_cex_hub_funding_thousands_of_unrelated_wallets_does_not_collapse_them() -> None:
    """THE test. MELT excludes CEX funding addresses because their outflows are user withdrawals,
    not control; without that exclusion this single address merges 2,000 strangers into one
    entity, and every downstream temporal split silently becomes a one-entity split."""
    inputs = _cex_hub_inputs()
    resolution = resolve(tape_of(list(range(1, HUB_CHILDREN + 1))), inputs)

    assert resolution.verdict == VERDICT_NO_LINKS
    assert resolution.stages["largest_cluster"] == 1
    assert resolution.stages["merged_wallets"] == 0
    assert resolution.stages["funders_excluded_as_hubs"] == 1
    assert len({link.entity_id for link in resolution.links}) == HUB_CHILDREN


def test_cex_hub_test_has_teeth_when_the_exclusion_is_disabled() -> None:
    """Falsification of the test above: with the degree rule pushed past the hub's fan-out, the
    2,000 wallets DO collapse — so the passing test is measuring the rule, not the fixture."""
    inputs = _cex_hub_inputs()
    resolution = resolve(
        tape_of(list(range(1, HUB_CHILDREN + 1))),
        inputs,
        hub_degree=HUB_CHILDREN + 1,
        supercluster_min_size=HUB_CHILDREN + 1,
    )
    assert resolution.stages["largest_cluster"] == HUB_CHILDREN
    assert resolution.stages["merged_wallets"] == HUB_CHILDREN


def test_hub_exclusion_removes_the_edge_not_the_wallets() -> None:
    """A hub's children are still resolvable by other evidence. Dropping the wallets instead of
    the edge would throw away every sniper that once withdrew from an exchange."""
    inputs = LinkInputs(
        funding=_cex_hub_inputs().funding,
        cosignatures=(CoSignature(signature=signature(1), signers=(address(1), address(2))),),
    )
    resolution = resolve(tape_of(list(range(1, HUB_CHILDREN + 1))), inputs)

    assert resolution.verdict == VERDICT_OK
    assert entity_of(resolution, 1) == entity_of(resolution, 2)
    assert resolution.cluster_sizes == {"2": 1}
    assert resolution.stages["largest_cluster"] == 2


def test_operator_exchange_list_excludes_a_funder_the_degree_rule_would_keep() -> None:
    """A small exchange or a faucet with three withdrawals passes the degree test. The curated
    list is the supplement for exactly that case — and it is a FILE, because a hard-coded
    unverifiable 'this address is Binance' is an assertion nobody in this repo can check."""
    edges = tuple(funding(900, index, slot=index) for index in (1, 2, 3))
    without = resolve(tape_of([1, 2, 3]), LinkInputs(funding=edges))
    assert without.stages["merged_wallets"] == 3

    with_list = resolve(
        tape_of([1, 2, 3]), LinkInputs(funding=edges), exchanges=frozenset({address(900)})
    )
    assert with_list.stages["merged_wallets"] == 0
    assert with_list.stages["funders_excluded_as_hubs"] == 1


def test_relay_cosigner_hub_does_not_merge_its_customers() -> None:
    """A fee-paying relayer co-signs with every customer. Same fan-out logic, other source."""
    relay = address(888_888)
    rows = tuple(
        CoSignature(signature=signature(index), signers=(relay, address(index)), slot=index)
        for index in range(1, 60)
    )
    resolution = resolve(tape_of(list(range(1, 60))), LinkInputs(cosignatures=rows))

    assert resolution.stages["cosigning_relay_hubs_excluded"] == 1
    assert resolution.stages["links_co_signing"] == 0
    assert resolution.stages["largest_cluster"] == 1


CHAIN_WALLETS = 240


def _chained_inputs() -> tuple[TapeIndex, LinkInputs]:
    """A blob built from links that every LOCAL rule accepts.

    Consecutive pairs share a first funder with fan-out exactly 2, and each pair is stitched to
    the next by a two-signer transaction. Every funder passes the degree test, every co-signer
    passes the relay test, and the UNION of the two sources still walks 240 wallets into one
    component. This is the shape a real bundler leaves behind, and it is why the degree rules
    cannot be the last line of defence.
    """
    edges = []
    for pair in range(CHAIN_WALLETS // 2):
        left, right = 2 * pair + 1, 2 * pair + 2
        edges.append(funding(100_000 + pair, left, slot=2 * pair, sig=left))
        edges.append(funding(100_000 + pair, right, slot=2 * pair + 1, sig=right))
    rows = tuple(
        CoSignature(
            signature=signature(500_000 + pair),
            signers=(address(2 * pair + 2), address(2 * pair + 3)),
            slot=pair,
        )
        for pair in range(CHAIN_WALLETS // 2 - 1)
    )
    tape = tape_of(list(range(1, CHAIN_WALLETS + 1)))
    return tape, LinkInputs(funding=tuple(edges), cosignatures=rows)


def test_funding_only_components_cannot_exceed_the_hub_degree() -> None:
    """A structural fact worth pinning: a wallet has exactly ONE first funder, so the
    shared-funder relation partitions wallets by funder and cannot chain. Funding-only clusters
    are therefore bounded above by ``hub_degree - 1``, and every blob larger than that came from
    combining sources — which is what the next test exercises."""
    edges = []
    for parent in range(1, 200):
        for child in (2 * parent, 2 * parent + 1):
            edges.append(funding(parent, child, slot=child, sig=child))
    resolution = resolve(tape_of(list(range(2, 400))), LinkInputs(funding=tuple(edges)))

    assert resolution.stages["largest_cluster"] == 2
    assert resolution.stages["largest_cluster"] < 25  # the default hub_degree


def test_chained_sources_build_a_supercluster_that_is_suppressed() -> None:
    """Degree capping alone is NOT enough, and this is the proof. A suppressed component emits
    NOTHING — emitting its members as singletons would assert an independence we do not have."""
    tape, inputs = _chained_inputs()
    resolution = resolve(tape, inputs)

    assert resolution.verdict == VERDICT_SUPERCLUSTER
    assert resolution.stages["largest_cluster"] == CHAIN_WALLETS
    assert resolution.stages["funders_excluded_as_hubs"] == 0, "every funder passed its local test"
    assert resolution.stages["cosigning_relay_hubs_excluded"] == 0, "so did every co-signer"
    assert resolution.stages["suppressed_supercluster_wallets"] == CHAIN_WALLETS
    assert resolution.links == ()


def test_supercluster_tripwire_has_teeth() -> None:
    """Falsification of the test above: raise the floor past the blob and it is emitted whole."""
    tape, inputs = _chained_inputs()
    resolution = resolve(tape, inputs, supercluster_min_size=100_000)

    assert resolution.verdict == VERDICT_OK
    assert resolution.stages["suppressed_supercluster_wallets"] == 0
    assert resolution.stages["largest_cluster"] == CHAIN_WALLETS
    assert resolution.links != ()


def test_suppressed_wallets_are_absent_not_emitted_as_singletons() -> None:
    tape, inputs = _chained_inputs()
    lone = address(10_000_000)
    tape = TapeIndex(wallets=tape.wallets | {lone}, signature_wallets={}, holdings={})
    resolution = resolve(tape, inputs)

    emitted = {link.wallet for link in resolution.links}
    assert emitted == {lone}, "only the untouched wallet survives; the blob is withheld entirely"


# ---------------------------------------------------------------------------------------------
# Refused sources — present so the report can quote what accepting them costs
# ---------------------------------------------------------------------------------------------


def test_unsigned_cooccurrence_is_refused_by_default() -> None:
    """A sprayer and its 60 victims share one signature each. On an account-model chain that is
    NOT Bitcoin's multi-input co-spend: only the sprayer holds a key."""
    sprayer = address(777_777)
    signature_wallets = {
        signature(index): frozenset({sprayer, address(index)}) for index in range(1, 61)
    }
    tape = TapeIndex(
        wallets=frozenset({sprayer} | {address(index) for index in range(1, 61)}),
        signature_wallets=signature_wallets,
        holdings={},
    )
    default = resolve(tape, LinkInputs())
    assert default.verdict == VERDICT_NO_LINKS
    assert default.stages["links_unsigned_cooccurrence_available"] == 60
    assert default.stages["merged_wallets"] == 0

    accepted = resolve(tape, LinkInputs(), allow_unsigned_cooccurrence=True)
    assert accepted.stages["largest_cluster"] == 61
    assert any("INFERENCE INVALID" in note for note in accepted.notes)
    assert CO_OCCURRENCE_UNSIGNED in METHOD_CONFIDENCE


def test_sponsor_edges_are_refused_by_default_and_merge_two_unrelated_wallets_when_trusted() -> None:
    """Reproduces the live-store finding in miniature: one dust sender that happens to have paid
    for a transaction touching two unrelated wallets merges them the moment sponsorship is
    trusted. On the real store those two wallets are our own sentinel and a third-party KOL."""
    rows = [
        {
            "subject_id": address(1),
            "payload": {"fee_payer": address(500), "signature": signature(1), "succeeded": True,
                        "sol_delta_lamports": 0, "token_deltas": [{"mint": address(50), "raw_delta": 5}]},
        },
        {
            "subject_id": address(2),
            "payload": {"fee_payer": address(500), "signature": signature(2), "succeeded": True,
                        "sol_delta_lamports": 0, "token_deltas": [{"mint": address(50), "raw_delta": 5}]},
        },
    ]
    edges = sponsor_edges_from_store(rows)
    assert len(edges) == 2
    assert all(edge.inbound_token and not edge.moved_sol for edge in edges)

    inputs = LinkInputs(sponsors=tuple(edges))
    default = resolve(tape_of([1, 2]), inputs)
    assert default.stages["merged_wallets"] == 0
    assert default.stages["links_sponsor_available"] == 1

    trusted = resolve(tape_of([1, 2]), inputs, trust_sponsor_edges=True)
    assert entity_of(trusted, 1) == entity_of(trusted, 2)
    assert {link.method for link in trusted.links if link.method != SINGLETON} == {SPONSOR_UNVERIFIED}
    assert any("INFERENCE INVALID" in note for note in trusted.notes)


# ---------------------------------------------------------------------------------------------
# Ordering, determinism, contract
# ---------------------------------------------------------------------------------------------


def test_first_funder_is_the_earliest_by_slot_not_the_first_row_seen() -> None:
    late = funding(901, 1, slot=99, sig=1)
    early = funding(902, 1, slot=5, sig=2)
    assert first_funders([late, early])[address(1)].funder == address(902)
    assert first_funders([early, late])[address(1)].funder == address(902)


def test_resolution_is_deterministic_under_input_shuffling() -> None:
    edges = [funding(900, index, slot=index) for index in range(1, 12)]
    edges += [funding(901, index, slot=index) for index in range(20, 26)]
    rows = [CoSignature(signature=signature(300), signers=(address(30), address(31)))]
    tape = tape_of(list(range(1, 12)) + list(range(20, 26)) + [30, 31])

    def render(seed: int) -> str:
        rng = random.Random(seed)
        shuffled = list(edges)
        rng.shuffle(shuffled)
        resolution = resolve(tape, LinkInputs(funding=tuple(shuffled), cosignatures=tuple(rows)))
        return "\n".join(
            json.dumps(link.to_json(), sort_keys=True, separators=(",", ":"))
            for link in resolution.links
        )

    assert render(1) == render(2) == render(3)


def test_entity_id_is_content_addressed_and_order_independent() -> None:
    members = [address(3), address(1), address(2)]
    assert entity_id_for(members) == entity_id_for(sorted(members))
    assert entity_id_for(members) != entity_id_for([*members, address(4)])


def test_every_emitted_record_satisfies_the_frozen_contract() -> None:
    edges = tuple(funding(900, index, slot=index) for index in (1, 2))
    resolution = resolve(tape_of([1, 2, 3]), LinkInputs(funding=edges))
    for link in resolution.links:
        assert isinstance(link, EntityLink)
        assert 0.0 <= link.confidence <= 1.0
        payload = json.loads(json.dumps(link.to_json()))
        assert set(payload) == {"wallet", "entity_id", "method", "confidence", "evidence"}
        # The frozen dataclass revalidates on construction, so a re-build is a contract check.
        EntityLink(
            wallet=payload["wallet"],
            entity_id=payload["entity_id"],
            method=payload["method"],
            confidence=payload["confidence"],
            evidence=tuple(payload["evidence"]),
        )


def test_hub_degree_below_two_fails_closed() -> None:
    with pytest.raises(EntityResolutionError):
        hub_funders({}, hub_degree=1)


# ---------------------------------------------------------------------------------------------
# Bundles
# ---------------------------------------------------------------------------------------------


def test_bundle_over_the_protocol_cap_is_refused() -> None:
    """Jito bundles hold at most five transactions. More distinct wallets than that means the
    signature map is wrong or the bundle is a shared relay — a protocol fact, not a tuned knob."""
    count = DEFAULT_MAX_BUNDLE_WALLETS + 3
    signature_wallets = {signature(i): frozenset({address(i)}) for i in range(1, count + 1)}
    tape = TapeIndex(
        wallets=frozenset(address(i) for i in range(1, count + 1)),
        signature_wallets=signature_wallets,
        holdings={},
    )
    bundles = tuple(
        BundleRow(bundle_id="b", signature=signature(i), bundle_index=i) for i in range(1, count + 1)
    )
    resolution = resolve(tape, LinkInputs(bundles=bundles))
    assert resolution.stages["bundles_refused_over_cap"] == 1
    assert resolution.stages["links_jito_bundle"] == 0
    assert resolution.stages["largest_cluster"] == 1


def test_bundle_signature_absent_from_the_tape_contributes_nothing() -> None:
    tape = TapeIndex(wallets=frozenset({address(1)}), signature_wallets={}, holdings={})
    bundles = (BundleRow(bundle_id="b", signature=signature(1)),)
    resolution = resolve(tape, LinkInputs(bundles=bundles))
    assert resolution.stages["links_jito_bundle"] == 0


# ---------------------------------------------------------------------------------------------
# Concentration — the number the whole signal exists to produce
# ---------------------------------------------------------------------------------------------


def test_top10_delta_is_zero_when_no_wallets_merge() -> None:
    holdings = {address(50): {address(i): 100 for i in range(1, 21)}}
    rows = top10_delta(holdings, {})
    assert len(rows) == 1
    assert rows[0].naive_share == pytest.approx(0.5)
    assert rows[0].delta_pp == pytest.approx(0.0)


def test_top10_delta_recovers_a_planted_bundle() -> None:
    """20 equal holders of 100 each. Eleven of them are one entity, so the adjusted top-10 sweeps
    the whole supply while the naive top-10 sees half of it: exactly +50pp."""
    holdings = {address(50): {address(i): 100 for i in range(1, 21)}}
    entity = entity_id_for([address(i) for i in range(1, 12)])
    assignment = {address(i): entity for i in range(1, 12)}
    row = top10_delta(holdings, assignment)[0]

    assert row.holders == 20
    assert row.entities == 10
    assert row.naive_share == pytest.approx(0.5)
    assert row.adjusted_share == pytest.approx(1.0)
    assert row.delta_pp == pytest.approx(50.0)


def test_adjusted_share_is_never_below_naive_over_random_assignments() -> None:
    """Grouping can only move mass into the top k. A negative delta would be an arithmetic bug,
    and it is the one direction the number can never legitimately go."""
    rng = random.Random(20260813)
    for trial in range(50):
        holdings = {
            address(50): {address(i): rng.randint(1, 10_000) for i in range(1, 40)}
        }
        assignment = {address(i): f"e{rng.randrange(6)}" for i in range(1, 40)}
        row = top10_delta(holdings, assignment)[0]
        assert row.adjusted_share >= row.naive_share - 1e-12, trial


def test_unassigned_wallets_are_their_own_entity_in_the_delta() -> None:
    holdings = {address(50): {address(1): 10, address(2): 20}}
    row = top10_delta(holdings, {})
    assert row[0].entities == 2


def test_top10_delta_keeps_raw_amounts_integral() -> None:
    big = 10**18  # beyond the f64 cliff the tape schema exists to avoid
    holdings = {address(50): {address(1): big, address(2): big + 1}}
    row = top10_delta(holdings, {})[0]
    assert row.total_raw == 2 * big + 1
    assert isinstance(row.total_raw, int)
    assert row.to_json()["total_raw"] == str(2 * big + 1)


# ---------------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------------


def test_load_links_accepts_the_melt_sidecar_shape_without_translation(tmp_path: Path) -> None:
    """``shitcoims_tape.backfill.load_melt`` writes bundle rows with no ``kind`` field. Accepting
    them directly means MELT's crawled traces import with no second format to keep in sync."""
    path = tmp_path / "links.jsonl"
    path.write_text(
        json.dumps(
            {
                "source": "melt.arxiv:2602.13480",
                "signature": signature(1),
                "bundle_id": "abc",
                "bundle_index": 0,
                "note": "jito bundle membership is not recoverable from chain",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    inputs = load_links(path)
    assert len(inputs.bundles) == 1
    assert inputs.bundles[0].bundle_id == "abc"
    assert inputs.rejected_rows == 0


def test_load_links_counts_malformed_rows_rather_than_repairing_them(tmp_path: Path) -> None:
    path = tmp_path / "links.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"kind": "funding", "funder": "notanaddress", "funded": address(1),
                            "lamports": 1, "signature": signature(1), "slot": 1}),
                json.dumps({"kind": "unknown"}),
                json.dumps({"kind": "funding", "funder": address(2), "funded": address(1),
                            "lamports": 1, "signature": signature(1), "slot": 1}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    inputs = load_links(path)
    assert len(inputs.funding) == 1
    assert inputs.rejected_rows == 2


def test_load_links_refuses_a_float_lamport_amount(tmp_path: Path) -> None:
    path = tmp_path / "links.jsonl"
    path.write_text(
        json.dumps({"kind": "funding", "funder": address(2), "funded": address(1),
                    "lamports": 1.5, "signature": signature(1), "slot": 1}) + "\n",
        encoding="utf-8",
    )
    assert load_links(path).rejected_rows == 1


def test_load_exchanges_reads_comments_and_addresses(tmp_path: Path) -> None:
    path = tmp_path / "cex.txt"
    path.write_text(f"# provenance goes here\n{address(900)}  # a labelled hot wallet\n\n", encoding="utf-8")
    assert load_exchanges(path) == frozenset({address(900)})


def test_load_tape_refuses_a_malformed_line(tmp_path: Path) -> None:
    path = tmp_path / "tape.jsonl"
    path.write_text('{"schema_version": 1, "kind": "trade"}\n', encoding="utf-8")
    with pytest.raises(EntityResolutionError):
        load_tape(path)


def test_load_tape_indexes_signatures_and_holdings(tmp_path: Path) -> None:
    lines = []
    for index, delta in ((1, 500), (2, 300)):
        lines.append(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "trade",
                    "observed_at": "2026-08-13T00:00:00+00:00",
                    "provenance": {"source": "test", "fetched_at": "2026-08-13T00:00:00+00:00"},
                    "chain": {"slot": 1, "signature": signature(9)},
                    "body": {
                        "mint": address(50),
                        "wallet": address(index),
                        "side": "buy",
                        "sol_delta_lamports": "-1000",
                        "token_delta_raw": str(delta),
                        "fee_lamports": "0",
                    },
                }
            )
        )
    path = tmp_path / "tape.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tape = load_tape(path)

    assert tape.trades == 2
    assert tape.signature_wallets[signature(9)] == frozenset({address(1), address(2)})
    assert tape.holdings[address(50)] == {address(1): 500, address(2): 300}


def test_load_tape_clamps_a_negative_balance_and_counts_it(tmp_path: Path) -> None:
    line = json.dumps(
        {
            "schema_version": 1,
            "kind": "trade",
            "observed_at": "2026-08-13T00:00:00+00:00",
            "provenance": {"source": "test", "fetched_at": "2026-08-13T00:00:00+00:00"},
            "chain": {"slot": 1, "signature": signature(9)},
            "body": {
                "mint": address(50),
                "wallet": address(1),
                "side": "sell",
                "sol_delta_lamports": "1000",
                "token_delta_raw": "-500",
                "fee_lamports": "0",
            },
        }
    )
    path = tmp_path / "tape.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    tape = load_tape(path)
    assert tape.negative_balances == 1
    assert tape.holdings == {}


# ---------------------------------------------------------------------------------------------
# Store import — through the audited importer, never raw
# ---------------------------------------------------------------------------------------------


def _store_row(subject: int, *, slot: int, sig: int, mint: int, delta: int) -> dict[str, object]:
    return {
        "subject_id": address(subject),
        "observed_at": "2026-08-13T12:00:00+00:00",
        # For chain rows the store puts BLOCK time in emitted_at; the importer un-inverts it.
        "emitted_at": "2026-08-12T20:00:00+00:00",
        "payload": {
            "signature": signature(sig),
            "slot": slot,
            "succeeded": True,
            "sol_delta_lamports": 1_000,
            "wallet_paid_fee": True,
            "fee_lamports": 5_000,
            "fee_payer": address(subject),
            "token_deltas": [{"mint": address(mint), "raw_delta": delta, "decimals": 6}],
        },
    }


def test_store_import_uninverts_the_clocks_through_the_audited_importer() -> None:
    tape, report = store_tape_index([_store_row(1, slot=7, sig=1, mint=50, delta=100)])
    assert report.trades == 1
    assert tape.signature_wallets[signature(1)] == frozenset({address(1)})
    assert tape.holdings[address(50)] == {address(1): 100}


def test_store_import_refuses_a_multi_leg_row_rather_than_splitting_it() -> None:
    row = _store_row(1, slot=7, sig=1, mint=50, delta=100)
    row["payload"]["token_deltas"].append({"mint": address(51), "raw_delta": 20, "decimals": 6})  # type: ignore[index,union-attr]
    tape, report = store_tape_index([row])
    assert report.ambiguous_multi_leg == 1
    assert tape.trades == 0


def test_sponsor_edges_ignore_self_paid_and_failed_transactions() -> None:
    rows = [
        {"subject_id": address(1), "payload": {"fee_payer": address(1), "signature": signature(1),
                                               "succeeded": True, "sol_delta_lamports": 1}},
        {"subject_id": address(1), "payload": {"fee_payer": address(9), "signature": signature(2),
                                               "succeeded": False, "sol_delta_lamports": 0}},
    ]
    assert sponsor_edges_from_store(rows) == []


def test_store_backed_resolution_runs_against_a_real_sqlite_copy(tmp_path: Path) -> None:
    """End to end over the actual store shape: no network, read-only, deterministic."""
    path = tmp_path / "intel.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE observations (sequence INTEGER PRIMARY KEY, kind TEXT, subject_id TEXT, "
        "observed_at TEXT, emitted_at TEXT, payload_json TEXT)"
    )
    for index, row in enumerate(
        [_store_row(1, slot=7, sig=1, mint=50, delta=100), _store_row(2, slot=8, sig=2, mint=50, delta=60)],
        start=1,
    ):
        connection.execute(
            "INSERT INTO observations VALUES (?,?,?,?,?,?)",
            (index, "wallet_transaction", row["subject_id"], row["observed_at"],
             row["emitted_at"], json.dumps(row["payload"])),
        )
    connection.commit()
    connection.close()

    from studies.entity_resolution import _load_store, store_rows

    tape, report, sponsors = _load_store(path)
    assert report.trades == 2
    assert sponsors == []
    resolution = resolve(tape, LinkInputs(sponsors=tuple(sponsors)))
    assert resolution.verdict == VERDICT_NO_LINKS
    assert resolution.stages["wallets_known"] == 2

    read_only = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        assert len(store_rows(read_only)) == 2
    finally:
        read_only.close()


# ---------------------------------------------------------------------------------------------
# Threshold reporting — §3 rule 7
# ---------------------------------------------------------------------------------------------


def test_hub_degree_sensitivity_shows_the_knob_moving_the_answer() -> None:
    """The NFT wash-trading literature produced 0.12% to 94.5% on one market purely by moving
    knobs. A single threshold reported without its curve is how that happens."""
    edges = tuple(funding(900, index, slot=index) for index in range(1, 11))
    tape = tape_of(list(range(1, 11)))
    curve = hub_degree_sensitivity(tape, LinkInputs(funding=edges), grid=(2, 5, 10, 25))

    by_degree = {row["hub_degree"]: row for row in curve}
    assert by_degree[2]["merged_wallets"] == 0
    assert by_degree[5]["merged_wallets"] == 0
    assert by_degree[10]["merged_wallets"] == 0  # fan-out 10 >= hub_degree 10, still excluded
    assert by_degree[25]["merged_wallets"] == 10
    merged = [row["merged_wallets"] for row in curve]
    assert merged == sorted(merged), (
        "with no hub present, raising the threshold can only admit more merges. That is NOT true "
        "in general once a hub exists — see the next test, where the tripwire reverses it."
    )


def test_raising_the_threshold_past_a_hub_trades_merges_for_refusal_not_for_errors() -> None:
    """The tripwire's whole purpose, measured on the planted world.

    At ``hub_degree`` 25 the exchange is excluded and 209 wallets merge correctly. At 200 the
    exchange survives the degree test, the blob forms, and the tripwire SUPPRESSES it — merges
    fall to 61 and recall collapses, but pair precision stays at 1.0. The failure mode converts
    from "hundreds of wrong merges" into "declined to answer", which is the only direction a
    fail-closed guard is allowed to move."""
    world = simulate(seed=20260813)
    guarded = resolve(world.tape, world.inputs, hub_degree=25)
    permissive = resolve(world.tape, world.inputs, hub_degree=200)

    assert pairwise_scores(guarded.assignment, world.truth)["pair_precision"] == 1.0
    permissive_scores = pairwise_scores(permissive.assignment, world.truth)
    assert permissive.verdict == VERDICT_SUPERCLUSTER
    assert permissive_scores["pair_precision"] == 1.0
    assert permissive_scores["false_positive_pairs"] == 0
    assert permissive_scores["pair_recall"] < pairwise_scores(guarded.assignment, world.truth)["pair_recall"]
    assert permissive.stages["merged_wallets"] < guarded.stages["merged_wallets"]


# ---------------------------------------------------------------------------------------------
# Calibration against a planted world — the only falsifiable number available without ground truth
# ---------------------------------------------------------------------------------------------


def test_planted_world_is_recovered_with_perfect_pair_precision() -> None:
    """Under the stated generator the resolver makes NO false merges, and loses exactly the
    recall the CEX rule costs: wallets an actor funded straight from the exchange are unlinkable
    by design, and the generator plants them on purpose rather than flattering the resolver."""
    world = simulate(seed=20260813)
    resolution = resolve(world.tape, world.inputs)
    scores = pairwise_scores(resolution.assignment, world.truth)

    assert resolution.stages["funders_excluded_as_hubs"] == 1
    assert scores["pair_precision"] == 1.0
    assert scores["false_positive_pairs"] == 0
    assert 0.6 < scores["pair_recall"] < 1.0
    assert scores["unassigned_wallets"] == 0


def test_calibration_is_stable_across_seeds() -> None:
    for seed in (1, 7, 99, 20260813):
        world = simulate(seed=seed)
        scores = pairwise_scores(resolve(world.tape, world.inputs).assignment, world.truth)
        assert scores["pair_precision"] == 1.0, seed
        assert scores["pair_recall"] > 0.5, seed


def test_calibration_has_teeth_precision_collapses_without_hub_exclusion() -> None:
    """Falsification of the test above: admit the exchange hub as a linkage source and the
    planted world's precision falls off a cliff, because 100+ unrelated strangers merge."""
    world = simulate(seed=20260813)
    resolution = resolve(
        world.tape, world.inputs, hub_degree=10_000, supercluster_min_size=10_000
    )
    scores = pairwise_scores(resolution.assignment, world.truth)
    assert scores["pair_precision"] < 0.2
    assert scores["false_positive_pairs"] > 1_000


def test_pairwise_scores_treat_a_withheld_wallet_as_a_singleton() -> None:
    """Refusing to answer costs recall. It must never be silently excused, or the tripwire would
    look free."""
    truth = {address(1): "a", address(2): "a", address(3): "b"}
    full = pairwise_scores({address(1): "e", address(2): "e", address(3): "f"}, truth)
    withheld = pairwise_scores({address(3): "f"}, truth)

    assert full["pair_recall"] == 1.0
    assert withheld["pair_recall"] == 0.0
    assert withheld["unassigned_wallets"] == 2


def test_simulator_is_deterministic_given_a_seed() -> None:
    first, second = simulate(seed=5), simulate(seed=5)
    assert first.truth == second.truth
    assert first.inputs.funding == second.inputs.funding
    assert simulate(seed=6).truth != first.truth
