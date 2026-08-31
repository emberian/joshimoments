from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

POLICY_DELETE_PATH = re.compile(r"/api/policies/([1-9A-HJ-NP-Za-km-z]{32,44})\Z")


class LocalAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class Query:
    source: str
    path: str
    params: dict[str, str]
    title: str
    action: str
    argument: str | None = None


class LocalAPI:
    """Fixed-route read-only client; user input can never select a URL."""

    def __init__(
        self,
        api_base: str,
        sentinel_api_base: str,
        http: httpx.AsyncClient,
    ):
        self.api_base = api_base
        self.sentinel_api_base = sentinel_api_base
        self.http = http

    async def put_json(self, path: str, body: dict) -> object:
        if not path.startswith("/api/policies"):
            raise LocalAPIError("scout may only write local policy YAML")
        try:
            response = await self.http.put(
                self.sentinel_api_base + path,
                json=body,
                headers={"content-type": "application/json", "accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise LocalAPIError(f"policy write failed ({type(exc).__name__})") from None

    async def post_json(self, path: str, body: dict) -> object:
        allowed = path == "/api/policies/protect-unmonitored" or path.endswith("/skip-auto")
        if not allowed or not path.startswith("/api/policies"):
            raise LocalAPIError("scout may only write local policy YAML")
        try:
            response = await self.http.post(
                self.sentinel_api_base + path,
                json=body,
                headers={"content-type": "application/json", "accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            raise LocalAPIError("protect write failed") from None

    async def delete_json(self, path: str) -> object:
        if POLICY_DELETE_PATH.fullmatch(path) is None:
            raise LocalAPIError("scout may only delete local policy YAML")
        try:
            response = await self.http.delete(
                self.sentinel_api_base + path,
                headers={"accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise LocalAPIError(f"policy delete failed ({type(exc).__name__})") from None

    async def get(self, query: Query) -> object:
        if query.source == "intel":
            base = self.api_base
        elif query.source == "sentinel":
            base = self.sentinel_api_base
        else:
            raise LocalAPIError("unknown local API source")
        try:
            response = await self.http.get(base + query.path, params=query.params)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise LocalAPIError(f"local data unavailable ({type(exc).__name__})") from None


def _render_snapshot(action: str, payload: dict) -> str | None:
    wallet = payload.get("wallet")
    system = payload.get("system")
    positions = payload.get("positions")
    unmonitored = payload.get("unmonitored")
    if not all(
        isinstance(value, expected)
        for value, expected in (
            (wallet, dict),
            (system, dict),
            (positions, list),
            (unmonitored, list),
        )
    ):
        return None
    holdings = positions + unmonitored
    if action == "portfolio":
        return "\n".join(
            [
                f"SOL: {wallet.get('sol', 'unknown')}",
                f"Token exit value: {wallet.get('portfolio_exit_sol', 'unknown')} SOL",
                f"Holdings: {len(holdings)} ({len(positions)} policy-protected)",
                f"Mode: {system.get('mode', 'unknown')} / {system.get('protection_state', 'unknown')}",
                f"Updated: {system.get('last_cycle_at', 'unknown')}",
            ]
        )
    if action == "positions":
        if not holdings:
            return "No nonzero token positions."
        lines = []
        for position in holdings[:30]:
            if not isinstance(position, dict):
                continue
            name = position.get("name") or str(position.get("mint", "unknown"))[:8]
            lines.append(
                f"• {name}: {position.get('ui_amount', '?')} tokens → "
                f"{position.get('exit_sol', '?')} SOL [{position.get('protection', 'unknown')}]"
            )
        if len(holdings) > 30:
            lines.append(f"… and {len(holdings) - 30} more")
        return "\n".join(lines)
    if action == "inventory":
        rows = [position for position in holdings if isinstance(position, dict)]
        lines = [
            f"SOL: {wallet.get('sol', 'unknown')}",
            f"Quoted token exit: {wallet.get('portfolio_exit_sol', 'unknown')} SOL",
        ]
        for position in rows:
            name = position.get("name") or str(position.get("mint", "unknown"))[:8]
            exit_sol = position.get("exit_sol")
            lines.append(
                f"• {name}: {position.get('ui_amount', '?')} tokens → "
                f"{'?' if exit_sol is None else exit_sol} SOL"
            )
        lines.append(f"Count: {len(rows)}")
        return "\n".join(lines)
    if action == "panic_preview":
        rows = [
            position
            for position in holdings
            if isinstance(position, dict) and _is_nonzero_holding(position)
        ]
        lines = ["THIS IS A PREVIEW. NOTHING WAS SOLD."]
        if rows:
            lines.append("A panic would attempt to sell:")
            for position in rows:
                name = position.get("name") or str(position.get("mint", "unknown"))[:8]
                exit_sol = position.get("exit_sol")
                lines.append(
                    f"• {name}: {position.get('ui_amount', '?')} tokens → "
                    f"{'?' if exit_sol is None else exit_sol} SOL"
                )
        else:
            lines.append("No nonzero holdings a panic would attempt to sell.")
        lines.append(f"Quoted exit if those sells filled: {_sum_exit_sol(rows)} SOL")
        gates = system.get("gate_failures")
        if isinstance(gates, list) and gates:
            lines.append("Live gates:")
            for gate in gates:
                lines.append(f"• {_text(gate, limit=200) or '?'}")
        else:
            lines.append("Live gates: all gates closed")
        return "\n".join(lines)
    if action == "risks":
        lines = [
            f"Protection: {system.get('protection_state', 'unknown')}",
            f"Configured policies: {len(positions)}; observe-only: {len(unmonitored)}",
        ]
        for position in holdings:
            if not isinstance(position, dict):
                continue
            rug = position.get("rug") or {}
            safety = position.get("mint_safety") or {}
            problems = []
            if rug.get("emergency"):
                problems.append(str(rug.get("reason") or "emergency rug signal"))
            if safety.get("mint_authority"):
                problems.append("mint authority active")
            if safety.get("freeze_authority"):
                problems.append("freeze authority active")
            problems.extend(str(value) for value in position.get("errors", []) if value)
            if problems:
                lines.append(f"• {position.get('name', 'unknown')}: {', '.join(problems)}")
        if len(lines) == 2:
            lines.append("No active emergency flags in the latest snapshot.")
        return "\n".join(lines)
    return None


def _render_event_counts(value: object) -> str:
    if not isinstance(value, dict):
        return "unknown"
    parts = []
    for key, count in list(value.items())[:12]:
        label = _text(key, limit=20)
        amount = _text(count, limit=12)
        if label is None or amount is None:
            continue
        parts.append(f"{label} {amount}")
    return ", ".join(parts) if parts else "none"


def _history_event_line(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    severity = (_text(value.get("severity"), limit=20) or "info").upper()
    category = _text(value.get("category"), limit=32) or "event"
    message = _text(value.get("message"), limit=200)
    timestamp = _text(value.get("timestamp"), limit=64)
    line = f"• [{severity}] {category}"
    if message:
        line = f"{line}: {message}"
    if timestamp:
        line = f"{line} ({timestamp})"
    return line


def _history_trade_line(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    name = _text(value.get("name"), limit=48) or _text(value.get("mint"), limit=8) or "unknown"
    reason = _text(value.get("reason"), limit=32) or "exit"
    output = _text(value.get("output_lamports"), limit=32) or "?"
    timestamp = _text(value.get("timestamp"), limit=64)
    mint = _text(value.get("mint"), limit=64)
    signature = _text(value.get("signature"), limit=88)
    line = f"• {name}: {reason} → {output} lamports"
    extras = [part for part in (timestamp, mint, signature) if part]
    if extras:
        line = f"{line} ({' · '.join(extras)})"
    return line


def _render_history(action: str, payload: dict) -> str | None:
    if action == "performance":
        return "\n".join(
            [
                f"SOL: {_text(payload.get('native_sol'), limit=32) or 'unknown'}",
                f"Token exit value: {_text(payload.get('portfolio_exit_sol'), limit=32) or 'unknown'} SOL",
                f"Realized: {_text(payload.get('realized_sol'), limit=32) or 'unknown'} SOL",
                f"Trades: {_text(payload.get('trade_count'), limit=12) or 'unknown'}",
                f"Protected: {_text(payload.get('protected_positions'), limit=12) or 'unknown'}",
                f"Observe-only: {_text(payload.get('observe_only'), limit=12) or 'unknown'}",
                f"Last exit: {_text(payload.get('last_exit_at'), limit=64) or 'never'}",
                (
                    f"Mode: {_text(payload.get('mode'), limit=40) or 'unknown'} / "
                    f"{_text(payload.get('protection_state'), limit=40) or 'unknown'}"
                ),
                f"Events: {_render_event_counts(payload.get('event_counts'))}",
            ]
        )
    if action == "events":
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        lines = [line for value in items[:10] if (line := _history_event_line(value))]
        return "\n".join(lines) if lines else "No events recorded."
    if action == "trades":
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        lines = [line for value in items[:10] if (line := _history_trade_line(value))]
        return "\n".join(lines) if lines else "No trades recorded."
    return None


def _as_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _is_nonzero_holding(position: dict) -> bool:
    raw = position.get("ui_amount")
    if raw is None:
        raw = position.get("amount")
    parsed = _as_decimal(raw)
    if parsed is not None:
        return parsed != 0
    return raw not in (None, "", 0, "0")


def _sum_exit_sol(holdings: list[dict]) -> str:
    if not holdings:
        return "0"
    total = Decimal(0)
    found = False
    for position in holdings:
        value = _as_decimal(position.get("exit_sol"))
        if value is None:
            continue
        total += value
        found = True
    return str(total) if found else "unknown"


def _text(value: object, *, limit: int = 500) -> str | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    result = str(value).strip().replace("\r", " ").replace("\n", " ")
    if not result:
        return None
    return result if len(result) <= limit else result[: limit - 1].rstrip() + "…"


def _item_line(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    severity = (_text(value.get("severity"), limit=20) or "info").upper()
    title = _text(value.get("title")) or _text(value.get("summary"))
    if title is None:
        kind = _text(value.get("kind"), limit=40) or "item"
        subject = _text(value.get("subject_id"), limit=60) or "unknown"
        title = f"{kind}: {subject}"
    source = _text(value.get("source_id"), limit=40)
    confidence = _text(value.get("confidence"), limit=20)
    suffix = " · ".join(part for part in (source, f"confidence {confidence}" if confidence else None) if part)
    return f"• [{severity}] {title}" + (f" — {suffix}" if suffix else "")


def _render_intelligence(action: str, payload: dict) -> str | None:
    if action in {"now", "x", "xkol"}:
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        empty = {
            "x": "No X observations in the current window.",
            "xkol": "No X KOL posts in the current window.",
        }.get(action, "No intelligence items in the current window.")
        lines = [line for value in items[:10] if (line := _item_line(value))]
        if not lines:
            return empty
        if payload.get("has_more") is True:
            lines.append("More items are available; use Next.")
        return "\n".join(lines)
    if action == "health":
        status = "healthy" if payload.get("healthy") is True else "degraded"
        runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        store = payload.get("store") if isinstance(payload.get("store"), dict) else {}
        reasons = payload.get("degraded_reasons")
        lines = [
            f"Status: {status}",
            f"Mode: {_text(payload.get('mode'), limit=40) or 'READ_ONLY'}",
            f"Writer: {'active' if runtime.get('writer_active') else 'idle'}",
            f"Collectors: {_text(runtime.get('collectors_active'), limit=8) or '0'}",
            f"Last cycle: {_text(runtime.get('last_cycle_at'), limit=80) or 'never'}",
            f"Store ready: {store.get('ready') is True}",
        ]
        if isinstance(reasons, list) and reasons:
            lines.append("Reasons: " + ", ".join(_text(item, limit=80) or "?" for item in reasons[:6]))
        return "\n".join(lines)
    if action == "mints":
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        lines = []
        for value in items[:20]:
            if not isinstance(value, dict):
                continue
            name = _text(value.get("name"), limit=80) or _text(value.get("id"), limit=80)
            if name is None:
                continue
            count = _text(value.get("member_count"), limit=12) or "0"
            types = value.get("member_types")
            type_note = ""
            if isinstance(types, dict) and types:
                type_note = " · " + ", ".join(f"{key} {types[key]}" for key in list(types)[:4])
            lines.append(f"• {name}: {count} members{type_note}")
        return "\n".join(lines) if lines else "No watchlists published yet."
    if action == "kols":
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        chosen = None
        for value in items:
            if not isinstance(value, dict):
                continue
            if value.get("id") == "x-kols":
                chosen = value
                break
            if chosen is None and _text(value.get("name"), limit=80) == "X KOL watches":
                chosen = value
        if chosen is None:
            return "No X KOL watchlist published yet."
        members = chosen.get("members")
        if not isinstance(members, list):
            members = chosen.get("entries")
        lines = []
        if isinstance(members, list):
            for member in members[:20]:
                handle = None
                note = None
                if isinstance(member, str):
                    handle = _text(member, limit=15)
                elif isinstance(member, dict):
                    handle = (
                        _text(member.get("handle"), limit=15)
                        or _text(member.get("subject_id"), limit=15)
                        or _text(member.get("id"), limit=15)
                    )
                    note = _text(member.get("notes") or member.get("label"), limit=80)
                if handle is None:
                    continue
                shown = handle if handle.startswith("@") else f"@{handle}"
                lines.append(f"• {shown}" + (f" — {note}" if note and note != handle else ""))
        if lines:
            return "\n".join(lines)
        name = _text(chosen.get("name"), limit=80) or "X KOL watches"
        count = _text(chosen.get("member_count"), limit=12) or "0"
        types = chosen.get("member_types")
        type_note = ""
        if isinstance(types, dict) and types:
            type_note = " · " + ", ".join(f"{key} {types[key]}" for key in list(types)[:4])
        row = [f"• {name}: {count} members{type_note}"]
        description = _text(chosen.get("description"), limit=200)
        if description:
            row.append(description)
        return "\n".join(row)
    if action == "sources":
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        lines = []
        for value in items[:30]:
            if not isinstance(value, dict):
                continue
            name = _text(value.get("name"), limit=80) or _text(value.get("id"), limit=80)
            if name is None:
                continue
            status = _text(value.get("status"), limit=30) or (
                "healthy" if value.get("healthy") is True else "unhealthy"
            )
            lag = _text(value.get("lag_seconds"), limit=20)
            lines.append(f"• {name}: {status}" + (f" · lag {lag}s" if lag else ""))
        return "\n".join(lines) if lines else "No source health records are available."
    if action == "digest":
        items = payload.get("items")
        value = items[0] if isinstance(items, list) and items else payload
        if not isinstance(value, dict):
            return None
        title = _text(value.get("title")) or "Latest digest"
        summary = _text(value.get("summary"), limit=2000) or "No digest summary is available."
        count = _text(value.get("item_count"), limit=20)
        return f"{title}\n{summary}" + (f"\nItems: {count}" if count else "")
    if action in {"wallet", "token", "cashtag", "kol"}:
        value = payload.get("dossier")
        if not isinstance(value, dict):
            return None
        label = _text(value.get("label"), limit=100) or _text(value.get("id"), limit=80) or "Dossier"
        summary = _text(value.get("summary"), limit=1800) or "No summary is available."
        risk = _text(value.get("risk"), limit=100)
        confidence = _text(value.get("confidence"), limit=40)
        quality = _text(value.get("data_quality"), limit=100)
        fields = [f"{label}\n{summary}"]
        if risk:
            fields.append(f"Risk: {risk}")
        if confidence:
            fields.append(f"Confidence: {confidence}")
        if quality:
            fields.append(f"Data quality: {quality}")
        return "\n".join(fields)
    if action == "why":
        value = payload.get("item")
        if not isinstance(value, dict):
            return None
        line = _item_line(value) or "Signal evidence"
        summary = _text(value.get("summary"), limit=1800)
        observed = _text(value.get("observed_at"), limit=80)
        fields = [line]
        if summary and summary not in line:
            fields.append(summary)
        if observed:
            fields.append(f"Observed: {observed}")
        return "\n".join(fields)
    return None


def render_payload(
    title: str,
    payload: object,
    *,
    action: str = "",
    max_chars: int = 3500,
) -> str:
    if isinstance(payload, dict):
        body = (
            _render_snapshot(action, payload)
            or _render_history(action, payload)
            or _render_intelligence(action, payload)
        )
        if body is None:
            body = "Data is available, but its response schema is not recognized safely."
    else:
        body = "The local service returned an unsupported response."
    text = f"{title}\n\n{body}"
    if len(text) > max_chars:
        text = text[: max_chars - 20].rstrip() + "\n… truncated"
    return text
