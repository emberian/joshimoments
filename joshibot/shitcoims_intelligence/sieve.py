"""PURE advisory firehose sieve.

The new-coin firehose is too large to speculate over. This module ranks
and vetoes candidates so a human may LOOK. It never signs, never talks
to a wallet, never opens a socket, and never claims an effect other than
"none". Intelligence cannot execute.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

VERDICT_PASS: Final = "pass"
VERDICT_VETO: Final = "veto"
VERDICT_WATCH_EXIT: Final = "watch_exit"
VERDICT_SKIP: Final = "skip"
EXECUTION_EFFECT_NONE: Final = "none"

# combine_verdicts: smaller is more severe. skip outranks pass — thin
# evidence is not an all-clear.
_SEVERITY: Final[dict[str, int]] = {
    VERDICT_VETO: 0,
    VERDICT_WATCH_EXIT: 1,
    VERDICT_SKIP: 2,
    VERDICT_PASS: 3,
}

# rank_cards band order (not the same as severity): pass before skip so
# the human sees open books before "not enough".
_RANK_BAND: Final[dict[str, int]] = {
    VERDICT_VETO: 0,
    VERDICT_WATCH_EXIT: 1,
    VERDICT_PASS: 2,
    VERDICT_SKIP: 3,
}

_KNOWN_VERDICTS: Final[frozenset[str]] = frozenset(_SEVERITY)

# Organic wash gates. trade_count below this is "not enough tape".
_MIN_TRADES_FOR_ORGANIC: Final = 20
_TOP_WALLET_SHARE_VETO: Final = 0.55
_WALLET_HHI_VETO: Final = 0.45
_MIN_UNIQUE_WALLETS: Final = 6
_SERIAL_SIBLING_VETO: Final = 2

# Holder-book gates. Same numbers as numerics.holder_veto — keep them
# aligned. Missing holder stats are skip, never an invented veto.
_HOLDER_TOP1_VETO: Final = 0.35
_HOLDER_HHI_VETO: Final = 0.40

# Farm-template vocabulary. Alone it is cheap talk; it only damns a
# mention when the same skeleton is being stamped across accounts.
_CAMPAIGN_VOCAB: Final[frozenset[str]] = frozenset(
    {
        "airdrop",
        "boost",
        "boosted",
        "family",
        "fomo",
        "gm",
        "listed",
        "listing",
        "send",
        "vote",
        "voted",
        "votes",
        "voting",
        "wagmi",
        "x100",
        "x30",
    }
)

_FEATURE_KEYS: Final[tuple[str, ...]] = (
    "unique_wallet_count",
    "top_wallet_quote_share",
    "wallet_volume_hhi",
    "trade_count",
    "returning_wallet_ratio",
)


@dataclass(frozen=True, slots=True)
class SieveCard:
    mint: str
    name: str | None
    verdict: str
    reasons: tuple[str, ...]
    scores: dict[str, float | None]
    execution_effect: str = EXECUTION_EFFECT_NONE

    def __post_init__(self) -> None:
        if self.execution_effect != EXECUTION_EFFECT_NONE:
            raise ValueError("SieveCard.execution_effect is always 'none'")
        if self.verdict not in _KNOWN_VERDICTS:
            raise ValueError(f"unknown verdict: {self.verdict!r}")
        if not isinstance(self.mint, str) or not self.mint.strip():
            raise ValueError("SieveCard.mint must be a nonempty string")


def score_mention_quality(
    *,
    text: str,
    followers: int,
    verified: bool,
    likes: int,
    skeleton_dupes: int,
) -> float:
    """0..1 genuine-attention prior. Farm templates score low.

    Raw mention COUNT is farmed. Near-duplicate skeleton text is the
    primary tell; Blue-plus-tiny-followers is the paid-farm signature;
    campaign vocab only damns templates, not a lone degen's original take.

    ``skeleton_dupes`` is the number of *other* mentions sharing this
    mention's whitespace-folded skeleton (0 means the text is unique).
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(verified, bool):
        raise TypeError("verified must be a bool")
    _require_nonneg_int(followers, "followers")
    _require_nonneg_int(likes, "likes")
    _require_nonneg_int(skeleton_dupes, "skeleton_dupes")

    prior = 1.0
    prior *= _duplicate_factor(skeleton_dupes)
    prior *= _reach_factor(followers)
    prior *= _engagement_factor(likes)
    prior *= _blue_tiny_factor(verified=verified, followers=followers)
    prior *= _campaign_factor(_campaign_hits(text), skeleton_dupes)
    return max(0.0, min(1.0, prior))


def deployer_verdict(
    *,
    creator: str | None,
    sibling_mints: tuple[str, ...],
    subject_mint: str,
) -> str:
    """veto if creator has >= 2 OTHER sibling mints in evidence. skip if no creator. else pass."""

    if creator is None or not str(creator).strip():
        return VERDICT_SKIP
    others = {mint for mint in sibling_mints if mint and mint != subject_mint}
    if len(others) >= _SERIAL_SIBLING_VETO:
        return VERDICT_VETO
    return VERDICT_PASS


def organic_verdict(features: Mapping[str, Any]) -> str:
    """Use early_coin-style keys if present.

    Veto if trade_count>=20 AND (top_wallet_quote_share>=0.55 or
    hhi>=0.45 or unique_wallet_count<6). skip if trade_count < 20.
    pass otherwise. Missing wash-signal keys do not invent a veto.
    """

    bag = _feature_bag(features)
    trade_count = _optional_int(bag, "trade_count")
    if trade_count is None or trade_count < _MIN_TRADES_FOR_ORGANIC:
        return VERDICT_SKIP

    top_share = _optional_float(bag, "top_wallet_quote_share")
    hhi = _optional_float(bag, "wallet_volume_hhi")
    unique = _optional_int(bag, "unique_wallet_count")

    if top_share is not None and top_share >= _TOP_WALLET_SHARE_VETO:
        return VERDICT_VETO
    if hhi is not None and hhi >= _WALLET_HHI_VETO:
        return VERDICT_VETO
    if unique is not None and unique < _MIN_UNIQUE_WALLETS:
        return VERDICT_VETO
    return VERDICT_PASS


def holder_verdict(features: Mapping[str, Any]) -> str:
    """Concentration of the *holder book*, not the trade tape.

    Keys: holder_count, holder_top1, holder_hhi, holder_nakamoto.
    skip if holder_count is missing or 0. veto if top1>=0.35 or
    nakamoto==1 or hhi>=0.40. else pass.
    """

    bag = _feature_bag(features)
    holders = _optional_int(bag, "holder_count")
    if holders is None or holders <= 0:
        return VERDICT_SKIP
    top1 = _optional_float(bag, "holder_top1")
    hhi = _optional_float(bag, "holder_hhi")
    nakamoto = _optional_int(bag, "holder_nakamoto")
    if top1 is not None and top1 >= _HOLDER_TOP1_VETO:
        return VERDICT_VETO
    if nakamoto is not None and nakamoto == 1:
        return VERDICT_VETO
    if hhi is not None and hhi >= _HOLDER_HHI_VETO:
        return VERDICT_VETO
    return VERDICT_PASS


def attention_exit_mints(
    *,
    held_mints: set[str],
    mentioned_mints: Sequence[str],
) -> frozenset[str]:
    """Intersection. Held mints that a KOL/mint URL mentioned."""

    return frozenset(held_mints).intersection(mentioned_mints)


def rank_cards(cards: Sequence[SieveCard]) -> tuple[SieveCard, ...]:
    """Order: veto first, then watch_exit, then pass, then skip. Stable within band."""

    indexed = list(enumerate(cards))
    indexed.sort(key=lambda item: (_RANK_BAND.get(item[1].verdict, 99), item[0]))
    return tuple(card for _, card in indexed)


def combine_verdicts(*verdicts: str) -> str:
    """Pick the most severe: veto > watch_exit > skip > pass."""

    if not verdicts:
        raise ValueError("combine_verdicts requires at least one verdict")
    for verdict in verdicts:
        if verdict not in _SEVERITY:
            raise ValueError(f"unknown verdict: {verdict!r}")
    return min(verdicts, key=_SEVERITY.__getitem__)


def _feature_bag(features: object) -> Mapping[str, Any]:
    if isinstance(features, Mapping):
        return features
    # Duck-type EarlyCoinFeatures without importing it. Tests stay on
    # plain mappings; a snapshot object still works via attributes.
    if any(hasattr(features, key) for key in _FEATURE_KEYS):
        return {key: getattr(features, key, None) for key in _FEATURE_KEYS}
    raise TypeError("features must be a mapping of early_coin-style keys")


def _optional_int(bag: Mapping[str, Any], key: str) -> int | None:
    value = bag.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _optional_float(bag: Mapping[str, Any], key: str) -> float | None:
    value = bag.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _require_nonneg_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def _tokens(text: str) -> set[str]:
    return set(re.sub(r"\W+", " ", text.lower()).split())


def _campaign_hits(text: str) -> int:
    return len(_tokens(text) & _CAMPAIGN_VOCAB)


def _duplicate_factor(skeleton_dupes: int) -> float:
    # PRIMARY farm tell: the same skeleton stamped across accounts.
    if skeleton_dupes >= 2:
        return 0.15
    if skeleton_dupes == 1:
        return 0.5
    return 1.0


def _reach_factor(followers: int) -> float:
    # Mild prior, not a verdict. An 8-follower original take is not farm.
    if followers < 100:
        return 0.7
    if followers < 1000:
        return 0.9
    return 1.0


def _engagement_factor(likes: int) -> float:
    # Soft: a real small account often has zero engagement.
    if likes <= 0:
        return 0.7
    return min(1.1, 0.8 + 0.5 * math.log1p(likes) / math.log(50))


def _blue_tiny_factor(*, verified: bool, followers: int) -> float:
    if verified and followers < 1000:
        return 0.55
    return 1.0


def _campaign_factor(hits: int, skeleton_dupes: int) -> float:
    if hits >= 2 and skeleton_dupes >= 1:
        return 0.4
    if hits >= 3:
        return 0.7
    return 1.0
