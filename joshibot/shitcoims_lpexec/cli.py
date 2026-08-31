"""`python -m shitcoims_lpexec` -- status, plan, and the nosis-trim playbook.

DRY RUN IS THE DEFAULT OF EVERY PATH, INCLUDING THE ERROR PATHS. `--live` is one of three
gates and on its own does nothing; and even with all three open this version signs, verifies
and simulates but cannot broadcast, because `rpc.READ_METHODS` has no `sendTransaction` in
it. See `signer.py` for why that is deliberate rather than unfinished.

The acceptance run is `playbook` with no flags: it reads live chain state, plans the trim
and the ladder, prices the rent twice (our arithmetic and the SDK's, independently), builds
every transaction through the untrusted sidecar, refuses anything the allowlist does not
recognise, simulates each one against the current slot, and writes the reconciliation rows.
No key is required for any of that.
"""

from __future__ import annotations

import argparse
import contextlib
import math
import sys
import time
from pathlib import Path
from typing import Any

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from .allowlist import POOLS, pool_for
from .binmath import LAMPORTS_PER_SOL, deposit_bin_array_indexes
from .config import ConfigError, LpExecConfig, load_config
from .datapi import DataApiError, fetch_pool, fetch_portfolio
from .gate import ExecutionGate, write_arm
from .guard import (
    CU_LIMIT_SIMULATION_MULTIPLIER,
    LANDING_BID_CEILING_MICRO_LAMPORTS,
    LANDING_BID_FLOOR_MICRO_LAMPORTS,
    TransactionRefused,
    guard_transaction,
)
from .ledger import CHAIN_CLOCK, VENDOR_CLOCK, Ledger, day_spend, new_run_id
from .planner import BinHolding, LadderPlan, PlanRefused, TrimPlan, plan_ladder, plan_trim
from .rpc import HeliusRpc, RpcError
from .secrets import SecretError
from .sidecar import Sidecar, SidecarError

# Solana's per-transaction ceiling. Used ONLY as the probe limit: a simulation cannot
# report what a transaction consumes if it is killed before finishing, so the measuring pass
# asks for everything and the confirming pass asks for what was measured.
CU_PROBE_LIMIT = 1_400_000
# Nothing useful runs under this, and a limit below it is a typo rather than a saving.
CU_LIMIT_FLOOR = 30_000

NOSIS_WEAVE_POOL = "48z2a9zvV7rBrMvwn3kE7vbwwiroiaaHm4rx1RwtksRF"
NOSIS_SOL_POOL = "C889ex3M6dDecsxjAAudiLjhdeKgehbLm4zK9wV3nX8N"
DEFAULT_NOSIS_TARGET_USD = 200.0


def _rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def _sol(lamports: int, sol_price: float | None) -> str:
    sol = lamports / LAMPORTS_PER_SOL
    if sol_price is None:
        return f"{sol:.6f} SOL"
    return f"{sol:.6f} SOL (${sol * sol_price:,.2f})"


def _open_rpc(config: LpExecConfig) -> HeliusRpc:
    return HeliusRpc(key_file=config.helius_api_key_file, timeout=config.rpc_timeout_seconds)


def _sidecar(config: LpExecConfig, rpc_key: str) -> Sidecar:
    return Sidecar(directory=config.sidecar_dir, rpc_url=rpc_key)


def _rpc_url(config: LpExecConfig) -> str:
    from .secrets import read_secret_file

    key = read_secret_file(config.helius_api_key_file, required=True)
    return f"https://mainnet.helius-rpc.com/?api-key={key}"


# --------------------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------------------


def cmd_status(config: LpExecConfig, args: argparse.Namespace) -> int:
    gate = ExecutionGate(config, cli_live=args.live)
    status = gate.status()
    _rule("shitcoims_lpexec -- status")
    print(f"wallet          {config.wallet_address}")
    absent = "" if config.config_path.exists() else "  (absent: defaults)"
    print(f"config          {config.config_path}{absent}")
    print(f"mode            {status.mode}")
    for failure in status.failures:
        print(f"  gate open     {failure}")
    if status.live:
        print("  all three gates are satisfied")
    print()
    print(f"key file        {config.secret_key_file}  "
          + ("present" if config.secret_key_file.exists() else "ABSENT"))
    print(f"arm file        {config.execution.arm_file}  "
          + ("present" if config.execution.arm_file.exists() else "absent"))
    print(f"arm value       {gate.expected_arm_value}")
    print()
    print("caps")
    ex = config.execution
    print(f"  per tx        {ex.per_tx_max_sol_lamports / LAMPORTS_PER_SOL:.4f} SOL"
          f" / ${ex.per_tx_max_token_usd:,.0f} token")
    print(f"  per day       {ex.per_day_max_sol_lamports / LAMPORTS_PER_SOL:.4f} SOL"
          f" / ${ex.per_day_max_token_usd:,.0f} token")
    print(f"  rate          >= {ex.min_seconds_between_transactions:.1f}s apart,"
          f" <= {ex.max_transactions_per_day}/day")
    spend = day_spend(config.ledger_dir)
    print(
        f"  today used    {spend.sol_lamports / LAMPORTS_PER_SOL:.6f} SOL / "
        f"${spend.token_usd:,.2f} token over {spend.transactions} submitted transaction(s)"
    )
    print()
    print("BROADCAST: not implemented in this version. rpc.READ_METHODS has no sendTransaction;")
    print("           with every gate open this package signs, verifies and simulates only.")
    print()
    print(f"pools allowlisted ({len(POOLS)}):")
    for pool in POOLS.values():
        print(f"  {pool.address}  {pool.label:<18} bin step {pool.bin_step:>4}  {pool.note[:60]}")
    sidecar = _sidecar(config, "https://unused")
    ready, reason = sidecar.available()
    print()
    print(f"builder         {'ready' if ready else reason}")
    return 0


# --------------------------------------------------------------------------------------
# playbook
# --------------------------------------------------------------------------------------


def _read_position(sidecar: Sidecar, pool: str, user: str, position: str | None) -> dict[str, Any]:
    payload = sidecar.positions(pool, user)
    positions = payload.get("positions") or []
    if not positions:
        raise PlanRefused(f"wallet {user} holds no open position in pool {pool}")
    if position is None:
        if len(positions) > 1:
            raise PlanRefused(
                f"pool {pool} holds {len(positions)} positions; name one with --position"
            )
        return dict(positions[0])
    for entry in positions:
        if entry.get("address") == position:
            return dict(entry)
    raise PlanRefused(f"position {position} is not open in pool {pool}")


def _print_trim(plan: TrimPlan, sol_price: float | None) -> None:
    _rule(f"STEP 1 -- trim {plan.token_x_symbol} in {plan.pool}")
    print(f"position          {plan.position}")
    print(f"active bin        {plan.active_bin_id}   bin step {plan.bin_step}"
          f" ({plan.bin_step / 100:.2f}%/bin)")
    print(
        f"held              {plan.held_x_raw / 10 ** plan.decimals_x:,.6f} {plan.token_x_symbol} "
        f"= ${plan.held_x_usd:,.2f}  @ ${plan.price_x_usd:.10f}"
    )
    print(f"target            ${plan.target_x_usd:,.2f}")
    print(
        f"remove            {plan.remove_x_raw / 10 ** plan.decimals_x:,.6f} {plan.token_x_symbol} "
        f"= ${plan.remove_x_usd:,.2f}"
    )
    print(
        f"retained          {plan.retained_x_raw / 10 ** plan.decimals_x:,.6f} {plan.token_x_symbol} "
        f"= ${plan.retained_x_usd:,.2f}"
    )
    print()
    print("  removal steps (top-down: the far end of the range is the idle inventory)")
    for step in plan.steps:
        print(
            f"    bins {step.from_bin_id:>4}..{step.to_bin_id:<4} @ {step.bps / 100:>6.2f}%  "
            f"-> {step.expected_x_raw / 10 ** plan.decimals_x:>14,.2f} {plan.token_x_symbol}"
        )
        print(f"      {step.reason}")
    print()
    print(f"  rent            {plan.rent.describe(sol_price)}")
    for note in plan.notes:
        print(f"  note            {note}")


def _print_ladder(plan: LadderPlan, sol_price: float | None) -> None:
    _rule(f"STEP 2 -- one-sided ask ladder on {plan.label} ({plan.pool})")
    print(f"active bin        {plan.active_bin_id}   bin step {plan.bin_step}"
          f" ({plan.bin_step / 100:.2f}%/bin)")
    print(
        f"spot              {plan.spot_price_ui:.12f} {plan.token_y_symbol}/{plan.token_x_symbol}"
    )
    print(f"range             bins {plan.min_bin_id}..{plan.max_bin_id}"
          f"  ({len(plan.rungs)} rungs, reach +{plan.reach_pct:.2f}%)")
    print(
        f"deposit           {plan.deposit_x_raw / 10 ** plan.decimals_x:,.6f} {plan.token_x_symbol} "
        f"= ${plan.deposit_x_usd:,.2f}   (one-sided: no {plan.token_y_symbol} at risk)"
    )
    print()
    header = f"price {plan.token_y_symbol}/{plan.token_x_symbol}"
    print(f"  {'bin':>6}  {header:>22}  {'vs spot':>9}  {plan.token_x_symbol:>16}")
    for rung in plan.rungs:
        print(
            f"  {rung.bin_id:>6}  {rung.price_ui:>22.12f}  {rung.pct_above_spot:>8.2f}%  "
            f"{rung.amount_x_raw / 10 ** plan.decimals_x:>16,.2f}"
        )
    print()
    print(f"  rent            {plan.rent.describe(sol_price)}")
    print(f"  rent share      {plan.rent_share_of_deposit:.2%} of deployed value")
    for note in plan.notes:
        print(f"  note            {note}")
    if plan.alternatives:
        print("  widths considered (chosen: the cheapest non-refundable rent that reaches target)")
        for alt in plan.alternatives[:6]:
            print(
                f"    width {alt['width']:>3}  reach +{alt['reach_pct']:>6.2f}%  "
                f"new arrays {alt['new_bin_arrays']}  rent {alt['non_refundable_sol']:.6f} SOL"
            )



def _diagnose(logs: list[str]) -> tuple[str, int | None]:
    """Turn a simulation log tail into a sentence, and recover the DLMM CU number.

    An `InstructionError [n, {Custom: 1}]` is opaque; the log line above it is not. The one
    case worth naming precisely is a token-balance failure inside an otherwise-correct
    transaction: the DLMM instruction reports its own consumption before the CPI that fails,
    so a large number there is positive evidence that the bin range, the derived PDAs, the
    bin-array coverage and the account ordering are all right and only the inventory is
    missing. That distinction is the difference between "the plan is wrong" and "step 2 was
    dry-run before step 1 landed".
    """
    dlmm_cu: int | None = None
    for line in logs:
        if "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo consumed" in line:
            parts = line.split()
            with contextlib.suppress(ValueError, IndexError):
                dlmm_cu = int(parts[parts.index("consumed") + 1])
    joined = "\n".join(logs)
    if "insufficient funds" in joined:
        return (
            "insufficient token balance -- the wallet does not hold the deposit yet; this is "
            "the expected result of simulating step 2 before step 1 has landed",
            dlmm_cu,
        )
    if "exceeded CUs meter" in joined or "exceeded maximum number of instructions" in joined:
        return ("compute budget exhausted -- raise the CU limit and re-simulate", dlmm_cu)
    if "custom program error" in joined:
        return ("the program rejected the instruction; read the log tail", dlmm_cu)
    return ("simulation failed with no recognisable log signature", dlmm_cu)


def _guard_one(
    *,
    tag: str,
    label: str,
    encoded: str,
    rpc: HeliusRpc,
    owner: Pubkey,
    config: LpExecConfig,
    ledger: Ledger,
    expected_pools: list[str],
    expected_positions: list[str],
    extra_signers: list[str],
    pool: str,
    quiet: bool = False,
) -> Any:
    try:
        guarded = guard_transaction(
            encoded=encoded,
            owner=owner,
            account_data=rpc.account_data,
            max_priority_fee_lamports=config.execution.max_priority_fee_lamports,
            expected_pools=expected_pools,
            expected_positions=expected_positions,
            extra_signers=extra_signers,
        )
    except TransactionRefused as exc:
        print(f"  {tag}  REFUSED: {exc}")
        ledger.emit("guard", step=label, verdict="refused", reason=str(exc), pool=pool)
        ledger.defect(reason="guard_refused", detail={"step": label, "error": str(exc)})
        return None
    ledger.emit(
        "guard",
        step=label,
        verdict="pass",
        pool=pool,
        instructions=[ix.name for ix in guarded.instructions],
        pools_touched=sorted(guarded.pools_touched),
        positions_touched=sorted(guarded.positions_touched),
        cu_limit=guarded.compute_unit_limit,
        cu_price=guarded.compute_unit_price_micro_lamports,
        priority_fee_lamports=guarded.priority_fee_lamports,
    )
    if not quiet:
        print(f"  {tag}  guard PASS: {guarded.summary()}")
        print(
            f"      signers {guarded.transaction.message.header.num_required_signatures}, "
            f"bid {guarded.compute_unit_price_micro_lamports:,} uL/CU, "
            f"priority fee {guarded.priority_fee_lamports:,} lamports"
        )
    return guarded


def _build_guard_simulate(
    *,
    label: str,
    build: Any,
    rpc: HeliusRpc,
    owner: Pubkey,
    config: LpExecConfig,
    ledger: Ledger,
    expected_pools: list[str],
    expected_positions: list[str],
    extra_signers: list[str],
    intended: dict[str, Any],
    pool: str,
    cu_price: int,
) -> list[dict[str, Any]]:
    """Two passes, because the landing policy's CU rule needs a measurement to exist first.

    `studies/RESULT_execution_landing.md` sec.8: `limit = ceil(consumed x 1.15)`, static
    fallback 160,000. The fallback is a PumpSwap-swap number and it is far too small for a
    26-bin one-sided DLMM deposit -- the first live run of this playbook hit `exceeded CUs
    meter at BPF instruction` at 160k while consuming 134,757 in the DLMM instruction alone.
    A retry at the same limit would have failed identically, forever.

    So: build at the per-transaction ceiling and simulate to MEASURE, then rebuild at
    `ceil(measured x 1.15)` and simulate again to CONFIRM the sized transaction still
    succeeds. Two passes cost two simulations and remove a whole class of "it worked in the
    plan and died on chain". The confirming pass is what goes in the reconciliation row,
    because that is the transaction that would actually be sent.
    """
    outcomes: list[dict[str, Any]] = []
    probe = build(CU_PROBE_LIMIT)
    encoded_list = list(probe["transactions"])
    ledger.emit("build", step=label, pool=pool, transactions=len(encoded_list), pass_name="probe")
    print(f"  {label}: {len(encoded_list)} transaction(s)")

    measured: list[int] = []
    for index, encoded in enumerate(encoded_list):
        tag = f"{label}[{index + 1}/{len(encoded_list)}]"
        guarded = _guard_one(
            tag=tag,
            label=label,
            encoded=encoded,
            rpc=rpc,
            owner=owner,
            config=config,
            ledger=ledger,
            expected_pools=expected_pools,
            expected_positions=expected_positions,
            extra_signers=extra_signers,
            pool=pool,
        )
        if guarded is None:
            outcomes.append({"tag": tag, "refused": True})
            continue
        try:
            simulated = rpc.simulate(encoded, sig_verify=False)
        except RpcError as exc:
            print(f"      probe simulate FAILED to run: {exc}")
            ledger.defect(reason="simulate_transport", detail={"step": label, "error": str(exc)})
            outcomes.append({"tag": tag, "sim_error": str(exc)})
            continue
        units = simulated.get("units_consumed")
        err = simulated.get("err")
        if err is not None or not isinstance(units, int) or units <= 0:
            logs = simulated.get("logs") or []
            diagnosis, dlmm_cu = _diagnose(logs)
            print(f"      probe simulate err={err} at the {CU_PROBE_LIMIT:,} CU ceiling")
            print(f"      diagnosis: {diagnosis}")
            if dlmm_cu:
                print(
                    f"      the DLMM instruction itself consumed {dlmm_cu:,} CU before failing, "
                    "so the bin range, PDAs and account layout are all correct"
                )
            for line in logs[-5:]:
                print(f"        | {line}")
            ledger.emit(
                "simulate",
                step=label,
                pool=pool,
                pass_name="probe",
                err=str(err),
                units_consumed=units,
                dlmm_units_consumed=dlmm_cu,
                diagnosis=diagnosis,
                sequencing_artifact=diagnosis.startswith("insufficient token balance"),
                t_event_source=CHAIN_CLOCK,
                t_event_unix=time.time(),
            )
            ledger.reconcile(
                step=label,
                pool=pool,
                position=expected_positions[0] if expected_positions else None,
                intended=intended,
                simulated={
                    "err": str(err),
                    "diagnosis": diagnosis,
                    "dlmm_units_consumed": dlmm_cu,
                    "instructions": [ix.name for ix in guarded.instructions],
                },
                actual=None,
                divergence_class="pending",
                note=diagnosis,
                mode="dry_run",
            )
            outcomes.append({"tag": tag, "err": err, "units": units, "diagnosis": diagnosis})
            continue
        sized = max(CU_LIMIT_FLOOR, math.ceil(units * CU_LIMIT_SIMULATION_MULTIPLIER))
        measured.append(sized)
        print(f"      probe: {units:,} CU consumed -> sized limit {sized:,} (x1.15)")
        ledger.emit(
            "simulate",
            step=label,
            pool=pool,
            pass_name="probe",
            err=None,
            units_consumed=units,
            sized_cu_limit=sized,
            t_event_source=CHAIN_CLOCK,
            t_event_unix=time.time(),
        )

    if not measured:
        return outcomes

    final_limit = max(measured)
    confirm = build(final_limit)
    ledger.emit(
        "build", step=label, pool=pool, transactions=len(confirm["transactions"]), pass_name="confirm"
    )
    for index, encoded in enumerate(list(confirm["transactions"])):
        tag = f"{label}[{index + 1}] sized"
        guarded = _guard_one(
            tag=tag,
            label=label,
            encoded=encoded,
            rpc=rpc,
            owner=owner,
            config=config,
            ledger=ledger,
            expected_pools=expected_pools,
            expected_positions=expected_positions,
            extra_signers=extra_signers,
            pool=pool,
            quiet=True,
        )
        if guarded is None:
            outcomes.append({"tag": tag, "refused": True})
            continue
        try:
            simulated = rpc.simulate(encoded, sig_verify=False)
        except RpcError as exc:
            outcomes.append({"tag": tag, "sim_error": str(exc)})
            continue
        units = simulated.get("units_consumed")
        err = simulated.get("err")
        fee = guarded.priority_fee_lamports
        if err is None:
            print(
                f"      CONFIRMED at limit {guarded.compute_unit_limit:,}: {units:,} CU, "
                f"priority fee {fee:,} lamports (${fee / LAMPORTS_PER_SOL * 75.4:.4f} at $75/SOL)"
            )
        else:
            print(f"      sized simulate err={err}")
            for line in (simulated.get("logs") or [])[-4:]:
                print(f"        | {line}")
        ledger.emit(
            "simulate",
            step=label,
            pool=pool,
            pass_name="confirm",
            err=str(err) if err is not None else None,
            units_consumed=units,
            cu_limit=guarded.compute_unit_limit,
            cu_price=cu_price,
            priority_fee_lamports=fee,
            t_event_source=CHAIN_CLOCK,
            t_event_unix=time.time(),
        )
        ledger.reconcile(
            step=label,
            pool=pool,
            position=expected_positions[0] if expected_positions else None,
            intended=intended,
            simulated={
                "err": str(err) if err is not None else None,
                "units_consumed": units,
                "cu_limit": guarded.compute_unit_limit,
                "instructions": [ix.name for ix in guarded.instructions],
                "priority_fee_lamports": fee,
            },
            actual=None,
            divergence_class="pending",
            note="dry run: no transaction was submitted, so `actual` is null by construction",
            mode="dry_run",
        )
        outcomes.append({"tag": tag, "units": units, "err": err, "guarded": guarded})
    return outcomes


def cmd_playbook(config: LpExecConfig, args: argparse.Namespace) -> int:
    run_id = new_run_id()
    gate = ExecutionGate(config, cli_live=args.live)
    status = gate.status()

    _rule("shitcoims_lpexec -- nosis trim playbook (DRY RUN against live chain state)")
    print(f"run_id            {run_id}")
    print(f"mode              {status.describe()}")
    print("broadcast         NOT IMPLEMENTED (rpc.READ_METHODS has no sendTransaction)")

    ledger = Ledger(config.ledger_dir, run_id=run_id)
    ledger.emit("gate", mode=status.mode, failures=list(status.failures), command="playbook")
    ledger.heartbeat(stage="playbook_start", wallet=config.wallet_address)

    owner = Pubkey.from_string(config.wallet_address)
    try:
        rpc_url = _rpc_url(config)
    except SecretError as exc:
        print(f"\nCANNOT PROCEED: {exc}")
        ledger.defect(reason="helius_key", detail=str(exc))
        ledger.close()
        return 2

    sidecar = _sidecar(config, rpc_url)
    ready, reason = sidecar.available()
    if not ready:
        print(f"\nCANNOT PROCEED: {reason}")
        ledger.defect(reason="sidecar_unavailable", detail=reason)
        ledger.close()
        return 2

    rpc = _open_rpc(config)
    try:
        # ---- live state -------------------------------------------------------------
        _rule("LIVE STATE")
        sol_price: float | None = None
        nosis_price: float | None = None
        try:
            portfolio = fetch_portfolio(config.wallet_address)
            sol_price = portfolio.sol_price_usd
            print(f"portfolio         ${portfolio.total_value_usd or 0:,.2f} across"
                  f" {len(portfolio.positions)} position(s)")
            for position in portfolio.positions:
                print(
                    f"  {position.position_address}  {position.token_x_symbol}/{position.token_y_symbol} "
                    f"${position.total_value_usd or 0:,.2f}  bins"
                    f" {position.lower_bin_id}..{position.upper_bin_id}"
                )
            ledger.emit(
                "plan",
                step="portfolio",
                positions=len(portfolio.positions),
                total_usd=portfolio.total_value_usd,
                t_event_source=VENDOR_CLOCK,
                t_event_unix=time.time(),
            )
        except DataApiError as exc:
            print(f"  datapi unavailable: {exc}")
            ledger.defect(reason="datapi", detail=str(exc))

        source_pool = pool_for(args.pool)
        target_pool = pool_for(args.ladder_pool)

        try:
            source_state = fetch_pool(source_pool.address)
            target_state = fetch_pool(target_pool.address)
            nosis_price = source_state.token_x_price_usd
            sol_price = sol_price or target_state.token_y_price_usd
            print(f"\n{source_pool.label} pool   spot {source_state.current_price}")
            print(f"{target_pool.label} pool     spot {target_state.current_price}  "
                  f"reserves {target_state.token_x_amount:,.0f} X / {target_state.token_y_amount:,.4f} Y  "
                  f"fee/TVL 24h {target_state.fee_tvl_24h_pct or 0:.2f}%")
            if target_state.is_empty:
                print("  REFUSING the ladder venue: pool holds no liquidity;"
                      " an ask there is a post to an empty room")
                ledger.defect(reason="empty_ladder_pool", detail=target_pool.address)
                return 3
        except DataApiError as exc:
            print(f"  pool valuation unavailable: {exc}")
            ledger.defect(reason="datapi_pool", detail=str(exc))
            return 3

        if not nosis_price or not sol_price:
            print("\nCANNOT PROCEED: no live USD price for the token or for SOL")
            return 3

        # ---- chain-truth position read ----------------------------------------------
        raw_position = _read_position(sidecar, source_pool.address, config.wallet_address, args.position)
        chain_state = sidecar.pool_state(source_pool.address)
        bins = [
            BinHolding(
                bin_id=int(b["bin_id"]),
                price_per_token=float(b["price_per_token"]),
                amount_x_raw=int(b["x"]),
                amount_y_raw=int(b["y"]),
            )
            for b in raw_position["bins"]
        ]
        print(
            f"\nchain read        position {raw_position['address']} bins "
            f"{raw_position['lower_bin_id']}..{raw_position['upper_bin_id']}, active bin "
            f"{chain_state['active_bin_id']}"
        )

        # ---- plan the trim ----------------------------------------------------------
        trim = plan_trim(
            pool=source_pool.address,
            position=raw_position["address"],
            bins=bins,
            active_bin_id=int(chain_state["active_bin_id"]),
            bin_step=int(chain_state["bin_step"]),
            decimals_x=int(chain_state["token_x_decimals"]),
            price_x_usd=nosis_price,
            target_x_usd=args.target_usd,
            token_x_symbol="nosis",
        )
        _print_trim(trim, sol_price)
        ledger.emit(
            "plan",
            step="trim",
            pool=trim.pool,
            position=trim.position,
            held_x_raw=str(trim.held_x_raw),
            remove_x_raw=str(trim.remove_x_raw),
            retained_x_raw=str(trim.retained_x_raw),
            target_usd=trim.target_x_usd,
            bins=list(trim.removed_bin_ids),
        )
        ledger.emit(
            "rent",
            step="trim",
            pool=trim.pool,
            refundable_lamports=trim.rent.refundable,
            non_refundable_lamports=trim.rent.non_refundable,
            new_bin_arrays=list(trim.rent.new_bin_arrays),
        )

        # ---- plan the ladder --------------------------------------------------------
        ladder_chain = sidecar.pool_state(target_pool.address)
        ladder_active = int(ladder_chain["active_bin_id"])
        ladder_step = int(ladder_chain["bin_step"])
        probe_lower = ladder_active + 1
        probe_upper = probe_lower + args.max_width - 1
        # Probe the DEPOSIT set, not the geometric one: an add-liquidity instruction
        # initialises `max(index(upper), index(lower)+1)` even when the whole range fits in
        # one array, so a probe over the geometric set would report a virgin array as
        # already-paid-for and under-price the plan by 0.0714 SOL.
        existing = rpc.existing_bin_arrays(
            target_pool.address, list(deposit_bin_array_indexes(probe_lower, probe_upper))
        )
        ladder = plan_ladder(
            pool=target_pool.address,
            label=target_pool.label,
            active_bin_id=ladder_active,
            bin_step=ladder_step,
            decimals_x=int(ladder_chain["token_x_decimals"]),
            decimals_y=int(ladder_chain["token_y_decimals"]),
            deposit_x_raw=args.ladder_deposit_raw or trim.remove_x_raw,
            price_x_usd=nosis_price,
            sol_price_usd=sol_price,
            existing_bin_arrays=existing,
            reach_pct=args.reach_pct,
            token_x_symbol="nosis",
            token_y_symbol="SOL",
            max_width=args.max_width,
        )
        _print_ladder(ladder, sol_price)
        ledger.emit(
            "plan",
            step="ladder",
            pool=ladder.pool,
            min_bin_id=ladder.min_bin_id,
            max_bin_id=ladder.max_bin_id,
            deposit_x_raw=str(ladder.deposit_x_raw),
            deposit_usd=ladder.deposit_x_usd,
            reach_pct=ladder.reach_pct,
        )

        # ---- rent, cross-checked against the SDK ------------------------------------
        _rule("RENT -- two independent derivations")
        our_non_refundable = trim.rent.non_refundable + ladder.rent.non_refundable
        our_refundable = trim.rent.refundable + ladder.rent.refundable
        print(f"  ours (binmath)  refundable {_sol(our_refundable, sol_price)}, "
              f"NOT refundable {_sol(our_non_refundable, sol_price)}")
        try:
            sdk = sidecar.quote_rent(
                pool=target_pool.address, min_bin_id=ladder.min_bin_id, max_bin_id=ladder.max_bin_id
            )
            sdk_bin_array_lamports = round(float(sdk["bin_array_cost_sol"]) * LAMPORTS_PER_SOL)
            sdk_position_lamports = round(float(sdk["position_cost_sol"]) * LAMPORTS_PER_SOL)
            print(
                f"  SDK quote       {sdk['bin_arrays_to_create']} new bin array(s) = "
                f"{_sol(sdk_bin_array_lamports, sol_price)}; {sdk['position_count']} position(s) = "
                f"{_sol(sdk_position_lamports, sol_price)}"
            )
            agree = (
                sdk_bin_array_lamports == ladder.rent.bin_array_lamports
                and sdk_position_lamports == ladder.rent.position_lamports
            )
            verdict = "YES -- both derivations match exactly" if agree else "NO -- MISMATCH"
            print(f"  agreement       {verdict}")
            ledger.emit(
                "rent",
                step="ladder",
                pool=ladder.pool,
                refundable_lamports=ladder.rent.refundable,
                non_refundable_lamports=ladder.rent.non_refundable,
                new_bin_arrays=list(ladder.rent.new_bin_arrays),
                sdk_bin_array_lamports=sdk_bin_array_lamports,
                sdk_position_lamports=sdk_position_lamports,
                agrees_with_sdk=agree,
            )
            if not agree:
                print("  A rent disagreement is a modeling error, not a rounding artefact. Refusing.")
                ledger.defect(reason="rent_disagreement", detail={"sdk": sdk})
                return 4
        except SidecarError as exc:
            print(f"  SDK quote unavailable: {exc}")
            ledger.defect(reason="sdk_rent_quote", detail=str(exc))

        # ---- caps -------------------------------------------------------------------
        _rule("CAPS")
        total_sol = our_non_refundable + our_refundable
        spend = day_spend(config.ledger_dir)
        checks = [
            ("per-tx SOL", total_sol, config.execution.per_tx_max_sol_lamports, "lamports"),
            (
                "per-day SOL",
                total_sol + spend.sol_lamports,
                config.execution.per_day_max_sol_lamports,
                "lamports",
            ),
        ]
        token_moved = trim.remove_x_usd + ladder.deposit_x_usd
        breached = False
        for name, value, limit, unit in checks:
            ok = value <= limit
            breached = breached or not ok
            print(f"  {name:<14} {value:>16,} / {limit:>16,} {unit}  {'ok' if ok else 'BREACH'}")
        for name, usd, usd_limit in (
            ("per-tx token", trim.remove_x_usd, config.execution.per_tx_max_token_usd),
            ("per-day token", token_moved + spend.token_usd, config.execution.per_day_max_token_usd),
        ):
            ok = usd <= usd_limit
            breached = breached or not ok
            verdict = "ok" if ok else "BREACH"
            print(f"  {name:<14} ${usd:>15,.2f} / ${usd_limit:>15,.2f}         {verdict}")
        if breached:
            print("\n  A cap breach refuses the plan. Nothing further is built.")
            ledger.defect(reason="cap_breach", detail={"total_sol_lamports": total_sol})
            return 5

        # ---- build, guard, simulate -------------------------------------------------
        cu_price = max(
            LANDING_BID_FLOOR_MICRO_LAMPORTS,
            min(args.cu_price, LANDING_BID_CEILING_MICRO_LAMPORTS),
        )
        _rule("BUILD -> GUARD -> SIMULATE")
        print(f"landing bid       {cu_price:,} uL/CU (RESULT_execution_landing.md sec.8 clamp)")
        print(f"CU sizing         probe at {CU_PROBE_LIMIT:,}, then rebuild at"
              f" ceil(measured x {CU_LIMIT_SIMULATION_MULTIPLIER})\n")

        all_ok = True
        for step in trim.steps:
            label = f"remove bins {step.from_bin_id}..{step.to_bin_id} @ {step.bps}bps"

            def _build_remove(limit: int, _step: Any = step) -> dict[str, Any]:
                return sidecar.remove_liquidity(
                    pool=trim.pool,
                    user=config.wallet_address,
                    position=trim.position,
                    from_bin_id=_step.from_bin_id,
                    to_bin_id=_step.to_bin_id,
                    bps=_step.bps,
                    cu_limit=limit,
                    cu_price=cu_price,
                )

            outcomes = _build_guard_simulate(
                label=label,
                build=_build_remove,
                cu_price=cu_price,
                rpc=rpc,
                owner=owner,
                config=config,
                ledger=ledger,
                expected_pools=[trim.pool],
                expected_positions=[trim.position],
                extra_signers=[],
                intended={
                    "from_bin_id": step.from_bin_id,
                    "to_bin_id": step.to_bin_id,
                    "bps": step.bps,
                    "expected_x_raw": str(step.expected_x_raw),
                    "expected_y_raw": str(step.expected_y_raw),
                },
                pool=trim.pool,
            )
            all_ok = all_ok and bool(outcomes) and all(
                o.get("err") is None and not o.get("refused") for o in outcomes
            )

        # The ladder needs a fresh position account. Its keypair is generated HERE, on the
        # trusted side, and only its pubkey crosses to the builder -- see guard.py on why a
        # second signer is tolerated at all.
        position_keypair = Keypair()
        print(f"\n  new position key generated locally: {position_keypair.pubkey()}")
        label = f"ladder bins {ladder.min_bin_id}..{ladder.max_bin_id}"

        def _build_ladder(limit: int) -> dict[str, Any]:
            return sidecar.add_one_sided(
                pool=ladder.pool,
                user=config.wallet_address,
                position=str(position_keypair.pubkey()),
                min_bin_id=ladder.min_bin_id,
                max_bin_id=ladder.max_bin_id,
                total_x=ladder.deposit_x_raw,
                total_y=0,
                cu_limit=limit,
                cu_price=cu_price,
            )

        outcomes = _build_guard_simulate(
            label=label,
            build=_build_ladder,
            cu_price=cu_price,
            rpc=rpc,
            owner=owner,
            config=config,
            ledger=ledger,
            expected_pools=[ladder.pool],
            expected_positions=[str(position_keypair.pubkey())],
            extra_signers=[str(position_keypair.pubkey())],
            intended={
                "min_bin_id": ladder.min_bin_id,
                "max_bin_id": ladder.max_bin_id,
                "deposit_x_raw": str(ladder.deposit_x_raw),
                "rungs": len(ladder.rungs),
            },
            pool=ladder.pool,
        )
        ladder_ok = bool(outcomes) and all(
            o.get("err") is None and not o.get("refused") for o in outcomes
        )

        # NOTE: the ladder simulation runs BEFORE the trim has actually happened, so the
        # wallet does not yet hold the nosis it would deposit. An insufficient-funds error
        # here is the CORRECT result of simulating step 2 in isolation and is reported as
        # such rather than hidden -- it is the sequencing, not the plan, that produces it.
        if not ladder_ok:
            print(
                "\n  The ladder is simulated against a wallet that has not yet received the\n"
                "  trimmed nosis, because step 2 is being dry-run before step 1 lands. An\n"
                "  insufficient-funds error here is a SEQUENCING artefact of the single-pass\n"
                "  dry run, not a defect in the plan -- re-run after the trim confirms. Any\n"
                "  OTHER error is real and the ledger row records which it was."
            )

        _rule("SUMMARY")
        print(f"  trim            ${trim.remove_x_usd:,.2f} of nosis out of {source_pool.label}")
        print(f"  ladder          {len(ladder.rungs)} rungs, bins"
              f" {ladder.min_bin_id}..{ladder.max_bin_id}, +{ladder.reach_pct:.1f}% reach")
        print(f"  rent            {_sol(our_non_refundable, sol_price)} NOT refundable,"
              f" {_sol(our_refundable, sol_price)} refundable")
        print(f"  ledger          {config.ledger_dir} ({ledger.rows_written} rows, run_id {run_id})")
        print(f"  mode            {status.mode} -- nothing was submitted")
        ledger.heartbeat(
            stage="playbook_end", rows=ledger.rows_written, trim_ok=all_ok, ladder_ok=ladder_ok
        )
        return 0
    except (PlanRefused, SidecarError, RpcError, DataApiError, SecretError) as exc:
        print(f"\nREFUSED: {type(exc).__name__}: {exc}")
        ledger.defect(reason=type(exc).__name__, detail=str(exc))
        return 6
    finally:
        rpc.close()
        ledger.close()


# --------------------------------------------------------------------------------------
# arm / disarm
# --------------------------------------------------------------------------------------


def cmd_arm(config: LpExecConfig, args: argparse.Namespace) -> int:
    gate = ExecutionGate(config, cli_live=False)
    write_arm(config.execution.arm_file, gate.expected_arm_value)
    print(f"Armed lpexec at {config.execution.arm_file}")
    print("execution.enabled and --live are still required, and broadcast is still unimplemented.")
    return 0


def cmd_disarm(config: LpExecConfig, args: argparse.Namespace) -> int:
    config.execution.arm_file.unlink(missing_ok=True)
    print("Disarmed lpexec.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shitcoims_lpexec",
        description="LP-only Meteora DLMM execution for tha funds. Cannot swap; dry-run by default.",
    )
    parser.add_argument("--config", default=None, help="path to lpexec.yaml (default: ./lpexec.yaml)")
    parser.add_argument("--live", action="store_true", help="request live execution (needs all three gates)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="gates, caps, allowlist and builder readiness")

    play = sub.add_parser("playbook", help="plan + build + guard + simulate the nosis trim, dry run")
    play.add_argument("--pool", default=NOSIS_WEAVE_POOL, help="pool holding the position to trim")
    play.add_argument("--position", default=None, help="position address (inferred if the pool holds one)")
    play.add_argument("--ladder-pool", default=NOSIS_SOL_POOL, help="pool to post the ask ladder on")
    play.add_argument(
        "--target-usd", type=float, default=DEFAULT_NOSIS_TARGET_USD, help="exposure to leave"
    )
    play.add_argument(
        "--reach-pct", type=float, default=20.0, help="how far above spot the top rung sits"
    )
    play.add_argument(
        "--ladder-deposit-raw",
        type=int,
        default=None,
        help="override the ladder deposit in raw token units; use to re-prove the ladder "
        "simulation once the trim has landed and the wallet actually holds the nosis",
    )
    play.add_argument(
        "--max-width", type=int, default=26, help="ladder rungs (26 = one-transaction limit)"
    )
    play.add_argument(
        "--cu-price", type=int, default=LANDING_BID_FLOOR_MICRO_LAMPORTS, help="microlamports/CU bid"
    )

    sub.add_parser("arm", help="write the 0600 arm file for this wallet")
    sub.add_parser("disarm", help="remove the arm file")
    return parser


COMMANDS = {"status": cmd_status, "playbook": cmd_playbook, "arm": cmd_arm, "disarm": cmd_disarm}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    return COMMANDS[args.command](config, args)


if __name__ == "__main__":
    raise SystemExit(main())
