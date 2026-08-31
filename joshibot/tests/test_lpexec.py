"""Tests for shitcoims_lpexec: the refusals, the gates, the bin math, the ledger.

NO NETWORK. Every transaction below is built with real solders and validated by the real
guard; the only thing faked is the account-data fetch used to expand address lookup tables,
and its default implementation asserts it is never called.

The load-bearing tests are the ones that build a REAL Meteora swap instruction -- correct
program id, correct 8-byte discriminator computed from `sha256("global:swap")` -- and assert
the guard refuses it. A comment claiming "we never build swaps" is worth nothing; a test that
constructs the exact bytes an attacker would need and watches them bounce is the claim.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import time
from pathlib import Path

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from shitcoims_lpexec import allowlist, binmath, planner
from shitcoims_lpexec.allowlist import (
    ALLOWED_DLMM,
    ASSOCIATED_TOKEN_PROGRAM,
    COMPUTE_BUDGET_PROGRAM,
    DLMM_PROGRAM,
    SYSTEM_PROGRAM,
    THA_FUNDS,
    TOKEN_PROGRAM,
    WSOL_MINT,
    discriminator,
)
from shitcoims_lpexec.config import ConfigError, default_config, load_config
from shitcoims_lpexec.gate import ExecutionGate, write_arm
from shitcoims_lpexec.guard import (
    TransactionRefused,
    associated_token_address,
    guard_transaction,
)
from shitcoims_lpexec.ledger import Ledger, day_spend, read_day
from shitcoims_lpexec.planner import BinHolding, PlanRefused, plan_ladder, plan_trim
from shitcoims_lpexec.rpc import READ_METHODS, HeliusRpc, RpcError, bin_array_key
from shitcoims_lpexec.secrets import SecretError, load_keypair, read_secret_file
from shitcoims_lpexec.signer import sign_guarded

NOSIS_WEAVE = "48z2a9zvV7rBrMvwn3kE7vbwwiroiaaHm4rx1RwtksRF"
NOSIS_SOL = "C889ex3M6dDecsxjAAudiLjhdeKgehbLm4zK9wV3nX8N"
NOT_A_POOL = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"

OWNER = Pubkey.from_string(THA_FUNDS)


def no_lookup(_address: str) -> bytes:
    raise AssertionError("this test transaction has no address lookup tables")


def encode(payer: Pubkey, instructions: list[Instruction], *, signers: int = 1) -> str:
    """Compile to an unsigned v0 transaction, exactly as the sidecar returns one."""
    import base64

    message = MessageV0.try_compile(payer, instructions, [], Hash.new_unique())
    unsigned = VersionedTransaction.populate(message, [Signature.default()] * signers)
    return base64.b64encode(bytes(unsigned)).decode("ascii")


def dlmm_ix(name: str, accounts: list[Pubkey], *, payload: bytes = b"") -> Instruction:
    """A real DLMM instruction: real program, real Anchor discriminator, real accounts."""
    return Instruction(
        Pubkey.from_string(DLMM_PROGRAM),
        bytes.fromhex(discriminator(name)) + payload,
        [AccountMeta(key, is_signer=False, is_writable=True) for key in accounts],
    )


def cu_ixs(limit: int = 200_000, price: int = 100_000) -> list[Instruction]:
    program = Pubkey.from_string(COMPUTE_BUDGET_PROGRAM)
    return [
        Instruction(program, bytes([2]) + struct.pack("<I", limit), []),
        Instruction(program, bytes([3]) + struct.pack("<Q", price), []),
    ]


def remove_accounts(pool: str, position: Pubkey, sender: Pubkey) -> list[Pubkey]:
    """`remove_liquidity_by_range`: position at 0, lb_pair at 1, sender at 11."""
    filler = [Pubkey.new_unique() for _ in range(9)]
    return [position, Pubkey.from_string(pool), *filler, sender]


def guard(encoded: str, **kwargs: object):  # type: ignore[no-untyped-def]
    defaults = {
        "owner": OWNER,
        "account_data": no_lookup,
        "max_priority_fee_lamports": 1_000_000,
    }
    defaults.update(kwargs)
    return guard_transaction(encoded=encoded, **defaults)  # type: ignore[arg-type]


# ======================================================================================
# THE CENTRAL CLAIM: no swap can be built.
# ======================================================================================


@pytest.mark.parametrize(
    "swap_name",
    [
        "swap",
        "swap2",
        "swap_exact_out",
        "swap_exact_out2",
        "swap_with_price_impact",
        "swap_with_price_impact2",
    ],
)
def test_every_dlmm_swap_instruction_is_refused(swap_name: str) -> None:
    """Build the real bytes an attacker would need and watch all six bounce."""
    position = Pubkey.new_unique()
    ix = dlmm_ix(swap_name, remove_accounts(NOSIS_WEAVE, position, OWNER), payload=b"\x00" * 16)
    encoded = encode(OWNER, [*cu_ixs(), ix])
    with pytest.raises(TransactionRefused, match="SWAP"):
        guard(encoded, expected_pools=[NOSIS_WEAVE], expected_positions=[str(position)])


def test_the_swap_refusal_is_data_not_code() -> None:
    """The discriminator we refuse is derived, not typed. A rename cannot open a hole."""
    assert discriminator("swap") == hashlib.sha256(b"global:swap").digest()[:8].hex()
    assert discriminator("swap") not in ALLOWED_DLMM
    for name in ("swap", "swap2", "swap_exact_out"):
        assert discriminator(name) in allowlist.SWAP_DISCRIMINATORS


def test_no_allowlisted_instruction_name_contains_swap() -> None:
    for spec in ALLOWED_DLMM.values():
        assert "swap" not in spec.name


def test_an_unknown_dlmm_instruction_is_refused() -> None:
    """Default-deny: an instruction nobody has read is refused, not tolerated."""
    position = Pubkey.new_unique()
    ix = Instruction(
        Pubkey.from_string(DLMM_PROGRAM),
        bytes.fromhex("00" * 8),
        [AccountMeta(position, is_signer=False, is_writable=True)],
    )
    with pytest.raises(TransactionRefused, match="not on the allowlist"):
        guard(encode(OWNER, [*cu_ixs(), ix]))


def test_go_to_a_bin_is_refused_because_it_reprices_the_pool() -> None:
    ix = dlmm_ix("go_to_a_bin", [Pubkey.from_string(NOSIS_WEAVE), OWNER])
    with pytest.raises(TransactionRefused, match="go_to_a_bin"):
        guard(encode(OWNER, [*cu_ixs(), ix]))


def test_an_arbitrary_program_is_refused() -> None:
    """Jupiter, PumpSwap, anything: not on the program allowlist, not built."""
    jupiter = Pubkey.from_string("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")
    ix = Instruction(jupiter, b"\x01\x02\x03", [AccountMeta(OWNER, is_signer=True, is_writable=True)])
    with pytest.raises(TransactionRefused, match="not an allowlisted program"):
        guard(encode(OWNER, [*cu_ixs(), ix]))


# ======================================================================================
# Pool and intent binding.
# ======================================================================================


def test_a_pool_outside_the_allowlist_is_refused() -> None:
    position = Pubkey.new_unique()
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOT_A_POOL, position, OWNER))
    with pytest.raises(TransactionRefused, match="not in the lpexec pool allowlist"):
        guard(encode(OWNER, [*cu_ixs(), ix]))


def test_an_allowlisted_pool_the_plan_did_not_authorise_is_refused() -> None:
    """The pool allowlist is the outer bound; the plan is the inner one."""
    position = Pubkey.new_unique()
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_SOL, position, OWNER))
    with pytest.raises(TransactionRefused, match="the plan authorised only"):
        guard(
            encode(OWNER, [*cu_ixs(), ix]),
            expected_pools=[NOSIS_WEAVE],
            expected_positions=[str(position)],
        )


def test_a_position_the_plan_did_not_authorise_is_refused() -> None:
    other = Pubkey.new_unique()
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_WEAVE, other, OWNER))
    with pytest.raises(TransactionRefused, match="did not authorise"):
        guard(
            encode(OWNER, [*cu_ixs(), ix]),
            expected_pools=[NOSIS_WEAVE],
            expected_positions=[str(Pubkey.new_unique())],
        )


def test_an_instruction_acting_for_another_wallet_is_refused() -> None:
    stranger = Pubkey.new_unique()
    position = Pubkey.new_unique()
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_WEAVE, position, stranger))
    with pytest.raises(TransactionRefused, match="not for tha funds"):
        guard(
            encode(OWNER, [*cu_ixs(), ix]),
            expected_pools=[NOSIS_WEAVE],
            expected_positions=[str(position)],
        )


def test_a_transaction_for_another_fee_payer_is_refused() -> None:
    stranger = Keypair().pubkey()
    position = Pubkey.new_unique()
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_WEAVE, position, stranger))
    with pytest.raises(TransactionRefused, match="fee payer is"):
        guard(encode(stranger, [*cu_ixs(), ix]))


def test_a_prebuilt_signature_is_refused() -> None:
    """The builder must hand back something unsigned. Anything else has been somewhere."""
    import base64

    position = Pubkey.new_unique()
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_WEAVE, position, OWNER))
    payer = Keypair()
    message = MessageV0.try_compile(payer.pubkey(), [*cu_ixs(), ix], [], Hash.new_unique())
    signed = VersionedTransaction(message, [payer])
    encoded = base64.b64encode(bytes(signed)).decode("ascii")
    with pytest.raises(TransactionRefused):
        guard(encoded, owner=payer.pubkey())


def test_a_transaction_with_no_dlmm_instruction_is_refused() -> None:
    with pytest.raises(TransactionRefused, match="no DLMM instruction"):
        guard(encode(OWNER, cu_ixs()))


# ======================================================================================
# The scaffolding programs, each with its own opcode rule.
# ======================================================================================


def test_an_spl_token_transfer_is_refused() -> None:
    """Allowing "the token program" would allow a drain. Opcode 3 is Transfer."""
    position = Pubkey.new_unique()
    transfer = Instruction(
        Pubkey.from_string(TOKEN_PROGRAM),
        bytes([3]) + struct.pack("<Q", 1_000_000),
        [AccountMeta(Pubkey.new_unique(), is_signer=False, is_writable=True) for _ in range(3)],
    )
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_WEAVE, position, OWNER))
    with pytest.raises(TransactionRefused, match="opcode 3 is not permitted"):
        guard(
            encode(OWNER, [*cu_ixs(), transfer, ix]),
            expected_pools=[NOSIS_WEAVE],
            expected_positions=[str(position)],
        )


def test_a_system_transfer_to_a_stranger_is_refused() -> None:
    """The one instruction that could empty the wallet gets the tightest rule."""
    position = Pubkey.new_unique()
    thief = Pubkey.new_unique()
    transfer = Instruction(
        Pubkey.from_string(SYSTEM_PROGRAM),
        struct.pack("<I", 2) + struct.pack("<Q", 15_000_000_000),
        [
            AccountMeta(OWNER, is_signer=True, is_writable=True),
            AccountMeta(thief, is_signer=False, is_writable=True),
        ],
    )
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_WEAVE, position, OWNER))
    with pytest.raises(TransactionRefused, match="only permitted destination"):
        guard(
            encode(OWNER, [*cu_ixs(), transfer, ix]),
            expected_pools=[NOSIS_WEAVE],
            expected_positions=[str(position)],
        )


def test_a_system_transfer_to_our_own_wsol_account_is_allowed_within_the_cap() -> None:
    position = Pubkey.new_unique()
    wsol = associated_token_address(OWNER, Pubkey.from_string(WSOL_MINT))
    transfer = Instruction(
        Pubkey.from_string(SYSTEM_PROGRAM),
        struct.pack("<I", 2) + struct.pack("<Q", 500_000),
        [
            AccountMeta(OWNER, is_signer=True, is_writable=True),
            AccountMeta(wsol, is_signer=False, is_writable=True),
        ],
    )
    ix = dlmm_ix("add_liquidity_by_strategy", remove_accounts(NOSIS_WEAVE, position, OWNER))
    guarded = guard(
        encode(OWNER, [*cu_ixs(), transfer, ix]),
        expected_pools=[NOSIS_WEAVE],
        expected_positions=[str(position)],
        max_wrap_lamports=1_000_000,
    )
    assert guarded.pools_touched == frozenset({NOSIS_WEAVE})

    with pytest.raises(TransactionRefused, match="would wrap"):
        guard(
            encode(OWNER, [*cu_ixs(), transfer, ix]),
            expected_pools=[NOSIS_WEAVE],
            expected_positions=[str(position)],
            max_wrap_lamports=1_000,
        )


def test_an_ata_created_for_someone_else_is_refused() -> None:
    position = Pubkey.new_unique()
    stranger = Pubkey.new_unique()
    ata = Instruction(
        Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM),
        b"\x01",
        [
            AccountMeta(OWNER, is_signer=True, is_writable=True),
            AccountMeta(Pubkey.new_unique(), is_signer=False, is_writable=True),
            AccountMeta(stranger, is_signer=False, is_writable=False),
        ],
    )
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_WEAVE, position, OWNER))
    with pytest.raises(TransactionRefused, match="only be created by us, for us"):
        guard(
            encode(OWNER, [*cu_ixs(), ata, ix]),
            expected_pools=[NOSIS_WEAVE],
            expected_positions=[str(position)],
        )


def test_a_priority_fee_above_the_cap_is_refused() -> None:
    position = Pubkey.new_unique()
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_WEAVE, position, OWNER))
    encoded = encode(OWNER, [*cu_ixs(limit=1_400_000, price=3_000_000), ix])
    with pytest.raises(TransactionRefused, match="exceeds the configured cap"):
        guard(
            encoded,
            expected_pools=[NOSIS_WEAVE],
            expected_positions=[str(position)],
            max_priority_fee_lamports=100_000,
        )


def test_a_heap_frame_request_is_refused() -> None:
    position = Pubkey.new_unique()
    heap = Instruction(
        Pubkey.from_string(COMPUTE_BUDGET_PROGRAM), bytes([1]) + struct.pack("<I", 256 * 1024), []
    )
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_WEAVE, position, OWNER))
    with pytest.raises(TransactionRefused, match="compute budget opcode"):
        guard(
            encode(OWNER, [*cu_ixs(), heap, ix]),
            expected_pools=[NOSIS_WEAVE],
            expected_positions=[str(position)],
        )


# ======================================================================================
# The second signer, and signing.
# ======================================================================================


def test_a_second_signer_we_did_not_create_is_refused() -> None:
    position = Keypair()
    ix = dlmm_ix(
        "initialize_position",
        [OWNER, position.pubkey(), Pubkey.from_string(NOSIS_WEAVE), OWNER],
    )
    ix = Instruction(
        ix.program_id,
        ix.data,
        [
            AccountMeta(OWNER, is_signer=True, is_writable=True),
            AccountMeta(position.pubkey(), is_signer=True, is_writable=True),
            AccountMeta(Pubkey.from_string(NOSIS_WEAVE), is_signer=False, is_writable=True),
            AccountMeta(OWNER, is_signer=False, is_writable=False),
        ],
    )
    encoded = encode(OWNER, [*cu_ixs(), ix], signers=2)
    with pytest.raises(TransactionRefused, match="which this plan did not create"):
        guard(
            encoded,
            expected_pools=[NOSIS_WEAVE],
            expected_positions=[str(position.pubkey())],
            extra_signers=[],
        )
    guarded = guard(
        encoded,
        expected_pools=[NOSIS_WEAVE],
        expected_positions=[str(position.pubkey())],
        extra_signers=[str(position.pubkey())],
    )
    assert guarded.transaction.message.header.num_required_signatures == 2


def test_signing_produces_a_locally_verified_transaction() -> None:
    wallet = Keypair()
    position = Pubkey.new_unique()
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_WEAVE, position, wallet.pubkey()))
    guarded = guard(
        encode(wallet.pubkey(), [*cu_ixs(), ix]),
        owner=wallet.pubkey(),
        expected_pools=[NOSIS_WEAVE],
        expected_positions=[str(position)],
    )
    signed = sign_guarded(guarded, wallet)
    assert signed.signers == (str(wallet.pubkey()),)
    assert len(signed.signature) > 60


def test_signing_without_the_required_key_refuses() -> None:
    wallet = Keypair()
    position = Pubkey.new_unique()
    ix = dlmm_ix("remove_liquidity_by_range", remove_accounts(NOSIS_WEAVE, position, wallet.pubkey()))
    guarded = guard(
        encode(wallet.pubkey(), [*cu_ixs(), ix]),
        owner=wallet.pubkey(),
        expected_pools=[NOSIS_WEAVE],
        expected_positions=[str(position)],
    )
    with pytest.raises(TransactionRefused, match="no key available"):
        sign_guarded(guarded, Keypair())


# ======================================================================================
# There is no send path.
# ======================================================================================


def test_the_rpc_client_cannot_broadcast() -> None:
    for method in ("sendTransaction", "sendRawTransaction", "requestAirdrop"):
        assert method not in READ_METHODS


def test_calling_a_write_method_raises_before_any_request(tmp_path: Path) -> None:
    key = tmp_path / "helius"
    key.write_text("fake-key", encoding="utf-8")
    os.chmod(key, 0o600)

    class ExplodingClient:
        def post(self, *_: object, **__: object) -> None:
            raise AssertionError("a write method must never reach the network")

        def close(self) -> None:
            return None

    rpc = HeliusRpc(key_file=key, client=ExplodingClient())  # type: ignore[arg-type]
    with pytest.raises(RpcError, match="not a method this package may call"):
        rpc.call("sendTransaction", ["deadbeef"])


def test_no_module_in_the_package_references_send_transaction() -> None:
    """A source-text check, so adding a send is a visible, deliberate act."""
    package = Path(__file__).resolve().parent.parent / "shitcoims_lpexec"
    for module in package.glob("*.py"):
        source = module.read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or '"""' in stripped or "READ_METHODS" in stripped:
                continue
            assert "sendTransaction" not in line or "no" in line.lower(), (
                f"{module.name} mentions sendTransaction outside a comment"
            )


# ======================================================================================
# Gates.
# ======================================================================================


def _config(tmp_path: Path, *, enabled: bool, with_key: bool) -> object:
    key_path = tmp_path / "wallet"
    if with_key:
        key_path.write_text(str(Keypair()), encoding="utf-8")
        os.chmod(key_path, 0o600)
    (tmp_path / "lpexec.yaml").write_text(
        f"""
wallet:
  address: {THA_FUNDS}
  secret_key_file: ./wallet
rpc:
  helius_api_key_file: ./helius
state_dir: ./state
execution:
  enabled: {"true" if enabled else "false"}
  arm_file: ./LPEXEC_ARMED
""",
        encoding="utf-8",
    )
    return load_config(tmp_path / "lpexec.yaml")


def test_all_three_gates_are_required(tmp_path: Path) -> None:
    config = _config(tmp_path, enabled=True, with_key=True)
    gate = ExecutionGate(config, cli_live=True)  # type: ignore[arg-type]
    assert gate.status().live is False  # arm file missing
    write_arm(config.execution.arm_file, gate.expected_arm_value)  # type: ignore[attr-defined]
    assert gate.status().live is True

    assert ExecutionGate(config, cli_live=False).status().live is False  # type: ignore[arg-type]
    closed = _config(tmp_path, enabled=False, with_key=True)
    write_arm(closed.execution.arm_file, ExecutionGate(closed, cli_live=True).expected_arm_value)  # type: ignore[attr-defined,arg-type]
    assert ExecutionGate(closed, cli_live=True).status().live is False  # type: ignore[arg-type]


def test_a_missing_key_file_is_a_gate_not_an_exception(tmp_path: Path) -> None:
    """The whole review workflow happens on a machine with no key. It must still run."""
    config = _config(tmp_path, enabled=True, with_key=False)
    gate = ExecutionGate(config, cli_live=True)  # type: ignore[arg-type]
    write_arm(config.execution.arm_file, gate.expected_arm_value)  # type: ignore[attr-defined]
    status = gate.status()
    assert status.live is False
    assert any("is absent (dry-run only)" in failure for failure in status.failures)


def test_a_group_readable_arm_file_disarms(tmp_path: Path) -> None:
    config = _config(tmp_path, enabled=True, with_key=True)
    gate = ExecutionGate(config, cli_live=True)  # type: ignore[arg-type]
    write_arm(config.execution.arm_file, gate.expected_arm_value)  # type: ignore[attr-defined]
    assert gate.status().live is True
    os.chmod(config.execution.arm_file, 0o644)  # type: ignore[attr-defined]
    status = gate.status()
    assert status.live is False
    assert any("unreadable" in failure for failure in status.failures)


def test_the_arm_value_is_package_scoped_and_wallet_bound(tmp_path: Path) -> None:
    config = _config(tmp_path, enabled=True, with_key=True)
    gate = ExecutionGate(config, cli_live=True)  # type: ignore[arg-type]
    assert gate.expected_arm_value == f"lpexec:{THA_FUNDS}"
    write_arm(config.execution.arm_file, f"shitcoims:{THA_FUNDS}")  # type: ignore[attr-defined]
    assert gate.status().live is False


def test_the_arm_file_is_written_at_0600(tmp_path: Path) -> None:
    path = tmp_path / "ARMED"
    write_arm(path, "lpexec:x")
    assert (path.stat().st_mode & 0o777) == 0o600


# ======================================================================================
# Secrets.
# ======================================================================================


def test_a_world_readable_secret_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "key"
    path.write_text("value", encoding="utf-8")
    os.chmod(path, 0o644)
    with pytest.raises(SecretError, match="group/world accessible"):
        read_secret_file(path)


def test_a_key_for_the_wrong_wallet_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "wallet"
    other = Keypair()
    path.write_text(str(other), encoding="utf-8")
    os.chmod(path, 0o600)
    load_keypair(path)  # no expectation: fine
    with pytest.raises(SecretError, match="but this package manages"):
        load_keypair(path, expected_pubkey=THA_FUNDS)


# ======================================================================================
# Config.
# ======================================================================================


def test_a_missing_config_is_dry_run_not_an_error(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.yaml")
    assert config.execution.enabled is False


def test_a_malformed_config_raises_rather_than_silently_defaulting(tmp_path: Path) -> None:
    path = tmp_path / "lpexec.yaml"
    path.write_text("execution:\n  enabled: true\n bad indent here\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(path)


def test_a_string_boolean_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "lpexec.yaml"
    path.write_text('execution:\n  enabled: "true"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a YAML boolean"):
        load_config(path)


def test_a_config_naming_another_wallet_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "lpexec.yaml"
    path.write_text(f"wallet:\n  address: {Keypair().pubkey()}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="this package manages one wallet"):
        load_config(path)


def test_a_day_cap_below_the_transaction_cap_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "lpexec.yaml"
    path.write_text(
        "execution:\n  per_tx_max_sol_lamports: 500000000\n  per_day_max_sol_lamports: 100000000\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="below the per-transaction cap"):
        load_config(path)


def test_the_default_config_is_closed() -> None:
    config = default_config()
    assert config.execution.enabled is False
    assert config.wallet_address == THA_FUNDS


# ======================================================================================
# Bin math and rent.
# ======================================================================================


def test_bin_prices_round_trip_through_the_inverse() -> None:
    for bin_id in (-594, -100, 0, 14, 34, 500):
        price = binmath.bin_price_ui(bin_id, 100, decimals_x=6, decimals_y=9)
        assert binmath.price_to_bin_id(price, 100, decimals_x=6, decimals_y=9) == bin_id


def test_bin_prices_match_the_live_nosis_weave_position() -> None:
    """Checked against the SDK's own per-bin `pricePerToken` for the real position."""
    assert binmath.bin_price_ui(0, 200, decimals_x=6, decimals_y=6) == pytest.approx(1.0)
    assert binmath.bin_price_ui(1, 200, decimals_x=6, decimals_y=6) == pytest.approx(1.02)
    assert binmath.bin_price_ui(34, 200, decimals_x=6, decimals_y=6) == pytest.approx(
        1.9606760320220148, rel=1e-12
    )
    assert binmath.bin_price_ui(-20, 200, decimals_x=6, decimals_y=6) == pytest.approx(
        0.6729713331080577, rel=1e-12
    )


def test_bin_array_index_floors_toward_negative_infinity() -> None:
    assert binmath.bin_array_index(0) == 0
    assert binmath.bin_array_index(69) == 0
    assert binmath.bin_array_index(70) == 1
    assert binmath.bin_array_index(-1) == -1
    assert binmath.bin_array_index(-594) == -9
    assert binmath.bin_array_indexes(-593, -568) == (-9,)


def test_bin_array_pdas_match_the_meteora_sdk() -> None:
    """Values produced by `@meteora-ag/dlmm@1.9.14`'s own deriveBinArray for this pool."""
    assert str(bin_array_key(NOSIS_WEAVE, 0)) == "9hYMwzgiscCr3jFcw23NLQnQckT8rLZvxK9suKXZsXGW"
    assert str(bin_array_key(NOSIS_WEAVE, 1)) == "F6UxBqZL2hdyQ2UQacUsniyDud4G77hzLaZnRuDwCbHQ"
    assert str(bin_array_key(NOSIS_WEAVE, -9)) == "8D8nKhBzsrSiTjGhaTApfzb21DRi9KxZ8SyLLDyk4BMa"


def test_rent_constants_match_the_meteora_sdk() -> None:
    """Read straight out of node_modules, so an SDK bump that moves them fails here."""
    sdk = (
        Path(__file__).resolve().parent.parent
        / "shitcoims_lpexec"
        / "node"
        / "node_modules"
        / "@meteora-ag"
        / "dlmm"
        / "dist"
        / "index.js"
    )
    if not sdk.exists():
        pytest.skip("the sidecar is not installed; run npm install in shitcoims_lpexec/node")
    source = sdk.read_text(encoding="utf-8", errors="ignore")
    assert "0.05740608" in source, "POSITION_FEE moved"
    assert "0.07143744" in source, "BIN_ARRAY_FEE moved"
    assert binmath.POSITION_RENT_LAMPORTS == 57_406_080
    assert binmath.BIN_ARRAY_RENT_LAMPORTS == 71_437_440


def test_rent_separates_refundable_from_non_refundable() -> None:
    quote = binmath.quote_rent(
        lower_bin_id=0, upper_bin_id=140, existing_bin_arrays=frozenset({0}), opens_position=True
    )
    assert quote.new_bin_arrays == (1, 2)
    assert quote.non_refundable == 2 * binmath.BIN_ARRAY_RENT_LAMPORTS
    assert quote.refundable == binmath.POSITION_RENT_LAMPORTS
    assert "NOT refundable" in quote.describe()


def test_an_existing_bin_array_costs_nothing() -> None:
    """Both the occupied array AND the padded upper one must exist for a deposit to be free."""
    quote = binmath.quote_rent(
        lower_bin_id=-593,
        upper_bin_id=-568,
        existing_bin_arrays=frozenset({-9, -8}),
        opens_position=True,
    )
    assert quote.non_refundable == 0


def test_a_deposit_pays_for_the_next_array_even_inside_one_array() -> None:
    """The rule the SDK cross-check caught: `upper = max(index(upper), index(lower) + 1)`.

    Bins -314..-305 all live in array -5, so the geometric answer is one array. A DEPOSIT
    initialises array -4 as well, and pricing it at zero understates the plan by 0.0714 SOL
    of rent that never comes back.
    """
    assert binmath.bin_array_indexes(-314, -305) == (-5,)
    assert binmath.deposit_bin_array_indexes(-314, -305) == (-5, -4)
    free = binmath.quote_rent(
        lower_bin_id=-314, upper_bin_id=-305, existing_bin_arrays=frozenset({-5}), opens_position=False
    )
    assert free.non_refundable == 0
    deposit = binmath.quote_rent(
        lower_bin_id=-314, upper_bin_id=-305, existing_bin_arrays=frozenset({-5}), opens_position=True
    )
    assert deposit.new_bin_arrays == (-4,)
    assert deposit.non_refundable == binmath.BIN_ARRAY_RENT_LAMPORTS


# ======================================================================================
# Planner.
# ======================================================================================


def _live_bins() -> list[BinHolding]:
    """The real nosis-side distribution read off chain on 2026-08-15, in raw units."""
    amounts = {
        14: 105408156006, 15: 108044836140, 16: 105926309941, 17: 103849323471,
        18: 101813062226, 19: 99816727672, 20: 97859536934, 21: 95940722484,
        22: 94059531847, 23: 92215227301, 24: 90407085589, 25: 88634397636,
        26: 86896468271, 27: 85192615952, 28: 83522172502, 29: 81884482845,
        30: 80278904750, 31: 78704808578, 32: 77161577038, 33: 75648604939,
        34: 74165298960,
    }
    return [
        BinHolding(
            bin_id=bin_id,
            price_per_token=binmath.bin_price_ui(bin_id, 200, decimals_x=6, decimals_y=6),
            amount_x_raw=raw,
            amount_y_raw=0,
        )
        for bin_id, raw in amounts.items()
    ]


def test_the_trim_removes_from_the_top_of_the_range() -> None:
    plan = plan_trim(
        pool=NOSIS_WEAVE,
        position="E829RTKuqZWXyvwYuJw9WS4LyaCjd1xrDGpYBDkuBpLP",
        bins=_live_bins(),
        active_bin_id=14,
        bin_step=200,
        decimals_x=6,
        price_x_usd=0.0002043214,
        target_x_usd=200.0,
        token_x_symbol="nosis",
    )
    assert plan.steps[0].to_bin_id == 34, "the highest bin must be in the first step"
    assert plan.steps[0].bps == 10_000
    assert plan.steps[-1].bps < 10_000, "the boundary bin is taken partially, not averaged"
    assert min(plan.removed_bin_ids) > 14, "bins at the active end are kept, not diluted"
    assert plan.retained_x_usd == pytest.approx(200.0, abs=1.0)
    assert plan.remove_x_raw + plan.retained_x_raw == plan.held_x_raw


def test_a_position_already_below_target_plans_no_removal() -> None:
    plan = plan_trim(
        pool=NOSIS_WEAVE,
        position="P",
        bins=_live_bins(),
        active_bin_id=14,
        bin_step=200,
        decimals_x=6,
        price_x_usd=0.0002043214,
        target_x_usd=10_000.0,
    )
    assert plan.steps == ()
    assert plan.remove_x_raw == 0
    assert "already at or below" in plan.notes[0]


def test_a_position_with_no_token_x_refuses() -> None:
    with pytest.raises(PlanRefused, match="holds no"):
        plan_trim(
            pool=NOSIS_WEAVE,
            position="P",
            bins=[BinHolding(0, 1.0, 0, 500)],
            active_bin_id=14,
            bin_step=200,
            decimals_x=6,
            price_x_usd=1.0,
            target_x_usd=10.0,
        )


def test_the_ladder_sits_strictly_above_spot() -> None:
    plan = plan_ladder(
        pool=NOSIS_SOL,
        label="nosis/SOL",
        active_bin_id=-594,
        bin_step=100,
        decimals_x=6,
        decimals_y=9,
        deposit_x_raw=928_584_104_863,
        price_x_usd=0.0002043214,
        sol_price_usd=75.4,
        existing_bin_arrays=frozenset({-9, -8}),
        reach_pct=20.0,
    )
    assert plan.min_bin_id == -593, "an ask ladder starts one bin above the active bin"
    assert all(rung.bin_id > -594 for rung in plan.rungs)
    assert all(rung.pct_above_spot > 0 for rung in plan.rungs)
    assert plan.reach_pct >= 20.0
    assert sum(rung.amount_x_raw for rung in plan.rungs) == plan.deposit_x_raw


def test_the_ladder_prefers_the_tight_width_at_equal_rent() -> None:
    """Free extra reach parks inventory where the flow is not. Tight wins on a tie."""
    plan = plan_ladder(
        pool=NOSIS_SOL,
        label="nosis/SOL",
        active_bin_id=-594,
        bin_step=100,
        decimals_x=6,
        decimals_y=9,
        deposit_x_raw=928_584_104_863,
        price_x_usd=0.0002043214,
        sol_price_usd=75.4,
        existing_bin_arrays=frozenset({-9, -8}),
        reach_pct=20.0,
    )
    assert len(plan.rungs) == 19, "19 bins at 1%/bin is the narrowest width clearing +20%"
    assert plan.rent.non_refundable == 0


def test_a_ladder_whose_rent_swamps_the_deposit_is_refused() -> None:
    """A tiny deposit across virgin bin arrays is a donation, and is refused as one."""
    with pytest.raises(PlanRefused, match="non-refundable bin-array rent"):
        plan_ladder(
            pool=NOSIS_SOL,
            label="nosis/SOL",
            active_bin_id=-594,
            bin_step=100,
            decimals_x=6,
            decimals_y=9,
            deposit_x_raw=1_000_000,  # $0.20 of nosis
            price_x_usd=0.0002043214,
            sol_price_usd=75.4,
            existing_bin_arrays=frozenset(),  # every array virgin
            reach_pct=20.0,
        )


def test_an_empty_ladder_deposit_is_refused() -> None:
    with pytest.raises(PlanRefused, match="needs something to deposit"):
        plan_ladder(
            pool=NOSIS_SOL,
            label="nosis/SOL",
            active_bin_id=-594,
            bin_step=100,
            decimals_x=6,
            decimals_y=9,
            deposit_x_raw=0,
            price_x_usd=1.0,
            sol_price_usd=75.4,
            existing_bin_arrays=frozenset({-9, -8}),
        )


def test_the_rent_share_ceiling_is_calibrated_against_the_measured_ladder_edge() -> None:
    """4% is ~2.5x the +1.4-2.0% edge RESULT_toll_positioning.md sec.4 measured."""
    assert planner.MAX_RENT_SHARE_OF_DEPLOYED == 0.04


# ======================================================================================
# Ledger.
# ======================================================================================


def test_every_row_carries_two_clocks_and_a_run_id(tmp_path: Path) -> None:
    with Ledger(tmp_path, run_id="lpx-test") as ledger:
        ledger.emit("plan", step="trim", pool=NOSIS_WEAVE)
    rows = read_day(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "lpx-test"
    assert row["t_ingest"].endswith("+00:00")
    assert row["t_event"] is None
    assert row["t_event_source"].startswith("absent:")


def test_an_unknown_row_kind_raises_at_write_time(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger, pytest.raises(KeyError, match="not a known lpexec row kind"):
        ledger.emit("kaboom")


def test_a_field_colliding_with_the_envelope_raises(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger, pytest.raises(KeyError, match="collide"):
        ledger.emit("plan", run_id="sneaky")


def test_the_reconciliation_row_has_all_three_columns_and_a_classification(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        ledger.reconcile(
            step="trim",
            pool=NOSIS_WEAVE,
            position="P",
            intended={"expected_x_raw": "902496420000"},
            simulated={"units_consumed": 79391},
            actual=None,
        )
    row = read_day(tmp_path)[0]
    assert set(row) >= {"intended", "simulated", "actual", "divergence_class"}
    assert row["actual"] is None
    assert row["divergence_class"] == "pending", "a program must not classify its own errors"


def test_an_invalid_divergence_class_raises(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger, pytest.raises(KeyError, match="not a divergence class"):
        ledger.reconcile(
            step="s", pool="p", position=None, intended={}, simulated=None, actual=None,
            divergence_class="probably_fine",
        )


def test_the_day_cap_counts_only_submitted_rows(tmp_path: Path) -> None:
    """A day of dry-run review must not exhaust a cap that bounds real spending."""
    with Ledger(tmp_path) as ledger:
        ledger.emit("plan", step="trim", sol_lamports=999_000_000, token_usd=5_000.0)
        ledger.emit("simulate", step="trim", sol_lamports=999_000_000)
        ledger.emit("submit", step="trim", sol_lamports=57_406_080, token_usd=189.73)
    spend = day_spend(tmp_path)
    assert spend.transactions == 1
    assert spend.sol_lamports == 57_406_080
    assert spend.token_usd == pytest.approx(189.73)


def test_rows_are_one_json_object_per_line_sorted(tmp_path: Path) -> None:
    with Ledger(tmp_path) as ledger:
        ledger.heartbeat(stage="test", scanned=3)
        ledger.defect(reason="x")
    path = next(tmp_path.glob("lpexec-*.jsonl"))
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert parsed["schema"] == "lpexec.v1"
    assert day_spend(tmp_path, time.time()).transactions == 0


# ======================================================================================
# The allowlist itself.
# ======================================================================================


def test_every_allowlisted_discriminator_is_derived_from_its_name() -> None:
    """A typo in a hex string is a hole. This recomputes all of them."""
    for disc, spec in ALLOWED_DLMM.items():
        assert disc == hashlib.sha256(f"global:{spec.name}".encode()).digest()[:8].hex()


def test_the_allowlist_agrees_with_the_independently_derived_cluster_table() -> None:
    """`shitcoims_cluster/pools.py` derived these while decoding live mainnet swaps."""
    from shitcoims_cluster.pools import KNOWN_DISCRIMINATORS

    for disc, name in KNOWN_DISCRIMINATORS.items():
        if disc in ALLOWED_DLMM:
            assert ALLOWED_DLMM[disc].name == name
        if name.startswith("swap"):
            assert disc not in ALLOWED_DLMM, f"{name} must never be allowlisted"


def test_every_allowlisted_pool_is_a_dlmm_pool_we_have_seen() -> None:
    from shitcoims_lpexec.allowlist import POOLS

    assert NOSIS_WEAVE in POOLS
    assert NOSIS_SOL in POOLS
    for pool in POOLS.values():
        assert len(pool.address) >= 32
        assert pool.token_x_mint != pool.token_y_mint
        assert pool.bin_step > 0


def test_the_pumpswap_pools_are_not_allowlisted() -> None:
    """They are swap venues on a different program. An LP tool has no business there."""
    from shitcoims_cluster.pools import CLUSTER_POOLS
    from shitcoims_lpexec.allowlist import POOLS

    for spec in CLUSTER_POOLS:
        if spec.dex == "pumpswap":
            assert spec.address not in POOLS
