"""The census orchestrator: phased, resumable, ledgered end to end (STUDY.md governs).

Usage (phases in order; every phase is idempotent and resumes from its receipts):

    uv run --offline python -m joshi_analysis.workability.census --root <scratch> discover
    ... stratify --quota 13
    ... permint
    ... callouts
    ... callout-tape
    ... measure
    ... interaction
    ... replay
    ... report
    ... status

No phase edits Rust, touches state/, or rebuilds anything: provider requests go through the
committed release binaries via ``reads``; ``measure`` onward is offline arithmetic.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

from joshi_analysis.scalplab.tape import LoadedTape, TapeError, load_tape

from . import FLAT_FLOOR_BPS, HARD_BUDGET_REQUESTS, STUDY_VERSION
from .budget import Ledger
from .callout import measure_entry_window
from .fees import venue_floor
from .interaction import decile_contrast, spearman_with_permutation
from .reads import (
    COMMUNITY_PACING_SECONDS,
    REPO,
    body_of_outcome,
    millis_of_iso,
    product_read,
    tape_walk,
    utc_of_millis,
)
from .sample import stratify
from .stats import outcome_statistics, split_events, window_statistics, windows_sufficient

GRID_REPLAY = REPO / "target" / "release" / "examples" / "grid_tape_replay"

SEED = 20260824
DISCOVERY_PAGES = 5
LIVE_PAGES = 3
SEARCH_TERMS = ("a", "e", "o", "i", "s", "t")
CALLOUT_TOP_MAX_MINTS = 80
COMMUNITY_MAX_MINTS = 50
CALLOUT_SEEK_MAX = 45
CANDLE_SUBSAMPLE_FRACTION = 0.5
WALK_PAGES = 3
CALLOUT_WINDOW_HOURS = 24

HYPOTHESIS = (
    "workability census control corpus: does selecting coins by a window-A statistic improve "
    "what the declared grid family extracts on window B, net of its own haircuts?"
)
KNOWN_FIRST = (
    "The declarer drew this mint by stratified seeded sample from the discovery surfaces and "
    "has seen only its enumeration row and walk receipts before this replay; window-A "
    "statistics were computed before any replay ran, and the selection rule is registered in "
    "workability/STUDY.md. The tape is a retrospective backfill with no live decision clock."
)

S_KEYS = (
    "S1_tier0_legs_ph",
    "S2_tier2_legs_ph",
    "S3_tier8_legs_ph",
    "S4_tier32_legs_ph",
    "S5_trades_ph",
    "S6_unique_traders_ph",
    "S7_trader_concentration",
    "S8_buy_imbalance",
    "S9_drift_slope_ph",
    "S10_log_range",
    "S11_intra_slot_share",
    "S12_callouts_in_A",
    "S13_log_mcap_proxy",
)
O_KEYS = ("O1_tier0_legs_ph", "O2_tier2_legs_ph", "O3_tier8_legs_ph", "O4_tier32_legs_ph")
PRIMARY_PAIRS = (("S4_tier32_legs_ph", "O4_tier32_legs_ph"), ("S5_trades_ph", "O4_tier32_legs_ph"))


def now_ms() -> int:
    return int(dt.datetime.now(dt.UTC).timestamp() * 1000)


def short(mint: str) -> str:
    return mint[:12]


def mint_dir(root: Path, mint: str) -> Path:
    return root / "mints" / mint


# --- phase: discover ----------------------------------------------------------------------------


def cmd_discover(ledger: Ledger, root: Path) -> None:
    """Enumerate the discovery surfaces. Every row is provider-asserted and read-time."""
    rows: dict[str, dict] = {}

    def keep(row: dict, source: str) -> None:
        mint = row.get("mint")
        if not mint or mint in rows:
            return
        rows[mint] = {
            "mint": mint,
            "source": source,
            "created_timestamp": row.get("created_timestamp"),
            "usd_market_cap": row.get("usd_market_cap"),
            "market_cap": row.get("market_cap"),
            "complete": row.get("complete"),
            "last_trade_timestamp": row.get("last_trade_timestamp"),
            "volume_1h_usd": row.get("volume_1h_usd"),
            "num_participants": row.get("num_participants"),
        }

    for sort in ("created_timestamp", "last_trade_timestamp"):
        for page in range(DISCOVERY_PAGES):
            result = product_read(
                ledger,
                root,
                f"disc_{sort[:7]}_p{page}",
                "discovery_coins",
                query={
                    "limit": "70",
                    "offset": str(page * 70),
                    "sort": sort,
                    "order": "DESC",
                },
            )
            for row in result.get("body") or []:
                keep(row, f"discovery_{sort}_p{page}")
    for page in range(LIVE_PAGES):
        result = product_read(
            ledger,
            root,
            f"live_p{page}",
            "currently_live",
            query={"limit": "60", "offset": str(page * 60)},
        )
        for row in result.get("body") or []:
            keep(row, f"currently_live_p{page}")
    for term in SEARCH_TERMS:
        result = product_read(
            ledger,
            root,
            f"search_{term}",
            "coin_search",
            query={"searchTerm": term, "limit": "100"},
        )
        for row in result.get("body") or []:
            keep(row, f"coin_search_{term}")
    out = root / "candidates.json"
    payload = {
        "study": STUDY_VERSION,
        "enumerated_at_ms": now_ms(),
        "n_distinct": len(rows),
        "bias_statement": (
            "these routes are product surfaces, not a census; the population represented is "
            "'coins the board would show an anonymous visitor now', and the coin_search rows "
            "are volume-ranked matches of 4 generic terms (biased, stated)"
        ),
        "rows": sorted(rows.values(), key=lambda r: str(r["mint"])),
    }
    out.write_text(json.dumps(payload, indent=1))
    print(f"{len(rows)} distinct mints -> {out}")


# --- phase: stratify ----------------------------------------------------------------------------


def cmd_stratify(root: Path, quota: int) -> None:
    candidates = json.loads((root / "candidates.json").read_text())
    census_instant = candidates["enumerated_at_ms"]
    draws = stratify(candidates["rows"], census_instant, quota, SEED)
    sampled: list[dict] = []
    by_mint = {row["mint"]: row for row in candidates["rows"]}
    for draw in draws:
        for mint in draw.drawn:
            sampled.append(
                {
                    "mint": mint,
                    "age": draw.age,
                    "mcap": draw.mcap,
                    "graduated_at_enumeration": draw.graduated,
                    "enumeration_row": by_mint[mint],
                }
            )
    manifest = {
        "study": STUDY_VERSION,
        "seed": SEED,
        "census_instant_ms": census_instant,
        "quota_per_cell": quota,
        "strata": [
            {
                "age": d.age,
                "mcap": d.mcap,
                "graduated": d.graduated,
                "quota": d.quota,
                "available": d.available,
                "drawn": len(d.drawn),
                "shortfall": d.shortfall,
            }
            for d in draws
        ],
        "n_sampled": len(sampled),
        "sampled": sampled,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1))
    filled = sum(1 for d in draws if d.available > 0)
    print(
        f"{len(sampled)} mints across {filled}/{len(draws)} populated cells "
        f"-> {root / 'manifest.json'}"
    )


# --- phase: permint -----------------------------------------------------------------------------


def in_candle_subsample(mint: str) -> bool:
    digest = hashlib.sha256(f"{SEED}:candles:{mint}".encode()).digest()
    return digest[0] < 256 * CANDLE_SUBSAMPLE_FRACTION


def cmd_permint(ledger: Ledger, root: Path, limit: int | None) -> None:
    manifest = json.loads((root / "manifest.json").read_text())
    sampled = manifest["sampled"][:limit] if limit else manifest["sampled"]
    walked = read = 0
    for item in sampled:
        mint = item["mint"]
        directory = mint_dir(root, mint)
        walk = tape_walk(
            ledger,
            directory / "state",
            directory,
            f"walk_{short(mint)}",
            mint,
            max_pages=WALK_PAGES,
        )
        if walk.get("receipt") is not None:
            walked += 1
        product_read(ledger, root, f"ce_{short(mint)}", "coin_exact", paths={"mint": mint})
        if in_candle_subsample(mint):
            product_read(
                ledger,
                root,
                f"cd_{short(mint)}",
                "candles",
                paths={"mint": mint},
                query={"interval": "1s", "limit": "1000", "currency": "SOL"},
            )
        read += 1
    print(f"permint: {read} mints processed, {walked} walks hold receipts")


# --- phase: callouts ----------------------------------------------------------------------------


def _recent_active_mints(root: Path, manifest: dict) -> list[str]:
    """Sampled mints ordered by walk-observed recency of their newest retained trade."""
    scored: list[tuple[int, str]] = []
    for item in manifest["sampled"]:
        mint = item["mint"]
        receipt_path = mint_dir(root, mint) / f"walk_{short(mint)}.receipt.json"
        if not receipt_path.exists():
            continue
        walk = json.loads(receipt_path.read_text()).get("walk", {})
        newest = walk.get("newestEventTime")
        if not newest:
            continue
        scored.append((millis_of_iso(newest), mint))
    scored.sort(reverse=True)
    return [mint for _, mint in scored]


def cmd_callouts(ledger: Ledger, root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text())
    census_instant = manifest["census_instant_ms"]
    horizon_ms = census_instant - CALLOUT_WINDOW_HOURS * 3_600_000
    active = _recent_active_mints(root, manifest)
    callouts: list[dict] = []
    for mint in active[:CALLOUT_TOP_MAX_MINTS]:
        result = product_read(
            ledger, root, f"ct_{short(mint)}", "callout_top", paths={"mint": mint},
            query={"limit": "50"},
        )
        body = result.get("body") or {}
        for row in body.get("callouts", []) if isinstance(body, dict) else []:
            created = row.get("createdAt")
            if isinstance(created, int | float) and created >= horizon_ms:
                callouts.append(
                    {
                        "calloutId": row.get("calloutId"),
                        "mint": mint,
                        "createdAt_ms": int(created),
                        "source_route": "callout_top",
                        "trust": result.get("trust"),
                        "clock": "occurrence_epoch_ms_provider_asserted",
                    }
                )
    for mint in active[:COMMUNITY_MAX_MINTS]:
        result = product_read(
            ledger,
            root,
            f"cc_{short(mint)}",
            "community_callouts",
            paths={"mint": mint},
            pacing_seconds=COMMUNITY_PACING_SECONDS,
        )
        body = result.get("body") or {}
        for row in body.get("callouts", []) if isinstance(body, dict) else []:
            created = row.get("createdAt")
            if not isinstance(created, str):
                continue
            try:
                created_ms = millis_of_iso(created)
            except ValueError:
                continue
            if created_ms >= horizon_ms:
                callouts.append(
                    {
                        "calloutId": row.get("id"),
                        "mint": mint,
                        "createdAt_ms": created_ms,
                        "source_route": "community_callouts",
                        "trust": result.get("trust"),  # retained_quarantined: no review exists
                        "clock": "occurrence_iso_us_provider_asserted",
                    }
                )
    deduped: dict[tuple, dict] = {}
    for row in callouts:
        deduped[(row["mint"], row["createdAt_ms"])] = row
    out = root / "callouts.json"
    out.write_text(
        json.dumps(
            {
                "window_hours": CALLOUT_WINDOW_HOURS,
                "horizon_ms": horizon_ms,
                "n": len(deduped),
                "confound": (
                    "createdAt is OCCURRENCE time on every callout route; availability is "
                    "unmeasured, so no number downstream separates reaction from cause"
                ),
                "rows": sorted(deduped.values(), key=lambda r: r["createdAt_ms"]),
            },
            indent=1,
        )
    )
    print(f"{len(deduped)} callouts within {CALLOUT_WINDOW_HOURS}h -> {out}")


def cmd_callout_tape(ledger: Ledger, root: Path) -> None:
    """Dedicated seek walks for callouts the per-mint tapes do not already cover."""
    plan = json.loads((root / "callouts.json").read_text())["rows"]
    walked = covered = 0
    for row in plan:
        if walked >= CALLOUT_SEEK_MAX:
            print(f"seek cap {CALLOUT_SEEK_MAX} reached; remaining callouts rely on permint tape")
            break
        mint = row["mint"]
        t0 = row["createdAt_ms"]
        receipt_path = mint_dir(root, mint) / f"walk_{short(mint)}.receipt.json"
        if receipt_path.exists():
            walk = json.loads(receipt_path.read_text()).get("walk", {})
            oldest, newest = walk.get("oldestEventTime"), walk.get("newestEventTime")
            if (
                oldest
                and newest
                and millis_of_iso(oldest) <= t0 - 300_000
                and millis_of_iso(newest) >= t0 + 1_800_000
            ):
                covered += 1
                continue
        tag = f"seek_{str(row.get('calloutId'))[:18]}"
        directory = root / "callout_tapes" / f"{mint}_{t0}"
        tape_walk(
            ledger,
            directory / "state",
            directory,
            tag,
            mint,
            seek=utc_of_millis(t0 + 30 * 60 * 1000),
            stop_before=utc_of_millis(t0 - 5 * 60 * 1000),
            max_pages=2,
        )
        walked += 1
    print(f"callout tape: {covered} already covered by permint walks, {walked} seek walks")


# --- phase: measure -----------------------------------------------------------------------------


def _load_mint_tape(directory: Path, mint: str) -> tuple[LoadedTape | None, str]:
    try:
        tape = load_tape(directory / "state")
    except TapeError as error:
        return None, f"tape_error: {error}"
    if mint not in tape.events_by_coin:
        held = ", ".join(m for m, _ in tape.provenance.coins[:3]) or "none"
        return tape, f"mint_absent_from_tape (holds: {held})"
    return tape, "ok"


def _coin_exact_facts(root: Path, mint: str) -> dict:
    outcome = root / "out" / f"ce_{short(mint)}.outcome.json"
    receipt = root / "out" / f"ce_{short(mint)}.receipt.json"
    facts: dict = {"present": False}
    if not outcome.exists():
        return facts
    body, _status = body_of_outcome(outcome)
    if not isinstance(body, dict):
        return facts
    trust = "unknown"
    if receipt.exists():
        trust = json.loads(receipt.read_text()).get("schemaTrustOutcome", "unknown")
    cap = body.get("market_cap")
    return {
        "present": True,
        "trust": trust,
        "complete": bool(body.get("complete")),
        "market_cap_sol": float(cap) if isinstance(cap, int | float) else None,
        "usd_market_cap": body.get("usd_market_cap"),
        "created_timestamp": body.get("created_timestamp"),
        "pump_swap_pool": body.get("pump_swap_pool"),
    }


def _candle_log_range(root: Path, mint: str) -> float | None:
    outcome = root / "out" / f"cd_{short(mint)}.outcome.json"
    if not outcome.exists():
        return None
    from math import log

    body, _status = body_of_outcome(outcome)
    rows = body if isinstance(body, list) else []
    highs = [float(r["high"]) for r in rows if isinstance(r, dict) and r.get("high")]
    lows = [float(r["low"]) for r in rows if isinstance(r, dict) and r.get("low")]
    if not highs or not lows or min(lows) <= 0:
        return None
    return log(max(highs)) - log(min(lows))


def cmd_measure(root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text())
    callout_rows = []
    callouts_path = root / "callouts.json"
    if callouts_path.exists():
        callout_rows = json.loads(callouts_path.read_text())["rows"]
    out_path = root / "measurements.jsonl"
    n_ok = n_insufficient = n_no_tape = 0
    with out_path.open("w") as sink:
        for item in manifest["sampled"]:
            mint = item["mint"]
            record: dict = {
                "mint": mint,
                "age": item["age"],
                "mcap": item["mcap"],
                "graduated_at_enumeration": item["graduated_at_enumeration"],
            }
            facts = _coin_exact_facts(root, mint)
            record["coin_exact"] = facts
            floor = venue_floor(
                bool(facts.get("complete")), facts.get("market_cap_sol")
            )
            record["floor_bps"] = floor.round_trip_bps
            record["floor_basis"] = floor.basis
            tape, status = _load_mint_tape(mint_dir(root, mint), mint)
            record["tape_status"] = status
            if tape is None or mint not in (tape.events_by_coin or {}):
                record["verdict"] = "NO_TAPE"
                n_no_tape += 1
                sink.write(json.dumps(record) + "\n")
                continue
            events = tape.events_by_coin[mint]
            provenance = tape.provenance
            record["tape"] = {
                "n_events": len(events),
                "arrival_clock": provenance.arrival_clock,
                "decision_clock": provenance.decision_clock_statement,
                "full_pages_without_overlap": provenance.full_pages_without_overlap,
            }
            venues = {event.venue for event in events}
            record["venues"] = sorted(venues)
            split = split_events(events)
            if split is None or not windows_sufficient(split):
                record["verdict"] = "INSUFFICIENT_WINDOWS"
                record["n_A"] = len(split.window_a) if split else 0
                record["n_B"] = len(split.window_b) if split else 0
                n_insufficient += 1
                sink.write(json.dumps(record) + "\n")
                continue
            record["split_instant_us"] = split.split_instant_us
            record["n_A"] = len(split.window_a)
            record["n_B"] = len(split.window_b)
            record["a_duration_hours"] = split.a_duration_hours
            record["b_duration_hours"] = split.b_duration_hours
            features = window_statistics(
                split.window_a, floor.round_trip_bps, split.a_duration_hours
            )
            outcomes = outcome_statistics(
                split.window_b, floor.round_trip_bps, split.b_duration_hours
            )
            flat_features = window_statistics(
                split.window_a, FLAT_FLOOR_BPS, split.a_duration_hours
            )
            flat_outcomes = outcome_statistics(
                split.window_b, FLAT_FLOOR_BPS, split.b_duration_hours
            )
            mint_callouts = [
                c
                for c in callout_rows
                if c["mint"] == mint and c["createdAt_ms"] * 1000 < split.split_instant_us
            ]
            has_callout_read = (root / "out" / f"ct_{short(mint)}.receipt.json").exists()
            features["S12_callouts_in_A"] = (
                float(len(mint_callouts)) if has_callout_read else None
            )
            record["A"] = features
            record["B"] = outcomes
            record["A_flat250"] = flat_features
            record["B_flat250"] = flat_outcomes
            record["candle_log_range_read_window"] = _candle_log_range(root, mint)
            record["verdict"] = "MEASURED"
            n_ok += 1
            sink.write(json.dumps(record) + "\n")
    print(
        f"measure: {n_ok} measured, {n_insufficient} insufficient windows, "
        f"{n_no_tape} without tape -> {out_path}"
    )
    _measure_callouts(root, callout_rows)


def _measure_callouts(root: Path, callout_rows: list[dict]) -> None:
    out_path = root / "callout_measures.jsonl"
    measured = missing = 0
    with out_path.open("w") as sink:
        for row in callout_rows:
            mint = row["mint"]
            t0 = row["createdAt_ms"]
            sources = [mint_dir(root, mint), root / "callout_tapes" / f"{mint}_{t0}"]
            events = None
            used = None
            for directory in sources:
                if not (directory / "state" / "catalog.sqlite").exists():
                    continue
                tape, _status = _load_mint_tape(directory, mint)
                if tape is not None and mint in tape.events_by_coin:
                    events = tape.events_by_coin[mint]
                    used = str(directory)
                    break
            if events is None:
                missing += 1
                continue
            facts = _coin_exact_facts(root, mint)
            floor = venue_floor(bool(facts.get("complete")), facts.get("market_cap_sol"))
            measure = measure_entry_window(events, t0, floor.round_trip_bps)
            if measure is None:
                missing += 1
                continue
            measured += 1
            sink.write(
                json.dumps(
                    {**row, **measure, "tape_dir": used, "floor_basis": floor.basis}
                )
                + "\n"
            )
    print(f"callout measure: {measured} windows, {missing} without covering tape -> {out_path}")


# --- phase: interaction -------------------------------------------------------------------------


def cmd_interaction(root: Path) -> None:
    records = [
        json.loads(line)
        for line in (root / "measurements.jsonl").open()
        if line.strip()
    ]
    measured = [r for r in records if r.get("verdict") == "MEASURED"]
    cells = []
    for s_key in S_KEYS:
        for o_key in O_KEYS:
            pairs = [
                (r["A"].get(s_key), r["B"].get(o_key))
                for r in measured
                if r["A"].get(s_key) is not None and r["B"].get(o_key) is not None
            ]
            xs = [float(a) for a, _ in pairs]
            ys = [float(b) for _, b in pairs]
            primary = (s_key, o_key) in PRIMARY_PAIRS
            digest = hashlib.sha256(f"{s_key}|{o_key}".encode()).digest()
            cell_seed = SEED + int.from_bytes(digest[:4], "big")
            result = spearman_with_permutation(xs, ys, seed=cell_seed)
            contrast = (
                decile_contrast(xs, ys, seed=SEED)
                if len(xs) >= 20
                else None
            )
            cells.append(
                {
                    "statistic": s_key,
                    "outcome": o_key,
                    "n": result.n,
                    "rho": result.rho,
                    "p_permutation": result.p_permutation,
                    "primary": primary,
                    "decile": (
                        {
                            "n_top": contrast.n_top,
                            "n_control": contrast.n_control,
                            "median_top": contrast.median_top,
                            "median_control": contrast.median_control,
                            "difference": contrast.difference,
                        }
                        if contrast
                        else None
                    ),
                }
            )
    n_tests = len(cells)
    alpha = 0.05
    bonferroni = alpha / n_tests if n_tests else None
    survivors = [
        c
        for c in cells
        if c["p_permutation"] is not None and bonferroni and c["p_permutation"] < bonferroni
    ]
    payload = {
        "study": STUDY_VERSION,
        "n_coins_measured": len(measured),
        "n_tests": n_tests,
        "bonferroni_threshold": bonferroni,
        "multiplicity_statement": (
            f"{n_tests} cells on {len(measured)} coins from one 72h window of one venue's "
            "product surface; only the two pre-named primary pairs are confirmatory, "
            "everything else is exploratory even below the Bonferroni line"
        ),
        "primary": [c for c in cells if c["primary"]],
        "bonferroni_survivors": survivors,
        "cells": cells,
    }
    (root / "interaction.json").write_text(json.dumps(payload, indent=1))
    print(
        f"interaction: {n_tests} cells over {len(measured)} coins, "
        f"{len(survivors)} below naive Bonferroni -> {root / 'interaction.json'}"
    )


# --- phase: replay ------------------------------------------------------------------------------


def _eligible_for_replay(record: dict) -> bool:
    return (
        record.get("verdict") == "MEASURED"
        and record.get("venues") == ["pump_amm"]
        and record["A"].get("S4_tier32_legs_ph") is not None
        and record.get("n_B", 0) >= 10  # the grid needs evaluable held-out events
    )


def cmd_replay(root: Path, limit: int | None) -> None:
    records = [
        json.loads(line)
        for line in (root / "measurements.jsonl").open()
        if line.strip()
    ]
    eligible = [r for r in records if _eligible_for_replay(r)]
    measured = [r for r in records if r.get("verdict") == "MEASURED"]
    if not eligible:
        (root / "replay.json").write_text(
            json.dumps(
                {
                    "verdict": "NO_ELIGIBLE_COINS",
                    "statement": (
                        f"0 of {len(measured)} measured coins were pure pump_amm tapes with a "
                        "defined S4; the committed polled-replay family derives only pump_amm "
                        "rows, so on this sample the harvest question is unanswerable by the "
                        "committed autostrats — a capability absence, stated as the result"
                    ),
                },
                indent=1,
            )
        )
        print("replay: no eligible coins; capability absence written to replay.json")
        return
    eligible.sort(key=lambda r: r["A"]["S4_tier32_legs_ph"], reverse=True)
    top_n = max(1, len(eligible) // 10)
    top = eligible[:top_n]
    rest = eligible[top_n:]
    generator = random.Random(SEED)
    control = generator.sample(rest, min(top_n, len(rest))) if rest else []
    chosen = [("top_decile_by_S4", r) for r in top] + [("random_control", r) for r in control]
    if limit:
        chosen = chosen[:limit]
    replay_dir = root / "replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for arm, record in chosen:
        mint = record["mint"]
        panel_path = replay_dir / f"{short(mint)}.panel.json"
        if not panel_path.exists():
            facts = record.get("coin_exact", {})
            cap = facts.get("market_cap_sol")
            # Declared schedule from the tier row the cap selects (worst-of-tables; the
            # tape is pump_amm by eligibility, so the ladder applies regardless of the
            # enumeration row's `complete`): first row (2, 93, 30); any higher row
            # (20, 5, 95). The derive falsifies a wrong declaration against the rows'
            # own legs, and the default row-fee candidates cover the ladder.
            first_row = venue_floor(True, cap).round_trip_bps == 250
            lp, protocol, creator = (2, 93, 30) if first_row else (20, 5, 95)
            cmd = [
                str(GRID_REPLAY),
                "--mint",
                mint,
                "--polled-root",
                str(mint_dir(root, mint) / "state"),
                "--hypothesis",
                HYPOTHESIS,
                "--known-first",
                KNOWN_FIRST,
                "--declared-by",
                "workability-census-deputy",
                "--fee-lp-bps",
                str(lp),
                "--fee-protocol-bps",
                str(protocol),
                "--fee-creator-bps",
                str(creator),
                "--out",
                str(panel_path),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
            if proc.returncode != 0:
                results.append(
                    {
                        "arm": arm,
                        "mint": mint,
                        "verdict": "REPLAY_REFUSED",
                        "error": proc.stderr.strip()[-400:],
                    }
                )
                continue
        panel = json.loads(panel_path.read_text())
        report = panel.get("heldOutReport", {})

        def bps(value: object) -> float | None:
            try:
                return float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        results.append(
            {
                "arm": arm,
                "mint": mint,
                "verdict": "REPLAYED",
                "S4_A": record["A"]["S4_tier32_legs_ph"],
                "held_out_net_bps": bps(report.get("heldOutNetBps")),
                "held_out_full_hold_bps": bps(report.get("heldOutFullHoldBps")),
                "held_out_half_hold_bps": bps(report.get("heldOutHalfHoldBps")),
                "first_window_net_bps": bps(report.get("firstWindowNetBps")),
                "split_instant_unix_ms": panel.get("splitInstantUnixMs"),
                "statement": report.get("statement"),
            }
        )
    top_nets = [
        r["held_out_net_bps"]
        for r in results
        if r["arm"] == "top_decile_by_S4" and r.get("held_out_net_bps") is not None
    ]
    control_nets = [
        r["held_out_net_bps"]
        for r in results
        if r["arm"] == "random_control" and r.get("held_out_net_bps") is not None
    ]
    from .interaction import median

    payload = {
        "study": STUDY_VERSION,
        "n_eligible": len(eligible),
        "n_measured": len(measured),
        "eligibility": "pump_amm-only tapes; the committed polled replay derives nothing else",
        "arms": {
            "top_decile_by_S4": {"n": len(top), "with_net": len(top_nets)},
            "random_control": {"n": len(control), "with_net": len(control_nets)},
        },
        "median_held_out_net_bps": {
            "top_decile": median(top_nets),
            "control": median(control_nets),
        },
        "oracle_note": (
            "held-out nets are oracle-window numbers on retrospective tapes; a live clock "
            "extracts strictly less"
        ),
        "results": results,
    }
    (root / "replay.json").write_text(json.dumps(payload, indent=1))
    print(
        f"replay: {len(results)} runs ({len(top_nets)} top nets, {len(control_nets)} control "
        f"nets) -> {root / 'replay.json'}"
    )


# --- phase: report ------------------------------------------------------------------------------


def cmd_report(root: Path, out_path: Path | None) -> None:
    from .report import render

    target = out_path or (root / "results.md")
    target.write_text(render(root))
    print(f"results -> {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=HARD_BUDGET_REQUESTS)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover")
    strat = sub.add_parser("stratify")
    strat.add_argument("--quota", type=int, default=13)
    permint = sub.add_parser("permint")
    permint.add_argument("--limit", type=int, default=None)
    sub.add_parser("callouts")
    sub.add_parser("callout-tape")
    sub.add_parser("measure")
    sub.add_parser("interaction")
    replay = sub.add_parser("replay")
    replay.add_argument("--limit", type=int, default=None)
    report = sub.add_parser("report")
    report.add_argument("--out", type=Path, default=None)
    sub.add_parser("status")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.root, args.budget)
    if args.command == "status":
        print(f"{ledger.spent()} of {ledger.budget} requests spent")
        for phase, count in sorted(ledger.by_phase().items()):
            print(f"  {phase}: {count}")
        return
    if args.command in ("discover", "permint", "callouts", "callout-tape"):
        from .reads import PRODUCT_READ, TRADES_BACKFILL

        for binary in (PRODUCT_READ, TRADES_BACKFILL):
            if not binary.exists():
                sys.exit(f"missing committed release binary {binary}")
    if args.command == "discover":
        cmd_discover(ledger, args.root)
    elif args.command == "stratify":
        cmd_stratify(args.root, args.quota)
    elif args.command == "permint":
        cmd_permint(ledger, args.root, args.limit)
    elif args.command == "callouts":
        cmd_callouts(ledger, args.root)
    elif args.command == "callout-tape":
        cmd_callout_tape(ledger, args.root)
    elif args.command == "measure":
        cmd_measure(args.root)
    elif args.command == "interaction":
        cmd_interaction(args.root)
    elif args.command == "replay":
        cmd_replay(args.root, args.limit)
    elif args.command == "report":
        cmd_report(args.root, args.out)


if __name__ == "__main__":
    main()
