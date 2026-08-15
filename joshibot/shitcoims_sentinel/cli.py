from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from solders.pubkey import Pubkey

from .config import ConfigError, load_config
from .domain import DecisionKind, PoolSnapshot, TokenHolding, to_jsonable
from .engine import SentinelEngine
from .executor import ExecutionResult
from .notifier import telegram_bot_identity, telegram_confirm_pairing, telegram_send_test
from .secrets import read_secret_file
from .server import create_app

TELEGRAM_DISCOVERY_DEFAULT_TIMEOUT_SECONDS = 600
TELEGRAM_LONG_POLL_SECONDS = 25
TELEGRAM_LONG_POLL_NETWORK_GRACE_SECONDS = 10

OBSERVATION_ONLY_REASON = "--status runs in observation mode; its execution dispatch is removed"


def _telegram_discovery_timeout(value: str) -> int:
    try:
        timeout = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number of seconds") from exc
    if not 30 <= timeout <= 3600:
        raise argparse.ArgumentTypeError("must be between 30 and 3600 seconds")
    return timeout


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentinel.py",
        description="Local, sell-only Solana sentinel for the shitcoims wallet",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--live", action="store_true", help="request live execution (also needs both other gates)"
    )
    parser.add_argument("--dry-run", action="store_true", help="explicitly select the default dry-run mode")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--status",
        action="store_true",
        help=(
            "run one observation-only cycle and print JSON; the execution dispatch is "
            "removed first, so this can never sell even with --live"
        ),
    )
    mode.add_argument("--panic", action="store_true", help="sell every non-zero SPL holding, then exit")
    mode.add_argument("--arm", action="store_true", help="write the shitcoims-specific live arm file")
    mode.add_argument("--disarm", action="store_true", help="remove the local live arm file")
    mode.add_argument(
        "--dispose",
        metavar="MINT",
        help=(
            "durably mark a held/configured mint to sell one confirmed block after "
            "its executable PnL crosses above break-even; never trades in this command"
        ),
    )
    mode.add_argument(
        "--cancel-dispose",
        metavar="MINT",
        help="durably cancel a local dispose policy; never trades in this command",
    )
    mode.add_argument(
        "--telegram-discover",
        action="store_true",
        help="print the bot deep link and safe chat-pairing instructions",
    )
    mode.add_argument(
        "--telegram-test",
        action="store_true",
        help="send a no-trade test to the configured private chat",
    )
    parser.add_argument(
        "--telegram-discover-timeout-seconds",
        type=_telegram_discovery_timeout,
        default=TELEGRAM_DISCOVERY_DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="Telegram pairing window (default: 600; allowed: 30-3600)",
    )
    return parser


def _open_telegram_pairing_qr(link: str, output_path: Path) -> bool:
    """Create a private one-time QR image and open it when local tools permit."""
    qrencode = shutil.which("qrencode")
    if qrencode is None:
        return False
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [qrencode, "--output", "-", "--size", "10", "--margin", "4", link],
            check=True,
            capture_output=True,
        )
        descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(completed.stdout)
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, subprocess.CalledProcessError):
        output_path.unlink(missing_ok=True)
        return False

    opener = shutil.which("open")
    if opener is None:
        return False
    try:
        completed = subprocess.run(
            [opener, str(output_path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return completed.returncode == 0


async def _telegram_one_shot(
    config,
    *,
    discover: bool,
    discovery_timeout_seconds: int = TELEGRAM_DISCOVERY_DEFAULT_TIMEOUT_SECONDS,
) -> None:
    token_file = config.notifications.telegram_bot_token_file
    if token_file is None:
        raise SystemExit("Telegram token file is not configured")
    token = read_secret_file(token_file, required=True)
    assert token is not None
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5)) as http:
        if discover:
            username, webhook_present, pending = await telegram_bot_identity(token, http)
            if webhook_present:
                raise SystemExit("Telegram discovery refused: this bot has a webhook configured")
            if pending:
                raise SystemExit(
                    "Telegram discovery refused: pending updates already exist; do not consume them blindly"
                )
            nonce = secrets.token_urlsafe(12)
            start_parameter = f"shitcoims_{nonce}"
            expected_text = f"/start {start_parameter}"
            link = f"https://t.me/{username}?start={start_parameter}"
            qr_path = config.state_dir / f"telegram-pairing-{nonce}.png"
            opened = _open_telegram_pairing_qr(link, qr_path)
            minutes = discovery_timeout_seconds / 60
            if opened:
                print(f"Opened a one-time Telegram pairing QR in Preview ({minutes:g}-minute window).")
            else:
                print("Could not open a local QR image; use the private-chat link below.")
            print(f"Scan the QR or open {link}", flush=True)
            deadline = time.monotonic() + discovery_timeout_seconds
            try:
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    poll_seconds = min(TELEGRAM_LONG_POLL_SECONDS, max(1, int(remaining)))
                    try:
                        response = await http.get(
                            f"https://api.telegram.org/bot{token}/getUpdates",
                            params={
                                "limit": 10,
                                "timeout": poll_seconds,
                                "allowed_updates": '["message"]',
                            },
                            timeout=httpx.Timeout(
                                poll_seconds + TELEGRAM_LONG_POLL_NETWORK_GRACE_SECONDS,
                                connect=5,
                            ),
                        )
                        response.raise_for_status()
                        body = response.json()
                    except httpx.ReadTimeout:
                        # Telegram long polling can occasionally outlive its requested hold time.
                        # A single network timeout must not cancel the whole pairing window.
                        continue
                    except Exception as exc:
                        raise RuntimeError(f"Telegram discovery failed ({type(exc).__name__})") from None
                    updates = body.get("result") if isinstance(body, dict) else None
                    if not isinstance(updates, list):
                        raise RuntimeError("Telegram discovery returned malformed data")
                    for update in updates:
                        message = update.get("message") or {}
                        chat = message.get("chat") or {}
                        sender = message.get("from") or {}
                        if (
                            message.get("text") != expected_text
                            or chat.get("type") != "private"
                            or sender.get("id") != chat.get("id")
                        ):
                            raise RuntimeError(
                                "Telegram discovery saw an unexpected update and refused to consume it"
                            )
                        chat_id = str(chat["id"])
                        await telegram_confirm_pairing(token, chat_id, http)
                        acknowledgement = await http.get(
                            f"https://api.telegram.org/bot{token}/getUpdates",
                            params={"offset": int(update["update_id"]) + 1, "timeout": 0},
                        )
                        acknowledgement.raise_for_status()
                        print(f'telegram_chat_id: "{chat_id}"')
                        return
                raise RuntimeError("Telegram discovery timed out; no update was consumed")
            finally:
                qr_path.unlink(missing_ok=True)
        chat_id = config.notifications.telegram_chat_id
        if not chat_id:
            raise SystemExit("Telegram chat ID is not configured")
        await telegram_send_test(token, chat_id, http)
        print("Telegram test delivered. No trade was executed.")


def _write_arm(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)


class _ObservationOnlyExecutor:
    """Stand-in for SellExecutor with no path to a signed transaction.

    It holds no keypair, no RPC client, no Jupiter client and no execution gate,
    so there is nothing here that could sign or submit. It exists because
    ``--status`` is documented read-only while ``engine.cycle()`` reaches
    ``SellExecutor.sell()``: ``--live --status`` was a live trading command
    wearing a read-only label.

    The ``sell`` signature deliberately mirrors ``SellExecutor.sell`` exactly. If
    that signature changes, this raises TypeError rather than quietly falling
    back to the real executor.
    """

    def __init__(self) -> None:
        self.suppressed: list[dict[str, Any]] = []

    async def sell(
        self,
        *,
        mint: str,
        name: str,
        reason: DecisionKind | str,
        observed_holding: TokenHolding,
        amount: int | None = None,
        pool: PoolSnapshot | None = None,
    ) -> ExecutionResult:
        requested = observed_holding.amount if amount is None else int(amount)
        self.suppressed.append(
            {
                "mint": mint,
                "name": name,
                "reason": str(reason),
                "amount": requested,
            }
        )
        return ExecutionResult(
            status="observation_only",
            signature=None,
            attempts=0,
            message=f"OBSERVATION ONLY: {name} would exit ({reason}); {OBSERVATION_ONLY_REASON}",
            input_amount=requested,
        )


class _ObservationOnlyGate:
    """Execution gate that can never report live, without hiding the real gates.

    The wrapped gate's real failures are still reported so ``--status`` keeps its
    value as a readiness check; the observation-mode line is appended so an
    otherwise empty failure list is not mistaken for a broken arm setup.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def cli_live(self) -> bool:
        return False

    @property
    def expected_arm_value(self) -> str:
        return self._inner.expected_arm_value

    def status(self, *, jupiter_ready: bool) -> tuple[bool, list[str]]:
        _live, failures = self._inner.status(jupiter_ready=jupiter_ready)
        return False, [*failures, OBSERVATION_ONLY_REASON]


def _seal_engine_for_status(engine: SentinelEngine) -> _ObservationOnlyExecutor:
    """Remove the execution dispatch from an engine before a --status cycle.

    Two independent layers, either sufficient alone: the executor is replaced by
    an object that cannot sign, and the gate is wrapped so it can never report
    live. The post-conditions are then re-read from the engine, so a future
    refactor that moves either attribute aborts --status instead of silently
    restoring the ability to trade.
    """
    if not hasattr(engine, "executor") or not hasattr(engine, "gate"):
        raise SystemExit("refusing --status: the engine no longer exposes executor/gate to seal")
    observer = _ObservationOnlyExecutor()
    engine.executor = observer
    engine.gate = _ObservationOnlyGate(engine.gate)
    if engine.executor is not observer or engine.gate.status(jupiter_ready=True)[0]:
        raise SystemExit("refusing --status: the engine can still reach execution")
    return observer


async def _one_shot(engine: SentinelEngine, *, panic: bool) -> None:
    """Run exactly one cycle.

    ``panic=False`` is the ``--status`` path and is sealed into observation mode
    before the cycle starts. Sealing lives here rather than at the call site so
    there is no way to reach the status cycle unsealed.
    """
    try:
        if panic:
            results = await engine.panic()
            print(json.dumps(to_jsonable(results), indent=2))
            return
        observer = _seal_engine_for_status(engine)
        report = dict(await engine.cycle())
        report["observation_only"] = {
            "note": OBSERVATION_ONLY_REASON,
            "suppressed_exits": observer.suppressed,
        }
        print(json.dumps(report, indent=2))
    finally:
        await engine.close()


async def _change_dispose_policy(
    engine: SentinelEngine, *, mint: str, enabled: bool
) -> None:
    """Validate scope and mutate local policy state without entering a trade path."""
    mint = mint.strip()
    if not mint or len(mint) > 64 or any(character.isspace() for character in mint):
        raise RuntimeError("dispose mint is malformed")
    configured = any(policy.mint == mint for policy in engine.config.positions)
    if not configured:
        try:
            mint = str(Pubkey.from_string(mint))
        except Exception as exc:
            raise RuntimeError("dispose mint is not a Solana public key") from exc
        holdings = await engine.rpc.token_holdings(engine.wallet_address)
        if not any(holding.mint == mint and holding.amount > 0 for holding in holdings):
            raise RuntimeError("dispose mint is neither currently held nor configured")
    engine.state.set_dispose_policy(mint, enabled=enabled)


async def _dispose_one_shot(
    engine: SentinelEngine, *, mint: str, enabled: bool
) -> None:
    try:
        await _change_dispose_policy(engine, mint=mint, enabled=enabled)
        action = "Marked" if enabled else "Cancelled dispose for"
        print(
            f"{action} {mint} in durable local state. No trade was executed."
        )
    finally:
        await engine.close()


def main() -> None:
    args = _parser().parse_args()
    if args.live and args.dry_run:
        raise SystemExit("--live and --dry-run are mutually exclusive")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Helius authenticates in the URL query string. httpx's INFO request log
    # therefore contains a credential and must never be enabled.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        config = load_config(args.config)
    except (ConfigError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc

    if args.telegram_discover or args.telegram_test:
        try:
            asyncio.run(
                _telegram_one_shot(
                    config,
                    discover=args.telegram_discover,
                    discovery_timeout_seconds=args.telegram_discover_timeout_seconds,
                )
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from None
        return

    try:
        engine = SentinelEngine(config, cli_live=args.live)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    if args.arm:
        _write_arm(config.execution.arm_file, engine.gate.expected_arm_value)
        print(
            f"Armed shitcoims at {config.execution.arm_file}; "
            "execution.enabled and --live are still required."
        )
        asyncio.run(engine.close())
        return
    if args.disarm:
        config.execution.arm_file.unlink(missing_ok=True)
        print("Disarmed shitcoims live execution.")
        asyncio.run(engine.close())
        return
    if args.dispose or args.cancel_dispose:
        try:
            asyncio.run(
                _dispose_one_shot(
                    engine,
                    mint=args.dispose or args.cancel_dispose,
                    enabled=bool(args.dispose),
                )
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from None
        return
    if args.status or args.panic:
        asyncio.run(_one_shot(engine, panic=args.panic))
        return

    app = create_app(engine)
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        log_level="info",
        access_log=False,
    )
