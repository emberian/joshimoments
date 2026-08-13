from pathlib import Path
from types import SimpleNamespace

import pytest

from shitcoims_sentinel import cli
from shitcoims_sentinel.storage import StateStore


def test_telegram_discovery_timeout_defaults_to_ten_minutes() -> None:
    args = cli._parser().parse_args(["--telegram-discover"])

    assert args.telegram_discover_timeout_seconds == 600


def test_telegram_discovery_timeout_can_be_extended() -> None:
    args = cli._parser().parse_args(["--telegram-discover", "--telegram-discover-timeout-seconds", "1200"])

    assert args.telegram_discover_timeout_seconds == 1200


@pytest.mark.parametrize("value", ["29", "3601", "not-a-number"])
def test_telegram_discovery_timeout_rejects_invalid_values(value: str) -> None:
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["--telegram-discover", "--telegram-discover-timeout-seconds", value])


def test_pairing_qr_is_private_and_opened_without_a_shell(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        return {"qrencode": "/tools/qrencode", "open": "/tools/open"}.get(name)

    def fake_run(command: list[str], **_kwargs):
        commands.append(command)
        return type(
            "Completed",
            (),
            {"returncode": 0, "stdout": b"png" if command[0] == "/tools/qrencode" else b""},
        )()

    monkeypatch.setattr(cli.shutil, "which", fake_which)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    output_path = tmp_path / "telegram-pairing-qr.png"

    assert cli._open_telegram_pairing_qr("https://t.me/example?start=one-time", output_path)
    assert output_path.stat().st_mode & 0o777 == 0o600
    assert commands == [
        [
            "/tools/qrencode",
            "--output",
            "-",
            "--size",
            "10",
            "--margin",
            "4",
            "https://t.me/example?start=one-time",
        ],
        ["/tools/open", str(output_path)],
    ]


def test_dispose_and_cancel_are_mutually_exclusive_local_commands() -> None:
    args = cli._parser().parse_args(["--dispose", "mint"])
    assert args.dispose == "mint"
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["--dispose", "mint", "--cancel-dispose", "mint"])


@pytest.mark.asyncio
async def test_dispose_command_only_mutates_state_for_configured_position(
    tmp_path: Path,
) -> None:
    class RpcMustNotBeCalled:
        async def token_holdings(self, _owner: str):
            raise AssertionError("configured mint validation must not need an RPC call")

    state = StateStore(tmp_path / "state.json")
    engine = SimpleNamespace(
        config=SimpleNamespace(positions=(SimpleNamespace(mint="mint"),)),
        rpc=RpcMustNotBeCalled(),
        wallet_address="wallet",
        state=state,
    )
    await cli._change_dispose_policy(engine, mint="mint", enabled=True)

    assert state.get("dispose_policies", "mint", "enabled") is True
    assert state.get("positions", "mint", "dispose_trigger_slot") is None
