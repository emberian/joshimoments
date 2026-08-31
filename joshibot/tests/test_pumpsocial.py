"""Tests for the pump social surface.

Every test here is OFFLINE: the client takes an injectable transport, so the bodies below
are real recorded responses replayed without a network. That matters for a reverse-
engineered surface — a test suite that needs pump.fun to be up tests pump.fun's uptime,
not our parsing, and goes red for the wrong reason at 3am.

The tests are weighted towards the REFUSALS and the TRAPS rather than the happy path,
because the happy path is what `python -m shitcoims_pumpsocial probe` checks against
production and the traps are what silently corrupt a dataset.
"""

from __future__ import annotations

import json

import pytest

from shitcoims_pumpsocial import (
    ENDPOINTS,
    MutatingEndpointRefused,
    PumpSocialClient,
    PumpSocialError,
    crawl_thread,
    on_curve,
)
from shitcoims_pumpsocial.client import NotFound, _callout_page, _page
from shitcoims_pumpsocial.endpoints import BY_NAME, LIVE, READABLE
from shitcoims_pumpsocial.models import (
    Quarantined,
    parse_callout,
    parse_follow_edge,
    parse_native_callout,
    parse_post,
    parse_profile,
)

JACK = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh"
IMPOSTER = "9T8QKsR28boKJL3x3td39rX8dk1xsd5zwWaF2nFzijvP"
DREGG = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"


def stub(routes: dict[str, object], *, record: list | None = None):
    """A transport that answers by URL substring. Returns (status, headers, body)."""

    def transport(method, url, headers, body):
        if record is not None:
            record.append((method, url, headers, body))
        for needle, response in routes.items():
            if needle in url:
                if isinstance(response, tuple):
                    status, payload = response
                else:
                    status, payload = 200, response
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                return status, {}, raw
        return 404, {}, json.dumps({"message": "Not Found"}).encode()

    return transport


def client(routes, **kw):
    return PumpSocialClient(transport=stub(routes), sleep=lambda _s: None, **kw)


# ---------------------------------------------------------------------------
# the read-only guarantee
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [e.name for e in ENDPOINTS if e.mutating])
def test_every_mutating_endpoint_is_refused(name):
    """The operator's pump identity is theirs. This package cannot act as them.

    Enumerated over the catalogue rather than spot-checked, so adding a mutating route
    without a refusal is impossible: the new route generates its own test case.
    """

    with pytest.raises(MutatingEndpointRefused):
        client({}).request(name)


def test_refusal_happens_before_any_transport_call():
    """A refusal must not be 'we sent it and ignored the answer'."""

    calls: list = []
    api = PumpSocialClient(transport=stub({}, record=calls), sleep=lambda _s: None)
    with pytest.raises(MutatingEndpointRefused):
        api.request("follow_user", path_params={"user_id": "x"})
    assert calls == []


def test_mutating_routes_are_excluded_from_the_live_set():
    assert all(not e.mutating for e in LIVE)
    assert all(not e.mutating for e in READABLE)


def test_no_bearer_or_signing_credential_is_ever_sent():
    """`x-api-key` is a public browser key; nothing here may send an Authorization header."""

    calls: list = []
    api = PumpSocialClient(transport=stub({"/users/": {"address": JACK}}, record=calls),
                           sleep=lambda _s: None)
    api.request("user_profile_v3", path_params={"key": JACK})
    sent = calls[0][2]
    assert "Authorization" not in sent and "authorization" not in sent


# ---------------------------------------------------------------------------
# the identity-substitution trap
# ---------------------------------------------------------------------------


def test_profile_rejects_a_substituted_identity():
    """`/users/batch` returns HTTP 200 describing a DIFFERENT wallet. That must raise.

    This is the live hazard, not a hypothetical: the endpoint resolves usernames as well
    as addresses, and `wallet_labels.yaml` records an address-poisoning campaign against
    this operator built on lookalike addresses. A resolver that silently answers about
    another wallet is the thing being defended against.
    """

    other = "He7it3jD9BQ2wHLfJUSvAw1AZK3VoMPPu2ZeDdMAWv3v"
    api = client({"/users/": {"address": other, "username": "batch", "followers": 0}})
    with pytest.raises(PumpSocialError, match="substituted an identity"):
        api.profile(JACK)


def test_profile_accepts_a_matching_echo():
    api = client({"/users/": {"address": JACK, "username": "jackduvalcalls", "followers": 17479}})
    data, prov = api.profile(JACK)
    assert data["username"] == "jackduvalcalls"
    assert prov.endpoint_name == "user_profile_v3"
    assert prov.t_ingest  # the second clock is always stamped


# ---------------------------------------------------------------------------
# address hygiene
# ---------------------------------------------------------------------------


def test_on_curve_separates_wallets_from_non_keys():
    assert on_curve(JACK) is True
    assert on_curve("not-base58-at-all!!") is None
    assert on_curve("cef4bed6-680b-491c-8089-1f3c6bfe763b") is None


def test_a_uuid_can_never_become_a_wallet():
    """The two backends both call their author key `userId`; one is a UUID, one a wallet.

    If a coin-communities row were ever fed to the native-callout parser, the UUID must
    QUARANTINE rather than land in `caller_wallet`. This is the highest-probability join
    corruption on this surface, so it gets an explicit test.
    """

    with pytest.raises(Quarantined, match="userId_not_base58_32"):
        parse_native_callout(
            {"calloutId": "c1", "userId": "cef4bed6-680b-491c-8089-1f3c6bfe763b",
             "coinMint": DREGG},
            t_ingest="2026-08-15T00:00:00+00:00",
        )


def test_post_without_a_wallet_is_quarantined_not_defaulted():
    with pytest.raises(Quarantined, match="walletAddress_missing"):
        parse_post({"id": "m1", "content": "hi"}, kind="message",
                   t_ingest="2026-08-15T00:00:00+00:00")


# ---------------------------------------------------------------------------
# clocks and the four-state discipline
# ---------------------------------------------------------------------------


def test_absent_counts_are_none_never_zero():
    """`design/glass.md` §0.3: "no data" is never zero. A missing count stays None."""

    post = parse_post(
        {"id": "m1", "walletAddress": JACK, "content": "x"},
        kind="message", t_ingest="2026-08-15T00:00:00+00:00",
    )
    assert post.like_count is None
    assert post.reply_count is None
    assert post.t_event is None  # no createdAt -> no invented clock


def test_measured_zero_is_kept_distinct_from_absent():
    post = parse_post(
        {"id": "m1", "walletAddress": JACK, "content": "x", "likeCount": 0, "replyCount": 0},
        kind="message", t_ingest="2026-08-15T00:00:00+00:00",
    )
    assert post.like_count == 0 and post.reply_count == 0


def test_two_clocks_are_separate_fields():
    post = parse_post(
        {"id": "m1", "walletAddress": JACK, "content": "x",
         "createdAt": "2026-06-27T13:30:45.478528Z"},
        kind="message", t_ingest="2026-08-15T09:00:00+00:00",
    )
    assert post.t_event.startswith("2026-06-27")
    assert post.t_ingest.startswith("2026-08-15")


def test_follow_edge_carries_the_follow_timestamp():
    edge = parse_follow_edge(
        {"address": JACK, "username": "jackduvalcalls", "timestamp": 1785841959626,
         "followers": 17482},
        follower=IMPOSTER, t_ingest="2026-08-15T00:00:00+00:00",
    )
    assert edge.follower == IMPOSTER and edge.followee == JACK
    assert edge.t_follow is not None and edge.t_follow.startswith("2026-")


# ---------------------------------------------------------------------------
# the X join
# ---------------------------------------------------------------------------


def test_twitter_numeric_id_is_extracted_from_the_profile_url():
    post = parse_post(
        {"id": "m1", "walletAddress": JACK, "content": "x",
         "userTwitterUrl": "https://x.com/i/user/294759965"},
        kind="message", t_ingest="2026-08-15T00:00:00+00:00",
    )
    assert post.author.twitter_id == "294759965"


def test_a_non_numeric_twitter_url_yields_none_not_a_guess():
    post = parse_post(
        {"id": "m1", "walletAddress": JACK, "content": "x",
         "userTwitterUrl": "https://x.com/jackduval"},
        kind="message", t_ingest="2026-08-15T00:00:00+00:00",
    )
    assert post.author.twitter_id is None


def test_the_two_follower_counts_stay_separate():
    """17,447 native vs 44,267 combined for the same person. They must never merge."""

    profile = parse_profile(
        {"address": JACK, "username": "jackduvalcalls", "followers": 17447, "following": 0},
        t_ingest="2026-08-15T00:00:00+00:00",
        cc_user={"user_id": "cef4bed6", "twitter_id": "1592708747943497728"},
        cc_profile={"user": {"followerCount": 44267, "nativeFollowerCount": 17447}},
    )
    assert profile.native_followers == 17447
    assert profile.combined_followers == 44267
    assert profile.twitter_id == "1592708747943497728"


# ---------------------------------------------------------------------------
# the callout scoring semantics
# ---------------------------------------------------------------------------


def test_native_multiple_is_a_peak_ratio_bounded_below_by_one():
    """Measured on 500 live callouts: `multiple == max(1, round(maxPriceSol/calloutPrice, 1))`.

    The consequence is the finding: this metric CANNOT express a losing call, so a
    "68% hit 2x" scoreboard built on it is a statement about peaks, never about returns.
    """

    row = {"calloutId": "c1", "userId": JACK, "coinMint": DREGG,
           "calloutPrice": 3.0050392461434085e-06, "maxPriceSol": 1.976244221989435e-05,
           "multiple": 6.6, "createdAt": 1783858767913, "peakTimestamp": 1784388005600}
    callout = parse_native_callout(row, t_ingest="2026-08-15T00:00:00+00:00")
    assert callout.multiple == pytest.approx(
        max(1.0, round(row["maxPriceSol"] / row["calloutPrice"], 1))
    )
    assert callout.caller_wallet == JACK


def test_coin_communities_multiplier_can_be_below_one():
    """The OTHER backend's `multiplier` is a live ratio and does go down — different field,
    different meaning, same word. Parsed into a differently-named record on purpose."""

    callout = parse_callout(
        {"id": "c1", "walletAddress": JACK, "content": "call", "multiplier": 0.3876,
         "maxMultiplier": 1.624, "calloutPrice": 0.0007, "calloutMarketCap": 708248.0},
        t_ingest="2026-08-15T00:00:00+00:00", mint=DREGG,
    )
    assert callout.multiplier < 1 < callout.max_multiplier
    assert callout.as_dict()["callout_market_cap"] == 708248.0


# ---------------------------------------------------------------------------
# pagination and truncation
# ---------------------------------------------------------------------------


def test_full_page_without_a_cursor_is_reported_as_truncated():
    """The bug this suite exists to prevent regressing.

    `messages_public` caps at 50 rows and returns no cursor of any spelling, so a capped
    page is indistinguishable from a finished one unless you check the row count. The
    first version of this crawler reported 59 of a coin's 176 posts as COMPLETE.
    """

    rows = [{"id": f"m{i}", "walletAddress": JACK, "content": "x"} for i in range(3)]
    api = client({"/messages/public": {"messages": rows}, "/callouts/public": {"callouts": []}})
    _posts, report = crawl_thread(api, DREGG, limit=3, max_pages=5)
    assert report.truncated, "a full page with no cursor must not read as complete"
    assert report.as_dict()["complete"] is False


def test_short_page_is_reported_as_complete():
    rows = [{"id": f"m{i}", "walletAddress": JACK, "content": "x"} for i in range(2)]
    api = client({"/messages/public": {"messages": rows}, "/callouts/public": {"callouts": []}})
    _posts, report = crawl_thread(api, DREGG, limit=50, max_pages=5)
    assert report.truncated == []
    assert report.as_dict()["complete"] is True


def test_unreadable_reply_tail_is_counted_as_censored():
    """Comment replies are countable but not readable. The gap is a number, not a silence."""

    rows = [{"id": "m1", "walletAddress": JACK, "content": "x", "replyCount": 7}]
    api = client({"/messages/public": {"messages": rows}, "/callouts/public": {"callouts": []}})
    _posts, report = crawl_thread(api, DREGG, limit=50, max_pages=5)
    assert report.censored_replies == 7


def test_callout_page_treats_empty_string_token_as_exhausted():
    assert _callout_page({"callouts": [{"a": 1}], "nextPageToken": ""}) == ([{"a": 1}], None)
    assert _callout_page({"callouts": [], "nextPageToken": "abc"}) == ([], "abc")


def test_page_unwrapper_returns_no_cursor_rather_than_looping():
    assert _page({"messages": [{"id": "x"}]}, "messages") == ([{"id": "x"}], None)
    assert _page({"messages": "not-a-list"}, "messages") == ([], None)


# ---------------------------------------------------------------------------
# transport behaviour
# ---------------------------------------------------------------------------


def test_rate_limit_retry_honours_retry_after_then_succeeds():
    state = {"n": 0}
    slept: list[float] = []

    def transport(method, url, headers, body):
        state["n"] += 1
        if state["n"] <= 2:
            return 429, {"retry-after": "1"}, b""
        return 200, {}, json.dumps({"address": JACK}).encode()

    api = PumpSocialClient(transport=transport, sleep=slept.append)
    data, _ = api.profile(JACK)
    assert data["address"] == JACK
    assert api.stats.retries_429 == 2
    assert slept and all(s > 0 for s in slept)


def test_rate_limit_gives_up_rather_than_hammering():
    api = PumpSocialClient(
        transport=lambda *a: (429, {"retry-after": "1"}, b""),
        sleep=lambda _s: None,
        max_429_retries=2,
    )
    with pytest.raises(PumpSocialError, match="rate limited"):
        api.profile(JACK)


def test_404_is_an_answer_with_its_own_exception_type():
    api = client({})
    with pytest.raises(NotFound):
        api.request("community", path_params={"mint": DREGG})
    assert api.stats.not_found == 1


def test_source_stated_staleness_is_carried_separately_from_our_clock():
    """`feed_public` serves a CACHE and says so. That is a third clock, not `t_event`."""

    api = client({"/feed/public": {"items": [], "computedAt": "2026-08-06T05:39:30Z"}})
    _data, prov = api.request("feed_public")
    assert prov.t_source_computed == "2026-08-06T05:39:30Z"
    assert prov.t_ingest != prov.t_source_computed


def test_unfilled_path_parameter_raises_rather_than_requesting_a_literal_brace():
    api = client({})
    with pytest.raises(PumpSocialError, match="unfilled"):
        api.request("community")


def test_unknown_path_parameter_is_rejected():
    api = client({})
    with pytest.raises(PumpSocialError, match="no path parameter"):
        api.request("community", path_params={"wallet": JACK})


def test_pacing_is_per_host_and_serialises_requests():
    now = {"t": 0.0}
    slept: list[float] = []
    api = PumpSocialClient(
        transport=stub({"/users/": {"address": JACK}}),
        sleep=lambda s: (slept.append(s), now.__setitem__("t", now["t"] + s)),
        clock=lambda: now["t"],
    )
    api.profile(JACK)
    api.profile(JACK)
    assert slept, "the second call to the same host must wait"


# ---------------------------------------------------------------------------
# catalogue integrity
# ---------------------------------------------------------------------------


def test_endpoint_names_are_unique():
    names = [e.name for e in ENDPOINTS]
    assert len(names) == len(set(names))
    assert len(BY_NAME) == len(ENDPOINTS)


def test_every_endpoint_declares_a_known_host_and_auth():
    for spec in ENDPOINTS:
        assert spec.host.startswith("https://")
        assert spec.auth in {"none", "api_key", "bearer_user", "server_secret"}
        assert spec.verdict in {"live", "dead", "auth_walled", "unmeasured"}


def test_api_key_is_only_attached_to_routes_that_declare_it():
    calls: list = []
    api = PumpSocialClient(
        transport=stub({"pump.fun": {"address": JACK}, "coin-communities": {"community": {}}},
                       record=calls),
        sleep=lambda _s: None,
    )
    api.request("user_profile_v3", path_params={"key": JACK})   # auth="none"
    api.request("community", path_params={"mint": DREGG})       # auth="api_key"
    assert "x-api-key" not in calls[0][2]
    assert "x-api-key" in calls[1][2]


def test_dead_routes_are_not_offered_as_live():
    """The catalogue's whole job. A route measured 404 must not appear in LIVE."""

    assert "message_replies_public" in BY_NAME
    assert BY_NAME["message_replies_public"].verdict == "dead"
    assert "message_replies_public" not in {e.name for e in LIVE}
