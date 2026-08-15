"""The HUNCH tape: the operator's own utterances, kept verbatim, as journal-grade facts.

WHAT THIS IS FOR, STATED PLAINLY
--------------------------------
Every entry-selection study in this tree returned null. The operator's own selection is the
one repeatedly-positive signal in the whole record: on the same pattern under the same
clock, the rule-chosen wiggle book's first closes ran **-14.08%** and their hand-picked
equivalents measured **+3.14%**. Whatever produces that gap has never been written down.

This module writes it down. ``state/hunches.jsonl`` is an append-only tape of moments where
the operator looked at a coin and did something about it -- the utterance VERBATIM, the
parse alongside it, the instrument reading at that instant, and the mint it resolved to.

THREE ROW KINDS, ONE CORPUS, ON PURPOSE. A ``hunch.v1`` is "I want in"; a ``hunch.zap.v1``
is "I want out, and here is everything the instrument could see when I decided"; a
``hunch.retraction.v1`` is "that was not a gesture". Entries and exits share one file
because they are one behaviour -- the operator watches a coin and acts on it twice -- and a
reactive exit policy fitted without the entry that preceded it would be fitted to half a
decision.

It is explicitly THREE things at once, and the third is the reason for the discipline:

1. a **transport**, read by :class:`HunchSource` into the desk, where a wiggle-kind hunch
   opens a real paper position in the OPERATOR book;
2. a **record**, scored by ``hunch report`` against the wiggle book under identical
   execution -- the intuition premium, measured rather than asserted;
3. the **future training set for intuition distillation**, and the import source for
   Joshi M1's ``Expectation``. That is why the row shape is Expectation-shaped rather than
   convenient (``design/domain-model.md`` §6: scope, claim, horizon, confidence, utterance,
   evidence, recorded-at), why the utterance is never normalised, cleaned or truncated, and
   why nothing here is ever rewritten or deleted. A model fitted later to "what does the
   operator pick" can only be as good as this file, and every field dropped today is a
   feature that model will not have.

DURABILITY IS THE WHOLE CONTRACT
--------------------------------
A hunch is a fact about a person at a moment and it is not reconstructible afterwards. So:

* the CLI appends and **fsyncs** before it prints anything, and the write happens BEFORE the
  instrument readout is computed -- a slow vendor can lose you a readout, never a hunch;
* :class:`HunchSource` tails from the START of the file, not from EOF like every other
  source on the desk, and dedupes on ``hunch_id``. A desk restarted an hour later still
  sees every hunch it has not yet acted on. The other sources attach at EOF because
  replaying a day of board snapshots would fabricate fills; replaying the hunch tape
  fabricates nothing, because acting on a hunch is idempotent in ``hunch_id``;
* a hunch whose gesture is older than :data:`HUNCH_ACTIONABLE_S` when the desk finally
  reads it is recorded as **expired, not acted on**, with the reason on the row. The tape
  keeps the fact; the book refuses the fill. Opening a position now at a price the operator
  never saw would be a fabricated fill, and "the desk was down" is a censoring event, which
  this repo prices rather than drops.

TWO CLOCKS, AND WHO OWNS THEM
-----------------------------
``t_event`` on a hunch row is the **gesture** -- the instant the operator hit enter -- and
its source is ``operator:gesture``. That is a real event clock owned by a real source, the
same status the callout feed's post time has and the firehose's absent one does not.
``t_ingest`` is when the row was persisted. The desk stamps its OWN ingest clock when it
reads the row, so a hunch that sat on disk through a restart carries the whole story: when
it was meant, when it was written, when it was seen.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Iterator

__all__ = [
    "HUNCH_ACTIONABLE_S",
    "HUNCH_PATH",
    "HUNCH_SCHEMA",
    "KIND_CLAIMS",
    "RETRACTION_SCHEMA",
    "ZAP_SCHEMA",
    "Hunch",
    "HunchSource",
    "Retraction",
    "Zap",
    "append_hunch",
    "append_retraction",
    "append_zap",
    "default_horizon_s",
    "new_hunch_id",
    "read_hunches",
    "read_tape",
    "read_zaps",
]

STATE: Final[Path] = Path(__file__).resolve().parent.parent / "state"

#: One file, forever, deliberately not day-partitioned. Hunches arrive a handful a day and
#: the tape's job is to be a corpus; a reader that has to glob and sort is a reader that
#: will one day miss a day.
HUNCH_PATH: Final[Path] = STATE / "hunches.jsonl"

#: Bumped when the row shape changes in a way a reader must know about. Readers keep
#: handling old versions; that is what the field is for.
HUNCH_SCHEMA: Final[str] = "hunch.v1"

#: A ZAP row: the operator closing a position because they do not like what they are
#: looking at. The other half of the gesture corpus, and the more valuable half.
#:
#: The operator's own account of what they actually do: *"a dashboard view that always lets
#: me zap out a position that i decide i dont like. because that's basically what i do... i
#: watch it closely, and pull out the position whenever i feel like it."*
#:
#: THAT IS A REACTIVE EXIT POLICY AND NOBODY HAS EVER RECORDED ITS INPUTS. Every exit rule
#: in this repo is a function of the clock or of one threshold, because the clock and the
#: threshold are the only things anybody wrote down. A zap row carries the INSTRUMENT STATE
#: AT THE MOMENT OF THE EXIT -- the recent price path, flow, depth, drawdown, the position's
#: own P&L and age -- alongside the exit itself, which makes ``(state, exit)`` pairs. Those
#: pairs are the training set for a reactive exit policy: the search that replaces the
#: wiggle book's five-minute clock with something fitted to what the operator is actually
#: reacting to. Every field dropped from a zap row is a feature that search will not have.
ZAP_SCHEMA: Final[str] = "hunch.zap.v1"

#: A RETRACTION row. The tape is append-only and nothing on it is ever edited or deleted --
#: including a gesture that turns out not to have been one. A misclick, or a row a test
#: harness wrote by mistake, is corrected by APPENDING a retraction naming the ``hunch_id``
#: and the reason, exactly as ``design/domain-model.md`` handles ``expectation.withdrawn``.
#:
#: Why not just delete the line: because the corpus this tape exists to become is a record
#: of what the operator did, and a file that can be edited is a file whose history is a
#: claim rather than a fact. A retraction keeps both the mistake and the correction, which
#: is strictly more information than a clean file -- and "the operator took this one back"
#: is itself a datum a distillation model should see.
RETRACTION_SCHEMA: Final[str] = "hunch.retraction.v1"

#: How stale a gesture may be when the desk first sees it and still open a position. The
#: OPERATOR book is the wiggle book's execution, whose entire horizon is 240-420 s, so a
#: gesture older than this is older than the trade it was asking for. Matches the desk's
#: own ``MAX_ACTIONABLE_AGE_S`` for observations, and for the same reason: an action the
#: desk could not have taken at the time is not an action, it is a backfill.
HUNCH_ACTIONABLE_S: Final[float] = 300.0

#: The CLI's ``--kind`` vocabulary, mapped onto the claim vocabulary of
#: ``design/domain-model.md`` §6. Small on purpose, and it grows only when scoring for the
#: new member exists FIRST -- a claim that binds to no observable is inexpressible here,
#: which is §9-rung-2 applied to the operator's own beliefs.
#:
#: ``wiggle``  -> the only kind that TRADES. "it'll oscillate enough to scalp", which the
#:                OPERATOR book answers with a real paper position on the wiggle clock.
#: ``down``    -> ``Drift(Down)``. Watch-only: no short exists on this desk, so a position
#:                would be a claim about machinery nobody has measured.
#: ``up``      -> ``Drift(Up)``. ALSO watch-only in v1, and this is a real choice rather
#:                than an oversight: the desk's only measured execution is a 5-minute
#:                scalp, and a multi-hour up-drift claim handed to a 5-minute clock would
#:                be scored as the scalp's outcome and reported as the belief's. When a
#:                hold-shaped execution is measured, this is where it attaches.
#: ``watch``   -> direction-free. Tracked and scored on what actually happened, with no
#:                Brier, because there is no binary claim to be right or wrong about.
KIND_CLAIMS: Final[dict[str, str]] = {
    "wiggle": "wiggle",
    "down": "drift_down",
    "up": "drift_up",
    "watch": "watch",
}

#: Default horizons per kind. PRIORS, and short ones: a horizon is the window over which
#: the desk must keep OBSERVING the coin to score the claim at all, and this desk's
#: observation of an arbitrary mint is a rate-limited refresh, not a subscription. A 3-day
#: default would mostly manufacture censored rows.
#:
#: ``wiggle`` takes no default because its horizon is not a preference -- it is the book's
#: drawn clock, 240-420 s, and letting a flag widen it is precisely how discipline drift
#: would enter the code rather than the trading.
DEFAULT_HORIZON_S: Final[dict[str, float]] = {
    "down": 3_600.0,
    "up": 3_600.0,
    "watch": 1_800.0,
}


def default_horizon_s(kind: str) -> float | None:
    """``None`` for ``wiggle``: its horizon belongs to the book's clock, not to a flag."""
    return DEFAULT_HORIZON_S.get(kind)


def iso(unix: float) -> str:
    return datetime.fromtimestamp(unix, tz=UTC).isoformat()


def new_hunch_id(mint: str, unix: float) -> str:
    """Stable, sortable, and an identifier the tape contract will accept verbatim.

    ``[A-Za-z0-9_-]`` only, because this id is carried onto ledger rows and eventually into
    a :class:`shitcoims_tape.schema.PropensityRecord` decision id, which validates as an
    identifier and would raise on anything else at write time.
    """
    return f"hn-{int(unix * 1000)}-{os.getpid()}-{mint[:8]}"


@dataclass(frozen=True, slots=True)
class Hunch:
    """One utterance about one coin, parsed but never replaced by its parse.

    Field-for-field this is ``design/domain-model.md``'s ``Expectation`` with the names it
    will import under: ``scope`` (a mint), ``claim`` (from the closed vocabulary),
    ``horizon``, ``confidence`` (what Brier scores), ``utterance`` (VERBATIM), ``evidence``
    (the instrument reading at the moment of the gesture) and ``recorded_at``. What is
    missing versus that design is the compiler and the approval diff, and that is the honest
    state of it: this is M1 in v1 form, a record and a paper position, not a proposal
    pipeline. Nothing here arms anything.
    """

    hunch_id: str
    run_id: str
    mint: str
    symbol: str | None
    kind: str
    claim: str
    utterance: str
    confidence: float
    horizon_s: float | None
    size_lamports: int
    t_gesture_unix: float
    t_ingest_unix: float
    resolution: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    schema: str = HUNCH_SCHEMA

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "hunch_id": self.hunch_id,
            "run_id": self.run_id,
            # Two clocks, and on this row the event clock is a PERSON.
            "t_event": iso(self.t_gesture_unix),
            "t_event_unix": self.t_gesture_unix,
            "t_event_source": "operator:gesture",
            "t_ingest": iso(self.t_ingest_unix),
            "t_ingest_unix": self.t_ingest_unix,
            # Expectation-shaped: scope, claim, horizon, confidence, utterance, evidence.
            "scope": {"kind": "mint", "mint": self.mint, "symbol": self.symbol},
            "claim": {"kind": self.claim},
            "kind": self.kind,
            "horizon_s": self.horizon_s,
            "confidence": self.confidence,
            "utterance": self.utterance,
            "size_lamports": self.size_lamports,
            "resolution": self.resolution,
            "evidence": self.evidence,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "Hunch | None":
        """Parse one tape row, or ``None`` if it is not one. Never raises on a bad row.

        A corrupt line in a tape that is never rewritten must not be able to stop the desk
        from reading the good lines after it.
        """
        if payload.get("schema") in {RETRACTION_SCHEMA, ZAP_SCHEMA}:
            return None
        try:
            scope = payload.get("scope") or {}
            mint = scope.get("mint") or payload.get("mint")
            hunch_id = payload.get("hunch_id")
            kind = str(payload.get("kind") or "wiggle")
            if not isinstance(mint, str) or not isinstance(hunch_id, str) or not mint:
                return None
            horizon = payload.get("horizon_s")
            return cls(
                hunch_id=hunch_id,
                run_id=str(payload.get("run_id") or ""),
                mint=mint,
                symbol=scope.get("symbol"),
                kind=kind,
                claim=str((payload.get("claim") or {}).get("kind") or KIND_CLAIMS.get(kind, kind)),
                utterance=str(payload.get("utterance") or ""),
                confidence=float(payload.get("confidence") or 0.0),
                horizon_s=float(horizon) if horizon is not None else None,
                size_lamports=int(payload.get("size_lamports") or 0),
                t_gesture_unix=float(payload.get("t_event_unix") or 0.0),
                t_ingest_unix=float(payload.get("t_ingest_unix") or 0.0),
                resolution=dict(payload.get("resolution") or {}),
                evidence=dict(payload.get("evidence") or {}),
                schema=str(payload.get("schema") or HUNCH_SCHEMA),
            )
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class Zap:
    """"I don't like this any more." The exit gesture, with the state that provoked it.

    ``state`` is the whole point and is deliberately unstructured: whatever the instrument
    could measure at the instant the operator decided, stored as it was measured. A schema
    that constrained it would be a bet on which feature the exit policy will turn out to
    need, made by the code that has the least evidence about that.

    ``reason`` is the operator's own words when they typed any, verbatim as ever, and empty
    when they just hit the key -- which is the normal case and is honest as an empty string.
    """

    zap_id: str
    mint: str
    position_id: str | None
    reason: str
    t_event_unix: float
    t_ingest_unix: float
    run_id: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    schema: str = ZAP_SCHEMA

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "zap_id": self.zap_id,
            "scope": {"kind": "mint", "mint": self.mint},
            "mint": self.mint,
            "position_id": self.position_id,
            "reason": self.reason,
            "run_id": self.run_id,
            # Two clocks: the keystroke, and when it was persisted.
            "t_event": iso(self.t_event_unix),
            "t_event_unix": self.t_event_unix,
            "t_event_source": "operator:zap",
            "t_ingest": iso(self.t_ingest_unix),
            "t_ingest_unix": self.t_ingest_unix,
            # THE TRAINING SET. Everything the desk could see when they decided to leave.
            "state": self.state,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "Zap | None":
        if payload.get("schema") != ZAP_SCHEMA:
            return None
        mint = payload.get("mint") or (payload.get("scope") or {}).get("mint")
        zap_id = payload.get("zap_id")
        if not isinstance(mint, str) or not isinstance(zap_id, str) or not mint:
            return None
        return cls(
            zap_id=zap_id,
            mint=mint,
            position_id=payload.get("position_id"),
            reason=str(payload.get("reason") or ""),
            t_event_unix=float(payload.get("t_event_unix") or 0.0),
            t_ingest_unix=float(payload.get("t_ingest_unix") or 0.0),
            run_id=str(payload.get("run_id") or ""),
            state=dict(payload.get("state") or {}),
        )


@dataclass(frozen=True, slots=True)
class Retraction:
    """"That was not a gesture." Appended, never applied by editing.

    Carries the same two clocks as a hunch, because taking something back is itself an act
    at a moment: ``t_event`` is when the operator decided, ``t_ingest`` when it was written.
    """

    retracts: str
    reason: str
    t_event_unix: float
    t_ingest_unix: float
    run_id: str = ""
    schema: str = RETRACTION_SCHEMA

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "retracts": self.retracts,
            "reason": self.reason,
            "run_id": self.run_id,
            "t_event": iso(self.t_event_unix),
            "t_event_unix": self.t_event_unix,
            "t_event_source": "operator:retraction",
            "t_ingest": iso(self.t_ingest_unix),
            "t_ingest_unix": self.t_ingest_unix,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "Retraction | None":
        if payload.get("schema") != RETRACTION_SCHEMA:
            return None
        retracts = payload.get("retracts")
        if not isinstance(retracts, str) or not retracts:
            return None
        return cls(
            retracts=retracts,
            reason=str(payload.get("reason") or ""),
            t_event_unix=float(payload.get("t_event_unix") or 0.0),
            t_ingest_unix=float(payload.get("t_ingest_unix") or 0.0),
            run_id=str(payload.get("run_id") or ""),
        )


def _append(payload: dict[str, Any], path: Path | None) -> Path:
    target = path or HUNCH_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
    with target.open("a") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return target


def new_zap_id(mint: str, unix: float) -> str:
    return f"zp-{int(unix * 1000)}-{os.getpid()}-{mint[:8]}"


def append_zap(zap: Zap, *, path: Path | None = None) -> Path:
    """Record an exit gesture, fsynced, before anything else happens.

    Same ordering contract as a hunch and for a stronger reason: a zap is the operator
    deciding to get out, and the row must survive the desk, the browser and the box.
    """
    return _append(zap.to_json(), path)


def read_zaps(path: Path | None = None) -> list[Zap]:
    """Every LIVE exit gesture, oldest first. The ``(state, exit)`` corpus in one call.

    Retractions apply here exactly as they do to hunches, and they matter more: a zap that
    was not the operator's is a fabricated training pair, and the reactive-exit search
    would fit to it as readily as to a real one. ``read_tape`` is the auditor's view and
    still returns everything.
    """
    _, retractions, zaps = read_tape(path)
    if not retractions:
        return zaps
    taken_back = {r.retracts for r in retractions}
    return [z for z in zaps if z.zap_id not in taken_back]


def append_retraction(
    hunch_id: str, reason: str, *, path: Path | None = None, now: float | None = None
) -> Path:
    """Take a gesture back. The original row stays on the tape, forever, beside this one."""
    when = time.time() if now is None else now
    return _append(
        Retraction(
            retracts=hunch_id, reason=reason, t_event_unix=when, t_ingest_unix=when
        ).to_json(),
        path,
    )


def append_hunch(hunch: Hunch, *, path: Path | None = None) -> Path:
    """Append one row and FSYNC it. The one operation in this module that must not fail.

    Flush-and-fsync rather than flush alone because the whole point of the tape is that a
    thing the operator said survives everything -- including the crash that a live desk
    makes more likely, not less. It costs a millisecond, once per gesture.
    """
    return _append(hunch.to_json(), path)


def read_tape(path: Path | None = None) -> tuple[list[Hunch], list[Retraction], list[Zap]]:
    """Everything on the tape, oldest first, by kind. Retractions are NOT applied here.

    The auditor's view. :func:`read_hunches` is the reader's view and applies them.
    """
    target = path or HUNCH_PATH
    hunches: list[Hunch] = []
    retractions: list[Retraction] = []
    zaps: list[Zap] = []
    try:
        with target.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                retraction = Retraction.from_json(payload)
                if retraction is not None:
                    retractions.append(retraction)
                    continue
                zap = Zap.from_json(payload)
                if zap is not None:
                    zaps.append(zap)
                    continue
                parsed = Hunch.from_json(payload)
                if parsed is not None:
                    hunches.append(parsed)
    except OSError:
        pass
    return hunches, retractions, zaps


def read_hunches(path: Path | None = None) -> list[Hunch]:
    """The live tape, oldest first: retractions applied, corrupt lines skipped.

    A retracted hunch is absent from THIS view and still present on disk. Anything scoring
    the operator reads this; anything auditing the file reads :func:`read_tape`.
    """
    hunches, retractions, _ = read_tape(path)
    if not retractions:
        return hunches
    taken_back = {r.retracts for r in retractions}
    return [h for h in hunches if h.hunch_id not in taken_back]


class HunchSource:
    """Tails ``state/hunches.jsonl`` into the desk. The only source whose events are a PERSON.

    Deliberately NOT a :class:`shitcoims_paperdesk.feeds.Source` subclass, because every
    contract on that class is about a market observer and none of them fit here:

    * ``seconds_since_event`` on a market feed distinguishes a cold collector from a quiet
      market. On this feed silence means the operator is asleep, which is neither, so the
      desk must never render a quiet hunch tape as a stale source and never open a
      ``watch_close`` with ``OBSERVER_LOST`` over it. It is still reported in the
      heartbeat -- as a COUNT and an age, with no staleness verdict attached.
    * ``from_start`` is the default here and the refusal everywhere else. See the module
      docstring: replaying board snapshots fabricates fills; replaying hunches cannot,
      because ``hunch_id`` makes acting on one idempotent and the desk holds the ids it has
      already acted on in its persisted state.
    """

    name = "hunches"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or HUNCH_PATH
        self.events = 0
        self.last_event_unix: float = 0.0
        self.bad_lines = 0
        self._offset = 0
        self._partial = ""

    def poll(self, now: float) -> list[Hunch | Retraction | Zap]:
        """Every row appended since the last poll, oldest first, in tape order.

        Returns the union type rather than filtering the other kinds out, because ORDER is
        the whole content of them: a hunch and the retraction that follows it two seconds
        later are two events, and a consumer that only ever saw the first would open a
        position the operator had already taken back. A zap is the same shape of fact in the
        other direction. The desk dispatches on the type.

        Reuses the partial-line discipline of :class:`shitcoims_paperdesk.feeds.JsonlTail`
        rather than that class itself, because that tailer takes a per-poll path callback
        and attaches at EOF, and both of those are wrong here in ways a flag would hide.
        """
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self._offset:  # truncated or replaced under us: re-read from the top
            self._offset = 0
            self._partial = ""
        if size <= self._offset:
            return []
        try:
            with self.path.open("rb") as fh:
                fh.seek(self._offset)
                chunk = fh.read(size - self._offset)
        except OSError:
            return []
        self._offset += len(chunk)
        text = self._partial + chunk.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._partial = lines.pop()
        out: list[Hunch | Retraction | Zap] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                self.bad_lines += 1
                continue
            if not isinstance(payload, dict):
                self.bad_lines += 1
                continue
            parsed: Hunch | Retraction | Zap | None = Retraction.from_json(payload)
            if parsed is None:
                parsed = Zap.from_json(payload)
            if parsed is None:
                parsed = Hunch.from_json(payload)
            if parsed is None:
                self.bad_lines += 1
                continue
            out.append(parsed)
        if out:
            self.events += len(out)
            self.last_event_unix = now
        return out

    def seconds_since_event(self, now: float) -> float:
        """Age of the last hunch, or of the desk's start. Reported, never used as staleness."""
        return now - self.last_event_unix if self.last_event_unix else float("nan")

    def __iter__(self) -> Iterator[Hunch | Retraction | Zap]:  # pragma: no cover - convenience
        return iter(self.poll(time.time()))
