from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from shitcoims_scout.desk import (
    bags_from_snapshot,
    default_policy_body,
    render_bag,
    render_candidates,
    render_desk,
)
from shitcoims_scout.local_api import LocalAPI, LocalAPIError
from shitcoims_scout.state import ScoutState


def test_desk_render_lists_observe_and_protected() -> None:
    snapshot = {
        "system": {"mode": "live", "protection_state": "DEGRADED"},
        "wallet": {"sol": "1.5", "portfolio_exit_sol": "0.4"},
        "positions": [
            {
                "mint": "EaPk9U9Das8EdWyDGV7NaNTcVZv3LQMAHwG63L4qpump",
                "name": "OMG",
                "exit_sol": "0.3",
            }
        ],
        "unmonitored": [
            {
                "mint": "5jUwEEKMawc1q1GCEKLgCYA77jbGfVvjz21nEpJrpump",
                "name": "clout",
                "exit_sol": "0.1",
            }
        ],
    }
    policies = [
        {
            "mint": "EaPk9U9Das8EdWyDGV7NaNTcVZv3LQMAHwG63L4qpump",
            "stop_loss_pct": -10,
            "take_profit_pct": 80,
            "runner_tightness": 20,
        }
    ]
    text = render_desk(snapshot, policies)
    assert "Cannot sell" in text
    assert "OMG" in text
    assert "SL -10" in text
    assert "arm +80" in text
    assert "runner" in text
    assert "trail 20%" not in text
    assert "clout" in text
    assert "10m" in text
    bags = bags_from_snapshot(snapshot, policies)
    clout = next(bag for bag in bags if bag.name == "clout")
    body = default_policy_body(clout)
    # An unprotected bag has no thresholds yet, and the desk does not invent any: every
    # threshold key is ABSENT so the sentinel's own defaults decide. The desk carrying its
    # own copy is how the same bag came to be protected under two different rules.
    assert "stop_loss_pct" not in body
    assert "take_profit_pct" not in body
    assert "runner_tightness" not in body
    assert "exit_style" not in body
    assert body["cost_basis_sol"] == 0.1
    assert body.get("execution") is None

    # A bag that already has a rule round-trips its own numbers, not the desk's.
    omg = next(bag for bag in bags if bag.name == "OMG")
    assert default_policy_body(omg)["stop_loss_pct"] == -10
    assert default_policy_body(omg)["take_profit_pct"] == 80
    assert default_policy_body(omg)["runner_tightness"] == 20


def test_desk_render_runner_floor_not_percent_leash() -> None:
    mint = "EaPk9U9Das8EdWyDGV7NaNTcVZv3LQMAHwG63L4qpump"
    snapshot = {
        "system": {"mode": "live", "protection_state": "DEGRADED"},
        "wallet": {"sol": "1.5", "portfolio_exit_sol": "0.4"},
        "positions": [
            {
                "mint": mint,
                "name": "OMG",
                "exit_sol": "0.3",
                "pnl_pct": "250",
                "unit_price_sol": "0.0035",
                "trailing_peak_unit_price_sol": "0.0051",
                "decision_reason": "thresholds clear",
                "thresholds": {
                    "stop_loss_pct": "-10",
                    "take_profit_pct": "80",
                    "runner_tightness": "20",
                },
                "runner": {
                    "floor_multiple": "2.20",
                    "below_floor_streak": 0,
                    "scale_rungs_fired": ["2"],
                    "original_amount": 1000,
                    "sell_amount": None,
                },
            }
        ],
        "unmonitored": [],
    }
    policies = [
        {
            "mint": mint,
            "stop_loss_pct": -10,
            "take_profit_pct": 80,
            "runner_tightness": 20,
            "rug_exit": True,
        }
    ]
    text = render_desk(snapshot, policies)
    assert "SL -10 / arm +80 / runner floor 2.2x" in text
    assert "trail 20%" not in text
    bags = bags_from_snapshot(snapshot, policies)
    bag = bags[0]
    assert bag.runner_tightness == 20
    assert bag.floor_multiple == "2.20"
    assert bag.peak == "5.1"
    detail = render_bag(bag)
    assert "SL -10 · arm +80 · runner floor 2.2x" in detail
    assert "peak 5.1x · floor 2.2x" in detail
    assert "scaled 2" in detail
    assert "trail 20%" not in detail
    assert default_policy_body(bag)["runner_tightness"] == 20


def test_desk_renders_switched_off_rules_as_rules_not_as_missing_data() -> None:
    """A bag held unless it rugs must not read like a bag whose numbers failed to load."""

    mint = "EaPk9U9Das8EdWyDGV7NaNTcVZv3LQMAHwG63L4qpump"
    snapshot = {
        "system": {"mode": "dry-run", "protection_state": "DRY_RUN"},
        "wallet": {"sol": "1", "portfolio_exit_sol": "0.2"},
        "positions": [{"mint": mint, "name": "HODL", "exit_sol": "0.2"}],
        "unmonitored": [],
    }
    policies = [
        {
            "mint": mint,
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "runner_tightness": None,
            "rug_exit": True,
        }
    ]
    text = render_desk(snapshot, policies)
    assert "no SL / no TP / no runner" in text
    assert "?" not in text.split("HODL")[1].splitlines()[0]
    detail = render_bag(bags_from_snapshot(snapshot, policies)[0])
    assert "no SL · no TP · no runner · rug True" in detail


def test_render_bag_badges_bonding_wait() -> None:
    mint = "EaPk9U9Das8EdWyDGV7NaNTcVZv3LQMAHwG63L4qpump"
    snapshot = {
        "system": {},
        "wallet": {},
        "positions": [
            {
                "mint": mint,
                "name": "PUMP",
                "exit_sol": "0.1",
                "decision_reason": "bonding curve: runner waits for graduation",
                "thresholds": {"runner_tightness": "20"},
                "runner": {"floor_multiple": None, "scale_rungs_fired": []},
            }
        ],
        "unmonitored": [],
    }
    policies = [
        {
            "mint": mint,
            "stop_loss_pct": -10,
            "take_profit_pct": 80,
            "runner_tightness": 20,
            "rug_exit": True,
        }
    ]
    detail = render_bag(bags_from_snapshot(snapshot, policies)[0])
    assert "waiting for graduation" in detail
    assert "SL -10 · arm +80 · runner" in detail


def test_render_candidates_lists_verdict_mint_reasons() -> None:
    text = render_candidates(
        {
            "items": [
                {
                    "verdict": "watch",
                    "mint": "EaPk9U9Das8EdWyDGV7NaNTcVZv3LQMAHwG63L4qpump",
                    "reasons": ["kol mentioned", "fresh pool"],
                }
            ]
        }
    )
    assert "Cannot sell" in text
    assert "watch" in text
    assert "EaPk9U9Das8EdWyDGV7NaNTcVZv3LQMAHwG63L4qpump" in text
    assert "kol mentioned" in text
    assert "fresh pool" in text


def test_render_candidates_missing_payload() -> None:
    assert render_candidates(None) == "Candidates API not up yet."
    assert render_candidates({}) == "Candidates API not up yet."
    assert "No candidates." in render_candidates({"items": []})


@pytest.mark.asyncio
async def test_delete_json_only_allows_policy_mint() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"removed": True, "can_execute": False})

    mint = "EaPk9U9Das8EdWyDGV7NaNTcVZv3LQMAHwG63L4qpump"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        api = LocalAPI("http://127.0.0.1:8788", "http://127.0.0.1:8787", http)
        result = await api.delete_json(f"/api/policies/{mint}")
        with pytest.raises(LocalAPIError):
            await api.delete_json("/api/panic")
        with pytest.raises(LocalAPIError):
            await api.delete_json("/api/policies/protect-unmonitored")
        with pytest.raises(LocalAPIError):
            await api.delete_json(f"/api/policies/{mint}/skip-auto")

    assert result == {"removed": True, "can_execute": False}
    assert len(seen) == 1
    assert seen[0].method == "DELETE"
    assert str(seen[0].url) == f"http://127.0.0.1:8787/api/policies/{mint}"


def test_callback_allowlist_includes_delete_and_candidates(tmp_path: Path) -> None:
    state = ScoutState(tmp_path / "scout.sqlite3")
    delete = state.create_callback("delete", {"mint": "EaPk9U9Das8EdWyDGV7NaNTcVZv3LQMAHwG63L4qpump"})
    candidates = state.create_callback("candidates", {})
    assert state.consume_callback(delete).action == "delete"
    assert state.consume_callback(candidates).action == "candidates"
    state.close()
