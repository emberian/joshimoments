"""Run the leg-in first-pass estimand over backfilled rounds and write the study JSON.

    cd analysis && uv run --offline python -m joshi_analysis.jupiter_backfill \
        --rounds ~/dev/joshi/state/prediction/backfill/backfill-*-rounds.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import legin, reads


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=Path, nargs="+", required=True)
    ap.add_argument(
        "--out-dir", type=Path, default=Path("~/dev/joshi/state/prediction/study")
    )
    args = ap.parse_args()

    rounds: dict[str, dict] = {}
    for path in args.rounds:
        for rec in reads.load_rounds(path):
            rounds[rec["roundKey"]] = rec  # later files win on duplicate keys
    per_round = [legin.leg_in_round(rec) for rec in rounds.values()]
    summary = legin.summarize(per_round)
    summary["inputFiles"] = [str(p) for p in args.rounds]
    summary["roundsIn"] = len(rounds)

    stamp = reads.utc_stamp()
    out = args.out_dir / f"backfill-legin-{stamp}.json"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "perRound": per_round}, indent=1))
    print(json.dumps(summary, indent=1))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
