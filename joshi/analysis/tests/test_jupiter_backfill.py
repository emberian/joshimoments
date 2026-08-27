"""Tests for the backfill parsing, settlement labeling, and leg-in estimand.

Synthetic fixtures only — no network. Fixtures mirror the provider shapes verbatim:
gamma list-fields are JSON strings, trade rows are [t, outcomeIndex, price, size, side].
"""

from __future__ import annotations

from joshi_analysis.jupiter_backfill import legin, reads
from joshi_analysis.jupiter_backfill.fetch import parse_event

START = 1_787_845_500
CLOSE = START + 300


def make_round(rows, history=None, gamma_closed=True, prices=("0", "1")):
    rec = {
        "contract": "joshi.jupiter_backfill.round.v1",
        "roundKey": f"5m-{START}",
        "horizon": "5m",
        "windowStartUnix": START,
        "closeTimeUnix": CLOSE,
        "outcomes": ["Up", "Down"],
        "ruleEra": reads.ERA_TWAP60,
        "trades": {"fetched": True, "rows": rows},
        "priceHistory": history or {"fetched": False, "up": [], "down": []},
        "gammaResolution": {
            "closed": gamma_closed,
            "umaResolutionStatus": "resolved" if gamma_closed else None,
            "outcomePrices": list(prices),
            "closedTime": None,
        },
    }
    rec["settlement"] = reads.settle_labels(rec)
    return rec


def fills(side_prices: dict[int, list[float]], t0=START + 10) -> list[list]:
    rows = []
    t = t0
    for oi, prices in side_prices.items():
        for p in prices:
            rows.append([t, oi, p, 10.0, "BUY"])
            t += 1
    return sorted(rows, key=lambda r: r[0])


def test_slug_window_parse_and_era():
    assert reads.parse_window_start("sol-updown-5m-1787845500") == 1_787_845_500
    assert reads.parse_window_start("sol-updown-5m-1787845501") is None  # off-grid
    assert reads.parse_window_start("nonsense") is None
    twap = "https://data.chain.link/streams/sol-usd-twap-60s-streams"
    assert reads.classify_era(twap) == reads.ERA_TWAP60
    assert reads.classify_era("https://data.chain.link/streams/sol-usd") == reads.ERA_ENDPOINT
    assert reads.classify_era(None) == reads.ERA_UNKNOWN


def test_parse_event_builds_round_from_gamma_shapes():
    event = {
        "id": 916172,
        "slug": f"sol-updown-5m-{START}",
        "markets": [
            {
                "id": 3903657,
                "conditionId": "0xb035",
                "endDate": "2026-08-27T15:50:00Z",
                "outcomes": '["Up", "Down"]',
                "clobTokenIds": '["111", "222"]',
                "outcomePrices": '["0", "1"]',
                "closed": True,
                "umaResolutionStatus": "resolved",
                "resolutionSource": "https://data.chain.link/streams/sol-usd-twap-60s-streams",
                "createdAt": "2026-08-26T15:52:39Z",
                "volumeNum": 1088.9,
            }
        ],
    }
    rec = parse_event(event, "5m")
    assert rec is not None
    assert rec["windowStartUnix"] == START and rec["closeTimeUnix"] == CLOSE
    assert rec["clobTokenIds"] == ["111", "222"]
    assert rec["ruleEra"] == reads.ERA_TWAP60
    assert reads.label_from_gamma(True, rec["outcomes"],
                                  rec["gammaResolution"]["outcomePrices"]) == "Down"
    # a horizon mismatch (endDate not start+300) is rejected, not silently kept
    event["markets"][0]["endDate"] = "2026-08-27T16:00:00Z"
    assert parse_event(event, "5m") is None


def test_gamma_label_requires_exact_pin_and_closed():
    assert reads.label_from_gamma(True, ["Up", "Down"], ["1", "0"]) == "Up"
    assert reads.label_from_gamma(True, ["Up", "Down"], ["0", "1"]) == "Down"
    # the Aug-5 zombie shape: near-pin but not exact, and not closed -> no label
    assert reads.label_from_gamma(False, ["Up", "Down"], ["0.9995", "0.0005"]) is None
    assert reads.label_from_gamma(True, ["Up", "Down"], ["0.9995", "0.0005"]) is None
    assert reads.label_from_gamma(True, ["Up", "Down"], ["0.5", "0.5"]) is None


def test_pin_label_from_post_close_trades():
    rows = [
        *fills({0: [0.4, 0.6]}),
        [CLOSE + 5, 0, 0.999, 5.0, "BUY"],
        [CLOSE + 9, 1, 0.001, 5.0, "SELL"],
    ]
    assert reads.label_from_pin(rows, ["Up", "Down"], CLOSE) == "Up"
    # conflicted pin (both sides high) -> None
    conflicted = [[CLOSE + 5, 0, 0.99, 1.0, "BUY"], [CLOSE + 6, 1, 0.95, 1.0, "BUY"]]
    assert reads.label_from_pin(conflicted, ["Up", "Down"], CLOSE) is None
    # no post-close trades -> None
    assert reads.label_from_pin(fills({0: [0.5]}), ["Up", "Down"], CLOSE) is None


def test_settlement_prefers_gamma_and_keeps_disagreement():
    rows = [[CLOSE + 5, 0, 0.999, 5.0, "BUY"], [CLOSE + 6, 1, 0.001, 5.0, "SELL"]]
    rec = make_round(rows, prices=("0", "1"))  # gamma says Down, pin says Up
    assert rec["settlement"]["label"] == "Down"
    assert rec["settlement"]["labelSource"] == "gamma-resolution-pin-disagrees"
    assert rec["settlement"]["labelPin"] == "Up"
    rec2 = make_round(rows, gamma_closed=False)  # no gamma label -> pin wins
    assert rec2["settlement"]["label"] == "Up"
    assert rec2["settlement"]["labelSource"] == "terminal-pin"


def test_zone_split_boundaries():
    rows = [
        [START - 1, 0, 0.5, 1.0, "BUY"],  # pre-window
        [START, 0, 0.5, 1.0, "BUY"],  # first in-window instant
        [CLOSE - 1, 1, 0.5, 1.0, "BUY"],  # last in-window instant
        [CLOSE, 1, 0.999, 1.0, "BUY"],  # settlement-pin zone
    ]
    zones = reads.split_zones(rows, START, CLOSE)
    assert zones.counts == {"up": 1, "down": 1, "preWindow": 1, "postClose": 1}


def test_leg_in_min_combined_and_fee():
    # Up trades down to 0.30 mid-window, Down to 0.55 at another moment: legged book 0.85.
    rows = fills({0: [0.55, 0.30, 0.50, 0.45, 0.60], 1: [0.70, 0.55, 0.60, 0.65, 0.58]})
    # cheap PRE-window and POST-close prints must not lower the in-window minima
    rows = [[START - 50, 0, 0.05, 1.0, "BUY"], *rows, [CLOSE + 2, 1, 0.001, 1.0, "SELL"]]
    res = legin.leg_in_round(make_round(rows))
    assert res["covered"] is True
    assert res["minUp"] == 0.30 and res["minDown"] == 0.55
    assert abs(res["combined"] - 0.85) < 1e-12
    fee_expected = 0.070 * 0.30 * 0.70 + 0.070 * 0.55 * 0.45
    assert abs(res["combinedNetFee"] - (0.85 + fee_expected)) < 1e-12
    assert res["lockedNetFee"] is True and res["lockedGross"] is True


def test_leg_in_coverage_gate_and_history_topup():
    thin = fills({0: [0.5, 0.5], 1: [0.6] * 6})
    res = legin.leg_in_round(make_round(thin))
    assert res["covered"] is False and res["reason"] == "insufficient-coverage"
    # 1-min history tops up ONLY the thin side, in-window points only
    history = {
        "fetched": True,
        "up": [[START + 60, 0.42], [START + 120, 0.44], [START + 180, 0.41],
               [START - 600, 0.05], [CLOSE + 100, 0.999]],
        "down": [[START + 60, 0.01]],
    }
    res2 = legin.leg_in_round(make_round(thin, history=history))
    assert res2["covered"] is True
    assert res2["source"] == "fills+1min-history"
    assert res2["minUp"] == 0.41  # not the out-of-window 0.05
    assert res2["minDown"] == 0.6  # down side was not thin: history not mixed in


def test_summarize_reports_rates_with_fee_floor_beside():
    rows_locked = fills({0: [0.30] * 5, 1: [0.55] * 5})
    rows_open = fills({0: [0.60] * 5, 1: [0.55] * 5})
    per = [legin.leg_in_round(make_round(r)) for r in (rows_locked, rows_open)]
    summary = legin.summarize(per)
    h = summary["byHorizon"]["5m"]
    assert h["covered"] == 2 and h["lockedNetFee"] == 1
    assert summary["feeFloorMidpointUsd"] == 0.0175
    assert any("fills" in c for c in summary["caveats"])
    assert h["byRuleEra"][reads.ERA_TWAP60]["covered"] == 2


# ---------------------------------------------------------------- census (decision-time)

from joshi_analysis.jupiter_backfill import census  # noqa: E402


def census_round(rows, label="Up"):
    return census.Round(
        key=f"5m-{START}", horizon="5m", open_s=START, close_s=CLOSE,
        label=label, rows=tuple(sorted(rows, key=lambda r: r[0])),
    )


def test_last_fill_at_is_causal_and_staleness_capped():
    rows = ([START + 10, 0, 0.40, 1.0, "BUY"], [START + 100, 0, 0.55, 1.0, "BUY"],
            [START + 105, 1, 0.50, 1.0, "BUY"])
    rnd = census_round(rows)
    # at t=99 only the t=10 fill exists on side 0 -- but it is 89s old (> 60s cap)
    assert census.last_fill_at(rnd.rows, 0, START + 99) is None
    assert census.last_fill_at(rnd.rows, 0, START + 99, stale_s=120) == 0.40
    # at t=110 the freshest side-0 fill is 0.55 (never the later-timestamped 0.50 on side 1)
    assert census.last_fill_at(rnd.rows, 0, START + 110) == 0.55
    assert census.last_fill_at(rnd.rows, 1, START + 110) == 0.50
    # side 1 has no fill at all before t=104
    assert census.last_fill_at(rnd.rows, 1, START + 104) is None


def test_fade_edges_flags_only_past_fee():
    # model P(up)=0.60: buying Up at 0.55 has edge 0.05 - fee(0.55)=0.0173 > 0 -> flagged;
    # buying Down (P=0.40) at 0.50 has edge -0.10-fee < 0 -> not a setup.
    edges = census.fade_edges(0.60, 0.55, 0.50)
    up = next(e for e in edges if e["side"] == 0)
    down = next(e for e in edges if e["side"] == 1)
    assert up["edgeNet"] > 0 and abs(up["edgeNet"] - (0.05 - census.fee(0.55))) < 1e-12
    assert down["edgeNet"] < 0
    # a missing quote yields no entry for that side
    assert [e["side"] for e in census.fade_edges(0.60, None, 0.50)] == [1]


def test_leg_in_causal_walk():
    rows = [
        [START + 20, 0, 0.30, 1.0, "BUY"],   # leg 1: Up at 0.30 (<= x)
        [START + 10, 1, 0.50, 1.0, "BUY"],   # earlier Down fill ABOVE y: not leg 2
        [START + 60, 1, 0.55, 1.0, "BUY"],   # leg 2: Down at 0.55 (<= y, later)
        [START - 30, 1, 0.10, 1.0, "BUY"],   # pre-window cheap fill must NOT count
        [CLOSE + 5, 1, 0.01, 1.0, "SELL"],   # post-close must NOT count
    ]
    rnd = census_round(rows, label="Down")
    w = census.leg_in_causal(rnd, 0.35, 0.55)
    assert w["outcome"] == "completed" and w["q1"] == 0.30 and w["q2"] == 0.55
    expected = 0.30 + census.fee(0.30) + 0.55 + census.fee(0.55)
    assert abs(w["combinedNet"] - expected) < 1e-12
    assert w["locked"] is True and abs(w["pnl"] - (1.0 - expected)) < 1e-12
    # y too tight -> naked leg on Up, which LOSES (label Down): pnl = -q1 - fee
    w2 = census.leg_in_causal(rnd, 0.35, 0.40)
    assert w2["outcome"] == "naked" and w2["side"] == 0
    assert abs(w2["pnl"] - (-0.30 - census.fee(0.30))) < 1e-12
    # x below every in-window print -> no trigger (the pre-window 0.10 must not fire it)
    assert census.leg_in_causal(rnd, 0.05, 0.99)["outcome"] == "no-trigger"


def test_leg_in_leg2_strictly_after_leg1():
    rows = [
        [START + 20, 0, 0.30, 1.0, "BUY"],
        [START + 20, 1, 0.55, 1.0, "BUY"],  # same instant: not strictly later
    ]
    rnd = census_round(rows, label="Up")
    w = census.leg_in_causal(rnd, 0.35, 0.60)
    assert w["outcome"] == "naked"  # won: pnl = 1 - 0.30 - fee
    assert w["pnl"] > 0


def test_buy_ahead_takes_first_aligned_in_band():
    class FakeSeries:
        def price_at(self, s, max_stale_s=120.0):
            # rising reference: trailing-1h return > +50bps at any pre-window t
            return 100.0 + (s - START) * 0.01

    rows = [
        [START - 500, 0, 0.70, 1.0, "BUY"],  # out of band -> skipped
        [START - 400, 1, 0.45, 1.0, "BUY"],  # in band but counter-trend (regime up)
        [START - 300, 0, 0.52, 1.0, "BUY"],  # FIRST aligned in-band -> the take
        [START - 100, 0, 0.41, 1.0, "BUY"],  # later aligned fill ignored (first-only)
        [START + 10, 0, 0.45, 1.0, "BUY"],   # in-window: not buy-ahead
    ]
    rnd = census_round(rows, label="Up")
    b = census.buy_ahead_take(rnd, FakeSeries())
    take = b["takes"]["aligned"]
    assert take["q"] == 0.52 and take["side"] == 0 and take["aheadS"] == 300
    assert abs(take["pnl"] - (1.0 - 0.52 - census.fee(0.52))) < 1e-12
    against = b["takes"]["against"]
    assert against["q"] == 0.45 and against["side"] == 1 and against["pnl"] < 0


def test_oracle_vs_causal_gap_exists_by_construction():
    # Up prints 0.30 early; Down only gets cheap LATE (0.10 at the end). Oracle pairs the
    # two minima (0.40 combined -> lock). The causal (0.35, 0.35) rule triggers on Up
    # then finds Down <= 0.35 later -> also completes here; but with y=0.05 leg 2 never
    # comes and the walk goes naked -- hindsight and decision-time diverge.
    rows = [
        [START + 10, 0, 0.30, 1.0, "BUY"],
        [START + 250, 1, 0.10, 1.0, "BUY"],
        *fills({0: [0.6] * 4, 1: [0.9] * 4}, t0=START + 30),
    ]
    rnd = census_round(rows, label="Down")
    assert census.oracle_lock(rnd) is True
    assert census.leg_in_causal(rnd, 0.35, 0.35)["outcome"] == "completed"
    assert census.leg_in_causal(rnd, 0.35, 0.05)["outcome"] == "naked"
