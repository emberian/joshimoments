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
