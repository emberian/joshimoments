"""Pinned, hand-auditable Borsh layouts for advisory Pump intelligence.

These layouts were independently transcribed from the official Pump public IDLs at
``pump-fun/pump-public-docs@9c82f61cb711b044a17f770ab8ce9f9bdf78f333``.
The hashes below make accidental source drift visible without loading an IDL at
runtime.  Updating a layout requires updating the commit, hash, and decoder tests
together.

This module deliberately contains event data only.  It has no execution concepts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias

PUMP_PROGRAM_ID: Final = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_AMM_PROGRAM_ID: Final = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"

SCHEMA_REPOSITORY: Final = "https://github.com/pump-fun/pump-public-docs"
SCHEMA_COMMIT: Final = "9c82f61cb711b044a17f770ab8ce9f9bdf78f333"
PUMP_IDL_SHA256: Final = "b90bc471327f671449271d5d1d42354d1fae6f5a06502f5834459a3108138e49"
PUMP_AMM_IDL_SHA256: Final = "6b5c7ec4e5ef9742fa99dc57b0d75b1031b379bba02a7e1b3c5a4cad68d77e56"

# A conservative application boundary independent of the Borsh u32 theoretical
# maximum.  Current supported events are far smaller than this.
MAX_EVENT_BYTES: Final = 16 * 1024
MAX_BORSH_STRING_BYTES: Final = 4 * 1024
MAX_SHAREHOLDERS: Final = 10

# The IDL itself does not express string maxima.  These decoder-only limits are
# intentionally generous relative to normal Pump values while bounding allocation.
STRING_BYTE_LIMITS: Final[dict[str, int]] = {
    "name": 256,
    "symbol": 64,
    "uri": 4 * 1024,
    "ix_name": 64,
}

Primitive: TypeAlias = str
TypeSpec: TypeAlias = Primitive | tuple[str, object]
FieldLayout: TypeAlias = tuple[str, TypeSpec]


@dataclass(frozen=True, slots=True)
class EventLayout:
    program_id: str
    event_name: str
    discriminator: bytes
    fields: tuple[FieldLayout, ...]
    idl_path: str
    idl_sha256: str


SHAREHOLDER_LAYOUT: Final[tuple[FieldLayout, ...]] = (
    ("address", "pubkey"),
    ("share_bps", "u16"),
)

PUMP_EVENT_LAYOUTS: Final = (
    EventLayout(
        PUMP_PROGRAM_ID,
        "CreateEvent",
        bytes((27, 114, 169, 77, 222, 235, 99, 118)),
        (
            ("name", "string"),
            ("symbol", "string"),
            ("uri", "string"),
            ("mint", "pubkey"),
            ("bonding_curve", "pubkey"),
            ("user", "pubkey"),
            ("creator", "pubkey"),
            ("timestamp", "i64"),
            ("virtual_token_reserves", "u64"),
            ("virtual_sol_reserves", "u64"),
            ("real_token_reserves", "u64"),
            ("token_total_supply", "u64"),
            ("token_program", "pubkey"),
            ("is_mayhem_mode", "bool"),
            ("is_cashback_enabled", "bool"),
            ("quote_mint", "pubkey"),
            ("virtual_quote_reserves", "u64"),
        ),
        "idl/pump.json",
        PUMP_IDL_SHA256,
    ),
    EventLayout(
        PUMP_PROGRAM_ID,
        "TradeEvent",
        bytes((189, 219, 127, 211, 78, 230, 97, 238)),
        (
            ("mint", "pubkey"),
            ("sol_amount", "u64"),
            ("token_amount", "u64"),
            ("is_buy", "bool"),
            ("user", "pubkey"),
            ("timestamp", "i64"),
            ("virtual_sol_reserves", "u64"),
            ("virtual_token_reserves", "u64"),
            ("real_sol_reserves", "u64"),
            ("real_token_reserves", "u64"),
            ("fee_recipient", "pubkey"),
            ("fee_basis_points", "u64"),
            ("fee", "u64"),
            ("creator", "pubkey"),
            ("creator_fee_basis_points", "u64"),
            ("creator_fee", "u64"),
            ("track_volume", "bool"),
            ("total_unclaimed_tokens", "u64"),
            ("total_claimed_tokens", "u64"),
            ("current_sol_volume", "u64"),
            ("last_update_timestamp", "i64"),
            ("ix_name", "string"),
            ("mayhem_mode", "bool"),
            ("cashback_fee_basis_points", "u64"),
            ("cashback", "u64"),
            ("buyback_fee_basis_points", "u64"),
            ("buyback_fee", "u64"),
            ("shareholders", ("vec", SHAREHOLDER_LAYOUT, MAX_SHAREHOLDERS)),
            ("quote_mint", "pubkey"),
            ("quote_amount", "u64"),
            ("virtual_quote_reserves", "u64"),
            ("real_quote_reserves", "u64"),
        ),
        "idl/pump.json",
        PUMP_IDL_SHA256,
    ),
    EventLayout(
        PUMP_PROGRAM_ID,
        "CompleteEvent",
        bytes((95, 114, 97, 156, 212, 46, 152, 8)),
        (
            ("user", "pubkey"),
            ("mint", "pubkey"),
            ("bonding_curve", "pubkey"),
            ("timestamp", "i64"),
            ("quote_mint", "pubkey"),
        ),
        "idl/pump.json",
        PUMP_IDL_SHA256,
    ),
    EventLayout(
        PUMP_PROGRAM_ID,
        "CompletePumpAmmMigrationEvent",
        bytes((189, 233, 93, 185, 92, 148, 234, 148)),
        (
            ("user", "pubkey"),
            ("mint", "pubkey"),
            ("mint_amount", "u64"),
            ("sol_amount", "u64"),
            ("pool_migration_fee", "u64"),
            ("bonding_curve", "pubkey"),
            ("timestamp", "i64"),
            ("pool", "pubkey"),
            ("quote_mint", "pubkey"),
        ),
        "idl/pump.json",
        PUMP_IDL_SHA256,
    ),
)

PUMP_AMM_EVENT_LAYOUTS: Final = (
    EventLayout(
        PUMP_AMM_PROGRAM_ID,
        "CreatePoolEvent",
        bytes((177, 49, 12, 210, 160, 118, 167, 116)),
        (
            ("timestamp", "i64"),
            ("index", "u16"),
            ("creator", "pubkey"),
            ("base_mint", "pubkey"),
            ("quote_mint", "pubkey"),
            ("base_mint_decimals", "u8"),
            ("quote_mint_decimals", "u8"),
            ("base_amount_in", "u64"),
            ("quote_amount_in", "u64"),
            ("pool_base_amount", "u64"),
            ("pool_quote_amount", "u64"),
            ("minimum_liquidity", "u64"),
            ("initial_liquidity", "u64"),
            ("lp_token_amount_out", "u64"),
            ("pool_bump", "u8"),
            ("pool", "pubkey"),
            ("lp_mint", "pubkey"),
            ("user_base_token_account", "pubkey"),
            ("user_quote_token_account", "pubkey"),
            ("coin_creator", "pubkey"),
            ("is_mayhem_mode", "bool"),
        ),
        "idl/pump_amm.json",
        PUMP_AMM_IDL_SHA256,
    ),
    EventLayout(
        PUMP_AMM_PROGRAM_ID,
        "BuyEvent",
        bytes((103, 244, 82, 31, 44, 245, 119, 119)),
        (
            ("timestamp", "i64"),
            ("base_amount_out", "u64"),
            ("max_quote_amount_in", "u64"),
            ("user_base_token_reserves", "u64"),
            ("user_quote_token_reserves", "u64"),
            ("pool_base_token_reserves", "u64"),
            ("pool_quote_token_reserves", "u64"),
            ("quote_amount_in", "u64"),
            ("lp_fee_basis_points", "u64"),
            ("lp_fee", "u64"),
            ("protocol_fee_basis_points", "u64"),
            ("protocol_fee", "u64"),
            ("quote_amount_in_with_lp_fee", "u64"),
            ("user_quote_amount_in", "u64"),
            ("pool", "pubkey"),
            ("user", "pubkey"),
            ("user_base_token_account", "pubkey"),
            ("user_quote_token_account", "pubkey"),
            ("protocol_fee_recipient", "pubkey"),
            ("protocol_fee_recipient_token_account", "pubkey"),
            ("coin_creator", "pubkey"),
            ("coin_creator_fee_basis_points", "u64"),
            ("coin_creator_fee", "u64"),
            ("track_volume", "bool"),
            ("total_unclaimed_tokens", "u64"),
            ("total_claimed_tokens", "u64"),
            ("current_sol_volume", "u64"),
            ("last_update_timestamp", "i64"),
            ("min_base_amount_out", "u64"),
            ("ix_name", "string"),
            ("cashback_fee_basis_points", "u64"),
            ("cashback", "u64"),
            ("buyback_fee_basis_points", "u64"),
            ("buyback_fee", "u64"),
            ("virtual_quote_reserves", "i128"),
            ("can_boost", "bool"),
            ("base_supply", "u64"),
        ),
        "idl/pump_amm.json",
        PUMP_AMM_IDL_SHA256,
    ),
    EventLayout(
        PUMP_AMM_PROGRAM_ID,
        "SellEvent",
        bytes((62, 47, 55, 10, 165, 3, 220, 42)),
        (
            ("timestamp", "i64"),
            ("base_amount_in", "u64"),
            ("min_quote_amount_out", "u64"),
            ("user_base_token_reserves", "u64"),
            ("user_quote_token_reserves", "u64"),
            ("pool_base_token_reserves", "u64"),
            ("pool_quote_token_reserves", "u64"),
            ("quote_amount_out", "u64"),
            ("lp_fee_basis_points", "u64"),
            ("lp_fee", "u64"),
            ("protocol_fee_basis_points", "u64"),
            ("protocol_fee", "u64"),
            ("quote_amount_out_without_lp_fee", "u64"),
            ("user_quote_amount_out", "u64"),
            ("pool", "pubkey"),
            ("user", "pubkey"),
            ("user_base_token_account", "pubkey"),
            ("user_quote_token_account", "pubkey"),
            ("protocol_fee_recipient", "pubkey"),
            ("protocol_fee_recipient_token_account", "pubkey"),
            ("coin_creator", "pubkey"),
            ("coin_creator_fee_basis_points", "u64"),
            ("coin_creator_fee", "u64"),
            ("cashback_fee_basis_points", "u64"),
            ("cashback", "u64"),
            ("buyback_fee_basis_points", "u64"),
            ("buyback_fee", "u64"),
            ("virtual_quote_reserves", "i128"),
            ("can_boost", "bool"),
            ("base_supply", "u64"),
        ),
        "idl/pump_amm.json",
        PUMP_AMM_IDL_SHA256,
    ),
    EventLayout(
        PUMP_AMM_PROGRAM_ID,
        "DepositEvent",
        bytes((120, 248, 61, 83, 31, 142, 107, 144)),
        (
            ("timestamp", "i64"),
            ("lp_token_amount_out", "u64"),
            ("max_base_amount_in", "u64"),
            ("max_quote_amount_in", "u64"),
            ("user_base_token_reserves", "u64"),
            ("user_quote_token_reserves", "u64"),
            ("pool_base_token_reserves", "u64"),
            ("pool_quote_token_reserves", "u64"),
            ("base_amount_in", "u64"),
            ("quote_amount_in", "u64"),
            ("lp_mint_supply", "u64"),
            ("pool", "pubkey"),
            ("user", "pubkey"),
            ("user_base_token_account", "pubkey"),
            ("user_quote_token_account", "pubkey"),
            ("user_pool_token_account", "pubkey"),
        ),
        "idl/pump_amm.json",
        PUMP_AMM_IDL_SHA256,
    ),
    EventLayout(
        PUMP_AMM_PROGRAM_ID,
        "WithdrawEvent",
        bytes((22, 9, 133, 26, 160, 44, 71, 192)),
        (
            ("timestamp", "i64"),
            ("lp_token_amount_in", "u64"),
            ("min_base_amount_out", "u64"),
            ("min_quote_amount_out", "u64"),
            ("user_base_token_reserves", "u64"),
            ("user_quote_token_reserves", "u64"),
            ("pool_base_token_reserves", "u64"),
            ("pool_quote_token_reserves", "u64"),
            ("base_amount_out", "u64"),
            ("quote_amount_out", "u64"),
            ("lp_mint_supply", "u64"),
            ("pool", "pubkey"),
            ("user", "pubkey"),
            ("user_base_token_account", "pubkey"),
            ("user_quote_token_account", "pubkey"),
            ("user_pool_token_account", "pubkey"),
        ),
        "idl/pump_amm.json",
        PUMP_AMM_IDL_SHA256,
    ),
)

SUPPORTED_LAYOUTS: Final = PUMP_EVENT_LAYOUTS + PUMP_AMM_EVENT_LAYOUTS
LAYOUTS_BY_PROGRAM: Final = {
    PUMP_PROGRAM_ID: {layout.discriminator: layout for layout in PUMP_EVENT_LAYOUTS},
    PUMP_AMM_PROGRAM_ID: {layout.discriminator: layout for layout in PUMP_AMM_EVENT_LAYOUTS},
}
PROGRAM_FOR_DISCRIMINATOR: Final = {
    layout.discriminator: layout.program_id for layout in SUPPORTED_LAYOUTS
}
