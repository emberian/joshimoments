"""Render the public shitcoims site from live data into an output directory.

    uv run python -m dregg_site.build \\
        --scores-dir /home/hbox/dregg-data/screen/scores \\
        --archive-db /home/hbox/dregg-data/archive/archive.sqlite \\
        --wire-dir   /home/hbox/dregg-data/wire \\
        --out        /path/to/www/shitcoims [--day YYYY-MM-DD]

Writes index.html, screen.html, record.html, research.html, and wire/ (index plus one
page per published wire artifact). It writes ONLY those names — never touches sign/
or anything else already in the out dir, and refuses an --out that would.

Deterministic: the only clock is the ``--day`` default (today UTC, same as the wire),
and the "data through" stamp is derived from the DATA's own timestamps, not from now.
Same inputs and day, same bytes.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from dregg_site import pages, record
from dregg_wire.facts import build_facts, load_scores

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OWNED = ("index.html", "screen.html", "record.html", "research.html")


# -- inputs ----------------------------------------------------------------------------


def wire_entries(wire_dir: Path) -> list[dict]:
    """Published wire artifacts, newest first. Days the operator SKIPPED stay out."""

    if not wire_dir.is_dir():
        return []
    skipped: set[str] = set()
    state_path = wire_dir / "wire_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            skipped = {day for day, entry in state.items() if entry.get("status") == "skipped"}
        except (json.JSONDecodeError, AttributeError):
            skipped = set()
    entries = []
    for path in sorted(wire_dir.glob("*.md"), reverse=True):
        day = path.stem
        if not DAY_RE.match(day) or day in skipped:
            continue
        markdown = path.read_text()
        lede = None
        for line in markdown.splitlines():
            line = line.strip()
            if line.startswith("*") and line.endswith("*") and len(line) > 2:
                lede = line.strip("*")
                break
        entries.append({"day": day, "markdown": markdown, "lede": lede})
    return entries


def data_through(rows: list[dict], archive_db: Path, day: str) -> str | None:
    """The freshest timestamp IN the data — the honest as-of, independent of run time."""

    candidates: list[str] = []
    for row in rows:
        scored = row.get("t_scored")
        if isinstance(scored, str):
            candidates.append(scored)
    if archive_db.exists():
        try:
            db = sqlite3.connect(f"file:{archive_db}?mode=ro", uri=True, timeout=5.0)
            try:
                (t_max,) = db.execute("SELECT max(t_response_ms) FROM fetches").fetchone()
            finally:
                db.close()
            if t_max:
                candidates.append(datetime.fromtimestamp(t_max / 1000.0, UTC).isoformat())
        except sqlite3.Error:
            pass
    if not candidates:
        return None
    latest = max(candidates)
    try:
        return datetime.fromisoformat(latest).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return None


# -- output ----------------------------------------------------------------------------


def _write(out_dir: Path, rel: str, text: str) -> Path:
    path = out_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def generate(
    *,
    day: str,
    scores_dir: Path,
    archive_db: Path,
    wire_dir: Path,
    out_dir: Path,
    wallet_parquet: Path | None = None,
    manifest_dir: Path | None = None,
) -> dict:
    if (out_dir / "index.html").resolve().is_relative_to((out_dir / "sign").resolve()):
        raise SystemExit("refusing: out dir resolves under sign/")  # pragma: no cover — belt
    if out_dir.name == "sign":
        raise SystemExit("refusing to generate into a sign/ directory — that page is not ours")

    rows = load_scores(scores_dir, day)
    facts = build_facts(
        day,
        scores_dir=scores_dir,
        archive_db=archive_db,
        wallet_parquet=wallet_parquet,
        manifest_dir=manifest_dir,
    )
    rec = record.collect(archive_db)
    wires = wire_entries(wire_dir)
    through = data_through(rows, archive_db, day)
    latest_wire = f"wire/{wires[0]['day']}.html" if wires else None

    written = [
        _write(out_dir, "index.html", pages.page_index(facts, rec, through, latest_wire)),
        _write(out_dir, "screen.html", pages.page_screen(facts, rows, through)),
        _write(out_dir, "record.html", pages.page_record(rec, facts, through)),
        _write(out_dir, "research.html", pages.page_research(through, day)),
        _write(out_dir, "wire/index.html", pages.page_wire_index(wires, day, through)),
    ]
    written += [
        _write(out_dir, f"wire/{w['day']}.html", pages.page_wire_day(w["day"], w["markdown"]))
        for w in wires
    ]
    return {
        "day": day,
        "out": str(out_dir),
        "pages": [str(p.relative_to(out_dir)) for p in written],
        "wires": [w["day"] for w in wires],
        "data_through": through,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dregg_site.build", description=__doc__)
    parser.add_argument("--scores-dir", type=Path, default=Path("state/dregg_screen/scores"))
    parser.add_argument("--archive-db", type=Path, default=Path("state/dregg_archive/smoke/archive.sqlite"))
    parser.add_argument("--wire-dir", type=Path, default=Path("state/dregg_wire"))
    parser.add_argument("--wallet-parquet", type=Path, default=None)
    parser.add_argument("--manifest-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--day", default=None, help="UTC day (default: today)")
    args = parser.parse_args(argv)

    day = args.day or datetime.now(UTC).strftime("%Y-%m-%d")
    if not DAY_RE.match(day):
        parser.error(f"--day must be YYYY-MM-DD, got {day!r}")
    manifest = generate(
        day=day,
        scores_dir=args.scores_dir,
        archive_db=args.archive_db,
        wire_dir=args.wire_dir,
        out_dir=args.out,
        wallet_parquet=args.wallet_parquet,
        manifest_dir=args.manifest_dir,
    )
    print(json.dumps(manifest, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
