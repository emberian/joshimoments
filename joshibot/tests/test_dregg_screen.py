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


# -- the crew-id fix: ties held whole, deterministic attribution, complete scan --------
#
# Measured before the fix (RESULT_d4m_crew_graph.md §2): the best Jaccard tied across
# 2+ crews in 44.7% of matches and the printed crew id was sqlite row order; LIMIT 200
# could drop the true best match; min_jaccard=0.10 never rejected anything. The fix
# carries the tie whole, names a deterministic representative, and scans every
# candidate. The Jaccard/overlap NUMBERS are pinned unchanged by these tests.

TIE_W = ["TieWalletA1111111111111111111111111111111",
         "TieWalletB1111111111111111111111111111111",
         "TieWalletC1111111111111111111111111111111"]
STRAY = "StrayWallet1111111111111111111111111111111"


def _tie_ledger(tmp_path: Path, *, reverse: bool = False, dirty_crew: bool = True,
                name: str = "tie.sqlite") -> Ledger:
    """Three crews whose stored fingerprints tie EXACTLY on a {W1, W2, stray} launch:
    each stored set shares {W1, W2} plus one private wallet (overlap 2, equal sizes,
    equal Jaccard). Crew 2 is the only one with recorded rips/dumps (when
    ``dirty_crew``). ``reverse`` flips every insert order — the axis the retired
    matcher's answer varied along."""

    path = tmp_path / name
    con = sqlite3.connect(path)
    con.executescript(ledger_mod._SCHEMA)
    crews = [
        (1, "TieDeployerA111111111111111111111111111111", 4, 0, 0, 0),
        (2, "TieDeployerB111111111111111111111111111111", 3, 2, 3, 1)
        if dirty_crew else (2, "TieDeployerB111111111111111111111111111111", 3, 0, 0, 0),
        (3, "TieDeployerC111111111111111111111111111111", 9, 0, 0, 0),
    ]
    coins = [("TieCoinA1pump", 1, 3), ("TieCoinB1pump", 2, 3), ("TieCoinC1pump", 3, 3)]
    sets = [(m, w) for m, _, _ in coins for w in (TIE_W[0], TIE_W[1], f"Private{m}")]
    if reverse:
        crews, coins, sets = crews[::-1], coins[::-1], sets[::-1]
    con.executemany("INSERT INTO crews VALUES (?,?,?,?,?,?)", crews)
    con.executemany("INSERT INTO crew_coins VALUES (?,?,?)", coins)
    con.executemany("INSERT INTO crew_set VALUES (?,?)", sets)
    con.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    con.commit()
    con.close()
    return Ledger(path)


def test_crew_tie_is_carried_whole_and_attribution_is_deterministic(tmp_path: Path):
    """The tie case: same CrewMatch regardless of sqlite insert/row order, all tied
    crews named, the representative the dirty one — and the measured numbers exactly
    the hand-computed values the retired matcher reported (overlap 2, union 3+3-2=4,
    Jaccard 0.5)."""

    results = []
    for reverse in (False, True):
        led = _tie_ledger(tmp_path, reverse=reverse, name=f"tie{int(reverse)}.sqlite")
        m = led.crew_match([TIE_W[0], TIE_W[1], STRAY])
        led.close()
        assert m is not None
        # the numbers: unchanged from the retired matcher, hand-checked
        assert m.jaccard == 0.5 and m.overlap == 2
        assert m.launch_set_size == 3 and m.matched_set_size == 3
        # the tie is the answer: every equally-supported crew, honestly counted
        assert m.tied_crew_ids == (1, 2, 3) and m.n_tied_crews == 3 and m.ambiguous
        assert m.n_tied_dirty == 1
        # deterministic representative: the crew with the recorded conduct, not row order
        assert m.crew_id == 2 and m.matched_mint == "TieCoinB1pump" and m.dirty
        results.append(m)
    assert results[0] == results[1]  # byte-equal across insert orders


def test_unambiguous_match_keeps_numbers_and_stays_unambiguous(mini_ledger: Ledger):
    """One stored crew, no tie: the fixture numbers are byte-unchanged and the match
    says so (tie set of exactly one)."""

    m = mini_ledger.crew_match([*CREW_W[:2], STRAY])
    assert m is not None
    assert m.jaccard == round(2 / (3 + 3 - 2), 4) and m.overlap == 2  # 0.5, unchanged
    assert m.tied_crew_ids == (1,) and m.n_tied_crews == 1 and not m.ambiguous
    assert m.n_tied_dirty == 1 and m.crew_id == 1


def test_tied_jaccard_reports_the_retired_matchers_overlap(tmp_path: Path):
    """Equal best Jaccard at DIFFERENT overlaps: the reported pair must stay the
    retired matcher's deterministic one — the largest overlap among best-Jaccard rows
    (its overlap-descending scan reported exactly that row), so no shipped statistic
    moves. Launch of 4: {W1,W2,W3,P1,P2} gives 3/6 = 0.5; {W1,W2} gives 2/4 = 0.5."""

    path = tmp_path / "ovl.sqlite"
    con = sqlite3.connect(path)
    con.executescript(ledger_mod._SCHEMA)
    con.executemany("INSERT INTO crews VALUES (?,?,?,?,?,?)", [
        (1, "OvlDeployerA111111111111111111111111111111", 2, 0, 0, 0),
        (3, "OvlDeployerC111111111111111111111111111111", 2, 0, 0, 0),
    ])
    con.executemany("INSERT INTO crew_coins VALUES (?,?,?)",
                    [("SmallCoin1pump", 1, 2), ("BigCoin1pump", 3, 5)])
    con.executemany("INSERT INTO crew_set VALUES (?,?)",
                    [("SmallCoin1pump", TIE_W[0]), ("SmallCoin1pump", TIE_W[1])]
                    + [("BigCoin1pump", w) for w in (*TIE_W, "PrivD11", "PrivE11")])
    con.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    con.commit()
    con.close()
    led = Ledger(path)
    m = led.crew_match([*TIE_W, STRAY])
    led.close()
    assert m is not None
    assert m.jaccard == 0.5 and m.overlap == 3 and m.matched_set_size == 5
    assert m.matched_mint == "BigCoin1pump" and m.crew_id == 3
    assert m.tied_crew_ids == (1, 3)  # the smaller-overlap equal-Jaccard crew still counts


def test_no_candidate_limit_can_lose_the_best_match(tmp_path: Path):
    """The retired ORDER BY overlap DESC LIMIT 200 could drop the Jaccard winner
    behind a block of 300 equal-overlap fillers (measured: 332/3,000 launches over
    the limit, 3 strictly worse answers). The scan is now complete — the winner is
    found regardless of insert position — and crew_match no longer has a truncation
    knob to mis-set."""

    import inspect

    h1, h2, q = ("HotWalletA111111111111111111111111111111",
                 "HotWalletB111111111111111111111111111111",
                 "QuietWallet11111111111111111111111111111")
    path = tmp_path / "trunc.sqlite"
    con = sqlite3.connect(path)
    con.executescript(ledger_mod._SCHEMA)
    con.executemany("INSERT INTO crews VALUES (?,?,?,?,?,?)", [
        (1, "FillerDeployer1111111111111111111111111111", 300, 0, 0, 0),
        (2, "WinnerDeployer1111111111111111111111111111", 2, 1, 0, 1),
    ])
    # 300 filler coins tied at overlap 2, Jaccard 2/12; the true winner (2/3) LAST
    for i in range(300):
        mint = f"Filler{i}pump"
        con.execute("INSERT INTO crew_coins VALUES (?,?,?)", (mint, 1, 11))
        con.executemany("INSERT INTO crew_set VALUES (?,?)",
                        [(mint, h1), (mint, h2)] + [(mint, f"Priv{i}x{k}") for k in range(9)])
    con.execute("INSERT INTO crew_coins VALUES ('Winner1pump', 2, 2)")
    con.executemany("INSERT INTO crew_set VALUES (?,?)", [("Winner1pump", q), ("Winner1pump", h1)])
    con.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    con.commit()
    con.close()
    led = Ledger(path)
    m = led.crew_match([h1, h2, q])
    led.close()
    assert m is not None
    assert m.jaccard == round(2 / 3, 4) and m.crew_id == 2 and m.matched_mint == "Winner1pump"
    assert not m.ambiguous
    # the structural pin: no limit parameter exists to reintroduce the loss
    assert "max_candidates" not in inspect.signature(Ledger.crew_match).parameters


def test_tied_dirty_crew_escalates_and_the_line_says_shared(tmp_path: Path):
    """A tie containing a dirty crew is KNOWN_CREW whichever representative is shown,
    and the postable line states the tie instead of naming one crew as if the data
    identified it."""

    led = _tie_ledger(tmp_path)
    snipes = [_tx(pre=[], post=[_tb(2, w, 1_000_000_000)]) for w in TIE_W[:2]]
    b = extract_birth_features(MINT, _create_tx(), snipes)
    s = score_launch(cheap_features_from_event(_cheap()), b, led)
    led.close()
    assert s.verdict == VERDICT_KNOWN_CREW
    assert s.crew is not None and s.crew.tied_crew_ids == (1, 2, 3)
    assert any(":tied=3:dirty_in_tie=1" in r for r in s.reasons)
    line = s.row()["tg_line"]
    assert "3 tracked crews share equally" in line and "does not single one out" in line
    assert "#1, #2, #3" in line and "#2 shown as one of them" in line
    assert "matched crew fingerprint #" not in line  # the single-crew claim is gone


def test_all_clean_tie_stays_continuity_not_a_verdict(tmp_path: Path):
    """A tie whose EVERY crew is clean is continuity, exactly as a clean single match
    is — and the note carries the whole tie set for the watch surfaces."""

    led = _tie_ledger(tmp_path, dirty_crew=False)
    snipes = [_tx(pre=[], post=[_tb(2, w, 1_000_000_000)]) for w in TIE_W[:2]]
    b = extract_birth_features(MINT, _create_tx(), snipes)
    s = score_launch(cheap_features_from_event(_cheap()), b, led)
    led.close()
    assert s.verdict == VERDICT_BUNDLED  # 3 birth-slot buyers; the crews add no record
    assert s.crew is None
    note = s.features["crew_continuity_note"]
    assert tuple(note["tied_crew_ids"]) == (1, 2, 3) and note["n_tied_dirty"] == 0


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


# -- the third stratum: the USDC-quoted curve (RESULT_third_stratum.md) -----------------

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _quote_create_tx(dev_buy: int = 10_000_000_000_000) -> dict:
    """A stratum-3 create: token side identical to standard, plus the curve's USDC
    vault leg the create transaction initializes (the corpus-validated witness)."""

    tx = _create_tx(dev_buy)
    tx["meta"]["postTokenBalances"].append(_tb(3, CURVE, 204_161_531, mint=USDC))
    return tx


def _create_event_logs(mint: str, vsol: int, quote: str) -> list[str]:
    """Real encoded CreateEvent bytes inside a well-formed pump invoke bracket."""

    import base64
    import struct

    from solders.pubkey import Pubkey

    from shitcoims_intelligence.pump_layouts import PUMP_EVENT_LAYOUTS, PUMP_PROGRAM_ID

    layout = next(la for la in PUMP_EVENT_LAYOUTS if la.event_name == "CreateEvent")
    values = {
        "name": "N", "symbol": "S", "uri": "u",
        "mint": mint, "bonding_curve": CURVE_PK, "user": DEV_PK, "creator": DEV_PK,
        "timestamp": 1_756_300_000, "virtual_token_reserves": 1_073_000_000_000_000,
        "virtual_sol_reserves": vsol, "real_token_reserves": 793_100_000_000_000,
        "token_total_supply": 1_000_000_000_000_000, "token_program": TOKEN_PK,
        "is_mayhem_mode": False, "is_cashback_enabled": False,
        "quote_mint": quote, "virtual_quote_reserves": vsol,
    }
    raw = bytearray(layout.discriminator)
    for name, spec in layout.fields:
        v = values[name]
        if spec == "string":
            encoded = str(v).encode()
            raw += struct.pack("<I", len(encoded)) + encoded
        elif spec == "pubkey":
            raw += bytes(Pubkey.from_string(str(v)))
        elif spec in ("u64", "i64"):
            raw += struct.pack("<q" if spec == "i64" else "<Q", int(v))
        elif spec == "bool":
            raw += b"\x01" if v else b"\x00"
        else:  # pragma: no cover - layout drift would fail the decode assert anyway
            raise AssertionError(f"unhandled spec {spec}")
    return [
        f"Program {PUMP_PROGRAM_ID} invoke [1]",
        "Program data: " + base64.b64encode(bytes(raw)).decode("ascii"),
        f"Program {PUMP_PROGRAM_ID} success",
    ]


# Valid base58 pubkeys the encoder can round-trip (the fixture MINT above is not one).
def _pk(seed: int) -> str:
    from solders.pubkey import Pubkey

    return str(Pubkey.from_bytes(bytes((seed,)) * 32))


CURVE_PK, DEV_PK, TOKEN_PK = _pk(2), _pk(3), _pk(4)


def test_quote_curve_detected_from_birth_legs():
    b = extract_birth_features(MINT, _quote_create_tx())
    assert b.born_standard  # token side is indistinguishable from standard
    assert b.quote_curve and b.curve_quote_mint == USDC
    assert b.curve_seed_source == "birth_legs" and b.curve_seed_vsol is None
    # a USDC leg NOT owned by the curve (someone paying fees in USDC) is not a witness
    tx = _create_tx()
    tx["meta"]["postTokenBalances"].append(_tb(3, SNIPER, 999, mint=USDC))
    assert not extract_birth_features(MINT, tx).quote_curve


def test_quote_curve_detected_from_create_event_logs():
    from dregg_screen.features import detect_curve_seed

    mint_pk = _pk(7)
    tx = _tx([], [_tb(1, CURVE, 1_000_000_000_000_000)])
    tx["meta"]["logMessages"] = _create_event_logs(mint_pk, 4_292_000_000, USDC)
    got = detect_curve_seed(mint_pk, tx, CURVE)
    assert got == (True, USDC, "create_event", 4_292_000_000)
    # the standard seed through the same channel stays standard
    wsol = "So11111111111111111111111111111111111111112"
    tx["meta"]["logMessages"] = _create_event_logs(mint_pk, 30_000_000_000, wsol)
    assert detect_curve_seed(mint_pk, tx, CURVE) == (False, None, "create_event", 30_000_000_000)


def test_quote_curve_never_mints_clean(mini_ledger: Ledger):
    """The registered ship rule (REGISTRATION_third_stratum.md T4): all five gates
    pass, but CLEAN names a measured precision claim and none was measured on this
    stratum — UNSCORED with the gates stated, outside the validated population."""

    b = extract_birth_features(MINT, _quote_create_tx())
    s = score_launch(cheap_features_from_event(_cheap()), b, mini_ledger,
                     base_rates=_rates(mini_ledger))
    assert s.verdict == VERDICT_UNSCORED
    assert s.reasons == ("quote_curve_screen_not_measured", "five_gates_passed")
    assert not s.in_validated_population
    assert "quote_curve:usdc:outside_validated_population" in s.population_notes
    assert s.features["quote_curve"] is True
    assert s.features["curve_quote_mint"] == USDC
    line = s.row()["tg_line"]
    assert "UNSCORED" in line and "CLEAN" not in line
    # the B1 precision sentence never rides a quote-curve line
    assert "Screen precision" not in line


def test_quote_curve_keeps_feature_fact_verdicts(mini_ledger: Ledger):
    """Birth-slot facts are valid on the stratum — a bundled quote-curve launch is
    BUNDLED, not shrugged into UNSCORED."""

    others = "Wal%s1111111111111111111111111111111111111"
    snipes = [_tx(pre=[], post=[_tb(2, others % i, 1_000_000_000)]) for i in range(3)]
    b = extract_birth_features(MINT, _quote_create_tx(), snipes)
    s = score_launch(cheap_features_from_event(_cheap()), b, mini_ledger)
    assert s.verdict == VERDICT_BUNDLED and not s.in_validated_population


def test_quote_seed_suspicion_is_note_only_until_hydration(mini_ledger: Ledger):
    payload = _cheap()
    payload["vSolInBondingCurve"] = 4.792
    payload["solAmount"] = 0.5
    c = cheap_features_from_event(payload)
    assert c.v_sol_seed_est == pytest.approx(4.292) and c.quote_seed_suspected
    s = score_launch(c, None, mini_ledger, unscored_reason="budget:daily_helius_ceiling")
    assert "vendor_seed:quote_curve_suspected:unverified" in s.population_notes
    assert not s.in_validated_population
    # a standard frame carries no suspicion (and hydration clears it either way)
    payload["vSolInBondingCurve"] = 30.493827158
    assert not cheap_features_from_event(payload).quote_seed_suspected
    b = extract_birth_features(MINT, _create_tx())
    s2 = score_launch(cheap_features_from_event(payload), b, mini_ledger)
    assert s2.verdict == VERDICT_CLEAN and s2.in_validated_population


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
