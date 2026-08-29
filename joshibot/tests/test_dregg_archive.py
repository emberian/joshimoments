"""Tests for dregg_archive. Every test is OFFLINE: the recording transport is injected,
so real API shapes are replayed without a network, and the clock is a variable.

Weighted towards the parts that can lie silently: exact-bytes retention, the deletion
inference's refusal to call roll-off a removal, the budget's durable stop, and outcome
math on candles with holes in them.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from pathlib import Path

import pytest

from dregg_archive import Service, Store, deletion, manifest
from dregg_archive.client import RecordingTransport
from dregg_archive.outcomes import CandleSeries, compute
from dregg_archive.store import MS_DAY, MS_HOUR, utc_day
from shitcoims_pumpsocial import MutatingEndpointRefused, PumpSocialClient

MS_MIN = 60_000

# Real on-curve wallets and mints, lifted from recorded firehose bodies — the models
# layer quarantines anything off-curve, so synthetic addresses would silently empty
# every derived table.
W1 = "GDpXs9XQhXFGu3VUDo9bZnf7xaFDijrE7E4i8TPUQmgv"
W2 = "FYEPNDJLbW74uJJ4Y9gWGftrUdJciVyJkL2Y2EnDoFzn"
W3 = "8Sh1MqzbTEZmWyKWmyQWEBHPdgcUjwgmMG1Df53tYjJk"
M1 = "5dqgLU2WTTi3tWQfyvj7ArtCEMq3mMAFVuVDQfUWpump"
M2 = "7D4tqzLwoTnquBtjPkFCzSjougpUTqPeuapBEVPVpump"

#: 2026-08-20 12:00:00 UTC — mid-day, so day-boundary arithmetic stays out of the way.
T0 = 1_787_918_400_000


class Clock:
    def __init__(self, ms: int):
        self.ms = ms

    def __call__(self) -> int:
        return self.ms


def raw_callout(cid: str, wallet: str, mint: str, t_ms: int, **over):
    row = {
        "calloutId": cid, "userId": wallet, "coinMint": mint,
        "thesis": f"thesis {cid}", "createdAt": t_ms,
        "calloutPrice": 1.7e-07, "marketCap": 13381.9, "multiple": 1.0,
        "maxPriceSol": 1.77e-07, "peakTimestamp": t_ms + 10_000,
        "username": None, "xUsername": None,
    }
    row.update(over)
    return row


class FakeAPI:
    """The three hosts, answered from in-memory fixtures. Records every URL asked."""

    def __init__(self):
        self.callouts: list[dict] = []
        self.top_by_mint: dict[str, list[dict]] = {}
        self.list_by_mint: dict[str, list[dict]] = {}
        self.candles_by_mint: dict[str, list[dict]] = {}
        self.calls: list[str] = []
        #: The measured 2026-08-29 drift: /callout/recent 400s into the uuid pipe.
        self.recent_broken = False

    def __call__(self, method, url, headers, body):
        self.calls.append(url)
        parts = urllib.parse.urlsplit(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}

        def ok(payload) -> tuple[int, dict, bytes]:
            return 200, {}, json.dumps(payload).encode()

        if "/callout/recent" in url:
            if self.recent_broken:
                return 400, {}, (b'{"statusCode":400,"message":'
                                 b'"Validation failed (uuid is expected)","error":"Bad Request"}')
            limit = int(q.get("limit", 50))
            offset = int(q["pageToken"][1:]) if "pageToken" in q else 0
            rows = sorted(self.callouts, key=lambda r: -r["createdAt"])
            page = rows[offset:offset + limit]
            token = f"p{offset + limit}" if offset + limit < len(rows) else ""
            return ok({"callouts": page, "nextPageToken": token})
        if "/callout/top/" in url:
            mint = parts.path.rsplit("/", 1)[1]
            return ok({"callouts": self.top_by_mint.get(mint, []), "nextPageToken": ""})
        if "/callout/list/" in url:
            mint = parts.path.rsplit("/", 1)[1]
            return ok({"callouts": self.list_by_mint.get(mint, []), "nextPageToken": ""})
        if "/candles" in url:
            mint = parts.path.split("/coins/")[1].split("/")[0]
            return ok(self.candles_by_mint.get(mint, []))
        if "/leaderboard/callouts/wallets/" in url:
            return ok({"totalCallouts": 3, "twoXPercent": 10.0})
        return 404, {}, b'{"message":"Not Found"}'


def write_config(tmp_path: Path, **over) -> Path:
    values = {
        "cadence_s": 600, "overlap_min": 2, "initial_lookback_min": 60,
        "walk_limit": 2, "walk_max_pages": 10, "daily_budget": 200,
        "sweep_gap_s": 0.0, "sweep_batch_max": 60,
        "caller_stats_per_day": 300, "caller_stats_per_cycle": 2,
        "active_caller_days": 7, "list_probes_per_cycle": 5, "deletion_horizon_h": 48,
    }
    values.update(over)
    def _toml(v):
        if isinstance(v, list):
            return "[" + ", ".join(f'"{x}"' for x in v) + "]"
        return str(v)

    service_lines = "\n".join(
        f"{k} = {_toml(v)}" for k, v in values.items() if not isinstance(v, str)
    )
    text = f"""
[paths]
db = "{tmp_path}/archive.sqlite"
heartbeat = "{tmp_path}/heartbeat.json"
manifests = "{tmp_path}/manifests"

[service]
{service_lines}

[candles]
candles_25h_interval = "5m"
candles_25h_limit = 600
candles_7d_interval = "1h"
candles_7d_limit = 200
"""
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def make_service(tmp_path: Path, api: FakeAPI, clock: Clock, **cfg_over) -> Service:
    cfg = write_config(tmp_path, **cfg_over)
    return Service(
        cfg, transport=api, clock_ms=clock,
        sleep=lambda _s: None, client_sleep=lambda _s: None,
    )


# ---------------------------------------------------------------------------
# raw layer
# ---------------------------------------------------------------------------


def test_store_roundtrip_exact_bytes(tmp_path):
    """The raw layer's one promise: bytes out are bytes in, hash and all."""

    store = Store(tmp_path / "a.sqlite")
    body = b'\x00\xff\x80 not even json \xf0\x9f\xa4\x96' + bytes(range(256))
    fid = store.record_fetch(
        route="callout_recent", url="https://x/y", t_request_ms=1, t_response_ms=2,
        status=200, body=body,
    )
    assert store.fetch_body(fid) == body
    row = store.fetch_row(fid)
    assert row[6] == hashlib.sha256(body).hexdigest()


def test_refusal_precedes_retention(tmp_path):
    """A mutating route is refused BEFORE the transport — so it is never even archived.

    The archive retaining a would-be write request would mean the write happened.
    """

    store = Store(tmp_path / "a.sqlite")
    recorder = RecordingTransport(FakeAPI(), store, Clock(T0))
    client = PumpSocialClient(transport=recorder, sleep=lambda _s: None)
    with pytest.raises(MutatingEndpointRefused):
        client.request("follow_user", path_params={"user_id": "x"})
    assert store.counts()["fetches"] == 0


# ---------------------------------------------------------------------------
# the walk: retention, windows, derivation, hwm
# ---------------------------------------------------------------------------


def _seed_feed(api: FakeAPI):
    api.callouts = [
        raw_callout("c1", W1, M1, T0 - 5 * MS_MIN),
        raw_callout("c2", W2, M1, T0 - 10 * MS_MIN),
        raw_callout("c3", W3, M2, T0 - 50 * MS_MIN),
    ]


def test_walk_retains_windows_and_derives_from_exact_bytes(tmp_path):
    api = FakeAPI()
    _seed_feed(api)
    clock = Clock(T0)
    svc = make_service(tmp_path, api, clock)
    hb = svc.cycle()

    assert hb["walk"]["pages"] == 2  # 2-row page + 1-row page: short page = completion
    assert hb["walk"]["reached_since"] is True
    assert hb["walk"]["new_callouts"] == 3
    assert hb["walk"]["quarantined"] == {}

    store = svc.store
    # Derived rows exist, and the bytes they were derived from are retained verbatim.
    rows = store.db.execute(
        "SELECT id, sha256 FROM fetches WHERE route='callout_recent' AND status=200"
    ).fetchall()
    assert len(rows) == 2
    for fid, sha in rows:
        body = store.fetch_body(fid)
        assert hashlib.sha256(body).hexdigest() == sha
        assert b"calloutId" in body
    # Window of the first page: [c2, c1].
    win = store.db.execute(
        "SELECT t_oldest_row_ms, t_newest_row_ms, row_count FROM fetch_windows"
        " WHERE fetch_id=?", (rows[0][0],),
    ).fetchone()
    assert win == (T0 - 10 * MS_MIN, T0 - 5 * MS_MIN, 2)
    # Callout, caller, sighting rows.
    assert store.counts()["callouts"] == 3
    assert store.counts()["callers"] == 3
    assert store.counts()["sightings"] == 3
    first = store.db.execute(
        "SELECT wallet, mint, t_event_ms, callout_price_first, n_sightings FROM callouts"
        " WHERE callout_id='c1'"
    ).fetchone()
    assert first == (W1, M1, T0 - 5 * MS_MIN, 1.7e-07, 1)
    # High-water mark is the newest event seen.
    assert store.hwm_ms() == T0 - 5 * MS_MIN


def test_hwm_and_overlap_arithmetic(tmp_path):
    api = FakeAPI()
    _seed_feed(api)
    clock = Clock(T0)
    svc = make_service(tmp_path, api, clock)
    svc.cycle()
    hwm1 = svc.store.hwm_ms()
    assert hwm1 == T0 - 5 * MS_MIN

    # Ten minutes later two new callouts exist; the walk must start at hwm - overlap
    # and stop as soon as a page is entirely older than that.
    clock.ms = T0 + 10 * MS_MIN
    api.callouts += [
        raw_callout("c4", W1, M2, T0 + 3 * MS_MIN),
        raw_callout("c5", W2, M2, T0 + 1 * MS_MIN),
    ]
    hb = svc.cycle()
    assert hb["walk_since_ms"] == hwm1 - 2 * MS_MIN  # overlap_min = 2 in the test config
    assert hb["walk"]["pages"] == 2  # page [c4,c5], then page [c1,c2] whose oldest < since
    assert hb["walk"]["reached_since"] is True
    assert hb["walk"]["new_callouts"] == 2
    assert svc.store.hwm_ms() == T0 + 3 * MS_MIN
    # The overlap re-sighted c1: two sightings now, and no false absence anywhere.
    n = svc.store.db.execute(
        "SELECT n_sightings FROM callouts WHERE callout_id='c1'"
    ).fetchone()[0]
    assert n == 2
    assert svc.store.counts()["verdicts_removed"] == 0
    assert svc.store.counts()["verdicts_unknown_absent"] == 0


# ---------------------------------------------------------------------------
# budget: hard stop, durable
# ---------------------------------------------------------------------------


def test_budget_hard_stop_is_durable(tmp_path):
    api = FakeAPI()
    api.callouts = [
        raw_callout(f"b{i}", W1, M1, T0 - i * MS_MIN) for i in range(1, 11)
    ]
    clock = Clock(T0)
    svc = make_service(tmp_path, api, clock, daily_budget=3, walk_limit=1)
    hb = svc.cycle()
    day = utc_day(T0)
    spent, stopped = svc.store.budget(day)
    assert spent == 3
    assert stopped is True
    assert hb["budget"]["stopped"] is True
    assert "idle" in hb["budget"]["note"]

    # A fresh process, same day: the stop survives — zero further requests.
    api2 = FakeAPI()
    svc2 = make_service(tmp_path, api2, clock, daily_budget=3, walk_limit=1)
    hb2 = svc2.cycle()
    assert api2.calls == []
    assert hb2["budget"]["stopped"] is True

    # A new UTC day starts fresh.
    clock.ms = T0 + MS_DAY
    svc3 = make_service(tmp_path, api2, clock, daily_budget=3, walk_limit=1)
    svc3.cycle()
    assert len(api2.calls) > 0


# ---------------------------------------------------------------------------
# sweeps: scheduling, dedupe, execution, outcomes end-to-end
# ---------------------------------------------------------------------------


def test_sweep_dedupe_and_execution_to_outcomes(tmp_path):
    api = FakeAPI()
    _seed_feed(api)  # c1, c2 on M1 same day; c3 on M2
    t1 = T0 - 5 * MS_MIN  # c1's event time
    api.top_by_mint[M1] = [
        raw_callout("c1", W1, M1, t1, username="alice", xUsername="alicex", multiple=2.5),
    ]
    # Closes as DECIMAL STRINGS: that is what swap-api actually serves (measured).
    for mint in (M1, M2):
        api.candles_by_mint[mint] = [
            {"timestamp": t1 - MS_HOUR, "close": "1.0", "open": "0.9"},
            {"timestamp": t1 + MS_HOUR, "close": "2.0", "open": "1.0"},
        ]
    clock = Clock(T0)
    svc = make_service(tmp_path, api, clock)
    svc.cycle()

    # (mint, day) dedupe: c1 and c2 share M1 and a UTC day -> ONE row per sweep kind.
    per_kind = dict(svc.store.db.execute(
        "SELECT kind, COUNT(*) FROM due_work WHERE key=? GROUP BY kind", (M1,)
    ).fetchall())
    assert per_kind["top25h"] == 1
    assert per_kind["top7d"] == 1
    assert per_kind["candles25h"] == 1
    assert per_kind["candles7d"] == 1

    # Nine days later everything is due; one cycle executes the lot.
    clock.ms = T0 + 9 * MS_DAY
    hb = svc.cycle()
    pending = svc.store.db.execute(
        "SELECT COUNT(*) FROM due_work WHERE done_ms IS NULL AND kind LIKE 'top%'"
        " OR done_ms IS NULL AND kind LIKE 'candles%'"
    ).fetchone()[0]
    assert pending == 0
    assert hb["sweeps"]["parked"] == 0

    urls = "\n".join(api.calls)
    assert "interval=5m&limit=600" in urls
    assert "interval=1h&limit=200" in urls

    # Candle fetch windows recorded per mint.
    candle_windows = svc.store.db.execute(
        "SELECT scope, t_oldest_row_ms, t_newest_row_ms, row_count FROM fetch_windows"
        " WHERE route='swap_candles' AND scope=?", (M1,),
    ).fetchall()
    assert (M1, t1 - MS_HOUR, t1 + MS_HOUR, 2) in candle_windows

    # The top sweep enriched identity (the firehose serves username: null).
    row = svc.store.db.execute(
        "SELECT username_last, x_username_last, provider_multiple_last FROM callouts"
        " WHERE callout_id='c1'"
    ).fetchone()
    assert row == ("alice", "alicex", 2.5)

    # And outcomes were computed from OUR retained candle bytes, in the same cycle.
    outcome = svc.store.db.execute(
        "SELECT ret_1h, ret_24h, ret_7d, max_close_multiple, max_drawdown, dead_flag"
        " FROM outcomes WHERE callout_id='c1' AND method_version='v1'"
    ).fetchone()
    assert outcome is not None
    ret_1h, ret_24h, ret_7d, max_mult, drawdown, dead = outcome
    assert ret_1h == pytest.approx(1.0)
    assert ret_24h == pytest.approx(1.0)
    assert ret_7d == pytest.approx(1.0)
    assert max_mult == pytest.approx(2.0)
    assert drawdown == pytest.approx(0.0)
    assert dead == 1  # no candle after t_event + 24h: no trades is a fact, not a gap


def test_dark_firehose_fallback_walks_known_mints(tmp_path):
    """When /callout/recent fails (measured drift), the archive keeps sighting via the
    per-mint list surface for mints it already knows — continuity, not conjuring."""

    api = FakeAPI()
    _seed_feed(api)
    clock = Clock(T0)
    svc = make_service(tmp_path, api, clock, fallback_seed_mints=[M1])
    svc.cycle()  # healthy cycle: M1 and M2 become known-active

    api.recent_broken = True
    api.list_by_mint[M1] = [raw_callout("c1", W1, M1, T0 - 5 * MS_MIN)]
    api.list_by_mint[M2] = [
        raw_callout("c3", W3, M2, T0 - 50 * MS_MIN),
        raw_callout("cNEW", W2, M2, T0 + 8 * MS_MIN),  # a callout the dark firehose never showed us
    ]
    clock.ms = T0 + 10 * MS_MIN
    hb = svc.cycle()
    assert hb["walk"]["failed"] is not None
    assert "uuid is expected" in hb["walk"]["failed"]

    # The failed fetch is retained too — the outage is itself archived.
    assert svc.store.db.execute(
        "SELECT COUNT(*) FROM fetches WHERE route='callout_recent' AND status=400"
    ).fetchone()[0] == 1

    # List probes ran for the known mints and kept deriving.
    list_windows = svc.store.db.execute(
        "SELECT scope, row_count FROM fetch_windows WHERE route='callout_list_mint'"
    ).fetchall()
    assert {w[0] for w in list_windows} == {M1, M2}
    assert svc.store.db.execute(
        "SELECT COUNT(*) FROM callouts WHERE callout_id='cNEW'"
    ).fetchone()[0] == 1
    # A callout first sighted through a sweep fetch still earns its follow-up sweeps.
    assert svc.store.db.execute(
        "SELECT COUNT(*) FROM due_work WHERE kind='candles25h' AND key=?", (M2,)
    ).fetchone()[0] == 1

    # Same hour, still dark: hourly dedupe means no new probes.
    clock.ms = T0 + 15 * MS_MIN
    svc.cycle()
    n_list = svc.store.db.execute(
        "SELECT COUNT(*) FROM fetches WHERE route='callout_list_mint'"
    ).fetchone()[0]
    assert n_list == 2

    # Next hour: probes again.
    clock.ms = T0 + 70 * MS_MIN
    svc.cycle()
    n_list2 = svc.store.db.execute(
        "SELECT COUNT(*) FROM fetches WHERE route='callout_list_mint'"
    ).fetchone()[0]
    assert n_list2 == 4


# ---------------------------------------------------------------------------
# deletion: the honest inference
# ---------------------------------------------------------------------------


def _plant_sighting(store, cid, mint, wallet, t_event, t_fetch):
    fid = store.record_fetch(
        route="callout_recent", url="https://x/recent", t_request_ms=t_fetch - 100,
        t_response_ms=t_fetch, status=200, body=b'{"planted": true}',
    )
    store.record_window(
        fid, route="callout_recent", scope=None,
        t_oldest_row_ms=t_event - 10 * MS_MIN, t_newest_row_ms=t_fetch,
        row_count=3, truncated=False,
    )
    store.record_sighting(cid, fid, "callout_recent")
    store.upsert_callout(
        callout_id=cid, wallet=wallet, mint=mint, t_event_ms=t_event, thesis="t",
        callout_price=1.0, market_cap=1.0, fetch_id=fid, provider_multiple=None,
        provider_peak_t_ms=None, username=None, x_username=None,
    )
    return fid


def _plant_absence(store, *, t_fetch, route, scope, lo, hi, status=200):
    fid = store.record_fetch(
        route=route, url=f"https://x/{route}", t_request_ms=t_fetch - 100,
        t_response_ms=t_fetch, status=status, body=b"{}",
    )
    store.record_window(
        fid, route=route, scope=scope, t_oldest_row_ms=lo, t_newest_row_ms=hi,
        row_count=2, truncated=False,
    )
    return fid


def test_rolled_off_is_unknown_absent_not_removed(tmp_path):
    """A window that no longer reaches t_event is the feed forgetting, not deleting."""

    store = Store(tmp_path / "a.sqlite")
    t_event = T0
    _plant_sighting(store, "cx", M1, W1, t_event, t_event + MS_MIN)
    # Later fetches whose windows START after t_event: roll-off, zero evidence.
    _plant_absence(store, t_fetch=t_event + 40 * MS_MIN, route="callout_recent",
                   scope=None, lo=t_event + 10 * MS_MIN, hi=t_event + 40 * MS_MIN)
    _plant_absence(store, t_fetch=t_event + 2 * MS_HOUR, route="callout_list_mint",
                   scope=M1, lo=t_event + 30 * MS_MIN, hi=t_event + 2 * MS_HOUR)
    events = deletion.absent_events(store, callout_id="cx", mint=M1, t_event_ms=t_event)
    assert events == []
    assert deletion.classify(events) == "unknown-absent"
    summary = deletion.run_pass(store, t_event + 3 * MS_HOUR, horizon_ms=48 * MS_HOUR)
    assert summary.removed == 0
    assert store.verdicts() == []  # nothing persisted: there is no evidence to hold


def test_spanned_absence_on_two_surfaces_61min_apart_is_removed(tmp_path):
    store = Store(tmp_path / "a.sqlite")
    t_event = T0
    _plant_sighting(store, "cx", M1, W1, t_event, t_event + MS_MIN)
    f2 = _plant_absence(store, t_fetch=t_event + 30 * MS_MIN, route="callout_recent",
                        scope=None, lo=t_event - 30 * MS_MIN, hi=t_event + 30 * MS_MIN)
    f3 = _plant_absence(store, t_fetch=t_event + 91 * MS_MIN, route="callout_list_mint",
                        scope=M1, lo=t_event - MS_HOUR, hi=t_event + 91 * MS_MIN)
    summary = deletion.run_pass(store, t_event + 2 * MS_HOUR, horizon_ms=48 * MS_HOUR)
    assert summary.removed == 1
    verdicts = store.verdicts(verdict="removed")
    assert len(verdicts) == 1
    assert verdicts[0]["callout_id"] == "cx"
    assert verdicts[0]["evidence_fetch_ids"] == sorted([f2, f3])
    assert verdicts[0]["published"] is False


def test_one_surface_or_short_spread_stays_unknown_absent(tmp_path):
    store = Store(tmp_path / "a.sqlite")
    t_event = T0
    # Case 1: two absences, 61 min apart, but the SAME surface.
    _plant_sighting(store, "ca", M1, W1, t_event, t_event + MS_MIN)
    _plant_absence(store, t_fetch=t_event + 30 * MS_MIN, route="callout_recent",
                   scope=None, lo=t_event - MS_HOUR, hi=t_event + 30 * MS_MIN)
    _plant_absence(store, t_fetch=t_event + 91 * MS_MIN, route="callout_recent",
                   scope=None, lo=t_event - MS_HOUR, hi=t_event + 91 * MS_MIN)
    # Case 2: two surfaces, only 30 min apart.
    t2 = T0 + 4 * MS_HOUR
    _plant_sighting(store, "cb", M2, W2, t2, t2 + MS_MIN)
    _plant_absence(store, t_fetch=t2 + 20 * MS_MIN, route="callout_recent",
                   scope=None, lo=t2 - MS_HOUR, hi=t2 + 20 * MS_MIN)
    _plant_absence(store, t_fetch=t2 + 50 * MS_MIN, route="callout_list_mint",
                   scope=M2, lo=t2 - MS_HOUR, hi=t2 + 50 * MS_MIN)
    summary = deletion.run_pass(store, t2 + 2 * MS_HOUR, horizon_ms=48 * MS_HOUR)
    assert summary.removed == 0
    assert summary.unknown_absent == 2
    assert {v["verdict"] for v in store.verdicts()} == {"unknown-absent"}
    # The single-surface case is the one worth a second-surface probe.
    assert M1 in summary.confirm_mints
    assert M2 not in summary.confirm_mints


def test_reappearance_resets_the_evidence(tmp_path):
    """A callout sighted again after an absence run has demonstrably not been removed."""

    store = Store(tmp_path / "a.sqlite")
    t_event = T0
    _plant_sighting(store, "cx", M1, W1, t_event, t_event + MS_MIN)
    _plant_absence(store, t_fetch=t_event + 30 * MS_MIN, route="callout_recent",
                   scope=None, lo=t_event - MS_HOUR, hi=t_event + 30 * MS_MIN)
    _plant_absence(store, t_fetch=t_event + 91 * MS_MIN, route="callout_list_mint",
                   scope=M1, lo=t_event - MS_HOUR, hi=t_event + 91 * MS_MIN)
    deletion.run_pass(store, t_event + 2 * MS_HOUR, horizon_ms=48 * MS_HOUR)
    assert store.counts()["verdicts_removed"] == 1
    # ... and then it shows up again.
    _plant_sighting(store, "cx", M1, W1, t_event, t_event + 3 * MS_HOUR)
    summary = deletion.run_pass(store, t_event + 4 * MS_HOUR, horizon_ms=48 * MS_HOUR)
    assert summary.cleared == 1
    assert store.verdicts() == []


def test_window_edge_is_not_spanned(tmp_path):
    """Strict interiority: a callout at exactly a window bound may live in the next page."""

    store = Store(tmp_path / "a.sqlite")
    t_event = T0
    _plant_sighting(store, "cx", M1, W1, t_event, t_event + MS_MIN)
    _plant_absence(store, t_fetch=t_event + 30 * MS_MIN, route="callout_recent",
                   scope=None, lo=t_event, hi=t_event + 30 * MS_MIN)  # lo == t_event
    events = deletion.absent_events(store, callout_id="cx", mint=M1, t_event_ms=t_event)
    assert events == []


# ---------------------------------------------------------------------------
# outcomes: the candle math
# ---------------------------------------------------------------------------


def test_outcome_math_on_hand_built_candles():
    t = T0
    fine = CandleSeries(300, t + 25 * MS_HOUR, (
        (t - 5 * MS_MIN, 1.0),
        (t + 30 * MS_MIN, 1.5),
        (t + MS_HOUR, 2.0),
        (t + 23 * MS_HOUR, 4.0),
    ))
    coarse = CandleSeries(3600, t + 7 * MS_DAY + MS_HOUR, (
        (t - MS_HOUR, 1.0),
        (t + MS_HOUR, 2.0),
        (t + 20 * MS_HOUR, 4.0),
        (t + 30 * MS_HOUR, 0.5),
        (t + 6 * MS_DAY, 0.25),
    ))
    out = compute(t, [fine, coarse])
    assert out.ret_1h == pytest.approx(1.0)      # 2.0 / 1.0 - 1, from the 5m series
    assert out.ret_24h == pytest.approx(3.0)     # last 5m close (23h) carries to 24h
    assert out.ret_7d == pytest.approx(-0.75)    # 0.25 / 1.0 - 1, from the 1h series
    assert out.max_close_multiple == pytest.approx(4.0)
    assert out.max_drawdown == pytest.approx((4.0 - 0.25) / 4.0)
    assert out.dead_flag is False                # trades exist after +24h
    assert out.complete is True


def test_outcome_horizon_not_elapsed_is_none_not_zero():
    """A horizon the fetch has not reached yet must be None — inventing it as 0 (or as
    the truncated last close) is fabricating a return that has not happened."""

    t = T0
    early = CandleSeries(300, t + 30 * MS_MIN, ((t - 5 * MS_MIN, 1.0), (t + 20 * MS_MIN, 3.0)))
    out = compute(t, [early])
    assert out.ret_1h is None
    assert out.ret_24h is None
    assert out.ret_7d is None
    assert out.dead_flag is None
    assert out.complete is False


def test_outcome_dead_coin_carries_last_close():
    t = T0
    series = CandleSeries(3600, t + 8 * MS_DAY, (
        (t - MS_HOUR, 1.0),
        (t + 2 * MS_HOUR, 0.5),
    ))
    out = compute(t, [series])
    assert out.dead_flag is True                 # nothing traded after +24h
    assert out.ret_24h == pytest.approx(-0.5)    # the 2h close carries forward
    assert out.ret_7d == pytest.approx(-0.5)
    assert out.max_close_multiple == pytest.approx(0.5)
    assert out.max_drawdown == pytest.approx(0.5)


def test_outcome_no_baseline_is_no_outcome():
    """A series that starts hours after the call has no anchor: every price field stays
    None. dead_flag is still judgeable (the +7d gate passed, nothing after +24h)."""

    t = T0
    series = CandleSeries(3600, t + 8 * MS_DAY, ((t + 5 * MS_HOUR, 2.0),))  # first candle 5h late
    out = compute(t, [series])
    assert out.ret_1h is None
    assert out.ret_24h is None
    assert out.max_close_multiple is None
    assert out.max_drawdown is None
    assert out.dead_flag is True


# ---------------------------------------------------------------------------
# config: keep-last-good
# ---------------------------------------------------------------------------


def test_config_rereads_and_keeps_last_good(tmp_path):
    api = FakeAPI()
    clock = Clock(T0)
    svc = make_service(tmp_path, api, clock)
    assert svc.cfg.cadence_s == 600

    cfg_path = tmp_path / "config.toml"
    good = cfg_path.read_text()
    cfg_path.write_text(good + "\nthis is not toml [[[")
    hb = svc.cycle()
    assert hb["config_status"].startswith("kept_last_good")
    assert svc.cfg.cadence_s == 600  # unchanged, not defaulted

    cfg_path.write_text(good.replace("cadence_s = 600", "cadence_s = 300"))
    hb = svc.cycle()
    assert hb["config_status"] == "ok"
    assert svc.cfg.cadence_s == 300

    # An unknown key is a broken edit too, not a silent ignore.
    cfg_path.write_text(good.replace("cadence_s = 600", "cadance_s = 600"))
    hb = svc.cycle()
    assert hb["config_status"].startswith("kept_last_good")
    assert "cadance_s" in hb["config_status"]


# ---------------------------------------------------------------------------
# manifests
# ---------------------------------------------------------------------------


def test_daily_manifest_rollup(tmp_path):
    store = Store(tmp_path / "a.sqlite")
    b1, b2 = b'{"x": 1}', b"\x80binary"
    store.record_fetch(route="callout_recent", url="u1", t_request_ms=T0,
                       t_response_ms=T0, status=200, body=b1)
    store.record_fetch(route="swap_candles", url="u2", t_request_ms=T0 + 1000,
                       t_response_ms=T0 + 1000, status=404, body=b2)
    day = utc_day(T0)
    out_dir = tmp_path / "manifests"
    written = manifest.write_pending(store, out_dir, today=utc_day(T0 + MS_DAY))
    assert [p.name for p in written] == [f"{day}.json"]

    payload = json.loads(written[0].read_text())
    assert payload["fetch_count"] == 2
    assert payload["total_bytes"] == len(b1) + len(b2)
    shas = [e["sha256"] for e in payload["fetches"]]
    assert shas == [hashlib.sha256(b1).hexdigest(), hashlib.sha256(b2).hexdigest()]
    lines = "\n".join(f"{e['id']}:{e['sha256']}:{e['bytes']}" for e in payload["fetches"])
    assert payload["rollup_sha256"] == hashlib.sha256(lines.encode()).hexdigest()

    # Idempotent: a second pass writes nothing and rewrites nothing.
    before = written[0].read_bytes()
    assert manifest.write_pending(store, out_dir, today=utc_day(T0 + MS_DAY)) == []
    assert written[0].read_bytes() == before
