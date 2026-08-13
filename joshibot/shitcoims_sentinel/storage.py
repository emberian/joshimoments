from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .domain import to_jsonable, utc_now

STATE_VERSION = 1


def _initial_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "positions": {},
        "dispose_policies": {},
        "pending_exits": {},
        "pool_baselines": {},
        "supply_baselines": {},
        "quote_baselines": {},
        "last_heartbeat_at": None,
        "updated_at": utc_now().isoformat(),
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(to_jsonable(payload), sort_keys=True, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock_path = path.with_name(f"{path.name}.lock")
        self._lock = threading.RLock()
        self._state = self._load()

    @contextmanager
    def _file_lock(self, *, exclusive: bool):
        """Serialize state refresh/write cycles across the server and local CLI."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.chmod(self.lock_path, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _initial_state()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read state file {self.path}: {exc}") from exc
        if not isinstance(value, dict) or value.get("version") != STATE_VERSION:
            raise RuntimeError(f"unsupported or malformed state file: {self.path}")
        return value

    def snapshot(self) -> dict[str, Any]:
        with self._lock, self._file_lock(exclusive=False):
            self._state = self._load()
            return json.loads(json.dumps(self._state))

    def get(self, *keys: str, default: Any = None) -> Any:
        with self._lock, self._file_lock(exclusive=False):
            self._state = self._load()
            value: Any = self._state
            for key in keys:
                if not isinstance(value, dict) or key not in value:
                    return default
                value = value[key]
            return json.loads(json.dumps(value))

    def set(self, *keys: str, value: Any) -> None:
        if not keys:
            raise ValueError("state key path cannot be empty")
        with self._lock, self._file_lock(exclusive=True):
            self._state = self._load()
            target = self._state
            for key in keys[:-1]:
                target = target.setdefault(key, {})
                if not isinstance(target, dict):
                    raise RuntimeError(f"state path {'/'.join(keys)} crosses a non-object")
            target[keys[-1]] = to_jsonable(value)
            self._state["updated_at"] = utc_now().isoformat()
            atomic_write_json(self.path, self._state)

    def delete(self, *keys: str) -> None:
        if not keys:
            raise ValueError("state key path cannot be empty")
        with self._lock, self._file_lock(exclusive=True):
            self._state = self._load()
            target = self._state
            for key in keys[:-1]:
                candidate = target.get(key)
                if not isinstance(candidate, dict):
                    return
                target = candidate
            if keys[-1] in target:
                del target[keys[-1]]
                self._state["updated_at"] = utc_now().isoformat()
                atomic_write_json(self.path, self._state)

    def set_dispose_policy(self, mint: str, *, enabled: bool) -> None:
        """Atomically change a local disposal override and reset its edge detector."""
        if not mint:
            raise ValueError("mint cannot be empty")
        with self._lock, self._file_lock(exclusive=True):
            self._state = self._load()
            policies = self._state.setdefault("dispose_policies", {})
            if not isinstance(policies, dict):
                raise RuntimeError("state dispose_policies is not an object")
            policies[mint] = {
                "enabled": enabled,
                "source": "local_cli",
                "changed_at": utc_now().isoformat(),
            }
            positions = self._state.setdefault("positions", {})
            if not isinstance(positions, dict):
                raise RuntimeError("state positions is not an object")
            position = positions.setdefault(mint, {})
            if not isinstance(position, dict):
                raise RuntimeError(f"state position {mint} is not an object")
            position["last_pnl_pct"] = None
            position["dispose_trigger_slot"] = None
            self._state["updated_at"] = utc_now().isoformat()
            atomic_write_json(self.path, self._state)


class EventJournal:
    def __init__(self, path: Path, *, max_memory: int = 200):
        self.path = path
        self.max_memory = max_memory
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._dedup: dict[str, float] = {}

    def emit(
        self,
        *,
        severity: str,
        category: str,
        message: str,
        context: dict[str, Any] | None = None,
        dedup_key: str | None = None,
        dedup_seconds: float = 300,
    ) -> dict[str, Any] | None:
        import time

        now_monotonic = time.monotonic()
        key = dedup_key or f"{severity}:{category}:{message}"
        with self._lock:
            if now_monotonic - self._dedup.get(key, float("-inf")) < dedup_seconds:
                return None
            self._dedup[key] = now_monotonic
            event = {
                "timestamp": utc_now().isoformat(),
                "severity": severity,
                "category": category,
                "message": message,
                "context": to_jsonable(context or {}),
            }
            self._events.append(event)
            self._events = self._events[-self.max_memory :]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return event

    def recent(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._events))
