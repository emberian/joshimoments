"""``uv run python -m shitcoims_netmap.render [--json]`` — the desk's view of the circuit.

The drawing is a *view*: :func:`render_text` takes the assembled map and returns a string, and
it reads nothing the ``--json`` output does not carry. Two rules it enforces visually, because
they are the two ways this instrument could mislead someone:

- a **curl is never printed without its net-of-cost value** on the following line;
- an unmeasured absence is drawn ``— not watching``, a measured one ``0.0/h measured``, and the
  two never share a glyph.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shitcoims_cluster.pools import CLUSTER_POOLS
from shitcoims_netmap.assemble import build_netmap
from shitcoims_netmap.lp import collect_lp
from shitcoims_netmap.physics import DEFAULT_GAS_USD
from shitcoims_netmap.prices import fetch_prices
from shitcoims_netmap.tapefeed import (
    EVIDENCE_NOT_WATCHING,
    EVIDENCE_OBSERVED,
    EVIDENCE_OBSERVED_ZERO,
    read_tape,
)

RULE = "─" * 100


def _money(value: Any, places: int = 0) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"${value:,.{places}f}"


def _num(value: Any, places: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value:,.{places}f}"


def _signed_bps(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value:+,.0f}"


def _flow_cell(flow: dict[str, Any]) -> str:
    """One cell that can never conflate a measured zero with an unobserved one."""

    evidence = flow.get("evidence")
    if evidence == EVIDENCE_NOT_WATCHING:
        unwatched = flow.get("swaps_unwatched") or 0
        seen = f" ({unwatched} seen)" if unwatched else ""
        return f"— not watching{seen}"
    rate = flow.get("swaps_per_hour")
    unwatched = flow.get("swaps_unwatched") or 0
    extra = f" +{unwatched}u" if unwatched else ""
    if evidence == EVIDENCE_OBSERVED_ZERO:
        return f"0.0/h measured ({_num(flow.get('watched_seconds'), 0)}s){extra}"
    if evidence == EVIDENCE_OBSERVED:
        return f"{_num(rate, 1)}/h in {_num(flow.get('watched_seconds'), 0)}s{extra}"
    return "—"


def _ours_cell(ours: Any) -> str:
    if ours is None:
        return " ? "
    return " * " if ours.get("is_ours") else "   "


def render_text(netmap: dict[str, Any]) -> str:
    lines: list[str] = []
    window = netmap.get("window") or {}
    sources = netmap.get("sources") or {}
    tape_source = sources.get("cluster_tape") or {}
    lp_source = sources.get("lp_meter") or {}

    lines.append(RULE)
    lines.append("NETWORK MAP — the token cluster as a circuit (read-only; PROGRAM.md §8)")
    lines.append(RULE)
    lines.append(
        f"generated {netmap.get('generated_at')}   "
        f"event window {_num(window.get('hours'), 1)}h ending {window.get('to_t_event')}"
    )
    lines.append(
        f"tape {tape_source.get('root', '—')}: {tape_source.get('rows', 0):,} rows, "
        f"{tape_source.get('partial_final_lines', 0)} partial tail(s) skipped, "
        f"{tape_source.get('malformed_lines', 0)} malformed"
    )
    lines.append(
        f"LP meter: wallet {lp_source.get('wallet') or 'UNRESOLVED'} "
        f"[{lp_source.get('provenance')}]   "
        f"value {_money(lp_source.get('total_value_usd'), 2)}   "
        f"unclaimed {_money(lp_source.get('total_unclaimed_usd'), 2)}"
    )
    physics = netmap.get("physics") or {}
    lines.append(f"physics: {physics.get('capacitance')}")
    lines.append(f"         {physics.get('fee')}")
    lines.append("")

    lines.append("NODES — token = node, potential = ln(price)")
    lines.append(
        f"  {'symbol':<8}{'price USD':>14}  {'deg':>3} {'live':>4}  "
        f"{'our LP inventory':>22}  {'gross flow (window)':>19}  {'net charge':>12}"
    )
    for node in netmap.get("nodes", []):
        inventory = node.get("inventory") or {}
        units, usd = inventory.get("lp_units"), inventory.get("lp_usd")
        if units is None:
            held = "unknown (no LP wallet)"
        elif units:
            held = f"{units:,.0f} u ({_money(usd, 0)})"
        else:
            held = "none in LP"
        price = node.get("price_usd")
        price_text = f"{price:,.8f}" if isinstance(price, (int, float)) else "—"
        lines.append(
            f"  {node.get('symbol', ''):<8}{price_text:>14}  "
            f"{node.get('degree', 0):>3} {node.get('degree_live', 0):>4}  {held:>22}  "
            f"{_money(node.get('flow_usd_out_window'), 0):>19}  "
            f"{_money(node.get('net_charge_usd_window'), 0):>12}"
        )
    lines.append("  inventory is LP-only and therefore a LOWER BOUND: a spot balance needs an RPC read.")
    lines.append("")

    lines.append("EDGES — pool = element.  '*' = ours, ' ' = not ours, '?' = ownership unknown")
    lines.append(
        f"  ours {'pair':<13}{'venue':<9}{'element':<15}{'TVL':>9} {'C $/ln p':>14} {'fee bps':>8}  "
        f"{'flow (event time)':<30}{'fail':>5}"
    )
    for edge in netmap.get("edges", []):
        element = edge.get("element") or {}
        capacitance = element.get("capacitance_usd_per_log_price") or {}
        if "value" in capacitance:
            cap_text = _money(capacitance.get("value"), 0)
        else:
            cap_text = f"{_money(capacitance.get('low'), 0)}-{_money(capacitance.get('high'), 0)}"
        fee = edge.get("fee") or {}
        fee_text = f"{_num(fee.get('taker_bps'), 0)}{'?' if fee.get('uncertain') else ''}"
        attempts = edge.get("attempts") or {}
        rate = attempts.get("failed_attempt_rate")
        rate_text = f"{rate:.0%}" if isinstance(rate, (int, float)) else "—"
        element_text = "battery stack" if element.get("type") == "battery_cell_stack" else "capacitor"
        if not edge.get("in_cluster_universe"):
            element_text += " +"
        venue = "meteora" if edge.get("dex") == "meteora_dlmm" else "pumpswap"
        lines.append(
            f"  {_ours_cell(edge.get('ours'))} {edge.get('label', ''):<13}{venue:<9}{element_text:<15}"
            f"{_money(element.get('tvl_usd'), 0):>9} {cap_text:>14} {fee_text:>8}  "
            f"{_flow_cell(edge.get('flow') or {}):<30}{rate_text:>5}"
        )
    lines.append(
        "  battery stack = Meteora DLMM (C = ∞ inside a bin, 0 at an edge; the range is the "
        "unobservable span)"
    )
    lines.append(
        "  flow is measured only inside watch coverage; '+Nu' counts swaps seen OUTSIDE it — "
        "evidence of flow, never of absence"
    )
    lines.append(
        "  '+' = not in the on-chain-verified cluster universe;  '?' after a fee = assumed, not served"
    )
    lines.append("")

    lines.append("CHARGE STATE — ΔQ over the window and the displacement it implies (V = Q/C)")
    lines.append(
        f"  {'pair':<13}{'venue':<9}{'net ΔQ (quote leg)':>24}  {'implied ΔV':>11}   last vault read"
    )
    for edge in netmap.get("edges", []):
        charge = edge.get("charge")
        if not charge:
            continue
        quote_mint = (edge.get("quote") or {}).get("mint", "")
        delta = (charge.get("net_delta_units") or {}).get(quote_mint)
        displacement = charge.get("implied_displacement_bps")
        venue = "meteora" if edge.get("dex") == "meteora_dlmm" else "pumpswap"
        lines.append(
            f"  {edge.get('label', ''):<13}{venue:<9}"
            f"{_num(delta, 3):>18} {(edge.get('quote') or {}).get('symbol', ''):<5} "
            f"{(_signed_bps(displacement) + ' bps') if displacement is not None else '—':>11}   "
            f"{charge.get('last_reserves_t_event') or '—'}"
        )
    lines.append(
        "  ΔV is defined only where C is: a battery stack's coarse-grained C needs the "
        "unobservable bin span, so it stays blank there."
    )
    lines.append("")

    lines.append("OURS — the junctions we own (fee income is the diode drop collected on every crossing)")
    ours_rows = [e for e in netmap.get("edges", []) if (e.get("ours") or {}).get("is_ours")]
    if not ours_rows:
        lines.append("  none resolved")
    for edge in ours_rows:
        ours = edge.get("ours") or {}
        in_range = ours.get("in_range")
        range_text = "in range" if in_range else ("OUT OF RANGE" if in_range is False else "range unknown")
        rate = ours.get("fee_rate_per_day")
        rate_text = f"{rate:.2%}/day" if isinstance(rate, (int, float)) else "—"
        lines.append(
            f"  {edge.get('label', ''):<13}position {_money(ours.get('value_usd'), 2):>10}  "
            f"unclaimed {_money(ours.get('unclaimed_fees_usd'), 2):>8}  "
            f"lifetime {_money(ours.get('lifetime_fees_usd'), 2):>8}  {rate_text:>12}  {range_text}"
        )
    lines.append("")

    lines.append("CYCLES — curl = Σ oriented ln(price); the band is the diode dead-zone")
    for cycle in netmap.get("cycles", []):
        curls = cycle.get("curl_bps") or {}
        primary = cycle.get("curl_primary_source")
        short = {"dexscreener": "DS", "geckoterminal": "GT", "chain_state": "CHAIN"}
        parts = [f"{short.get(source, source[:2])} {_signed_bps(value)}" for source, value in curls.items()]
        lines.append(
            f"  {cycle.get('name', ''):<34} curl {' | '.join(parts) or '—'} bps   "
            f"band {_num(cycle.get('fee_band_bps'), 0)}   "
            f"spread {_num(cycle.get('source_spread_bps'), 0)}   (primary: {primary})"
        )
        values = cycle.get("net_value_usd") or {}
        wide = (values.get("no_concentration") or {}).get("net_usd")
        tight = (values.get("tight_dlmm_span") or {}).get("net_usd")
        lines.append(
            f"      net of fees+depth+gas: {_money(wide, 2)} (no concentration) … "
            f"{_money(tight, 2)} (tight DLMM span)   thinnest leg {_money(cycle.get('thinnest_leg_usd'), 0)}"
        )
        lines.append(f"      verdict: {cycle.get('verdict')}")
    lines.append("  a curl residual is a DIAGNOSTIC, not a trade signal — the value line is the whole story.")
    lines.append("")

    warnings = netmap.get("warnings") or []
    if warnings:
        lines.append("WARNINGS")
        for warning in warnings:
            lines.append(f"  ! {warning}")
    lines.append(RULE)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m shitcoims_netmap.render",
        description="Render the cluster as a circuit: nodes, edges, ours-vs-theirs, curl residuals.",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="emit the contract instead of the view"
    )
    parser.add_argument("--window-hours", type=float, default=24.0, help="event-time window for tape stats")
    parser.add_argument(
        "--gas-usd", type=float, default=DEFAULT_GAS_USD, help="atomic-route gas, for the full band"
    )
    parser.add_argument("--lp-wallet", default=None, help="wallet holding our DLMM positions")
    parser.add_argument(
        "--tape-dir", type=Path, default=None, help="cluster tape root (default: state/cluster_tape)"
    )
    parser.add_argument("--no-network", action="store_true", help="tape only; prices and LP feed are skipped")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.now(UTC)

    tape = read_tape(root=args.tape_dir, window_hours=args.window_hours, now=now)

    candidates: list[str] = []
    for pool_tape in tape.pools.values():
        for wallet, _count in pool_tape.lp_candidates.most_common():
            if wallet not in candidates:
                candidates.append(wallet)

    lp = None
    if not args.no_network:
        lp = collect_lp(
            wallet=args.lp_wallet,
            tape_candidates=candidates,
            now_epoch_seconds=time.time(),
        )

    addresses = [spec.address for spec in CLUSTER_POOLS]
    dlmm_addresses = [spec.address for spec in CLUSTER_POOLS if not spec.replay_sufficient_reserves]
    if lp is not None:
        for pool in lp.positions:
            if pool not in addresses:
                addresses.append(pool)
            if pool not in dlmm_addresses:
                dlmm_addresses.append(pool)

    if args.no_network:
        from shitcoims_netmap.prices import PriceSnapshot

        prices = PriceSnapshot(fetched_at=now.isoformat(), errors=["--no-network: no price feed read"])
    else:
        prices = fetch_prices(addresses, dlmm_addresses=dlmm_addresses, now=now)

    netmap = build_netmap(tape=tape, prices=prices, lp=lp, gas_usd=args.gas_usd, now=now)
    print(json.dumps(netmap, indent=1, sort_keys=True) if args.as_json else render_text(netmap))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
