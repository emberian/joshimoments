"""Daily manifests: the archive's hashes, shaped for anchoring in a public git repo.

A private archive can prove nothing about WHEN it knew something — a claim that "this
callout existed and here are the bytes" is only as strong as the archive's own honesty
about not back-dating. The manifest is the fix: once a day, every retained fetch's sha256
is rolled into one file whose own hash, committed to a public repo (the commit is ops,
not this module), timestamps the whole day's evidence externally. From then on,
fabricating or altering a body means breaking a hash that left the building.

Each file carries the per-fetch lines (id, route, sha256, uncompressed byte count) plus a
rollup — sha256 over the newline-joined `id:sha256:bytes` lines, scheme named in the file
so a verifier needs no out-of-band knowledge. Only COMPLETED days are manifested: today's
file would be a moving target, and a manifest that changes after publication is worse
than none.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .store import Store, day_end_ms, day_start_ms

ROLLUP_SCHEME = "sha256(id:sha256:bytes lines, \\n-joined)-v1"


def build(store: Store, day: str) -> dict:
    rows = store.db.execute(
        "SELECT id, route, sha256, body_zst FROM fetches"
        " WHERE t_response_ms >= ? AND t_response_ms < ? ORDER BY id",
        (day_start_ms(day), day_end_ms(day)),
    ).fetchall()
    entries = []
    total = 0
    for fetch_id, route, sha, body_zst in rows:
        size = len(store.decompress(body_zst))
        total += size
        entries.append({"id": int(fetch_id), "route": route, "sha256": sha, "bytes": size})
    lines = "\n".join(f"{e['id']}:{e['sha256']}:{e['bytes']}" for e in entries)
    return {
        "date": day,
        "fetch_count": len(entries),
        "total_bytes": total,
        "rollup_scheme": ROLLUP_SCHEME,
        "rollup_sha256": hashlib.sha256(lines.encode()).hexdigest(),
        "fetches": entries,
    }


def write_pending(store: Store, out_dir: Path, *, today: str) -> list[Path]:
    """Write a manifest for every completed day that has fetches and no manifest yet.

    Idempotent by file existence, so a re-run neither rewrites published history nor
    needs bookkeeping beyond the directory itself.
    """

    days = [
        r[0]
        for r in store.db.execute(
            "SELECT DISTINCT strftime('%Y-%m-%d', t_response_ms / 1000, 'unixepoch')"
            " FROM fetches ORDER BY 1"
        ).fetchall()
        if r[0] and r[0] < today
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for day in days:
        path = out_dir / f"{day}.json"
        if path.exists():
            continue
        payload = build(store, day)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=1) + "\n")
        tmp.rename(path)
        written.append(path)
    return written
