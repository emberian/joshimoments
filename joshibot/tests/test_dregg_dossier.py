"""Offline tests for the dossier lane: index build, lookups, cards, gating, rate limit.

Same discipline as test_dregg_gate_lookup: no live Telegram, no live Helius, and no real
parquets — the fixtures are tiny parquet files written in the estimator's exact shape,
plus a crew ledger built on dregg_screen.ledger's REAL schema (not a hand-rolled mirror).
The build path needs the research group (duckdb/pyarrow); the whole module skips cleanly
where those are absent, because everything downstream consumes the built sqlite.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from solders.keypair import Keypair

from dregg_dossier import cards, store
from dregg_dossier.lookup import (
    DEFAULT_RATE_PER_MINUTE,
    EJECTED_TEXT,
    UNAVAILABLE_TEXT,
    WALLET_USAGE_TEXT,
    DossierLookup,
)
from dregg_gate.config import Config
from dregg_gate.state import GateState
from dregg_screen.ledger import _SCHEMA as LEDGER_SCHEMA

# The build path needs the research group; everything downstream reads the built sqlite.
pytest.importorskip("duckdb", reason="the dossier build lives in the research group")
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

UPDATED_THROUGH = 1_786_751_999  # 2026-08-14 23:59:59 UTC, the real corpus end
CORPUS_START = UPDATED_THROUGH - 9 * 86_400
NOW = UPDATED_THROUGH + 14 * 86_400  # a fortnight stale, like the real render today


def addr() -> str:
    return str(Keypair().pubkey())


# One address set for the whole module so cards and fixtures agree.
W_FLASH, W_HARVESTER, W_SLOW, W_UNKNOWN = addr(), addr(), addr(), addr()
M_HOT, M_QUIET, M_MISSING = addr(), addr(), addr()


def _wallet_row(owner: str, owner_id: int, **overrides) -> dict:
    row = {
        "owner": owner, "owner_id": owner_id,
        "n_legs": 30.0, "n_buys": 15.0, "n_sells": 15.0, "n_coins": 5,
        "active_days": 4, "span_days": 6.0, "t_first": CORPUS_START, "t_last": UPDATED_THROUGH,
        "gross_sol": 20.0, "buy_sol": 10.0, "sell_sol": 10.0, "sol_asymmetry": 0.0,
        "sell_buy_leg_ratio": 1.0, "roundtrip_frac": 0.5,
        "net_realized_sol": -0.5, "win_rate": 0.4, "n_coins_closed": 5.0, "n_coins_win": 2.0,
        "median_realized_sol_closed": -0.01,
        "median_hold_s": 40.0, "p90_hold_s": 500.0,
        "n_priced_sells": 15, "rp_frac_in_profit": 0.3, "rp_frac_at_loss": 0.3,
        "rp_frac_breakeven": 0.4, "rp_p10": 0.1, "rp_p50": 0.5, "rp_p90": 0.9,
        "holds_through_red": 0.1, "rp_mode": "MIXED",
        "fresh_frac": 0.9, "exit_ratio": 0.8, "guild_solo": "FLASH", "cid": None,
        "guild_cluster": None, "guild": "FLASH",
        "median_entry_latency_s": 8.0, "on_ladder": False,
        "in_rotation": False, "rotation_hours": 0,
        "updated_through": UPDATED_THROUGH, "schema_version": 1,
    }
    row.update(overrides)
    return row


def _write(path: Path, rows: list[dict]) -> None:
    pq.write_table(pa.Table.from_pylist(rows), path)


@pytest.fixture(scope="module")
def fixture_index(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a real dossier index from tiny fixture inputs; return its path."""

    root = tmp_path_factory.mktemp("dossier-fixtures")
    wallets_dir = root / "wallets"
    wallets_dir.mkdir()

    _write(wallets_dir / "estimator.parquet", [
        _wallet_row(
            W_FLASH, 1, guild="FLASH", rp_mode="BREAKEVEN_PRESET",
            net_realized_sol=1.5, win_rate=0.7, n_coins_win=4.0,
            in_rotation=True, rotation_hours=30, on_ladder=True,
        ),
        _wallet_row(
            W_HARVESTER, 2, guild="HARVESTER", guild_cluster="HARVESTER", rp_mode="MIXED",
            net_realized_sol=8.0, median_hold_s=900.0,
        ),
        _wallet_row(
            W_SLOW, 3, guild="SLOW", rp_mode="LOSS_CUTTER",
            net_realized_sol=-4.0, win_rate=0.1, n_coins_win=0.0,
            median_hold_s=8_000.0, n_priced_sells=None, median_entry_latency_s=None,
        ),
    ])
    # W_UNKNOWN (owner_id 4) trades but is below the activity floor: no estimator row.

    _write(wallets_dir / "iceberg.parquet", [
        {
            "owner": W_HARVESTER, "mint": M_HOT, "owner_id": 2, "mint_id": 1,
            "iceberg_score": 12.5, "drawdown": 0.95, "sold_frac_of_own": 0.95,
            "n_dist_sells": 400, "dist_sold_sol": 250.0, "duration_s": 86_400.0,
            "resilience": 1.2, "timing_q": 0.03, "self_wash": None,
            "is_recent": True, "last_dist_t": UPDATED_THROUGH - 3_600, "is_candidate": True,
        },
        {   # a non-candidate episode: must NOT surface on any card
            "owner": W_SLOW, "mint": M_HOT, "owner_id": 3, "mint_id": 1,
            "iceberg_score": 0.5, "drawdown": 0.2, "sold_frac_of_own": 0.2,
            "n_dist_sells": 2, "dist_sold_sol": 1.0, "duration_s": 60.0,
            "resilience": -0.5, "timing_q": None, "self_wash": 0.0,
            "is_recent": None, "last_dist_t": UPDATED_THROUGH - 86_400, "is_candidate": False,
        },
    ])

    _write(wallets_dir / "coin_exit_signal.parquet", [
        {
            "mint": M_HOT, "mint_id": 1, "n_distributors": 1, "max_iceberg_score": 12.5,
            "any_recent": True, "n_timing_pass": 1, "last_dist_t": UPDATED_THROUGH - 3_600,
        },
        # M_QUIET carries no row at all: the clean no-signal path.
    ])

    pvp = root / "pvp"
    pvp.mkdir()
    _write(pvp / "trades.parquet", [
        {"mint_id": mint_id, "owner_id": owner_id}
        for mint_id, owner_id in [
            (1, 1), (1, 1), (1, 2), (1, 3), (1, 4),  # M_HOT: all four (one dupe leg)
            (2, 2), (2, 3),                          # M_QUIET: the two calm wallets
        ]
    ])
    _write(pvp / "mints.parquet", [
        {"mint": M_HOT, "mint_id": 1, "operator_coin": False},
        {"mint": M_QUIET, "mint_id": 2, "operator_coin": False},
    ])
    _write(pvp / "owners.parquet", [
        {"owner": owner, "owner_id": owner_id}
        for owner, owner_id in [(W_FLASH, 1), (W_HARVESTER, 2), (W_SLOW, 3), (W_UNKNOWN, 4)]
    ])

    # Crew ledger on the real dregg_screen schema: crew 7 LAUNCHED M_QUIET, and its
    # birth-slot set on another coin contains two of M_HOT's traders (overlap path).
    ledger_path = root / "crew.sqlite"
    con = sqlite3.connect(ledger_path)
    con.executescript(LEDGER_SCHEMA)
    other_crew_coin = addr()
    con.execute("INSERT INTO crews VALUES (7, ?, 3, 2, 5, 1)", (addr(),))
    con.execute("INSERT INTO crew_coins VALUES (?, 7, 2)", (other_crew_coin,))
    con.execute("INSERT INTO crew_coins VALUES (?, 7, 1)", (M_QUIET,))
    con.executemany(
        "INSERT INTO crew_set VALUES (?, ?)",
        [(other_crew_coin, W_FLASH), (other_crew_coin, W_HARVESTER), (M_QUIET, addr())],
    )
    con.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [(k, json.dumps(v)) for k, v in {
            "schema_version": 1, "built_at": "2026-08-29T00:00:00+00:00",
            "corpus_span": ["2026-08-05", "2026-08-28"], "crews": 1,
        }.items()],
    )
    con.commit()
    con.close()

    out = root / "dossier.sqlite"
    meta = store.build(
        wallets_dir, out,
        trades_path=pvp / "trades.parquet",
        mints_path=pvp / "mints.parquet",
        owners_path=pvp / "owners.parquet",
        crew_ledger_path=ledger_path,
    )
    assert meta["n_wallets"] == 3
    assert meta["n_coins"] == 2
    assert meta["comp_source"] == "trades"
    return out


@pytest.fixture(scope="module")
def dossier(fixture_index: Path) -> store.Dossier:
    return store.Dossier(fixture_index)


# -- store ----------------------------------------------------------------------------


def test_build_without_trades_falls_back_to_holders(fixture_index: Path, tmp_path: Path):
    """No priced tape on the box: composition degrades to significant holders, labeled."""

    wallets_dir = fixture_index.parent / "wallets"
    out = tmp_path / "dossier-holders.sqlite"
    meta = store.build(wallets_dir, out)  # no trades/mints/owners, no crew ledger
    assert meta["comp_source"] == "iceberg_holders"
    assert meta["crew_ledger"] is None
    dossier = store.Dossier(out)
    view = dossier.coin(M_HOT)
    assert view["comp"]["n_traders"] == 2  # only the two >=0.1%-peak holders
    text = cards.coin_card(M_HOT, view, dossier.meta, NOW)
    assert "Significant holders" in text and "Who traded it" not in text
    assert "crew ledger was not reachable" in text  # unknown, never rendered as clear


def test_build_meta_carries_freshness_and_sources(dossier: store.Dossier):
    assert dossier.meta["updated_through"] == UPDATED_THROUGH
    assert dossier.meta["corpus_span"] == ["2026-08-05", "2026-08-14"]
    assert dossier.meta["crew_ledger"]["corpus_span"] == ["2026-08-05", "2026-08-28"]
    assert dossier.staleness_days is not None and dossier.staleness_days > 13


def test_wallet_lookup_roundtrip(dossier: store.Dossier):
    row = dossier.wallet(W_FLASH)
    assert row is not None
    assert row["guild"] == "FLASH"
    assert row["rp_mode"] == "BREAKEVEN_PRESET"
    assert row["net_realized_sol"] == pytest.approx(1.5)
    assert row["on_ladder"] == 1 and row["in_rotation"] == 1
    assert dossier.wallet(W_UNKNOWN) is None  # below the floor: None, not a zeroed row


def test_coin_view_composition_math(dossier: store.Dossier):
    view = dossier.coin(M_HOT)
    assert view is not None
    comp = view["comp"]
    # 4 distinct traders (the duplicate leg collapses), 3 of them profiled.
    assert comp["n_traders"] == 4
    assert comp["n_profiled"] == 3
    assert (comp["n_flash"], comp["n_harvester"], comp["n_slow"]) == (1, 1, 1)
    assert comp["n_breakeven_preset"] == 1
    assert comp["n_net_positive"] == 2  # W_FLASH +1.5, W_HARVESTER +8.0
    assert comp["n_on_ladder"] == 1 and comp["n_in_rotation"] == 1
    # Only the GATED candidate surfaces; the tiny non-candidate episode never does.
    assert [ep["owner"] for ep in view["icebergs"]] == [W_HARVESTER]
    assert view["exit"]["n_timing_pass"] == 1


def test_coin_view_clean_no_signal_and_miss(dossier: store.Dossier):
    quiet = dossier.coin(M_QUIET)
    assert quiet is not None
    assert quiet["exit"] is None  # no gated distributor: absent, not a zero score
    assert quiet["icebergs"] == []
    assert dossier.coin(M_MISSING) is None


def test_crew_join_both_paths(dossier: store.Dossier):
    hot = dossier.coin(M_HOT)
    overlap = [c for c in hot["crews"] if not c["launched_by"]]
    assert len(overlap) == 1 and overlap[0]["crew_id"] == 7 and overlap[0]["n_overlap"] == 2
    quiet = dossier.coin(M_QUIET)
    launched = [c for c in quiet["crews"] if c["launched_by"]]
    assert len(launched) == 1 and launched[0]["crew_id"] == 7
    assert launched[0]["crew_rips"] == 2 and launched[0]["crew_dumps"] == 5


# -- cards ----------------------------------------------------------------------------


def all_sample_cards(dossier: store.Dossier) -> list[str]:
    meta = dossier.meta
    return [
        cards.wallet_card(dossier.wallet(W_FLASH), meta, NOW),
        cards.wallet_card(dossier.wallet(W_SLOW), meta, NOW),
        cards.wallet_miss(W_UNKNOWN, meta, NOW),
        cards.coin_card(M_HOT, dossier.coin(M_HOT), meta, NOW),
        cards.coin_card(M_QUIET, dossier.coin(M_QUIET), meta, NOW),
        cards.coin_miss(M_MISSING, meta, NOW),
    ]


def test_every_card_is_plain_text_with_freshness_stamp(dossier: store.Dossier):
    for text in all_sample_cards(dossier):
        assert "<" not in text, "cards are plain text; nothing may look like markup"
        assert "2026-08-05..2026-08-14" in text  # rule 2: the corpus window, always
        assert "14 days old" in text  # ...and how stale it has become
        assert len(text) <= 4096  # Telegram's sendMessage cap


def test_wallet_card_content(dossier: store.Dossier):
    text = cards.wallet_card(dossier.wallet(W_FLASH), dossier.meta, NOW)
    assert "FLASH" in text and "BREAKEVEN_PRESET" in text
    assert "break-even preset" in text  # the plain-English translation, not just the enum
    assert "+1.50 SOL" in text
    assert "4 of 5 green (80% win rate)" in text
    assert "8-second scheduler ladder" in text
    assert "unsold bags are never marked into profit" in text.lower()
    assert f"https://solscan.io/account/{W_FLASH}" in text


def test_wallet_miss_is_null_with_reason_never_zero(dossier: store.Dossier):
    text = cards.wallet_miss(W_UNKNOWN, dossier.meta, NOW)
    assert "below the activity threshold" in text
    assert "not a zero score" in text
    assert "0 SOL" not in text and "0.00" not in text  # no invented figures at all


def test_coin_card_flagged_vs_benign_heads(dossier: store.Dossier):
    hot = cards.coin_card(M_HOT, dossier.coin(M_HOT), dossier.meta, NOW)
    assert "EXIT SIGNAL" in hot
    assert "4 wallets; 3 profiled" in hot
    assert "1 BREAKEVEN_PRESET" in hot
    assert "timing q=0.03" in hot
    assert "does not prove chart management" in hot  # rule 3, welded on
    assert "crew #7" in hot and "2 rips / 5 insider dumps" in hot
    assert "not a fingerprint match" in hot

    quiet = cards.coin_card(M_QUIET, dossier.coin(M_QUIET), dossier.meta, NOW)
    assert "EXIT SIGNAL" not in quiet
    assert "clean no-signal" in quiet and "not a zero score" in quiet
    assert "LAUNCHED by fingerprinted crew #7" in quiet


def test_clean_crew_launch_reads_as_continuity_not_crime():
    """dregg_screen's rule carried over: a clean crew's reuse is continuity, never a record."""

    crew = {
        "crew_id": 3, "launched_by": 1, "dirty": 0, "n_overlap": None,
        "crew_coins": 4, "crew_rips": 0, "crew_dumps": 0,
    }
    lines = "\n".join(cards._crew_lines([crew], {"crew_ledger": {"crews": 1}}))
    assert "serial deployer" in lines and "no rips or dumps on record" in lines
    assert "LAUNCHED by fingerprinted" not in lines


def test_coin_miss_is_honest_about_scope(dossier: store.Dossier):
    text = cards.coin_miss(M_MISSING, dossier.meta, NOW)
    assert "outside the 2026-08-05..2026-08-14 corpus" in text
    assert "not a clean bill" in text


# -- lookup: gating and rate limiting -------------------------------------------------


class Clock:
    def __init__(self, now: float = NOW):
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_lookup(tmp_path: Path, index: Path | None, **kwargs) -> tuple[DossierLookup, GateState, Clock]:
    cfg = Config(
        telegram_token_file=tmp_path / "token",
        helius_key_file=tmp_path / "helius",
        db_path=tmp_path / "gate.sqlite",
        heartbeat_path=tmp_path / "heartbeat.json",
    )
    state = GateState(cfg.db_path)
    clock = Clock()
    lookup = DossierLookup(lambda: cfg, state, index_path=index, clock=clock, **kwargs)
    return lookup, state, clock


def test_unverified_gets_teaser_never_data(tmp_path: Path, fixture_index: Path):
    lookup, _, _ = make_lookup(tmp_path, fixture_index)
    for reply, mode in (lookup.reply_wallet(1, W_FLASH), lookup.reply_coin(1, M_HOT)):
        assert mode is None
        assert "verify to unlock" in reply
        assert "888,888" in reply
        assert W_FLASH not in reply and M_HOT not in reply  # the shape, not the data


def test_ejected_and_usage_and_bad_arg(tmp_path: Path, fixture_index: Path):
    lookup, state, clock = make_lookup(tmp_path, fixture_index)
    state.record_verification(9, addr(), 10**12, clock())
    assert lookup.reply_wallet(9, None) == (WALLET_USAGE_TEXT, None)
    assert lookup.reply_wallet(9, "not-base58!!") == (WALLET_USAGE_TEXT, None)
    assert "usually ending" in lookup.reply_coin(9, None)[0]
    state.set_member_status(9, "ejected", None)
    assert lookup.reply_wallet(9, W_FLASH) == (EJECTED_TEXT, None)


def test_rate_limit_shared_across_both_commands(tmp_path: Path, fixture_index: Path):
    lookup, state, clock = make_lookup(tmp_path, fixture_index, rate_per_minute=2)
    state.record_verification(9, addr(), 10**12, clock())
    state.record_verification(8, addr(), 10**12, clock())
    assert "WALLET DOSSIER" in lookup.reply_wallet(9, W_FLASH)[0]
    assert "COIN DOSSIER" in lookup.reply_coin(9, M_HOT)[0]
    capped, mode = lookup.reply_wallet(9, W_FLASH)
    assert mode is None and "capped at 2" in capped
    # Another member is not collateral damage...
    assert "WALLET DOSSIER" in lookup.reply_wallet(8, W_FLASH)[0]
    # ...and the window slides open again.
    clock.now += 61
    assert "WALLET DOSSIER" in lookup.reply_wallet(9, W_FLASH)[0]


def test_verified_member_gets_cards_and_honest_misses(tmp_path: Path, fixture_index: Path):
    lookup, state, clock = make_lookup(tmp_path, fixture_index)
    state.record_verification(9, addr(), 10**12, clock())
    assert "below the activity threshold" in lookup.reply_wallet(9, W_UNKNOWN)[0]
    assert "outside the 2026-08-05..2026-08-14 corpus" in lookup.reply_coin(9, M_MISSING)[0]
    text, mode = lookup.reply_coin(9, M_HOT)
    assert mode is None and "EXIT SIGNAL" in text and "<" not in text


def test_missing_index_is_honest_and_recovers(tmp_path: Path, fixture_index: Path):
    ghost = tmp_path / "nowhere.sqlite"
    lookup, state, clock = make_lookup(tmp_path, ghost)
    state.record_verification(9, addr(), 10**12, clock())
    assert lookup.reply_wallet(9, W_FLASH) == (UNAVAILABLE_TEXT, None)
    ghost.symlink_to(fixture_index)  # the build lands later, no restart needed
    assert "WALLET DOSSIER" in lookup.reply_wallet(9, W_FLASH)[0]


def test_default_rate_is_modest():
    assert DEFAULT_RATE_PER_MINUTE <= 10


# -- guard: the module never grows an HTML branch -------------------------------------


def test_no_parse_mode_anywhere(tmp_path: Path, fixture_index: Path):
    lookup, state, clock = make_lookup(tmp_path, fixture_index)
    state.record_verification(9, addr(), 10**12, clock())
    replies = [
        lookup.reply_wallet(1, W_FLASH),      # teaser
        lookup.reply_wallet(9, None),         # usage
        lookup.reply_wallet(9, W_FLASH),      # card
        lookup.reply_coin(9, M_QUIET),        # card
        lookup.reply_coin(9, M_MISSING),      # miss
    ]
    assert all(mode is None for _, mode in replies)
