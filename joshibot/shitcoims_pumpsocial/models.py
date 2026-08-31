"""Typed records for the pump social surface, and the hygiene every address passes.

WHAT MAKES THESE RECORDS DIFFERENT FROM THE X RECORDS
------------------------------------------------------
`RESULT_caller_wallets.md` had to *resolve* an author: a tweet carries a handle, a handle
is not a wallet, and the join succeeded for 5 of 146 handles. Here the author IS a wallet —
`walletAddress` is a field on every message, reply and callout — so `Author` is not a
resolution attempt with a confidence score, it is a parse. That is the whole reason this
surface is worth crawling.

The corollary is an obligation. An address that arrives as a native field still arrives
from a third-party host (`api.coin-communities.xyz` is not a pump.fun domain), and
`wallet_labels.yaml` records both a live address-poisoning campaign against this operator
and two fabricated addresses that reached that file this week. So every address parsed here
passes the on-curve test before it is allowed into a record, and one that fails is
QUARANTINED with its reason rather than dropped — a silent drop turns an attack into a
smaller sample, which is the failure mode you cannot see afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# address hygiene
# ---------------------------------------------------------------------------

_ED_P = 2**255 - 19
_ED_D = 37095705934669439343138083508754565189542113879843219016388785533085940283555
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}


def _b58decode(value: str) -> bytes:
    number = 0
    for char in value:
        number = number * 58 + _B58_INDEX[char]
    body = number.to_bytes((number.bit_length() + 7) // 8, "big")
    pad = len(value) - len(value.lstrip("1"))
    return b"\x00" * pad + body


def on_curve(address: str) -> bool | None:
    """True if `address` is a real ed25519 public key — an account that CAN sign.

    Deliberately a copy of `studies.copytrading.on_curve`'s arithmetic rather than an
    import: a package under `shitcoims_*` importing from `studies/` would invert the
    dependency direction (research reads the packages, not the other way round). Pure
    arithmetic, no RPC, no list to maintain. None means "not even base58/32 bytes".
    """

    try:
        raw = _b58decode(address)
    except (ValueError, KeyError):
        return None
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, "little")
    sign = (y >> 255) & 1
    y &= (1 << 255) - 1
    if y >= _ED_P:
        return False
    u = (y * y - 1) % _ED_P
    v = (_ED_D * y * y + 1) % _ED_P
    x = pow((u * pow(v, _ED_P - 2, _ED_P)) % _ED_P, (_ED_P + 3) // 8, _ED_P)
    if (v * x * x - u) % _ED_P != 0:
        x = (x * pow(2, (_ED_P - 1) // 4, _ED_P)) % _ED_P
        if (v * x * x - u) % _ED_P != 0:
            return False
    return not (x == 0 and sign == 1)


class Quarantined(ValueError):
    """A record that did not parse. Counted, never silently dropped."""


# ---------------------------------------------------------------------------
# clocks
# ---------------------------------------------------------------------------


def parse_iso(value: Any) -> str | None:
    """Normalise the API's `createdAt` to a UTC ISO string, or None.

    None is a real answer and is preserved as None. It must never become 0 or "now" —
    "no data is never zero" is a platform contract in `design/glass.md` §0.3, and a
    fabricated timestamp is how a callout gets scored against the wrong bar.
    """

    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def parse_ms(value: Any) -> str | None:
    """Millisecond epoch -> UTC ISO. The follow graph and `latestPostAt` use these."""

    if not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _address(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise Quarantined(f"{field}_missing")
    verdict = on_curve(value)
    if verdict is None:
        raise Quarantined(f"{field}_not_base58_32")
    if verdict is False:
        raise Quarantined(f"{field}_off_curve")
    return value


def _text(value: Any, *, limit: int = 8_000) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise Quarantined("text_not_a_string")
    return value[:limit]


def _int(value: Any) -> int | None:
    """Counts are tri-state: a number, or absent. Absent is None, never 0."""

    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _twitter_id(url: Any) -> str | None:
    """`https://x.com/i/user/294759965` -> `294759965`.

    The API gives the NUMERIC id, not the handle, which is the strictly better join key:
    a handle can be changed or squatted (that is the homoglyph impersonator's entire
    method), a numeric id cannot. `RESULT_caller_wallets.md` §1 route 2 was declared dead
    because frontend-api-v3 profiles carry `x_username: null`; this field is that route,
    alive, on the other backend.
    """

    if not isinstance(url, str):
        return None
    marker = "/i/user/"
    if marker not in url:
        return None
    tail = url.rsplit(marker, 1)[1].strip("/")
    return tail if tail.isdigit() else None


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Author:
    """A pump social author. Natively a wallet — this is a parse, not a resolution."""

    wallet: str
    user_id: str | None
    username: str | None
    display_name: str | None
    twitter_id: str | None
    #: The author's follower count AS REPORTED ON THIS POST. It is a snapshot at read
    #: time, not at post time, and it is a DIFFERENT number from the profile's
    #: `nativeFollowerCount`. Kept separate for exactly that reason.
    follower_count_at_read: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "wallet": self.wallet,
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "twitter_id": self.twitter_id,
            "follower_count_at_read": self.follower_count_at_read,
        }


def parse_author(row: dict[str, Any]) -> Author:
    return Author(
        wallet=_address(row.get("walletAddress"), field="walletAddress"),
        user_id=row.get("userId") if isinstance(row.get("userId"), str) else None,
        username=row.get("username") if isinstance(row.get("username"), str) else None,
        display_name=row.get("displayName") if isinstance(row.get("displayName"), str) else None,
        twitter_id=_twitter_id(row.get("userTwitterUrl")),
        follower_count_at_read=_int(row.get("followerCount")),
    )


@dataclass(frozen=True, slots=True)
class Post:
    """A comment, a reply, or a callout — the shapes are near-identical, so one record.

    `kind` distinguishes them. `parent_message_id` / `parent_callout_id` carry the thread
    structure; both None means a top-level post.
    """

    post_id: str
    kind: str  # "message" | "callout" | "feed"
    mint: str | None
    community_id: str | None
    author: Author
    content: str
    t_event: str | None        # the API's createdAt — the post's own clock
    t_ingest: str              # when we read it — ours
    like_count: int | None
    reply_count: int | None
    parent_message_id: str | None
    parent_callout_id: str | None
    is_spam: bool | None
    is_harmful: bool | None
    media_url: str | None
    mentioned_user_ids: tuple[str, ...]
    deleted_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "post_id": self.post_id,
            "kind": self.kind,
            "mint": self.mint,
            "community_id": self.community_id,
            "author": self.author.as_dict(),
            "content": self.content,
            "t_event": self.t_event,
            "t_ingest": self.t_ingest,
            "like_count": self.like_count,
            "reply_count": self.reply_count,
            "parent_message_id": self.parent_message_id,
            "parent_callout_id": self.parent_callout_id,
            "is_spam": self.is_spam,
            "is_harmful": self.is_harmful,
            "media_url": self.media_url,
            "mentioned_user_ids": list(self.mentioned_user_ids),
            "deleted_at": self.deleted_at,
        }


def parse_post(row: dict[str, Any], *, kind: str, t_ingest: str, mint: str | None = None) -> Post:
    post_id = row.get("id")
    if not isinstance(post_id, str) or not post_id:
        raise Quarantined("id_missing")
    row_mint = row.get("tokenAddress")
    mentions = row.get("mentionedUserIds")
    return Post(
        post_id=post_id,
        kind=kind,
        mint=row_mint if isinstance(row_mint, str) else mint,
        community_id=row.get("communityId") if isinstance(row.get("communityId"), str) else None,
        author=parse_author(row),
        content=_text(row.get("content")),
        t_event=parse_iso(row.get("createdAt")),
        t_ingest=t_ingest,
        like_count=_int(row.get("likeCount")),
        reply_count=_int(row.get("replyCount")),
        parent_message_id=row.get("parentMessageId") if isinstance(row.get("parentMessageId"), str) else None,
        parent_callout_id=row.get("parentCalloutId") if isinstance(row.get("parentCalloutId"), str) else None,
        is_spam=row.get("isSpam") if isinstance(row.get("isSpam"), bool) else None,
        is_harmful=row.get("isHarmful") if isinstance(row.get("isHarmful"), bool) else None,
        media_url=row.get("mediaUrl") if isinstance(row.get("mediaUrl"), str) else None,
        mentioned_user_ids=tuple(m for m in (mentions or []) if isinstance(m, str)),
        deleted_at=parse_iso(row.get("deletedAt")),
    )


@dataclass(frozen=True, slots=True)
class Callout(Post):
    """A callout, plus the platform's own scoring of it.

    READ THE MULTIPLIER FIELDS CAREFULLY. `max_multiplier` is the peak the coin reached
    at `max_multiplier_at`, and the measured mean `averageTimeToPeak` on a real caller is
    ~29 days. It is therefore a PEAK-AT-ANY-LATER-TIME statistic, not a return anyone
    could have taken: pump's own leaderboard says jackduvalcalls hits 2x on 68% of calls,
    while this repo's `RESULT_callout_edge.md` measures buying AT the callout at -11.9% at
    1 h and -43.6% at 8 h. Both numbers are correct and they measure different things. The
    fields are kept because the ENTRY side is the valuable part: `callout_price` and
    `callout_market_cap` are the platform's own record of the bar the call was made at,
    which is exactly the join key an event study needs and which no other source gives us
    for free.
    """

    multiplier: float | None
    max_multiplier: float | None
    max_multiplier_at: str | None
    callout_price: float | None
    callout_market_cap: float | None

    def as_dict(self) -> dict[str, Any]:
        # Explicit base call, not `super()`: `@dataclass(slots=True)` returns a NEW class
        # object, so the zero-argument `super()`'s compile-time __class__ cell points at
        # the pre-decoration class and raises at runtime. This bites once per codebase.
        base = Post.as_dict(self)
        base.update(
            {
                "multiplier": self.multiplier,
                "max_multiplier": self.max_multiplier,
                "max_multiplier_at": self.max_multiplier_at,
                "callout_price": self.callout_price,
                "callout_market_cap": self.callout_market_cap,
            }
        )
        return base


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_callout(row: dict[str, Any], *, t_ingest: str, mint: str | None = None) -> Callout:
    base = parse_post(row, kind="callout", t_ingest=t_ingest, mint=mint)
    return Callout(
        **{f.name: getattr(base, f.name) for f in dataclass_fields(base)},
        multiplier=_float(row.get("multiplier")),
        max_multiplier=_float(row.get("maxMultiplier")),
        max_multiplier_at=parse_iso(row.get("maxMultiplierAt")),
        callout_price=_float(row.get("calloutPrice")),
        callout_market_cap=_float(row.get("calloutMarketCap")),
    )


@dataclass(frozen=True, slots=True)
class NativeCallout:
    """A callout from pump's OWN `/callout/*` family — a different shape, same event.

    The field this record exists to disambiguate is `userId`. On `frontend-api-v3`'s
    callout family `userId` is a WALLET ADDRESS; on `api.coin-communities.xyz` a field of
    the identical name is a UUID. Two id systems sharing a field name across two backends
    that both describe callouts is the highest-probability join corruption on this
    surface, so here the wallet is parsed into `caller_wallet` (on-curve checked) and the
    UUID never enters this record at all.

    `multiple` and `max_price_sol`/`peak_t` are PEAK statistics — see `Callout`.
    """

    callout_id: str
    caller_wallet: str
    mint: str
    thesis: str
    t_event: str | None        # `createdAt`, ms epoch -> ISO
    t_ingest: str
    callout_price: float | None
    market_cap: float | None
    multiple: float | None
    max_price_sol: float | None
    peak_t: str | None
    username: str | None
    x_username: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "callout_id": self.callout_id,
            "caller_wallet": self.caller_wallet,
            "mint": self.mint,
            "thesis": self.thesis,
            "t_event": self.t_event,
            "t_ingest": self.t_ingest,
            "callout_price": self.callout_price,
            "market_cap": self.market_cap,
            "multiple": self.multiple,
            "max_price_sol": self.max_price_sol,
            "peak_t": self.peak_t,
            "username": self.username,
            "x_username": self.x_username,
        }


def parse_native_callout(row: dict[str, Any], *, t_ingest: str) -> NativeCallout:
    callout_id = row.get("calloutId")
    if not isinstance(callout_id, str) or not callout_id:
        raise Quarantined("calloutId_missing")
    return NativeCallout(
        callout_id=callout_id,
        # `userId` is a wallet on this family. The on-curve check is what stops a UUID
        # from ever silently occupying this field: a UUID is not base58/32 bytes, so it
        # quarantines as `userId_not_base58_32` instead of becoming a fake address.
        caller_wallet=_address(row.get("userId"), field="userId"),
        mint=_address(row.get("coinMint"), field="coinMint"),
        thesis=_text(row.get("thesis"), limit=4_000),
        t_event=parse_ms(row.get("createdAt")),
        t_ingest=t_ingest,
        callout_price=_float(row.get("calloutPrice")),
        market_cap=_float(row.get("marketCap")),
        multiple=_float(row.get("multiple")),
        max_price_sol=_float(row.get("maxPriceSol")),
        peak_t=parse_ms(row.get("peakTimestamp")),
        username=row.get("username") if isinstance(row.get("username"), str) else None,
        x_username=row.get("xUsername") if isinstance(row.get("xUsername"), str) else None,
    )


@dataclass(frozen=True, slots=True)
class FollowEdge:
    """One directed follow, with the clock the graph is actually interesting for.

    `t_follow` is why this endpoint matters more than a follower count: it turns the
    social graph into an EVENT stream. The homoglyph impersonator in `wallet_labels.yaml`
    was pinned as deliberate rather than coincidental precisely by ordering two of these
    timestamps — it followed its target on 2026-08-04 and renamed itself to a lookalike
    on 2026-08-09.
    """

    follower: str          # the wallet doing the following (the crawl root)
    followee: str          # the wallet being followed
    t_follow: str | None
    followee_username: str | None
    followee_followers: int | None
    t_ingest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "follower": self.follower,
            "followee": self.followee,
            "t_follow": self.t_follow,
            "followee_username": self.followee_username,
            "followee_followers": self.followee_followers,
            "t_ingest": self.t_ingest,
        }


def parse_follow_edge(row: dict[str, Any], *, follower: str, t_ingest: str) -> FollowEdge:
    return FollowEdge(
        follower=follower,
        followee=_address(row.get("address"), field="address"),
        t_follow=parse_ms(row.get("timestamp")),
        followee_username=row.get("username") if isinstance(row.get("username"), str) else None,
        followee_followers=_int(row.get("followers")),
        t_ingest=t_ingest,
    )


@dataclass(frozen=True, slots=True)
class Profile:
    """A pump identity, assembled from BOTH backends.

    The two follower counts are deliberately separate fields. frontend-api-v3 and
    coin-communities report different numbers for the same person because they count
    different populations (`native_followers` is pump.fun's own; `combined_followers`
    includes the linked X audience). `design/glass.md` §0.4 — measured and attested never
    sum — applies to this pair: they are never added, and a renderer that wants one must
    say which.
    """

    wallet: str
    username: str | None
    bio: str | None
    native_followers: int | None
    native_following: int | None
    combined_followers: int | None
    user_id: str | None
    twitter_id: str | None
    last_username_update: str | None
    t_ingest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "wallet": self.wallet,
            "username": self.username,
            "bio": self.bio,
            "native_followers": self.native_followers,
            "native_following": self.native_following,
            "combined_followers": self.combined_followers,
            "user_id": self.user_id,
            "twitter_id": self.twitter_id,
            "last_username_update": self.last_username_update,
            "t_ingest": self.t_ingest,
        }


def parse_profile(
    v3: dict[str, Any],
    *,
    t_ingest: str,
    cc_user: dict[str, Any] | None = None,
    cc_profile: dict[str, Any] | None = None,
) -> Profile:
    """Merge a frontend-api-v3 profile with the coin-communities view of the same wallet."""

    cc_user = cc_user or {}
    inner = (cc_profile or {}).get("user") if isinstance(cc_profile, dict) else None
    inner = inner if isinstance(inner, dict) else {}
    return Profile(
        wallet=_address(v3.get("address"), field="address"),
        username=v3.get("username") if isinstance(v3.get("username"), str) else None,
        bio=v3.get("bio") if isinstance(v3.get("bio"), str) else None,
        native_followers=_int(v3.get("followers")),
        native_following=_int(v3.get("following")),
        combined_followers=_int(inner.get("followerCount")),
        user_id=(
            cc_user.get("user_id")
            if isinstance(cc_user.get("user_id"), str)
            else (inner.get("id") if isinstance(inner.get("id"), str) else None)
        ),
        twitter_id=cc_user.get("twitter_id") if isinstance(cc_user.get("twitter_id"), str) else None,
        last_username_update=parse_ms(v3.get("last_username_update_timestamp")),
        t_ingest=t_ingest,
    )


@dataclass(frozen=True, slots=True)
class CalloutStats:
    """pump's own caller scoreboard for one wallet. A PEAK statistic — see `Callout`."""

    wallet: str
    total_callouts: int | None
    callouts_with_multiple: int | None
    two_x_percent: float | None
    one_point_five_x_percent: float | None
    one_point_two_x_percent: float | None
    average_multiple: float | None
    median_multiple: float | None
    average_time_to_peak_s: float | None
    t_ingest: str

    @property
    def rates_are_defined(self) -> bool:
        """False when the source reports rates over an empty denominator.

        The API answers a caller with NO callouts as `totalCallouts: 0` alongside
        `twoXPercent: 0.0` and `medianMultiple: 0.0` — i.e. it renders no-data as zero,
        the exact defect `design/glass.md` §0.3 forbids. A reader that trusts the
        percentage sees "0% hit 2x", which reads as a bad caller rather than an unrated
        one. Measured on mdudas (`FuP8dYQy..`), who has no callout record at all.
        """

        return bool(self.total_callouts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "wallet": self.wallet,
            "rates_are_defined": self.rates_are_defined,
            "total_callouts": self.total_callouts,
            "callouts_with_multiple": self.callouts_with_multiple,
            "two_x_percent": self.two_x_percent,
            "one_point_five_x_percent": self.one_point_five_x_percent,
            "one_point_two_x_percent": self.one_point_two_x_percent,
            "average_multiple": self.average_multiple,
            "median_multiple": self.median_multiple,
            "average_time_to_peak_s": self.average_time_to_peak_s,
            "t_ingest": self.t_ingest,
        }


def parse_callout_stats(row: dict[str, Any], *, wallet: str, t_ingest: str) -> CalloutStats:
    return CalloutStats(
        wallet=wallet,
        total_callouts=_int(row.get("totalCallouts")),
        callouts_with_multiple=_int(row.get("calloutsWithMultiple")),
        two_x_percent=_float(row.get("twoXPercent")),
        one_point_five_x_percent=_float(row.get("onePointFiveXPercent")),
        one_point_two_x_percent=_float(row.get("onePointTwoXPercent")),
        average_multiple=_float(row.get("averageMultiple")),
        median_multiple=_float(row.get("medianMultiple")),
        average_time_to_peak_s=_float(row.get("averageTimeToPeak")),
        t_ingest=t_ingest,
    )
