"""Assembles the LP-desk panel from one retention directory, entirely offline.

Everything here replays ``rpc_log.jsonl`` — the acquisition already happened and was
retained; this module never opens a socket. The panel carries four sections:

1. the reconstruction (net versus gross on her actual history, with receipts);
2. the regime dial (fee intensity versus realized variance, windows attached);
3. the policy frontier (the declared ensemble over the dense retained tape);
4. the alert spec (what a keeper-side LP telemetry tap would watch, report only).
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

from . import dial as dial_mod
from . import frontier as frontier_mod
from .cadence import both_sides_calibration, oscillation_rows, shuffle_split
from .events import decode_transaction_events
from .layouts import (
    decode_bin_array_liquidity,
    decode_lb_pair,
    decode_oracle,
    decode_position_v2,
    position_composition,
)
from .reconstruct import PoolIdentity, build_ledger, reconstruct
from .vocabulary import (
    DESK_AUTHORITY,
    PANEL_CONTRACT,
    PROVIDER_CLAIM,
    RECONSTRUCTED_FROM_CHAIN,
)

__all__ = ["RetainedRun", "build_panel", "load_run"]

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WSOL_MINT = "So11111111111111111111111111111111111111112"


@dataclass
class RetainedRun:
    """The retention log, indexed for replay."""

    manifest: dict
    account_infos: dict[str, dict]  # address -> latest getAccountInfo response
    multiple_accounts: list[tuple[list[str], dict]]
    program_accounts: list[tuple[list, list]]
    signatures: dict[str, list[dict]]  # address -> concatenated pages, newest first
    transactions: dict[str, dict]  # signature -> getTransaction result
    received_unix_ms: dict[str, int]  # address -> when its account read was received


def load_run(retention_dir: Path) -> RetainedRun:
    manifest = json.loads((retention_dir / "manifest.json").read_text())
    run = RetainedRun(manifest, {}, [], [], {}, {}, {})
    with (retention_dir / "rpc_log.jsonl").open() as handle:
        for line in handle:
            row = json.loads(line)
            method = row.get("method")
            if method is None:
                continue
            params = row["params"]
            response = row["response"]
            if method == "getAccountInfo":
                result = response.get("result") or {}
                run.account_infos[params[0]] = result
                run.received_unix_ms[params[0]] = row["received_unix_ms"]
            elif method == "getMultipleAccounts":
                run.multiple_accounts.append((params[0], response.get("result") or {}))
            elif method == "getProgramAccounts":
                run.program_accounts.append((params, response.get("result") or []))
            elif method == "getSignaturesForAddress":
                run.signatures.setdefault(params[0], []).extend(
                    response.get("result") or []
                )
            elif method == "getTransaction":
                if params and params[0] == "batch":
                    for item in response.get("batch") or []:
                        result = item.get("result")
                        if result:
                            sig = result["transaction"]["signatures"][0]
                            run.transactions[sig] = result
                else:
                    result = response.get("result")
                    if result:
                        run.transactions[result["transaction"]["signatures"][0]] = result
    return run


def _mint_decimals(run: RetainedRun, mint: str) -> int:
    for addresses, result in run.multiple_accounts:
        if mint in addresses:
            value = (result.get("value") or [None] * len(addresses))[addresses.index(mint)]
            if value:
                return base64.b64decode(value["data"][0])[44]
    raise ValueError(f"mint {mint} was not retained; decimals unknowable offline")


def _pool_identity(run: RetainedRun, pool_address: str) -> tuple[PoolIdentity, object]:
    pair = decode_lb_pair(run.account_infos[pool_address]["value"], pool_address)
    x_decimals = _mint_decimals(run, pair.token_x_mint)
    y_decimals = _mint_decimals(run, pair.token_y_mint)
    if pair.token_y_mint == USDC_MINT:
        quote_is_y = True
    elif pair.token_x_mint == USDC_MINT:
        quote_is_y = False
    else:
        quote_is_y = True  # positional fallback; the panel names the mints regardless
    identity = PoolIdentity(
        address=pool_address,
        bin_step=pair.bin_step,
        token_x_mint=pair.token_x_mint,
        token_y_mint=pair.token_y_mint,
        reserve_x=pair.reserve_x,
        reserve_y=pair.reserve_y,
        x_decimals=x_decimals,
        y_decimals=y_decimals,
        quote_is_y=quote_is_y,
    )
    return identity, pair


def _swap_records(
    run: RetainedRun, identity: PoolIdentity, signatures: set[str]
) -> list[dial_mod.SwapRecord]:
    records = []
    for signature in signatures:
        transaction = run.transactions.get(signature)
        if transaction is None or (transaction.get("meta") or {}).get("err") is not None:
            continue
        for event in decode_transaction_events(transaction).events:
            name = event["event"]
            if name not in ("Swap", "Swap2Evt") or event["lb_pair"] != identity.address:
                continue
            end_bin = event["end_bin_id"]
            price = identity.quote_per_base_display(end_bin)
            if name == "Swap":
                lp_fee_atoms = event["fee"] - event["protocol_fee"] - event["host_fee"]
                fee_on_x = event["swap_for_y"]  # v1 charges the input token
                in_on_x = event["swap_for_y"]
            else:
                lp_fee_atoms = event["mm_fee"]
                fee_on_x = event["fees_on_token_x"]
                in_on_x = event["swap_for_y"]
            # value the fee and the volume in quote units at this swap's own end bin
            if fee_on_x:
                fee_quote = (Decimal(lp_fee_atoms) / Decimal(10) ** identity.x_decimals) * (
                    price if identity.quote_is_y else Decimal(1)
                )
            else:
                fee_quote = (Decimal(lp_fee_atoms) / Decimal(10) ** identity.y_decimals) * (
                    Decimal(1) if identity.quote_is_y else price
                )
            if in_on_x:
                volume_quote = (
                    Decimal(event["amount_in"]) / Decimal(10) ** identity.x_decimals
                ) * (price if identity.quote_is_y else Decimal(1))
            else:
                volume_quote = (
                    Decimal(event["amount_in"]) / Decimal(10) ** identity.y_decimals
                ) * (Decimal(1) if identity.quote_is_y else price)
            records.append(
                dial_mod.SwapRecord(
                    block_time=transaction.get("blockTime") or 0,
                    slot=transaction["slot"],
                    end_bin_id=end_bin,
                    fee_quote=fee_quote,
                    volume_quote=volume_quote,
                )
            )
    records.sort(key=lambda r: (r.block_time, r.slot))
    return records


def build_panel(retention_dir: Path, *, now_unix: int | None = None) -> dict:
    run = load_run(Path(retention_dir))
    manifest = run.manifest
    pool_address = manifest["pool"]
    wallet = manifest["wallet"]
    now = now_unix if now_unix is not None else int(time.time())

    identity, pair = _pool_identity(run, pool_address)

    # --- reconstruction --------------------------------------------------------------
    ledger = build_ledger(list(run.transactions.values()), identity, wallet)

    bin_arrays = []
    for params, rows in run.program_accounts:
        filters = params[1].get("filters") if len(params) > 1 else None
        if not filters or not any("dataSize" in f for f in filters):
            continue
        for row in rows:
            bin_arrays.append(decode_bin_array_liquidity(row["account"], row["pubkey"]))

    open_values: dict[str, tuple[int, int, int]] = {}
    pending = None
    position_notes = []
    open_positions = manifest.get("open_positions") or []
    for params, rows in run.program_accounts:
        filters = params[1].get("filters") if len(params) > 1 else None
        if not filters or any("dataSize" in f for f in filters):
            continue
        pend_x = pend_y = 0
        read_ms = manifest.get("finished_unix_ms") or manifest["started_unix_ms"]
        for row in rows:
            position = decode_position_v2(row["account"], row["pubkey"])
            x_atoms, y_atoms = position_composition(position, bin_arrays)
            open_values[row["pubkey"]] = (x_atoms, y_atoms, read_ms // 1000)
            pend_x += position.pending_fee_x_atoms_fixed_slots
            pend_y += position.pending_fee_y_atoms_fixed_slots
            position_notes.append(
                f"position {row['pubkey'][:8]}... bins {position.lower_bin_id}.."
                f"{position.upper_bin_id} ({position.bin_count()} bins), lifetime claimed "
                f"fees x={position.total_claimed_fee_x_atoms} "
                f"y={position.total_claimed_fee_y_atoms}"
            )
        if rows:
            pending = (pend_x, pend_y, read_ms // 1000)

    reconstruction = None
    reconstruction_error = None
    if ledger:
        try:
            reconstruction = reconstruct(
                ledger,
                identity,
                now_unix=now,
                open_position_values=open_values,
                pending_fees=pending,
                sol_is_base=WSOL_MINT in (identity.token_x_mint, identity.token_y_mint),
            )
        except ValueError as error:
            reconstruction_error = str(error)
    else:
        reconstruction_error = "no position-affecting transactions among the retained bodies"

    # --- the dense swap tape and the dial --------------------------------------------
    pool_sig_rows = run.signatures.get(pool_address, [])
    pool_sigs = {r["signature"] for r in pool_sig_rows}
    tape = _swap_records(run, identity, pool_sigs & set(run.transactions))

    active_id = manifest.get("active_id_at_fetch", pair.active_id)
    active_tvl = None
    for _, bins in bin_arrays:
        for bin_id, amount_x, amount_y, _supply in bins:
            if bin_id == active_id:
                active_tvl = identity.value_in_quote(amount_x, amount_y, bin_id)
    tvl_age = max(now - (manifest.get("finished_unix_ms", 0) // 1000), 0)

    oracle_address = (manifest.get("oracle") or {}).get("address")
    oracle_path: list[tuple[int, float]] = []
    if oracle_address and oracle_address in run.account_infos:
        observations = decode_oracle(
            run.account_infos[oracle_address]["value"], oracle_address
        )
        for earlier, later in pairwise(observations):
            span = later.last_updated_at - earlier.last_updated_at
            if span > 0:
                twa = (
                    later.cumulative_active_bin_id - earlier.cumulative_active_bin_id
                ) / span
                oracle_path.append((later.last_updated_at, twa))

    dial_reading = None
    dial_error = None
    oracle_sigma = None
    if len(oracle_path) >= 2:
        sigma2, span = dial_mod.sigma2_from_path(oracle_path, identity.bin_step)
        oracle_sigma = {
            "sigma2_per_day": sigma2,
            "window_s": span,
            "source": "oracle ring, time-weighted-average bin per observation interval; "
            "sparse observation understates the variance of a mean-reverting path",
        }
    if tape and active_tvl and active_tvl > 0:
        path = [(r.block_time, float(r.end_bin_id)) for r in tape]
        try:
            sigma2_dense, span_dense = dial_mod.sigma2_from_path(path, identity.bin_step)
            dial_reading = dial_mod.regime_dial(
                tape,
                bin_step=identity.bin_step,
                sigma2_per_day=sigma2_dense,
                sigma_source="dense retained swap window, end-bin path",
                sigma_window_s=span_dense,
                active_bin_tvl_quote=active_tvl,
                active_bin_tvl_age_s=tvl_age,
            )
        except ValueError as error:
            dial_error = str(error)
    else:
        dial_error = "tape or active-bin TVL missing; the dial declines to read"

    # --- the frontier ----------------------------------------------------------------
    frontier_panel = None
    frontier_oracle_panel = None
    frontier_error = None
    frontier_oracle_note = None
    pseudo_tape: list[dial_mod.SwapRecord] = []
    hoisted_cost_fraction = Decimal("0.0001")
    if tape and active_tvl and active_tvl > 0 and reconstruction is not None:
        tvl = reconstruction.time_weighted_deployed_quote
        recenters = (
            reconstruction.rebalance_transactions + reconstruction.withdraw_transactions
        )
        # Rent is recoverable and excluded; the per-recenter cost is the measured tx fee.
        per_recenter = reconstruction.tx_fees_quote / max(recenters, 1)
        cost_fraction = per_recenter / tvl if tvl > 0 else Decimal("0.0001")
        hoisted_cost_fraction = max(cost_fraction, Decimal(0))
        frontier_panel = frontier_mod.sweep(
            tape,
            bin_step=identity.bin_step,
            x_decimals=identity.x_decimals,
            y_decimals=identity.y_decimals,
            active_bin_tvl_quote=active_tvl,
            recenter_cost_fraction=max(cost_fraction, Decimal(0)),
        )
        # Second frontier: the oracle's much longer real price path with MODELED fees —
        # constant fee intensity calibrated on the dense window, spread over each oracle
        # interval. Real path, modeled flow; both statements travel with the panel.
        if len(oracle_path) >= 10 and dial_reading is not None:
            fee_per_s = dial_reading.fee_flow_quote_per_day / Decimal(86_400)
            pseudo = pseudo_tape
            prev_t: int | None = None
            for t, twa in oracle_path:
                fee = fee_per_s * Decimal(t - prev_t) if prev_t is not None else Decimal(0)
                pseudo.append(
                    dial_mod.SwapRecord(
                        block_time=t,
                        slot=t,
                        end_bin_id=round(twa),
                        fee_quote=fee,
                        volume_quote=Decimal(0),
                    )
                )
                prev_t = t
            frontier_oracle_panel = frontier_mod.sweep(
                pseudo,
                bin_step=identity.bin_step,
                x_decimals=identity.x_decimals,
                y_decimals=identity.y_decimals,
                active_bin_tvl_quote=active_tvl,
                recenter_cost_fraction=max(cost_fraction, Decimal(0)),
                min_dwells_s=(0, 300, 1800),
            )
            frontier_oracle_note = (
                "oracle-path frontier: the REAL active-bin path from the pool's oracle "
                "(time-weighted average bin per interval, rounded to whole bins) with "
                "MODELED fees — constant intensity calibrated on the dense window and "
                "spread over each interval. Averaging hides intra-interval excursions, so "
                "recenter counts here are floors and fee capture is smoothed."
            )
    else:
        frontier_error = "frontier needs the tape, the active-bin TVL, and her measured costs"

    # --- the measured calibration of the fee-capture model ---------------------------
    # The dial and the frontier price fee capture as (own dollars in active bin) / (one
    # static read of active-bin TVL). Her own books measure what she actually captured.
    # The ratio kappa binds the model to the operator: kappa << 1 means the static bin
    # read understates the liquidity actually competing for fills (JIT and intra-swap
    # depth the tape cannot see), and every model fee number scales by kappa while the
    # inventory-shift arithmetic stays exact.
    calibration = None
    if (
        dial_reading is not None
        and reconstruction is not None
        and reconstruction.gross_fee_rate_per_day is not None
    ):
        her_width = 6  # half-width in bins of her recentering 13-bin position
        # fee side scales exactly as 1/(2w+1); compute it at her width from the flow.
        model_fee_rate = float(
            dial_reading.fee_flow_quote_per_day / dial_reading.active_bin_tvl_quote
        ) / (2 * her_width + 1)
        if model_fee_rate:
            kappa = float(reconstruction.gross_fee_rate_per_day) / model_fee_rate
            calibration = {
                "herHalfWidthBins": her_width,
                "measuredGrossPerDay": str(reconstruction.gross_fee_rate_per_day),
                "modelFeeSidePerDayAtHerWidth": model_fee_rate,
                "kappa": kappa,
                "reading": (
                    "kappa is the measured-to-model fee-capture ratio; frontier and "
                    "dial fee numbers are model-priced and scale by kappa, while every "
                    "inventory-shift number is exact arithmetic on the path. A kappa "
                    "well under 1 says effective competing liquidity is ~1/kappa times "
                    "the static active-bin read."
                ),
            }

    # --- both-sides calibration: her "we hit both sides decently often", measured -----
    both_sides = None
    oscillation = None
    her_recenter_interval_s = None
    if reconstruction is not None:
        recenter_times = sorted(
            {e.block_time for e in ledger if e.kind in ("rebalance", "withdraw")}
        )
        gaps = [b - a for a, b in pairwise(recenter_times) if b > a]
        if gaps:
            gaps.sort()
            her_recenter_interval_s = gaps[len(gaps) // 2]
    if len(oracle_path) >= 10:
        both_sides = {
            "source": (
                "oracle path, time-weighted-average bin per interval: touch rates are "
                "FLOORS (intra-interval excursions are averaged away)"
            ),
            "window_s": oracle_path[-1][0] - oracle_path[0][0],
            "herMedianRecenterIntervalS": her_recenter_interval_s,
            "widths": [
                panel.as_dict()
                for panel in both_sides_calibration(
                    oracle_path,
                    widths=(1, 2, 3, 5, 6, 8, 13, 21),
                    horizons_s=(300, 900, 1800, 3600),
                )
            ],
        }
        oscillation = oscillation_rows(oracle_path, identity.bin_step)
    if tape and len(tape) >= 3 and both_sides is not None:
        both_sides["denseWindow"] = {
            "source": "dense swap tape, per-swap end bins: no averaging floor, short window",
            "window_s": tape[-1].block_time - tape[0].block_time,
            "widths": [
                panel.as_dict()
                for panel in both_sides_calibration(
                    [(r.block_time, float(r.end_bin_id)) for r in tape],
                    widths=(1, 2, 3, 5),
                    horizons_s=(15, 30, 60, 90),
                )
            ],
        }

    # --- shuffle versus full recenter, split and priced from the reconciled ledger ----
    shuffle = None
    if ledger:
        shuffle = shuffle_split(ledger, identity.value_in_quote).as_dict()

    # --- the frontier as a function of attention cadence, kappa-calibrated ------------
    attention_frontier = None
    shaped_frontier = None
    if pseudo_tape and calibration is not None:
        kappa = Decimal(str(calibration["kappa"]))

        def run_cell(cell, **kw):
            result = frontier_mod.simulate_policy(
                pseudo_tape,
                cell,
                bin_step=identity.bin_step,
                x_decimals=identity.x_decimals,
                y_decimals=identity.y_decimals,
                active_bin_tvl_quote=active_tvl,
                recenter_cost_fraction=hoisted_cost_fraction,
                **kw,
            )
            calibrated_net = (
                kappa * result.fees_quote
                + result.final_value_quote
                - result.recenter_cost_quote
                - Decimal(1)
            )
            return result, calibrated_net

        hodl_net = None
        rows = []
        widths = (1, 2, 3, 5, 6, 8)
        cadences: list[int | None] = [60, 300, 900, 3600, 14400, None]
        for cadence in cadences:
            for width in widths:
                cell = frontier_mod.PolicyCell(width, 0, 0, never_recenter=cadence is None)
                result, calibrated = run_cell(
                    cell, attention_interval_s=cadence if cadence is not None else None
                )
                if hodl_net is None:
                    p0 = identity.quote_per_base_display(pseudo_tape[0].end_bin_id)
                    p1 = identity.quote_per_base_display(pseudo_tape[-1].end_bin_id)
                    hodl_net = (Decimal(1) / 2 + Decimal(1) / 2 * p1 / p0) - Decimal(1)
                rows.append(
                    {
                        "cadence_s": cadence,
                        "halfWidthBins": width,
                        "calibratedNet": str(calibrated),
                        "modelFees": str(result.fees_quote),
                        "recenters": result.recenter_count,
                    }
                )
        wide_cell = frontier_mod.PolicyCell(34, 0, 0, never_recenter=True)
        _, wide_net = run_cell(wide_cell)
        best_by_cadence = {}
        for row in rows:
            key = row["cadence_s"]
            if key not in best_by_cadence or Decimal(row["calibratedNet"]) > Decimal(
                best_by_cadence[key]["calibratedNet"]
            ):
                best_by_cadence[key] = row
        crossover = None
        for cadence in cadences:
            if cadence is None:
                continue
            if Decimal(best_by_cadence[cadence]["calibratedNet"]) <= wide_net:
                crossover = cadence
                break
        attention_frontier = {
            "note": (
                "attended cells recenter only at the first event after each attention "
                "tick; kappa-calibrated fees, exact path arithmetic; the crossover is "
                "the fastest cadence at which the best attended-narrow cell no longer "
                "beats unattended-wide ON THIS WINDOW"
            ),
            "windowS": pseudo_tape[-1].block_time - pseudo_tape[0].block_time,
            "hodl5050Net": str(hodl_net),
            "unattendedWideNet_w34": str(wide_net),
            "bestByCadence": [best_by_cadence[c] for c in cadences],
            "allRows": rows,
            "crossoverCadenceS": crossover,
        }

        shaped_rows = []
        for width in (2, 3, 5, 6, 8):
            cell = frontier_mod.PolicyCell(width, 0, 0)
            _base_result, base_net = run_cell(cell)
            for shaping in (
                frontier_mod.CusumShaping(0.5, 3.0),
                frontier_mod.CusumShaping(0.5, 6.0),
            ):
                shaped_result, shaped_net = run_cell(cell, shaping=shaping)
                shaped_rows.append(
                    {
                        "halfWidthBins": width,
                        "shaping": shaping.name(),
                        "calibratedNet": str(shaped_net),
                        "symmetricNet": str(base_net),
                        "rescue": str(shaped_net - base_net),
                        "reshapes": shaped_result.reshape_count,
                        "recenters": shaped_result.recenter_count,
                    }
                )
        shaped_frontier = {
            "note": (
                "asymmetric shaping: CUSUM on bin increments (declared k, h in bins); "
                "the adverse side is withheld as trend-riding inventory earning no fees; "
                "every reshape pays one shuffle at the measured cost fraction. 'rescue' "
                "is shaped-minus-symmetric calibrated net for the same width"
            ),
            "rows": shaped_rows,
        }

    # --- the DAMM v2 arm: mechanism grounded, yield proxied, absence stated -----------
    damm_v2_arm = {
        "mechanism": (
            "DAMM v2 (cp-amm) is a constant-product pool: a position is a share of the "
            "whole curve — full-range by construction, nothing to recenter, no rent "
            "churn, no attention required. Its fee is base fee (schedulers: time, rate "
            "limit, market cap) PLUS a dynamic fee with the same volatility-accumulator "
            "family as the DLMM (max_volatility_accumulator, variable_fee_control, "
            "volatility_reference), capped at a max numerator."
        ),
        "mechanismProvenance": (
            "MeteoraAg/damm-v2 @ 2565067, programs/cp-amm/src/state/fee.rs, retained at "
            "analysis/fixtures/lpdesk/damm_v2_state_fee_2565067.rs"
        ),
        "proxy": (
            "the unattended-wide rows of the attention frontier (cadence None) are the "
            "measured PROXY for this arm on this pool's own path: full-range-like, "
            "never recentered, flat fee intensity. Direction of error: DAMM v2's dynamic "
            "fee RAISES the fee rate in high-sigma regimes (to a cap), so the flat-fee "
            "proxy UNDERSTATES a DAMM v2 position's fee take exactly when sigma is high, "
            "and slightly overstates it in quiet regimes if the base fee is lower."
        ),
        "absence": (
            "no measured DAMM v2 SOL/USDC yield: the dammv2 API did not answer "
            "(retained probes), and a chain-derived yield needs a fee-volume tape of a "
            "chosen DAMM v2 pool (~100 further requests) that this budget does not "
            "cover. That tape is the next bounded read if this arm matters."
        ),
    }

    # --- activity history from signature pages ---------------------------------------
    by_hour: dict[int, int] = {}
    for row in pool_sig_rows:
        block_time = row.get("blockTime")
        if block_time:
            by_hour[block_time // 3600] = by_hour.get(block_time // 3600, 0) + 1
    activity = [
        {"hour_unix": hour * 3600, "pool_transactions": count}
        for hour, count in sorted(by_hour.items())
    ]

    alert_spec = {
        "purpose": "what a keeper-side LP telemetry tap would watch; REPORT ONLY, nothing "
        "here is implemented outside analysis/",
        "signals": [
            {
                "name": "position_in_range",
                "watch": "LbPair.active_id vs the open position's [lower_bin_id, upper_bin_id]",
                "why": "out of range earns zero fees while still holding the shifted inventory",
                "source": "two account reads; both already decoded by this package",
            },
            {
                "name": "band_exit_duration",
                "watch": "seconds since active_id left the band, reset on re-entry",
                "why": "her policy is recenter-on-exit; the dwell is the policy variable "
                "the frontier sweeps",
            },
            {
                "name": "fee_accrual_stall",
                "watch": "pending fee atoms unchanged across N reads while in range",
                "why": "in-range with no accrual means flow died or liquidity crowded in; "
                "either way the narrow premise is decaying",
            },
            {
                "name": "regime_dial_threshold",
                "watch": "4*F*s/(T_a*sigma^2) from a rolling swap window and oracle path",
                "why": "the width-free worth-narrow gauge; alert on crossing 1 downward",
            },
            {
                "name": "volatility_freshness",
                "watch": "LbPair.volatility_last_update_unix_s age",
                "why": "bytes-level evidence of swap silence, no tape required",
            },
        ],
    }

    panel = {
        "contract": PANEL_CONTRACT,
        "authority": DESK_AUTHORITY,
        "generated_unix": now,
        "pool": {
            "address": pool_address,
            "bin_step": identity.bin_step,
            "base_fee_rate_per_1e9": pair.base_fee_rate_per_1e9(),
            "max_variable_fee_rate_per_1e9": pair.max_variable_fee_rate_per_1e9(),
            "token_x_mint": identity.token_x_mint,
            "token_y_mint": identity.token_y_mint,
            "active_id_at_fetch": active_id,
            "labels": {
                "provider": PROVIDER_CLAIM,
                "chain": RECONSTRUCTED_FROM_CHAIN,
                "note": "account bytes and transaction bodies as served by Helius RPC; "
                "amounts and events are chain-stated, service and ordering are the provider's",
            },
        },
        "reconstruction": (
            reconstruction.as_dict() if reconstruction else {"absent": reconstruction_error}
        ),
        "position_notes": position_notes,
        "open_positions": open_positions,
        "dial": dial_reading.as_dict() if dial_reading else {"absent": dial_error},
        "oracle_sigma": oracle_sigma or {"absent": "oracle path too short or unretained"},
        "frontier": (
            frontier_panel.as_dict() if frontier_panel else {"absent": frontier_error}
        ),
        "dial_calibration": calibration or {"absent": "needs both the dial and her books"},
        "both_sides": both_sides or {"absent": "oracle path too short"},
        "oscillation": oscillation or {"absent": "oracle path too short"},
        "shuffle_split": shuffle or {"absent": "no ledger"},
        "attention_frontier": attention_frontier
        or {"absent": "needs the pseudo tape and the kappa calibration"},
        "shaped_frontier": shaped_frontier
        or {"absent": "needs the pseudo tape and the kappa calibration"},
        "damm_v2_arm": damm_v2_arm,
        "frontier_oracle": (
            {"note": frontier_oracle_note, **frontier_oracle_panel.as_dict()}
            if frontier_oracle_panel
            else {"absent": "oracle path too short or dial absent"}
        ),
        "activity_by_hour": activity,
        "alert_spec": alert_spec,
        "retention": {
            "dir": str(retention_dir),
            "requests_spent": manifest.get("requests_spent"),
            "budget": manifest.get("budget"),
            "absences": manifest.get("absences"),
        },
    }
    return panel
