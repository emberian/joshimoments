from __future__ import annotations

import argparse
import asyncio
import logging

import httpx

from .config import ScoutConfigError, load_scout_config, read_private_token
from .gateway import ScoutGateway
from .local_api import LocalAPI
from .state import ScoutState, ScoutStateError
from .telegram import Telegram


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scout.py",
        description="Read-only Telegram intelligence gateway for shitcoims",
    )
    parser.add_argument("--config", default="intelligence.yaml")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration and local state without contacting Telegram",
    )
    parser.add_argument(
        "--check-ready",
        action="store_true",
        help="require enabled state, exact Telegram IDs, and a private token file",
    )
    return parser


async def _run(config, token: str) -> None:
    state = ScoutState(config.state_file)
    try:
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(15, connect=5),
                follow_redirects=False,
            ) as telegram_http,
            httpx.AsyncClient(
                timeout=httpx.Timeout(10, connect=2),
                follow_redirects=False,
            ) as local_http,
        ):
            telegram = Telegram(token, telegram_http, state)
            local_api = LocalAPI(config.api_base, config.sentinel_api_base, local_http)
            await ScoutGateway(config, state, telegram, local_api).run()
    finally:
        state.close()


def main() -> None:
    args = _parser().parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Telegram embeds its credential in request URLs. Never enable request logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        config = load_scout_config(args.config)
        if args.check_config and not args.check_ready:
            print(
                "shitcoims Scout configuration valid "
                f"(enabled={str(config.enabled).lower()}, state={config.state_file})"
            )
            return
        if not config.enabled:
            raise ScoutConfigError("Scout is disabled; set scout.enabled: true after review")
        if config.telegram_chat_id is None or config.telegram_user_id is None:
            raise ScoutConfigError("scout.telegram_chat_id and scout.telegram_user_id are both required")
        token = read_private_token(config.telegram_bot_token_file)
        if args.check_ready:
            state = ScoutState(config.state_file)
            state.close()
            print("shitcoims Scout is ready to start (no Telegram request was made)")
            return
        asyncio.run(_run(config, token))
    except (ScoutConfigError, ScoutStateError) as exc:
        raise SystemExit(str(exc)) from None
