from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import httpx

from .config import Config, GateConfigError, read_secret
from .service import run_service
from .state import GateState, GateStateError
from .telegram import Telegram


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dregg-gate",
        description="$DREGG token-gate Telegram bot (@ltshitcoims_bot)",
    )
    parser.add_argument("--config", default="dregg_gate.toml")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration, secrets, and the state lock without contacting Telegram",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="one live getMe/getWebhookInfo round-trip, then exit",
    )
    return parser


async def _probe(config: Config, token: str) -> str:
    state = GateState(config.db_path)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15, connect=5), follow_redirects=False
        ) as http:
            return await Telegram(token, http, state).probe()
    finally:
        state.close()


def main() -> None:
    args = _parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Telegram and Helius both embed credentials in request URLs. Never enable request logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        config_path = Path(args.config).expanduser().resolve()
        config = Config.load(config_path)
        token = read_secret(config.telegram_token_file, "Telegram bot token")
        helius_key = read_secret(config.helius_key_file, "Helius API key")
        if args.check_config:
            state = GateState(config.db_path)
            state.close()
            print(f"dregg gate configuration valid (db={config.db_path}); no network request was made")
            return
        if args.probe:
            username = asyncio.run(_probe(config, token))
            print(f"dregg gate authenticated as @{username}")
            return
        asyncio.run(run_service(config_path, config, token, helius_key))
    except (GateConfigError, GateStateError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
