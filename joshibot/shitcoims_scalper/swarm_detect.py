"""Imitation-swarm detection over the pump.fun launch stream.

The hypothesis this module instruments, in the operator's words: *"noticing when
scam/imitators start popping up. I'm willing to bet that if we are fast we can setup
positions that will massively gain from them when they are even slightly legitimate."*

Why it is a different animal from the callout channel
-----------------------------------------------------
``studies/RESULT_callout_edge.md`` measured social callouts as an **anti**-signal: buying
one returns −11.9% at 1 h, and permuting caller identity *beat* the real identity 24/24.
The structural reading offered there is that talking is free, so a callout is cheap talk
emitted by someone recruiting exit liquidity.

An imitator is not talking. Launching a clone costs a create transaction plus an initial
buy (median ~0.5 SOL of dev buy in this tape), and it is emitted by an adversary who has
*chosen a target*. A swarm of clones around one coin is therefore a market-implied
attention estimate produced by parties with skin in the game — a **costly signal**. That is
the one theoretical reason to expect a different answer than the callout study got, and it
is the thing the data has to either survive or kill.

What is actually observable, and the discriminator
--------------------------------------------------
Every ``create`` frame carries ``traderPublicKey`` — the deployer. That single field splits
the phenomenon in two, and the two must never be pooled:

* **parasite swarm** — N *distinct* deployers converge on one host. Independent adversaries
  each paying to attach themselves to the same attention object. This is the hypothesis.
* **launch farm** — one deployer emits N near-identical coins. This is a factory shipping
  inventory; the "target" may be nothing at all. Possibly informative in its own right
  (MELT puts 36.5% of supply in coordinated hands), but it is a different measurement and
  it is reported separately.

Collision noise is the null, and it is large
--------------------------------------------
The callout study's cashtag resolver measured only **23.6%** of launches carrying a ticker
unique within 30 minutes. ``SOLANA``, ``TRUMPCOIN`` and ``COPE`` are ambient: a name
collision is the *base state* of this market, not an event. So "3 coins share a symbol" is
not a detection — the detector emits families, and the study calibrates the onset threshold
against a **rotation null** (:func:`rotate_stream`) that keeps the launch-time process and
the symbol distribution exactly as observed and destroys only their alignment.

Two clocks
----------
Same discipline as :mod:`shitcoims_scalper.firehose`. ``t_ingest`` is our clock, stamped
when the row was read off a socket or an API response. ``t_event`` is the vendor's, and it
is non-null **iff** the vendor supplied one:

* PumpPortal ``create`` frames carry no clock at all → ``t_event`` is null there, and the
  firehose tape says so in words on every row.
* The pump.fun ``/coins`` REST census *does* carry ``created_timestamp`` → those rows have a
  real ``t_event``, and the census is therefore what dates a launch.

A detector that ran off ``t_ingest`` alone would be measuring our socket, so the replay
prefers ``t_event`` whenever the census supplies one and records which clock it used.

Why there is a census at all
----------------------------
The firehose is a socket and sockets drop. Measured on ``state/firehose/`` for
2026-08-15: one clean 56-minute segment, one 172-minute hole, and a 10-minute stretch where
*two* windows were connected at once and every launch landed twice. Meanwhile the pump.fun
REST list is a poller — the failure mode this repo already got burned by — but it is a
poller over a *different* transport, so their union is strictly better than either, and the
disagreement between them is itself a measurement. Coverage of the socket against the REST
list over a quiet 33-minute window: **565/572 = 98.8%**, so the socket is good when it is
up; the census exists for when it is not, and for ``image_uri``, which PumpPortal never
sends.

``/coins?sort=created_timestamp&order=DESC`` pages to a hard wall at ``offset≈2000`` (empty
list beyond), which is ~1.9 h at the observed ~1090 launches/hour. So the census can heal a
short hole and cannot resurrect a long one; a run started after a two-hour outage has lost
that data permanently, and the study excludes such intervals rather than zero-filling them.

Usage
-----
::

    # gap-filling / enriching census, runs alongside the firehose (~30 req / 20 min)
    python -m shitcoims_scalper.swarm_detect census --loop --interval 300

    # offline, deterministic replay of the recorded tapes -> state/swarms/*.jsonl
    python -m shitcoims_scalper.swarm_detect replay --report

    # same, with the launch attributes rotated against the clock (the ambient null)
    python -m shitcoims_scalper.swarm_detect replay --rotate 3600 --out-tag null
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import random
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
FIREHOSE_NEW_TOKEN = STATE / "firehose" / "new_token"
FIREHOSE_LEDGER = STATE / "firehose" / "ledger"
SWARMS = STATE / "swarms"

PUMP_API = "https://frontend-api-v3.pump.fun"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) joshibot-research/1.0"

#: pump.fun fixed supply. Market cap in SOL is price × this, so the two are interchangeable
#: for returns and only one of them needs to be stored.
PUMP_SUPPLY = 1_000_000_000.0

#: The REST list stops serving beyond this offset (measured: ``offset=2000`` returns ``[]``).
CENSUS_MAX_OFFSET = 2000
CENSUS_PAGE = 50


# --------------------------------------------------------------------------------------
# launch record
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Launch:
    """One token creation, from whichever transport saw it.

    ``t`` is the launch time the detector runs on, in epoch seconds, and ``t_source`` says
    which clock it came from. ``vendor`` means pump.fun's own ``created_timestamp``;
    ``ingest`` means our socket clock, used only when no census row exists for the mint.
    """

    mint: str
    symbol: str
    name: str
    deployer: str
    t: float
    t_source: str
    uri: str | None = None
    image_uri: str | None = None
    sol_amount: float | None = None
    initial_buy: float | None = None
    mcap_sol: float | None = None
    t_ingest: float | None = None
    sources: tuple[str, ...] = ()

    def as_row(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["sources"] = list(self.sources)
        return d


def _epoch(iso: str) -> float:
    return dt.datetime.fromisoformat(iso).timestamp()


def _iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()


def _ms_or_s(v: float) -> float:
    """pump.fun mixes seconds and milliseconds across endpoints; normalise to seconds."""
    return v / 1000.0 if v > 1e11 else float(v)


# --------------------------------------------------------------------------------------
# normalisation and similarity
# --------------------------------------------------------------------------------------

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def norm_text(s: str | None) -> str:
    if not s:
        return ""
    return _NON_ALNUM.sub("", s.lower())


def squash_runs(s: str) -> str:
    """``readddddddddd`` -> ``read``. Runs of one character collapse to a single copy.

    Imitators lengthen a ticker to dodge exact-match tooling while keeping it readable, and
    the tape's largest single symbol cluster is literally ``READDDDDDDDDD`` (41 launches).
    Collapsing to one is what makes ``READ`` and ``READDDDDDDD`` meet; collapsing to two
    does not, because the padded form still keeps a double.

    The cost is stated rather than hidden: this also merges ``BULL`` with ``BUL`` and
    ``EGG`` with ``EG``. So it is emitted as its own match kind (``symbol_squashed``), never
    folded into ``symbol``, and every family row carries the kind counts — a family resting
    only on squashed matches is visible as such and can be excluded downstream.
    """
    out: list[str] = []
    for ch in s:
        if not out or ch != out[-1]:
            out.append(ch)
    return "".join(out)


def levenshtein(a: str, b: str, cap: int) -> int:
    """Edit distance, abandoned once it provably exceeds ``cap`` (returns ``cap + 1``)."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for j, cb in enumerate(b, 1):
        cur = [j]
        best = j
        for i, ca in enumerate(a, 1):
            v = min(prev[i] + 1, cur[i - 1] + 1, prev[i - 1] + (ca != cb))
            cur.append(v)
            best = min(best, v)
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def name_similarity(a: str, b: str) -> float:
    """1 − normalised edit distance on the alphanumeric-folded names."""
    if not a or not b:
        return 0.0
    n = max(len(a), len(b))
    cap = n  # no early abandon needed at these lengths
    return 1.0 - levenshtein(a, b, cap) / n


def trigrams(s: str) -> set[str]:
    if len(s) < 3:
        return {s} if s else set()
    return {s[i : i + 3] for i in range(len(s) - 2)}


# --------------------------------------------------------------------------------------
# the detector
# --------------------------------------------------------------------------------------

#: Match kinds, ordered strongest-first. ``uri`` and ``image`` are *identity* of the
#: metadata object: two coins pointing at one IPFS document are the same artwork and the
#: same description, which is as close to a confession as this data gets.
MATCH_KINDS = ("uri", "image", "symbol", "symbol_squashed", "name", "name_near")


@dataclass
class Family:
    """A set of launches the detector believes are imitations of one another."""

    fid: str
    members: list[Launch] = field(default_factory=list)
    kinds: Counter = field(default_factory=Counter)
    onset_emitted: bool = False
    onset_index: int | None = None
    #: every id this family has ever been known by. Families merge when a launch links two
    #: previously separate ones, and an onset already written to disk carries whichever id
    #: was current *then*; without this the join from an event back to its family silently
    #: drops the merged cases.
    aliases: set[str] = field(default_factory=set)

    @property
    def t_first(self) -> float:
        return self.members[0].t

    @property
    def t_last(self) -> float:
        return max(m.t for m in self.members)

    def deployers(self) -> Counter:
        return Counter(m.deployer for m in self.members)


class SwarmDetector:
    """Streaming, single-pass, bounded-memory imitation clustering.

    Feed it launches in time order; it yields events. It never looks forward, so a replay
    over a tape produces exactly the event sequence a live process would have produced from
    the same stream — that equivalence is what makes the latency numbers meaningful.

    Parameters
    ----------
    window_s:
        How long a launch stays eligible to attract clones. Older launches leave the
        matching index (their families stay in memory for reporting). The imitation
        response is a minutes-scale phenomenon — Marino's median time-to-graduation is 4.4
        minutes — so a 60-minute default is already generous.
    k:
        Family size at which an onset fires. **Not a discovery threshold**: at k=2 the
        ambient collision rate is enormous. The study calibrates k against
        :func:`rotate_stream`, and the detector emits families at every size so the
        threshold can be swept without a re-run.
    name_threshold:
        Minimum name similarity for a ``name_near`` link.
    traction:
        Optional ``(mint, t) -> float | None`` probe, called **only at onset** and only for
        the members of the firing family, returning that coin's traded volume in SOL up to
        ``t``. This is what makes "host" an observable rather than a guess: the host is the
        family member that had *bought attention* before the swarm arrived, not merely the
        first one to exist. Live, the probe is one HTTP call per member against
        ``swap-api.pump.fun`` (measured ~0.25 s each, so ~0.75 s for a k=3 onset); offline
        the study injects a candle-backed probe restricted to ``t`` so there is no
        look-ahead. When absent, the host falls back to the earliest member and the row says
        so in ``host_rule``.
    """

    def __init__(
        self,
        window_s: float = 3600.0,
        k: int = 3,
        name_threshold: float = 0.82,
        min_name_len: int = 4,
        traction: Any = None,
    ) -> None:
        self.traction = traction
        self.window_s = float(window_s)
        self.k = int(k)
        self.name_threshold = float(name_threshold)
        self.min_name_len = int(min_name_len)

        self._families: dict[str, Family] = {}
        self._fid_of: dict[str, str] = {}          # mint -> family id
        self._live: list[Launch] = []              # launches still inside the window
        self._by_key: dict[str, list[str]] = defaultdict(list)   # exact key -> mints
        self._by_trigram: dict[str, list[str]] = defaultdict(list)
        self._launch: dict[str, Launch] = {}
        self._seq = 0
        self._t0: float | None = None
        #: launches per deployer seen SO FAR. Distinct-deployer count is only an upper bound
        #: on independence — sybil wallets are free, and MELT puts 36.5% of supply in
        #: coordinated hands — so the cheap discriminator recorded alongside it is how much
        #: prior launch history each cloner has. A wallet with fifty prior launches in the
        #: same tape is infrastructure; a wallet on its first is at least *consistent* with
        #: an independent actor, and no more than that.
        self._dev_launches: Counter = Counter()
        self._prior_launches: dict[str, int] = {}

    # -- keys -------------------------------------------------------------------------

    def _exact_keys(self, ln: Launch) -> list[tuple[str, str]]:
        keys: list[tuple[str, str]] = []
        if ln.uri:
            keys.append(("uri", "uri\x00" + ln.uri))
        if ln.image_uri:
            keys.append(("image", "img\x00" + ln.image_uri))
        sym = norm_text(ln.symbol)
        if sym:
            keys.append(("symbol", "sym\x00" + sym))
            sq = squash_runs(sym)
            # indexed unconditionally, so a padded ticker and its unpadded twin land in the
            # same bucket; ``>= 3`` keeps two-letter debris from fusing unrelated coins
            if len(sq) >= 3:
                keys.append(("symbol_squashed", "sqs\x00" + sq))
        nm = norm_text(ln.name)
        if nm:
            keys.append(("name", "nam\x00" + nm))
        return keys

    # -- ingestion --------------------------------------------------------------------

    def push(self, ln: Launch) -> list[dict[str, Any]]:
        """Absorb one launch; return any events it triggered."""
        events: list[dict[str, Any]] = []
        if self._t0 is None:
            self._t0 = ln.t
        self._evict(ln.t)
        self._launch[ln.mint] = ln
        self._seq += 1
        prior_for_this = self._dev_launches[ln.deployer]
        self._dev_launches[ln.deployer] += 1
        self._prior_launches[ln.mint] = prior_for_this

        matches: dict[str, str] = {}  # mint -> strongest kind
        for kind, key in self._exact_keys(ln):
            for other in self._by_key.get(key, ()):
                if other != ln.mint:
                    matches.setdefault(other, kind)

        nm = norm_text(ln.name)
        if len(nm) >= self.min_name_len:
            cand: set[str] = set()
            for g in trigrams(nm):
                cand.update(self._by_trigram.get(g, ()))
            for other in cand:
                if other == ln.mint or other in matches:
                    continue
                o = self._launch.get(other)
                if o is None:
                    continue
                onm = norm_text(o.name)
                if len(onm) < self.min_name_len:
                    continue
                if name_similarity(nm, onm) >= self.name_threshold:
                    matches[other] = "name_near"

        # index this launch
        for _kind, key in self._exact_keys(ln):
            self._by_key[key].append(ln.mint)
        if len(nm) >= self.min_name_len:
            for g in trigrams(nm):
                self._by_trigram[g].append(ln.mint)
        self._live.append(ln)

        if not matches:
            fid = f"f{self._seq:07d}"
            fam = Family(fid=fid, members=[ln])
            self._families[fid] = fam
            self._fid_of[ln.mint] = fid
            return events

        # merge every matched family into the oldest one
        fids = {self._fid_of[m] for m in matches if m in self._fid_of}
        keep = min(fids, key=lambda f: (self._families[f].t_first, f))
        fam = self._families[keep]
        fam.aliases.add(keep)
        for other in fids - {keep}:
            victim = self._families.pop(other)
            fam.members.extend(victim.members)
            fam.kinds.update(victim.kinds)
            fam.onset_emitted = fam.onset_emitted or victim.onset_emitted
            fam.aliases.add(other)
            fam.aliases.update(victim.aliases)
            for m in victim.members:
                self._fid_of[m.mint] = keep
        fam.members.append(ln)
        fam.members.sort(key=lambda m: (m.t, m.mint))
        for kind in set(matches.values()):
            fam.kinds[kind] += 1
        self._fid_of[ln.mint] = keep

        if not fam.onset_emitted and len(fam.members) >= self.k:
            fam.onset_emitted = True
            fam.onset_index = len(fam.members)
            events.append(self._onset_row(fam, ln))
        return events

    def _evict(self, now: float) -> None:
        cut = now - self.window_s
        if not self._live or self._live[0].t >= cut:
            return
        drop, keep = [], []
        for ln in self._live:
            (drop if ln.t < cut else keep).append(ln)
        self._live = keep
        for ln in drop:
            for _kind, key in self._exact_keys(ln):
                bucket = self._by_key.get(key)
                if bucket and ln.mint in bucket:
                    bucket.remove(ln.mint)
                    if not bucket:
                        self._by_key.pop(key, None)
            nm = norm_text(ln.name)
            if len(nm) >= self.min_name_len:
                for g in trigrams(nm):
                    bucket = self._by_trigram.get(g)
                    if bucket and ln.mint in bucket:
                        bucket.remove(ln.mint)
                        if not bucket:
                            self._by_trigram.pop(g, None)

    # -- events -----------------------------------------------------------------------

    def _pick_host(self, members: Sequence[Launch], t: float) -> tuple[Launch, str, dict[str, float]]:
        """Earliest member, unless a traction probe says somebody else owns the attention.

        "Earliest" is the right prior — an imitation postdates its target — but it is wrong
        exactly when it matters: if the original launched before we started listening, or
        during a socket hole, the earliest member we *saw* is itself a clone. So when a
        probe is available the host is the member with the most SOL of volume transacted
        before the onset, with ties and empties falling back to earliest. Both the rule that
        fired and the probe's readings are recorded, so the two rules can be differenced.
        """
        earliest = members[0]
        if self.traction is None:
            return earliest, "earliest", {}
        readings: dict[str, float] = {}
        for m in members:
            v = self.traction(m.mint, t)
            if v is not None:
                readings[m.mint] = float(v)
        if not readings or max(readings.values()) <= 0.0:
            return earliest, "earliest_no_traction", readings
        best = max(readings.items(), key=lambda kv: (kv[1], -members.index(next(m for m in members if m.mint == kv[0]))))
        host = next(m for m in members if m.mint == best[0])
        return host, ("traction" if host.mint != earliest.mint else "traction_agrees_earliest"), readings

    def _onset_row(self, fam: Family, trigger: Launch) -> dict[str, Any]:
        members = fam.members
        host, host_rule, traction = self._pick_host(members, trigger.t)
        clones = [m for m in members if m.mint != host.mint]
        dep = Counter(m.deployer for m in clones)
        host_dep = host.deployer
        clone_spend = sum(c.sol_amount or 0.0 for c in clones)
        t_onset = trigger.t
        return {
            "kind": "swarm_onset",
            "t_ingest": _iso(time.time()),
            "t_event": _iso(t_onset),
            "t_event_source": f"launch_clock:{trigger.t_source}",
            "family_id": fam.fid,
            # The detector can only nominate a host it *saw*. If the family's earliest
            # member is itself within one window of the stream start, the true original may
            # have launched before we were listening and this "host" is really the first
            # clone. Flagged, never silently dropped.
            "host_left_censored": bool(self._t0 is not None and host.t - self._t0 < self.window_s),
            "host_rule": host_rule,
            "host_is_earliest": host.mint == members[0].mint,
            "traction_sol": traction,
            "host_mint": host.mint,
            "host_symbol": host.symbol,
            "host_name": host.name,
            "host_deployer": host_dep,
            "host_t": _iso(host.t),
            "host_sol_amount": host.sol_amount,
            "host_mcap_sol": host.mcap_sol,
            "onset_t": _iso(t_onset),
            "onset_mint": trigger.mint,
            "size": len(members),
            "clone_count": len(clones),
            "distinct_clone_deployers": len(dep),
            "clone_deployer_max_share": (max(dep.values()) / len(clones)) if clones else 0.0,
            "host_deployer_is_cloner": host_dep in dep,
            "clone_spend_sol": clone_spend,
            "clone_dev_prior_launches": [self._prior_launches.get(c.mint, 0) for c in clones],
            "clone_devs_first_launch": sum(
                1 for c in clones if self._prior_launches.get(c.mint, 0) == 0
            ),
            "host_dev_prior_launches": self._prior_launches.get(host.mint, 0),
            "match_kinds": dict(fam.kinds),
            "taxonomy": taxonomy(len(clones), dep, host_dep),
            # the two latency numbers the hypothesis lives or dies on
            "lag_from_host_s": t_onset - host.t,
            "lag_from_first_clone_s": (t_onset - clones[0].t) if clones else 0.0,
            "members": [m.mint for m in members],
        }

    def families(self) -> list[Family]:
        return sorted(self._families.values(), key=lambda f: (f.t_first, f.fid))

    def family_rows(self) -> Iterator[dict[str, Any]]:
        for fam in self.families():
            if len(fam.members) < 2:
                continue
            host = fam.members[0]
            dep = Counter(m.deployer for m in fam.members[1:])
            yield {
                "kind": "family",
                "t_ingest": _iso(time.time()),
                "t_event": _iso(fam.t_first),
                "t_event_source": f"launch_clock:{host.t_source}",
                "family_id": fam.fid,
                "aliases": sorted(fam.aliases | {fam.fid}),
                "size": len(fam.members),
                "onset_size": fam.onset_index,
                "host_mint": host.mint,
                "host_symbol": host.symbol,
                "t_first": _iso(fam.t_first),
                "t_last": _iso(fam.t_last),
                "distinct_deployers": len(fam.deployers()),
                "distinct_clone_deployers": len(dep),
                "taxonomy": taxonomy(len(fam.members) - 1, dep, host.deployer),
                "match_kinds": dict(fam.kinds),
                "members": [
                    {
                        "mint": m.mint,
                        "symbol": m.symbol,
                        "name": m.name,
                        "deployer": m.deployer,
                        "t": _iso(m.t),
                        "t_source": m.t_source,
                        "sol_amount": m.sol_amount,
                        "mcap_sol": m.mcap_sol,
                        "uri": m.uri,
                        "image_uri": m.image_uri,
                    }
                    for m in fam.members
                ],
            }


def taxonomy(n_clones: int, clone_deployers: Counter, host_deployer: str) -> str:
    """``farm`` / ``parasite`` / ``mixed`` — the split that must never be pooled.

    A farm is one wallet shipping inventory. A parasite swarm is independent adversaries
    each paying to attach to somebody else's attention. Only the second is the operator's
    hypothesis, and the threshold is stated here rather than buried: a family is a farm when
    a single deployer emitted **more than 60%** of the clones (or the host's own deployer
    did most of the cloning, which is a dev spamming their own idea), and a parasite when
    **no** deployer holds more than 60% *and* the host's deployer is absent from the clones.
    """
    if n_clones <= 0:
        return "singleton"
    top = max(clone_deployers.values())
    share = top / n_clones
    host_share = clone_deployers.get(host_deployer, 0) / n_clones
    if host_share > 0.6:
        return "self_farm"
    if share > 0.6:
        return "farm"
    if host_deployer in clone_deployers:
        return "mixed"
    return "parasite"


# --------------------------------------------------------------------------------------
# stream construction: firehose tape + REST census, deduped, restricted to listening windows
# --------------------------------------------------------------------------------------


def read_firehose(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    for p in sorted(paths):
        if not p.exists():
            continue
        with p.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("kind") == "new_token":
                    yield row


def read_census(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    for p in sorted(paths):
        if not p.exists():
            continue
        with p.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("kind") == "census_coin":
                    yield row


def listening_intervals(paths: Iterable[Path]) -> list[tuple[float, float]]:
    """Intervals during which the firehose socket was demonstrably connected.

    Read from the ledger's ``watch_open`` / ``watch_close`` / ``heartbeat`` rows. A study
    must exclude the complement rather than zero-fill it: outside these intervals the
    absence of a launch is our blindness, not the market's silence.
    """
    opens: dict[str, float] = {}
    last_seen: dict[str, float] = {}
    out: list[tuple[float, float]] = []
    for p in sorted(paths):
        if not p.exists():
            continue
        with p.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                wid = row.get("window_id") or (row.get("window") or {}).get("window_id")
                t = row.get("t_ingest")
                if not wid or not t:
                    continue
                ts = _epoch(t)
                kind = row.get("kind")
                if kind == "watch_open":
                    opens[wid] = ts
                    last_seen[wid] = ts
                else:
                    last_seen[wid] = max(last_seen.get(wid, ts), ts)
                if kind == "watch_close" and wid in opens:
                    out.append((opens.pop(wid), ts))
    for wid, t0 in opens.items():
        out.append((t0, last_seen.get(wid, t0)))
    out.sort()
    merged: list[tuple[float, float]] = []
    for a, b in out:
        if merged and a <= merged[-1][1] + 1.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def build_stream(
    firehose_paths: Sequence[Path],
    census_paths: Sequence[Path],
    restrict: Sequence[tuple[float, float]] | None = None,
) -> tuple[list[Launch], dict[str, Any]]:
    """Merge both transports into one time-ordered, mint-deduped launch stream."""
    census: dict[str, dict[str, Any]] = {}
    for row in read_census(census_paths):
        m = row["mint"]
        prev = census.get(m)
        if prev is None or row.get("t_ingest", "") < prev.get("t_ingest", ""):
            census[m] = row  # earliest observation of the coin

    seen: dict[str, Launch] = {}
    stats = Counter()
    for row in read_firehose(firehose_paths):
        mint = row.get("mint")
        if not mint:
            continue
        stats["firehose_rows"] += 1
        if mint in seen:
            stats["firehose_dupe"] += 1
            continue
        p = row.get("payload") or {}
        c = census.get(mint)
        t_ingest = _epoch(row["t_ingest"])
        if c is not None:
            t, src = _ms_or_s(c["created_timestamp"]), "vendor"
        else:
            t, src = t_ingest, "ingest"
        seen[mint] = Launch(
            mint=mint,
            symbol=p.get("symbol") or "",
            name=p.get("name") or "",
            deployer=p.get("traderPublicKey") or (c or {}).get("creator") or "",
            t=t,
            t_source=src,
            uri=p.get("uri") or (c or {}).get("metadata_uri"),
            image_uri=(c or {}).get("image_uri"),
            sol_amount=_f(p.get("solAmount")),
            initial_buy=_f(p.get("initialBuy")),
            mcap_sol=_f(p.get("marketCapSol")),
            t_ingest=t_ingest,
            sources=("firehose",) + (("census",) if c is not None else ()),
        )

    for mint, c in census.items():
        if mint in seen:
            continue
        stats["census_only"] += 1
        seen[mint] = Launch(
            mint=mint,
            symbol=c.get("symbol") or "",
            name=c.get("name") or "",
            deployer=c.get("creator") or "",
            t=_ms_or_s(c["created_timestamp"]),
            t_source="vendor",
            uri=c.get("metadata_uri"),
            image_uri=c.get("image_uri"),
            sol_amount=None,
            initial_buy=None,
            mcap_sol=_f(c.get("mcap_sol_at_first_sight")),
            t_ingest=_epoch(c["t_ingest"]) if c.get("t_ingest") else None,
            sources=("census",),
        )

    launches = sorted(seen.values(), key=lambda l: (l.t, l.mint))
    if restrict:
        launches = [l for l in launches if any(a <= l.t <= b for a, b in restrict)]
    stats["launches"] = len(launches)
    stats["vendor_clock"] = sum(1 for l in launches if l.t_source == "vendor")
    stats["with_image"] = sum(1 for l in launches if l.image_uri)
    return launches, dict(stats)


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------------------
# the ambient null
# --------------------------------------------------------------------------------------


def rotate_stream(launches: Sequence[Launch], shift_s: float) -> list[Launch]:
    """Circularly shift launch *identity* against launch *time*.

    The i-th launch keeps its timestamp and takes the symbol/name/uri/deployer of the launch
    that happened ``shift_s`` earlier.

    **What this null does and does not destroy, measured rather than assumed.** Because
    launches arrive at a near-constant ~1090/hour, a contiguous block of *indices* is a
    contiguous block of *time*, so a rotation carries a burst of forty ``READDDDDDDDDD``
    launches to a different hour **intact**. Family counts are therefore almost unchanged by
    it (measured: 210 rotated vs 200 real), and anyone reading that as "the detector finds
    nothing above chance" has misread the null. What rotation *does* destroy is the pairing
    between a burst and the particular host coin it landed on — which makes it the right
    null for "is it the swarm, or merely a coin that had traction at that minute?", and the
    wrong null for "are same-symbol launches temporally clustered at all?".

    Use it together with :func:`shuffle_stream`, never instead of it. PROGRAM.md §3.13: a
    single null is a knob, not a test, and the two must be compared at matched density.
    """
    if not launches:
        return []
    n = len(launches)
    times = [l.t for l in launches]
    # shift by however many positions ``shift_s`` corresponds to at the local rate
    span = times[-1] - times[0]
    if span <= 0:
        return list(launches)
    k = int(round(n * (shift_s % span) / span)) % n
    out: list[Launch] = []
    for i, ln in enumerate(launches):
        donor = launches[(i + k) % n]
        out.append(
            dataclasses.replace(
                ln,
                symbol=donor.symbol,
                name=donor.name,
                uri=donor.uri,
                image_uri=donor.image_uri,
                deployer=donor.deployer,
            )
        )
    return out


def shuffle_stream(launches: Sequence[Launch], seed: int) -> list[Launch]:
    """Permute launch identity across the whole tape, i.i.d.

    The *collision floor*. Every symbol keeps its total frequency over the tape and every
    launch keeps its timestamp; what is destroyed is any tendency for same-symbol launches
    to arrive near each other. ``SOLANA`` still launches twenty-five times, but at twenty-five
    times drawn uniformly from the day's launches, so any family it forms inside a
    sixty-minute window is chance.

    This is the null that answers "is imitation a real temporal phenomenon", and it is the
    one that must be beaten before a swarm is an event at all. Its weakness is the mirror of
    rotation's: it also scatters a *farm's* forty launches, which really were coordinated,
    so it slightly over-deletes. Reporting both brackets the truth, which is the entire
    point of PROGRAM.md §3.13.
    """
    rng = random.Random(seed)
    donors = list(range(len(launches)))
    rng.shuffle(donors)
    out: list[Launch] = []
    for ln, j in zip(launches, donors, strict=True):
        d = launches[j]
        out.append(
            dataclasses.replace(
                ln,
                symbol=d.symbol,
                name=d.name,
                uri=d.uri,
                image_uri=d.image_uri,
                deployer=d.deployer,
            )
        )
    return out


def plant_swarms(
    launches: Sequence[Launch],
    n_swarms: int,
    *,
    clones: int = 3,
    delay_s: float = 120.0,
    seed: int = 1,
    prefix: str = "PLANT",
) -> tuple[list[Launch], dict[str, list[str]]]:
    """Inject synthetic parasite swarms into a real stream. The known-EFFECT world.

    PROGRAM.md §3.12: an estimator that detects nothing passes a false-positive test
    perfectly, so a green zero-control certifies a broken detector exactly as readily as a
    working one. The ambient nulls (:func:`shuffle_stream`, :func:`rotate_stream`) are only
    the zero side; this is the other half.

    ``n_swarms`` real launches are chosen as hosts and ``clones`` synthetic launches are
    appended after each, spaced over ``delay_s``, each copying the host's symbol and name,
    each from a fresh deployer — i.e. textbook parasites. The planted mints are marked with
    ``prefix`` so recovery can be scored exactly, and the returned map is host mint ->
    planted clone mints.

    Note what this can and cannot certify. It measures the detector's **sensitivity** to a
    clean parasite swarm and its ability to nominate the right host. It says nothing about
    whether a real-world swarm looks like this one, which is why it is a control and not a
    validation.
    """
    rng = random.Random(seed)
    if len(launches) < n_swarms * 4 or n_swarms <= 0:
        return list(launches), {}
    # hosts drawn away from the ends so the planted clones land inside the tape
    lo, hi = int(len(launches) * 0.05), int(len(launches) * 0.85)
    host_idx = rng.sample(range(lo, hi), n_swarms)
    planted: dict[str, list[str]] = {}
    extra: list[Launch] = []
    for n, i in enumerate(host_idx):
        host = launches[i]
        mints = []
        for c in range(clones):
            mint = f"{prefix}{n:04d}c{c}"
            mints.append(mint)
            extra.append(
                Launch(
                    mint=mint,
                    symbol=host.symbol,
                    name=host.name,
                    deployer=f"{prefix}DEV{n:04d}{c}",
                    t=host.t + delay_s * (c + 1) / clones,
                    t_source="planted",
                    uri=None,
                    image_uri=None,
                    sol_amount=0.5,
                    initial_buy=1.0,
                    mcap_sol=30.0,
                    t_ingest=host.t,
                    sources=("planted",),
                )
            )
        planted[host.mint] = mints
    out = sorted([*launches, *extra], key=lambda l: (l.t, l.mint))
    return out, planted


# --------------------------------------------------------------------------------------
# census collector
# --------------------------------------------------------------------------------------


def _http_json(url: str, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def census_page(offset: int, limit: int = CENSUS_PAGE) -> list[dict[str, Any]]:
    url = (
        f"{PUMP_API}/coins?offset={offset}&limit={limit}"
        f"&sort=created_timestamp&order=DESC&includeNsfw=true"
    )
    out = _http_json(url)
    return out if isinstance(out, list) else []


def census_once(
    out_path: Path,
    known: set[str],
    max_offset: int = CENSUS_MAX_OFFSET,
    stop_after_known_pages: int = 3,
    pause: float = 0.35,
    verbose: bool = True,
) -> dict[str, Any]:
    """One sweep back through the REST list, appending coins we have never seen.

    Stops early after ``stop_after_known_pages`` consecutive fully-known pages — on the
    steady state that is 2–3 requests, and after a socket outage it walks back to the wall.
    """
    added = 0
    pages = 0
    known_streak = 0
    errors = 0
    t0 = time.time()
    with out_path.open("a") as fh:
        for offset in range(0, max_offset, CENSUS_PAGE):
            try:
                page = census_page(offset)
            except Exception as exc:  # noqa: BLE001 - a poller must record its own failures
                errors += 1
                fh.write(
                    json.dumps(
                        {
                            "kind": "census_error",
                            "t_ingest": _iso(time.time()),
                            "t_event": None,
                            "t_event_source": "absent:local_row_has_no_vendor_clock",
                            "offset": offset,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    + "\n"
                )
                break
            pages += 1
            if not page:
                break
            fresh = 0
            for c in page:
                mint = c.get("mint")
                if not mint or mint in known:
                    continue
                known.add(mint)
                fresh += 1
                added += 1
                fh.write(json.dumps(_census_row(c)) + "\n")
            if fresh == 0:
                known_streak += 1
                if known_streak >= stop_after_known_pages:
                    break
            else:
                known_streak = 0
            time.sleep(pause)
        fh.write(
            json.dumps(
                {
                    "kind": "heartbeat",
                    "t_ingest": _iso(time.time()),
                    "t_event": None,
                    "t_event_source": "absent:local_row_has_no_vendor_clock",
                    "pages": pages,
                    "added": added,
                    "errors": errors,
                    "known_total": len(known),
                    "elapsed_s": round(time.time() - t0, 3),
                }
            )
            + "\n"
        )
    if verbose:
        print(
            f"[census] pages={pages} added={added} errors={errors} "
            f"known={len(known)} in {time.time() - t0:.1f}s",
            file=sys.stderr,
        )
    return {"pages": pages, "added": added, "errors": errors, "known": len(known)}


def _census_row(c: dict[str, Any]) -> dict[str, Any]:
    created = c.get("created_timestamp")
    return {
        "kind": "census_coin",
        "t_ingest": _iso(time.time()),
        # the REST list *does* carry a vendor clock, unlike the PumpPortal frames
        "t_event": _iso(_ms_or_s(created)) if created else None,
        "t_event_source": "vendor:created_timestamp" if created else "absent:no_created_timestamp",
        "mint": c.get("mint"),
        "created_timestamp": created,
        "name": c.get("name"),
        "symbol": c.get("symbol"),
        "creator": c.get("creator"),
        "image_uri": c.get("image_uri"),
        "metadata_uri": c.get("metadata_uri"),
        "description": (c.get("description") or "")[:400],
        "twitter": c.get("twitter"),
        "telegram": c.get("telegram"),
        "website": c.get("website"),
        "complete": c.get("complete"),
        "reply_count": c.get("reply_count"),
        "mcap_sol_at_first_sight": c.get("market_cap"),
        "ath_mcap_sol": c.get("ath_market_cap"),
        "ath_mcap_ts": c.get("ath_market_cap_timestamp"),
        "last_trade_ts": c.get("last_trade_timestamp"),
        "pool_address": c.get("pool_address"),
    }


def load_known(paths: Iterable[Path]) -> set[str]:
    known: set[str] = set()
    for row in read_census(paths):
        if row.get("mint"):
            known.add(row["mint"])
    return known


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _default_paths(tag: str, days: int = 3) -> list[Path]:
    today = dt.datetime.now(dt.timezone.utc).date()
    return [
        (FIREHOSE_NEW_TOKEN if tag == "new_token" else FIREHOSE_LEDGER)
        / f"{today - dt.timedelta(days=d)}.jsonl"
        for d in range(days)
    ]


def _census_paths(days: int = 3) -> list[Path]:
    today = dt.datetime.now(dt.timezone.utc).date()
    return [SWARMS / f"census-{today - dt.timedelta(days=d)}.jsonl" for d in range(days)]


def cmd_census(args: argparse.Namespace) -> int:
    SWARMS.mkdir(parents=True, exist_ok=True)
    known = load_known(_census_paths(days=7))
    print(f"[census] resuming with {len(known)} known mints", file=sys.stderr)
    while True:
        today = dt.datetime.now(dt.timezone.utc).date()
        census_once(SWARMS / f"census-{today}.jsonl", known)
        if not args.loop:
            return 0
        time.sleep(args.interval)


def cmd_replay(args: argparse.Namespace) -> int:
    SWARMS.mkdir(parents=True, exist_ok=True)
    fh_paths = [Path(p) for p in args.firehose] if args.firehose else _default_paths("new_token", args.days)
    led_paths = [Path(p) for p in args.ledger] if args.ledger else _default_paths("ledger", args.days)
    cen_paths = [Path(p) for p in args.census] if args.census else _census_paths(args.days)

    intervals = listening_intervals(led_paths) if not args.no_restrict else None
    launches, stats = build_stream(fh_paths, cen_paths, intervals)
    if args.rotate:
        launches = rotate_stream(launches, args.rotate)

    det = SwarmDetector(window_s=args.window, k=args.k, name_threshold=args.name_threshold)
    onsets: list[dict[str, Any]] = []
    for ln in launches:
        onsets.extend(det.push(ln))

    tag = f".{args.out_tag}" if args.out_tag else ""
    ev_path = SWARMS / f"events{tag}.jsonl"
    fam_path = SWARMS / f"families{tag}.jsonl"
    with ev_path.open("w") as fh:
        for row in onsets:
            fh.write(json.dumps(row) + "\n")
    with fam_path.open("w") as fh:
        for row in det.family_rows():
            fh.write(json.dumps(row) + "\n")

    if args.report:
        _report(launches, onsets, det, stats, intervals)
    print(json.dumps({"onsets": len(onsets), "events": str(ev_path), "families": str(fam_path), **stats}))
    return 0


def _report(
    launches: Sequence[Launch],
    onsets: Sequence[dict[str, Any]],
    det: SwarmDetector,
    stats: dict[str, Any],
    intervals: Sequence[tuple[float, float]] | None,
) -> None:
    out = sys.stderr
    print("\n=== stream ===", file=out)
    for k, v in sorted(stats.items()):
        print(f"  {k:20s} {v}", file=out)
    if intervals:
        cover = sum(b - a for a, b in intervals) / 3600
        print(f"  listening_hours      {cover:.2f} over {len(intervals)} windows", file=out)
    if launches:
        span = (launches[-1].t - launches[0].t) / 3600
        print(f"  span_hours           {span:.2f}   rate={len(launches)/max(span,1e-9):.0f}/h", file=out)
    fams = [f for f in det.families() if len(f.members) >= 2]
    print(f"\n=== families (size>=2): {len(fams)} ===", file=out)
    tax = Counter(
        taxonomy(len(f.members) - 1, Counter(m.deployer for m in f.members[1:]), f.members[0].deployer)
        for f in fams
    )
    print(f"  taxonomy: {dict(tax)}", file=out)
    print(f"\n=== onsets (k>={det.k}): {len(onsets)} ===", file=out)
    tax_o = Counter(o["taxonomy"] for o in onsets)
    print(f"  taxonomy: {dict(tax_o)}", file=out)
    if onsets:
        lags = sorted(o["lag_from_host_s"] for o in onsets)
        q = lambda p: lags[min(len(lags) - 1, int(p * len(lags)))]  # noqa: E731
        print(
            f"  lag from host launch (s): p10={q(.1):.0f} p50={q(.5):.0f} p90={q(.9):.0f}",
            file=out,
        )
    sizes = Counter(len(f.members) for f in fams)
    print(f"  final size histogram: {dict(sorted(sizes.items()))}", file=out)
    print("\n  largest families (final size, not onset size):", file=out)
    for f in sorted(fams, key=lambda f: -len(f.members))[:15]:
        dep = Counter(m.deployer for m in f.members[1:])
        print(
            f"    {f.members[0].symbol[:18]:18s} n={len(f.members):3d} "
            f"clone_devs={len(dep):3d} {taxonomy(len(f.members)-1, dep, f.members[0].deployer):9s} "
            f"{dict(f.kinds)}",
            file=out,
        )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("census", help="poll the pump.fun REST list; gap-fill and enrich")
    c.add_argument("--loop", action="store_true")
    c.add_argument("--interval", type=float, default=300.0)
    c.set_defaults(fn=cmd_census)

    r = sub.add_parser("replay", help="deterministic offline detection over the tapes")
    r.add_argument("--firehose", nargs="*", default=None)
    r.add_argument("--ledger", nargs="*", default=None)
    r.add_argument("--census", nargs="*", default=None)
    r.add_argument("--days", type=int, default=3)
    r.add_argument("--window", type=float, default=3600.0)
    r.add_argument("--k", type=int, default=3)
    r.add_argument("--name-threshold", type=float, default=0.82)
    r.add_argument("--rotate", type=float, default=0.0, help="ambient-null rotation, seconds")
    r.add_argument("--out-tag", default="")
    r.add_argument("--no-restrict", action="store_true", help="ignore the ledger's listening windows")
    r.add_argument("--report", action="store_true")
    r.set_defaults(fn=cmd_replay)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
