"""The analyst's bench: bounded, read-only analysis over durable catalogs.

Every method here opens sqlite strictly `mode=ro` (never the writer lock, safe
against the live keeper), reads bounded rows, and reports provenance with every
number: which catalog, which observation, whose clock. Nothing here writes
anything anywhere — conclusions travel back through the engine and become
durable only via the journal lane (append_note), never here.

The signature-volatility computation is `analysis/src/joshi_analysis/signature.py`
loaded by file path (it is dependency-free; loading the package would pull
duckdb, which the resident deliberately does not carry). The definition it
implements is P2 in docs/microstructure/trades_quotes_prices/FORMAL_MODEL.md.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from resident_tools import ToolError

# One retained response body is plenty for a turn; anything bigger is refused
# with its actual size stated, never truncated silently.
MAX_BLOB_BYTES = 8_000_000
SQLITE_TIMEOUT_S = 2.0


def _load_signature_module(repo_root: Path):
    path = Path(repo_root) / "analysis" / "src" / "joshi_analysis" / "signature.py"
    if not path.is_file():
        raise ToolError(f"signature module not found at {path}")
    spec = importlib.util.spec_from_file_location("joshi_resident_signature", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=SQLITE_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    return conn


class AnalysisTools:
    """Read-only analysis over the named catalogs the config points at."""

    def __init__(self, repo_root: Path, catalogs: dict[str, Path]):
        self.repo_root = Path(repo_root)
        self.catalogs = {name: Path(p) for name, p in catalogs.items()}
        self._signature = None

    def _catalog_path(self, name: str) -> Path:
        if name not in self.catalogs:
            known = ", ".join(sorted(self.catalogs)) or "none configured"
            raise ToolError(f"unknown catalog {name!r}; configured catalogs: {known}")
        path = self.catalogs[name]
        if not path.is_file():
            raise ToolError(f"catalog {name!r} configured at {path} but no file is there")
        return path

    def _signature_module(self):
        if self._signature is None:
            self._signature = _load_signature_module(self.repo_root)
        return self._signature

    # ------------------------------------------------------------------
    # list_catalogs
    # ------------------------------------------------------------------
    def list_catalogs(self) -> str:
        """Which durable catalogs the analyst can read, and whether they exist."""
        out = []
        for name, path in sorted(self.catalogs.items()):
            entry = {"catalog": name, "path": str(path), "exists": path.is_file()}
            if entry["exists"]:
                entry["bytes"] = path.stat().st_size
            out.append(entry)
        return json.dumps({
            "catalogs": out,
            "note": "all access is sqlite mode=ro; nothing here can write",
        }, indent=1)

    # ------------------------------------------------------------------
    # catalog_census
    # ------------------------------------------------------------------
    def catalog_census(self, catalog: str) -> str:
        """Bounded counts for one catalog: what is retained, and how fresh.

        Counts are exact; the mint list is the newest 20 identified mints, and
        says so — it is a window, never the census of all mints.
        """
        path = self._catalog_path(catalog)
        conn = _open_ro(path)
        try:
            def one(sql: str, *args) -> int:
                return int(conn.execute(sql, args).fetchone()[0])

            census = {
                "catalog": catalog,
                "path": str(path),
                "commands": one("SELECT count(*) FROM command"),
                "scenes": one("SELECT count(*) FROM scene"),
                "observations": one("SELECT count(*) FROM observation"),
                "acquisitions": one("SELECT count(*) FROM acquisition"),
                "sourceEvents": one("SELECT count(*) FROM source_event"),
            }
            newest = conn.execute(
                "SELECT observation_id, received_wall_us FROM observation"
                " ORDER BY commit_seq DESC LIMIT 1").fetchone()
            if newest is not None:
                census["newestObservation"] = {
                    "observationId": newest["observation_id"],
                    "receivedWallUs": int(newest["received_wall_us"]),
                }
            else:
                census["newestObservation"] = None
            mints = conn.execute(
                "SELECT natural_key, identified_commit_seq FROM source_event"
                " WHERE event_namespace = 'solana.token_mint'"
                " ORDER BY identified_commit_seq DESC LIMIT 20").fetchall()
            census["newestMints"] = [
                {"mint": r["natural_key"],
                 "identifiedCommitSeq": int(r["identified_commit_seq"])}
                for r in mints
            ]
            census["newestMintsNote"] = (
                "a 20-row window of the newest identified mints, not a census "
                "of all mints this catalog knows")
            return json.dumps(census, indent=1)
        except sqlite3.Error as error:
            raise ToolError(f"catalog census refused by sqlite: {error}")
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # run_signature
    # ------------------------------------------------------------------
    def run_signature(self, catalog: str, mint: str) -> str:
        """Signature volatility (FORMAL_MODEL.md P2) on the newest retained
        candle window for one mint, computed from the provider's exact durable
        bytes in this catalog. Both clocks are reported — event time and wall
        time genuinely disagree on gap-compressed candles and neither is
        privileged. A lag with no pairs is absent, never zero."""
        path = self._catalog_path(catalog)
        conn = _open_ro(path)
        try:
            # The mint linkage hangs off the acquisition's :attempt envelope
            # observation; the provider's exact bytes are the same
            # acquisition's :body observation. Join through the acquisition.
            row = conn.execute(
                "SELECT o.observation_id, o.blob_id, o.received_wall_us,"
                "       o.parse_disposition, a.source_locator_redacted,"
                "       a.started_wall_us, a.acquisition_id"
                " FROM acquisition a"
                " JOIN observation link ON link.acquisition_id = a.acquisition_id"
                " JOIN observation_source_event ose"
                "   ON ose.observation_id = link.observation_id"
                " JOIN source_event se ON se.source_event_id = ose.source_event_id"
                " JOIN observation o ON o.acquisition_id = a.acquisition_id"
                "   AND o.observation_id LIKE '%:body'"
                " WHERE a.source_locator_redacted LIKE '%/candles%'"
                "   AND se.event_namespace = 'solana.token_mint'"
                "   AND se.natural_key = ?"
                " ORDER BY o.commit_seq DESC LIMIT 1",
                (mint,),
            ).fetchone()
            if row is None:
                raise ToolError(
                    f"no retained candle observation for mint {mint} in catalog "
                    f"{catalog!r} — absence of retention, not evidence the coin "
                    f"did not trade")
            raw = self._blob_bytes(conn, path, row["blob_id"])
        except sqlite3.Error as error:
            raise ToolError(f"signature read refused by sqlite: {error}")
        finally:
            conn.close()

        try:
            bars_json = json.loads(raw)
            bars = [(int(bar["timestamp"]), Decimal(bar["close"])) for bar in bars_json]
        except (ValueError, KeyError, TypeError) as error:
            raise ToolError(
                f"retained candle bytes for {mint} did not parse as the "
                f"reviewed candle shape: {error}")
        if len(bars) < 2:
            raise ToolError(
                f"retained candle window for {mint} holds {len(bars)} bar(s); "
                f"signature volatility needs at least 2")

        signature = self._signature_module()
        report = signature.render(bars)
        provenance = {
            "catalog": catalog,
            "observationId": row["observation_id"],
            "acquisitionId": row["acquisition_id"],
            "sourceLocator": row["source_locator_redacted"],
            "acquisitionStartedWallUs": int(row["started_wall_us"]),
            "observationReceivedWallUs": int(row["received_wall_us"]),
            "parseDisposition": row["parse_disposition"],
            "bars": len(bars),
            "firstBarMs": bars[0][0],
            "lastBarMs": bars[-1][0],
            "definition": ("signature volatility, Definition P2, "
                           "docs/microstructure/trades_quotes_prices/FORMAL_MODEL.md"),
            "note": ("computed from the provider's exact retained bytes; bar "
                     "timestamps are the provider's candle clocks, not the "
                     "ingest clock"),
        }
        return json.dumps(provenance, indent=1) + "\n\n" + report

    # ------------------------------------------------------------------
    def _blob_bytes(self, conn: sqlite3.Connection, catalog_path: Path,
                    blob_id: str) -> bytes:
        row = conn.execute(
            "SELECT storage_mode, inline_bytes, relative_path, compression"
            " FROM blob_object WHERE blob_id = ? LIMIT 1", (blob_id,)).fetchone()
        if row is None:
            raise ToolError(f"blob {blob_id} has no blob_object row")
        if row["compression"] != "identity":
            raise ToolError(
                f"blob {blob_id} is stored {row['compression']}-compressed; the "
                f"resident carries no decompressor and will not guess")
        if row["storage_mode"] == "inline":
            raw = row["inline_bytes"]
            if raw is None:
                raise ToolError(f"blob {blob_id} inline row holds no bytes")
            raw = bytes(raw)
        else:
            rel = row["relative_path"]
            if not rel:
                raise ToolError(f"blob {blob_id} external row names no path")
            on_disk = catalog_path.parent / "blobs" / rel
            if not on_disk.is_file():
                raise ToolError(
                    f"blob {blob_id} external bytes are not on disk at "
                    f"{on_disk} — disposed, not missing by accident")
            if on_disk.stat().st_size > MAX_BLOB_BYTES:
                raise ToolError(
                    f"blob {blob_id} is {on_disk.stat().st_size} bytes, over "
                    f"the {MAX_BLOB_BYTES} turn bound")
            raw = on_disk.read_bytes()
        if len(raw) > MAX_BLOB_BYTES:
            raise ToolError(
                f"blob {blob_id} is {len(raw)} bytes, over the "
                f"{MAX_BLOB_BYTES} turn bound")
        return raw


ANALYST_PROMPT_EXTRA = """

## The analysis bench

Beyond the paired core you have a read-only bench over durable catalogs:
list_catalogs (what exists), catalog_census (bounded counts and freshness for
one catalog), and run_signature (signature volatility — Definition P2 in
docs/microstructure/trades_quotes_prices/FORMAL_MODEL.md — on the newest
retained candle window for a mint, from the provider's exact durable bytes).
All of it is sqlite mode=ro; none of it can write.

Bench discipline:
- Every computed number carries its provenance — which catalog, which
  observation, whose clocks. Quote the provenance when you journal a number.
- Event time and wall time genuinely disagree on gap-compressed candles;
  report both, privilege neither, never average them.
- A lag with no pairs is an absent measurement, never zero. A mint with no
  retained candles is absent retention, never "did not trade".
- The vocabulary is docs/microstructure/trades_quotes_prices/ (FORMAL_MODEL,
  GLOSSARY, EMPIRICAL_CLAIMS). Use its terms — variogram, signature
  volatility, event time vs wall time — rather than inventing near-synonyms.
"""
