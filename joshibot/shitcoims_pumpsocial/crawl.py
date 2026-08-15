"""The two crawls the operator asked for: comment threads, and the follower network.

WHAT A CRAWL OWES ITS READER
----------------------------
Every crawl here returns a `CrawlReport` alongside its rows, and the report is the part
that makes the rows usable. It records what was asked for, what came back, what was
quarantined and why, and — the field that matters most — whether the crawl STOPPED
BECAUSE IT RAN OUT OF DATA or because it hit its own cap. `studies/quality_callers.py`
splits a census slice rather than accept a capped one for exactly this reason; the same
discipline applies to a paginated crawl, where a silent cap turns "this coin has 40
comments" into a fact when it is really "we asked for 40".

The tape disciplines apply unchanged: two clocks on every row, censoring recorded as data,
"no data" never rendered as zero.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from .client import NotFound, PumpSocialClient, PumpSocialError
from .models import (
    FollowEdge,
    NativeCallout,
    Post,
    Profile,
    Quarantined,
    parse_callout,
    parse_callout_stats,
    parse_follow_edge,
    parse_native_callout,
    parse_post,
    parse_profile,
)

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "state" / "pumpsocial"


@dataclass(slots=True)
class CrawlReport:
    """What the crawl did, including what it could not do."""

    kind: str
    roots: list[str] = field(default_factory=list)
    t_start: str = ""
    t_end: str = ""
    pages: int = 0
    rows: int = 0
    quarantined: dict[str, int] = field(default_factory=dict)
    #: Roots whose fetch 404'd — an ANSWER (no community, no follows), not an error.
    absent: list[str] = field(default_factory=list)
    #: Roots whose fetch errored. These are holes in the sample and are named.
    failed: dict[str, str] = field(default_factory=dict)
    #: True if any listing stopped at `max_pages` rather than at the end of the data.
    truncated: list[str] = field(default_factory=list)
    requests: int = 0
    #: Replies the API COUNTS but will not serve publicly (comment replies; see
    #: `endpoints.message_replies_public`). Censoring as data: the tail is known to exist
    #: and known to be missing, which is a different fact from a thread having no replies.
    censored_replies: int = 0

    def note_quarantine(self, reason: str) -> None:
        self.quarantined[reason] = self.quarantined.get(reason, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "roots": self.roots,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "pages": self.pages,
            "rows": self.rows,
            "quarantined": self.quarantined,
            "absent": self.absent,
            "failed": self.failed,
            "truncated": self.truncated,
            "requests": self.requests,
            "censored_replies": self.censored_replies,
            "complete": not self.truncated and not self.failed,
        }

    def line(self) -> str:
        state = "COMPLETE" if not self.truncated and not self.failed else "PARTIAL"
        censored = f", {self.censored_replies} replies censored" if self.censored_replies else ""
        return (
            f"{self.kind}: {self.rows} rows over {self.pages} pages from "
            f"{len(self.roots)} roots [{state}] — {sum(self.quarantined.values())} quarantined, "
            f"{len(self.absent)} absent, {len(self.failed)} failed{censored}"
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# comment threads
# ---------------------------------------------------------------------------


def _paginate(
    fetch: Any, *, max_pages: int, label: str, report: CrawlReport, page_size: int
) -> Iterator[tuple[list[dict[str, Any]], str]]:
    """Walk a cursor-paginated listing, recording truncation rather than hiding it.

    Three stop conditions, and only one of them is completion:

    * a SHORT page (fewer rows than asked for) means the data ran out — complete;
    * `max_pages`, or a repeating cursor, is truncation and is named in `report`;
    * a FULL page with NO cursor is truncation too, and it is the one worth explaining.
      `messages_public` caps at 50 rows regardless of `limit`, returns `{"messages": [...]}`
      with no cursor field of any spelling, and so looks exactly like a completed listing —
      on a coin whose own `postCount` said 176 this crawler first reported 59 rows and
      called them COMPLETE. A listing that hands back precisely as many rows as you asked
      for has told you nothing about whether more exist, and recording that as completion
      is how a partial sample becomes a confident total.
    """

    cursor: str | None = None
    seen_cursors: set[str] = set()
    for page in range(max_pages):
        rows, next_cursor, prov = fetch(cursor)
        report.pages += 1
        yield rows, prov.t_ingest
        if not next_cursor:
            if len(rows) >= page_size:
                report.truncated.append(f"{label}:full_page_no_cursor@page{page}")
            return
        if not rows:
            return
        if next_cursor in seen_cursors:
            # A cursor that repeats means the server is looping us; stop and say so.
            report.truncated.append(f"{label}:cursor_loop@page{page}")
            return
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    report.truncated.append(f"{label}:max_pages")


def crawl_thread(
    client: PumpSocialClient,
    mint: str,
    *,
    include_replies: bool = True,
    include_callouts: bool = True,
    limit: int = 50,
    max_pages: int = 20,
    report: CrawlReport | None = None,
) -> tuple[list[Post], CrawlReport]:
    """Every comment and callout on one coin, plus whatever reply tail is readable.

    The reply tail is ASYMMETRIC and the asymmetry is the API's, not ours: callout
    replies are public, comment replies are a measured 404 (see
    `endpoints.message_replies_public`). So replies are FETCHED under callouts and
    COUNTED under comments, and the uncollectable half lands in `report.censored_replies`
    rather than vanishing — a thread that looks short because the API would not serve its
    replies is a different fact from a thread with no replies.

    Parents are selected on `reply_count != 0`, a tri-state read: a count that is ABSENT
    is unknown and gets asked about, while a measured zero is skipped. Collapsing those
    two is how a crawl quietly loses the replies on every post the API declined to count.
    """

    report = report or CrawlReport(kind="thread", t_start=_now())
    if mint not in report.roots:
        report.roots.append(mint)
    posts: list[Post] = []

    def collect(rows: Iterable[dict[str, Any]], t_ingest: str, kind: str) -> list[Post]:
        out: list[Post] = []
        for row in rows:
            try:
                parsed = (
                    parse_callout(row, t_ingest=t_ingest, mint=mint)
                    if kind == "callout"
                    else parse_post(row, kind=kind, t_ingest=t_ingest, mint=mint)
                )
            except Quarantined as exc:
                report.note_quarantine(str(exc))
                continue
            out.append(parsed)
        return out

    try:
        for rows, t_ingest in _paginate(
            lambda c: client.messages(mint, limit=limit, cursor=c),
            max_pages=max_pages,
            label=f"messages:{mint}",
            report=report,
            page_size=limit,
        ):
            posts.extend(collect(rows, t_ingest, "message"))
    except NotFound:
        report.absent.append(f"messages:{mint}")
    except PumpSocialError as exc:
        report.failed[f"messages:{mint}"] = str(exc)

    if include_callouts:
        try:
            for rows, t_ingest in _paginate(
                lambda c: client.callouts(mint, limit=limit, cursor=c),
                max_pages=max_pages,
                label=f"callouts:{mint}",
                report=report,
                page_size=limit,
            ):
                posts.extend(collect(rows, t_ingest, "callout"))
        except NotFound:
            report.absent.append(f"callouts:{mint}")
        except PumpSocialError as exc:
            report.failed[f"callouts:{mint}"] = str(exc)

    if include_replies:
        # Callout replies ARE publicly readable; comment replies are NOT (the route is a
        # measured 404 — see endpoints.message_replies_public). So the reply tail is
        # fetched where it exists and COUNTED where it does not, which keeps the censoring
        # visible instead of letting a thread look shorter than it is.
        for parent in [p for p in list(posts) if p.kind == "callout" and p.reply_count != 0]:
            try:
                for rows, t_ingest in _paginate(
                    lambda c, pid=parent.post_id: client.callout_replies(
                        mint, pid, limit=limit, cursor=c
                    ),
                    max_pages=max_pages,
                    label=f"callout_replies:{parent.post_id}",
                    report=report,
                    page_size=limit,
                ):
                    posts.extend(collect(rows, t_ingest, "message"))
            except NotFound:
                report.absent.append(f"callout_replies:{parent.post_id}")
            except PumpSocialError as exc:
                report.failed[f"callout_replies:{parent.post_id}"] = str(exc)

    # The unreadable half, stated as a number rather than left as a gap in the rows.
    report.censored_replies = sum(
        p.reply_count or 0 for p in posts if p.kind == "message" and p.reply_count
    )
    report.rows = len(posts)
    report.t_end = _now()
    report.requests = client.stats.requests
    return posts, report


def crawl_recent_callouts(
    client: PumpSocialClient,
    *,
    limit: int = 50,
    max_pages: int = 20,
    since_ms: int | None = None,
) -> tuple[list[NativeCallout], CrawlReport]:
    """Walk pump's live callout firehose backwards from now.

    `since_ms` stops the walk once the feed is older than a wall-clock bound, which is
    how this becomes a repeatable incremental collector rather than a one-shot scrape:
    run it on a timer with `since_ms` set to the last run's high-water mark and the pages
    fetched are proportional to elapsed activity. The cursor is a KEYSET token
    (`{score, member}` over `<wallet>|<ms>|<calloutId>`), so unlike an offset it does not
    skip or duplicate rows when new callouts land mid-walk.
    """

    report = CrawlReport(kind="recent_callouts", t_start=_now(), roots=["/callout/recent"])
    out: list[NativeCallout] = []
    token: str | None = None
    for page in range(max_pages):
        try:
            rows, token, prov = client.recent_callouts(limit=limit, page_token=token)
        except PumpSocialError as exc:
            report.failed[f"page{page}"] = str(exc)
            break
        report.pages += 1
        oldest: int | None = None
        for row in rows:
            created = row.get("createdAt")
            if isinstance(created, int):
                oldest = created if oldest is None else min(oldest, created)
            try:
                out.append(parse_native_callout(row, t_ingest=prov.t_ingest))
            except Quarantined as exc:
                report.note_quarantine(str(exc))
        if since_ms is not None and oldest is not None and oldest < since_ms:
            break
        if not token:
            if len(rows) >= limit:
                report.truncated.append(f"recent:full_page_no_token@page{page}")
            break
        if page == max_pages - 1:
            report.truncated.append("recent:max_pages")
    report.rows = len(out)
    report.t_end = _now()
    report.requests = client.stats.requests
    return out, report


# ---------------------------------------------------------------------------
# the follower network
# ---------------------------------------------------------------------------


def crawl_follow_graph(
    client: PumpSocialClient,
    roots: list[str],
    *,
    depth: int = 1,
    page_size: int = 100,
    max_pages: int = 20,
    max_nodes: int = 500,
    report: CrawlReport | None = None,
) -> tuple[list[FollowEdge], CrawlReport]:
    """Breadth-first over `/following`, out-edges only, with follow timestamps.

    THE SHAPE OF THIS GRAPH IS NOT SYMMETRIC AND THAT IS A FINDING, NOT A LIMITATION TO
    WORK AROUND. pump exposes who a wallet FOLLOWS, never who follows it, so the crawl
    can only ever go forwards. A wallet's follower COUNT is available from its profile,
    so `followers(X)` is knowable as a number while `{w : w follows X}` is knowable only
    by crawling everyone — i.e. in-edges are discovered incidentally, as a by-product of
    whoever you happened to expand. Any analysis over in-degree here is over a SAMPLE
    whose inclusion probability depends on the roots, and must say so.

    `max_nodes` is a hard budget. The frontier is expanded in the order discovered, and
    whatever is left unexpanded when the budget runs out is recorded in `truncated` —
    a partial BFS that does not say it is partial is a graph with invented absences.
    """

    report = report or CrawlReport(kind="follow_graph", t_start=_now())
    report.roots.extend(r for r in roots if r not in report.roots)
    edges: list[FollowEdge] = []
    seen: set[str] = set()
    frontier: list[tuple[str, int]] = [(r, 0) for r in roots]

    while frontier:
        wallet, level = frontier.pop(0)
        if wallet in seen:
            continue
        if len(seen) >= max_nodes:
            report.truncated.append(f"max_nodes:{len(frontier) + 1}_unexpanded")
            break
        seen.add(wallet)
        offset = 0
        try:
            for page in range(max_pages):
                rows, prov = client.following(wallet, limit=page_size, offset=offset)
                report.pages += 1
                for row in rows:
                    try:
                        edge = parse_follow_edge(row, follower=wallet, t_ingest=prov.t_ingest)
                    except Quarantined as exc:
                        report.note_quarantine(str(exc))
                        continue
                    edges.append(edge)
                    if level + 1 <= depth and edge.followee not in seen:
                        frontier.append((edge.followee, level + 1))
                if len(rows) < page_size:
                    break
                offset += page_size
                if page == max_pages - 1:
                    report.truncated.append(f"following:{wallet}:max_pages")
        except NotFound:
            report.absent.append(f"following:{wallet}")
        except PumpSocialError as exc:
            report.failed[f"following:{wallet}"] = str(exc)

    report.rows = len(edges)
    report.t_end = _now()
    report.requests = client.stats.requests
    return edges, report


# ---------------------------------------------------------------------------
# identity: the both-backends join
# ---------------------------------------------------------------------------


def resolve_wallets(
    client: PumpSocialClient, wallets: list[str], *, batch_size: int = 50
) -> tuple[dict[str, dict[str, Any]], CrawlReport]:
    """wallet -> {user_id, twitter_id, username} for a whole set, in batches.

    The batch route reports a per-address `status`, so a wallet with no pump identity
    comes back as a MISS rather than being dropped from the map. That distinction is the
    whole point: "this trader has no pump profile" and "we failed to ask" are different
    facts and the caller can tell them apart.
    """

    report = CrawlReport(kind="resolve_wallets", t_start=_now(), roots=list(wallets))
    resolved: dict[str, dict[str, Any]] = {}
    for start in range(0, len(wallets), batch_size):
        chunk = wallets[start : start + batch_size]
        try:
            results, prov = client.users_by_wallet(chunk)
        except PumpSocialError as exc:
            report.failed[f"batch@{start}"] = str(exc)
            continue
        report.pages += 1
        for wallet in chunk:
            entry = results.get(wallet)
            if not isinstance(entry, dict) or entry.get("status") != "ok":
                resolved[wallet] = {"status": "miss", "t_ingest": prov.t_ingest}
                continue
            resolved[wallet] = {
                "status": "ok",
                "user_id": entry.get("user_id"),
                "twitter_id": entry.get("twitter_id"),
                "username": entry.get("username"),
                "t_ingest": prov.t_ingest,
            }
    report.rows = sum(1 for v in resolved.values() if v.get("status") == "ok")
    report.t_end = _now()
    report.requests = client.stats.requests
    return resolved, report


def full_profile(client: PumpSocialClient, wallet: str) -> Profile:
    """A profile assembled from BOTH backends, with each side allowed to be absent."""

    v3, prov = client.profile(wallet)
    cc_user: dict[str, Any] = {}
    cc_profile: dict[str, Any] = {}
    try:
        results, _ = client.users_by_wallet([wallet])
        entry = results.get(wallet)
        if isinstance(entry, dict) and entry.get("status") == "ok":
            cc_user = entry
            user_id = entry.get("user_id")
            if isinstance(user_id, str):
                data, _ = client.request("user_profile", path_params={"user_id": user_id})
                if isinstance(data, dict):
                    cc_profile = data
    except PumpSocialError:
        pass  # the v3 half is still a real profile; the cc fields stay None, not zero
    return parse_profile(v3, t_ingest=prov.t_ingest, cc_user=cc_user, cc_profile=cc_profile)


def caller_scorecard(client: PumpSocialClient, wallet: str) -> dict[str, Any] | None:
    """pump's own callout scoreboard for a wallet, or None if it has none."""

    try:
        data, prov = client.wallet_callout_stats(wallet)
    except NotFound:
        return None
    if not data:
        return None
    return parse_callout_stats(data, wallet=wallet, t_ingest=prov.t_ingest).as_dict()


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------


def write_jsonl(path: Path, rows: Iterable[Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w") as handle:
        for row in rows:
            payload = row.as_dict() if hasattr(row, "as_dict") else row
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
            count += 1
    return count


def write_report(path: Path, report: CrawlReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), indent=1) + "\n")
