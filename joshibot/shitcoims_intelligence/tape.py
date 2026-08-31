"""Event-time trade tape. The numeric door MF opened and we left shut.

Helius *enhanced* txs (tokenTransfers + nativeTransfers) reconstruct a full
pool tape. Our stored ``wallet_transaction`` rows are a *watched-wallet*
projection of the same idea. Both collapse to ``TapePrint`` then to the
early_coin-shaped feature bag the sieve already understands.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .numerics import concentration, hhi


@dataclass(frozen=True, slots=True)
class TapePrint:
    ts: int
    mint: str
    wallet: str
    side: str
    quote_sol: float
    base: float


def prints_from_wallet_payload(
    payload: Mapping[str, Any], *, wallet: str, ts: int | None = None
) -> tuple[TapePrint, ...]:
    """Project one stored wallet_transaction payload into prints."""

    if payload.get("succeeded") is False:
        return ()
    stamp = ts if ts is not None else _as_int(payload.get("slot")) or 0
    deltas = payload.get("token_deltas")
    if not isinstance(deltas, Sequence) or isinstance(deltas, (str, bytes)):
        return ()
    sol_abs = abs(_as_int(payload.get("sol_delta_lamports")) or 0) / 1_000_000_000
    prints: list[TapePrint] = []
    token_legs = [delta for delta in deltas if isinstance(delta, Mapping) and delta.get("mint")]
    if not token_legs:
        return ()
    # A transaction carries ONE native SOL delta. When it moves several mints — a route, a
    # multi-hop swap, an arbitrage — there is no way to attribute that single number to a
    # particular leg, and splitting it evenly invents a per-leg price for every one of them.
    # A fabricated price is worse than a missing print, because a study cannot tell the two
    # apart: it looks like a measured trade. Refuse the row instead, so the ambiguity stays
    # visible as a smaller n rather than becoming confident noise.
    if len(token_legs) > 1:
        return ()
    quote_each = sol_abs
    for delta in token_legs:
        raw = _as_int(delta.get("raw_delta"))
        if raw is None or raw == 0:
            continue
        decimals = _as_int(delta.get("decimals")) or 0
        base = abs(raw) / (10 ** decimals) if decimals >= 0 else float(abs(raw))
        side = "buy" if raw > 0 else "sell"
        prints.append(
            TapePrint(
                ts=stamp,
                mint=str(delta.get("mint")),
                wallet=wallet,
                side=side,
                quote_sol=quote_each,
                base=base,
            )
        )
    return tuple(prints)


def prints_from_enhanced_tx(
    tx: Mapping[str, Any], *, mint: str, pool: str | None = None
) -> tuple[TapePrint, ...]:
    """Helius Enhanced shape (roommate onchain.reconstruct_trades), no import."""

    stamp = _as_int(tx.get("timestamp") or tx.get("blockTime"))
    if stamp is None:
        return ()
    trader = str(tx.get("feePayer") or tx.get("fee_payer") or "")
    legs = [
        leg
        for leg in (tx.get("tokenTransfers") or tx.get("token_transfers") or [])
        if isinstance(leg, Mapping) and str(leg.get("mint") or "") == mint
    ]
    if not legs:
        return ()
    chosen = None
    side = ""
    for leg in legs:
        if str(leg.get("toUserAccount") or "") == trader:
            chosen, side = leg, "buy"
            break
        if str(leg.get("fromUserAccount") or "") == trader:
            chosen, side = leg, "sell"
            break
    if chosen is None:
        chosen = max(legs, key=lambda leg: float(leg.get("tokenAmount") or 0))
        from_pool = pool and str(chosen.get("fromUserAccount") or "") == pool
        side = "buy" if from_pool else "sell"
    base = float(chosen.get("tokenAmount") or 0)
    if base <= 0:
        return ()
    natives = tx.get("nativeTransfers") or tx.get("native_transfers") or []
    sol = 0.0
    for native in natives:
        if not isinstance(native, Mapping):
            continue
        if trader in {
            str(native.get("fromUserAccount") or ""),
            str(native.get("toUserAccount") or ""),
        }:
            sol += abs(int(native.get("amount") or 0)) / 1_000_000_000
    return (
        TapePrint(
            ts=stamp,
            mint=mint,
            wallet=trader,
            side=side,
            quote_sol=sol,
            base=base,
        ),
    )


def prints_from_history_tx(tx: Mapping[str, Any], *, mint: str) -> tuple[TapePrint, ...]:
    """Project one full jsonParsed (or Enhanced) history tx into mint prints.

    Fee-payer is the trader, matching ``prints_from_enhanced_tx``. Enhanced
    envelopes (tokenTransfers / nativeTransfers) are delegated unchanged.
    """

    if tx.get("tokenTransfers") or tx.get("token_transfers"):
        return prints_from_enhanced_tx(tx, mint=mint)

    meta = tx.get("meta")
    if not isinstance(meta, dict) or meta.get("err") is not None:
        return ()
    stamp = _as_int(tx.get("blockTime") or tx.get("timestamp"))
    if stamp is None:
        return ()
    keys = _history_account_keys(tx)
    if not keys:
        return ()
    trader = keys[0]
    pre_raw, pre_decimals = _owner_mint_raw(meta.get("preTokenBalances"), mint, trader)
    post_raw, post_decimals = _owner_mint_raw(meta.get("postTokenBalances"), mint, trader)
    delta = post_raw - pre_raw
    if delta == 0:
        return ()
    decimals = post_decimals if post_decimals >= 0 else pre_decimals
    base = abs(delta) / (10**decimals) if decimals >= 0 else float(abs(delta))
    if base <= 0:
        return ()
    quote = _fee_payer_sol_abs(meta, keys)
    return (
        TapePrint(
            ts=stamp,
            mint=mint,
            wallet=trader,
            side="buy" if delta > 0 else "sell",
            quote_sol=quote,
            base=base,
        ),
    )


def holder_features(balances: Sequence[float]) -> dict[str, float | int]:
    """Concentration bag the holder sieve already knows how to read."""

    xs = [value for value in balances if value > 0]
    if not xs:
        return {"holder_count": 0}
    conc = concentration(xs)
    return {
        "holder_count": conc.holders,
        "holder_top1": conc.top1,
        "holder_hhi": conc.hhi,
        "holder_nakamoto": conc.nakamoto,
        "holder_gini": conc.gini,
        "holder_top10": conc.top10,
    }


_COUNT_KEYS = frozenset(
    {
        "trade_count",
        "unique_wallet_count",
        "holder_count",
        "buy_count",
        "sell_count",
    }
)


def merge_feature_bags(*bags: Mapping[str, Any] | None) -> dict[str, Any]:
    """Union bags. None never overwrites. Larger counts win; other keys later-win."""

    merged: dict[str, Any] = {}
    for bag in bags:
        if not bag:
            continue
        for key, value in dict(bag).items():
            if value is None:
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = value
                continue
            if (
                key in _COUNT_KEYS
                and isinstance(existing, int | float)
                and isinstance(value, int | float)
                and not isinstance(existing, bool)
                and not isinstance(value, bool)
            ):
                if value > existing:
                    merged[key] = value
                continue
            merged[key] = value
    return merged


def features_from_prints(prints: Sequence[TapePrint]) -> dict[str, float | int | None]:
    """early_coin-shaped bag so organic_verdict can run without Pump logs."""

    if not prints:
        return {"trade_count": 0, "unique_wallet_count": 0}
    wallets = [print_.wallet for print_ in prints]
    unique = set(wallets)
    buys = sum(1 for print_ in prints if print_.side == "buy")
    sells = len(prints) - buys
    by_wallet: dict[str, float] = defaultdict(float)
    for print_ in prints:
        by_wallet[print_.wallet] += max(print_.quote_sol, 0.0)
    volumes = list(by_wallet.values())
    total = sum(volumes)
    top_share = (max(volumes) / total) if total > 0 else None
    repeats = sum(1 for wallet, count in Counter(wallets).items() if count >= 2)
    return {
        "trade_count": len(prints),
        "unique_wallet_count": len(unique),
        "buy_count": buys,
        "sell_count": sells,
        "top_wallet_quote_share": top_share,
        "wallet_volume_hhi": hhi(volumes) if total > 0 else None,
        "returning_wallet_ratio": (repeats / len(unique)) if unique else 0.0,
    }


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def _as_int_loose(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def _history_account_keys(tx: Mapping[str, Any]) -> list[str]:
    transaction = tx.get("transaction")
    if not isinstance(transaction, dict):
        return []
    message = transaction.get("message")
    if not isinstance(message, dict):
        return []
    keys: list[str] = []
    for value in message.get("accountKeys") or []:
        key = value.get("pubkey") if isinstance(value, dict) else value
        if isinstance(key, str):
            keys.append(key)
    return keys


def _owner_mint_raw(values: Any, mint: str, owner: str) -> tuple[int, int]:
    """Sum raw token amounts for ``owner``/``mint``. Missing rows are zero.

    Decimals is -1 when no row was seen so a later row can fill it.
    """

    if not isinstance(values, list):
        return 0, -1
    total = 0
    decimals = -1
    for entry in values:
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("mint") or "") != mint:
            continue
        if str(entry.get("owner") or "") != owner:
            continue
        ui = entry.get("uiTokenAmount")
        surface = ui if isinstance(ui, Mapping) else entry
        raw = _as_int_loose(surface.get("amount"))
        if raw is None:
            continue
        places = _as_int_loose(surface.get("decimals"))
        if places is not None:
            decimals = places
        total += raw
    return total, decimals


def _fee_payer_sol_abs(meta: Mapping[str, Any], keys: Sequence[str]) -> float:
    pre = meta.get("preBalances")
    post = meta.get("postBalances")
    if not isinstance(pre, list) or not isinstance(post, list) or not keys:
        return 0.0
    try:
        before = int(pre[0])
        after = int(post[0])
    except (IndexError, TypeError, ValueError):
        return 0.0
    return abs(after - before) / 1_000_000_000
