from decimal import Decimal
from pathlib import Path

from shitcoims_sentinel.config import RugConfig
from shitcoims_sentinel.domain import (
    PUMP_MINT_AUTHORITY,
    ExitQuote,
    MintSafety,
    PoolSnapshot,
    TokenHolding,
    utc_now,
)
from shitcoims_sentinel.rug_detector import RugDetector
from shitcoims_sentinel.storage import StateStore


def config() -> RugConfig:
    return RugConfig(30, 40, 5, 20, 0.1, 20)


def test_liquidity_drop_needs_quote_collapse_and_confirmation(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state.json")
    state.set(
        "pool_baselines",
        "mint",
        value={"pair_address": "pair", "reserve_value": "100", "reserve_unit": "SOL"},
    )
    state.set("quote_baselines", "mint", value="1")
    holding = TokenHolding("mint", 1_000_000, 6, ("account",), ("program",))
    pool = PoolSnapshot(
        "pair", "pumpfun", "mint", "sol", Decimal("1000"), Decimal("50"), "SOL", None, utc_now()
    )
    quote = ExitQuote("mint", 1_000_000, 700_000_000, None, None, "metis", utc_now())
    signal = RugDetector(config(), state).assess(
        holding=holding,
        pool=pool,
        mint_safety=MintSafety(None, None, 1_000_000, 6, "program"),
        quote=quote,
    )
    assert signal.emergency
    assert signal.needs_confirmation
    assert signal.liquidity_drop_pct == Decimal("50.0")


def test_liquidity_api_anomaly_with_intact_quote_does_not_sell(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state.json")
    state.set(
        "pool_baselines",
        "mint",
        value={"pair_address": "pair", "reserve_value": "100", "reserve_unit": "SOL"},
    )
    state.set("quote_baselines", "mint", value="1")
    holding = TokenHolding("mint", 1_000_000, 6, ("account",), ("program",))
    quote = ExitQuote("mint", 1_000_000, 950_000_000, None, None, "metis", utc_now())
    signal = RugDetector(config(), state).assess(
        holding=holding,
        pool=None,
        mint_safety=MintSafety(None, None, 1_000_000, 6, "program"),
        quote=quote,
    )
    assert not signal.emergency


def test_active_mint_supply_flood_is_emergency(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state.json")
    state.set("supply_baselines", "mint", value=100)
    holding = TokenHolding("mint", 1_000_000, 6, ("account",), ("program",))
    signal = RugDetector(config(), state).assess(
        holding=holding,
        pool=None,
        mint_safety=MintSafety("authority", None, 110, 6, "program"),
        quote=None,
    )
    assert signal.emergency
    assert "supply grew" in (signal.reason or "")


def test_missing_providers_are_unknown_not_zero(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state.json")
    state.set(
        "pool_baselines",
        "mint",
        value={"pair_address": "pair", "reserve_value": "100", "reserve_unit": "SOL"},
    )
    state.set("quote_baselines", "mint", value="1")
    holding = TokenHolding("mint", 1_000_000, 6, ("account",), ("program",))
    signal = RugDetector(config(), state).assess(
        holding=holding,
        pool=None,
        mint_safety=MintSafety(None, None, 1_000_000, 6, "program"),
        quote=None,
    )
    assert not signal.emergency
    assert signal.liquidity_drop_pct is None


def test_canonical_pump_mint_authority_is_not_treated_as_creator_control(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state.json")
    state.set("supply_baselines", "mint", value=100)
    holding = TokenHolding("mint", 1_000_000, 6, ("account",), ("program",))
    signal = RugDetector(config(), state).assess(
        holding=holding,
        pool=None,
        mint_safety=MintSafety(PUMP_MINT_AUTHORITY, None, 110, 6, "program"),
        quote=None,
    )
    assert not signal.emergency
