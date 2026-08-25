"""Drivers for the committed release binaries. Every provider request goes through them.

``joshi-pump-product-read`` for the catalogued product routes, ``joshi-pump-trades-backfill``
for trade tapes, both from ``target/release`` (the committed binaries; this study never
rebuilds them). A read with no reviewed schema still retains its exact bytes but is refused
promotion — such bodies are decodable from the emitted outcome and every number derived from
them must carry the ``retained_quarantined`` label, which the result dict states.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PRODUCT_READ = REPO / "target" / "release" / "joshi-pump-product-read"
TRADES_BACKFILL = REPO / "target" / "release" / "joshi-pump-trades-backfill"
FIXTURES = REPO / "crates" / "joshi-pump-api" / "fixtures"

REVIEWS: dict[str, Path] = {
    "discovery_coins": FIXTURES / "row_projection_discovery_coins_v1.json",
    "currently_live": FIXTURES / "row_projection_currently_live_v1.json",
    "coin_search": FIXTURES / "row_projection_coin_search_v1.json",
    "coin_exact": FIXTURES / "row_projection_coin_exact_v1.json",
    "callout_top": FIXTURES / "row_projection_callout_top_v1.json",
    "candles": FIXTURES / "schema_review_candles_v1.json",
    "trades": FIXTURES / "schema_review_trades_v1.json",
    # community_callouts: NO reviewed artifact exists in the tree (checked 2026-08-24).
    # Reads retain bytes and quarantine; results carry retained_quarantined.
}

PACING_SECONDS = 2.0
COMMUNITY_PACING_SECONDS = 3.5


def utc_of_millis(millis: int) -> str:
    """Epoch milliseconds as the canonical six-digit UTC wire instant."""
    stamp = dt.datetime.fromtimestamp(millis / 1000.0, tz=dt.UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def millis_of_iso(text: str) -> int:
    """ISO-8601 (Z or offset) to epoch milliseconds."""
    return int(dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def body_of_outcome(outcome_path: Path) -> tuple[dict | list | None, int | None]:
    """Decode the exact retained bytes of the last attempt in a fetch outcome."""
    outcome = json.loads(outcome_path.read_text())
    attempts = outcome.get("attempts", [])
    if not attempts:
        return None, None
    attempt = attempts[-1]
    status = attempt.get("httpStatus")
    body = attempt.get("body", {})
    if body.get("status") != "exact":
        return None, status
    raw = base64.b64decode(body["bytesBase64"])
    try:
        return json.loads(raw), status
    except json.JSONDecodeError:
        return None, status


def product_read(
    ledger,
    root: Path,
    tag: str,
    route: str,
    *,
    paths: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    pacing_seconds: float = PACING_SECONDS,
) -> dict:
    """One admitted product read, cached by tag, ledgered before the spend."""
    out_dir = root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    outcome_path = out_dir / f"{tag}.outcome.json"
    receipt_path = out_dir / f"{tag}.receipt.json"
    review = REVIEWS.get(route)
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        body, status = body_of_outcome(outcome_path)
        return _read_result(tag, True, receipt, body, status, review)
    ledger.reserve(1)
    cmd = [
        str(PRODUCT_READ),
        "--route",
        route,
        "--state-dir",
        str(root / "admit"),
        "--emit-outcome",
        str(outcome_path),
        "--request-budget",
        "1",
    ]
    if review is not None:
        cmd.extend(["--review", str(review)])
    if route == "community_callouts":
        # The route's origin requires the shared product key every pump.fun visitor ships;
        # same file the keeper reads (ops/keeper.toml community_key_file), never rendered.
        cmd.extend(["--community-key-file", str(Path.home() / ".coin-communities-key")])
    for name, value in (paths or {}).items():
        if name == "mint":
            cmd.extend(["--mint", value])
        else:
            cmd.extend(["--path", f"{name}={value}"])
    for name, value in (query or {}).items():
        cmd.extend(["--query", f"{name}={value}"])
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    ledger.record(
        {
            "phase": route,
            "tag": tag,
            "requests": 1,
            "exit": proc.returncode,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    )
    if proc.returncode != 0:
        (out_dir / f"{tag}.stderr.txt").write_text(proc.stderr)
        body, status = (
            body_of_outcome(outcome_path) if outcome_path.exists() else (None, None)
        )
        time.sleep(pacing_seconds)
        return {
            "tag": tag,
            "cached": False,
            "error": proc.stderr.strip()[-500:],
            "receipt": None,
            "body": body,
            "status": status,
            # A route with no reviewed schema quarantines by design; its retained bytes
            # are usable only under this label. Anything else is an ordinary failure.
            "trust": (
                "retained_quarantined"
                if review is None and body is not None
                else "refused_or_failed"
            ),
        }
    receipt = json.loads(proc.stdout)
    receipt_path.write_text(json.dumps(receipt, indent=1))
    body, status = body_of_outcome(outcome_path)
    time.sleep(pacing_seconds)
    return _read_result(tag, False, receipt, body, status, review)


def _read_result(
    tag: str,
    cached: bool,
    receipt: dict,
    body: dict | list | None,
    status: int | None,
    review: Path | None,
) -> dict:
    trust = receipt.get("schemaTrustOutcome", "unknown")
    if review is None:
        trust = "retained_quarantined"  # no reviewed schema exists; bytes retained, refused
    return {
        "tag": tag,
        "cached": cached,
        "receipt": receipt,
        "body": body,
        "status": status,
        "trust": trust,
    }


def tape_walk(
    ledger,
    state_dir: Path,
    receipt_dir: Path,
    tag: str,
    mint: str,
    *,
    seek: str | None = None,
    stop_before: str | None = None,
    max_pages: int = 3,
    page_limit: int = 100,
    pacing_seconds: float = PACING_SECONDS,
) -> dict:
    """One bounded backwards trade walk into a per-mint state dir, cached by tag."""
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{tag}.receipt.json"
    if receipt_path.exists():
        return {"tag": tag, "cached": True, "receipt": json.loads(receipt_path.read_text())}
    ledger.reserve(max_pages)
    cmd = [
        str(TRADES_BACKFILL),
        "--mint",
        mint,
        "--state-dir",
        str(state_dir),
        "--review",
        str(REVIEWS["trades"]),
        "--page-limit",
        str(page_limit),
        "--request-budget",
        str(max_pages),
        "--max-pages",
        str(max_pages),
        "--wall-budget-seconds",
        "90",
    ]
    if seek:
        cmd.extend(["--seek", seek])
    if stop_before:
        cmd.extend(["--stop-before", stop_before])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
    if proc.returncode != 0:
        # No receipt means the spend cannot be read back; the whole ceiling is counted,
        # conservative in the budget's favour.
        ledger.record({"phase": "tape", "tag": tag, "requests": max_pages, "exit": 2})
        (receipt_dir / f"{tag}.stderr.txt").write_text(proc.stderr)
        time.sleep(pacing_seconds)
        return {"tag": tag, "cached": False, "error": proc.stderr.strip()[-500:], "receipt": None}
    receipt = json.loads(proc.stdout)
    used = int(receipt["walk"]["requestsUsed"])
    ledger.record({"phase": "tape", "tag": tag, "requests": used, "exit": 0})
    receipt_path.write_text(json.dumps(receipt, indent=1))
    time.sleep(pacing_seconds)
    return {"tag": tag, "cached": False, "receipt": receipt}
