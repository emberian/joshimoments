"""Read-only firehose ranking: observations in, SieveCard-like mappings out.

This module never signs, never quotes, and never imports the sentinel executor
or MarketFabric.  ``execution_effect`` is always ``"none"``.

A sibling lane owns ``shitcoims_intelligence.sieve``.  When that module is
importable we call its verdict helpers; otherwise the same function names live
here as a thin fallback so the HTTP projection stays implemented.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .models import Observation, StoredObservation, thaw_json
from .sieve import (
    VERDICT_PASS,
    VERDICT_SKIP,
    VERDICT_VETO,
    VERDICT_WATCH_EXIT,
    attention_exit_mints,
    combine_verdicts,
    deployer_verdict,
    holder_verdict,
    organic_verdict,
)
from .tape import (
    TapePrint,
    features_from_prints,
    merge_feature_bags,
    prints_from_wallet_payload,
)

MAX_CANDIDATE_CARDS = 40
EXECUTION_EFFECT = "none"

_OBSERVATION_TYPES = (Observation, StoredObservation)
_KOL_MENTION_KINDS = frozenset({"x_kol_post", "x_mint_mention"})
_EARLY_COIN_KEYS = frozenset(
    {
        "buy_count",
        "effective_wallet_count",
        "returning_wallet_ratio",
        "sell_count",
        "top_wallet_quote_share",
        "trade_count",
        "unique_wallet_count",
        "wallet_volume_hhi",
    }
)
_CREATOR_KEYS = ("creator", "coin_creator", "creator_address")
_NAME_KEYS = ("name", "symbol")
_HOLDER_FEATURE_KEYS = (
    "holder_count",
    "holder_top1",
    "holder_hhi",
    "holder_nakamoto",
    "holder_gini",
    "holder_top10",
)

def build_candidates(
    *,
    observations: Sequence[Any],
    held_mints: Sequence[str] = (),
    creators: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Project stored observations into at most 40 advisory candidate cards."""

    held = {str(mint).strip() for mint in held_mints if str(mint).strip()}
    creator_by_mint = {
        str(mint).strip(): str(creator).strip()
        for mint, creator in (creators or {}).items()
        if str(mint).strip() and str(creator).strip()
    }

    buckets: dict[str, _MintBucket] = {}
    order: list[str] = []
    prints_by_mint: dict[str, list[TapePrint]] = {}

    for item in observations:
        kind, subject_type, subject_id, payload, extra = _coerce_observation(item)
        surfaces = (payload, extra)
        for mint in _collect_mints(subject_type=subject_type, subject_id=subject_id, surfaces=surfaces):
            bucket = buckets.get(mint)
            if bucket is None:
                bucket = _MintBucket(mint=mint)
                buckets[mint] = bucket
                order.append(mint)
            bucket.kinds.add(kind)
            bucket.mentions += 1
            if kind in _KOL_MENTION_KINDS:
                bucket.kol_mentioned = True
            name = _first_text(surfaces, _NAME_KEYS)
            if name and bucket.name is None:
                bucket.name = name
            creator = _first_text(surfaces, _CREATOR_KEYS)
            if creator:
                creator_by_mint.setdefault(mint, creator)
            features = merge_feature_bags(
                _early_coin_from_surfaces(surfaces),
                _holder_from_surfaces(surfaces),
                _prints_features_from_surfaces(surfaces),
            )
            if features:
                bucket.features = merge_feature_bags(bucket.features, features)
            if kind == "wallet_transaction":
                wallet = str(subject_id or payload.get("wallet") or "")
                stamp = _as_int(payload.get("slot")) or 0
                for print_ in prints_from_wallet_payload(payload, wallet=wallet, ts=stamp):
                    prints_by_mint.setdefault(print_.mint, []).append(print_)

    siblings_by_creator: dict[str, list[str]] = {}
    for mint, creator in creator_by_mint.items():
        siblings_by_creator.setdefault(creator, []).append(mint)

    cards: list[dict[str, Any]] = []
    for mint in order:
        bucket = buckets[mint]
        creator = creator_by_mint.get(mint)
        raw_siblings = siblings_by_creator.get(creator, ()) if creator else ()
        siblings = tuple(item for item in raw_siblings if item != mint)
        if mint in prints_by_mint:
            derived = features_from_prints(prints_by_mint[mint])
            bucket.features = merge_feature_bags(derived, bucket.features)
        organic = organic_verdict(bucket.features or {})
        holders = holder_verdict(bucket.features or {})
        deployer = deployer_verdict(
            creator=creator, sibling_mints=siblings, subject_mint=mint
        )
        watched = attention_exit_mints(
            held_mints=held, mentioned_mints=(mint,) if bucket.kol_mentioned else ()
        )
        attention = VERDICT_WATCH_EXIT if mint in watched else VERDICT_SKIP
        verdict = combine_verdicts(organic, holders, deployer, attention)
        reasons: list[str] = ["seen in the intelligence firehose"]
        if verdict == VERDICT_VETO:
            reasons.append("sieve veto (serial deployer, wash, or holder cabal)")
        elif verdict == VERDICT_WATCH_EXIT:
            reasons.append("held mint mentioned by a watched KOL")
        elif verdict == VERDICT_PASS:
            reasons.append("organic-open: look, do not buy automatically")
        elif verdict == VERDICT_SKIP:
            reasons.append("not enough tape")
        scores = {"mentions": float(bucket.mentions)}
        cards.append(
            {
                "mint": mint,
                "name": bucket.name,
                "verdict": verdict,
                "reasons": reasons,
                "scores": scores,
                "execution_effect": EXECUTION_EFFECT,
            }
        )

    cards.sort(key=_card_sort_key)
    return tuple(cards[:MAX_CANDIDATE_CARDS])


@dataclasses.dataclass
class _MintBucket:
    mint: str
    name: str | None = None
    features: dict[str, Any] | None = None
    kinds: set[str] = dataclasses.field(default_factory=set)
    mentions: int = 0
    kol_mentioned: bool = False


def _card_sort_key(card: Mapping[str, Any]) -> tuple[int, float, str]:
    verdict = str(card.get("verdict") or "")
    priority = {
        VERDICT_VETO: 0,
        VERDICT_WATCH_EXIT: 1,
        VERDICT_PASS: 2,
        VERDICT_SKIP: 3,
    }.get(verdict, 4)
    mentions = _finite_float((_as_mapping(card.get("scores")) or {}).get("mentions")) or 0.0
    return (priority, -mentions, str(card.get("mint") or ""))


def _coerce_observation(
    item: Any,
) -> tuple[str, str, str, dict[str, Any], dict[str, Any]]:
    if isinstance(item, _OBSERVATION_TYPES):
        payload = _as_mapping(thaw_json(item.payload)) or {}
        return item.kind, item.subject_type, item.subject_id, payload, {}
    if isinstance(item, Mapping):
        raw = dict(item)
        nested = raw.get("payload")
        if isinstance(nested, Mapping):
            payload = _as_mapping(thaw_json(nested)) or {}
            extra = {key: value for key, value in raw.items() if key != "payload"}
        else:
            payload = _as_mapping(thaw_json(raw)) or {}
            extra = {}
        return (
            str(raw.get("kind") or payload.get("kind") or ""),
            str(raw.get("subject_type") or payload.get("subject_type") or ""),
            str(raw.get("subject_id") or payload.get("subject_id") or ""),
            payload,
            extra,
        )
    raise TypeError("observations must be Observation records or mappings")


def _collect_mints(
    *,
    subject_type: str,
    subject_id: str,
    surfaces: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    found: list[str] = []

    def add(value: Any) -> None:
        if not isinstance(value, str):
            return
        mint = value.strip()[:64]
        if mint and mint not in found:
            found.append(mint)

    if subject_type == "token":
        add(subject_id)
    for surface in surfaces:
        add(surface.get("mint"))
        mint_candidates = surface.get("mint_candidates")
        if isinstance(mint_candidates, Sequence) and not isinstance(mint_candidates, (str, bytes)):
            for item in mint_candidates:
                add(item)
        token_deltas = surface.get("token_deltas")
        if isinstance(token_deltas, Sequence) and not isinstance(token_deltas, (str, bytes)):
            for delta in token_deltas:
                if isinstance(delta, Mapping):
                    add(delta.get("mint"))
        details = surface.get("details")
        if isinstance(details, Mapping):
            add(details.get("mint"))
            nested_candidates = details.get("mint_candidates")
            if isinstance(nested_candidates, Sequence) and not isinstance(nested_candidates, (str, bytes)):
                for item in nested_candidates:
                    add(item)
            nested_deltas = details.get("token_deltas")
            if isinstance(nested_deltas, Sequence) and not isinstance(nested_deltas, (str, bytes)):
                for delta in nested_deltas:
                    if isinstance(delta, Mapping):
                        add(delta.get("mint"))
    return tuple(found)


def _holder_from_surfaces(surfaces: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    bag: dict[str, Any] = {}
    for surface in surfaces:
        for key in _HOLDER_FEATURE_KEYS:
            if key in bag:
                continue
            value = surface.get(key)
            if value is not None:
                bag[key] = value
    return bag or None


def _prints_features_from_surfaces(
    surfaces: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    prints: list[TapePrint] = []
    for surface in surfaces:
        raw = surface.get("prints")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            continue
        for item in raw:
            reconstructed = _as_tape_print(item)
            if reconstructed is not None:
                prints.append(reconstructed)
    return features_from_prints(prints) if prints else None


def _as_tape_print(value: Any) -> TapePrint | None:
    if isinstance(value, TapePrint):
        return value
    mapping = _as_mapping(value)
    if mapping is None:
        return None
    mint = mapping.get("mint")
    wallet = mapping.get("wallet")
    side = mapping.get("side")
    if not isinstance(mint, str) or not mint.strip():
        return None
    if not isinstance(wallet, str) or not wallet.strip():
        return None
    if side not in {"buy", "sell"}:
        return None
    quote = _finite_float(mapping.get("quote_sol"))
    base = _finite_float(mapping.get("base"))
    return TapePrint(
        ts=_as_int(mapping.get("ts")) or 0,
        mint=mint.strip(),
        wallet=wallet.strip(),
        side=side,
        quote_sol=quote if quote is not None else 0.0,
        base=base if base is not None else 0.0,
    )


def _early_coin_from_surfaces(surfaces: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    for surface in surfaces:
        if surface.get("feature_key") == "early_coin":
            value = _as_mapping(surface.get("value"))
            if value is not None and _looks_like_early_coin(value):
                return value
        nested = _as_mapping(surface.get("early_coin"))
        if nested is not None and _looks_like_early_coin(nested):
            return nested
        if _looks_like_early_coin(surface):
            return dict(surface)
    return None


def _looks_like_early_coin(value: Mapping[str, Any]) -> bool:
    return any(key in value for key in _EARLY_COIN_KEYS)


def _first_text(surfaces: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> str | None:
    for surface in surfaces:
        for key in keys:
            value = surface.get(key)
            if isinstance(value, str):
                text = value.strip()[:80]
                if text:
                    return text
    return None


def _normalize_verdict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return {"verdict": text, "reasons": (text,), "scores": {}} if text else None
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    mapping = _as_mapping(value)
    if mapping is None:
        return None
    return mapping


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _as_reason_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        reasons: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in reasons:
                reasons.append(text)
        return tuple(reasons)
    return ()


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number
