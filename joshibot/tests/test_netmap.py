"""Tests for the network map. Offline: every feed is a fixture, no socket is opened.

The five things worth breaking a build over, all of them corrections earned somewhere else in
this project:

1. ``C = TVL/4`` at even weights, and a DLMM's capacitance is an *interval* rather than a number.
2. The curl is compared against the diode dead-zone, and never reported without its net value.
3. "No flow" and "not watching" are different answers, and the tape can tell them apart.
4. The tape is appended to while it is read, so a half-written last line must not become a row
   and must not be counted as corruption either.
5. A DLMM edge is marked as a battery-cell stack and never as a capacitor.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from shitcoims_cluster.pools import CLUSTER_POOLS, DREGG, NOSIS, WEAVE, WSOL_MINT
from shitcoims_netmap.assemble import build_netmap
from shitcoims_netmap.lp import LpSnapshot, OurPosition, collect_lp
from shitcoims_netmap.physics import (
    DLMM_SPAN_TIGHT,
    DLMM_SPAN_WIDE,
    ELEMENT_BATTERY_STACK,
    ELEMENT_CAPACITOR,
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
from shitcoims_netmap.prices import DlmmState, PoolQuote, PriceSnapshot
from shitcoims_netmap.render import render_text
from shitcoims_netmap.tapefeed import (
    EVIDENCE_NOT_WATCHING,
    EVIDENCE_OBSERVED,
    EVIDENCE_OBSERVED_ZERO,
    ReadStats,
    read_jsonl,
    read_tape,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
WEAVE_SOL = "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn"
NOSIS_SOL = "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc"
DREGG_SOL = "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU"
WEAVE_NOSIS = "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD"


# ----------------------------------------------------------------------------------------
# 1. the capacitance identity
# ----------------------------------------------------------------------------------------


def test_capacitance_is_a_quarter_of_tvl_at_even_weights() -> None:
    assert capacitance_usd(40_000.0) == pytest.approx(10_000.0)
    assert capacitance_usd(57_414.0) == pytest.approx(57_414.0 / 4)


def test_capacitance_is_maximised_at_even_weights() -> None:
    """`C = w_x·w_y·TVL`: skewing the weights makes a pool LESS capacitive at its own price."""

    even = capacitance_usd(1_000.0, weight_base=0.5)
    for weight in (0.3, 0.8):
        assert capacitance_usd(1_000.0, weight_base=weight) == pytest.approx(
            weight * (1 - weight) * 1_000.0
        )
        assert capacitance_usd(1_000.0, weight_base=weight) < even


def test_dlmm_capacitance_is_an_interval_not_a_number() -> None:
    """A DLMM's span is unobservable from any keyless endpoint, so a point estimate is a lie."""

    low, high = dlmm_capacitance_bounds(800.0)
    assert low == pytest.approx(800.0 / DLMM_SPAN_WIDE)
    assert high == pytest.approx(800.0 / DLMM_SPAN_TIGHT)
    # The wide bound coincides exactly with constant product: no concentration assumed.
    assert low == pytest.approx(capacitance_usd(800.0))
    assert high / low == pytest.approx(DLMM_SPAN_WIDE / DLMM_SPAN_TIGHT)


def test_depth_term_is_the_inverse_capacitance_and_infinite_on_a_dead_pool() -> None:
    assert depth_term(1_000.0, span=4.0) == pytest.approx(1.0 / capacitance_usd(1_000.0))
    assert math.isinf(depth_term(0.0, span=4.0))


# ----------------------------------------------------------------------------------------
# 2. curl, the fee dead-zone, and the value that must travel with it
# ----------------------------------------------------------------------------------------


def test_curl_is_zero_on_a_consistent_triangle() -> None:
    """KVL: a consistent set of prices has no curl, whatever the numbers are."""

    p_ab, p_bc = 2.0, 3.0
    p_ca = 1.0 / (p_ab * p_bc)
    assert curl_log(((p_ab, 1), (p_bc, 1), (p_ca, 1))) == pytest.approx(0.0)


def test_curl_orientation_flips_sign() -> None:
    assert curl_log(((2.0, 1), (2.0, -1))) == pytest.approx(0.0)
    assert bps(curl_log(((1.01, 1), (1.0, -1)))) == pytest.approx(bps(math.log(1.01)), rel=1e-9)


def test_curl_is_none_when_a_leg_has_no_price() -> None:
    assert curl_log(((2.0, 1), (0.0, -1))) is None


def test_fee_band_is_the_sum_of_the_diode_drops() -> None:
    """Band edges ARE the fee sum, in log space: `Σ ln(1/(1-f))`."""

    fees = (pumpswap_fee(128_000.0), dlmm_fee(2.0, 0.0))
    expected = math.log(1 / (1 - 0.012)) + math.log(1 / (1 - 0.02))
    assert fee_band_log(fees) == pytest.approx(expected)
    assert bps(fee_band_log(fees)) == pytest.approx(1e4 * expected)


def test_fdv_ladder_moves_the_pumpswap_fee() -> None:
    assert pumpswap_fee(128_000.0).taker == pytest.approx(0.0025 + 0.0095)
    assert pumpswap_fee(500_000.0).taker == pytest.approx(0.0025 + 0.0060)
    assert pumpswap_fee(5_000_000.0).taker == pytest.approx(0.0025 + 0.0035)


def test_dlmm_fee_is_served_when_the_pool_config_is_and_flagged_when_it_is_not() -> None:
    served = dlmm_fee(6.0, 0.25)
    assert served.taker == pytest.approx(0.0625)
    assert served.uncertain is False
    assumed = dlmm_fee(None)
    assert assumed.uncertain is True


def test_full_band_exceeds_the_fee_band_by_the_gas_and_depth_term() -> None:
    band = fee_band_log((pumpswap_fee(128_000.0),))
    thin = full_band_log(band, depth_term(433.0, span=4.0), 0.30)
    deep = full_band_log(band, depth_term(57_000.0, span=4.0), 0.30)
    assert thin > deep > band
    # A thin pool does not create an arbitrage; it destroys one by making the loop uneconomic.


def test_arb_value_is_negative_inside_the_band_and_charges_gas_for_doing_nothing() -> None:
    band = fee_band_log((pumpswap_fee(128_000.0), pumpswap_fee(128_000.0)))
    notional, profit = arb_value_usd(band / 2, band, depth_term(50_000.0, span=4.0), 0.30)
    assert notional == 0.0
    assert profit == pytest.approx(-0.30)


def test_arb_value_scales_with_the_excess_over_the_band() -> None:
    band = fee_band_log((pumpswap_fee(128_000.0),))
    sum_depth = depth_term(50_000.0, span=4.0)
    _, small = arb_value_usd(band + 0.001, band, sum_depth, 0.0)
    _, large = arb_value_usd(band + 0.002, band, sum_depth, 0.0)
    assert large == pytest.approx(4 * small)  # profit is quadratic in the excess


# ----------------------------------------------------------------------------------------
# 3 & 4. the tape: watch windows, and being read mid-write
# ----------------------------------------------------------------------------------------


def _swap_row(pool: str, t_event: datetime, *, kind: str = "swap") -> dict:
    stamp = t_event.isoformat()
    return {
        "row_id": f"{pool}:{stamp}:{kind}",
        "kind": kind,
        "pool": pool,
        "dex": "pumpswap",
        "label": "weave/SOL",
        "t_event": stamp,
        "t_ingest": (t_event + timedelta(seconds=30)).isoformat(),
        "chain": {"slot": 1, "signature": "sig", "block_time": int(t_event.timestamp())},
        "counterparty": None,
        "fee_payer": "payer",
        "swap_legs": 1,
        "leg_names": ["buy"],
        "token_in_mint": WSOL_MINT,
        "token_in_raw": "1000000000",
        "token_out_mint": WEAVE,
        "token_out_raw": "5000000",
        "reserves": {
            "pool": pool,
            "dex": "pumpswap",
            "replay_sufficient": True,
            "vaults": [
                {
                    "account": "a",
                    "mint": WEAVE,
                    "decimals": 6,
                    "pre_raw": "1000000000",
                    "post_raw": "995000000",
                    "delta_raw": "-5000000",
                },
                {
                    "account": "b",
                    "mint": WSOL_MINT,
                    "decimals": 9,
                    "pre_raw": "100000000000",
                    "post_raw": "101000000000",
                    "delta_raw": "1000000000",
                },
            ],
        },
    }


def _attempt_row(pool: str, t_event: datetime) -> dict:
    stamp = t_event.isoformat()
    return {
        "row_id": f"{pool}:{stamp}:attempt",
        "kind": "attempt",
        "pool": pool,
        "dex": "pumpswap",
        "label": "weave/SOL",
        "t_event": stamp,
        "t_ingest": stamp,
        "chain": {"slot": 1, "signature": "sig2", "block_time": int(t_event.timestamp())},
        "error": "{'InstructionError': [3, {'Custom': 6004}]}",
    }


def _write_rows(
    root: Path, stream: str, pool: str, day: datetime, rows: list[dict], *, tail: str = ""
) -> Path:
    path = root / stream / f"{pool}-{day.strftime('%Y%m%d')}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows) + tail
    path.write_text(body, encoding="utf-8")
    return path


def _watch_rows(
    pool: str, opened: datetime, *, closed: datetime | None = None, poll: float = 20.0
) -> list[dict]:
    window = {
        "mint": pool,
        "opened_at": opened.isoformat(),
        "deadline": (opened + timedelta(days=1)).isoformat(),
    }
    rows = [
        {
            "kind": "watch_open",
            "pool": pool,
            "poll_interval_seconds": poll,
            "gap_factor": 2.0,
            "window": dict(window),
        }
    ]
    if closed is not None:
        rows.append(
            {
                "kind": "watch_close",
                "pool": pool,
                "polls": 3,
                "gaps": 0,
                "window": {**window, "closed_at": closed.isoformat(), "close_reason": "deadline"},
            }
        )
    return rows


def test_absence_inside_a_watch_window_is_a_measured_zero(tmp_path: Path) -> None:
    opened = NOW - timedelta(hours=2)
    _write_rows(tmp_path, "watch", WEAVE_SOL, opened, _watch_rows(WEAVE_SOL, opened))
    snapshot = read_tape(root=tmp_path, window_hours=6.0, now=NOW, pools=[_spec(WEAVE_SOL)])
    pool = snapshot.pools[WEAVE_SOL]

    assert pool.evidence == EVIDENCE_OBSERVED_ZERO
    assert pool.swaps_per_hour == 0.0
    # Coverage runs to now minus one poll interval: chain time newer than the last poll has not
    # been asked about, and claiming it would fabricate a zero at the leading edge.
    assert pool.watched_seconds == pytest.approx(2 * 3600 - 20.0)


def test_absence_outside_a_watch_window_is_not_a_zero(tmp_path: Path) -> None:
    """No watch rows at all: the collector was not looking, and the rate is None, not 0."""

    _write_rows(tmp_path, "swaps", WEAVE_SOL, NOW, [_swap_row(WEAVE_SOL, NOW - timedelta(hours=3))])
    snapshot = read_tape(root=tmp_path, window_hours=6.0, now=NOW, pools=[_spec(WEAVE_SOL)])
    pool = snapshot.pools[WEAVE_SOL]

    assert pool.evidence == EVIDENCE_NOT_WATCHING
    assert pool.swaps_per_hour is None
    assert pool.watched_seconds == 0.0
    # Presence is still evidence: the swap happened, it just licenses no claim about absence.
    assert pool.swaps == 1
    assert pool.swaps_unwatched == 1


def test_flow_rate_is_measured_only_over_watched_seconds(tmp_path: Path) -> None:
    opened = NOW - timedelta(hours=1)
    _write_rows(tmp_path, "watch", WEAVE_SOL, opened, _watch_rows(WEAVE_SOL, opened))
    rows = [
        _swap_row(WEAVE_SOL, NOW - timedelta(minutes=30)),
        _swap_row(WEAVE_SOL, NOW - timedelta(minutes=20)),
        _swap_row(WEAVE_SOL, NOW - timedelta(hours=4)),  # before the window opened
    ]
    _write_rows(tmp_path, "swaps", WEAVE_SOL, NOW, rows)
    snapshot = read_tape(root=tmp_path, window_hours=6.0, now=NOW, pools=[_spec(WEAVE_SOL)])
    pool = snapshot.pools[WEAVE_SOL]

    assert pool.evidence == EVIDENCE_OBSERVED
    assert pool.swaps == 3
    assert pool.swaps_watched == 2
    assert pool.swaps_unwatched == 1
    assert pool.swaps_per_hour == pytest.approx(2 * 3600.0 / pool.watched_seconds)


def test_a_gap_row_removes_coverage_rather_than_zero_filling_it(tmp_path: Path) -> None:
    opened = NOW - timedelta(hours=2)
    rows = _watch_rows(WEAVE_SOL, opened)
    rows.append(
        {
            "kind": "gap",
            "pool": WEAVE_SOL,
            "started_at": (NOW - timedelta(hours=2)).isoformat(),
            "ended_at": (NOW - timedelta(hours=1)).isoformat(),
            "seconds": 3600.0,
            "reason": "collector_not_running",
            "poll_interval_seconds": 20.0,
        }
    )
    _write_rows(tmp_path, "watch", WEAVE_SOL, opened, rows)
    snapshot = read_tape(root=tmp_path, window_hours=6.0, now=NOW, pools=[_spec(WEAVE_SOL)])
    pool = snapshot.pools[WEAVE_SOL]

    assert pool.watched_seconds == pytest.approx(3600.0 - 20.0)
    assert pool.gap_seconds == pytest.approx(3600.0)


def test_failed_attempt_rate_excludes_router_references(tmp_path: Path) -> None:
    opened = NOW - timedelta(hours=1)
    _write_rows(tmp_path, "watch", WEAVE_SOL, opened, _watch_rows(WEAVE_SOL, opened))
    rows = [
        _swap_row(WEAVE_SOL, NOW - timedelta(minutes=30)),
        _swap_row(WEAVE_SOL, NOW - timedelta(minutes=29), kind="reference"),
        _attempt_row(WEAVE_SOL, NOW - timedelta(minutes=28)),
        _attempt_row(WEAVE_SOL, NOW - timedelta(minutes=27)),
        _attempt_row(WEAVE_SOL, NOW - timedelta(minutes=26)),
    ]
    _write_rows(tmp_path, "swaps", WEAVE_SOL, NOW, rows)
    pool = read_tape(root=tmp_path, window_hours=6.0, now=NOW, pools=[_spec(WEAVE_SOL)]).pools[WEAVE_SOL]

    assert pool.references == 1
    assert pool.failed_attempt_rate == pytest.approx(3 / 4)


def test_a_half_written_last_line_is_skipped_and_not_called_corruption(tmp_path: Path) -> None:
    """The collector holds the handle open; an unterminated tail is a race, not a defect."""

    partial = json.dumps(_swap_row(WEAVE_SOL, NOW - timedelta(minutes=5)))[:60]
    path = _write_rows(
        tmp_path, "swaps", WEAVE_SOL, NOW, [_swap_row(WEAVE_SOL, NOW - timedelta(minutes=10))], tail=partial
    )
    stats = ReadStats()
    rows = list(read_jsonl(path, stats))

    assert len(rows) == 1
    assert stats.partial_final_lines == 1
    assert stats.malformed_lines == 0


def test_a_malformed_interior_line_is_counted_as_malformed(tmp_path: Path) -> None:
    path = tmp_path / "swaps" / f"{WEAVE_SOL}-20260813.jsonl"
    path.parent.mkdir(parents=True)
    good = json.dumps(_swap_row(WEAVE_SOL, NOW - timedelta(minutes=10)))
    path.write_text(f"{good}\n{{not json\n{good}\n", encoding="utf-8")
    stats = ReadStats()
    rows = list(read_jsonl(path, stats))

    assert len(rows) == 2
    assert stats.malformed_lines == 1
    assert stats.partial_final_lines == 0


def test_a_partial_tail_does_not_break_the_whole_read(tmp_path: Path) -> None:
    opened = NOW - timedelta(hours=1)
    _write_rows(tmp_path, "watch", WEAVE_SOL, opened, _watch_rows(WEAVE_SOL, opened))
    _write_rows(
        tmp_path,
        "swaps",
        WEAVE_SOL,
        NOW,
        [_swap_row(WEAVE_SOL, NOW - timedelta(minutes=30))],
        tail='{"kind":"swap","pool":"GA1n',
    )
    snapshot = read_tape(root=tmp_path, window_hours=6.0, now=NOW, pools=[_spec(WEAVE_SOL)])

    assert snapshot.pools[WEAVE_SOL].swaps == 1
    assert snapshot.read.partial_final_lines == 1
    assert snapshot.read.malformed_lines == 0


def test_an_lp_deposit_is_not_counted_as_charge_injection(tmp_path: Path) -> None:
    """An LP add raises Q and C together and moves the potential by nothing. Two books."""

    liquidity = _swap_row(WEAVE_SOL, NOW - timedelta(minutes=15), kind="liquidity")
    for vault in liquidity["reserves"]["vaults"]:
        vault["delta_raw"] = "7000000"
        vault["post_raw"] = str(int(vault["pre_raw"]) + 7_000_000)
    liquidity["leg_names"] = ["add_liquidity"]
    liquidity["fee_payer"] = "LpWallet"
    _write_rows(
        tmp_path,
        "swaps",
        WEAVE_SOL,
        NOW,
        [_swap_row(WEAVE_SOL, NOW - timedelta(minutes=20)), liquidity],
    )
    pool = read_tape(root=tmp_path, window_hours=6.0, now=NOW, pools=[_spec(WEAVE_SOL)]).pools[WEAVE_SOL]

    assert pool.net_delta_units[WSOL_MINT] == pytest.approx(1.0)  # the swap's 1 SOL only
    assert pool.liquidity_delta_units[WSOL_MINT] == pytest.approx(0.007)
    assert pool.lp_candidates["LpWallet"] == 1


def test_rows_outside_the_event_window_are_not_counted(tmp_path: Path) -> None:
    _write_rows(
        tmp_path,
        "swaps",
        WEAVE_SOL,
        NOW,
        [_swap_row(WEAVE_SOL, NOW - timedelta(hours=5)), _swap_row(WEAVE_SOL, NOW - timedelta(minutes=5))],
    )
    pool = read_tape(root=tmp_path, window_hours=1.0, now=NOW, pools=[_spec(WEAVE_SOL)]).pools[WEAVE_SOL]

    assert pool.swaps == 1


def test_the_join_is_on_event_time_not_ingest_time(tmp_path: Path) -> None:
    """A row backfilled hours late still lands at its chain time, not at its fetch time."""

    row = _swap_row(WEAVE_SOL, NOW - timedelta(minutes=30))
    row["t_ingest"] = (NOW + timedelta(hours=6)).isoformat()  # fetched much later
    _write_rows(tmp_path, "swaps", WEAVE_SOL, NOW, [row])
    pool = read_tape(root=tmp_path, window_hours=1.0, now=NOW, pools=[_spec(WEAVE_SOL)]).pools[WEAVE_SOL]

    assert pool.swaps == 1
    assert pool.last_swap_t_event == row["t_event"]
    assert pool.ingest_before_event_rows == 0


def _spec(address: str):
    return next(spec for spec in CLUSTER_POOLS if spec.address == address)


# ----------------------------------------------------------------------------------------
# 5. the assembled map
# ----------------------------------------------------------------------------------------


def _quote(address: str, price: float, base: str, quote: str, *, liq: float, source: str) -> PoolQuote:
    return PoolQuote(
        address=address,
        source=source,
        price_native=price,
        base_mint=base,
        quote_mint=quote,
        base_price_usd=0.00013,
        liquidity_usd=liq,
        volume_24h_usd=1000.0,
        txns_24h=42,
        fdv_usd=128_000.0,
    )


def _price_snapshot(**overrides) -> PriceSnapshot:
    dex = {
        WEAVE_SOL: _quote(WEAVE_SOL, 1.8e-06, WEAVE, WSOL_MINT, liq=28_000.0, source="dexscreener"),
        NOSIS_SOL: _quote(NOSIS_SOL, 3.3e-06, NOSIS, WSOL_MINT, liq=48_000.0, source="dexscreener"),
        DREGG_SOL: _quote(DREGG_SOL, 4.8e-06, DREGG, WSOL_MINT, liq=57_000.0, source="dexscreener"),
        WEAVE_NOSIS: _quote(WEAVE_NOSIS, 0.55, WEAVE, NOSIS, liq=800.0, source="dexscreener"),
    }
    dlmm = {
        WEAVE_NOSIS: DlmmState(
            address=WEAVE_NOSIS,
            bin_step=300,
            base_fee_pct=6.0,
            dynamic_fee_pct=0.25,
            protocol_fee_pct=10.0,
            token_x_mint=WEAVE,
            token_y_mint=NOSIS,
            token_x_amount=3_000_000.0,
            token_y_amount=1_200_000.0,
            token_x_price_usd=0.00013,
            token_y_price_usd=0.00025,
            current_price=0.55,
        )
    }
    snapshot = PriceSnapshot(fetched_at=NOW.isoformat(), dexscreener=dex, dlmm=dlmm)
    for key, value in overrides.items():
        setattr(snapshot, key, value)
    return snapshot


def _netmap(**kwargs):
    return build_netmap(
        tape=kwargs.pop("tape", None),
        prices=kwargs.pop("prices", _price_snapshot()),
        lp=kwargs.pop("lp", None),
        now=NOW,
        **kwargs,
    )


def _edge(netmap: dict, pool: str) -> dict:
    return next(edge for edge in netmap["edges"] if edge["pool"] == pool)


def test_dlmm_edges_are_battery_stacks_and_cpmm_edges_are_capacitors() -> None:
    netmap = _netmap()
    dlmm = _edge(netmap, WEAVE_NOSIS)
    cpmm = _edge(netmap, WEAVE_SOL)

    assert dlmm["element"]["type"] == ELEMENT_BATTERY_STACK
    assert "battery" in dlmm["element"]["identity"].lower()
    assert set(dlmm["element"]["capacitance_usd_per_log_price"]) >= {"low", "high", "span_bounds"}

    assert cpmm["element"]["type"] == ELEMENT_CAPACITOR
    assert cpmm["element"]["capacitance_usd_per_log_price"]["value"] == pytest.approx(28_000.0 / 4)


def test_the_dlmm_capacitance_uses_the_vault_tvl_not_the_aggregator_field() -> None:
    netmap = _netmap()
    dlmm = _edge(netmap, WEAVE_NOSIS)
    expected_tvl = 3_000_000 * 0.00013 + 1_200_000 * 0.00025

    assert dlmm["element"]["tvl_usd"] == pytest.approx(expected_tvl, abs=0.01)
    assert "meteora" in dlmm["element"]["tvl_source"]
    assert dlmm["element"]["capacitance_usd_per_log_price"]["low"] == pytest.approx(
        expected_tvl / DLMM_SPAN_WIDE, abs=0.01
    )


def test_the_fee_element_is_a_diode_pair_everywhere() -> None:
    netmap = _netmap()
    for edge in netmap["edges"]:
        assert edge["fee"]["element"] == "back_to_back_diode_pair"
        assert "NOT I" in edge["fee"]["dissipation"]
    assert _edge(netmap, WEAVE_NOSIS)["fee"]["taker_bps"] == pytest.approx(625.0)
    assert _edge(netmap, WEAVE_NOSIS)["fee"]["uncertain"] is False


def test_a_drained_edge_is_reported_at_its_chain_tvl_with_a_warning() -> None:
    """Meteora reads the vaults empty while an aggregator still advertises $433: say so."""

    prices = _price_snapshot()
    prices.dexscreener[WEAVE_NOSIS] = _quote(
        WEAVE_NOSIS, 0.55, WEAVE, NOSIS, liq=433.0, source="dexscreener"
    )
    prices.dlmm[WEAVE_NOSIS] = DlmmState(
        address=WEAVE_NOSIS,
        base_fee_pct=6.0,
        token_x_mint=WEAVE,
        token_y_mint=NOSIS,
        token_x_amount=0.0,
        token_y_amount=0.00002,
        token_x_price_usd=0.00013,
        token_y_price_usd=0.00025,
        current_price=0.55,
    )
    netmap = build_netmap(tape=None, prices=prices, lp=None, now=NOW)

    assert _edge(netmap, WEAVE_NOSIS)["element"]["tvl_usd"] == pytest.approx(0.0, abs=0.01)
    assert any("DRAINED" in warning for warning in netmap["warnings"])


def test_every_cycle_carries_its_net_of_cost_value_beside_its_curl() -> None:
    netmap = _netmap()
    assert netmap["cycles"], "the fixture universe must form at least one cycle"
    for cycle in netmap["cycles"]:
        assert "curl_bps" in cycle
        assert cycle["net_value_usd"]["no_concentration"]["net_usd"] is not None
        assert cycle["net_value_usd"]["tight_dlmm_span"]["net_usd"] is not None
        assert cycle["diagnostic_only"] is True
        assert cycle["fee_band_bps"] > 0


def test_a_consistent_triangle_lands_inside_the_dead_zone() -> None:
    """Prices built to satisfy KVL exactly must report zero curl and 'inside the band'."""

    prices = _price_snapshot()
    weave_sol = prices.dexscreener[WEAVE_SOL].price_native
    nosis_sol = prices.dexscreener[NOSIS_SOL].price_native
    prices.dexscreener[WEAVE_NOSIS] = _quote(
        WEAVE_NOSIS, weave_sol / nosis_sol, WEAVE, NOSIS, liq=800.0, source="dexscreener"
    )
    netmap = build_netmap(tape=None, prices=prices, lp=None, now=NOW)
    triangle = next(c for c in netmap["cycles"] if len(c["legs"]) == 3)

    assert triangle["curl_bps"]["dexscreener"] == pytest.approx(0.0, abs=0.5)
    assert "inside the fee dead-zone" in triangle["verdict"]
    assert triangle["net_value_usd"]["tight_dlmm_span"]["net_usd"] < 0


def test_a_residual_outside_the_fee_band_can_still_be_uneconomic() -> None:
    """The thin leg destroys the trade: outside the band, still not worth the gas."""

    prices = _price_snapshot()
    weave_sol = prices.dexscreener[WEAVE_SOL].price_native
    nosis_sol = prices.dexscreener[NOSIS_SOL].price_native
    # 10% off the consistent price: just outside a ~886 bps band, through a $380 leg.
    mispriced = 1.10 * weave_sol / nosis_sol
    prices.dexscreener[WEAVE_NOSIS] = _quote(
        WEAVE_NOSIS, mispriced, WEAVE, NOSIS, liq=380.0, source="dexscreener"
    )
    prices.dlmm[WEAVE_NOSIS] = DlmmState(
        address=WEAVE_NOSIS,
        base_fee_pct=6.0,
        dynamic_fee_pct=0.25,
        token_x_mint=WEAVE,
        token_y_mint=NOSIS,
        token_x_amount=1_000_000.0,
        token_y_amount=1_000_000.0,
        token_x_price_usd=0.00013,
        token_y_price_usd=0.00025,
        current_price=mispriced,
    )
    netmap = build_netmap(tape=None, prices=prices, lp=None, now=NOW)
    triangle = next(c for c in netmap["cycles"] if len(c["legs"]) == 3)

    assert abs(triangle["curl_bps"]["dexscreener"]) > triangle["fee_band_bps"]
    assert triangle["net_value_usd"]["no_concentration"]["net_usd"] <= 0
    assert triangle["net_value_usd"]["tight_dlmm_span"]["net_usd"] <= 0
    assert "uneconomic" in triangle["verdict"]


def test_sources_that_disagree_by_more_than_the_band_make_the_cycle_unresolvable() -> None:
    prices = _price_snapshot()
    prices.geckoterminal = {
        address: _quote(
            address,
            quote.price_native * 1.5,
            quote.base_mint,
            quote.quote_mint,
            liq=quote.liquidity_usd,
            source="geckoterminal",
        )
        for address, quote in prices.dexscreener.items()
    }
    netmap = build_netmap(tape=None, prices=prices, lp=None, now=NOW)
    two_cycle = next(c for c in netmap["cycles"] if c["source_spread_bps"] is not None)

    assert two_cycle["source_spread_bps"] > two_cycle["fee_band_bps"]
    assert "unresolvable" in two_cycle["verdict"]


def test_a_source_quoting_a_different_pair_is_refused_not_reoriented() -> None:
    """Symbols were transposed once in this project; mints decide, and a mismatch is dropped."""

    prices = _price_snapshot()
    prices.dexscreener[WEAVE_SOL] = _quote(
        WEAVE_SOL, 1.8e-06, DREGG, WSOL_MINT, liq=28_000.0, source="dexscreener"
    )
    netmap = build_netmap(tape=None, prices=prices, lp=None, now=NOW)

    assert _edge(netmap, WEAVE_SOL)["prices"]["base_in_quote"] == {}


def test_inverted_orientation_is_flipped_rather_than_dropped() -> None:
    prices = _price_snapshot()
    prices.dexscreener[WEAVE_SOL] = _quote(
        WEAVE_SOL, 1.0 / 1.8e-06, WSOL_MINT, WEAVE, liq=28_000.0, source="dexscreener"
    )
    netmap = build_netmap(tape=None, prices=prices, lp=None, now=NOW)

    assert _edge(netmap, WEAVE_SOL)["prices"]["base_in_quote"]["dexscreener"] == pytest.approx(1.8e-06)


# ----------------------------------------------------------------------------------------
# ownership: unknown is a third state
# ----------------------------------------------------------------------------------------


def _lp_snapshot() -> LpSnapshot:
    position = OurPosition(
        pool=WEAVE_NOSIS,
        position_address="pos1",
        pair="weave/nosis",
        value_usd=800.0,
        unclaimed_fees_usd=6.13,
        claimed_fees_usd=34.34,
        lifetime_fees_usd=40.47,
        in_range=True,
        age_days=0.5,
        fee_rate_per_day=0.2,
        rate_is_thin=True,
        token_amounts={WEAVE: 3_000_000.0, NOSIS: 1_200_000.0},
        token_usd={WEAVE: 390.0, NOSIS: 300.0},
    )
    return LpSnapshot(
        wallet="Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ",
        provenance="inferred_from_tape",
        positions={WEAVE_NOSIS: [position]},
        total_value_usd=800.0,
    )


def test_ownership_is_null_when_no_wallet_resolved_and_the_map_says_so() -> None:
    netmap = _netmap(lp=None)

    assert all(edge["ours"] is None for edge in netmap["edges"])
    assert any("unknown" in warning for warning in netmap["warnings"])


def test_ownership_is_true_only_where_a_position_is_held() -> None:
    netmap = _netmap(lp=_lp_snapshot())

    assert _edge(netmap, WEAVE_NOSIS)["ours"]["is_ours"] is True
    assert _edge(netmap, WEAVE_NOSIS)["ours"]["provenance"] == "inferred_from_tape"
    assert _edge(netmap, WEAVE_SOL)["ours"]["is_ours"] is False
    assert "other wallets are not searched" in _edge(netmap, WEAVE_SOL)["ours"]["basis"]


def test_inventory_is_reported_as_a_lower_bound_from_lp_positions() -> None:
    netmap = _netmap(lp=_lp_snapshot())
    weave = next(node for node in netmap["nodes"] if node["mint"] == WEAVE)

    assert weave["inventory"]["lp_units"] == pytest.approx(3_000_000.0)
    assert weave["inventory"]["complete"] is False
    assert weave["inventory"]["wallet_balance_units"] is None


def test_an_inferred_candidate_with_no_positions_is_not_adopted() -> None:
    """A wallet that once claimed fees and has since withdrawn is not this map's LP wallet."""

    module = SimpleNamespace(collect_report=lambda wallet, now_epoch_seconds: SimpleNamespace(positions=[]))
    snapshot = collect_lp(tape_candidates=["SomeWallet"], now_epoch_seconds=0.0, module=module)

    assert snapshot.resolved is False
    assert snapshot.provenance == "unknown"


def test_a_declared_wallet_with_no_positions_is_still_adopted() -> None:
    """The operator said this is the wallet; "no positions" is then a real answer about it."""

    module = SimpleNamespace(collect_report=lambda wallet, now_epoch_seconds: SimpleNamespace(positions=[]))
    snapshot = collect_lp(wallet="Declared", tape_candidates=[], now_epoch_seconds=0.0, module=module)

    assert snapshot.resolved is True
    assert snapshot.provenance == "declared"
    ownership = snapshot.ownership(WEAVE_NOSIS)
    assert ownership is not None and ownership["is_ours"] is False


def test_a_dead_lp_feed_degrades_the_map_instead_of_stopping_it() -> None:
    def boom(wallet: str, now_epoch_seconds: float) -> None:
        raise RuntimeError("API down")

    snapshot = collect_lp(
        wallet="Declared", now_epoch_seconds=0.0, module=SimpleNamespace(collect_report=boom)
    )

    assert snapshot.resolved is False
    assert snapshot.errors and "API down" in snapshot.errors[0]


# ----------------------------------------------------------------------------------------
# the view is a view: nothing appears in the ASCII that is not in the JSON
# ----------------------------------------------------------------------------------------


def test_the_terminal_view_renders_from_the_contract_alone() -> None:
    netmap = _netmap(lp=_lp_snapshot())
    text = render_text(netmap)

    assert "NETWORK MAP" in text
    assert "battery stack" in text
    assert "weave/nosis" in text
    for cycle in netmap["cycles"]:
        assert cycle["verdict"] in text


def test_the_view_never_draws_a_measured_zero_like_an_unobserved_one(tmp_path: Path) -> None:
    opened = NOW - timedelta(hours=1)
    _write_rows(tmp_path, "watch", WEAVE_SOL, opened, _watch_rows(WEAVE_SOL, opened))
    _write_rows(tmp_path, "swaps", NOSIS_SOL, NOW, [_swap_row(NOSIS_SOL, NOW - timedelta(minutes=10))])
    tape = read_tape(root=tmp_path, window_hours=6.0, now=NOW)
    netmap = build_netmap(tape=tape, prices=_price_snapshot(), lp=None, now=NOW)
    text = render_text(netmap)

    assert _edge(netmap, WEAVE_SOL)["flow"]["evidence"] == EVIDENCE_OBSERVED_ZERO
    assert _edge(netmap, NOSIS_SOL)["flow"]["evidence"] == EVIDENCE_NOT_WATCHING
    assert "0.0/h measured" in text
    assert "not watching" in text


def test_implied_displacement_uses_charge_over_capacitance_on_cpmm_only(tmp_path: Path) -> None:
    """ΔV = ΔQ/C, and only where C is a number rather than an interval."""

    opened = NOW - timedelta(hours=1)
    _write_rows(tmp_path, "watch", WEAVE_SOL, opened, _watch_rows(WEAVE_SOL, opened))
    _write_rows(tmp_path, "swaps", WEAVE_SOL, NOW, [_swap_row(WEAVE_SOL, NOW - timedelta(minutes=10))])
    tape = read_tape(root=tmp_path, window_hours=6.0, now=NOW)
    prices = _price_snapshot()
    prices.dlmm[WEAVE_SOL] = DlmmState(
        address="x", token_x_mint=WSOL_MINT, token_x_price_usd=76.0
    )  # a SOL price for the quote leg
    netmap = build_netmap(tape=tape, prices=prices, lp=None, now=NOW)
    edge = _edge(netmap, WEAVE_SOL)

    # One swap put 1 SOL into the pool; C is TVL/4 from the chosen TVL source.
    delta_usd = 1.0 * 76.0
    expected = 1e4 * delta_usd / capacitance_usd(edge["element"]["tvl_usd"])
    assert edge["charge"]["implied_displacement_bps"] == pytest.approx(expected, rel=1e-3)
    assert _edge(netmap, WEAVE_NOSIS)["charge"]["implied_displacement_bps"] is None
