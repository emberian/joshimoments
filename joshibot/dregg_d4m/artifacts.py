"""Versioned artifacts under ``state/dregg_d4m/``, for the visualisation lane to consume.

Every analysis writes PARQUET tables plus one JSON manifest per run. The manifest is the
contract: it names the schema version, the seed, the matrices' provenance (including their
window stamps), the row counts, and the null parameters. A renderer that reads a table
without reading the manifest is rendering a picture with no date on it.

Layout::

    state/dregg_d4m/
      <analysis>-v<SCHEMA>-<YYYYMMDD>.parquet      one per table
      manifest-<YYYYMMDD>.json                     every table written that day
      current.json                                 symlink to the newest manifest

Symlink swap is atomic (write ``.tmp``, ``os.replace``), the same discipline
``dregg_screen.ledger`` uses for ``current.sqlite``, so a reader never sees a half-written
pointer.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "state" / "dregg_d4m"

#: Bump when a column's MEANING changes. New columns append without a bump.
SCHEMA_VERSION = 1


@dataclass
class Run:
    """One analysis run: tables written plus the manifest that explains them."""

    analysis: str
    out_dir: Path = OUT_DIR
    stamp: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y%m%d"))
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def path_for(self, table: str) -> Path:
        return self.out_dir / f"{self.analysis}_{table}-v{SCHEMA_VERSION}-{self.stamp}.parquet"

    def write_table(self, table: str, frame: Any, *, columns: dict[str, str]) -> Path:
        """Write one table and register its column dictionary in the manifest.

        ``columns`` is required, not optional: a table whose columns are not documented is
        not an artifact, it is a dump."""

        missing = set(frame.columns) - set(columns)
        if missing:
            raise ValueError(f"{table}: undocumented columns {sorted(missing)}")
        path = self.path_for(table)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        self.tables[table] = {
            "path": path.name,
            "rows": len(frame),
            "columns": columns,
        }
        return path

    def finish(self, *, provenance: list[dict[str, Any]], params: dict[str, Any]) -> Path:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "analysis": self.analysis,
            "stamp": self.stamp,
            "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "registration": "studies/REGISTRATION_d4m.md",
            "matrices": provenance,
            "params": params,
            "tables": self.tables,
            "results": self.meta,
        }
        path = self.out_dir / f"manifest_{self.analysis}-{self.stamp}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, default=str))
        _swap_current(self.out_dir, path)
        return path


def _swap_current(out_dir: Path, target: Path) -> None:
    link = out_dir / "current.json"
    tmp = out_dir / ".current.tmp"
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(target.name)
    os.replace(tmp, link)
