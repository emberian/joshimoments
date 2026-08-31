import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from solders.keypair import Keypair

from shitcoims_sentinel import cli
from shitcoims_sentinel.domain import TokenHolding
from shitcoims_sentinel.executor import ExecutionGate, ExecutionResult, SellExecutor
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


class _MustNotSell:
    """Stands in for the real SellExecutor; reaching it is the bug."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def sell(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("--status reached the real executor")


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def sell(self, **kwargs):
        self.calls.append(kwargs)
        return ExecutionResult("success", "sig", 1, "sold", 7)


def _holding(mint: str = "MintAAA", amount: int = 1234) -> TokenHolding:
    return TokenHolding(
        mint=mint, amount=amount, decimals=6, token_accounts=("acct",), program_ids=("prog",)
    )


def _satisfied_live_gate(tmp_path: Path) -> ExecutionGate:
    """A real ExecutionGate with all three live gates genuinely satisfied."""
    keypair = Keypair()
    arm_file = tmp_path / "arm"
    arm_file.write_text(f"shitcoims:{keypair.pubkey()}\n", encoding="utf-8")
    arm_file.chmod(0o600)
    config = SimpleNamespace(execution=SimpleNamespace(enabled=True, arm_file=arm_file))
    return ExecutionGate(config, keypair, cli_live=True)


class _CyclingEngine:
    """Engine stub whose cycle reaches the executor, exactly as the real one does."""

    def __init__(self, gate, executor) -> None:
        self.gate = gate
        self.executor = executor
        self.closed = False
        self.panicked = False
        self.results: list = []

    async def cycle(self) -> dict:
        live, failures = self.gate.status(jupiter_ready=True)
        result = await self.executor.sell(
            mint="MintAAA",
            name="LOOT",
            reason="exit_stop",
            observed_holding=_holding(),
        )
        self.results.append(result)
        return {"system": {"mode": "live" if live else "dry-run", "gate_failures": failures}}

    async def panic(self) -> list:
        self.panicked = True
        return [
            await self.executor.sell(
                mint="MintAAA", name="LOOT", reason="panic", observed_holding=_holding()
            )
        ]

    async def close(self) -> None:
        self.closed = True


def test_the_live_gate_used_by_the_status_tests_is_genuinely_satisfied(tmp_path: Path) -> None:
    # Without this the --status tests below would pass vacuously.
    assert _satisfied_live_gate(tmp_path).status(jupiter_ready=True) == (True, [])


@pytest.mark.asyncio
async def test_status_cannot_reach_the_executor_with_every_live_gate_satisfied(
    tmp_path: Path, capsys
) -> None:
    real_executor = _MustNotSell()
    engine = _CyclingEngine(_satisfied_live_gate(tmp_path), real_executor)

    await cli._one_shot(engine, panic=False)

    assert real_executor.calls == [], "--status must never dispatch to the real executor"
    assert isinstance(engine.executor, cli._ObservationOnlyExecutor)
    assert engine.gate.status(jupiter_ready=True) == (False, [cli.OBSERVATION_ONLY_REASON])

    result = engine.results[0]
    assert result.status == "observation_only"
    assert result.signature is None
    assert result.input_amount == 1234

    report = json.loads(capsys.readouterr().out)
    assert report["system"]["mode"] == "dry-run"
    assert report["system"]["gate_failures"] == [cli.OBSERVATION_ONLY_REASON]
    assert report["observation_only"]["suppressed_exits"] == [
        {"mint": "MintAAA", "name": "LOOT", "reason": "exit_stop", "amount": 1234}
    ]
    assert engine.closed is True


@pytest.mark.asyncio
async def test_panic_is_honestly_named_and_stays_able_to_execute(tmp_path: Path) -> None:
    real_executor = _RecordingExecutor()
    engine = _CyclingEngine(_satisfied_live_gate(tmp_path), real_executor)

    await cli._one_shot(engine, panic=True)

    assert engine.panicked is True
    assert engine.executor is real_executor
    assert len(real_executor.calls) == 1
    assert engine.gate.status(jupiter_ready=True) == (True, [])
    assert engine.closed is True


def test_seal_for_status_refuses_an_engine_it_cannot_seal() -> None:
    with pytest.raises(SystemExit):
        cli._seal_engine_for_status(SimpleNamespace())
    with pytest.raises(SystemExit):
        cli._seal_engine_for_status(SimpleNamespace(executor=object()))


def test_observation_only_executor_signature_matches_the_real_sell() -> None:
    # A drifted signature must raise rather than let --status fall back to
    # the real executor, so pin the two signatures together.
    assert inspect.signature(cli._ObservationOnlyExecutor.sell) == inspect.signature(
        SellExecutor.sell
    )


def test_status_flag_help_no_longer_claims_a_bare_read_only_cycle() -> None:
    action = next(a for a in cli._parser()._actions if a.dest == "status")
    assert "never sell" in action.help
