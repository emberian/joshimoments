"""dregg_screen: offline unit tests plus the corpus feature-parity gate.

The parity tests are the load-bearing ones. The live screen only inherits B1's
validated precision numbers if its feature extractor computes THE SAME FUNCTION as
``studies/operator_crime.py``'s SQL — so those tests take real corpus birth slots,
re-shape them into Helius wire format, run the live extractor, and hold the outputs
equal to the study's own ``panel.parquet`` row. They are skipped (not passed) when the
corpus artifacts are absent, so a green run on a machine without the data never
impersonates the proof.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from dregg_screen import ledger as ledger_mod
from dregg_screen.features import (
    cheap_features_from_event,
    extract_birth_features,
    mint_legs,
)
from dregg_screen.hydrate import BudgetExhausted, DailyBudget, Hydrator
from dregg_screen.ledger import Ledger
from dregg_screen.score import (
    VERDICT_BUNDLED,
    VERDICT_CLEAN,
    VERDICT_KNOWN_CREW,
    VERDICT_NOT_CLEAN,
    VERDICT_UNSCORED,
    score_launch,
)

REPO = Path(__file__).resolve().parent.parent
FRESH = REPO / "studies" / "data" / "operator_crime_fresh"
COMBINED = FRESH / "combined"

MINT = "MintPumpPumpPumpPumpPumpPumpPumpPumpPumppump"
CURVE = "CurveOwnerAccount11111111111111111111111111"
DEV = "DeployerWallet1111111111111111111111111111"
SNIPER = "SniperWallet111111111111111111111111111111"


def _tb(idx: int, owner: str, amount: int, decimals: int = 6, mint: str = MINT) -> dict:
    return {
        "accountIndex": idx,
        "mint": mint,
        "owner": owner,
        "uiTokenAmount": {"amount": str(amount), "decimals": decimals},
    }


def _tx(pre: list[dict], post: list[dict], err=None) -> dict:
    return {"meta": {"err": err, "preTokenBalances": pre, "postTokenBalances": post}}


def _create_tx(dev_buy: int = 10_000_000_000_000) -> dict:
    """A standard create: curve seeded with 1e15 minus the dev buy, dev buy positive."""

    return _tx([], [_tb(1, CURVE, 1_000_000_000_000_000 - dev_buy), _tb(2, DEV, dev_buy)])


# -- feature extraction ----------------------------------------------------------------


def test_mint_legs_nets_inside_the_row():
    tx = _tx(
        pre=[_tb(1, CURVE, 500), _tb(2, DEV, 100), _tb(3, SNIPER, 40)],
        post=[_tb(1, CURVE, 450), _tb(2, DEV, 100)],  # account 3 closed, 2 unchanged
    )
    legs = {leg.owner: leg.delta_raw for leg in mint_legs(tx, MINT)}
    assert legs == {CURVE: -50, SNIPER: -40}  # zero delta dropped, closed account negated


def test_mint_legs_ignores_other_mints():
    tx = _tx(pre=[], post=[_tb(1, CURVE, 5, mint="So11111111111111111111111111111111111111112")])
    assert mint_legs(tx, MINT) == []


def test_extract_birth_standard_create_with_snipe():
    snipe = _tx(pre=[_tb(1, CURVE, 990_000_000_000_000)],
                post=[_tb(1, CURVE, 980_000_000_000_000), _tb(2, SNIPER, 10_000_000_000_000)])
    b = extract_birth_features(MINT, _create_tx(), [snipe])
    assert b.born_standard and b.minted_raw == 1_000_000_000_000_000 and b.decimals == 6
    assert b.curve_owner == CURVE and b.deployer == DEV
    assert b.dev_buy_raw == 10_000_000_000_000 and b.dev_buy_share == pytest.approx(0.01)
    assert b.n_snipers == 2 and set(b.snipers) == {DEV, SNIPER}
    assert b.snipers_ex_deployer == (SNIPER,)


def test_extract_birth_no_dev_buy():
    tx = _tx([], [_tb(1, CURVE, 1_000_000_000_000_000)])
    b = extract_birth_features(MINT, tx)
    assert b.born_standard and b.deployer is None and b.dev_buy_raw == 0 and b.n_snipers == 0


def test_extract_birth_failed_same_slot_tx_is_not_a_sniper():
    failed = _tx(pre=[], post=[_tb(2, SNIPER, 1_000)], err={"InstructionError": [0, {}]})
    b = extract_birth_features(MINT, _create_tx(), [failed])
    assert b.n_snipers == 1 and set(b.snipers) == {DEV}


def test_extract_birth_nonstandard_curve():
    tx = _tx([], [_tb(1, CURVE, 10**18, decimals=9)])  # the 9-decimal impostor shape
    b = extract_birth_features(MINT, tx)
    assert not b.born_standard


def test_cheap_features_from_observed_frame_shape():
    payload = {
        "signature": "sig111", "mint": MINT, "traderPublicKey": DEV, "txType": "create",
        "initialBuy": 17376518.132293, "solAmount": 0.5, "bondingCurveKey": CURVE,
        "vTokensInBondingCurve": 1055623481.867707, "vSolInBondingCurve": 30.493827158,
        "marketCapSol": 30.6, "name": "N", "symbol": "S", "uri": "u",
        "is_mayhem_mode": False, "pool": "pump",
    }
    c = cheap_features_from_event(payload)
    assert c.dev_buy_raw_est == 17_376_518_132_293  # vendor tokens -> raw, exact
    assert c.creator == DEV and c.signature == "sig111" and not c.is_mayhem_mode


# -- the mini crime ledger -------------------------------------------------------------

RIPPER = "RipperDeployer11111111111111111111111111111"
CREW_W = ["CrewWalletA1111111111111111111111111111111",
          "CrewWalletB1111111111111111111111111111111",
          "CrewWalletC1111111111111111111111111111111"]


@pytest.fixture()
def mini_ledger(tmp_path: Path) -> Ledger:
    path = tmp_path / "ledger.sqlite"
    con = sqlite3.connect(path)
    con.executescript(ledger_mod._SCHEMA)
    con.execute("INSERT INTO deployer_history VALUES (?,?,?,?,?,?)", (RIPPER, 7, 3, 5, 0, 1756300000))
    con.execute("INSERT INTO sniper_counts VALUES (?,?)", (CREW_W[0], 12))
    con.execute("INSERT INTO crews VALUES (1,?,4,2,3,1)", (RIPPER,))
    con.execute("INSERT INTO crew_coins VALUES ('PriorMintpump', 1, 3)")
    con.executemany("INSERT INTO crew_set VALUES ('PriorMintpump', ?)", [(w,) for w in CREW_W])
    meta = {
        "schema_version": 1, "built_at": "2026-08-29T00:00:00+00:00",
        "corpus_span": ["2026-08-05", "2026-08-28"],
        "validation": {
            "validated_span": "2026-08-26..28 (seeded history, B1)",
            "screen_seeded": {
                "is_rip": {"base_rate": 0.00528, "clean_precision": 1.0,
                           "clean_ci": [0.9995, 1.0], "admit_rate": 0.0851},
                "collapse": {"base_rate": 0.00838, "clean_precision": 0.99974,
                             "clean_ci": [0.9991, 0.9999], "admit_rate": 0.0851},
            },
        },
    }
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
    con.commit()
    con.close()
    return Ledger(path)


def _cheap(creator: str = DEV, initial_buy: float = 10_000_000.0) -> dict:
    return {"signature": "sig", "mint": MINT, "traderPublicKey": creator,
            "initialBuy": initial_buy, "name": "N", "symbol": "TST", "pool": "pump"}


def _rates(ledger: Ledger) -> dict:
    from dregg_screen.score import base_rates_from_ledger

    return base_rates_from_ledger(ledger)


def test_verdict_clean(mini_ledger: Ledger):
    b = extract_birth_features(MINT, _create_tx())
    s = score_launch(cheap_features_from_event(_cheap()), b, mini_ledger,
                     base_rates=_rates(mini_ledger))
    assert s.verdict == VERDICT_CLEAN and s.in_validated_population
    line = s.row()["tg_line"]
    assert "CLEAN" in line and "rank risk" in line and "99.97%" in line
    assert "scam" not in line.lower() and "rugger" not in line.lower()


def test_verdict_bundled(mini_ledger: Ledger):
    others = "Wal%s1111111111111111111111111111111111111"
    snipes = [
        _tx(pre=[], post=[_tb(2, others % i, 1_000_000_000)]) for i in range(3)
    ]
    b = extract_birth_features(MINT, _create_tx(), snipes)
    s = score_launch(cheap_features_from_event(_cheap()), b, mini_ledger)
    assert s.verdict == VERDICT_BUNDLED and b.n_snipers == 4
    assert "4 buyers in the birth slot" in s.row()["tg_line"]


def test_verdict_known_crew_by_fingerprint(mini_ledger: Ledger):
    snipes = [_tx(pre=[], post=[_tb(2, w, 1_000_000_000)]) for w in CREW_W[:2]]
    b = extract_birth_features(MINT, _create_tx(), snipes)
    s = score_launch(cheap_features_from_event(_cheap()), b, mini_ledger)
    assert s.verdict == VERDICT_KNOWN_CREW
    assert s.crew is not None and s.crew.crew_id == 1 and s.crew.overlap == 2
    assert s.crew.jaccard == pytest.approx(2 / 3, abs=1e-4)  # {2 shared} / {2+3-2... }
    line = s.row()["tg_line"]
    assert "crew fingerprint #1" in line and "Jaccard" in line
    assert "scam" not in line.lower()


def test_verdict_known_crew_by_deployer_record_needs_no_hydration(mini_ledger: Ledger):
    s = score_launch(cheap_features_from_event(_cheap(creator=RIPPER)), None, mini_ledger)
    assert s.verdict == VERDICT_KNOWN_CREW and not s.hydrated
    assert any(r.startswith("deployer_record") for r in s.reasons)
    assert "3 rips" in s.row()["tg_line"]


def test_verdict_known_crew_by_recidivist_sniper(mini_ledger: Ledger):
    snipe = _tx(pre=[], post=[_tb(2, CREW_W[0], 1_000_000_000)])
    b = extract_birth_features(MINT, _create_tx(), [snipe])
    s = score_launch(cheap_features_from_event(_cheap()), b, mini_ledger)
    assert s.verdict == VERDICT_KNOWN_CREW
    assert any(r.startswith("recidivist_sniper") for r in s.reasons)


def test_verdict_not_clean_dev_buy(mini_ledger: Ledger):
    b = extract_birth_features(MINT, _create_tx(dev_buy=50_000_000_000_000))  # 5%
    s = score_launch(cheap_features_from_event(_cheap(initial_buy=50_000_000.0)), b, mini_ledger)
    assert s.verdict == VERDICT_NOT_CLEAN


def test_verdict_unscored_budget_keeps_cheap_features(mini_ledger: Ledger):
    s = score_launch(cheap_features_from_event(_cheap()), None, mini_ledger,
                     unscored_reason="budget:daily_helius_ceiling")
    assert s.verdict == VERDICT_UNSCORED
    assert "budget:daily_helius_ceiling" in s.reasons and "cheap_gates_passed" in s.reasons


def test_no_dev_buy_is_flagged_outside_population(mini_ledger: Ledger):
    tx = _tx([], [_tb(1, CURVE, 1_000_000_000_000_000)])
    b = extract_birth_features(MINT, tx)
    s = score_launch(cheap_features_from_event(_cheap(initial_buy=0.0)), b, mini_ledger)
    assert s.verdict == VERDICT_CLEAN and not s.in_validated_population
    assert "no_dev_buy:outside_validated_population" in s.population_notes
    assert "Outside the validated population" in s.row()["tg_line"]


def test_mayhem_flag_is_note_when_unverified_and_gone_when_hydrated_standard(mini_ledger: Ledger):
    payload = _cheap()
    payload["is_mayhem_mode"] = True
    # Unhydrated: the flag is an honest "curve unverified" population note.
    s = score_launch(cheap_features_from_event(payload), None, mini_ledger,
                     unscored_reason="policy:mayhem_flag_nonstandard_curve")
    assert s.verdict == VERDICT_UNSCORED
    assert any(n.startswith("vendor_flag:is_mayhem_mode") for n in s.population_notes)
    # Hydrated and born standard: minted_raw is the authority, the note disappears.
    b = extract_birth_features(MINT, _create_tx())
    s2 = score_launch(cheap_features_from_event(payload), b, mini_ledger)
    assert s2.verdict == VERDICT_CLEAN and s2.in_validated_population
    assert s2.features["is_mayhem_mode"] is True


def test_partial_birth_slot_cannot_mint_clean(mini_ledger: Ledger):
    b = extract_birth_features(MINT, _create_tx(), partial=True)
    s = score_launch(cheap_features_from_event(_cheap()), b, mini_ledger)
    assert s.verdict == VERDICT_UNSCORED and "birth_slot_partial" in s.reasons


# -- budget and hydrator ---------------------------------------------------------------


def test_budget_persists_and_guards(tmp_path: Path):
    p = tmp_path / "budget.json"
    b = DailyBudget(ceiling=2, path=p)
    b.guard()
    b.spend()
    b.guard()
    b.spend()
    with pytest.raises(BudgetExhausted):
        b.guard()
    b2 = DailyBudget(ceiling=2, path=p)  # a restart must not forget the spend
    with pytest.raises(BudgetExhausted):
        b2.guard()


def test_hydrator_birth_slot_flow():
    create_sig, snipe_sig = "createSig", "snipeSig"
    responses = {
        "getTransaction": {
            create_sig: {"slot": 100, **_create_tx()},
            snipe_sig: {"slot": 100, **_tx(pre=[], post=[_tb(2, SNIPER, 5)])},
        },
        "getSignaturesForAddress": [
            [{"signature": "laterSig", "slot": 105, "err": None},
             {"signature": "failedSig", "slot": 100, "err": {"x": 1}},
             {"signature": snipe_sig, "slot": 100, "err": None},
             {"signature": create_sig, "slot": 100, "err": None}],
        ],
    }
    calls: list[str] = []

    async def post(_url: str, body: dict) -> dict:
        calls.append(body["method"])
        if body["method"] == "getTransaction":
            return {"result": responses["getTransaction"][body["params"][0]]}
        return {"result": responses["getSignaturesForAddress"][0]}

    hyd = Hydrator(budget=DailyBudget(ceiling=100), post=post)
    slot = asyncio.run(hyd.birth_slot(MINT, create_sig))
    assert slot.slot == 100 and len(slot.same_slot_txs) == 1 and not slot.partial
    assert slot.requests == 3  # create + signatures + one same-slot tx; the failed sig skipped
    b = extract_birth_features(MINT, slot.create_tx, slot.same_slot_txs, partial=slot.partial)
    assert b.n_snipers == 2 and SNIPER in b.snipers


def test_hydrator_budget_exhaustion_propagates():
    async def post(_url: str, body: dict) -> dict:  # pragma: no cover - never reached
        raise AssertionError("should not be called")

    hyd = Hydrator(budget=DailyBudget(ceiling=0), post=post)
    with pytest.raises(BudgetExhausted):
        asyncio.run(hyd.birth_slot(MINT, "sig"))


# -- CORPUS FEATURE PARITY (the gate that makes the validated numbers transferable) ----

needs_corpus = pytest.mark.skipif(
    not (FRESH / "panel.parquet").exists() or not (COMBINED / "panel.parquet").exists(),
    reason="operator_crime_fresh corpus artifacts not present",
)


def _reconstruct_helius_txs(rows) -> list[dict]:
    """Re-shape corpus ledger rows (one per netted token-account leg) into Helius wire
    form: a positive leg becomes a post-only balance, a negative leg a pre-only one.
    The extractor nets pre/post per accountIndex, so this round-trips exactly."""

    txs = []
    for _, tx_rows in rows.groupby("tx_index"):
        pre, post = [], []
        for i, r in enumerate(tx_rows.itertuples()):
            entry = _tb(i, r.owner, abs(int(r.delta_raw)), decimals=int(r.decimals), mint=r.mint)
            (post if r.delta_raw > 0 else pre).append(entry)
        txs.append(_tx(pre=pre, post=post))
    return txs


@needs_corpus
def test_birth_feature_parity_on_real_corpus_slots():
    """The live extractor must reproduce panel.parquet's birth-slot features exactly."""

    import duckdb
    import pandas as pd

    panel = pd.read_parquet(
        FRESH / "panel.parquet",
        columns=["mint", "deployer", "birth_slot", "birth_time", "n_snipers",
                 "dev_buy_raw", "n_birth_legs"],
    )
    day = FRESH / "ledger" / "day=2026-08-27.parquet"
    lo = pd.Timestamp("2026-08-27", tz="UTC").timestamp()
    hi = lo + 86_400
    pool = panel[(panel["birth_time"] >= lo) & (panel["birth_time"] < hi)]
    sample = pd.concat([
        pool[pool["n_snipers"] == 0].head(3),
        pool[pool["n_snipers"] == 1].head(4),
        pool[pool["n_snipers"].between(2, 5)].head(4),
        pool[pool["n_snipers"] >= 8].head(3),
    ])
    assert len(sample) >= 10

    con = duckdb.connect()
    con.execute("SET threads=4")
    con.register("sample", sample[["mint", "birth_slot"]])
    rows = con.execute(
        f"""SELECT l.mint, l.block_slot, l.tx_index, l.owner, l.delta_raw, l.decimals
            FROM read_parquet('{day}') l JOIN sample s
              ON l.mint = s.mint AND l.block_slot = s.birth_slot
            ORDER BY l.mint, l.tx_index"""
    ).df()

    checked = 0
    for row in sample.itertuples():
        mine = rows[rows["mint"] == row.mint]
        if mine.empty:
            continue
        txs = _reconstruct_helius_txs(mine)
        create, others = txs[0], txs[1:]  # min tx_index IS the create: the mint cannot
        #                                    be touched before it exists
        b = extract_birth_features(row.mint, create, others)
        assert b.born_standard, row.mint
        assert b.n_snipers == row.n_snipers, (row.mint, b.n_snipers, row.n_snipers)
        assert b.dev_buy_raw == row.dev_buy_raw, row.mint
        assert b.deployer == (row.deployer if isinstance(row.deployer, str) else None), row.mint
        assert b.n_birth_legs == row.n_birth_legs, row.mint
        checked += 1
    assert checked >= 10


@needs_corpus
def test_history_feature_parity_via_cutoff_ledger(tmp_path: Path):
    """A ledger built with cutoff = a corpus coin's birth_time must reproduce the
    panel's strictly-causal prior_* columns and sniper_prior_max for that coin."""

    import pandas as pd

    panel = pd.read_parquet(COMBINED / "panel.parquet")
    snipers = pd.read_parquet(COMBINED / "snipers.parquet")

    fresh_lo = pd.Timestamp("2026-08-27", tz="UTC").timestamp()
    pool = panel[(panel["birth_time"] >= fresh_lo) & panel["deployer"].notna()
                 & (panel["prior_launches"] > 0)]
    # Ties break exact parity (the panel orders same-second events by mint); exclude
    # coins whose deployer or snipers have any same-second sibling appearance.
    births_by_dep = panel.groupby(["deployer", "birth_time"]).size()
    sn_by_wallet_t = snipers.groupby(["owner", "birth_time"]).size()

    checked = 0
    for row in pool.sample(n=min(60, len(pool)), random_state=7).itertuples():
        if checked >= 4:
            break
        if births_by_dep.get((row.deployer, row.birth_time), 0) > 1:
            continue
        my_snipers = snipers[snipers["mint"] == row.mint]["owner"]
        if any(sn_by_wallet_t.get((w, row.birth_time), 0) > 1 for w in my_snipers):
            continue
        out = tmp_path / f"cutoff-{checked}.sqlite"
        ledger_mod.build(COMBINED / "panel.parquet", COMBINED / "snipers.parquet", out,
                         cutoff=float(row.birth_time))
        led = Ledger(out)
        h = led.deployer_history(row.deployer)
        assert h.launches == row.prior_launches, row.mint
        assert h.rips == row.prior_rips, row.mint
        assert h.dumps == row.prior_dumps, row.mint
        assert led.sniper_prior_max(list(my_snipers)) == row.sniper_prior_max, row.mint
        led.close()
        checked += 1
    assert checked >= 3
