"""Tests for the imitation-swarm detector. Offline: no socket, no HTTP, fixtures only.

The things worth breaking a build over here, each one a way the study's headline number
could have been wrong without anything looking wrong:

1. **A merge must not orphan an already-emitted onset.** Families merge when one launch
   links two of them; the onset row on disk carries whichever id was current then, so the
   surviving family has to remember every id it has ever been known by or the join from
   event back to family silently drops exactly the biggest swarms.
2. **The taxonomy split must actually split.** One deployer emitting N clones and N
   deployers emitting one each are opposite phenomena that produce identical family sizes.
   If ``taxonomy`` ever pools them the whole study is measuring launch farming.
3. **The detector must not look forward.** A replay over a tape has to produce exactly the
   event sequence a live process would have produced from the same stream — that
   equivalence is the only thing that makes the reported detection lag meaningful.
4. **The ambient null must preserve what it claims to preserve.** ``rotate_stream`` is the
   whole defence against "SOLANA launched 25 times" being read as a swarm; if it perturbs
   the launch-time process or the symbol distribution it is not a null, it is a second
   model.
5. **Eviction must be real.** An index that never forgets turns a 24-hour tape into one
   giant family and reports a detection at every collision in the day.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shitcoims_scalper.swarm_detect import (
    Launch,
    SwarmDetector,
    build_stream,
    levenshtein,
    listening_intervals,
    name_similarity,
    norm_text,
    plant_swarms,
    rotate_stream,
    shuffle_stream,
    squash_runs,
    taxonomy,
)


def mk(mint: str, t: float, symbol: str, dev: str, name: str | None = None, **kw) -> Launch:
    return Launch(
        mint=mint,
        symbol=symbol,
        name=name if name is not None else symbol,
        deployer=dev,
        t=t,
        t_source="vendor",
        sol_amount=kw.pop("sol_amount", 0.5),
        **kw,
    )


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------


def test_norm_text_strips_everything_but_alphanumerics():
    assert norm_text("$READ!!!") == "read"
    assert norm_text("  Sol-ana  ") == "solana"
    assert norm_text(None) == ""


def test_squash_runs_collapses_padding_to_one():
    # imitators pad a ticker to dodge exact match; collapsing to ONE is what makes the
    # padded and unpadded forms meet, and the known cost (BULL == BUL) is why the resulting
    # link is recorded as its own weaker match kind rather than as a symbol match
    assert squash_runs("readddddddddd") == "read"
    assert squash_runs("egg") == "eg"
    assert squash_runs("aaaa") == "a"


def test_two_letter_debris_does_not_fuse_coins():
    det = SwarmDetector(k=2, window_s=3600)
    det.push(mk("m1", 100, "AAA", "D0", name="alpha"))
    # "AAA" squashes to "a" and "AA" to "a"; below the 3-char floor nothing is indexed
    assert det.push(mk("m2", 120, "AA", "D1", name="beta")) == []


def test_levenshtein_abandons_above_cap():
    assert levenshtein("abc", "abc", 2) == 0
    assert levenshtein("abc", "abd", 2) == 1
    assert levenshtein("abc", "xyzzy", 1) == 2  # cap + 1, not a real distance


def test_name_similarity_is_normalised():
    assert name_similarity("trencher", "trencher") == 1.0
    assert name_similarity("trencher", "trenchers") == pytest.approx(1 - 1 / 9)
    assert name_similarity("trencher", "") == 0.0


# ---------------------------------------------------------------------------
# taxonomy — the split that must never be pooled
# ---------------------------------------------------------------------------


def test_taxonomy_separates_farm_from_parasite():
    from collections import Counter

    # one wallet shipping four clones: a factory
    assert taxonomy(4, Counter({"A": 4}), "HOST") == "farm"
    # four independent wallets, host's own deployer absent: the hypothesis
    assert taxonomy(4, Counter({"A": 1, "B": 1, "C": 1, "D": 1}), "HOST") == "parasite"
    # the host's own dev spamming their own idea is neither
    assert taxonomy(4, Counter({"HOST": 3, "B": 1}), "HOST") == "self_farm"
    # host present but not dominant
    assert taxonomy(4, Counter({"HOST": 1, "B": 1, "C": 1, "D": 1}), "HOST") == "mixed"
    assert taxonomy(0, Counter(), "HOST") == "singleton"


def test_taxonomy_threshold_is_a_strict_majority_not_a_plurality():
    from collections import Counter

    # 3 of 5 = 60% exactly is NOT a farm; the rule is "more than 60%", stated in the
    # docstring, and a boundary that drifts silently changes every proportion in the RESULT
    assert taxonomy(5, Counter({"A": 3, "B": 1, "C": 1}), "HOST") == "parasite"
    assert taxonomy(5, Counter({"A": 4, "B": 1}), "HOST") == "farm"


# ---------------------------------------------------------------------------
# clustering
# ---------------------------------------------------------------------------


def test_exact_symbol_forms_a_family_and_fires_at_k():
    det = SwarmDetector(k=3, window_s=3600)
    assert det.push(mk("m1", 100, "GRANNY", "D0")) == []
    assert det.push(mk("m2", 160, "GRANNY", "D1")) == []
    events = det.push(mk("m3", 200, "GRANNY", "D2"))
    assert len(events) == 1
    ev = events[0]
    assert ev["host_mint"] == "m1"
    assert ev["clone_count"] == 2
    assert ev["distinct_clone_deployers"] == 2
    assert ev["taxonomy"] == "parasite"
    assert ev["lag_from_host_s"] == 100
    assert ev["lag_from_first_clone_s"] == 40


def test_onset_fires_once_per_family():
    det = SwarmDetector(k=3, window_s=3600)
    for i in range(8):
        det.push(mk(f"m{i}", 100 + i, "SAME", f"D{i}"))
    fams = [f for f in det.families() if len(f.members) >= 2]
    assert len(fams) == 1
    assert fams[0].onset_index == 3  # fired at the third arrival and never again


def test_shared_metadata_uri_links_coins_with_different_tickers():
    # the strongest link in the payload: same IPFS document means same artwork and
    # description, whatever the ticker says
    det = SwarmDetector(k=2, window_s=3600)
    det.push(mk("m1", 100, "AAA", "D0", uri="ipfs://X"))
    ev = det.push(mk("m2", 120, "ZZZ", "D1", uri="ipfs://X"))
    assert len(ev) == 1
    assert ev[0]["match_kinds"] == {"uri": 1}


def test_squashed_symbol_links_padded_tickers():
    det = SwarmDetector(k=2, window_s=3600)
    det.push(mk("m1", 100, "READ", "D0"))
    ev = det.push(mk("m2", 120, "READDDDDDDD", "D1"))
    assert len(ev) == 1
    assert "symbol_squashed" in ev[0]["match_kinds"]


def test_near_name_links_and_unrelated_names_do_not():
    det = SwarmDetector(k=2, window_s=3600, name_threshold=0.82)
    det.push(mk("m1", 100, "AAA", "D0", name="Trencher"))
    ev = det.push(mk("m2", 120, "BBB", "D1", name="Trenchers"))
    assert len(ev) == 1 and "name_near" in ev[0]["match_kinds"]

    det2 = SwarmDetector(k=2, window_s=3600)
    det2.push(mk("m1", 100, "AAA", "D0", name="Trencher"))
    assert det2.push(mk("m2", 120, "BBB", "D1", name="Elephant")) == []


def test_eviction_stops_a_stale_launch_from_recruiting():
    det = SwarmDetector(k=2, window_s=600)
    det.push(mk("m1", 0, "GRANNY", "D0"))
    assert det.push(mk("m2", 5000, "GRANNY", "D1")) == []  # far outside the window
    assert all(len(f.members) == 1 for f in det.families())


def test_merge_preserves_the_id_an_onset_was_emitted_under():
    """Two families linked later by a bridging launch — the join must still work.

    ``A``/``A`` fires an onset under one id, ``B``/``B`` exists under another, and a coin
    carrying A's symbol and B's uri fuses them. The surviving family keeps only one id, so
    without the alias set the already-written event row points at a family that no longer
    exists and the biggest swarms vanish from the study.
    """
    det = SwarmDetector(k=2, window_s=3600)
    det.push(mk("a1", 100, "AAA", "D0", uri="u:A"))
    ev_a = det.push(mk("a2", 110, "AAA", "D1", uri="u:A"))
    det.push(mk("b1", 120, "BBB", "D2", uri="u:B"))
    ev_b = det.push(mk("b2", 130, "BBB", "D3", uri="u:B"))
    assert ev_a and ev_b
    det.push(mk("x1", 140, "AAA", "D4", uri="u:B"))  # the bridge

    rows = list(det.family_rows())
    assert len(rows) == 1
    fam = rows[0]
    assert fam["size"] == 5
    aliases = set(fam["aliases"])
    assert {ev_a[0]["family_id"], ev_b[0]["family_id"]} <= aliases


def test_host_traction_probe_overrides_earliest():
    """The earliest member we *saw* is not always the original.

    With a probe present the host is whoever had already transacted the most before onset,
    and the row records which rule fired so the two can be differenced in the study.
    """
    volumes = {"m1": 1.0, "m2": 900.0, "m3": 0.0}
    det = SwarmDetector(k=3, window_s=3600, traction=lambda m, t: volumes.get(m))
    det.push(mk("m1", 100, "SAME", "D0"))
    det.push(mk("m2", 110, "SAME", "D1"))
    ev = det.push(mk("m3", 120, "SAME", "D2"))
    assert ev[0]["host_mint"] == "m2"
    assert ev[0]["host_rule"] == "traction"
    assert ev[0]["host_is_earliest"] is False
    assert ev[0]["clone_count"] == 2  # the demoted earliest becomes a clone, not a ghost


def test_host_falls_back_to_earliest_when_nothing_has_traded():
    det = SwarmDetector(k=3, window_s=3600, traction=lambda m, t: 0.0)
    det.push(mk("m1", 100, "SAME", "D0"))
    det.push(mk("m2", 110, "SAME", "D1"))
    ev = det.push(mk("m3", 120, "SAME", "D2"))
    assert ev[0]["host_mint"] == "m1"
    assert ev[0]["host_rule"] == "earliest_no_traction"


def test_left_censoring_is_flagged_not_hidden():
    det = SwarmDetector(k=2, window_s=600)
    det.push(mk("m1", 1000, "SAME", "D0"))
    ev = det.push(mk("m2", 1100, "SAME", "D1"))
    # the family's first member is inside one window of the stream's own start, so the true
    # original may predate our listening
    assert ev[0]["host_left_censored"] is True

    # once a full window of CONTINUOUS tape sits behind the host, censoring lifts
    det2 = SwarmDetector(k=2, window_s=600)
    for i in range(20):
        det2.push(mk(f"bg{i}", i * 50.0, f"BG{i}", f"DX{i}", name=f"background {i}"))
    det2.push(mk("m1", 1000, "SAME", "D0"))
    ev2 = det2.push(mk("m2", 1100, "SAME", "D1"))
    assert ev2[0]["host_left_censored"] is False


def test_replay_is_causal():
    """Feeding the same stream one launch at a time yields the same events as in bulk.

    This is what licenses reading the emitted lags as a live decision latency. It would fail
    the moment any statistic were computed over the full tape rather than the prefix.
    """
    stream = [mk(f"m{i}", 100 * i, ["AAA", "BBB", "AAA", "CCC", "AAA"][i % 5], f"D{i%3}") for i in range(20)]
    a = SwarmDetector(k=3, window_s=3600)
    events_a = [e for ln in stream for e in a.push(ln)]
    b = SwarmDetector(k=3, window_s=3600)
    events_b = []
    for i in range(len(stream)):
        b_i = SwarmDetector(k=3, window_s=3600)
        got = [e for ln in stream[: i + 1] for e in b_i.push(ln)]
        events_b = got
    assert [e["family_id"] for e in events_a] == [e["family_id"] for e in events_b]
    assert [e["onset_mint"] for e in events_a] == [e["onset_mint"] for e in events_b]


# ---------------------------------------------------------------------------
# the ambient null
# ---------------------------------------------------------------------------


def test_rotation_preserves_times_and_the_symbol_multiset():
    stream = [mk(f"m{i}", i * 37.0, f"S{i%7}", f"D{i%5}") for i in range(50)]
    rot = rotate_stream(stream, 500.0)
    assert [l.t for l in rot] == [l.t for l in stream]
    assert sorted(l.symbol for l in rot) == sorted(l.symbol for l in stream)
    assert sorted(l.deployer for l in rot) == sorted(l.deployer for l in stream)
    assert [l.mint for l in rot] == [l.mint for l in stream]


def test_rotation_actually_moves_something():
    stream = [mk(f"m{i}", i * 60.0, f"S{i}", f"D{i}") for i in range(40)]
    rot = rotate_stream(stream, 600.0)
    assert any(a.symbol != b.symbol for a, b in zip(stream, rot, strict=True))


def test_rotation_of_a_pure_burst_destroys_the_burst():
    """A real swarm is time-localised; the null's version of it is scattered.

    Ten clones inside one minute, then ninety unrelated launches spread over hours. After
    rotation the ten shared symbols land on ten scattered timestamps, so a window-bounded
    detector no longer sees a family — which is exactly the collision floor the study
    compares against.
    """
    burst = [mk(f"b{i}", 1000 + i, "SWARM", f"D{i}") for i in range(10)]
    rest = [mk(f"r{i}", 2000 + i * 300, f"U{i}", f"E{i}") for i in range(90)]
    stream = sorted(burst + rest, key=lambda l: l.t)

    real = SwarmDetector(k=3, window_s=600)
    real_events = [e for ln in stream for e in real.push(ln)]
    assert len(real_events) == 1

    rot = rotate_stream(stream, 9000.0)
    null = SwarmDetector(k=3, window_s=600)
    null_events = [e for ln in rot for e in null.push(ln)]
    assert len(null_events) < len(real_events) + 1


# ---------------------------------------------------------------------------
# stream construction
# ---------------------------------------------------------------------------


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_build_stream_dedupes_and_prefers_the_vendor_clock(tmp_path):
    """Two sockets connected at once put every launch on the tape twice.

    Measured on the real tape for 2026-08-15: two overlapping windows for ten minutes, 316
    rows where ~170 launches happened. A study that counted rows would have reported double
    the launch rate and manufactured a family out of every coin.
    """
    fh = tmp_path / "new_token" / "day.jsonl"
    payload = {
        "signature": "s",
        "traderPublicKey": "DEV",
        "name": "Granny",
        "symbol": "GRANNY",
        "uri": "ipfs://x",
        "solAmount": 0.5,
        "initialBuy": 1.0,
        "marketCapSol": 30.0,
    }
    _write(
        fh,
        [
            {"kind": "new_token", "t_ingest": "2026-08-15T04:00:00+00:00", "mint": "m1",
             "payload": payload, "window_id": "w1"},
            {"kind": "new_token", "t_ingest": "2026-08-15T04:00:00.2+00:00", "mint": "m1",
             "payload": payload, "window_id": "w2"},
        ],
    )
    cen = tmp_path / "census.jsonl"
    _write(
        cen,
        [
            {"kind": "census_coin", "t_ingest": "2026-08-15T04:05:00+00:00", "mint": "m1",
             "created_timestamp": 1786852740000, "name": "Granny", "symbol": "GRANNY",
             "creator": "DEV", "image_uri": "ipfs://img", "metadata_uri": "ipfs://x"},
            {"kind": "census_coin", "t_ingest": "2026-08-15T04:05:00+00:00", "mint": "m2",
             "created_timestamp": 1786852745000, "name": "Granny", "symbol": "GRANNY",
             "creator": "DEV2", "image_uri": "ipfs://img", "metadata_uri": "ipfs://y"},
        ],
    )
    launches, stats = build_stream([fh], [cen])
    assert stats["firehose_rows"] == 2
    assert stats["firehose_dupe"] == 1
    assert stats["census_only"] == 1
    assert len(launches) == 2
    m1 = next(l for l in launches if l.mint == "m1")
    assert m1.t_source == "vendor"          # census clock wins over our socket clock
    assert m1.t == 1786852740.0
    assert m1.image_uri == "ipfs://img"     # the field PumpPortal never sends
    assert m1.sources == ("firehose", "census")


def test_listening_intervals_leave_a_hole_where_we_were_deaf(tmp_path):
    led = tmp_path / "ledger.jsonl"
    _write(
        led,
        [
            {"kind": "watch_open", "t_ingest": "2026-08-15T00:00:00+00:00",
             "window": {"window_id": "w1"}},
            {"kind": "watch_close", "t_ingest": "2026-08-15T00:10:00+00:00", "window_id": "w1"},
            {"kind": "watch_open", "t_ingest": "2026-08-15T03:00:00+00:00",
             "window": {"window_id": "w2"}},
            {"kind": "heartbeat", "t_ingest": "2026-08-15T03:30:00+00:00", "window_id": "w2"},
        ],
    )
    iv = listening_intervals([led])
    assert len(iv) == 2
    assert iv[0][1] - iv[0][0] == pytest.approx(600.0)
    # the still-open window ends at its last row, never at "now"
    assert iv[1][1] - iv[1][0] == pytest.approx(1800.0)
    # the 2h50m hole between them is not an interval, so a study excludes it
    assert not any(a <= _epoch("2026-08-15T01:30:00+00:00") <= b for a, b in iv)


def _epoch(iso: str) -> float:
    import datetime as dt

    return dt.datetime.fromisoformat(iso).timestamp()


# ---------------------------------------------------------------------------
# the known-EFFECT control
# ---------------------------------------------------------------------------

def _distinct_stream(n: int, seed: int = 11) -> list[Launch]:
    """A background stream in which nothing resembles anything else.

    Built from a seeded RNG rather than an f-string over an index, because the obvious
    fixture — ``f"name number {i}"`` — produces names differing in one character out of
    eleven, i.e. similarity 0.91, well over the 0.82 threshold. That fixture silently turned
    the "unrelated background" into one enormous clone family and made the recovery test fail
    for the fixture instead of for the detector. A background that is supposed to be inert
    has to be *checked* inert, which is what the assertion at the end of this function does.
    """
    import random as _random
    import string as _string

    rng = _random.Random(seed)
    out = []
    for i in range(n):
        word = "".join(rng.choice(_string.ascii_lowercase) for _ in range(12))
        sym = "".join(rng.choice(_string.ascii_uppercase) for _ in range(8))
        out.append(mk(f"m{i}", i * 30.0, sym, f"D{i}", name=word))
    det = SwarmDetector(k=2, window_s=1800)
    assert not [e for ln in out for e in det.push(ln)], "background fixture is not inert"
    return out


def test_single_linkage_transitivity_is_a_real_property_not_a_bug():
    """A ~ B and B ~ C puts A, B and C in one family even though A and C are unalike.

    This is inherent to union-merge clustering and it is *correct* for this domain — a
    campaign that drifts its ticker one character at a time is one campaign — but it means a
    family is a connected component, not a clique, and family size must never be read as
    "this many coins share a ticker". The largest real family in the tape spans `website`,
    `READDDDDDDDDD` and `GRANNY` and is held together by a shared image, which is exactly
    the behaviour wanted; the failure mode to watch is a background of near-identical names
    fusing into one component, which is what this test pins.
    """
    det = SwarmDetector(k=2, window_s=3600)
    det.push(mk("a", 0, "AAA", "D0", name="aardvark"))
    det.push(mk("b", 10, "BBB", "D1", name="aardvarks"))
    det.push(mk("c", 20, "CCC", "D2", name="aardvarkss"))
    fams = [f for f in det.families() if len(f.members) >= 2]
    assert len(fams) == 1 and len(fams[0].members) == 3
    # a and c are NOT directly similar enough; they are one family only through b
    assert name_similarity("aardvark", "aardvarkss") < 0.82


def test_planted_swarms_are_recovered():
    """PROGRAM.md §3.12: the zero-control alone certifies a broken detector.

    A detector that returns nothing passes every ambient null perfectly. So the planted
    world has to be recovered, and it has to be recovered *with the right host* — nominating
    a clone as the host would silently point every downstream position at the wrong coin.
    """
    base = _distinct_stream(400)
    stream, planted = plant_swarms(base, 20, clones=3, delay_s=120.0, seed=3)
    assert len(planted) == 20
    assert len(stream) == len(base) + 60

    det = SwarmDetector(k=3, window_s=1800)
    events = [e for ln in stream for e in det.push(ln)]
    hosts = {e["host_mint"] for e in events}
    assert len(hosts & set(planted)) == 20, "every planted swarm must be found, on its host"
    for e in events:
        if e["host_mint"] in planted:
            assert e["clone_count"] >= 2
            assert e["distinct_clone_deployers"] >= 2
            assert e["taxonomy"] == "parasite"


def test_planting_does_not_disturb_the_rest_of_the_stream():
    base = _distinct_stream(400)
    stream, planted = plant_swarms(base, 10, clones=3, seed=5)
    # every original launch survives unchanged and in time order
    originals = [l for l in stream if not l.mint.startswith("PLANT")]
    assert [l.mint for l in originals] == [l.mint for l in base]
    assert all(l.t_source == "planted" for l in stream if l.mint.startswith("PLANT"))


def test_shuffle_preserves_marginals_but_scatters_a_burst():
    """The collision floor must actually destroy co-arrival, unlike rotation.

    Rotation on a near-constant launch rate carries a burst intact — that is measured on the
    real tape and documented — so the i.i.d. shuffle is the null that has to do this job.
    """
    burst = [mk(f"b{i}", 5000 + i, "SWARM", f"D{i}") for i in range(12)]
    rest = [mk(f"r{i}", i * 40.0, f"U{i}", f"E{i}") for i in range(400)]
    stream = sorted(burst + rest, key=lambda l: l.t)

    real = SwarmDetector(k=3, window_s=600)
    assert len([e for ln in stream for e in real.push(ln)]) == 1

    shuffled = shuffle_stream(stream, seed=7)
    assert [l.t for l in shuffled] == [l.t for l in stream]
    assert sorted(l.symbol for l in shuffled) == sorted(l.symbol for l in stream)
    null = SwarmDetector(k=3, window_s=600)
    assert len([e for ln in shuffled for e in null.push(ln)]) == 0


def test_left_censoring_restarts_after_a_hole_in_the_tape():
    """A 172-minute socket outage exists in the real tape; it must reset the horizon.

    Without this, a coin launched two minutes after the socket came back is called
    "uncensored" even though every possible parent inside the outage is invisible — and it
    would then be nominated as a host and traded as an original.
    """
    det = SwarmDetector(k=2, window_s=1800)
    det.push(mk("a", 0, "AAA", "D0", name="aardvark"))
    det.push(mk("b", 100, "BBB", "D1", name="bicycle"))
    # ... 3 hours of nothing: we were not listening ...
    det.push(mk("m1", 11000, "SAME", "D2", name="cinnamon"))
    ev = det.push(mk("m2", 11100, "SAME", "D3", name="cinnamon"))
    assert ev[0]["host_left_censored"] is True, "post-hole hosts have no visible history"

    # and once enough CONTINUOUS post-hole tape has accumulated, censoring lifts again
    for i in range(30):
        det.push(mk(f"bg{i}", 11200 + i * 60.0, f"BG{i}", f"D{100+i}", name=f"background {i}"))
    det.push(mk("n1", 13100, "OTHER", "D4", name="eggplant"))
    ev2 = det.push(mk("n2", 13160, "OTHER", "D5", name="eggplant"))
    assert ev2[0]["host_left_censored"] is False
