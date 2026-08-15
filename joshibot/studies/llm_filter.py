#!/usr/bin/env python3
"""Is an LLM *glance* worth more than five numeric comparisons?

The operator's original strategy was to click every coin in the callout feed and
look at it for a few seconds — a human judgement over the name, the image, the
chart shape, the vibe. The mechanical filter (`shitcoims_scalper.policy`) is five
numeric comparisons and has access to none of that. This study asks whether an
LLM's glance carries information the numbers do not.

WHAT IS BEING COMPARED, precisely. Board entry gives ~35k timestamped attention
shocks over one 10 h tape (`studies/board_entry.py`). The incumbent selector is
drawdown-at-entry: split at 50% off ATH and the shallow side outperforms. The LLM
is handed the *same numerics* plus the qualitative fields the mechanical filter
cannot read — symbol, name, description, image URI, socials, reply count — and
must beat that split on the same cohort, at the same horizon, with the same
censoring treatment.

THREE THINGS THIS DESIGN REFUSES TO LET THE LLM GET AWAY WITH:

1. **A deterministic verdict is useless downstream.** A yes/no at propensity 1.0
   cannot be scored off-policy against any alternative, so every decision here is
   sampled from a distribution built out of the model's own stated confidence and
   wrapped in the same epsilon flip `shitcoims_scalper.policy` uses. The action
   actually taken is logged with the probability that produced it, in a real
   `shitcoims_tape.schema.PropensityRecord`.

2. **A content-free control.** The same cohort is screened a second time with
   every identifying field stripped — numbers only. If the blind arm scores as
   well as the sighted one, the model is reading the numbers we handed it and the
   "vibe" is a story we told ourselves.

3. **A shuffled-label null.** The verdicts are held fixed and the outcomes are
   permuted across the cohort, thousands of times, to get the null distribution of
   the very statistic being reported. Any gap smaller than that distribution's
   tail is noise with a narrative attached.

LEAKAGE CONTROL, because half the qualitative fields are fetched live TODAY and
the tape is from the PAST. Only *immutable* creation-time metadata is taken from
the live API — name, description, image URI, socials, creator, nsfw flag. Every
number that moves (market cap, ATH, reply count, completion, last trade) is read
from the tape snapshot at the entry timestamp. A live `usd_market_cap` in the
prompt would be a direct read of the answer.

CENSORING, inherited from `studies/board_entry.py` and not re-litigated here: a
coin is observed only while it sits on a board, so an 8 h forward return exists
only for coins that survived 8 h in view. Both arms and the baseline are scored on
that same survivor cohort, so the comparison is fair even though the level is
biased up. The bias cancels in the contrast; it does not cancel in the level.

Usage:
    python studies/llm_filter.py --stage cohort     # tape -> cohort
    python studies/llm_filter.py --stage meta       # + immutable metadata
    python studies/llm_filter.py --stage screen --arm full --backend grok
    python studies/llm_filter.py --stage screen --arm blind --backend grok
    python studies/llm_filter.py --stage score
    python studies/llm_filter.py --stage selftest   # anti-mirror gate, no spend
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import random
import re
import shutil
import statistics as st
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, Sequence

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from studies.board_entry import (  # noqa: E402
    HORIZONS_S, build_price_series, forward_returns, load,
)

CACHE = REPO / ".cache" / "llm_filter"
TAPE_GLOB = str(REPO / "state" / "boards" / "*.jsonl")

POLICY_ID_FULL = "llm-glance-full-v1"
POLICY_ID_BLIND = "llm-glance-blind-v1"

# The horizon the incumbent baseline was published at (studies/RESULT_board_entry.md).
PRIMARY_HORIZON = 28800
# The incumbent's knob. Reported with every number it produces, per PROGRAM.md §3.7.
DRAWDOWN_CUT = 0.50
# Epsilon flip, matching shitcoims_scalper.policy.ScalperPolicy's default.
EXPLORE_EPS = 0.05

PUMP_API = "https://frontend-api-v3.pump.fun"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Fetched live, so ONLY fields that cannot have changed since the tape was cut.
# Anything that moves is read from the tape snapshot instead. See module docstring.
IMMUTABLE_META_FIELDS = (
    "name",
    "description",
    "image_uri",
    "twitter",
    "telegram",
    "website",
    "creator",
    "nsfw",
    "show_name",
    "created_timestamp",
)

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["buy", "skip"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "confidence", "reason"],
}

# The second framing, added after the first one came back DEGENERATE: asked for a
# buy/skip verdict, the model skipped 100% of 189 coins. A filter that selects
# nothing has no contrast to score and no propensity worth logging — it is an off
# switch, not a filter. Asking instead for a calibrated probability keeps the
# model's ranking even when its level is uniformly bearish, which is the quantity
# a selection filter actually needs. Both framings are kept and both are reported.
PROB_SCHEMA = {
    "type": "object",
    "properties": {
        "p_up": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string"},
    },
    "required": ["p_up", "reason"],
}

PROB_ARMS = ("probfull", "probblind")
# The batch arms ask the same probability question with N coins in one call. They
# exist because batching is the ONLY lever that moves the throughput ceiling by an
# order of magnitude, and a lever that changes the answer is not a free one — so
# they are scored as arms, against the same outcomes, not just timed.
BATCH_ARMS = ("batchfull", "batchblind", "tastefull", "tastepick", "colourfull")
ALL_ARMS = ("full", "blind", "probfull", "probblind", "batchfull", "batchblind",
            "tastefull", "tastepick", "colourfull")

# THE COLOUR ARM — the operator's idea, and the only elicitation here that does not
# impose a scale at all.
#
# Every other arm hands the model an axis we invented (probability of up, 0-100
# conviction, buy/skip) and then measures along it. If the model's judgement does
# not decompose onto our axis, that failure is indistinguishable from having no
# judgement. A palette has no axis: the labels are arbitrary, unordered, and carry
# no instruction about what "good" means.
#
# So we never order them. The test asks only whether the model's own partition of
# the coins separates the outcomes AT ALL -- a rank-based between-group statistic
# with a shuffled-label null. If some colour reliably lands on coins that run, that
# is the vibe channel showing up without us having named it. If the partition is
# outcome-independent, no scale we chose was ever the problem.
PALETTE = ("crimson", "amber", "gold", "emerald", "teal", "azure",
           "indigo", "violet", "magenta", "slate")

COLOUR_RULES = (
    "You are looking at {n} Solana memecoins that just hit a pump.fun trending board. "
    "Do not analyse them and do not rate them. Just tell me what COLOUR each one is.\n\n"
    "Use only these words: " + ", ".join(PALETTE) + ".\n\n"
    "There is no right answer and no scale -- these colours are not ranked and none of "
    "them means good or bad. Go on feel: the name, the joke, the description, the shape "
    "it is in. Give the most vivid colour you actually sense in each coin, and use the "
    "whole palette rather than defaulting to a couple of them.\n\n"
    "Reply with one line per coin and nothing else, in this exact form:\n"
    "0 crimson\n1 slate\n2 gold\n"
)


def parse_colours(text: str) -> dict[int, str]:
    """`12 azure` per line. Anything else is ignored rather than guessed at."""
    out: dict[int, str] = {}
    for line in text.splitlines():
        m = re.match(r"\s*\[?(\d+)\]?[\s:.\-]+([a-zA-Z]+)\s*$", line.strip())
        if m and m.group(2).lower() in PALETTE:
            out[int(m.group(1))] = m.group(2).lower()
    return out


def kruskal_between(groups: Sequence[Sequence[float]]) -> float:
    """Between-group spread of MEAN RANKS. Larger = the partition separates outcomes.

    Rank-based so the heavy return tail cannot manufacture it, and deliberately
    unnormalised -- it is only ever compared against its own permutation null, so
    the constant does not matter and a chi-square approximation is not needed.
    """
    allv = sorted(v for g in groups for v in g)
    rk = {}
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1] == allv[i]:
            j += 1
        rk[allv[i]] = (i + j) / 2.0 + 1.0
        i = j + 1
    n = len(allv)
    if n < 2:
        return 0.0
    grand = (n + 1) / 2.0
    return sum(len(g) * ((sum(rk[v] for v in g) / len(g)) - grand) ** 2
               for g in groups if g) / n

# THE PROMPT WAS PART OF THE EXPERIMENT AND THE FIRST VERSION WAS BAD.
# Two defects, both ours, both plausible causes of the degenerate verdict:
#   1. PROB_RULES/SYSTEM_RULES tell the model "Most of these coins go to zero"
#      before asking it to judge. That is priming the answer, not eliciting it.
#   2. Every arm ran at --reasoning-effort low with a bare-number schema, so the
#      model had no room to look at anything before committing to a figure.
# "Will this run" is a taste judgement, and we asked for it in a form that admits
# no taste. This arm removes the prior, raises the effort, gives the model a
# free-text `take` field to think in before it scores, and asks for an integer
# 0-100 rank rather than a probability -- a scale people actually have taste on.
# It is batched, because batching is what produced spread in the first place and
# is cheap enough that testing our own prompt is not a budget decision.
TASTE_RULES = (
    "You are a degen memecoin trader with good instincts and real money on the line. "
    "You are looking at coins that just hit a pump.fun trending board. You know what a "
    "coin that is about to run looks like and what a dead one looks like -- the name, "
    "the joke, whether the description sounds like a person or a template, whether "
    "anyone is talking, where it is in its own move. Trust that. "
    "For each coin give a `take` (a short, blunt, honest read -- what you actually "
    "notice) and a `score` from 0 to 100: how much you would want to be long it for the "
    "next eight hours, where 0 is 'this is over' and 100 is 'I am buying this right now'. "
    "SPREAD YOUR SCORES. Rank them against each other. If you give everything the same "
    "number you have told me nothing. Some of these will run and some will not; your job "
    "is to tell them apart, not to tell me memecoins are risky. "
    "Answer with strict JSON only: a `verdicts` array of {id, score, take}, every id present."
)

# THE PICK ARM — the operator's design, and the closest thing here to the actual
# human behaviour being modelled. Every arm above forces a judgement on EVERY coin:
# a probability, a score, a verdict. That is not what clicking through a callout
# feed is. The human looks at fifty things and picks three, and says nothing at all
# about the other forty-seven.
#
# Three defects it fixes at once:
#   * No forced opinion. Silence is a legitimate answer, so a coin the model has
#     nothing to say about no longer drags a manufactured 0.31 into the ranking.
#   * No output schema. Constrained decoding is dropped entirely -- the model
#     writes prose and we parse one line out of it. If overconstraining was what
#     flattened the earlier arms, this is where that shows.
#   * Omission stops being an error and becomes the SIGNAL. The batch arms had to
#     treat a missing id as a bug; here not-mentioned means not-picked, which is a
#     complete and well-defined selector with no missingness at all.
#
# The selection RATE is then the model's own choice and is itself a result: a
# screen that picks 45 of 50 is not screening, and one that picks 0 is the off
# switch again.
PICK_RULES = (
    "You are a degen memecoin trader with good instincts and real money on the line. "
    "Below are {n} coins that just hit a pump.fun trending board. You know what a coin "
    "that is about to run looks like and what a dead one looks like -- the name, the "
    "joke, whether the description sounds like a person or a template, whether anyone "
    "is talking, where it is in its own move. Trust that.\n\n"
    "Tell me which ones you would ACTUALLY BUY and hold for the next eight hours. "
    "Pick as many or as few as you genuinely mean -- three, ten, one, none. Do not pick "
    "something to fill a quota and do not pass on everything to be safe.\n\n"
    "Start your reply with exactly one line in this form and nothing else on it:\n"
    "PICKS: 3, 17, 42\n"
    "(or `PICKS: none`). After that line, say whatever you want about why."
)


def parse_picks(text: str, n: int) -> set[int] | None:
    """Pull the ids out of a free-form reply. None means the reply was unusable.

    Deliberately strict: the PICKS line or nothing. Scavenging stray integers out
    of the prose would silently invent selections out of a model that was chatting,
    and a selector built from a parser's guesses is not a selector.
    """
    # Anywhere in the reply, not just at a line start: the harness concatenates its
    # thinking with the answer, so the marker legitimately lands mid-line
    # ("...a live catalyst.PICKS: none"). Requiring column zero read that as a
    # parse failure and threw away a real verdict.
    m = re.search(r"PICKS\s*:\s*([^\n]*)", text, re.I)
    if not m:
        return None
    body = m.group(1).strip()
    if not body or re.match(r"none\b", body, re.I):
        return set()   # an empty selection is an ANSWER, not a failure
    got = {int(x) for x in re.findall(r"\d+", body)}
    return {i for i in got if 0 <= i < n}


TASTE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "take": {"type": "string"},
                },
                "required": ["id", "score", "take"],
            },
        }
    },
    "required": ["verdicts"],
}


def base_arm(arm: str) -> str:
    """Which FEATURE SET an arm sees: 'full' (with content) or 'blind' (numbers only).

    Only the ask differs between framings; the prompt body is shared. This was
    briefly wrong and it mattered: the taste and colour arms fell through to their
    own names, so they rendered the BLIND body and were asked for a vibe judgement
    on a table of numbers with no name, description or image in it. The model said
    so in its reply ("the board feed only has metrics") — which is the only reason
    it was caught.
    """
    for pre in ("prob", "batch", "taste", "colour"):
        if arm.startswith(pre):
            rest = arm[len(pre):]
            return "blind" if rest == "blind" else "full"
    return arm


# --------------------------------------------------------------------------
# Cohort construction
# --------------------------------------------------------------------------


def build_cohort(horizon: int = PRIMARY_HORIZON) -> list[dict[str, Any]]:
    """The 8 h-evaluable, entity-deduplicated board-entry population.

    THE SAMPLING RULE, stated once and applied without exception:

      1. `kind == board_entry` with a usable market cap at t0 and a known
         `drawdown_from_ath` (the baseline needs the conditioning variable).
      2. A forward return at the primary horizon that is OBSERVED, not censored.
         `board_entry.value_at` decides this; we do not reimplement it.
      3. **One row per mint** — the earliest entry. PROGRAM.md §3.2. This is not a
         nicety: the same coin re-enters the boards dozens of times in ten hours,
         and counting each as an independent observation is what inflates the
         published baseline (see RESULT).
      4. Everything that survives 1-3 is screened. No subsampling, no
         stratification, no class balancing — §3.3. The population is small enough
         that a sample would only add variance.
    """
    # board_entry.py is a SHARED file another lane also edits, and its HORIZONS_S
    # is what decides which forward returns get computed at all. If it stops
    # covering our horizon we would silently build an empty cohort and report a
    # study on nothing; fail here instead, where the cause is legible.
    if horizon not in HORIZONS_S:
        raise SystemExit(
            f"studies/board_entry.py HORIZONS_S is {HORIZONS_S} and does not include "
            f"{horizon}s, so no return at that horizon is computed. Add it there, or "
            f"pass a --horizon that is in the list.")
    rows = load(TAPE_GLOB)
    entries = [r for r in rows if r.get("kind") == "board_entry"]
    series = build_price_series(rows)
    recs = forward_returns(entries, series)

    by_key = {(e["mint"], e["t_ingest"]): e for e in entries}
    key = f"r{horizon}"

    seen: set[str] = set()
    cohort: list[dict[str, Any]] = []
    for rec in sorted(recs, key=lambda r: r["t"]):
        if rec.get(key) is None or rec["drawdown"] < 0:
            continue
        if rec["mint"] in seen:
            continue
        raw = by_key.get((rec["mint"], rec["t"]))
        if raw is None:
            continue
        seen.add(rec["mint"])
        cohort.append(
            {
                "mint": rec["mint"],
                "board": rec["board"],
                "t0": rec["t"],
                "rank": rec.get("rank"),
                "mc0_usd": rec["mc0"],
                "drawdown": rec["drawdown"],
                # Snapshot numerics, read at t0 from the tape. Never from the live API.
                "symbol": raw.get("symbol"),
                "reply_count": raw.get("reply_count"),
                "is_currently_live": raw.get("is_currently_live"),
                "complete": raw.get("complete"),
                "ath_market_cap": raw.get("ath_market_cap"),
                "age_s": _age_s(raw),
                "trade_recency_s": _recency_s(raw),
                "sol_in_curve": (raw.get("virtual_sol_reserves") or 0) / 1e9,
                "returns": {f"r{h}": rec.get(f"r{h}") for h in (300, 1800, 3600, 7200, 14400, 21600, 28800)},
            }
        )
    return cohort


def _unix(v: Any) -> float | None:
    """pump.fun mixes seconds and milliseconds in the same field across endpoints."""
    if not v:
        return None
    x = float(v)
    return x / 1000.0 if x > 1e11 else x


def _age_s(raw: dict[str, Any]) -> float | None:
    c = _unix(raw.get("created_unix"))
    return None if c is None else raw["t_ingest"] - c


def _recency_s(raw: dict[str, Any]) -> float | None:
    lt = _unix(raw.get("last_trade_unix"))
    return None if lt is None else raw["t_ingest"] - lt


# --------------------------------------------------------------------------
# Immutable metadata
# --------------------------------------------------------------------------


def fetch_meta(mints: Sequence[str], workers: int = 4) -> dict[str, dict[str, Any]]:
    def one(m: str) -> tuple[str, dict[str, Any]]:
        req = urllib.request.Request(
            f"{PUMP_API}/coins/{m}", headers={"User-Agent": UA, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                d = json.load(resp)
        except (urllib.error.URLError, OSError, ValueError) as e:
            return m, {"_error": str(e)[:200]}
        return m, {k: d.get(k) for k in IMMUTABLE_META_FIELDS}

    out: dict[str, dict[str, Any]] = {}
    with cf.ThreadPoolExecutor(workers) as ex:
        for m, d in ex.map(one, mints):
            out[m] = d
    return out


# --------------------------------------------------------------------------
# Prompt construction — the two arms
# --------------------------------------------------------------------------

SYSTEM_RULES = (
    "You are screening brand-new Solana memecoins on pump.fun for a very short "
    "scalp. You will see one coin. Decide whether a trader looking for a coin that "
    "will be worth MORE in eight hours should buy it now. Most of these coins go to "
    "zero. Answer with strict JSON only: verdict (buy|skip), confidence in [0,1] "
    "for how sure you are of that verdict, and a one-sentence reason."
)

# Deliberately anchored on the observed base rate. Without the anchor the model
# answers the question it wants to answer ("is this a good coin") rather than the
# one that can be scored ("rank this against the others"), and returns the same
# pessimistic number every time.
PROB_RULES = (
    "You are screening Solana memecoins on pump.fun. You will see one coin as it "
    "appears on a trending board. Estimate the probability that its market cap is "
    "HIGHER eight hours from now than it is right now. Roughly half of the coins in "
    "this population are higher after eight hours, so calibrate against 0.5 and use "
    "the FULL range — 0.05 for a coin you are confident dies, 0.95 for one you are "
    "confident keeps running, and spread the ones in between. Do not return the same "
    "number for every coin. Answer with strict JSON only: p_up in [0,1] and a "
    "one-sentence reason."
)


def _fmt_num(x: Any, unit: str = "", nd: int = 0) -> str:
    if x is None:
        return "unknown"
    return f"{float(x):,.{nd}f}{unit}"


def render_prompt(row: dict[str, Any], meta: dict[str, Any], arm: str) -> str:
    """FULL sees everything; BLIND sees only what the mechanical filter could see.

    The blind arm is the content-free control. It is not a weaker prompt — it is
    the SAME prompt with every identifying string removed, so a score difference
    between arms is attributable to the qualitative content and nothing else.
    """
    rules = PROB_RULES if arm in PROB_ARMS else SYSTEM_RULES
    arm = base_arm(arm)
    n = []
    n.append(f"- age since launch: {_fmt_num(row['age_s'], ' s')}")
    n.append(f"- seconds since last trade: {_fmt_num(row['trade_recency_s'], ' s')}")
    n.append(f"- market cap now: ${_fmt_num(row['mc0_usd'])}")
    n.append(f"- all-time-high market cap: ${_fmt_num(row.get('ath_market_cap'))}")
    n.append(f"- drawdown from ATH: {row['drawdown'] * 100:.1f}%")
    n.append(f"- SOL in the bonding curve: {_fmt_num(row['sol_in_curve'], ' SOL', 2)}")
    n.append(f"- reply count: {_fmt_num(row.get('reply_count'))}")
    n.append(f"- currently livestreaming: {bool(row.get('is_currently_live'))}")
    n.append(f"- bonding curve complete (graduated): {bool(row.get('complete'))}")
    n.append(f"- just entered the '{row['board']}' board at rank {row.get('rank')}")

    if arm == "blind":
        head = (
            "A coin just appeared on a pump.fun trending board. Its name, symbol, "
            "description and images are WITHHELD from you. You have only these numbers:"
        )
        return f"{rules}\n\n{head}\n" + "\n".join(n) + "\n\nJSON only."

    q = []
    q.append(f"- symbol: {row.get('symbol')!r}")
    q.append(f"- name: {meta.get('name')!r}")
    desc = (meta.get("description") or "").strip().replace("\r", " ").replace("\n", " ")
    q.append(f"- description: {desc[:600]!r}" if desc else "- description: (empty)")
    q.append(f"- image: {meta.get('image_uri') or '(none)'}")
    q.append(f"- twitter: {meta.get('twitter') or '(none)'}")
    q.append(f"- telegram: {meta.get('telegram') or '(none)'}")
    q.append(f"- website: {meta.get('website') or '(none)'}")
    q.append(f"- flagged nsfw: {bool(meta.get('nsfw'))}")

    head = "A coin just appeared on a pump.fun trending board.\n\nWhat it is:"
    return (
        f"{rules}\n\n{head}\n"
        + "\n".join(q)
        + "\n\nWhere it stands:\n"
        + "\n".join(n)
        + "\n\nJSON only."
    )


# --------------------------------------------------------------------------
# Backends — a pluggable judge, so the harness is testable without spend
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Judgement:
    """One model answer, normalised across the two framings.

    ``signal`` is the single number everything downstream ranks on: the model's
    preference for entering, in [0,1]. For the verdict framing it is built from
    the stated confidence (a `buy` at 0.9 outranks a `buy` at 0.6 outranks a
    `skip`); for the probability framing it is the stated probability itself.
    Collapsing both to one scale is what lets the two be scored by the same
    estimator without a second code path to get wrong.
    """

    verdict: str
    confidence: float
    signal: float
    reason: str
    latency_s: float
    cost_usd: float
    input_tokens: int
    output_tokens: int
    backend: str
    p_up: float | None = None
    error: str | None = None


def signal_from_verdict(verdict: str, confidence: float) -> float:
    c = max(0.0, min(1.0, confidence))
    return 0.5 + 0.5 * c if verdict == "buy" else 0.5 - 0.5 * c


class Backend(Protocol):
    name: str

    def judge(self, prompt: str, arm: str = "full") -> Judgement: ...


class StubBackend:
    """Deterministic pseudo-judge. Exercises every code path with zero spend.

    Its verdict is a hash of the prompt, so it is reproducible and carries NO
    information about the outcome — which makes a stub run a useful smoke test of
    the scoring code: it must report no edge.
    """

    name = "stub"

    def __init__(self, latency_s: float = 0.0) -> None:
        self.latency_s = latency_s

    def judge(self, prompt: str, arm: str = "full") -> Judgement:
        if self.latency_s:
            time.sleep(self.latency_s)
        h = hashlib.sha256(prompt.encode()).digest()
        if arm in PROB_ARMS:
            p = 0.05 + (h[0] % 90) / 100.0
            return Judgement("buy" if p >= 0.5 else "skip", abs(p - 0.5) * 2, p, "stub",
                             self.latency_s, 0.0, 0, 0, self.name, p_up=p)
        verdict = "buy" if h[0] % 2 == 0 else "skip"
        conf = 0.5 + (h[1] % 50) / 100.0
        return Judgement(verdict, conf, signal_from_verdict(verdict, conf), "stub",
                         self.latency_s, 0.0, 0, 0, self.name)


class GrokCLIBackend:
    """The xAI `grok` CLI in headless single-turn mode.

    This is an AGENT harness, not a completion endpoint, and the shape of that
    shows up in the measurements: a fixed ~17k-token system preamble rides on
    every call whatever the prompt says, and process startup plus session setup
    dominates a short judgement. Both are reported rather than optimised away,
    because they are what the throughput ceiling is actually made of.

    Tools are stripped and `--verbatim` prevents the harness from rewriting the
    prompt; `--cwd` points somewhere neutral so the agent never picks up this
    repo's AGENTS.md/CLAUDE.md and starts reasoning about joshibot.
    """

    name = "grok"

    _DISALLOWED = (
        "Bash,Read,Write,Edit,MultiEdit,NotebookEdit,WebSearch,WebFetch,Task,"
        "Glob,Grep,TodoWrite,BashOutput,KillShell,SlashCommand,Skill,ExitPlanMode"
    )

    def __init__(self, *, binary: str | None = None, model: str | None = None,
                 effort: str = "low", cwd: str | None = None, timeout_s: float = 900.0) -> None:
        self.binary = binary or shutil.which("grok") or str(Path.home() / ".grok" / "bin" / "grok")
        self.model = model
        self.effort = effort
        self.timeout_s = timeout_s
        # An EMPTY directory, and deliberately not inside .cache/llm_filter: grok is
        # an agent and it will look around. Pointed at the cache it announced it was
        # going to read "prior decision logs and a cohort file" — i.e. this study's
        # own answers — which would have contaminated the arm silently if the reply
        # had happened to parse.
        self.cwd = cwd or str(Path(tempfile.gettempdir()) / "llm_filter_grokhome")
        Path(self.cwd).mkdir(parents=True, exist_ok=True)

    def judge(self, prompt: str, arm: str = "full") -> Judgement:
        prob = arm in PROB_ARMS
        cmd = [
            self.binary, "-p", prompt,
            "--output-format", "json",
            "--json-schema", json.dumps(PROB_SCHEMA if prob else VERDICT_SCHEMA),
            "--reasoning-effort", self.effort,
            "--no-memory", "--verbatim",
            "--cwd", self.cwd,
            "--disallowed-tools", self._DISALLOWED,
        ]
        if self.model:
            cmd += ["-m", self.model]

        def fail(msg: str, dt: float, cost: float = 0.0) -> Judgement:
            return Judgement("skip", 0.0, 0.5, "", dt, cost, 0, 0, self.name, error=msg)

        t0 = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            return fail("timeout", time.monotonic() - t0)
        dt = time.monotonic() - t0
        if proc.returncode != 0:
            return fail(f"rc={proc.returncode}: {proc.stderr[-300:]}", dt)
        try:
            d = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return fail(f"unparseable: {proc.stdout[-300:]}", dt)
        so = d.get("structuredOutput")
        if not isinstance(so, dict):
            # The CLI occasionally returns the JSON as text without honouring the schema.
            so = _salvage_json(d.get("text") or "")
        cost = float(d.get("total_cost_usd") or 0.0)
        u = d.get("usage") or {}
        tin, tout = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
        if not isinstance(so, dict):
            return fail("no structured output", dt, cost)

        if prob:
            try:
                p = max(0.0, min(1.0, float(so["p_up"])))
            except (KeyError, TypeError, ValueError):
                return fail("no p_up", dt, cost)
            return Judgement("buy" if p >= 0.5 else "skip", abs(p - 0.5) * 2, p,
                             str(so.get("reason", ""))[:400], dt, cost, tin, tout,
                             self.name, p_up=p)
        if so.get("verdict") not in ("buy", "skip"):
            return fail("no verdict", dt, cost)
        conf = max(0.0, min(1.0, float(so.get("confidence", 0.5))))
        return Judgement(so["verdict"], conf, signal_from_verdict(so["verdict"], conf),
                         str(so.get("reason", ""))[:400], dt, cost, tin, tout, self.name)


BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "p_up": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["id", "p_up"],
            },
        }
    },
    "required": ["verdicts"],
}


def render_batch_prompt(rows: Sequence[dict[str, Any]],
                        meta: dict[str, dict[str, Any]], arm: str) -> str:
    """N coins in one call. The reason to want this, and the reason to distrust it.

    WANT: the CLI bills a ~15k-token system preamble on every invocation whatever
    the prompt says, so at batch 1 the overhead IS the cost. Amortising it over 25
    coins is the only lever that moves the throughput ceiling by an order of
    magnitude, and the ceiling is what decides whether this can run at all.

    DISTRUST: it changes the task. Judged alone, a coin is scored against the
    model's prior; judged in a list of 25, it is scored against its neighbours,
    and the neighbours are an accident of batching. The scores also stop being
    independent — one confident opinion at the top of the list can anchor the
    rest. `--stage batch` therefore measures BOTH the speedup and the rank
    agreement with the single-call answers on the same coins, because a batched
    number that disagrees with the unbatched one is cheaper at doing something else.
    """
    body = []
    for i, row in enumerate(rows):
        m = meta.get(row["mint"], {})
        bits = [f"age {_fmt_num(row['age_s'], 's')}",
                f"last trade {_fmt_num(row['trade_recency_s'], 's')} ago",
                f"mcap ${_fmt_num(row['mc0_usd'])}",
                f"{row['drawdown'] * 100:.0f}% off ATH",
                f"{_fmt_num(row['sol_in_curve'], ' SOL', 1)} in curve",
                f"{_fmt_num(row.get('reply_count'))} replies",
                f"live={bool(row.get('is_currently_live'))}",
                f"graduated={bool(row.get('complete'))}",
                f"board={row['board']}#{row.get('rank')}"]
        if base_arm(arm) == "full":
            desc = (m.get("description") or "").strip().replace("\n", " ")[:200]
            bits = [f"symbol {row.get('symbol')!r}", f"name {m.get('name')!r}",
                    f"desc {desc!r}", f"image={'yes' if m.get('image_uri') else 'no'}",
                    f"socials={'yes' if (m.get('twitter') or m.get('telegram')) else 'no'}"] + bits
        body.append(f"[{i}] " + ", ".join(bits))
    if arm == "colourfull":
        return (COLOUR_RULES.format(n=len(rows)) + "\n\n" + "\n".join(body))
    if arm == "tastepick":
        return (PICK_RULES.format(n=len(rows)) + "\n\n" + "\n".join(body))
    if arm == "tastefull":
        return (TASTE_RULES + f"\n\nHere are {len(rows)} coins.\n\n"
                + "\n".join(body) + "\n\nJSON only.")
    return (PROB_RULES.replace("You will see one coin as it appears on a trending board.",
                               f"You will see {len(rows)} coins, each with an id.")
            .replace("Answer with strict JSON only: p_up in [0,1] and a one-sentence reason.",
                     "Answer with strict JSON only: a `verdicts` array with one {id, p_up} "
                     "per coin, every id present, no reasons.")
            + "\n\n" + "\n".join(body) + "\n\nJSON only.")


def grok_batch(be: "GrokCLIBackend", prompt: str,
               arm: str = "batchfull") -> tuple[dict[int, float], Judgement]:
    """One call, many verdicts. Returns {id: signal in [0,1]} plus cost/latency."""
    taste = arm == "tastefull"
    pick = arm == "tastepick"
    colour = arm == "colourfull"
    cmd = [be.binary, "-p", prompt, "--output-format", "json",
           "--reasoning-effort", ("high" if (taste or pick) else be.effort),
           # ONE turn. Without the schema the harness is free to act like an agent
           # instead of answering, and it did: it narrated a plan to go read files
           # and never emitted a verdict.
           "--max-turns", "1", "--no-memory", "--verbatim",]
    if not (pick or colour):   # these arms run UNCONSTRAINED: no schema, prose out
        cmd += ["--json-schema", json.dumps(TASTE_SCHEMA if taste else BATCH_SCHEMA)]
    cmd += [
           "--cwd", be.cwd, "--disallowed-tools", be._DISALLOWED]
    if be.model:
        cmd += ["-m", be.model]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=be.timeout_s)
    except subprocess.TimeoutExpired:
        return {}, Judgement("skip", 0.0, 0.5, "", time.monotonic() - t0, 0.0, 0, 0,
                             be.name, error="timeout")
    dt = time.monotonic() - t0
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}, Judgement("skip", 0.0, 0.5, "", dt, 0.0, 0, 0, be.name,
                             error=f"unparseable: {proc.stdout[-200:]}")
    u = d.get("usage") or {}
    j = Judgement("skip", 0.0, 0.5, "", dt, float(d.get("total_cost_usd") or 0.0),
                  int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0), be.name)
    out: dict[int, float] = {}
    if colour:
        cols = parse_colours(d.get("text") or "")
        if not cols:
            return {}, Judgement("skip", 0.0, 0.5, (d.get("text") or "")[:400], dt,
                                 j.cost_usd, j.input_tokens, j.output_tokens, be.name,
                                 error="no colour lines")
        # Encode the LABEL as the payload; nothing downstream may treat it as ordered.
        return ({i: float(PALETTE.index(c)) for i, c in cols.items()},
                Judgement("skip", 0.0, 0.5, "", dt, j.cost_usd, j.input_tokens,
                          j.output_tokens, be.name))
    if pick:
        # n is not known here, so accept any id and let the caller clamp.
        picks = parse_picks(d.get("text") or "", 10_000)
        if picks is None:
            return {}, Judgement("skip", 0.0, 0.5, (d.get("text") or "")[:400], dt,
                                 j.cost_usd, j.input_tokens, j.output_tokens, be.name,
                                 error="no PICKS line")
        j = Judgement("skip", 0.0, 0.5, (d.get("text") or "")[:600], dt, j.cost_usd,
                      j.input_tokens, j.output_tokens, be.name)
        return {i: 1.0 for i in picks}, j
    so = d.get("structuredOutput") or _salvage_json(d.get("text") or "") or {}
    for e in (so.get("verdicts") or []):
        try:
            v = float(e["score"]) / 100.0 if taste else float(e["p_up"])
            out[int(e["id"])] = max(0.0, min(1.0, v))
        except (KeyError, TypeError, ValueError):
            continue
    return out, j


def _salvage_json(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------
# The policy: verdict -> stochastic action with a logged propensity
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LLMDecision:
    mint: str
    action: str  # "enter" | "skip"
    propensity: float
    p_enter: float
    verdict: str
    confidence: float
    explored: bool
    features_sha256: str
    decided_at: str
    decision_id: str
    policy_id: str


class LLMFilterPolicy:
    """Turn a model answer into a decision that off-policy evaluation can score.

    Two sources of randomisation, both logged, both deliberate — and the task's
    two permitted constructions are each exercised by one of the arms:

    * **The model's own uncertainty** (the probability arms). `p_up` is used
      directly as the entry probability, so a coin the model rates 0.7 is entered
      70% of the time. No wrapper, no hand-chosen epsilon shaping the middle of
      the distribution.
    * **An epsilon flip around a verdict** (the verdict arms), exactly as
      `shitcoims_scalper.policy` does it. A `buy` at confidence 0.6 is a weaker
      preference than a `buy` at 0.95, and collapsing both to "enter" throws that
      away, so the stated confidence sets the entry probability and the epsilon
      floor guarantees the other action stays reachable.

    The floor is not decoration. Without it the propensity of the unchosen action
    is zero and no importance-weighted estimator can identify it — the same
    requirement `PropensityRecord` enforces by refusing a propensity of 0. So
    `p_enter` lives in [eps, 1-eps] and the propensity of whichever action was
    sampled is what gets written down, at decision time, never reconstructed.
    """

    def __init__(self, *, policy_id: str, explore_eps: float = EXPLORE_EPS,
                 seed: int | None = None) -> None:
        if not 0.0 < explore_eps < 0.5:
            raise ValueError("explore_eps must be in (0, 0.5)")
        self.policy_id = policy_id
        self.explore_eps = explore_eps
        self.rng = random.Random(seed)

    def p_enter(self, signal: float) -> float:
        eps = self.explore_eps
        return max(eps, min(1.0 - eps, max(0.0, min(1.0, signal))))

    def decide(self, *, mint: str, features: dict[str, Any], verdict: str,
               confidence: float, now_unix: float, signal: float | None = None) -> LLMDecision:
        s = signal_from_verdict(verdict, confidence) if signal is None else signal
        p = self.p_enter(s)
        enter = self.rng.random() < p
        propensity = p if enter else 1.0 - p
        explored = enter != (verdict == "buy")
        feat = {k: features[k] for k in sorted(features)}
        digest = hashlib.sha256(
            json.dumps(feat, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        return LLMDecision(
            mint=mint,
            action="enter" if enter else "skip",
            propensity=propensity,
            p_enter=p,
            verdict=verdict,
            confidence=confidence,
            explored=explored,
            features_sha256=digest,
            decided_at=datetime.fromtimestamp(now_unix, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            decision_id=f"{mint[:8]}-{int(now_unix * 1000)}",
            policy_id=self.policy_id,
        )


def to_propensity_record(d: LLMDecision):
    """Construct the REAL `shitcoims_tape.schema.PropensityRecord`.

    Imported, not mirrored. If the tape's schema tightens — a stricter mint check,
    a narrower propensity interval — this study breaks loudly instead of quietly
    writing records the tape would reject.
    """
    from shitcoims_tape.schema import PropensityRecord

    return PropensityRecord(
        decision_id=d.decision_id,
        decided_at=d.decided_at,
        policy_id=d.policy_id,
        action=d.action,
        propensity=d.propensity,
        features_sha256=d.features_sha256,
        envelope_verdict="study",
        mint=d.mint,
    )


# --------------------------------------------------------------------------
# Screening
# --------------------------------------------------------------------------


@dataclass
class ScreenStats:
    calls: int = 0
    errors: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    latencies: list[float] = field(default_factory=list)
    wall_s: float = 0.0

    def summary(self) -> dict[str, Any]:
        lat = sorted(self.latencies)
        med = st.median(lat) if lat else 0.0
        p90 = lat[int(0.9 * (len(lat) - 1))] if lat else 0.0
        return {
            "calls": self.calls,
            "errors": self.errors,
            "cost_usd": round(self.cost_usd, 4),
            "cost_per_call_usd": round(self.cost_usd / self.calls, 5) if self.calls else 0.0,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_median_s": round(med, 2),
            "latency_p90_s": round(p90, 2),
            "wall_s": round(self.wall_s, 1),
            "calls_per_min": round(60.0 * self.calls / self.wall_s, 2) if self.wall_s else 0.0,
        }


def screen_batched(cohort: list[dict[str, Any]], meta: dict[str, dict[str, Any]], *,
                   arm: str, backend: "GrokCLIBackend", batch: int, max_usd: float,
                   seed: int, out_path: Path) -> ScreenStats:
    """Screen the cohort N coins per call, in cohort (time) order.

    Ordered by t0 rather than shuffled on purpose: a live screen would batch
    whatever arrived in the last few seconds, so its neighbours are contemporaries.
    Shuffling would make the batch context artificially diverse and flatter the
    method. A coin the model omits from its answer is recorded as an ERROR, not
    imputed — silent omission is the failure mode that makes batching dangerous
    and it must show up in the numbers.
    """
    policy = LLMFilterPolicy(policy_id=f"llm-glance-{arm}{batch}-v1", seed=seed)
    stats = ScreenStats()
    t_start = time.monotonic()
    with out_path.open("a") as fh:
        for start in range(0, len(cohort), batch):
            if stats.cost_usd >= max_usd:
                print(f"  !! cost cap ${max_usd:.2f} reached", flush=True)
                break
            rows = cohort[start:start + batch]
            res, j = grok_batch(backend, render_batch_prompt(rows, meta, arm), arm)
            stats.calls += 1
            stats.cost_usd += j.cost_usd
            stats.input_tokens += j.input_tokens
            stats.output_tokens += j.output_tokens
            stats.latencies.append(j.latency_s)
            picking = arm == "tastepick"
            colouring = arm == "colourfull"
            for i, row in enumerate(rows):
                p_up = res.get(i)
                if colouring:
                    lab = res.get(i)
                    err = j.error or (None if lab is not None else "no colour")
                    fx = {k: row.get(k) for k in ("age_s", "drawdown", "mc0_usd")}
                    # A colour is not a preference, so the policy stays uninformative:
                    # every coin gets the same coin-flip entry probability and a valid
                    # propensity. The colour rides along as a LABEL, never as a score.
                    d2 = policy.decide(mint=row["mint"], features=fx, verdict="skip",
                                       confidence=0.0, now_unix=row["t0"], signal=0.5)
                    fh.write(json.dumps({
                        "mint": row["mint"], "arm": arm, "t0": row["t0"],
                        "verdict": "skip", "confidence": 0.0, "signal": 0.5,
                        "p_up": None,
                        "colour": None if lab is None else PALETTE[int(lab)],
                        "reason": "", "error": err, "batch": batch,
                        "latency_s": round(j.latency_s / len(rows), 3),
                        "cost_usd": j.cost_usd / len(rows),
                        "input_tokens": j.input_tokens // len(rows),
                        "output_tokens": j.output_tokens // len(rows),
                        "prompt_sha256": "", "prompt_chars": 0,
                        "decision": {"action": d2.action, "propensity": d2.propensity,
                                     "p_enter": d2.p_enter, "explored": d2.explored},
                        "propensity_record": to_propensity_record(d2).to_json(),
                    }) + "\n")
                    continue
                if picking:
                    # Not mentioned IS the decision. Only a failed parse is an error.
                    p_up = 1.0 if i in res else 0.0
                    err = j.error
                else:
                    err = j.error or (None if p_up is not None else "omitted from batch")
                if err:
                    stats.errors += 1
                sig = 0.5 if p_up is None else p_up
                feats = {k: row.get(k) for k in
                         ("age_s", "trade_recency_s", "sol_in_curve", "drawdown", "mc0_usd",
                          "reply_count", "is_currently_live", "complete", "rank", "board")}
                d = policy.decide(mint=row["mint"], features=feats,
                                  verdict="buy" if sig >= 0.5 else "skip",
                                  confidence=abs(sig - 0.5) * 2, now_unix=row["t0"], signal=sig)
                fh.write(json.dumps({
                    "mint": row["mint"], "arm": arm, "t0": row["t0"],
                    "verdict": "buy" if sig >= 0.5 else "skip",
                    "confidence": abs(sig - 0.5) * 2, "signal": sig, "p_up": p_up,
                    "reason": j.reason if arm == "tastepick" else "",
                    "error": err, "batch": batch,
                    "latency_s": round(j.latency_s / len(rows), 3),
                    "cost_usd": j.cost_usd / len(rows),
                    "input_tokens": j.input_tokens // len(rows),
                    "output_tokens": j.output_tokens // len(rows),
                    "prompt_sha256": "", "prompt_chars": 0,
                    "decision": {"action": d.action, "propensity": d.propensity,
                                 "p_enter": d.p_enter, "explored": d.explored},
                    "propensity_record": to_propensity_record(d).to_json(),
                }) + "\n")
            fh.flush()
            print(f"    {start + len(rows)}/{len(cohort)}  ${stats.cost_usd:.2f}  "
                  f"{stats.errors} omitted", flush=True)
    stats.wall_s = time.monotonic() - t_start
    return stats


def screen(cohort: list[dict[str, Any]], meta: dict[str, dict[str, Any]], *,
           arm: str, backend: Backend, workers: int, max_usd: float,
           seed: int, out_path: Path) -> ScreenStats:
    policy = LLMFilterPolicy(policy_id=f"llm-glance-{arm}-v1", seed=seed)
    stats = ScreenStats()
    done: dict[str, dict[str, Any]] = {}
    if out_path.exists():  # resume: an interrupted run must not be re-paid for
        for line in out_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["mint"]] = r
        print(f"  resuming: {len(done)} already screened", flush=True)

    todo = [r for r in cohort if r["mint"] not in done]
    print(f"  arm={arm} to screen: {len(todo)} (cap ${max_usd:.2f}, {workers} workers)", flush=True)

    stop = False
    t_start = time.monotonic()
    with out_path.open("a") as fh, cf.ThreadPoolExecutor(workers) as ex:
        futs = {}
        for row in todo:
            prompt = render_prompt(row, meta.get(row["mint"], {}), arm)
            futs[ex.submit(backend.judge, prompt, arm)] = (row, prompt)
        for fut in cf.as_completed(futs):
            row, prompt = futs[fut]
            try:
                j = fut.result()
            except cf.CancelledError:
                continue  # cancelled by the cost cap; nothing was spent on it
            stats.calls += 1
            stats.cost_usd += j.cost_usd
            stats.input_tokens += j.input_tokens
            stats.output_tokens += j.output_tokens
            stats.latencies.append(j.latency_s)
            if j.error:
                stats.errors += 1
            feats = {k: row.get(k) for k in
                     ("age_s", "trade_recency_s", "sol_in_curve", "drawdown", "mc0_usd",
                      "reply_count", "is_currently_live", "complete", "rank", "board")}
            d = policy.decide(mint=row["mint"], features=feats, verdict=j.verdict,
                              confidence=j.confidence, now_unix=row["t0"], signal=j.signal)
            rec = {
                "mint": row["mint"],
                "arm": arm,
                "t0": row["t0"],
                "verdict": j.verdict,
                "confidence": j.confidence,
                "signal": j.signal,
                "p_up": j.p_up,
                "reason": j.reason,
                "error": j.error,
                "latency_s": round(j.latency_s, 3),
                "cost_usd": j.cost_usd,
                "input_tokens": j.input_tokens,
                "output_tokens": j.output_tokens,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "prompt_chars": len(prompt),
                "decision": {
                    "action": d.action, "propensity": d.propensity, "p_enter": d.p_enter,
                    "explored": d.explored,
                },
                "propensity_record": to_propensity_record(d).to_json(),
            }
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            if stats.calls % 20 == 0:
                print(f"    {stats.calls}/{len(todo)}  ${stats.cost_usd:.2f}  "
                      f"{stats.errors} err", flush=True)
            if stats.cost_usd >= max_usd and not stop:
                stop = True
                print(f"  !! cost cap ${max_usd:.2f} reached at {stats.calls} calls; "
                      "cancelling the rest", flush=True)
                for f2 in futs:
                    f2.cancel()
    stats.wall_s = time.monotonic() - t_start
    return stats


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def _signal(r: dict[str, Any]) -> float:
    """The graded preference in [0,1].

    Reconstructed from verdict+confidence when a decision log predates the
    `signal` field, and NOT from the logged `p_enter` — that one is clipped to
    [eps, 1-eps], which flattens every confident answer onto the same value and
    would silently destroy the ranking this study depends on.
    """
    v = r.get("signal")
    if v is not None:
        return float(v)
    return signal_from_verdict(r["verdict"], r["confidence"])


def _pup(vals: Sequence[float]) -> float:
    return 100.0 * sum(1 for v in vals if v > 0) / len(vals) if vals else float("nan")


def _stat_gap(sel: Sequence[float], rej: Sequence[float]) -> float:
    """The statistic under test: percentage-point gap in p(up), selected minus rejected.

    p(up) and not mean return, deliberately. These returns are heavy-tailed enough
    that a mean is a report on one or two coins; PROGRAM.md §3.5 wants base-rate
    preserving metrics, and a hit rate is one. The median is reported alongside but
    a median gap has no clean permutation interpretation when group sizes drift.
    """
    if not sel or not rej:
        return float("nan")
    return _pup(sel) - _pup(rej)


def auc(sel: Sequence[float], rej: Sequence[float]) -> float:
    """P(a selected coin out-returns a rejected one), ties at 0.5. 0.5 = no skill.

    A rank statistic, so it uses the whole return distribution instead of only its
    sign, and it is invariant to the heavy tail that makes the mean unreadable. It
    is also strictly more powerful than the p(up) gap at this sample size, which
    matters: at n=189 the p(up) gap's null band is ~14 pp wide and swallows most
    real effects. Base-rate preserving in the sense §3.5 asks for — it is a
    within-pair comparison and cannot be inflated by the selection rate.
    """
    if not sel or not rej:
        return float("nan")
    allv = sorted(list(sel) + list(rej))
    ranks: dict[float, float] = {}
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1] == allv[i]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        ranks[allv[i]] = r
        i = j + 1
    rsum = sum(ranks[v] for v in sel)
    n1, n2 = len(sel), len(rej)
    return (rsum - n1 * (n1 + 1) / 2.0) / (n1 * n2)


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    def rank(v: Sequence[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def partial_spearman(xs: Sequence[float], ys: Sequence[float],
                     zs: Sequence[float]) -> float:
    """Rank correlation of x and y with z's rank-linear part removed from both.

    The question this answers: once you already know `z`, does `x` still tell you
    anything about `y`? For an LLM handed the same numbers the baseline uses, that
    is the ONLY question worth asking — an arm that scores well by re-deriving the
    drawdown rule has added a 40-second round trip and no information.
    """
    def rank(v: Sequence[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    def resid(a: list[float], b: list[float]) -> list[float]:
        n = len(a)
        ma, mb = sum(a) / n, sum(b) / n
        sbb = sum((x - mb) ** 2 for x in b)
        if sbb == 0:
            return [x - ma for x in a]
        beta = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / sbb
        return [x - ma - beta * (y - mb) for x, y in zip(a, b)]

    rx, ry, rz = rank(xs), rank(ys), rank(zs)
    ex, ey = resid(rx, rz), resid(ry, rz)
    n = len(ex)
    mx, my = sum(ex) / n, sum(ey) / n
    num = sum((a - mx) * (b - my) for a, b in zip(ex, ey))
    den = (sum((a - mx) ** 2 for a in ex) * sum((b - my) ** 2 for b in ey)) ** 0.5
    return num / den if den else 0.0


def paired_arm_difference(sig_a: Sequence[float], sig_b: Sequence[float],
                          outcomes: Sequence[float], *, iters: int,
                          seed: int) -> tuple[float, float]:
    """Is arm A's ranking really better than arm B's, or are we reading two p-values?

    Comparing "A is significant and B is not" is the classic error — the DIFFERENCE
    has its own sampling distribution and it is wider than either. Null: per coin,
    swap which arm's signal is used, independently, 50/50. Under that null the arms
    are interchangeable and the observed gap in Spearman should be unremarkable.
    """
    obs = spearman(list(sig_a), list(outcomes)) - spearman(list(sig_b), list(outcomes))
    rng = random.Random(seed)
    hits = 0
    for _ in range(iters):
        a2, b2 = [], []
        for x, y in zip(sig_a, sig_b):
            if rng.random() < 0.5:
                a2.append(x); b2.append(y)
            else:
                a2.append(y); b2.append(x)
        d = spearman(a2, list(outcomes)) - spearman(b2, list(outcomes))
        if abs(d) >= abs(obs) - 1e-12:
            hits += 1
    return obs, (hits + 1) / (iters + 1)


def permutation_stat(labels: Sequence[Any], outcomes: Sequence[float],
                     stat: Callable[[Sequence[Any], Sequence[float]], float], *,
                     iters: int, seed: int) -> tuple[float, float, tuple[float, float]]:
    """Generic shuffled-label null: fix the decisions, permute the outcomes.

    Returns (observed, two-sided p, null 2.5/97.5 percentiles).
    """
    obs = stat(labels, outcomes)
    rng = random.Random(seed)
    pool = list(outcomes)
    null: list[float] = []
    for _ in range(iters):
        rng.shuffle(pool)
        v = stat(labels, pool)
        if v == v:
            null.append(v)
    null.sort()
    centre = null[len(null) // 2] if null else 0.0
    hits = sum(1 for v in null if abs(v - centre) >= abs(obs - centre) - 1e-12)
    lo = null[int(0.025 * (len(null) - 1))] if null else float("nan")
    hi = null[int(0.975 * (len(null) - 1))] if null else float("nan")
    return obs, (hits + 1) / (len(null) + 1), (lo, hi)


def _auc_stat(labels: Sequence[bool], outcomes: Sequence[float]) -> float:
    return auc([o for l, o in zip(labels, outcomes) if l],
               [o for l, o in zip(labels, outcomes) if not l])


def permutation_p(labels: Sequence[bool], outcomes: Sequence[float], *,
                  iters: int = 20000, seed: int = 11) -> tuple[float, float, float]:
    """THE SHUFFLED-LABEL NULL. Verdicts fixed, outcomes permuted.

    This holds the selector's decisions and its selection RATE exactly fixed and
    asks what gap that same selector would show against outcomes it cannot
    possibly have known. It is two-sided and it is the inference procedure as well
    as the null — no bootstrap, no resampling for balance (§3.3).

    Returns (observed gap, two-sided p, null 95th percentile of |gap|).
    """
    obs = _stat_gap([o for l, o in zip(labels, outcomes) if l],
                    [o for l, o in zip(labels, outcomes) if not l])
    rng = random.Random(seed)
    pool = list(outcomes)
    hits = 0
    absnull: list[float] = []
    for _ in range(iters):
        rng.shuffle(pool)
        g = _stat_gap([o for l, o in zip(labels, pool) if l],
                      [o for l, o in zip(labels, pool) if not l])
        absnull.append(abs(g))
        if abs(g) >= abs(obs) - 1e-12:
            hits += 1
    absnull.sort()
    return obs, (hits + 1) / (iters + 1), absnull[int(0.95 * (iters - 1))]


def describe(name: str, sel: Sequence[float], rej: Sequence[float], horizon: int) -> None:
    print(f"  {name}")
    for lbl, g in (("selected", sel), ("rejected", rej)):
        if not g:
            print(f"    {lbl:>10}  n=0")
            continue
        print(f"    {lbl:>10}  n={len(g):>4}  median {st.median(g) * 100:>8.2f}%  "
              f"mean {st.mean(g) * 100:>8.2f}%  p(up) {_pup(g):>5.1f}%")
    if sel and rej:
        print(f"    {'gap':>10}  p(up) {_stat_gap(sel, rej):+.1f} pp   "
              f"median {(st.median(sel) - st.median(rej)) * 100:+.2f} pp"
              f"   [horizon {horizon}s]")


def score(cohort: list[dict[str, Any]], decisions: dict[str, list[dict[str, Any]]],
          *, horizon: int, iters: int, seed: int) -> None:
    key = f"r{horizon}"
    by_mint = {r["mint"]: r for r in cohort}
    outcomes = {m: r["returns"][key] for m, r in by_mint.items() if r["returns"].get(key) is not None}

    print("=" * 78)
    print("LLM-AS-SELECTION-FILTER vs THE DRAWDOWN BASELINE")
    print("=" * 78)
    print(f"  cohort: {len(cohort)} entity-deduplicated board entries, horizon {horizon}s")
    print(f"  every number below is on the SAME cohort and the SAME survivor set.\n")

    # ---- the incumbent, on this cohort, at its published threshold
    sel = [outcomes[m] for m, r in by_mint.items() if m in outcomes and r["drawdown"] < DRAWDOWN_CUT]
    rej = [outcomes[m] for m, r in by_mint.items() if m in outcomes and r["drawdown"] >= DRAWDOWN_CUT]
    print(f"BASELINE — drawdown-at-entry, threshold {DRAWDOWN_CUT * 100:.0f}% off ATH")
    describe("shallow selects", sel, rej, horizon)
    labels = [by_mint[m]["drawdown"] < DRAWDOWN_CUT for m in outcomes]
    vals = [outcomes[m] for m in outcomes]
    obs, p, q95 = permutation_p(labels, vals, iters=iters, seed=seed)
    print(f"    NULL (shuffled labels, {iters} perms): observed {obs:+.1f} pp, "
          f"p={p:.4f}, null |gap| 95th pct {q95:.1f} pp")
    a, pa, (lo, hi) = permutation_stat(labels, vals, _auc_stat, iters=iters, seed=seed)
    print(f"    AUC {a:.3f}  p={pa:.4f}  null 95% [{lo:.3f}, {hi:.3f}]")
    dd = [-by_mint[m]["drawdown"] for m in outcomes]
    rho, prho, (rlo, rhi) = permutation_stat(
        dd, vals, lambda x, y: spearman(list(x), list(y)), iters=iters, seed=seed)
    print(f"    Spearman(-drawdown, return) {rho:+.3f}  p={prho:.4f}  "
          f"null 95% [{rlo:+.3f}, {rhi:+.3f}]\n")

    # ---- §3.4, baselines before models: every raw numeric on its own, unfitted.
    # No training, no cross-validation, nothing to overfit at n=189 — just "how
    # much does this one column already know?". If a single column beats the LLM,
    # the LLM is not adding judgement, it is adding latency.
    # `rankscore` is 0.5 + rho/2, i.e. Spearman rescaled onto the AUC axis so it
    # reads on the same scale as everything else in this report. It is NOT a
    # Mann-Whitney AUC and is not comparable to one digit-for-digit; it is
    # comparable ACROSS THIS TABLE, which is all it is used for. 0.5 = no relation,
    # below 0.5 = the feature predicts DOWN.
    print("SINGLE-FEATURE BASELINES — each raw number alone, no fitting "
          "(rankscore = 0.5 + rho/2; 0.5 is chance)")
    feats = ("drawdown", "age_s", "trade_recency_s", "sol_in_curve", "mc0_usd",
             "reply_count", "rank")
    tbl = []
    for f in feats:
        xs, ys = [], []
        for m in outcomes:
            xv = by_mint[m].get(f)
            if xv is None:
                continue
            xs.append(float(xv))
            ys.append(outcomes[m])
        if len(set(xs)) < 2:
            continue
        a, pa, _ = permutation_stat(xs, ys, lambda x, y: 0.5 + 0.5 * spearman(list(x), list(y)),
                                    iters=max(2000, iters // 4), seed=seed)
        tbl.append((abs(a - 0.5), f, a, pa, len(xs)))
    for _, f, a, pa, n in sorted(tbl, reverse=True):
        print(f"    {f:>16}  rankscore {a:.3f}  p={pa:.4f}  n={n}")
    print()

    # ---- each LLM arm
    for arm, recs in sorted(decisions.items()):
        ok = [r for r in recs if not r.get("error") and r["mint"] in outcomes]
        if not ok:
            print(f"ARM {arm}: no usable decisions\n")
            continue
        n_err = sum(1 for r in recs if r.get("error"))
        buy_rate = 100.0 * sum(1 for r in ok if r["verdict"] == "buy") / len(ok)
        confs = [r["confidence"] for r in ok]
        sig = [_signal(r) for r in ok]
        v = [outcomes[r["mint"]] for r in ok]
        print(f"ARM {arm}  (n={len(ok)}, {n_err} errors, buy-rate {buy_rate:.0f}%, "
              f"median confidence {st.median(confs):.2f}, signal range "
              f"{min(sig):.2f}-{max(sig):.2f}, distinct signals {len(set(sig))})")
        if buy_rate in (0.0, 100.0):
            print("    !! DEGENERATE VERDICT: this arm gave the same answer to every coin. "
                  "A selector with no contrast cannot be scored on its verdict; only the "
                  "graded signal below carries any information.")

        # (a) the raw verdict, the thing a human would act on
        s = [outcomes[r["mint"]] for r in ok if r["verdict"] == "buy"]
        j = [outcomes[r["mint"]] for r in ok if r["verdict"] == "skip"]
        describe("verdict=buy selects", s, j, horizon)
        if s and j:
            lab = [r["verdict"] == "buy" for r in ok]
            obs, p, q95 = permutation_p(lab, v, iters=iters, seed=seed)
            print(f"    NULL (shuffled labels): observed {obs:+.1f} pp, p={p:.4f}, "
                  f"null |gap| 95th pct {q95:.1f} pp")
            a, pa, (lo, hi) = permutation_stat(lab, v, _auc_stat, iters=iters, seed=seed)
            print(f"    AUC {a:.3f}  p={pa:.4f}  null 95% [{lo:.3f}, {hi:.3f}]")

        # (a2) THE GRADED SIGNAL, which survives a degenerate verdict. Does a
        #      higher stated preference mean a higher return? This is the most
        #      powerful test available at n=189 and it is the one that decides
        #      whether the glance carries information at all.
        if len(set(sig)) > 1:
            rho, prho, (rlo, rhi) = permutation_stat(
                sig, v, lambda x, y: spearman(list(x), list(y)), iters=iters, seed=seed)
            print(f"    Spearman(signal, return) {rho:+.3f}  p={prho:.4f}  "
                  f"null 95% [{rlo:+.3f}, {rhi:+.3f}]")
            # ...and the same correlation with the incumbent's own columns
            # partialled out. If this collapses, the arm re-derived the baseline.
            for ctrl in ("drawdown", "mc0_usd"):
                z = [float(by_mint[r["mint"]][ctrl]) for r in ok]
                pr = partial_spearman(sig, v, z)
                _, ppr, (plo, phi) = permutation_stat(
                    sig, v, lambda x, y, _z=z: partial_spearman(list(x), list(y), _z),
                    iters=iters, seed=seed)
                print(f"      partial on {ctrl:<9} {pr:+.3f}  p={ppr:.4f}  "
                      f"null 95% [{plo:+.3f}, {phi:+.3f}]")
            # ...and the selector you would actually run: take the top half by
            # signal. The threshold is the cohort median, reported here per §3.7.
            cutv = st.median(sig)
            lab = [x > cutv for x in sig]
            if 0 < sum(lab) < len(lab):
                ts = [outcomes[r["mint"]] for r, l in zip(ok, lab) if l]
                tj = [outcomes[r["mint"]] for r, l in zip(ok, lab) if not l]
                describe(f"top half by signal (> {cutv:.3f})", ts, tj, horizon)
                a, pa, (lo, hi) = permutation_stat(lab, v, _auc_stat, iters=iters, seed=seed)
                print(f"    AUC {a:.3f}  p={pa:.4f}  null 95% [{lo:.3f}, {hi:.3f}]")
        else:
            print("    !! CONSTANT SIGNAL: the model returned one number for every coin. "
                  "There is nothing to rank and nothing to test.")

        # (b) the sampled ACTION — what the propensity log actually records
        s = [outcomes[r["mint"]] for r in ok if r["decision"]["action"] == "enter"]
        j = [outcomes[r["mint"]] for r in ok if r["decision"]["action"] == "skip"]
        describe("sampled action=enter", s, j, horizon)

        # THE OPERATIVE SELECTOR from here down. When the verdict has contrast it
        # IS the selector; when the model said the same word to every coin the
        # only thing left to select on is the graded signal, split at its median.
        # Stated explicitly because a silent fallback would make the strata and
        # temporal tables below mean different things in different arms.
        if 0 < sum(1 for r in ok if r["verdict"] == "buy") < len(ok):
            picked = {r["mint"]: r["verdict"] == "buy" for r in ok}
            sel_desc = "verdict=buy"
        else:
            cutv = st.median(sig)
            picked = {r["mint"]: _signal(r) > cutv for r in ok}
            sel_desc = f"signal > {cutv:.3f}"
        print(f"    [selector for the tables below: {sel_desc}]")

        # (c) the conditional test: does the glance add anything the drawdown
        #     has not already said? This is the question that decides the study.
        for strat, keep in (("shallow (<50%)", lambda r: by_mint[r["mint"]]["drawdown"] < DRAWDOWN_CUT),
                            ("deep (>=50%)", lambda r: by_mint[r["mint"]]["drawdown"] >= DRAWDOWN_CUT)):
            sub = [r for r in ok if keep(r)]
            s = [outcomes[r["mint"]] for r in sub if picked[r["mint"]]]
            j = [outcomes[r["mint"]] for r in sub if not picked[r["mint"]]]
            describe(f"within {strat}", s, j, horizon)
            if s and j:
                lab = [picked[r["mint"]] for r in sub]
                vv = [outcomes[r["mint"]] for r in sub]
                a, pa, (lo, hi) = permutation_stat(lab, vv, _auc_stat, iters=iters, seed=seed)
                print(f"    AUC {a:.3f}  p={pa:.4f}  null 95% [{lo:.3f}, {hi:.3f}]")

        # (d) a same-rate random selector: the LLM must beat a coin flip that
        #     picks at its own base rate, not merely differ from zero.
        rng = random.Random(seed + 99)
        rate = sum(1 for m in picked.values() if m) / len(picked)
        gaps = []
        for _ in range(2000):
            lab = [rng.random() < rate for _ in ok]
            g = _stat_gap([o for l, o in zip(lab, v) if l], [o for l, o in zip(lab, v) if not l])
            if g == g:
                gaps.append(abs(g))
        gaps.sort()
        print(f"    RANDOM SELECTOR at the same {rate * 100:.0f}% rate: "
              f"|gap| median {st.median(gaps):.1f} pp, 95th pct {gaps[int(0.95 * len(gaps))]:.1f} pp")

        # (e) temporal split — §3.1/§3.6. One tape means this is a within-window
        #     check, not a held-out day; it is reported as such.
        tss = sorted(by_mint[r["mint"]]["t0"] for r in ok)
        cut = tss[len(tss) // 2]
        for half, keep in (("EARLY half", lambda r: by_mint[r["mint"]]["t0"] < cut),
                           ("LATE half", lambda r: by_mint[r["mint"]]["t0"] >= cut)):
            sub = [r for r in ok if keep(r)]
            s = [outcomes[r["mint"]] for r in sub if picked[r["mint"]]]
            j = [outcomes[r["mint"]] for r in sub if not picked[r["mint"]]]
            describe(f"{half} (n={len(sub)})", s, j, horizon)
        print()

    # ---- the colour arm gets its own test: an UNORDERED partition, so no rank
    # correlation and no AUC is meaningful. The only honest question is whether the
    # model's own grouping separates the outcomes at all.
    for arm, recs in sorted(decisions.items()):
        cols = [(r.get("colour"), outcomes.get(r["mint"])) for r in recs
                if r.get("colour") and r["mint"] in outcomes]
        if len(cols) < 30:
            continue
        buckets: dict[str, list[float]] = {}
        for c_, v_ in cols:
            buckets.setdefault(c_, []).append(v_)
        print(f"COLOUR PARTITION — arm {arm} (n={len(cols)}, "
              f"{len(buckets)} of {len(PALETTE)} colours used)")
        for name, g in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            print(f"    {name:>9}  n={len(g):>4}  median {st.median(g) * 100:>8.2f}%  "
                  f"p(up) {_pup(g):>5.1f}%")
        labs = [c_ for c_, _ in cols]
        vals2 = [v_ for _, v_ in cols]
        obs, pk, (klo, khi) = permutation_stat(
            labs, vals2,
            lambda L, V: kruskal_between(
                [[v for l2, v in zip(L, V) if l2 == k] for k in sorted(set(L))]),
            iters=iters, seed=seed)
        print(f"    between-colour rank spread {obs:.3f}  p={pk:.4f}  "
              f"null 95% [{klo:.3f}, {khi:.3f}]")
        print("    The colours are NOT ordered and are never treated as a score; this")
        print("    asks only whether the model's own partition knows anything.\n")

    # ---- §3.9, trials accounting. Every arm above was tested on two headline
    # statistics (rank AUC and Spearman), and the arms themselves were not
    # pre-registered — the probability framing was added AFTER the verdict framing
    # came back degenerate. That is a garden of forking paths and the correction
    # belongs in the report, not in a footnote nobody reads.
    n_arms = len(decisions)
    # Per arm: raw Spearman, top-half AUC, and two partials. Counting only the
    # two we would headline would be exactly the undercount §3.9 warns about.
    n_tests = 4 * n_arms
    print(f"TRIALS ACCOUNTING — {n_arms} arms x 4 reported statistics = {n_tests} tests.")
    print(f"  Bonferroni threshold for a family-wise 5%: p < {0.05 / n_tests:.4f}.")
    print("  Any arm above whose p does not clear that is a candidate, not a finding.")
    print("  The baseline is exempt: it was published before this study and is the")
    print("  thing being tested against, not one of the tests.\n")

    # ---- arm agreement: is the vibe doing anything at all?
    for fa, ba in (("full", "blind"), ("probfull", "probblind")):
        if fa not in decisions or ba not in decisions:
            continue
        f = {r["mint"]: r for r in decisions[fa] if not r.get("error")}
        b = {r["mint"]: r for r in decisions[ba] if not r.get("error")}
        both = sorted(set(f) & set(b))
        if both:
            agree = sum(1 for m in both if f[m]["verdict"] == b[m]["verdict"])
            print(f"SIGHTED ({fa}) vs BLIND ({ba})")
            print(f"  verdict agreement on {len(both)} shared coins: "
                  f"{100.0 * agree / len(both):.0f}%")
            ds = [_signal(f[m]) - _signal(b[m]) for m in both]
            rr = [outcomes[m] for m in both if m in outcomes]
            dd2 = [_signal(f[m]) - _signal(b[m]) for m in both if m in outcomes]
            print(f"  signal shift from seeing the content: median {st.median(ds):+.3f}, "
                  f"|shift| median {st.median([abs(x) for x in ds]):.3f}, "
                  f"Spearman(shift, return) {spearman(dd2, rr):+.3f}")
            print("  THE VIBE TEST: that last number is the whole question — it is the "
                  "correlation between what the CONTENT alone changed and what happened.")
            shared = [m for m in both if m in outcomes]
            if len(shared) > 20:
                d, pd = paired_arm_difference(
                    [_signal(b[m]) for m in shared], [_signal(f[m]) for m in shared],
                    [outcomes[m] for m in shared], iters=min(iters, 5000), seed=seed)
                print(f"  PAIRED ARM DIFFERENCE (blind minus sighted Spearman) on "
                      f"{len(shared)} coins: {d:+.3f}, p={pd:.4f}")
                print("  Two separate p-values are not a comparison; this line is.")
            flips = [m for m in both if f[m]["verdict"] != b[m]["verdict"]]
            if flips:
                fb = [outcomes[m] for m in flips if m in outcomes and f[m]["verdict"] == "buy"]
                bb = [outcomes[m] for m in flips if m in outcomes and b[m]["verdict"] == "buy"]
                print(f"  {len(flips)} disagreements. Where the CONTENT flipped it to buy: "
                      f"n={len(fb)} p(up) {_pup(fb):.0f}%; where content flipped it to skip: "
                      f"n={len(bb)} p(up) {_pup(bb):.0f}%")
                print("  If the content carries signal, the first should beat the second.")


# --------------------------------------------------------------------------
# Self-test — the anti-mirror gate
# --------------------------------------------------------------------------


def selftest() -> int:
    """No network, no spend. Proves the harness talks to the REAL schema."""
    from shitcoims_tape.schema import PropensityRecord

    fails: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
        if not cond:
            fails.append(name)

    pol = LLMFilterPolicy(policy_id=POLICY_ID_FULL, seed=1)

    # 1. Propensity is never 0 or >1, at any verdict/confidence the schema will see.
    bad = [(v, c) for v in ("buy", "skip") for c in (0.0, 0.5, 1.0)
           if not (0.0 < pol.p_enter(signal_from_verdict(v, c)) < 1.0)]
    bad += [(x,) for x in (0.0, 1.0, -5.0, 5.0) if not (0.0 < pol.p_enter(x) < 1.0)]
    check("p_enter stays strictly inside (0,1)", not bad, str(bad))

    # 2. Confidence 1.0 must NOT collapse to a deterministic action, or off-policy
    #    evaluation loses the arm it needs. This is the failure the design exists
    #    to prevent, so it is asserted, not assumed.
    acts = {pol.decide(mint="A" * 43, features={"x": 1}, verdict="buy",
                       confidence=1.0, now_unix=1786717317.0).action
            for _ in range(400)}
    check("a confidence-1.0 buy still sometimes skips", acts == {"enter", "skip"}, str(acts))

    # 3. The REAL PropensityRecord accepts what we emit — imported, not mirrored.
    d = pol.decide(mint="8XtRWb4uAAJFMP4QQhoYYCWR6XXb7ybcCdiqPwz9s5WS",
                   features={"drawdown": 0.4, "age_s": 120.0}, verdict="buy",
                   confidence=0.8, now_unix=1786717317.0)
    rec = to_propensity_record(d)
    check("constructs a real shitcoims_tape PropensityRecord",
          isinstance(rec, PropensityRecord) and rec.to_json()["propensity"] == d.propensity)

    # 4. And rejects a zero propensity, which is what makes (1) load-bearing.
    try:
        PropensityRecord(decision_id="x", decided_at=d.decided_at, policy_id="p",
                         action="enter", propensity=0.0, features_sha256="0" * 64,
                         envelope_verdict="study")
        check("schema rejects propensity 0", False, "it did not")
    except Exception as e:
        check("schema rejects propensity 0", True, type(e).__name__)

    # 5. The two arms really are the same numbers with the strings removed.
    row = {"mint": "m", "board": "market_cap", "t0": 1.0, "rank": 3, "mc0_usd": 5000.0,
           "drawdown": 0.42, "symbol": "WIF", "reply_count": 12, "is_currently_live": True,
           "complete": False, "ath_market_cap": 9000.0, "age_s": 300.0,
           "trade_recency_s": 4.0, "sol_in_curve": 31.2}
    meta = {"name": "dogwifhat", "description": "a dog with a hat", "image_uri": "ipfs://x",
            "twitter": "https://twitter.com/x"}
    full, blind = render_prompt(row, meta, "full"), render_prompt(row, meta, "blind")
    leaks = [s for s in ("WIF", "dogwifhat", "a dog with a hat", "ipfs://x", "twitter.com")
             if s in blind]
    check("blind arm leaks no identifying content", not leaks, str(leaks))
    check("blind arm keeps every number", all(
        f"{row['drawdown'] * 100:.1f}%" in blind and "31.20 SOL" in blind
        and "5,000" in blind and "300 s" in blind for _ in (0,)))
    check("full arm carries the content", all(s in full for s in ("WIF", "dogwifhat", "ipfs://x")))
    pf = render_prompt(row, meta, "probfull")
    pb = render_prompt(row, meta, "probblind")
    check("probability arms ask for p_up, not a verdict",
          "p_up" in pf and "p_up" in pb and "verdict" not in pf)
    check("probability blind arm leaks nothing either",
          not [x for x in ("WIF", "dogwifhat", "ipfs://x") if x in pb])

    # A probability arm must use the model's OWN number as the entry probability,
    # not a rescaled version of it -- that is the "sample from its uncertainty"
    # construction the design promises, and it is only true away from the clip.
    check("p_up passes through as p_enter", abs(pol.p_enter(0.73) - 0.73) < 1e-9)
    sb = StubBackend()
    jp = [sb.judge(f"c{i}", "probfull") for i in range(200)]
    check("prob stub spans the range and sets p_up",
          all(j.p_up is not None for j in jp) and max(j.signal for j in jp) - min(
              j.signal for j in jp) > 0.5)

    # 6. The stub backend carries no outcome information, so the scorer must find
    #    nothing on it. A scorer that reports an edge here is broken (§3.12: the
    #    known-ZERO world).
    stub = StubBackend()
    js = [stub.judge(f"coin {i}") for i in range(400)]
    check("stub is a genuine coin flip", 0.4 < sum(1 for j in js if j.verdict == "buy") / len(js) < 0.6)
    rng = random.Random(3)
    lab = [j.verdict == "buy" for j in js]
    out = [rng.gauss(0, 1) for _ in js]
    _, p, _ = permutation_p(lab, out, iters=2000, seed=5)
    check("permutation test finds nothing in a known-zero world", p > 0.05, f"p={p:.3f}")

    # 7. And finds something in a known-EFFECT world (§3.12: both controls, always).
    out2 = [abs(rng.gauss(0, 1)) if l else -abs(rng.gauss(0, 1)) for l in lab]
    _, p2, _ = permutation_p(lab, out2, iters=2000, seed=5)
    check("permutation test finds a planted effect", p2 < 0.01, f"p={p2:.4f}")

    print(f"\n  {'ALL PASS' if not fails else str(len(fails)) + ' FAILURE(S): ' + ', '.join(fails)}")
    return 1 if fails else 0


# --------------------------------------------------------------------------


def dec_path(arm: str, backend: str, horizon: int) -> Path:
    """Where an arm's decisions live. The primary horizon keeps the unsuffixed
    name the first runs wrote, so those are not re-paid for."""
    if horizon == PRIMARY_HORIZON:
        return CACHE / f"decisions-{arm}-{backend}.jsonl"
    return CACHE / f"decisions-{arm}-{backend}-h{horizon}.jsonl"


def _load_jsonl(p: Path) -> list[dict[str, Any]]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", required=True,
                    choices=("cohort", "meta", "screen", "score", "selftest", "latency",
                             "batch"))
    ap.add_argument("--arm", default="full", choices=ALL_ARMS)
    ap.add_argument("--backend", default="grok", choices=("grok", "stub"))
    ap.add_argument("--model", default=None)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-usd", type=float, default=3.0)
    ap.add_argument("--horizon", type=int, default=PRIMARY_HORIZON)
    ap.add_argument("--iters", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--limit", type=int, default=0, help="screen only the first N (debug)")
    ap.add_argument("--batch-sizes", default="1,5,10,25,50")
    ap.add_argument("--batch", type=int, default=25, help="coins per call for the batch arms")
    ap.add_argument("--sample", type=int, default=0,
                    help="cohort stage: seeded uniform draw down to N entities")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    cohort_p = CACHE / f"cohort-{args.horizon}.json"
    meta_p = CACHE / "meta.json"

    if args.stage == "selftest":
        return selftest()

    if args.stage == "cohort":
        c = build_cohort(args.horizon)
        if args.sample and len(c) > args.sample:
            # THE SAMPLING RULE for a horizon whose population exceeds the budget:
            # a seeded uniform draw over the entity-deduplicated cohort, taken
            # BEFORE any screening and never revisited. Not stratified — §3.3 —
            # so the drawdown and market-cap base rates the baseline is measured
            # on are the ones the LLM is measured on.
            c = sorted(random.Random(args.seed).sample(c, args.sample), key=lambda r: r["t0"])
            print(f"  sampled {len(c)} of the full cohort (seed {args.seed})")
        cohort_p.write_text(json.dumps(c, indent=1))
        sh = [r for r in c if r["drawdown"] < DRAWDOWN_CUT]
        dp = [r for r in c if r["drawdown"] >= DRAWDOWN_CUT]
        k = f"r{args.horizon}"
        print(f"cohort: {len(c)} mints -> {cohort_p}")
        print(f"  t0 span: {(max(r['t0'] for r in c) - min(r['t0'] for r in c)) / 3600:.2f} h")
        for lbl, g in (("shallow", sh), ("deep", dp)):
            v = [r["returns"][k] for r in g]
            print(f"  {lbl:>8} n={len(g):>4} median {st.median(v) * 100:>7.2f}% "
                  f"p(up) {_pup(v):>5.1f}%")
        return 0

    if args.stage == "meta":
        c = json.loads(cohort_p.read_text())
        # MERGE, never overwrite: one metadata file serves every horizon's cohort,
        # and clobbering it would silently un-sight an already-screened arm.
        m = json.loads(meta_p.read_text()) if meta_p.exists() else {}
        need = [r["mint"] for r in c if r["mint"] not in m or m[r["mint"]].get("_error")]
        print(f"  {len(c) - len(need)} already cached, fetching {len(need)}")
        m.update(fetch_meta(need))
        meta_p.write_text(json.dumps(m, indent=1))
        m = {r["mint"]: m[r["mint"]] for r in c}
        errs = sum(1 for v in m.values() if v.get("_error"))
        named = sum(1 for v in m.values() if v.get("name"))
        desc = sum(1 for v in m.values() if (v.get("description") or "").strip())
        img = sum(1 for v in m.values() if v.get("image_uri"))
        soc = sum(1 for v in m.values() if v.get("twitter") or v.get("telegram"))
        print(f"metadata: {len(m)} mints ({errs} errors) -> {meta_p}")
        print(f"  name {named} · description {desc} · image {img} · socials {soc}")
        return 0

    if args.stage == "latency":
        be = _backend(args)
        row = json.loads(cohort_p.read_text())[0]
        meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
        p = render_prompt(row, meta.get(row["mint"], {}), args.arm)
        print(f"prompt is {len(p)} chars")
        for i in range(3):
            j = be.judge(p)
            print(f"  call {i}: {j.latency_s:.1f}s  ${j.cost_usd:.5f}  "
                  f"in={j.input_tokens} out={j.output_tokens}  "
                  f"{j.verdict}@{j.confidence}  err={j.error}")
        return 0

    if args.stage == "batch":
        # THE THROUGHPUT QUESTION, measured rather than asserted. Two things come
        # out of it: how much the fixed per-call preamble amortises, and whether
        # the answers survive being asked together.
        c = json.loads(cohort_p.read_text())
        meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
        be = _backend(args)
        if not isinstance(be, GrokCLIBackend):
            print("batch staging needs the grok backend")
            return 2
        single = {r["mint"]: _signal(r)
                  for r in _load_jsonl(dec_path(args.arm, args.backend, args.horizon))
                  if not r.get("error")}
        sizes = [int(x) for x in args.batch_sizes.split(",")]
        rng = random.Random(args.seed)
        print(f"{'batch':>6}{'calls':>7}{'coins':>7}{'wall_s':>9}{'coins/min':>11}"
              f"{'$/coin':>10}{'tok/coin':>10}{'returned':>10}{'rho vs single':>15}")
        for n in sizes:
            pool = [r for r in c if r["mint"] in single] or c
            reps = max(1, min(3, len(pool) // n))
            got: dict[str, float] = {}
            cost = tin = tout = 0
            t0 = time.monotonic()
            for _ in range(reps):
                rows = rng.sample(pool, n)
                res, j = grok_batch(be, render_batch_prompt(rows, meta, args.arm), args.arm)
                cost += j.cost_usd
                tin += j.input_tokens
                tout += j.output_tokens
                for i, row in enumerate(rows):
                    if i in res:
                        got[row["mint"]] = res[i]
            wall = time.monotonic() - t0
            coins = reps * n
            shared = [m for m in got if m in single]
            rho = (spearman([got[m] for m in shared], [single[m] for m in shared])
                   if len(shared) > 5 else float("nan"))
            print(f"{n:>6}{reps:>7}{coins:>7}{wall:>9.1f}{60 * coins / wall:>11.1f}"
                  f"{cost / coins:>10.5f}{(tin + tout) // max(1, coins):>10}"
                  f"{len(got):>10}{rho:>15.3f}")
        print("\n  'rho vs single' is the rank correlation between the batched score and the")
        print("  SINGLE-CALL score for the same coin. Near 1.0 means batching is free; well")
        print("  below means the speedup bought a different question being answered.")
        return 0

    if args.stage == "screen":
        c = json.loads(cohort_p.read_text())
        if args.limit:
            c = c[: args.limit]
        meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
        if base_arm(args.arm) == "full" and not meta:
            print("refusing to run the sighted arm without metadata; run --stage meta")
            return 2
        out = dec_path(args.arm, args.backend, args.horizon)
        if args.arm in BATCH_ARMS:
            be = _backend(args)
            if not isinstance(be, GrokCLIBackend):
                print("batch arms need the grok backend")
                return 2
            s = screen_batched(c, meta, arm=args.arm, backend=be, batch=args.batch,
                               max_usd=args.max_usd, seed=args.seed, out_path=out)
        else:
            s = screen(c, meta, arm=args.arm, backend=_backend(args), workers=args.workers,
                       max_usd=args.max_usd, seed=args.seed, out_path=out)
        print(json.dumps(s.summary(), indent=1))
        print(f"  -> {out}")
        return 0

    if args.stage == "score":
        c = json.loads(cohort_p.read_text())
        decisions: dict[str, list[dict[str, Any]]] = {}
        for arm in ALL_ARMS:
            recs = _load_jsonl(dec_path(arm, args.backend, args.horizon))
            if recs:
                decisions[arm] = recs
        if not decisions:
            print("no decisions on disk; run --stage screen first")
            return 2
        score(c, decisions, horizon=args.horizon, iters=args.iters, seed=args.seed)
        for arm, recs in sorted(decisions.items()):
            lat = [r["latency_s"] for r in recs if r.get("latency_s")]
            cost = sum(r.get("cost_usd") or 0.0 for r in recs)
            tin = sum(r.get("input_tokens") or 0 for r in recs)
            tout = sum(r.get("output_tokens") or 0 for r in recs)
            if lat:
                print(f"\nCOST/LATENCY arm={arm}: {len(recs)} calls, ${cost:.2f} "
                      f"(${cost / len(recs):.5f}/call), {tin:,} in / {tout:,} out tokens, "
                      f"latency median {st.median(lat):.1f}s p90 "
                      f"{sorted(lat)[int(0.9 * (len(lat) - 1))]:.1f}s")
        return 0

    return 2


def _backend(args) -> Backend:
    if args.backend == "stub":
        return StubBackend()
    return GrokCLIBackend(model=args.model, effort=args.effort)


if __name__ == "__main__":
    raise SystemExit(main())
