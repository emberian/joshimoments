"""The live screen service: every new pump.fun launch, scored within seconds.

SHAPE
-----
One process, three lanes sharing an asyncio loop:

* the FIREHOSE lane is :class:`shitcoims_scalper.firehose.FirehoseClient` verbatim —
  subscribeNewToken over the PumpPortal socket, with that module's whole weather
  discipline inherited rather than reimplemented: watch_open/close windows, gap rows on
  reconnect AND across restarts, heartbeats, staleness alarms, jittered backoff. Its
  tape lands under ``state/dregg_screen/firehose/`` so this service's listening record
  is self-contained. A sink adapter forwards each ``new_token`` row into the queue.
* SCORER workers pop launches, score the cheap (websocket + ledger) gates immediately,
  and hydrate the birth slot via Helius only where the policy says the spend can matter
  (see THE POLICY below). Scores append to ``scores/<day>.jsonl``, refresh the rolling
  ``latest.json`` (atomic tmp+rename), and append the TG-postable line to
  ``tg-<day>.log``. NOTHING IS POSTED — the gate/bot lane consumes the artifacts.
* the HEARTBEAT lane writes ``heartbeat.json`` atomically every cycle: verdict counts,
  queue depth, Helius budget spent/ceiling, ledger build + corpus span + staleness,
  firehose liveness. A dead lane is visible within a minute, not at the post-mortem.

THE POLICY (why most launches cost zero Helius)
-----------------------------------------------
The screen is a CONJUNCTION, so a launch that already fails a cheap gate cannot be
rescued by hydration — only launches whose cheap gates ALL pass can possibly mint a
CLEAN, and those are the only ones worth the spend. Measured on the fresh corpus
(2026-08-26..28, 34.8k launches/day): the cheap gates (dev buy < 2%, deployer with no
recorded rips/dumps) pass ~16% of dev-buy launches; no-dev-buy launches (~16% more,
outside the validated population but scored with a flag) mostly pass too. At the
measured ~2-3 Helius requests per hydration that is ~15-30k requests/day depending on
``hydrate_no_dev_buy`` — against ~90k/day for hydrating everything. When the daily
ceiling is hit, launches are emitted as UNSCORED(budget) with their cheap features
attached, FIFO, honestly — never silently dropped.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import time
import tomllib
from collections import deque
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from shitcoims_scalper.firehose import (
    Feed,
    FirehoseClient,
    JsonlSink,
    last_close_on_disk,
)

from .features import cheap_features_from_event, extract_birth_features
from .hydrate import BudgetExhausted, DailyBudget, HydrationFailed, Hydrator, helius_url
from .ledger import Ledger, resolve_current
from .score import base_rates_from_ledger, score_launch

LOGGER = logging.getLogger("dregg_screen.live")

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class Config:
    state_dir: Path = REPO_ROOT / "state" / "dregg_screen"
    ledger_path: Path | None = None  # default: <ledger dir>/current.sqlite
    helius_key_file: str = "~/.helius-key"
    daily_helius_budget: int = 30_000
    hydrate_delay_s: float = 3.0  # let the RPC index the birth slot before asking
    hydrate_no_dev_buy: bool = True  # spend on the out-of-population stratum too
    hydrate_mayhem: bool = False  # mayhem creates measured 10/10 nonstandard (2e15 mint):
    #                                 hydration can only confirm UNSCORED, so skip the spend
    hydrate_all: bool = False  # full coverage; only sane with a budget sized for ~90k/day
    workers: int = 4
    queue_max: int = 2000
    latest_n: int = 200
    heartbeat_s: float = 30.0
    crew_min_overlap: int = 2
    crew_min_jaccard: float = 0.10
    max_same_slot_txs: int = 6

    @classmethod
    def load(cls, path: Path | None) -> "Config":
        cfg = cls()
        if path is None:
            return cfg
        raw = tomllib.loads(path.read_text())
        for key, value in raw.items():
            if not hasattr(cfg, key):
                raise ValueError(f"unknown config key {key!r}")
            current = getattr(cfg, key)
            if isinstance(current, Path) or (current is None and key == "ledger_path"):
                value = Path(str(value)).expanduser()
                if not value.is_absolute():
                    value = REPO_ROOT / value
            elif isinstance(current, bool):
                if not isinstance(value, bool):
                    raise ValueError(f"config key {key!r}: expected bool")
            elif isinstance(current, int):
                value = int(value)
            elif isinstance(current, float):
                value = float(value)
            cfg = replace(cfg, **{key: value})
        return cfg


@dataclass(slots=True)
class Launch:
    """One create event, queued for scoring."""

    payload: dict[str, Any]
    t_ingest: str
    received_monotonic: float


class ScreenSink:
    """Forwards firehose rows to the tape AND create events into the scoring queue.

    The tape keeps the full weather record (gaps, heartbeats, defects); the queue gets
    only ``new_token`` rows. A full queue is an honest verdict, not a silent drop: the
    launch is scored immediately as UNSCORED(queue_overflow) from its cheap features.
    """

    def __init__(self, tape: JsonlSink, service: "ScreenService") -> None:
        self.tape = tape
        self.service = service

    @property
    def rows_written(self) -> int:
        return self.tape.rows_written

    def write(self, partition: str, row: Mapping[str, Any]) -> None:
        self.tape.write(partition, row)
        if row.get("kind") != "new_token":
            return
        payload = row.get("payload")
        if isinstance(payload, dict):
            self.service.enqueue(Launch(
                payload=payload,
                t_ingest=str(row.get("t_ingest")),
                received_monotonic=time.monotonic(),
            ))

    def close(self) -> None:
        self.tape.close()


class ScreenService:
    def __init__(self, cfg: Config, *, hydrator: Hydrator | None = None,
                 ledger: Ledger | None = None) -> None:
        self.cfg = cfg
        self.state_dir = cfg.state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = ledger or Ledger(cfg.ledger_path or resolve_current())
        self.base_rates = base_rates_from_ledger(self.ledger)
        self.budget = DailyBudget(
            ceiling=cfg.daily_helius_budget, path=self.state_dir / "helius_budget.json"
        )
        self.hydrator = hydrator or Hydrator(
            budget=self.budget,
            url=helius_url(cfg.helius_key_file),
            max_same_slot_txs=cfg.max_same_slot_txs,
        )
        self.queue: asyncio.Queue[Launch] = asyncio.Queue(maxsize=cfg.queue_max)
        self.latest: deque[dict[str, Any]] = deque(maxlen=cfg.latest_n)
        self.counts: dict[str, int] = {}
        self.events_seen = 0
        self.hydrations = 0
        self.overflow = 0
        self.started_at = datetime.now(UTC)
        self._score_file: Any = None
        self._score_day = ""
        self._tg_file: Any = None

    # -- intake ------------------------------------------------------------------

    def enqueue(self, launch: Launch) -> None:
        self.events_seen += 1
        try:
            self.queue.put_nowait(launch)
        except asyncio.QueueFull:
            self.overflow += 1
            self._emit(self._score(launch, unscored_reason="queue_overflow"), launch)

    # -- policy ------------------------------------------------------------------

    def _wants_hydration(self, launch: Launch) -> tuple[bool, str | None]:
        """Spend only where a CLEAN is reachable — or everywhere, if configured."""

        cheap = cheap_features_from_event(launch.payload)
        if not cheap.signature or not cheap.mint:
            return False, "event_missing_signature_or_mint"
        if self.cfg.hydrate_all:
            return True, None
        if cheap.is_mayhem_mode and not self.cfg.hydrate_mayhem:
            # The validated screen is defined on standard-supply births only; a mayhem
            # create (measured: mints 2e15) can only ever hydrate into UNSCORED.
            return False, "policy:mayhem_flag_nonstandard_curve"
        history = self.ledger.deployer_history(cheap.creator)
        if history.rips > 0 or history.dumps > 0:
            return False, None  # cheap verdict is already KNOWN_CREW
        if cheap.dev_buy_share_est >= 0.02:
            return False, None  # cheap verdict is already NOT_CLEAN
        if cheap.dev_buy_raw_est == 0 and not self.cfg.hydrate_no_dev_buy:
            return False, "policy:no_dev_buy_stratum_disabled"
        return True, None

    # -- scoring -----------------------------------------------------------------

    def _score(self, launch: Launch, *, birth=None, unscored_reason: str | None = None):
        cheap = cheap_features_from_event(launch.payload)
        return score_launch(
            cheap,
            birth,
            self.ledger,
            unscored_reason=unscored_reason,
            crew_min_overlap=self.cfg.crew_min_overlap,
            crew_min_jaccard=self.cfg.crew_min_jaccard,
            base_rates=self.base_rates,
        )

    async def _worker(self) -> None:
        while True:
            launch = await self.queue.get()
            try:
                await self._handle(launch)
            except Exception:
                LOGGER.exception("scoring failed for %s", launch.payload.get("mint"))
            finally:
                self.queue.task_done()

    async def _handle(self, launch: Launch) -> None:
        wants, reason = self._wants_hydration(launch)
        birth = None
        extra: dict[str, Any] = {}
        if wants:
            # Give the RPC a beat to index the slot; the event is seconds old at most.
            age = time.monotonic() - launch.received_monotonic
            if age < self.cfg.hydrate_delay_s:
                await asyncio.sleep(self.cfg.hydrate_delay_s - age)
            cheap = cheap_features_from_event(launch.payload)
            try:
                slot = await self.hydrator.birth_slot(cheap.mint, cheap.signature or "")
                birth = extract_birth_features(
                    cheap.mint, slot.create_tx, slot.same_slot_txs, partial=slot.partial
                )
                self.hydrations += 1
                extra["hydration"] = {
                    "birth_slot": slot.slot, "requests": slot.requests,
                    "same_slot_txs": len(slot.same_slot_txs), "partial": slot.partial,
                }
            except BudgetExhausted:
                reason = "budget:daily_helius_ceiling"
            except HydrationFailed as exc:
                reason = f"hydration_failed:{exc}"[:160]
        score = self._score(launch, birth=birth, unscored_reason=reason)
        self._emit(score, launch, extra)

    # -- outputs -----------------------------------------------------------------

    def _emit(self, score, launch: Launch, extra: dict[str, Any] | None = None) -> None:
        now = datetime.now(UTC)
        row = score.row()
        row.update(extra or {})
        row["t_event_ingest"] = launch.t_ingest
        row["t_scored"] = now.isoformat(timespec="microseconds")
        row["ledger"] = {
            "built_at": self.ledger.meta.get("built_at"),
            "corpus_span": self.ledger.meta.get("corpus_span"),
            "staleness_days": self.ledger.staleness_days,
        }
        self.counts[score.verdict] = self.counts.get(score.verdict, 0) + 1

        day = now.date().isoformat()
        if day != self._score_day:
            if self._score_file:
                self._score_file.close()
            if self._tg_file:
                self._tg_file.close()
            scores_dir = self.state_dir / "scores"
            scores_dir.mkdir(parents=True, exist_ok=True)
            self._score_file = (scores_dir / f"{day}.jsonl").open("a", encoding="utf-8")
            self._tg_file = (scores_dir / f"tg-{day}.log").open("a", encoding="utf-8")
            self._score_day = day
        self._score_file.write(json.dumps(row, separators=(",", ":")) + "\n")
        self._score_file.flush()
        self._tg_file.write(row["tg_line"] + "\n")
        self._tg_file.flush()

        self.latest.append(row)
        self._write_json(self.state_dir / "latest.json", {
            "generated_at": row["t_scored"],
            "counts": dict(self.counts),
            "scores": list(self.latest),
        })

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=1) + "\n")
        os.replace(tmp, path)

    def heartbeat_payload(self, firehose: FirehoseClient | None) -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            "t": now.isoformat(timespec="seconds"),
            "up_seconds": round((now - self.started_at).total_seconds(), 1),
            "events_seen": self.events_seen,
            "queue_depth": self.queue.qsize(),
            "queue_overflow": self.overflow,
            "verdicts": dict(sorted(self.counts.items())),
            "hydrations": self.hydrations,
            "budget": {"day": self.budget.day, "spent": self.budget.spent,
                       "ceiling": self.budget.ceiling},
            "ledger": {
                "path": str(self.ledger.path),
                "built_at": self.ledger.meta.get("built_at"),
                "corpus_span": self.ledger.meta.get("corpus_span"),
                "staleness_days": self.ledger.staleness_days,
                "stale_warning": (self.ledger.staleness_days or 0) > 14,
            },
            "firehose": {
                "windows": firehose.ledger.windows,
                "gaps": firehose.ledger.gaps,
                "gap_seconds": round(firehose.ledger.gap_seconds, 1),
                "connected": firehose.ledger.current is not None,
                "events_by_kind": dict(firehose.events_by_kind),
            } if firehose else None,
        }

    async def _heartbeat_loop(self, firehose: FirehoseClient) -> None:
        while True:
            self._write_json(self.state_dir / "heartbeat.json",
                             self.heartbeat_payload(firehose))
            await asyncio.sleep(self.cfg.heartbeat_s)

    # -- the run -----------------------------------------------------------------

    async def run(self, minutes: float | None = None) -> dict[str, Any]:
        tape_root = self.state_dir / "firehose"
        resume_from = last_close_on_disk(tape_root)
        client = FirehoseClient(
            sink=ScreenSink(JsonlSink(tape_root), self),
            feeds=(Feed.NEW_TOKEN,),
            resume_from=resume_from,
        )
        workers = [asyncio.create_task(self._worker()) for _ in range(self.cfg.workers)]
        beat = asyncio.create_task(self._heartbeat_loop(client))
        deadline = (
            datetime.now(UTC) + timedelta(minutes=minutes) if minutes is not None else None
        )
        loop = asyncio.get_running_loop()
        import signal as _signal
        for signame in ("SIGINT", "SIGTERM"):
            sig = getattr(_signal, signame, None)
            if sig is not None:
                with contextlib.suppress(NotImplementedError):
                    loop.add_signal_handler(sig, client.stop)
        try:
            stats = await client.run(deadline=deadline)
        finally:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.queue.join(), timeout=30.0)
            for task in (*workers, beat):
                task.cancel()
            await asyncio.gather(*workers, beat, return_exceptions=True)
            await self.hydrator.close()
            self._write_json(self.state_dir / "heartbeat.json", self.heartbeat_payload(None))
            if self._score_file:
                self._score_file.close()
            if self._tg_file:
                self._tg_file.close()
        summary = {
            "firehose": stats.to_json(),
            "events_seen": self.events_seen,
            "verdicts": dict(sorted(self.counts.items())),
            "hydrations": self.hydrations,
            "helius_spent_today": self.budget.spent,
        }
        return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dregg_screen.live", description=__doc__)
    ap.add_argument("--config", type=Path, default=None, help="TOML config (see config.example.toml)")
    ap.add_argument("--minutes", type=float, default=None, help="stop after N minutes (smoke runs)")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = Config.load(args.config)
    service = ScreenService(cfg)
    LOGGER.info(
        "dregg_screen starting: ledger %s (corpus %s, %s days stale), budget %d/day, "
        "policy hydrate_all=%s hydrate_no_dev_buy=%s",
        service.ledger.path, service.ledger.meta.get("corpus_span"),
        service.ledger.staleness_days, cfg.daily_helius_budget,
        cfg.hydrate_all, cfg.hydrate_no_dev_buy,
    )
    summary = asyncio.run(service.run(minutes=args.minutes))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
