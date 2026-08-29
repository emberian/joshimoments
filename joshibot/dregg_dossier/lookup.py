"""/wallet and /coin: the dossier lane of the gate bot. Gated, rate-limited, plain text.

Same shape as ``dregg_gate.lookup.ScreenLookup`` so the gateway wires it in one line per
command:

* GATED — dossier cards are a holder perk. Unverified users get an honest teaser (shape,
  not data); ejected members are pointed back at /verify.
* RATE-LIMITED per user across BOTH commands (one shared budget, default 6/min,
  ``gate.dossier_rate_per_minute`` if the primary adds the key) so nobody scripts the DM
  lane into a free behavioral API over 728k wallets.
* PLAIN TEXT ONLY — every reply returns ``(text, None)``; there is no HTML branch at all
  in this module, so nothing can be mis-escaped.
* READ-ONLY over the dossier index (``state/wallets/dossier/current.sqlite`` by default,
  ``gate.dossier_index_path`` if configured). The index is opened lazily and kept; if it
  is missing the reply says so honestly and the next lookup retries, so a build that
  lands after the service starts is picked up without a restart.

GATEWAY WIRING (the primary applies; copy and logic live here so the diff stays minimal):

    from dregg_dossier.lookup import DossierLookup          # imports, next to ScreenLookup
    self.dossier = DossierLookup(lambda: self.config, state, clock=clock)   # __init__
    elif command == "/wallet":                               # _private_message
        reply, mode = self.dossier.reply_wallet(uid, parts[1] if len(parts) > 1 else None)
        self.dm(chat_id, reply, dedup, parse_mode=mode)
    elif command == "/coin":
        reply, mode = self.dossier.reply_coin(uid, parts[1] if len(parts) > 1 else None)
        self.dm(chat_id, reply, dedup, parse_mode=mode)

plus two lines in HELP_TEXT / start_text. Optional Config keys (defaults apply without
them): ``dossier_index_path`` (str/Path), ``dossier_rate_per_minute`` (int).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path

from dregg_gate.config import Config
from dregg_gate.state import GateState
from dregg_gate.verify import parse_pubkey

from .store import Dossier, resolve_current

log = logging.getLogger(__name__)

RATE_WINDOW_SECONDS = 60.0
DEFAULT_RATE_PER_MINUTE = 6


def teaser_text(threshold_tokens: int) -> str:
    """What an unverified user sees instead of a card: the shape, not the data."""

    return (
        "/wallet and /coin are holder perks — verify to unlock.\n\n"
        "Verified members get the behavioral dossier on any of 728k profiled wallets "
        "(guild, realization policy, realized PnL, hold times, bot tells) and the holder "
        "composition of any coin in our data (guild mix, preset-bot count, crews, large "
        "holders quietly distributing). A taste of the shape:\n\n"
        "FLASH / BREAKEVEN_PRESET — ░░.░ SOL realized across ░░ coins, ░░% win rate, "
        "median hold ░░ s, enters ░ s after launch, mercenary rotation: yes.\n\n"
        f"Hold {threshold_tokens:,} $DREGG and send /verify <wallet> to get in."
    )


EJECTED_TEXT = (
    "Your seat lapsed (the wallet dropped below the gate), so dossier lookups are "
    "locked. /verify <wallet> again to restore them."
)

WALLET_USAGE_TEXT = (
    "Usage: /wallet <address> — paste the wallet's Solana address "
    "(32-44 base58 characters)."
)

COIN_USAGE_TEXT = (
    "Usage: /coin <mint> — paste the coin's mint address "
    "(32-44 base58 characters, usually ending in \"pump\")."
)

UNAVAILABLE_TEXT = (
    "The dossier index isn't loaded on this box right now — the data layer exists but "
    "hasn't been built here. Poke the operator; nothing you did was wrong."
)


def rate_limited_text(per_minute: int) -> str:
    return (
        f"Easy — dossier lookups are capped at {per_minute} a minute per member, so the "
        "bot stays a bot and not a free behavioral API. Try again in a moment."
    )


class DossierLookup:
    """/wallet + /coin state: per-user rate window shared across both commands, and the
    lazily-opened index. Config comes through a getter so the service's keep-last-good
    reload reaches lookups without extra wiring."""

    def __init__(
        self,
        config_getter: Callable[[], Config],
        state: GateState,
        *,
        index_path: Path | None = None,
        rate_per_minute: int | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self._config = config_getter
        self.state = state
        self.clock = clock
        self._index_override = index_path
        self._rate_override = rate_per_minute
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        self._dossier: Dossier | None = None

    # -- knobs (constructor override > Config attr if the primary adds it > default) ---

    def _index_path(self) -> Path:
        if self._index_override is not None:
            return self._index_override
        configured = getattr(self._config(), "dossier_index_path", None)
        return Path(configured) if configured else resolve_current()

    def _rate(self) -> int:
        if self._rate_override is not None:
            return self._rate_override
        configured = getattr(self._config(), "dossier_rate_per_minute", None)
        return int(configured) if configured else DEFAULT_RATE_PER_MINUTE

    # -- plumbing ----------------------------------------------------------------------

    def _open(self) -> Dossier | None:
        if self._dossier is None:
            try:
                self._dossier = Dossier(self._index_path())
            except (OSError, ValueError) as exc:
                log.warning("dossier index unavailable at %s (%s)", self._index_path(), exc)
                return None
        return self._dossier

    def _admit(self, uid: int) -> bool:
        now = self.clock()
        hits = self._hits[uid]
        while hits and now - hits[0] >= RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= self._rate():
            return False
        hits.append(now)
        return True

    def _gate(self, uid: int) -> str | None:
        """The member/rate ladder shared by both commands; None means proceed."""

        member = self.state.member(uid)
        if member is None:
            return teaser_text(self._config().threshold_tokens)
        if member.status == "ejected":
            return EJECTED_TEXT
        if not self._admit(uid):
            return rate_limited_text(self._rate())
        return None

    # -- the handlers ------------------------------------------------------------------

    def reply_wallet(self, uid: int, arg: str | None) -> tuple[str, str | None]:
        """The full /wallet decision: (reply text, parse_mode — always None: plain text)."""

        from . import cards

        refusal = self._gate(uid)
        if refusal is not None:
            return refusal, None
        if arg is None or parse_pubkey(arg) is None:
            return WALLET_USAGE_TEXT, None
        dossier = self._open()
        if dossier is None:
            return UNAVAILABLE_TEXT, None
        now = self.clock()
        row = dossier.wallet(arg)
        if row is None:
            return cards.wallet_miss(arg, dossier.meta, now), None
        return cards.wallet_card(row, dossier.meta, now), None

    def reply_coin(self, uid: int, arg: str | None) -> tuple[str, str | None]:
        """The full /coin decision: (reply text, parse_mode — always None: plain text)."""

        from . import cards

        refusal = self._gate(uid)
        if refusal is not None:
            return refusal, None
        if arg is None or parse_pubkey(arg) is None:
            return COIN_USAGE_TEXT, None
        dossier = self._open()
        if dossier is None:
            return UNAVAILABLE_TEXT, None
        now = self.clock()
        view = dossier.coin(arg)
        if view is None:
            return cards.coin_miss(arg, dossier.meta, now), None
        return cards.coin_card(arg, view, dossier.meta, now), None
