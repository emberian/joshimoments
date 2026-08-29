"""/watch and /unwatch — the DM command lane, dispatched by the gate gateway.

Same shape as dregg_gate.lookup.ScreenLookup, on purpose: the gateway wires this in
as one dispatch branch, config arrives through a getter so keep-last-good reloads
reach us, GateState answers "is this a verified holder", and every reply is plain
text with no parse_mode. The gateway diff stays minimal because everything —
validation, caps, copy — lives here.

The subscriptions land in the WATCH db (dregg_watch.state), which the matcher service
reads in its own process. Two writers, one WAL sqlite, no flock — the gate db's flock
guards the Telegram poller identity and has no business here.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path

from dregg_gate.state import GateState
from dregg_gate.verify import parse_pubkey

from .state import WatchState

RATE_WINDOW_SECONDS = 60.0

_USERNAME = re.compile(r"@?[A-Za-z0-9_]{3,32}\Z")
_CREW_ID = re.compile(r"#?([0-9]{1,12})\Z")

USAGE_TEXT = (
    "Your personal watchlist — I DM you when it happens.\n\n"
    "/watch coin <mint> — anything touching that coin: screen verdict, callout, "
    "momentum alert\n"
    "/watch deployer <wallet> — that deployer launches again\n"
    "/watch crew <crew id> — that crew's fingerprint shows up in a new launch\n"
    "/watch caller <wallet or @name> — that caller makes a new callout\n"
    "/watch clean — every CLEAN-verdict launch (high volume; rides a digest)\n"
    "/watch list — your watches\n"
    "/unwatch <id> — stop one\n\n"
    "Bursts fold into a digest instead of flooding you."
)

BAD_WALLET_TEXT = (
    "That doesn't parse as a Solana address — expect 32-44 base58 characters "
    "(no 0, O, I, or l). Copy it exactly and try again."
)

BAD_CREW_TEXT = (
    "Crew ids are numbers — copy one from a screen card's crew line "
    "(e.g. \"fingerprint #81422\" is /watch crew 81422)."
)

BAD_CALLER_TEXT = (
    "Give me the caller's wallet address, or their name as the archive shows it "
    "(letters, digits, underscores; @ optional)."
)


def teaser_text(threshold_tokens: int) -> str:
    return (
        "Personal watchlists are a holder perk — verify to unlock.\n\n"
        "Verified members can tell the bot exactly what to watch — a coin, a deployer "
        "wallet (\"tell me when the one who rugged me launches again\"), a crew "
        "fingerprint, a caller, or every CLEAN launch — and get a DM the moment it "
        "happens.\n\n"
        f"Hold {threshold_tokens:,} $DREGG and send /verify <wallet> to get in."
    )


EJECTED_TEXT = (
    "Your seat lapsed (the wallet dropped below the gate), so your watchlist is "
    "paused. /verify <wallet> again to restore it — your watches are kept."
)


def rate_limited_text(per_minute: int) -> str:
    return (
        f"Easy — watch commands are capped at {per_minute} a minute per member. "
        "Try again in a moment."
    )


def cap_text(max_subs: int) -> str:
    return (
        f"You're at the cap ({max_subs} watches). /watch list to see them, "
        "/unwatch <id> to make room."
    )


class WatchCommands:
    """Per-process command handler; the gateway constructs exactly one."""

    def __init__(
        self,
        config_getter: Callable[[], object],
        gate_state: GateState,
        *,
        clock: Callable[[], float] = time.time,
        max_subs: int = 25,
        rate_per_minute: int = 10,
        watch_state: WatchState | None = None,
    ):
        self._config = config_getter
        self.gate_state = gate_state
        self.clock = clock
        self.max_subs = max_subs
        self.rate_per_minute = rate_per_minute
        self._watch_state = watch_state
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    @property
    def state(self) -> WatchState:
        if self._watch_state is None:
            path = Path(self._config().watch_db_path)  # duck-typed: the gate Config
            self._watch_state = WatchState(path)
        return self._watch_state

    def _admit(self, uid: int) -> bool:
        now = self.clock()
        hits = self._hits[uid]
        while hits and now - hits[0] >= RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= self.rate_per_minute:
            return False
        hits.append(now)
        return True

    # -- the entry point (gateway calls exactly this) --------------------------------

    def reply(self, uid: int, command: str, args: list[str]) -> str:
        """command is '/watch' or '/unwatch'; args are the words after it. Plain text out."""

        cfg = self._config()
        member = self.gate_state.member(uid)
        if member is None:
            return teaser_text(getattr(cfg, "threshold_tokens", 0))
        if member.status == "ejected":
            return EJECTED_TEXT
        if not self._admit(uid):
            return rate_limited_text(self.rate_per_minute)
        if command == "/unwatch":
            return self._unwatch(uid, args[0] if args else None)
        if not args:
            return USAGE_TEXT
        verb = args[0].lower()
        if verb == "list":
            return self._list(uid)
        if verb in ("coin", "deployer", "crew", "caller", "clean"):
            return self._add(uid, verb, args[1] if len(args) > 1 else None)
        return USAGE_TEXT

    # -- add -------------------------------------------------------------------------

    def _add(self, uid: int, kind: str, raw: str | None) -> str:
        spec, mode, error = self._normalize(kind, raw)
        if error is not None:
            return error
        if self.state.count_for_user(uid) >= self.max_subs:
            return cap_text(self.max_subs)
        sub_id, created = self.state.add(uid, kind, spec, mode, self.clock())
        if not created:
            return f"Already watching that (watch #{sub_id})."
        return self._confirm(kind, spec, sub_id)

    def _normalize(self, kind: str, raw: str | None) -> tuple[str, str, str | None]:
        """(spec, mode, error). Specs are normalized so duplicates collide honestly."""

        if kind == "clean":
            return "", "digest", None
        if raw is None:
            what = {"coin": "mint", "deployer": "wallet", "crew": "crew id",
                    "caller": "wallet or @name"}[kind]
            return "", "", f"Usage: /watch {kind} <{what}> — put it after the kind, in the same message."
        if kind in ("coin", "deployer"):
            if parse_pubkey(raw) is None:
                return "", "", BAD_WALLET_TEXT
            return raw, "event", None
        if kind == "crew":
            match = _CREW_ID.fullmatch(raw)
            if match is None:
                return "", "", BAD_CREW_TEXT
            return str(int(match.group(1))), "event", None
        # caller: a wallet verbatim, or a username lowercased without '@'
        if parse_pubkey(raw) is not None:
            return raw, "event", None
        if _USERNAME.fullmatch(raw):
            return raw.lstrip("@").lower(), "event", None
        return "", "", BAD_CALLER_TEXT

    def _confirm(self, kind: str, spec: str, sub_id: int) -> str:
        stop = f"/unwatch {sub_id} to stop."
        if kind == "coin":
            return (
                f"Watching coin {spec} (watch #{sub_id}). I'll DM you when the screen "
                f"scores it, a caller calls it, or it hits the movers board. {stop}"
            )
        if kind == "deployer":
            return (
                f"Watching deployer {spec} (watch #{sub_id}). The moment that wallet "
                f"launches again, you'll hear about it here. {stop}"
            )
        if kind == "crew":
            return (
                f"Watching crew #{spec} (watch #{sub_id}). If that fingerprint shows up "
                f"in a new launch's birth slot, I'll DM you. {stop}"
            )
        if kind == "caller":
            return (
                f"Watching caller {spec} (watch #{sub_id}). New callouts from them land "
                f"here. {stop}"
            )
        return (
            f"Watching every CLEAN launch (watch #{sub_id}). Fair warning: the screen "
            "admits roughly 1 in 12 of ~35,000 launches a day — thousands of matches. "
            "So this one rides a digest: one batched message every half hour or so, "
            f"never a flood. {stop}"
        )

    # -- list / unwatch ---------------------------------------------------------------

    def _list(self, uid: int) -> str:
        subs = self.state.subs_for_user(uid)
        if not subs:
            return "No watches yet. /watch shows the kinds."
        lines = [f"Your watches ({len(subs)} of {self.max_subs}):"]
        for sub in subs:
            label = f"#{sub.id} {sub.kind}"
            if sub.spec:
                label += f" {sub.spec}"
            if sub.mode == "digest":
                label += " (digest)"
            lines.append(label)
        lines.append("/unwatch <id> to stop one.")
        return "\n".join(lines)

    def _unwatch(self, uid: int, raw: str | None) -> str:
        if raw is None or not raw.lstrip("#").isdigit():
            return "Usage: /unwatch <id> — the number from /watch list."
        sub_id = int(raw.lstrip("#"))
        if self.state.remove(uid, sub_id):
            return f"Watch #{sub_id} stopped."
        return f"No watch #{sub_id} on your list. /watch list shows yours."
