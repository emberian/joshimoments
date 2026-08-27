"""Tests for the registered jupiter_base_rate estimands, on synthetic data only."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from joshi_analysis.jupiter_base_rate import reference, rounds, study
from joshi_analysis.jupiter_base_rate.reference import Candle


def make_candles(start: int, closes: list[str], opens: list[str] | None = None):
    """Uniform 60s candles; prices are Decimal literals. opens default to previous close."""
    out: dict[int, Candle] = {}
    for i, close in enumerate(closes):
        opn = opens[i] if opens else (closes[i - 1] if i else close)
        c = Decimal(close)
        out[start + 60 * i] = Candle(
            time_s=start + 60 * i,
            low=min(Decimal(opn), c),
            high=max(Decimal(opn), c),
            open=Decimal(opn),
            close=c,
            volume=Decimal(1),
        )
    return out


def test_flat_price_ties_resolve_up_under_both_rules():
    candles = make_candles(0, ["100"] * 11)
    h = study.evaluate_horizon(candles, 300)
    assert h.n_endpoint == h.up_endpoint == 2
    assert h.n_twap == h.up_twap == 2
    assert h.disagreements == 0


def test_endpoint_and_twap_rules_can_disagree():
    # dip-then-recover inside [0, 300): price AT 300 above open(0) but window TWAP below.
    closes = ["100", "90", "90", "90", "100.5"] + ["100.5"] * 6
    opens = ["100", *closes[:-1]]
    candles = make_candles(0, closes, opens)
    h = study.evaluate_horizon(candles, 300)
    first_twap = study.window_twap(candles, 0, 300)
    assert first_twap == (Decimal("100") + Decimal("90") * 3 + Decimal("100.5")) / 5
    assert study.point_price(candles, 300) == Decimal("100.5")  # open of minute 300
    assert h.up_endpoint == 2 and h.disagreements == 1


def test_grid_anchoring_and_missing_minutes_are_counted_not_imputed():
    # start off-grid at 120: first 5m window anchors at 300.
    candles = make_candles(120, ["100"] * 20)
    h = study.evaluate_horizon(candles, 300)
    assert h.grid_windows == 3  # T = 300, 600, 900 fit inside span (last stamp 1260)
    # knock out an interior minute of the first window: TWAP excluded, endpoint kept.
    del candles[420]
    h2 = study.evaluate_horizon(candles, 300)
    assert h2.n_endpoint == h.n_endpoint
    assert h2.excluded_missing_interior == 1
    assert h2.n_twap == h.n_twap - 1
    # knock out a boundary: window excluded entirely.
    del candles[600]
    h3 = study.evaluate_horizon(candles, 300)
    assert h3.excluded_missing_boundary >= 1


def test_wilson_interval_sane():
    lo, hi = study.wilson_95(50, 100)
    assert lo < 0.5 < hi
    lo1, hi1 = study.wilson_95(100, 100)
    assert hi1 <= 1.0 and lo1 > 0.9
    assert study.wilson_95(0, 0) is None


def test_rate_block_carries_reference_label_and_fee_floor():
    block = study.rate_block(3, 4)
    assert "NOT settlement-exact" in block["reference"]
    assert block["feeFloor"]["explicitMidpointPerDollar"] == 0.0175


def test_loader_keeps_provider_decimal_literals_exact(tmp_path: Path):
    body = json.dumps([[60, 104.51, 104.68, 104.54, 104.58, 2049.32080812]])
    line = {"kind": "candles", "venue": "coinbase", "bodyText": body}
    (tmp_path / "reference-x.jsonl").write_text(json.dumps(line) + "\n")
    candles = reference.load_coinbase(tmp_path)
    assert candles[60].close == Decimal("104.58")
    assert candles[60].volume == Decimal("2049.32080812")


def test_venue_dispersion_over_overlap():
    candles = make_candles(0, ["100", "100"])
    kraken = {0: Decimal("100.1"), 60: Decimal("100"), 999: Decimal("50")}
    d = reference.venue_dispersion(candles, kraken)
    assert d["n"] == 2
    assert abs(d["maxAbsRel"] - 0.001) < 1e-12


def _collect_line(kind: str, event_id: str, horizon: str, arrival_us: int, **extra) -> str:
    rec = {
        "kind": kind,
        "eventId": event_id,
        "horizon": horizon,
        "title": f"Solana Up or Down {event_id}",
        "arrivalUnixUs": arrival_us,
        **extra,
    }
    return json.dumps(rec) + "\n"


def test_stale_islive_rounds_are_filtered_by_window_vs_collection_span(tmp_path: Path):
    now_s = 1_787_838_600
    genuine_close = now_s + 200  # closes just after collection started
    stale_close = now_s - 2_000_000  # weeks old, yet flagged isLive by the API
    markets_g = [{"closeTime": genuine_close, "openTime": genuine_close - 86000}]
    markets_s = [{"closeTime": stale_close, "openTime": stale_close - 86000}]
    twap_rules = "resolve to Up if the time-weighted average price (TWAP) ... Chainlink"
    endpoint_rules = "resolve to Up if the price at the end ... Chainlink"
    lines = [
        _collect_line("rules", "POLY-1", "5m", now_s * 1_000_000, rulesPrimary=twap_rules),
        _collect_line("sample", "POLY-1", "5m", now_s * 1_000_000, markets=markets_g),
        _collect_line("rules", "POLY-9", "15m", now_s * 1_000_000, rulesPrimary=endpoint_rules),
        _collect_line("sample", "POLY-9", "15m", now_s * 1_000_000, markets=markets_s),
        _collect_line("sample", "POLY-1", "5m", (now_s + 40) * 1_000_000, markets=markets_g),
        _collect_line("settlement", "POLY-1", "5m", (now_s + 400) * 1_000_000, result="Up"),
    ]
    (tmp_path / "collect-x.jsonl").write_text("".join(lines))
    parsed, totals = rounds.read_rounds(tmp_path)
    assert parsed["POLY-1"].genuine and parsed["POLY-1"].rule_variant == "twap"
    assert not parsed["POLY-9"].genuine and parsed["POLY-9"].rule_variant == "endpoint"
    assert parsed["POLY-1"].window == (genuine_close - 300, genuine_close)
    assert totals["samples"] == 3
    inv = rounds.inventory(parsed)
    assert inv["genuine"]["total"] == 1
    assert inv["genuine"]["withSettlementLine"] == 1
    assert inv["staleFilteredOut"]["eventIds"] == ["POLY-9"]


def test_terminal_label_inferred_only_from_post_close_pinned_pricing(tmp_path: Path):
    now_s = 1_787_838_600
    close = now_s + 100
    in_window = [
        {"marketId": "POLY-7-0", "closeTime": close, "pricing": {"buyYesPriceUsd": 470_000}},
        {"marketId": "POLY-7-1", "closeTime": close, "pricing": {"buyYesPriceUsd": 550_000}},
    ]
    post_close = [
        {"marketId": "POLY-7-0", "closeTime": close, "pricing": {"buyYesPriceUsd": 1_000}},
        {"marketId": "POLY-7-1", "closeTime": close, "pricing": {"buyYesPriceUsd": 1_000_000}},
    ]
    lines = [
        _collect_line("sample", "POLY-7", "5m", now_s * 1_000_000, markets=in_window),
        _collect_line("sample", "POLY-7", "5m", (close + 30) * 1_000_000, markets=post_close),
    ]
    (tmp_path / "collect-x.jsonl").write_text("".join(lines))
    parsed, _ = rounds.read_rounds(tmp_path)
    assert parsed["POLY-7"].terminal_label == "Down"  # -1 side pinned to $1
    inv = rounds.inventory(parsed)
    assert inv["genuine"]["terminalLabeled"] == 1
    assert inv["genuine"]["terminalLabels"]["POLY-7"]["label"] == "Down"
    # a round with only in-window pricing stays unlabeled
    (tmp_path / "collect-x.jsonl").write_text(
        _collect_line("sample", "POLY-8", "5m", now_s * 1_000_000, markets=in_window)
    )
    parsed2, _ = rounds.read_rounds(tmp_path)
    assert parsed2["POLY-8"].terminal_label is None


def test_signature_report_reuses_instrument_and_marks_thin_lags_absent():
    candles = make_candles(0, [str(100 + (i % 3)) for i in range(40)])
    rep = study.signature_report(candles)
    assert rep["instrument"].startswith("joshi_analysis.signature")
    by_lag = {row["lagSeconds"]: row for row in rep["wallTime"]}
    assert by_lag[1]["sigma2"] is None and by_lag[1]["pairs"] == 0  # sub-bar lag: absent
    assert by_lag[60]["sigma2"] is not None
