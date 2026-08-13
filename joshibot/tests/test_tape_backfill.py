"""Tests for the MELT and RED-PUMP loaders.

Neither archive was obtainable in this environment, so these run against synthetic fixtures
in the documented shape. What they pin is not the column names — those are a declared guess
in :class:`MeltFieldMap` / :class:`RedPumpFieldMap` — but the *contract*: what a censored
label is allowed to become, where it is allowed to live, and which units are refused.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from shitcoims_tape import EventKind, Side, TapeEvent, WatchClose, WatchWindow, tape_health
from shitcoims_tape.backfill import (
    MELT_SOURCE,
    RED_PUMP_MEASURED_DISPLACEMENT_SECONDS,
    RED_PUMP_SOURCE,
    BackfillError,
    BackfillReport,
    MeltFieldMap,
    RedPumpFieldMap,
    SidecarWriter,
    load_melt,
    load_red_pump,
    read_records,
)
from shitcoims_tape.schema import _MINT

FETCHED = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
SIG_A = "5" * 88
SIG_B = "4" * 88


def _mint() -> str:
    return str(Keypair().pubkey())


def _jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _split(items: list[object]) -> tuple[list[TapeEvent], BackfillReport]:
    events = [item for item in items if isinstance(item, TapeEvent)]
    reports = [item for item in items if isinstance(item, BackfillReport)]
    assert len(reports) == 1
    return events, reports[0]


# --- RED-PUMP: the censored corpus -------------------------------------------------


def test_every_red_pump_record_carries_a_displaced_watch_so_the_tape_is_never_complete(
    tmp_path: Path,
) -> None:
    """Its labels came from a top-50-newest poller: a "did not graduate" may simply be unseen."""

    mint = _mint()
    path = _jsonl(
        tmp_path / "red-pump.jsonl",
        [
            {
                "mint": mint,
                "creator": _mint(),
                "name": "Zoo",
                "symbol": "ZOO",
                "created_at": "2026-08-01T00:00:00+00:00",
                "outcome": "not_graduated",
            }
        ],
    )
    events, report = _split(
        list(
            load_red_pump(
                path,
                displacement_window_seconds=RED_PUMP_MEASURED_DISPLACEMENT_SECONDS,
                fetched_at=FETCHED,
            )
        )
    )

    kinds = [event.kind for event in events]
    assert kinds == [EventKind.LAUNCH, EventKind.WATCH]
    window = events[1].body
    assert isinstance(window, WatchWindow)
    assert window.close_reason is WatchClose.DISPLACED
    assert window.is_informatively_censored
    # The window is 2.77 minutes wide inside a deadline the labels claim covers 24 hours.
    opened = datetime.fromisoformat(window.opened_at)
    assert (datetime.fromisoformat(window.closed_at or "") - opened).total_seconds() == 166
    assert (datetime.fromisoformat(window.deadline) - opened).total_seconds() == 86400

    health = tape_health(observed_trades=1, reference_trades=1, watches=[window])
    assert health.censoring_rate == 1.0
    assert health.complete is False
    assert report.launches == 1 and report.watches == 1


def test_the_outcome_label_never_reaches_the_tape_and_the_sidecar_flags_it(tmp_path: Path) -> None:
    """A label that can be joined by accident is a label that will be used as ground truth."""

    mint = _mint()
    path = _jsonl(
        tmp_path / "red-pump.jsonl",
        [
            {
                "mint": mint,
                "creator": _mint(),
                "name": "Zoo",
                "symbol": "ZOO",
                "created_at": "2026-08-01T00:00:00+00:00",
                "outcome": "graduated",
            }
        ],
    )
    sidecar = SidecarWriter(tmp_path / "red_pump_outcomes.jsonl")
    events, report = _split(
        list(
            load_red_pump(
                path,
                displacement_window_seconds=166,
                fetched_at=FETCHED,
                outcome_sidecar=sidecar,
            )
        )
    )
    sidecar.close()

    serialised = "\n".join(event.to_jsonl() for event in events)
    assert "graduated" not in serialised  # the label value never appears anywhere
    for event in events:
        assert "outcome" not in json.loads(event.to_jsonl())["body"]
    # The provenance does say the labels were censored -- that is the point, not a leak.
    assert all("outcome_labels=censored" in (event.provenance.cursor or "") for event in events)

    rows = [json.loads(line) for line in sidecar.path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["mint"] == mint
    assert rows[0]["outcome"] == "graduated"
    assert rows[0]["is_graduation_ground_truth"] is False
    assert rows[0]["censoring"] == "displacement"
    assert report.sidecar_rows == 1


def test_the_displacement_assumption_is_stamped_into_every_row_it_produced(tmp_path: Path) -> None:
    """It is not in the archive, so it must travel with the data that depends on it."""

    path = _jsonl(
        tmp_path / "red-pump.jsonl",
        [
            {
                "mint": _mint(),
                "creator": _mint(),
                "created_at": "2026-08-01T00:00:00+00:00",
                "outcome": "x",
            }
        ],
    )
    events, _report = _split(
        list(load_red_pump(path, displacement_window_seconds=166, fetched_at=FETCHED))
    )
    for event in events:
        assert event.provenance.source == RED_PUMP_SOURCE
        assert "displacement_window_s=166" in (event.provenance.cursor or "")
        assert "outcome_labels=censored" in (event.provenance.cursor or "")


def test_a_recorded_observation_window_beats_the_run_wide_assumption(tmp_path: Path) -> None:
    path = _jsonl(
        tmp_path / "red-pump.jsonl",
        [
            {
                "mint": _mint(),
                "creator": _mint(),
                "created_at": "2026-08-01T00:00:00+00:00",
                "last_seen_at": "2026-08-01T00:07:00+00:00",
            }
        ],
    )
    events, _report = _split(
        list(load_red_pump(path, displacement_window_seconds=166, fetched_at=FETCHED))
    )
    window = events[1].body
    assert isinstance(window, WatchWindow)
    assert window.closed_at == "2026-08-01T00:07:00+00:00"


def test_a_red_pump_launch_carries_no_chainstamp_it_could_be_ordered_by(tmp_path: Path) -> None:
    """It is a launch registry, not a transaction archive. A fabricated slot would order it."""

    path = _jsonl(
        tmp_path / "red-pump.jsonl",
        [{"mint": _mint(), "creator": _mint(), "created_at": "2026-08-01T00:00:00+00:00"}],
    )
    events, _report = _split(
        list(load_red_pump(path, displacement_window_seconds=166, fetched_at=FETCHED))
    )
    assert events[0].kind is EventKind.LAUNCH
    assert events[0].chain is None


def test_a_naive_archive_timestamp_is_refused_until_someone_declares_it_utc(tmp_path: Path) -> None:
    path = _jsonl(
        tmp_path / "red-pump.jsonl",
        [{"mint": _mint(), "creator": _mint(), "created_at": "2026-08-01 00:00:00"}],
    )
    events, report = _split(
        list(load_red_pump(path, displacement_window_seconds=166, fetched_at=FETCHED))
    )
    assert events == []
    assert report.skipped == 1

    events, report = _split(
        list(
            load_red_pump(
                path,
                displacement_window_seconds=166,
                fetched_at=FETCHED,
                fields=RedPumpFieldMap(assume_utc=True),
            )
        )
    )
    assert report.launches == 1
    assert events[0].body.mint  # type: ignore[union-attr]


def test_a_window_of_zero_or_less_is_refused(tmp_path: Path) -> None:
    path = _jsonl(tmp_path / "red-pump.jsonl", [])
    with pytest.raises(ValueError, match="must be positive"):
        next(load_red_pump(path, displacement_window_seconds=0))


# --- MELT: the irreplaceable archive -----------------------------------------------


def test_melt_trades_keep_their_sign_convention_and_their_chainstamp(tmp_path: Path) -> None:
    mint, wallet, curve = _mint(), _mint(), _mint()
    path = _jsonl(
        tmp_path / "melt.jsonl",
        [
            {
                "record_type": "trade",
                "mint": mint,
                "trader": wallet,
                "is_buy": True,
                "sol_amount_lamports": "500000000",
                "token_amount_raw": "1000000000000",
                "fee_lamports": 5_000_000,
                "bonding_curve": curve,
                "slot": 12345,
                "signature": SIG_A,
                "block_time": 1786000000,
            },
            {
                "record_type": "trade",
                "mint": mint,
                "trader": wallet,
                "is_buy": False,
                "sol_amount_lamports": 400_000_000,
                "token_amount_raw": 900_000_000_000,
                "slot": 12346,
                "signature": SIG_B,
            },
        ],
    )
    events, report = _split(list(load_melt(path, fetched_at=FETCHED)))
    assert report.trades == 2 and report.skipped == 0
    buy, sell = (event.body for event in events)
    assert (buy.side, buy.sol_delta_lamports, buy.token_delta_raw) == (
        Side.BUY,
        -500_000_000,
        1_000_000_000_000,
    )
    assert (sell.side, sell.sol_delta_lamports, sell.token_delta_raw) == (
        Side.SELL,
        400_000_000,
        -900_000_000_000,
    )
    assert events[0].chain is not None and events[0].chain.slot == 12345
    assert events[0].provenance.source == MELT_SOURCE


def test_a_melt_amount_arriving_as_a_float_is_refused_rather_than_rounded(tmp_path: Path) -> None:
    """No float in the money path. A SOL-denominated column must be caught, not converted."""

    path = _jsonl(
        tmp_path / "melt.jsonl",
        [
            {
                "record_type": "trade",
                "mint": _mint(),
                "trader": _mint(),
                "is_buy": True,
                "sol_amount_lamports": 0.5,
                "token_amount_raw": 1_000_000,
                "slot": 1,
                "signature": SIG_A,
            }
        ],
    )
    events, report = _split(list(load_melt(path, fetched_at=FETCHED)))
    assert events == []
    assert report.skipped == 1


def test_a_melt_trade_without_a_signature_cannot_be_ordered_and_is_skipped(tmp_path: Path) -> None:
    path = _jsonl(
        tmp_path / "melt.jsonl",
        [
            {
                "record_type": "trade",
                "mint": _mint(),
                "trader": _mint(),
                "is_buy": True,
                "sol_amount_lamports": 1,
                "token_amount_raw": 1,
                "slot": 1,
            }
        ],
    )
    events, report = _split(list(load_melt(path, fetched_at=FETCHED)))
    assert events == []
    assert report.skipped == 1


def test_melt_bundle_membership_goes_to_a_sidecar_because_the_contract_has_no_field(
    tmp_path: Path,
) -> None:
    """Bundle traces are not recoverable from chain, and the frozen schema cannot hold them."""

    path = _jsonl(
        tmp_path / "melt.jsonl",
        [
            {
                "record_type": "trade",
                "mint": _mint(),
                "trader": _mint(),
                "is_buy": True,
                "sol_amount_lamports": 1,
                "token_amount_raw": 1,
                "slot": 1,
                "signature": SIG_A,
                "jito_bundle_id": "bundle-7",
                "jito_bundle_index": 2,
            }
        ],
    )
    sidecar = SidecarWriter(tmp_path / "melt_bundles.jsonl")
    events, report = _split(list(load_melt(path, fetched_at=FETCHED, bundle_sidecar=sidecar)))
    sidecar.close()
    assert "bundle-7" not in "\n".join(event.to_jsonl() for event in events)
    rows = [json.loads(line) for line in sidecar.path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["bundle_id"] == "bundle-7"
    assert rows[0]["signature"] == SIG_A
    assert report.sidecar_rows == 1


def test_melt_emits_no_watch_windows_because_it_is_not_our_observation(tmp_path: Path) -> None:
    """A third party's coverage decisions must not become our censoring record."""

    path = _jsonl(
        tmp_path / "melt.jsonl",
        [
            {
                "record_type": "launch",
                "mint": _mint(),
                "creator": _mint(),
                "name": "x",
                "symbol": "X",
                "created_at": 1786000000,
                "initial_virtual_sol_reserves": 30_000_000_000,
                "dev_buy_token_amount": 42,
                "slot": 9,
                "signature": SIG_A,
            }
        ],
    )
    events, report = _split(list(load_melt(path, fetched_at=FETCHED)))
    assert report.watches == 0
    assert [event.kind for event in events] == [EventKind.LAUNCH]
    assert events[0].body.dev_buy_raw == 42  # type: ignore[union-attr]


# --- input formats -----------------------------------------------------------------


def test_a_csv_archive_with_a_comma_bearing_symbol_survives_the_read(tmp_path: Path) -> None:
    """CSV is accepted on input only; the tape is JSONL because symbols look like this."""

    path = tmp_path / "red-pump.csv"
    path.write_text(
        'mint,creator,name,symbol,created_at,outcome\n'
        f'{_mint()},{_mint()},"ha,ha","A,""B""",2026-08-01T00:00:00+00:00,x\n',
        encoding="utf-8",
    )
    rows = list(read_records(path))
    assert rows[0]["name"] == "ha,ha"
    assert rows[0]["symbol"] == 'A,"B"'

    events, report = _split(
        list(load_red_pump(path, displacement_window_seconds=166, fetched_at=FETCHED))
    )
    assert report.launches == 1
    assert events[0].body.symbol == 'A,"B"'  # type: ignore[union-attr]


def test_an_unknown_archive_format_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "archive.parquet"
    path.write_bytes(b"PAR1")
    with pytest.raises(BackfillError, match="unsupported archive format"):
        list(read_records(path))


def test_the_field_map_is_the_single_place_a_real_archive_gets_repointed(tmp_path: Path) -> None:
    """The published column names are UNVERIFIED here; overriding them must be one object."""

    path = _jsonl(
        tmp_path / "melt.jsonl",
        [
            {
                "kind": "swap",
                "token": _mint(),
                "wallet": _mint(),
                "direction_is_buy": 1,
                "lamports": 7,
                "raw_tokens": 8,
                "sig": SIG_A,
                "slot": 3,
            }
        ],
    )
    fields = MeltFieldMap(
        record_kind="kind",
        trade_kind="swap",
        mint="token",
        wallet="wallet",
        is_buy="direction_is_buy",
        sol_amount="lamports",
        token_amount="raw_tokens",
        signature="sig",
    )
    _events, report = _split(list(load_melt(path, fields=fields, fetched_at=FETCHED)))
    assert report.trades == 1 and report.skipped == 0


# --- the intelligence store: two clocks, inverted between row kinds -----------------


def _wallet_row(
    *,
    mint: str,
    wallet: str,
    raw_delta: int,
    slot: int = 437_991_053,
    block_time: str | None = "2026-07-01T12:00:00+00:00",
    fetched: str = "2026-08-13T16:05:00+00:00",
    succeeded: bool = True,
    extra_legs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """One stored ``wallet_transaction`` observation, in the store's own inverted shape."""

    return {
        "kind": "wallet_transaction",
        "subject_type": "wallet",
        "subject_id": wallet,
        # THE INVERSION: emitted_at is BLOCK time, observed_at is FETCH time.
        "emitted_at": block_time,
        "observed_at": fetched,
        "payload": {
            "signature": SIG_A,
            "slot": slot,
            "transaction_index": 4,
            "succeeded": succeeded,
            "fee_lamports": 5_000,
            "wallet_paid_fee": True,
            "sol_delta_lamports": -500_000_000 if raw_delta > 0 else 400_000_000,
            "token_deltas": [
                {"mint": mint, "raw_delta": raw_delta, "decimals": 6},
                *(extra_legs or []),
            ],
        },
    }


def test_the_stores_inverted_clocks_are_normalised_into_the_contract() -> None:
    """emitted_at is BLOCK time for chain rows; reading observed_at as trade time inverts causality.

    Verified upstream by regressing slot on emitted_at and recovering 0.4213 s/slot, Solana's
    slot time. The backfiller walks history in reverse, so one fetch at 16:05Z carries the
    OLDEST slot -- against observed_at the relation runs backwards.
    """

    from shitcoims_tape.backfill import load_intelligence_wallet_transactions

    mint, wallet = _mint(), _mint()
    events, report = _split(
        list(
            load_intelligence_wallet_transactions(
                [
                    _wallet_row(mint=mint, wallet=wallet, raw_delta=1_000_000),
                    _wallet_row(
                        mint=mint,
                        wallet=wallet,
                        raw_delta=-900_000,
                        slot=437_991_060,
                        block_time="2026-07-01T12:00:03+00:00",
                    ),
                ]
            )
        )
    )
    assert report.trades == 2

    buy, sell = events
    assert buy.chain is not None and sell.chain is not None
    # Chain time landed on the chainstamp, from emitted_at -- NOT from observed_at.
    assert buy.chain.block_time == 1782907200  # 2026-07-01T12:00:00Z
    assert sell.chain.block_time - buy.chain.block_time == 3
    # And the later slot really is the later block time, which is what the inversion broke.
    assert (sell.chain.slot > buy.chain.slot) == (sell.chain.block_time > buy.chain.block_time)
    # The observer clock is the fetch time, and it is the SAME for both -- one page, one fetch.
    assert buy.observed_at == sell.observed_at == "2026-08-13T16:05:00+00:00"
    assert buy.body.side is Side.BUY and sell.body.side is Side.SELL  # type: ignore[union-attr]


def _lowercased_that_no_longer_decodes() -> str:
    """A lowercased pubkey that still LOOKS like base58 but no longer decodes to 32 bytes.

    Both conditions matter: the point of the test is that the contract's character-class
    pattern accepts the string and only a real decode rejects it. (A lowercased `L` leaves the
    base58 alphabet entirely, so those cases would prove nothing about the decode check.)
    """

    while True:
        candidate = _mint().lower()
        if _MINT.match(candidate) is None:
            continue
        try:
            Pubkey.from_string(candidate)
        except ValueError:
            return candidate


def test_a_lowercased_address_is_refused_rather_than_coerced() -> None:
    """Base58 is case-sensitive, so a lowercased address is unrecoverable, not repairable.

    The contract's own pattern is a character-class check and passes a lowercased address
    unchanged, so the importer decodes as well. That catches roughly 3 in 4 (measured: 380 of
    500 random keys); the remaining quarter still decodes to some valid 32-byte address and is
    indistinguishable from a real one, which is why write-time validation belongs in the
    collector. One of 28 stored mint mentions is already corrupt this way.
    """

    from shitcoims_tape.backfill import load_intelligence_wallet_transactions, strict_pubkey

    events, report = _split(
        list(
            load_intelligence_wallet_transactions(
                [_wallet_row(mint=_lowercased_that_no_longer_decodes(), wallet=_mint(), raw_delta=1)]
            )
        )
    )
    assert events == []
    assert report.rejected_addresses == 1
    assert report.skipped == 1

    # And the check really is stronger than the contract's pattern, which accepts this.
    corrupt = _lowercased_that_no_longer_decodes()
    assert _MINT.match(corrupt) is not None
    with pytest.raises(BackfillError, match="32-byte base58"):
        strict_pubkey(corrupt, field="mint")


def test_a_chain_row_without_a_block_time_is_kept_and_counted_not_guessed() -> None:
    """Slot still orders exactly; ~11% of the store's chain rows are in this state."""

    from shitcoims_tape.backfill import load_intelligence_wallet_transactions

    events, report = _split(
        list(
            load_intelligence_wallet_transactions(
                [_wallet_row(mint=_mint(), wallet=_mint(), raw_delta=1, block_time=None)]
            )
        )
    )
    assert report.trades == 1
    assert report.without_block_time == 1
    assert events[0].chain is not None
    assert events[0].chain.block_time is None  # not backfilled from the fetch time
    assert events[0].chain.slot == 437_991_053


def test_a_multi_leg_transaction_is_skipped_rather_than_having_its_sol_split() -> None:
    """Dividing one native delta evenly across legs fabricates a price per leg."""

    from shitcoims_tape.backfill import load_intelligence_wallet_transactions

    events, report = _split(
        list(
            load_intelligence_wallet_transactions(
                [
                    _wallet_row(
                        mint=_mint(),
                        wallet=_mint(),
                        raw_delta=1_000,
                        extra_legs=[{"mint": _mint(), "raw_delta": 2_000, "decimals": 6}],
                    )
                ]
            )
        )
    )
    assert events == []
    assert report.ambiguous_multi_leg == 1


def test_a_failed_transaction_from_the_store_is_not_imported() -> None:
    from shitcoims_tape.backfill import load_intelligence_wallet_transactions

    events, report = _split(
        list(
            load_intelligence_wallet_transactions(
                [_wallet_row(mint=_mint(), wallet=_mint(), raw_delta=1, succeeded=False)]
            )
        )
    )
    assert events == []
    assert report.skipped == 1


def test_social_rows_use_the_opposite_convention_and_keep_their_post_time() -> None:
    """For a tweet, observed_at IS the post time -- the exact reverse of the chain rows."""

    from shitcoims_tape.backfill import load_intelligence_callouts

    mint = _mint()
    events, report = _split(
        list(
            load_intelligence_callouts(
                [
                    {
                        "kind": "x_mint_mention",
                        "source_id": "x.apify",
                        "subject_type": "token",
                        "subject_id": mint,
                        "source_native_id": "tweet-1",
                        # POST time here, INGEST time in emitted_at -- inverted vs chain rows.
                        "observed_at": "2026-08-13T10:00:00+00:00",
                        "emitted_at": "2026-08-13T10:04:30+00:00",
                        "payload": {
                            "mint": mint,
                            "author_username": "someone",
                            "author_followers": 1234,
                            "like_count": 7,
                            "retweet_count": 3,
                            "url": "https://x.invalid/1",
                        },
                    }
                ]
            )
        )
    )
    assert report.callouts == 1
    event = events[0]
    # observed_at keeps ONE meaning contract-wide: when we saw it. The ingest stamp.
    assert event.observed_at == "2026-08-13T10:04:30+00:00"
    # The causal origin is preserved, typed and auditable, rather than overwriting observed_at.
    assert "posted_at=2026-08-13T10:00:00+00:00" in (event.provenance.cursor or "")
    assert event.body.mint == mint  # type: ignore[union-attr]
    assert event.body.resolved_from == "x_mint_mention"  # type: ignore[union-attr]
    assert event.body.engagement == 10  # type: ignore[union-attr]
    assert "text" not in event.body.to_json()  # the prose itself is never stored


def test_a_social_row_that_never_resolved_to_a_mint_is_not_a_callout() -> None:
    """A cashtag is a claim, not an identifier; pooling the two corrupts the study."""

    from shitcoims_tape.backfill import load_intelligence_callouts

    events, report = _split(
        list(
            load_intelligence_callouts(
                [
                    {
                        "kind": "x_cashtag",
                        "source_id": "x.apify",
                        "subject_type": "cashtag",
                        "subject_id": "DOGE",
                        "observed_at": "2026-08-13T10:00:00+00:00",
                        "payload": {"author_username": "someone"},
                    }
                ]
            )
        )
    )
    assert events == []
    assert report.skipped == 1
