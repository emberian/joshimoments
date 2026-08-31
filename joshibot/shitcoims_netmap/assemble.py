"""Assemble the three feeds into the network map. Pure: feeds in, JSON-serialisable dict out.

This module does no I/O and no network. Everything the terminal view shows is built here, so
``--json`` is the contract and the ASCII is a view of it — a number that exists only in the
drawing is a number nobody can audit.

The shape, top level::

    {
      "schema", "generated_at", "clocks", "window", "config",
      "sources":  per-feed health, including what the tape reader had to tolerate
      "nodes":    [ {symbol, mint, price_usd, degree, inventory, flow} ]
      "edges":    [ {pool, label, dex, element, fee, prices, flow, attempts, charge, ours} ]
      "cycles":   [ {name, legs, curl_bps, fee_band_bps, net_value_usd, verdict} ]
      "warnings": [ str ]
    }

Two invariants the rest of the codebase should be able to rely on:

- **A curl never appears without its net-of-cost value.** ``cycles[].net_value_usd`` is built in
  the same function as ``cycles[].curl_bps`` and both are always present. The largest standing
  residual in this cluster was measured at **$0.37-$9.86 per loop** after depth and gas; a curl
  without that number beside it is an invitation to trade noise.
- **Absence is typed.** ``edges[].flow.evidence`` is one of ``observed`` / ``observed_zero`` /
  ``not_watching``. There is no field that means "zero or unobserved", so no renderer can
  accidentally draw them the same.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from shitcoims_cluster.pools import CLUSTER_POOLS, DREGG, NOSIS, SOLVE, WEAVE, WSOL_MINT, PoolSpec
from shitcoims_netmap import SCHEMA
from shitcoims_netmap.lp import LpSnapshot
from shitcoims_netmap.physics import (
    CPMM_SPAN,
    DEFAULT_GAS_USD,
    DLMM_SPAN_TIGHT,
    DLMM_SPAN_WIDE,
    ELEMENT_BATTERY_STACK,
    ELEMENT_CAPACITOR,
    Fee,
    arb_value_usd,
    bps,
    capacitance_usd,
    curl_log,
    depth_term,
    dlmm_capacitance_bounds,
    dlmm_fee,
    fee_band_log,
    full_band_log,
    pumpswap_fee,
)
from shitcoims_netmap.prices import (
    SOURCE_CHAIN,
    SOURCE_DEXSCREENER,
    SOURCE_GECKOTERMINAL,
    PoolQuote,
    PriceSnapshot,
)
from shitcoims_netmap.tapefeed import EVIDENCE_NOT_WATCHING, PoolTape, TapeSnapshot

#: Human labels for the mints ``shitcoims_cluster.pools`` verified on chain. The symbols are for
#: humans only: the scratchpad that produced the swing study has weave and SOLVE transposed, and
#: nothing here joins on a symbol.
SYMBOL_BY_MINT: dict[str, str] = {
    WEAVE: "weave",
    NOSIS: "nosis",
    DREGG: "DREGG",
    SOLVE: "SOLVE",
    WSOL_MINT: "SOL",
}

#: Below this a pool's quote is a fossil rather than a market, and it is excluded from cycles.
MIN_CYCLE_LIQUIDITY_USD = 100.0


@dataclass(slots=True)
class Edge:
    """One pool as a circuit element, after every feed has been folded in."""

    pool: str
    label: str
    dex: str
    base_mint: str
    quote_mint: str
    base_symbol: str
    quote_symbol: str
    is_dlmm: bool
    mint_provenance: str
    in_cluster_universe: bool
    tvl_usd: float
    tvl_source: str
    fee: Fee
    prices: dict[str, float]
    tape: PoolTape | None
    ownership: dict[str, Any] | None
    liquidity_cross_check: dict[str, Any]
    extra: dict[str, Any]

    @property
    def element_type(self) -> str:
        return ELEMENT_BATTERY_STACK if self.is_dlmm else ELEMENT_CAPACITOR

    @property
    def primary_price(self) -> float | None:
        return (
            self.prices.get(SOURCE_DEXSCREENER)
            or self.prices.get(SOURCE_GECKOTERMINAL)
            or self.prices.get(SOURCE_CHAIN)
        )

    def depth_bounds(self) -> tuple[float, float]:
        """``(pessimistic, optimistic)`` depth term. A DLMM's span is unobservable, hence a pair."""

        if self.is_dlmm:
            return (
                depth_term(self.tvl_usd, span=DLMM_SPAN_WIDE),
                depth_term(self.tvl_usd, span=DLMM_SPAN_TIGHT),
            )
        value = depth_term(self.tvl_usd, span=CPMM_SPAN)
        return (value, value)


def _symbol(mint: str, fallback: str = "") -> str:
    return SYMBOL_BY_MINT.get(mint, fallback or f"{mint[:4]}…")


def _oriented(quote: PoolQuote | None, base_mint: str, quote_mint: str) -> float | None:
    """The aggregator's price re-expressed as *our* base in *our* quote, or ``None``.

    A source that reports a different pair than the on-chain-verified mints say is refused
    rather than reoriented on symbols — the symbols are the part that was transposed once.
    """

    if quote is None or not quote.usable:
        return None
    if quote.base_mint and quote.quote_mint:
        if (quote.base_mint, quote.quote_mint) == (base_mint, quote_mint):
            return quote.price_native
        if (quote.base_mint, quote.quote_mint) == (quote_mint, base_mint):
            return 1.0 / quote.price_native
        return None
    return quote.price_native


def _cluster_edge(
    spec: PoolSpec,
    prices: PriceSnapshot,
    tape: TapeSnapshot | None,
    lp: LpSnapshot | None,
) -> Edge:
    base_symbol, _, quote_symbol = spec.label.partition("/")
    by_symbol = {SYMBOL_BY_MINT.get(m, ""): m for m in spec.mints}
    base_mint = by_symbol.get(base_symbol, "")
    quote_mint = by_symbol.get(quote_symbol, "")
    return _build_edge(
        pool=spec.address,
        label=spec.label,
        dex=spec.dex,
        base_mint=base_mint,
        quote_mint=quote_mint,
        base_symbol=base_symbol,
        quote_symbol=quote_symbol,
        is_dlmm=not spec.replay_sufficient_reserves,
        mint_provenance="on_chain_verified (shitcoims_cluster.pools)",
        in_cluster_universe=True,
        prices=prices,
        tape=tape.pools.get(spec.address) if tape else None,
        ownership=lp.ownership(spec.address) if lp else None,
    )


def _chain_price(
    *,
    tape: PoolTape | None,
    dlmm: Any,
    base_mint: str,
    quote_mint: str,
    is_dlmm: bool,
) -> tuple[float | None, str | None, str]:
    """A price from pool *state*, with the event time it is from and what it is made of.

    Constant product: `p = y/x` from the vault balances the tape last observed — exact for the
    marginal price *if* the vaults hold no unclaimed fees, which is unverified here, so this
    channel is reported and cross-checked rather than trusted as primary.

    DLMM: the active bin, via Meteora's ``current_price``. A DLMM that has not traded has not
    moved its active bin, so — unlike a constant-product last-trade — a quiet DLMM quote is a
    parked battery rather than a stale print (study §2.2), which is why it carries no staleness
    stamp and needs none.
    """

    if is_dlmm:
        if dlmm is None or dlmm.current_price <= 0:
            return (None, None, "unavailable")
        if (dlmm.token_x_mint, dlmm.token_y_mint) == (base_mint, quote_mint):
            return (dlmm.current_price, None, "meteora active bin (token_y per token_x)")
        if (dlmm.token_x_mint, dlmm.token_y_mint) == (quote_mint, base_mint):
            return (1.0 / dlmm.current_price, None, "meteora active bin, inverted")
        return (None, None, "unavailable: DLMM mints do not match this edge")
    if tape is None:
        return (None, None, "unavailable: no tape rows")
    base_units = tape.last_reserves_units.get(base_mint, 0.0)
    quote_units = tape.last_reserves_units.get(quote_mint, 0.0)
    if base_units <= 0 or quote_units <= 0:
        return (None, None, "unavailable: no two-legged vault reading in the window")
    return (
        quote_units / base_units,
        tape.last_reserves_t_event,
        "constant-product vault ratio y/x from the cluster tape (unclaimed-fee bias unverified)",
    )


def _tape_tvl_usd(tape: PoolTape | None, prices: PriceSnapshot) -> float | None:
    """TVL from the last vault balances the tape observed, priced at current node prices.

    Both legs must be present: a one-legged reading would report half a pool. This is a
    chain-derived number stamped with the slot it came from, which is what makes it usable as a
    control on an aggregator's liquidity field.
    """

    if tape is None or len(tape.last_reserves_units) < 2:
        return None
    total = 0.0
    for mint, units in tape.last_reserves_units.items():
        price, _ = prices.token_price_usd(mint)
        if price <= 0:
            return None
        total += units * price
    return total


def _choose_tvl(
    *,
    is_dlmm: bool,
    meteora_tvl: float | None,
    tape_tvl: float | None,
    dex_tvl: float | None,
    gecko_tvl: float | None,
) -> tuple[float, str]:
    """Chain-derived vault readings beat aggregator liquidity fields, **including when zero**.

    A vault read that comes back empty is a measurement — the pool was drained — and treating it
    as a missing value is how a dead edge keeps rendering at an aggregator's stale $433. Study
    §7.3 independently measured DexScreener's reserve fields carrying a persistent bias of up to
    896 bps against the same pools, so the ordering is not a preference, it is the control.
    """

    if is_dlmm and meteora_tvl is not None:
        return meteora_tvl, "meteora_dlmm_api vaults x token prices (chain-derived)"
    if tape_tvl is not None:
        return tape_tvl, "cluster tape vault balances at the last observed slot (chain-derived)"
    if dex_tvl:
        return dex_tvl, "dexscreener liquidity.usd (aggregator)"
    if gecko_tvl:
        return gecko_tvl, "geckoterminal reserve_in_usd (aggregator)"
    return 0.0, "unavailable"


def _tvl_disagreement(*, chosen: float, others: list[float | None]) -> float | None:
    """Worst ratio between the chosen TVL and any other source. ``None`` when incomparable."""

    values = [v for v in others if isinstance(v, (int, float)) and v > 0]
    if not values or chosen <= 0:
        return None
    return round(max(max(v / chosen, chosen / v) for v in values), 2)


def _build_edge(
    *,
    pool: str,
    label: str,
    dex: str,
    base_mint: str,
    quote_mint: str,
    base_symbol: str,
    quote_symbol: str,
    is_dlmm: bool,
    mint_provenance: str,
    in_cluster_universe: bool,
    prices: PriceSnapshot,
    tape: PoolTape | None,
    ownership: dict[str, Any] | None,
) -> Edge:
    dex_quote = prices.dexscreener.get(pool)
    gecko_quote = prices.geckoterminal.get(pool)
    dlmm_state = prices.dlmm.get(pool)

    price_map: dict[str, float] = {}
    for source, quote in ((SOURCE_DEXSCREENER, dex_quote), (SOURCE_GECKOTERMINAL, gecko_quote)):
        oriented = _oriented(quote, base_mint, quote_mint)
        if oriented:
            price_map[source] = oriented
    chain_price, chain_stamp, chain_basis = _chain_price(
        tape=tape,
        dlmm=dlmm_state,
        base_mint=base_mint,
        quote_mint=quote_mint,
        is_dlmm=is_dlmm,
    )
    if chain_price:
        price_map[SOURCE_CHAIN] = chain_price

    tape_tvl = _tape_tvl_usd(tape, prices)
    tvl_usd, tvl_source = _choose_tvl(
        is_dlmm=is_dlmm,
        meteora_tvl=dlmm_state.tvl_usd if dlmm_state is not None else None,
        tape_tvl=tape_tvl,
        dex_tvl=dex_quote.liquidity_usd if dex_quote is not None else None,
        gecko_tvl=gecko_quote.liquidity_usd if gecko_quote is not None else None,
    )

    if is_dlmm:
        fee = dlmm_fee(
            dlmm_state.base_fee_pct if dlmm_state else None,
            dlmm_state.dynamic_fee_pct if dlmm_state else None,
        )
    else:
        fdv = (dex_quote.fdv_usd if dex_quote else 0.0) or (gecko_quote.fdv_usd if gecko_quote else 0.0)
        fee = pumpswap_fee(fdv)

    cross_check = {
        "chosen_usd": round(tvl_usd, 2),
        "chosen_source": tvl_source,
        "dexscreener_liquidity_usd": dex_quote.liquidity_usd if dex_quote else None,
        "geckoterminal_reserve_usd": gecko_quote.liquidity_usd if gecko_quote else None,
        "meteora_vault_tvl_usd": round(dlmm_state.tvl_usd, 2) if dlmm_state else None,
        "tape_reserves_usd": None if tape_tvl is None else round(tape_tvl, 2),
        "tape_reserves_t_event": tape.last_reserves_t_event if tape else None,
        "disagreement_ratio": _tvl_disagreement(
            chosen=tvl_usd,
            others=[
                dex_quote.liquidity_usd if dex_quote else None,
                gecko_quote.liquidity_usd if gecko_quote else None,
                tape_tvl,
            ],
        ),
    }
    extra: dict[str, Any] = {
        "chain_price_basis": chain_basis,
        "chain_price_t_event": chain_stamp,
        "volume_24h_usd": dex_quote.volume_24h_usd if dex_quote else None,
        "txns_24h": dex_quote.txns_24h if dex_quote else None,
        "txns_1h": dex_quote.txns_1h if dex_quote else None,
        "fdv_usd": dex_quote.fdv_usd if dex_quote else None,
    }
    if dlmm_state is not None:
        extra["dlmm"] = {
            "bin_step": dlmm_state.bin_step,
            "base_fee_pct": dlmm_state.base_fee_pct,
            "dynamic_fee_pct": dlmm_state.dynamic_fee_pct,
            "protocol_fee_pct": dlmm_state.protocol_fee_pct,
            "current_price": dlmm_state.current_price,
            "vault_amounts": {
                dlmm_state.token_x_mint: dlmm_state.token_x_amount,
                dlmm_state.token_y_mint: dlmm_state.token_y_amount,
            },
            "api_tvl_field_is_zero": dlmm_state.is_blacklisted,
        }

    return Edge(
        pool=pool,
        label=label,
        dex=dex,
        base_mint=base_mint,
        quote_mint=quote_mint,
        base_symbol=base_symbol,
        quote_symbol=quote_symbol,
        is_dlmm=is_dlmm,
        mint_provenance=mint_provenance,
        in_cluster_universe=in_cluster_universe,
        tvl_usd=tvl_usd,
        tvl_source=tvl_source,
        fee=fee,
        prices=price_map,
        tape=tape,
        ownership=ownership,
        liquidity_cross_check=cross_check,
        extra=extra,
    )


def _lp_only_edges(lp: LpSnapshot | None, prices: PriceSnapshot, known: set[str]) -> list[Edge]:
    """Edges we hold LP in that are not in the on-chain-verified cluster universe.

    They are drawn because an edge of ours is part of the circuit whether or not ``pools.py``
    blessed it, and they are flagged ``in_cluster_universe: false`` with a weaker mint
    provenance so nobody mistakes an API's word for the chain read.
    """

    if lp is None:
        return []
    edges: list[Edge] = []
    for pool, positions in lp.positions.items():
        if pool in known:
            continue
        state = prices.dlmm.get(pool)
        mints = list(positions[0].token_amounts) if positions else []
        base_mint = state.token_x_mint if state else (mints[0] if mints else "")
        quote_mint = state.token_y_mint if state else (mints[1] if len(mints) > 1 else "")
        pair = positions[0].pair if positions else None
        base_symbol, _, quote_symbol = (pair or "").partition("/")
        edges.append(
            _build_edge(
                pool=pool,
                label=pair or f"{_symbol(base_mint)}/{_symbol(quote_mint)}",
                dex="meteora_dlmm",
                base_mint=base_mint,
                quote_mint=quote_mint,
                base_symbol=base_symbol or _symbol(base_mint),
                quote_symbol=quote_symbol or _symbol(quote_mint),
                is_dlmm=True,
                mint_provenance="meteora_api (NOT chain-verified by shitcoims_cluster.pools)",
                in_cluster_universe=False,
                prices=prices,
                tape=None,
                ownership=lp.ownership(pool),
            )
        )
    return edges


def _edge_json(edge: Edge, prices: PriceSnapshot) -> dict[str, Any]:
    low, high = (
        dlmm_capacitance_bounds(edge.tvl_usd)
        if edge.is_dlmm
        else (capacitance_usd(edge.tvl_usd), capacitance_usd(edge.tvl_usd))
    )
    depth_low, depth_high = edge.depth_bounds()
    element: dict[str, Any] = {
        "type": edge.element_type,
        "tvl_usd": round(edge.tvl_usd, 2),
        "tvl_source": edge.tvl_source,
        "liquidity_cross_check": edge.liquidity_cross_check,
        "depth_term_log_per_usd": {
            "pessimistic": None if not math.isfinite(depth_low) else depth_low,
            "optimistic": None if not math.isfinite(depth_high) else depth_high,
        },
    }
    if edge.is_dlmm:
        element["identity"] = (
            "C̄ = TVL/W, a SERIES BATTERY-CELL STACK: C = ∞ inside a bin, 0 at a bin edge. "
            "W (the log-width the liquidity spans) is not observable from any keyless endpoint, "
            "so this is an interval, never a point"
        )
        element["capacitance_usd_per_log_price"] = {
            "low": round(low, 2),
            "high": round(high, 2),
            "span_bounds": [DLMM_SPAN_WIDE, DLMM_SPAN_TIGHT],
            "concentration_vs_cpmm": f"{CPMM_SPAN / DLMM_SPAN_TIGHT:.0f}x at the tight bound",
        }
    else:
        element["identity"] = "C = w_x·w_y·TVL = TVL/4 at even weights (exact, verified to 6 s.f.)"
        element["capacitance_usd_per_log_price"] = {"value": round(low, 2), "weights": [0.5, 0.5]}

    prices_json: dict[str, Any] = {
        "base_in_quote": dict(edge.prices),
        "clock": prices.clock,
        "as_of": prices.fetched_at,
    }
    dex_price = edge.prices.get(SOURCE_DEXSCREENER)
    gecko_price = edge.prices.get(SOURCE_GECKOTERMINAL)
    chain_price = edge.prices.get(SOURCE_CHAIN)
    if dex_price and gecko_price:
        prices_json["aggregator_disagreement_bps"] = round(bps(math.log(gecko_price / dex_price)), 1)
    if dex_price and chain_price:
        prices_json["chain_vs_dexscreener_bps"] = round(bps(math.log(chain_price / dex_price)), 1)
    prices_json["chain_price_basis"] = edge.extra.get("chain_price_basis")
    prices_json["chain_price_t_event"] = edge.extra.get("chain_price_t_event")

    out: dict[str, Any] = {
        "pool": edge.pool,
        "label": edge.label,
        "dex": edge.dex,
        "base": {"symbol": edge.base_symbol, "mint": edge.base_mint},
        "quote": {"symbol": edge.quote_symbol, "mint": edge.quote_mint},
        "mint_provenance": edge.mint_provenance,
        "in_cluster_universe": edge.in_cluster_universe,
        "element": element,
        "fee": edge.fee.to_json(),
        "prices": prices_json,
        "market": edge.extra,
        "ours": edge.ownership,
    }
    if edge.tape is not None:
        tape_json = edge.tape.to_json()
        out["flow"] = tape_json["flow"]
        out["attempts"] = tape_json["attempts"]
        out["charge"] = tape_json["charge"]
        out["tape_counts"] = tape_json["counts"]
        out["tape_window"] = tape_json["window"]
        out["clock_alarms"] = tape_json["clock_alarms"]
        out["lp_candidates_from_tape"] = tape_json["lp_candidates_from_tape"]
        out["charge"]["implied_displacement_bps"] = _implied_displacement_bps(edge, prices)
        out["charge"]["implied_displacement_note"] = (
            "ΔV ≈ ΔQ/C with C at the current TVL. C moves with Q (C = Q/2 for constant product), "
            "so over a large window this is a linearisation, not an identity"
        )
        out["flow"]["gross_usd_at_current_price"] = _gross_flow_usd(edge, prices)
        out["flow"]["gross_usd_note"] = (
            "historical flow valued at the CURRENT price: a magnitude, not a P&L, and the only "
            "place in this map where an ingest-clock quote touches an event-time quantity"
        )
    else:
        out["flow"] = {
            "evidence": EVIDENCE_NOT_WATCHING,
            "note": "this edge is outside the cluster tape's pool set — the collector never watched it",
        }
    return out


def _gross_flow_usd(edge: Edge, prices: PriceSnapshot) -> float | None:
    if edge.tape is None:
        return None
    total = 0.0
    seen = False
    for mint, units in edge.tape.gross_out_units.items():
        price, _ = prices.token_price_usd(mint)
        if price > 0:
            total += units * price
            seen = True
    return round(total, 2) if seen else None


def _implied_displacement_bps(edge: Edge, prices: PriceSnapshot) -> float | None:
    """`ΔV = ΔQ/C` for the window, in bps — how far the net charge injection moved the potential.

    Defined for a constant-product edge, where `C = TVL/4` is exact and `Q` is the quote-side
    reserve in dollars. A DLMM's `C` is a comb whose coarse-graining needs the unobservable bin
    span, so this stays ``None`` there rather than quoting a number that depends on a knob.
    """

    if edge.tape is None or edge.is_dlmm or edge.tvl_usd <= 0:
        return None
    delta_units = edge.tape.net_delta_units.get(edge.quote_mint)
    if delta_units is None:
        return None
    price, _ = prices.token_price_usd(edge.quote_mint)
    if price <= 0:
        return None
    capacitance = capacitance_usd(edge.tvl_usd)
    if capacitance <= 0:
        return None
    return round(bps(delta_units * price / capacitance), 1)


def _nodes(edges: list[Edge], prices: PriceSnapshot, lp: LpSnapshot | None) -> list[dict[str, Any]]:
    mints: dict[str, str] = {}
    for edge in edges:
        for mint, symbol in ((edge.base_mint, edge.base_symbol), (edge.quote_mint, edge.quote_symbol)):
            if mint:
                mints.setdefault(mint, _symbol(mint, symbol))

    nodes: list[dict[str, Any]] = []
    for mint, symbol in mints.items():
        touching = [e for e in edges if mint in (e.base_mint, e.quote_mint)]
        live = [e for e in touching if e.tvl_usd >= MIN_CYCLE_LIQUIDITY_USD]
        price_usd, price_from = prices.token_price_usd(mint)

        inventory_units = 0.0
        inventory_usd = 0.0
        held_in: list[str] = []
        if lp is not None:
            for pool, positions in lp.positions.items():
                for position in positions:
                    if mint in position.token_amounts:
                        inventory_units += position.token_amounts[mint]
                        inventory_usd += position.token_usd.get(mint, 0.0)
                        held_in.append(pool)

        gross_units = sum(
            (e.tape.gross_out_units.get(mint, 0.0) if e.tape else 0.0) for e in touching
        )
        net_units = sum((e.tape.net_delta_units.get(mint, 0.0) if e.tape else 0.0) for e in touching)
        watched = any(e.tape is not None and e.tape.watched_seconds > 0 for e in touching)

        nodes.append(
            {
                "symbol": symbol,
                "mint": mint,
                "price_usd": price_usd or None,
                "price_source": price_from or None,
                "degree": len(touching),
                "degree_live": len(live),
                "edges": [e.label for e in touching],
                "inventory": {
                    "lp_units": round(inventory_units, 6) if lp is not None else None,
                    "lp_usd": round(inventory_usd, 2) if lp is not None else None,
                    "in_pools": sorted(set(held_in)),
                    "wallet_balance_units": None,
                    "complete": False,
                    "basis": (
                        "LP positions only. A wallet's spot balance needs an RPC read, which is "
                        "outside this map's three read-only feeds, so inventory is a LOWER BOUND"
                        if lp is not None and lp.resolved
                        else "no LP wallet resolved — inventory is unknown, not zero"
                    ),
                },
                "flow_units_out_window": round(gross_units, 6),
                "flow_usd_out_window": round(gross_units * price_usd, 2) if price_usd else None,
                "net_charge_units_window": round(net_units, 6),
                "net_charge_usd_window": round(net_units * price_usd, 2) if price_usd else None,
                "any_watch_coverage": watched,
            }
        )
    return sorted(nodes, key=lambda n: (-n["degree"], n["symbol"]))


@dataclass(slots=True)
class CycleLeg:
    edge: Edge
    orientation: int


def _build_cycles(edges: list[Edge]) -> list[list[CycleLeg]]:
    """2-cycles (same pair, two venues) and triangles, over edges that can actually be priced.

    The 2-cycle is the degenerate cycle and the best-instrumented one here, because both legs
    can have real liquidity; it is reported alongside the triangles rather than instead of them.
    """

    live = [
        e
        for e in edges
        if e.primary_price and e.tvl_usd >= MIN_CYCLE_LIQUIDITY_USD and e.base_mint and e.quote_mint
    ]
    cycles: list[list[CycleLeg]] = []

    by_pair: dict[frozenset[str], list[Edge]] = {}
    for edge in live:
        by_pair.setdefault(frozenset({edge.base_mint, edge.quote_mint}), []).append(edge)
    for group in by_pair.values():
        for first, second in itertools.combinations(group, 2):
            back = -1 if (second.base_mint, second.quote_mint) == (first.base_mint, first.quote_mint) else 1
            cycles.append([CycleLeg(first, +1), CycleLeg(second, back)])

    deepest: dict[frozenset[str], Edge] = {}
    for edge in live:
        key = frozenset({edge.base_mint, edge.quote_mint})
        if key not in deepest or edge.tvl_usd > deepest[key].tvl_usd:
            deepest[key] = edge
    node_mints = sorted({m for e in live for m in (e.base_mint, e.quote_mint)})
    for triple in itertools.combinations(node_mints, 3):
        i, j, k = triple
        legs: list[CycleLeg] = []
        for a, b in ((i, j), (j, k), (k, i)):
            leg_edge = deepest.get(frozenset({a, b}))
            if leg_edge is None:
                legs = []
                break
            oriented = +1 if (leg_edge.base_mint, leg_edge.quote_mint) == (a, b) else -1
            legs.append(CycleLeg(leg_edge, oriented))
        if legs:
            cycles.append(legs)
    return cycles


def _cycle_json(legs: list[CycleLeg], gas_usd: float) -> dict[str, Any]:
    names: list[str] = []
    for leg in legs:
        start = leg.edge.base_symbol if leg.orientation > 0 else leg.edge.quote_symbol
        names.append(start)
    names.append(names[0])

    fees = [leg.edge.fee for leg in legs]
    band = fee_band_log(fees)
    depth_pessimistic = sum(leg.edge.depth_bounds()[0] for leg in legs)
    depth_optimistic = sum(leg.edge.depth_bounds()[1] for leg in legs)

    curls: dict[str, float] = {}
    for source in (SOURCE_DEXSCREENER, SOURCE_GECKOTERMINAL, SOURCE_CHAIN):
        value = curl_log([(leg.edge.prices.get(source, 0.0), leg.orientation) for leg in legs])
        if value is not None:
            curls[source] = value

    # The primary stays an aggregator, on purpose: the chain channel's `y/x` is exact only if the
    # vaults hold no unclaimed fees, which nothing here has verified. It is reported beside the
    # others as a control, not promoted over them.
    primary_source = SOURCE_DEXSCREENER if SOURCE_DEXSCREENER in curls else next(iter(curls), "")
    primary = curls.get(primary_source)
    spread = (
        abs(curls[SOURCE_DEXSCREENER] - curls[SOURCE_GECKOTERMINAL])
        if SOURCE_DEXSCREENER in curls and SOURCE_GECKOTERMINAL in curls
        else None
    )
    stamps = [
        leg.edge.extra.get("chain_price_t_event")
        for leg in legs
        if leg.edge.extra.get("chain_price_t_event")
    ]

    values: dict[str, Any] = {}
    verdict = "no_price"
    if primary is not None:
        notional_wide, profit_wide = arb_value_usd(primary, band, depth_pessimistic, gas_usd)
        notional_tight, profit_tight = arb_value_usd(primary, band, depth_optimistic, gas_usd)
        values = {
            "no_concentration": {"notional_usd": round(notional_wide, 2), "net_usd": round(profit_wide, 2)},
            "tight_dlmm_span": {"notional_usd": round(notional_tight, 2), "net_usd": round(profit_tight, 2)},
            "gas_usd": gas_usd,
            "note": (
                "net of the fee dead-zone, the ½C(ΔV)² depth cost on every leg, and gas. The "
                "interval is the unobservable DLMM concentration; a cycle with no DLMM leg has a "
                "degenerate one"
            ),
        }
        if spread is not None and spread > band:
            verdict = "unresolvable — sources disagree by more than the band"
        elif abs(primary) <= band:
            verdict = "inside the fee dead-zone — KVL holds, no current"
        elif profit_tight <= 0:
            verdict = "outside the fee band but uneconomic at any size"
        elif profit_wide <= 0:
            verdict = "economic ONLY under an assumed DLMM concentration — unmeasured"
        else:
            verdict = "outside the full band at both depth bounds"

    return {
        "name": " → ".join(names),
        "legs": [
            {
                "pool": leg.edge.pool,
                "label": leg.edge.label,
                "orientation": leg.orientation,
                "dex": leg.edge.dex,
                "element": leg.edge.element_type,
                "tvl_usd": round(leg.edge.tvl_usd, 2),
                "fee_bps": round(1e4 * leg.edge.fee.taker, 1),
                "fee_uncertain": leg.edge.fee.uncertain,
                "ours": None if leg.edge.ownership is None else leg.edge.ownership.get("is_ours"),
            }
            for leg in legs
        ],
        "curl_bps": {source: round(bps(value), 1) for source, value in curls.items()},
        "curl_primary_source": primary_source or None,
        "source_spread_bps": None if spread is None else round(bps(spread), 1),
        "chain_leg_event_times": sorted(stamps),
        "chain_channel_note": (
            "curl_bps.chain_state is built from pool STATE — constant-product vault ratios at the "
            "slots listed above, DLMM active bins — and its legs are stamped at different chain "
            "times, so it carries its own staleness rather than an aggregator's"
        ),
        "fee_band_bps": round(bps(band), 1),
        "full_band_bps": {
            "no_concentration": round(bps(full_band_log(band, depth_pessimistic, gas_usd)), 1),
            "tight_dlmm_span": round(bps(full_band_log(band, depth_optimistic, gas_usd)), 1),
        },
        "net_value_usd": values,
        "verdict": verdict,
        "diagnostic_only": True,
        "diagnostic_note": (
            "A curl residual is a STATE MEASUREMENT, not a trade signal. The largest residual "
            "measured in this cluster was worth $0.37-$9.86 per loop after depth and gas, and "
            "cross-source disagreement here reaches 15,493 bps against fee bands of 186-342 bps."
        ),
        "thinnest_leg_usd": round(min((leg.edge.tvl_usd for leg in legs), default=0.0), 2),
    }


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _warnings(
    edges: list[Edge], tape: TapeSnapshot | None, prices: PriceSnapshot, lp: LpSnapshot | None
) -> list[str]:
    notes: list[str] = []
    if tape is not None:
        if tape.read.partial_final_lines:
            notes.append(
                f"{tape.read.partial_final_lines} tape file(s) ended mid-line — the collector is "
                "writing right now; those partial rows were skipped, not parsed"
            )
        if tape.read.malformed_lines:
            notes.append(
                f"{tape.read.malformed_lines} malformed tape line(s) — NOT a write race, investigate"
            )
        unwatched = [e.label for e in edges if e.tape is not None and e.tape.watched_seconds <= 0]
        if unwatched:
            notes.append(
                "no watch coverage in the window for: "
                + ", ".join(unwatched)
                + " — their flow is unknown, not zero"
            )
        alarms = sum(e.tape.ingest_before_event_rows for e in edges if e.tape is not None)
        if alarms:
            notes.append(f"{alarms} row(s) have t_ingest before t_event — clock corruption, investigate")
    for edge in edges:
        check = edge.liquidity_cross_check
        aggregated = [
            value
            for key, value in check.items()
            if key in ("dexscreener_liquidity_usd", "geckoterminal_reserve_usd")
            and isinstance(value, (int, float))
        ]
        if edge.tvl_usd < 10.0 and any(value >= 100.0 for value in aggregated):
            notes.append(
                f"{edge.label} ({edge.pool[:6]}…): the vaults read {_money(edge.tvl_usd)} on chain "
                f"while aggregators still advertise up to {_money(max(aggregated))} — a DRAINED "
                "edge with a stale quote. Any residual through it is an aggregator artefact"
            )
        elif isinstance(check.get("disagreement_ratio"), (int, float)) and check["disagreement_ratio"] >= 2.0:
            notes.append(
                f"{edge.label}: TVL sources disagree by {check['disagreement_ratio']}x "
                f"(chosen {_money(edge.tvl_usd)} from {edge.tvl_source}) — capacitance is only as "
                "good as this number"
            )
    unwatched_ours = [
        e.label
        for e in edges
        if e.tape is None and e.ownership is not None and e.ownership.get("is_ours")
    ]
    if unwatched_ours:
        notes.append(
            "we hold LP on edge(s) the cluster tape does not watch at all: "
            + ", ".join(unwatched_ours)
            + " — no flow, no attempt rate and no reserve path exists for them until the "
            "collector's pool set includes them"
        )
    for error in prices.errors:
        notes.append(f"price feed: {error}")
    if lp is None or not lp.resolved:
        notes.append(
            "no LP wallet resolved — every edge's ownership is null (unknown), which is NOT the "
            "same as not ours. Pass --lp-wallet or set JOSHIBOT_LP_WALLET"
        )
    elif lp.provenance == "inferred_from_tape":
        notes.append(
            f"LP wallet {lp.wallet} was INFERRED from tape liquidity rows and confirmed to hold "
            "open positions; it is evidence, not a declaration by the operator"
        )
    assumed = [e.label for e in edges if e.fee.uncertain and e.is_dlmm]
    if assumed:
        notes.append(
            "DLMM fee assumed (pool config not served) on: "
            + ", ".join(assumed)
            + " — the fee band IS the result, so treat those cycles as swept, not measured"
        )
    return notes


def build_netmap(
    *,
    tape: TapeSnapshot | None,
    prices: PriceSnapshot,
    lp: LpSnapshot | None,
    gas_usd: float = DEFAULT_GAS_USD,
    now: datetime | None = None,
    specs: tuple[PoolSpec, ...] = CLUSTER_POOLS,
) -> dict[str, Any]:
    """The whole map, as one JSON-serialisable dict. No I/O, no network, no clock surprises."""

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    edges = [_cluster_edge(spec, prices, tape, lp) for spec in specs]
    edges.extend(_lp_only_edges(lp, prices, {spec.address for spec in specs}))
    cycles = _build_cycles(edges)

    return {
        "schema": SCHEMA,
        "generated_at": moment.isoformat(),
        "clocks": {
            "join_and_display": "event time (chain blockTime) for everything from the tape",
            "ingest_only": "aggregator quotes and LP API values carry no block time",
            "why": (
                "ingest order ran BACKWARDS against chain order at Spearman -0.77 on backfill; "
                "mixing the two clocks fabricates latencies"
            ),
        },
        "window": {
            "from_t_event": tape.window.start.isoformat() if tape else None,
            "to_t_event": tape.window.end.isoformat() if tape else None,
            "hours": round(tape.window.seconds / 3600.0, 3) if tape else None,
        },
        "config": {
            "gas_usd": gas_usd,
            "dlmm_span_bounds": [DLMM_SPAN_WIDE, DLMM_SPAN_TIGHT],
            "min_cycle_liquidity_usd": MIN_CYCLE_LIQUIDITY_USD,
        },
        "physics": {
            "capacitance": "C = w_x·w_y·TVL (TVL/4 at even weights) — liquidity sets CAPACITANCE",
            "fee": "back-to-back diode pair, dissipation f·|Φ| linear in flow — NOT I²R",
            "dlmm": "series battery-cell stack: C = ∞ inside a bin, 0 at a bin edge",
            "resistance": (
                "the only ohmic element is behavioural (arbitrageur response); it is the model's "
                "single free parameter and is NOT derivable from these three feeds"
            ),
        },
        "sources": {
            "cluster_tape": (
                {"root": tape.root, **tape.read.to_json(), "as_of": tape.now.isoformat()}
                if tape
                else {"status": "not read"}
            ),
            "prices": {
                "fetched_at": prices.fetched_at,
                "dexscreener_pools": len(prices.dexscreener),
                "geckoterminal_pools": len(prices.geckoterminal),
                "dlmm_pool_states": len(prices.dlmm),
                "errors": prices.errors,
            },
            "lp_meter": lp.to_json() if lp else {"status": "not read"},
        },
        "nodes": _nodes(edges, prices, lp),
        "edges": [_edge_json(edge, prices) for edge in edges],
        "cycles": [_cycle_json(legs, gas_usd) for legs in cycles],
        "warnings": _warnings(edges, tape, prices, lp),
    }
