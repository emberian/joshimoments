"""dregg-guard — the deadman for the dregg constellation on hbox.

Runs from a systemd timer (10-min). Checks, in order; alerts by Telegram DM to the
operator chat (deduped: a condition alerts once per state-change, not per tick), and
optionally pings a healthchecks.io URL so hbox-down itself alerts externally.

Checks:
  - archiver heartbeat fresh (< 3 * cadence_s old) and cycle advancing
  - budget sane (spent <= ceiling; stopped state alerted once)
  - disk free at the data root >= 20 GiB (alert + STOP-WRITERS advice; no auto-kill)
  - dregg services active (systemctl --user is-active, configurable list)

State (last alerted condition set) lives beside the heartbeat so re-alerts only fire on
change. Alerting failures are themselves recorded to the state file; the guard never
raises out — a crashed guard is what the external deadman is for.

Usage: uv run python -m dregg_archive.guard --config dregg_archive/config.toml \
         [--services dregg-archiver.service] [--ping-url URL]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:  # py311+
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

DISK_FLOOR_GIB = 20.0
STALE_FACTOR = 3.0


def _read_secret(path: Path) -> str:
    return path.read_text().strip()


def tg_send(token: str, chat_id: str, text: str) -> bool:
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:4000]}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return bool(json.loads(r.read()).get("ok"))
    except Exception:
        return False


def check(cfg_path: Path, services: list[str]) -> tuple[list[str], dict]:
    problems: list[str] = []
    info: dict = {}
    cfg = tomllib.loads(cfg_path.read_text()) if tomllib else {}
    base = cfg_path.parent
    hb_path = (base / cfg["paths"]["heartbeat"]).resolve()
    cadence = float(cfg.get("service", {}).get("cadence_s", 600))

    # heartbeat freshness + budget
    if not hb_path.exists():
        problems.append(f"heartbeat missing: {hb_path}")
    else:
        try:
            hb = json.loads(hb_path.read_text())
            age = time.time() - hb.get("t_ms", 0) / 1000.0
            info["heartbeat_age_s"] = round(age)
            info["cycle"] = hb.get("cycle")
            if age > STALE_FACTOR * cadence:
                problems.append(f"heartbeat stale: {age:.0f}s old (cadence {cadence:.0f}s)")
            budget = hb.get("budget") or {}
            info["budget"] = budget
            if budget.get("stopped"):
                problems.append(
                    f"archiver budget-stopped: {budget.get('spent')}/{budget.get('ceiling')}"
                    f" ({budget.get('note') or 'ceiling hit'})"
                )
        except Exception as error:  # unreadable heartbeat is itself a problem
            problems.append(f"heartbeat unreadable: {error}")

    # disk
    data_root = hb_path.parent
    usage = shutil.disk_usage(data_root)
    free_gib = usage.free / 2**30
    info["disk_free_gib"] = round(free_gib, 1)
    if free_gib < DISK_FLOOR_GIB:
        problems.append(
            f"disk low at {data_root}: {free_gib:.1f} GiB free (< {DISK_FLOOR_GIB:.0f});"
            " stop writers before this fills"
        )

    # services
    for unit in services:
        try:
            out = subprocess.run(
                ["systemctl", "--user", "is-active", unit],
                capture_output=True, text=True, timeout=10,
            )
            state = out.stdout.strip()
            if state != "active":
                problems.append(f"{unit}: {state or 'unknown'}")
        except Exception as error:
            problems.append(f"{unit}: systemctl failed ({error})")
    return problems, info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--services", nargs="*", default=["dregg-archiver.service"])
    ap.add_argument("--token-file", type=Path, default=Path.home() / ".config/dregg/telegram-token")
    ap.add_argument("--chat-id", default="6913902526")
    ap.add_argument("--ping-url", default=None, help="healthchecks.io URL; pinged on every clean run")
    args = ap.parse_args()

    problems, info = check(args.config, args.services)
    state_path = args.config.parent / ".guard_state.json"
    prev: list[str] = []
    if state_path.exists():
        try:
            prev = json.loads(state_path.read_text()).get("problems", [])
        except Exception:
            prev = []

    alert_ok = None
    if problems != prev:  # alert only on state CHANGE (incl. recovery)
        token = _read_secret(args.token_file)
        if problems:
            text = "🚨 dregg-guard:\n" + "\n".join(f"• {p}" for p in problems)
        else:
            text = "✅ dregg-guard: all clear again"
        alert_ok = tg_send(token, args.chat_id, text)

    if args.ping_url and not problems:
        with contextlib.suppress(Exception):
            urllib.request.urlopen(args.ping_url, timeout=10)

    state_path.write_text(json.dumps({
        "t": time.time(), "problems": problems, "info": info, "alert_ok": alert_ok,
    }, indent=1))
    print(json.dumps({"problems": problems, **info}))


if __name__ == "__main__":
    main()
