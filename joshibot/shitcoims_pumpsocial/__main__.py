"""CLI. Every subcommand writes to `state/pumpsocial/` and prints what it could not do."""

from __future__ import annotations

import argparse
import json

from .client import PumpSocialClient
from .crawl import (
    OUT,
    caller_scorecard,
    crawl_follow_graph,
    crawl_recent_callouts,
    crawl_thread,
    full_profile,
    resolve_wallets,
    write_jsonl,
    write_report,
)
from .endpoints import ENDPOINTS
from .probe import probe_all


def cmd_probe(args: argparse.Namespace) -> int:
    summary = probe_all()
    print(
        f"{summary['endpoints']} endpoints: {summary['live']} live, {summary['dead']} dead, "
        f"{summary['auth_walled']} auth-walled, {summary['refused_mutating']} refused "
        f"(mutating), {summary['errors']} errors"
    )
    if summary["drifted"]:
        print(f"DRIFT vs catalogue: {', '.join(summary['drifted'])}")
    else:
        print("no drift vs catalogue")
    print(f"-> {OUT / 'surface.json'}  ({summary['stats']})")
    return 0


def cmd_catalogue(args: argparse.Namespace) -> int:
    for spec in ENDPOINTS:
        flag = "MUT" if spec.mutating else "   "
        print(f"{flag} {spec.verdict:<12} {spec.auth:<14} {spec.method:<6} {spec.host}{spec.path}")
    return 0


def cmd_thread(args: argparse.Namespace) -> int:
    client = PumpSocialClient()
    posts, report = crawl_thread(
        client, args.mint, limit=args.limit, max_pages=args.max_pages,
        include_replies=not args.no_replies,
    )
    path = OUT / "threads" / f"{args.mint}.jsonl"
    write_jsonl(path, posts)
    write_report(path.with_suffix(".report.json"), report)
    print(report.line())
    authors = {p.author.wallet for p in posts}
    with_x = {p.author.wallet for p in posts if p.author.twitter_id}
    print(f"  {len(authors)} distinct author wallets, {len(with_x)} with a linked X id")
    print(f"-> {path}")
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    client = PumpSocialClient()
    edges, report = crawl_follow_graph(
        client, args.wallets, depth=args.depth, max_nodes=args.max_nodes
    )
    path = OUT / "graph" / f"{args.wallets[0][:8]}-d{args.depth}.jsonl"
    write_jsonl(path, edges)
    write_report(path.with_suffix(".report.json"), report)
    print(report.line())
    print(f"  {len({e.followee for e in edges})} distinct followees")
    print(f"-> {path}")
    return 0


def cmd_firehose(args: argparse.Namespace) -> int:
    client = PumpSocialClient()
    callouts, report = crawl_recent_callouts(client, limit=args.limit, max_pages=args.max_pages)
    path = OUT / "callouts_recent.jsonl"
    write_jsonl(path, callouts)
    write_report(path.with_suffix(".report.json"), report)
    print(report.line())
    wallets = {c.caller_wallet for c in callouts}
    mints = {c.mint for c in callouts}
    theses = [c.thesis for c in callouts if c.thesis]
    print(f"  {len(wallets)} distinct caller wallets, {len(mints)} distinct mints")
    if theses:
        print(f"  {len(set(theses))} distinct theses of {len(theses)} — "
              f"{100 * (1 - len(set(theses)) / len(theses)):.0f}% duplicated text")
    print(f"-> {path}")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    client = PumpSocialClient()
    profile = full_profile(client, args.wallet)
    print(json.dumps(profile.as_dict(), indent=1))
    return 0


def cmd_callers(args: argparse.Namespace) -> int:
    client = PumpSocialClient()
    rows = []
    for wallet in args.wallets:
        stats = caller_scorecard(client, wallet)
        if stats is None:
            print(f"{wallet[:8]}..  no callout record")
            continue
        rows.append(stats)
        if not stats["rates_are_defined"]:
            # n=0 with rates of 0.0 is the source rendering no-data as zero. Say so.
            print(f"{wallet[:8]}..  n=0 — UNRATED (the API's 0.0% here means no data, not 0%)")
            continue
        print(
            f"{wallet[:8]}..  n={stats['total_callouts']:<3}  "
            f"2x={stats['two_x_percent']:.0f}%  "
            f"median_peak={stats['median_multiple']:.2f}x  t_peak="
            f"{(stats['average_time_to_peak_s'] or 0) / 86400:.0f}d"
        )
    if rows:
        path = OUT / "callers.jsonl"
        write_jsonl(path, rows)
        print(f"-> {path}")
    print("NOTE: these are PEAK-at-any-later-time statistics, not returns. See models.Callout.")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    client = PumpSocialClient()
    resolved, report = resolve_wallets(client, args.wallets)
    print(json.dumps(resolved, indent=1))
    print(report.line())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="shitcoims_pumpsocial", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="re-measure every catalogued endpoint").set_defaults(fn=cmd_probe)
    sub.add_parser("catalogue", help="print the endpoint map").set_defaults(fn=cmd_catalogue)

    p = sub.add_parser("thread", help="comments + callouts on one coin")
    p.add_argument("mint")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--max-pages", type=int, default=20)
    p.add_argument("--no-replies", action="store_true")
    p.set_defaults(fn=cmd_thread)

    p = sub.add_parser("graph", help="BFS the follow graph from one or more wallets")
    p.add_argument("wallets", nargs="+")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--max-nodes", type=int, default=200)
    p.set_defaults(fn=cmd_graph)

    p = sub.add_parser("firehose", help="pump's live callout feed (/callout/recent)")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--max-pages", type=int, default=10)
    p.set_defaults(fn=cmd_firehose)

    p = sub.add_parser("profile", help="a wallet's identity across both backends")
    p.add_argument("wallet")
    p.set_defaults(fn=cmd_profile)

    p = sub.add_parser("callers", help="pump's own callout scoreboard for wallets")
    p.add_argument("wallets", nargs="+")
    p.set_defaults(fn=cmd_callers)

    p = sub.add_parser("resolve", help="wallets -> pump identities, batched")
    p.add_argument("wallets", nargs="+")
    p.set_defaults(fn=cmd_resolve)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
