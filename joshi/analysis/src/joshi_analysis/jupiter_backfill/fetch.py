"""Bounded, receipted backfill fetcher for SOL up/down rounds (Polymarket public data).

READ-ONLY: GET requests only, to three public Polymarket surfaces —

- Gamma      https://gamma-api.polymarket.com  round enumeration by recurring series
             (sol-up-or-down-5m id 10686, sol-up-or-down-15m id 10423) and Polymarket's
             own resolution fields (closed / umaResolutionStatus / outcomePrices).
- data-api   https://data-api.polymarket.com/trades  tick-level FILLS per conditionId
             (both outcome tokens in one call) — the primary price data: what actually
             transacted, at full resolution. Fills, not the book.
- CLOB       https://clob.polymarket.com/prices-history  1-minute price points per
             outcome token — the fallback for rounds too thin in fills.

Every response body is retained VERBATIM (raw text) with both clocks in the raw jsonl
files; the assembled rounds.jsonl is a DERIVED join shape documented in BACKFILL.md.
A global request budget hard-stops the run; every request, gap, retry, and truncation
is receipted. A failed pull is a durable gap record, never a silent skip.

Run (network required; uv --offline refers to package resolution only):
    cd analysis && uv run --offline python -m joshi_analysis.jupiter_backfill.fetch \
        --days-5m 7 --days-15m 14 --budget 6000 \
        --out ~/dev/joshi/state/prediction/backfill
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import reads

GAMMA = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = "joshi-prediction-backfill/1 (read-only study)"

SERIES = {"5m": "10686", "15m": "10423"}
ENUM_PAGE = 100
ENUM_MAX_OFFSET = 2900  # gamma rejects offsets >= ~3000
RECONCILE_CAP = 400  # per horizon: slug re-probes for grid slots the pages missed
TRADES_PAGE = 500
MAX_TRADE_PAGES = 6  # 3000 fills per round; beyond that the round is flagged truncated
THIN_SIDE_OBS = 5  # < this many in-window fills on either side -> fetch 1-min history
HISTORY_PRE_S = 3600  # 1 h of pre-window listing-time prices (stale buy-ahead census)
HISTORY_POST_S = 300  # past close: catches the settlement pin


def _now_us() -> int:
    return int(time.time() * 1_000_000)


class Budget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.spent = 0
        self.by_stage: dict[str, int] = {}

    def take(self, stage: str) -> bool:
        if self.spent >= self.limit:
            return False
        self.spent += 1
        self.by_stage[stage] = self.by_stage.get(stage, 0) + 1
        return True

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit


class Fetcher:
    """Paced GET with verbatim retention and one retry; failures become gap records."""

    def __init__(self, raw_dir: Path, stamp: str, budget: Budget, pace_s: float) -> None:
        self.budget = budget
        self.pace_s = pace_s
        self.gaps: list[dict] = []
        self._raw_paths = {
            kind: raw_dir / f"backfill-{stamp}-{kind}.jsonl"
            for kind in ("enum", "trades", "prices", "reconcile")
        }

    def _emit_raw(self, kind: str, record: dict) -> None:
        record["arrivalUnixUs"] = _now_us()
        record["arrivalMonotonicNs"] = time.monotonic_ns()
        with self._raw_paths[kind].open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def get_json(self, kind: str, stage: str, url: str, meta: dict) -> object | None:
        """One budgeted, paced GET (+1 retry). Returns parsed JSON or None (durable gap)."""
        for attempt in (1, 2):
            if not self.budget.take(stage):
                self.gaps.append({"stage": stage, "why": "budget-exhausted", **meta})
                return None
            time.sleep(self.pace_s)
            status, body = self._get(url)
            self._emit_raw(
                kind,
                {"url": url, "httpStatus": status, "attempt": attempt, **meta,
                 "bodyText": body},
            )
            if status == 200 and body is not None:
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    pass  # fall through to retry
            time.sleep(3.0 if status == 429 else 0.5)
        self.gaps.append({"stage": stage, "why": f"http-{status}", **meta})
        return None

    @staticmethod
    def _get(url: str, timeout: float = 25.0) -> tuple[int, str | None]:
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, None
        except Exception:
            return 0, None


def parse_event(event: dict, horizon: str) -> dict | None:
    """One gamma event (with its single embedded market) -> a partial round record."""
    markets = event.get("markets") or []
    if len(markets) != 1:
        return None
    m = markets[0]
    slug = str(event.get("slug") or "")
    window_start = reads.parse_window_start(slug)
    close_unix = reads.iso_to_unix(m.get("endDate"))
    if window_start is None or close_unix is None:
        return None
    outcomes = reads.json_list(m.get("outcomes"))
    token_ids = reads.json_list(m.get("clobTokenIds"))
    if close_unix - window_start != reads.HORIZON_SECONDS[horizon]:
        return None
    return {
        "contract": "joshi.jupiter_backfill.round.v1",
        "roundKey": f"{horizon}-{window_start}",
        "horizon": horizon,
        "windowStartUnix": window_start,
        "closeTimeUnix": close_unix,
        "slug": slug,
        "gammaEventId": str(event.get("id")),
        "gammaMarketId": str(m.get("id")),
        "conditionId": m.get("conditionId"),
        "clobTokenIds": token_ids,
        "outcomes": outcomes,
        "ruleEra": reads.classify_era(m.get("resolutionSource")),
        "resolutionSource": m.get("resolutionSource"),
        "listedAt": m.get("createdAt"),
        "volumeUsd": m.get("volumeNum"),
        "gammaResolution": {
            "closed": m.get("closed"),
            "umaResolutionStatus": m.get("umaResolutionStatus"),
            "outcomePrices": reads.json_list(m.get("outcomePrices")),
            "closedTime": m.get("closedTime"),
        },
    }


def enumerate_series(f: Fetcher, horizon: str, cutoff_unix: int) -> dict[str, dict]:
    """Walk the series' closed events newest-first until the cutoff; dedup by roundKey."""
    rounds: dict[str, dict] = {}
    offset = 0
    while offset <= ENUM_MAX_OFFSET:
        url = (
            f"{GAMMA}/events?series_id={SERIES[horizon]}&closed=true"
            f"&limit={ENUM_PAGE}&order=id&ascending=false&offset={offset}"
        )
        page = f.get_json("enum", "enum", url, {"horizon": horizon, "offset": offset})
        if not isinstance(page, list) or not page:
            break
        oldest_seen = None
        for event in page:
            rec = parse_event(event, horizon)
            if rec is None:
                f.gaps.append(
                    {"stage": "enum", "why": "unparseable-event",
                     "eventId": str(event.get("id")), "horizon": horizon}
                )
                continue
            oldest_seen = rec["windowStartUnix"]
            if rec["windowStartUnix"] >= cutoff_unix:
                rounds[rec["roundKey"]] = rec
        offset += ENUM_PAGE
        if oldest_seen is not None and oldest_seen < cutoff_unix:
            break
    return rounds


def reconcile_grid(
    f: Fetcher, rounds: dict[str, dict], horizon: str, cutoff_unix: int, now_unix: int
) -> dict:
    """Offset paging can skip a round when new events close mid-walk. Re-fetch every
    grid slot missing from the enumeration by its deterministic slug; slots that stay
    empty are recorded as absent (round not closed / never existed) — a durable fact,
    not a silent hole."""
    step = reads.HORIZON_SECONDS[horizon]
    grid_start = cutoff_unix - (cutoff_unix % step) + step
    expected = range(grid_start, now_unix - 2 * step, step)
    missing = [ws for ws in expected if f"{horizon}-{ws}" not in rounds]
    probed, unprobed = missing[:RECONCILE_CAP], missing[RECONCILE_CAP:]
    recovered = 0
    absent = []
    for ws in probed:
        slug = f"sol-updown-{horizon}-{ws}"
        url = f"{GAMMA}/events?slug={slug}"
        page = f.get_json("reconcile", "reconcile", url, {"slug": slug})
        rec = parse_event(page[0], horizon) if isinstance(page, list) and page else None
        if rec is not None and rec["windowStartUnix"] >= cutoff_unix:
            rounds[rec["roundKey"]] = rec
            recovered += 1
        else:
            absent.append(ws)
    return {"expectedGridSlots": len(list(expected)), "missingAfterPages": len(missing),
            "recoveredBySlug": recovered, "absentCount": len(absent),
            "absentSlotsFirst50": absent[:50], "unprobedBeyondCap": len(unprobed)}


def fetch_trades(f: Fetcher, rec: dict) -> None:
    """All fills for the round's conditionId (both outcome tokens, full market lifetime:
    pre-window listing trades through post-close pin trades). Slim rows, ascending t."""
    condition_id = rec["conditionId"]
    all_trades: list[dict] = []
    pages = 0
    truncated = False
    fetched = True
    while pages < MAX_TRADE_PAGES:
        url = (
            f"{DATA_API}/trades?market={condition_id}"
            f"&limit={TRADES_PAGE}&offset={pages * TRADES_PAGE}"
        )
        body = f.get_json(
            "trades", "trades", url, {"roundKey": rec["roundKey"], "page": pages}
        )
        if not isinstance(body, list):
            fetched = pages > 0  # partial coverage still counts as fetched-with-gap
            break
        all_trades.extend(t for t in body if isinstance(t, dict))
        pages += 1
        if len(body) < TRADES_PAGE:
            break
    else:
        truncated = True
    rows = sorted(
        [
            [t.get("timestamp"), t.get("outcomeIndex"), t.get("price"),
             t.get("size"), t.get("side")]
            for t in all_trades
            if isinstance(t.get("timestamp"), int)
        ],
        key=lambda r: r[0],
    )
    zones = reads.split_zones(rows, rec["windowStartUnix"], rec["closeTimeUnix"])
    rec["trades"] = {
        "fetched": fetched,
        "requests": pages,
        "truncated": truncated,
        "count": len(rows),
        "inWindowCount": zones.counts,
        "rows": rows,
    }


def fetch_history(f: Fetcher, rec: dict) -> None:
    """1-minute price points for both outcome tokens (thin-round fallback)."""
    start = rec["windowStartUnix"] - HISTORY_PRE_S
    end = rec["closeTimeUnix"] + HISTORY_POST_S
    out: dict[str, list] = {}
    for side, token in zip(("up", "down"), rec["clobTokenIds"], strict=False):
        url = (
            f"{CLOB}/prices-history?market={token}"
            f"&startTs={start}&endTs={end}&fidelity=1"
        )
        body = f.get_json(
            "prices", "prices", url, {"roundKey": rec["roundKey"], "side": side}
        )
        hist = body.get("history") if isinstance(body, dict) else None
        out[side] = (
            [[p.get("t"), p.get("p")] for p in hist if isinstance(p, dict)]
            if isinstance(hist, list)
            else []
        )
    rec["priceHistory"] = {"fetched": True, "up": out.get("up", []),
                           "down": out.get("down", [])}


def is_thin(rec: dict) -> bool:
    counts = rec.get("trades", {}).get("inWindowCount", {})
    return min(counts.get("up", 0), counts.get("down", 0)) < THIN_SIDE_OBS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-5m", type=float, default=7.0)
    ap.add_argument("--days-15m", type=float, default=14.0)
    ap.add_argument("--budget", type=int, default=6000, help="hard cap on HTTP requests")
    ap.add_argument("--pace", type=float, default=0.12, help="seconds between requests")
    ap.add_argument(
        "--out", type=Path, default=Path("~/dev/joshi/state/prediction/backfill")
    )
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = reads.utc_stamp()
    budget = Budget(args.budget)
    f = Fetcher(args.out, stamp, budget, args.pace)
    now_unix = int(time.time())

    rounds: dict[str, dict] = {}
    reconcile: dict[str, dict] = {}
    spans = {"5m": args.days_5m, "15m": args.days_15m}
    for horizon, days in spans.items():
        cutoff = now_unix - int(days * 86400)
        found = enumerate_series(f, horizon, cutoff)
        reconcile[horizon] = reconcile_grid(f, found, horizon, cutoff, now_unix)
        rounds.update(found)
        print(f"enumerated {horizon}: {len(found)} rounds "
              f"(grid: {reconcile[horizon]})", flush=True)

    ordered = sorted(rounds.values(), key=lambda r: (r["horizon"], r["windowStartUnix"]))
    for i, rec in enumerate(ordered):
        if budget.exhausted:
            rec["trades"] = {"fetched": False, "requests": 0, "truncated": False,
                             "count": 0, "inWindowCount": {}, "rows": []}
            continue
        fetch_trades(f, rec)
        if i % 200 == 0:
            print(f"trades {i}/{len(ordered)} (requests {budget.spent})", flush=True)

    thin = [rec for rec in ordered if is_thin(rec) and rec["trades"]["fetched"]]
    print(f"thin rounds needing 1-min history: {len(thin)}", flush=True)
    for rec in thin:
        if budget.exhausted:
            break
        fetch_history(f, rec)
    for rec in ordered:
        rec.setdefault("priceHistory", {"fetched": False, "up": [], "down": []})

    rounds_path = args.out / f"backfill-{stamp}-rounds.jsonl"
    with rounds_path.open("w") as fh:
        for rec in ordered:
            rec["settlement"] = reads.settle_labels(rec)
            del rec["gammaResolution"]  # now nested under settlement.gamma
            fh.write(json.dumps(rec) + "\n")

    by_horizon = {
        h: sum(1 for r in ordered if r["horizon"] == h) for h in SERIES
    }
    label_sources: dict[str, int] = {}
    eras: dict[str, int] = {}
    for rec in ordered:
        label_sources[rec["settlement"]["labelSource"]] = (
            label_sources.get(rec["settlement"]["labelSource"], 0) + 1
        )
        eras[rec["ruleEra"]] = eras.get(rec["ruleEra"], 0) + 1
    receipt = {
        "contract": "joshi.jupiter_backfill.receipt.v1",
        "authority": "read_only_no_execution",
        "stamp": stamp,
        "generatedUnix": now_unix,
        "requestBudget": budget.limit,
        "requestsSpent": budget.spent,
        "requestsByStage": budget.by_stage,
        "paceSeconds": args.pace,
        "spansDays": spans,
        "roundsByHorizon": by_horizon,
        "windowStartRange": {
            h: [
                min((r["windowStartUnix"] for r in ordered if r["horizon"] == h),
                    default=None),
                max((r["windowStartUnix"] for r in ordered if r["horizon"] == h),
                    default=None),
            ]
            for h in SERIES
        },
        "gridReconcile": reconcile,
        "tradesFetched": sum(1 for r in ordered if r["trades"]["fetched"]),
        "tradesTruncatedRounds": sum(1 for r in ordered if r["trades"]["truncated"]),
        "thinRounds": len(thin),
        "historyFetched": sum(1 for r in ordered if r["priceHistory"]["fetched"]),
        "settlementLabelSources": label_sources,
        "ruleEras": eras,
        "gapCount": len(f.gaps),
        "gaps": f.gaps[:200],
        "caveats": [
            "trades are fills: realistic transacted prices, never guaranteed fillable size",
            "all prices/timestamps are provider claims in their declared units",
            "enumeration covers gamma closed=true rounds only; stuck-open rounds absent",
            "nothing here is settlement-exact; the census inherits ~2bp reference basis",
        ],
    }
    (args.out / f"backfill-{stamp}.receipt.json").write_text(json.dumps(receipt, indent=1))
    print(json.dumps({k: receipt[k] for k in
                      ("requestsSpent", "roundsByHorizon", "settlementLabelSources",
                       "ruleEras", "gapCount")}, indent=1), flush=True)
    print(f"rounds -> {rounds_path}", flush=True)


if __name__ == "__main__":
    main()
