"""The portal's gate, its session, and its outage behaviour.

The tests that matter here are the refusals: a request with no session must not be able to
obtain a gated byte by any route, a stale roster must NOT lock a holder out, and a missing
roster must NOT let anyone in. Those three are the whole security and honesty argument, so
they are asserted structurally (walk every route) rather than route by route.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from solders.keypair import Keypair

from dregg_gate.gateway import format_tokens as gateway_format_tokens
from dregg_portal import FRESHNESS_MARKER, SCHEMA_MANIFEST, SCHEMA_ROSTER
from dregg_portal.app import Portal, client_address
from dregg_portal.challenge import CHALLENGE_TEMPLATE, build_challenge, valid_wallet
from dregg_portal.config import Config, PortalConfigError
from dregg_portal.roster import decide, format_tokens
from dregg_portal.roster import load as load_roster
from dregg_portal.roster import parse as parse_roster
from dregg_portal.session import (
    COOKIE_NAME,
    SessionKeyError,
    clear_cookie,
    from_cookie_header,
    generate_key,
    mint,
    read,
    read_key,
    set_cookie,
    write_key,
)
from dregg_portal.signerjs import NACL_SHA256, extract, wallet_crypto
from dregg_portal.store import Challenge, PortalStore

DECIMALS = 6
THRESHOLD = 888_888
NEED = THRESHOLD * 10**DECIMALS


class Clock:
    def __init__(self, t: float = 1_760_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def roster_dict(*, now: float, holders: dict[str, dict]) -> dict:
    return {
        "schema": SCHEMA_ROSTER,
        "generated_at": now,
        "generated_day": "2026-08-29",
        "mint": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
        "decimals": DECIMALS,
        "threshold_tokens": THRESHOLD,
        "source": "gate.sqlite members, desk box",
        "sweep": {"last_day": "2026-08-29", "status": "complete"},
        "holders": holders,
    }


def holder(balance: int, standing: str = "ok", **extra) -> dict:
    return {
        "balance_raw": balance,
        "threshold_tokens": THRESHOLD,
        "standing": standing,
        "checked_at": 1_760_000_000.0,
        "origin": "gate",
        "grace_until": None,
        **extra,
    }


@pytest.fixture
def portal(tmp_path: Path):
    """A portal with a full holder, a short holder, and one gated page on disk."""

    clock = Clock()
    artifacts = tmp_path / "artifacts"
    (artifacts / "gated").mkdir(parents=True)
    key_path = tmp_path / "keys" / "session.key"
    write_key(key_path, generate_key())
    config = Config(
        artifacts_dir=artifacts,
        state_db=tmp_path / "portal.sqlite",
        session_key_file=key_path,
        heartbeat_path=tmp_path / "heartbeat.json",
    )
    store = PortalStore(config.state_db)
    instance = Portal(config, store, read_key(key_path), clock=clock)
    instance.clock = clock
    (artifacts / "gated" / "screen.html").write_text(
        f"<!doctype html><title>screen</title>{FRESHNESS_MARKER}<p>the feed</p>"
    )
    (artifacts / "gated" / "index.html").write_text(
        f"<!doctype html><title>desk</title>{FRESHNESS_MARKER}<p>the desk</p>"
    )
    (artifacts / "manifest.json").write_text(
        json.dumps({"schema": SCHEMA_MANIFEST, "generated_at": clock.t, "day": "2026-08-29"})
    )
    yield instance, clock, artifacts
    store.close()


def write_roster(artifacts: Path, payload: dict) -> None:
    (artifacts / "roster.json").write_text(json.dumps(payload))


def session_for(portal_obj: Portal, wallet: str, clock: Clock, ttl: int = 3600) -> dict:
    token = mint(portal_obj.session_key, wallet, now=clock.t, ttl_seconds=ttl)
    return {"cookie": f"{COOKIE_NAME}={token}"}


# -- the challenge -------------------------------------------------------------------


def test_challenge_is_domain_separated_and_says_it_is_not_a_transaction():
    text = build_challenge("Wallet111", "abc123", 1_760_000_000.0)
    assert text.startswith("shitcoims wire portal sign-in")
    assert "not a transaction" in text
    # The bot's own template must not be reproduced here: a person reading a wallet
    # confirmation screen has to be able to tell the two surfaces apart.
    from dregg_gate.verify import CHALLENGE_TEMPLATE as GATE_TEMPLATE

    assert CHALLENGE_TEMPLATE.splitlines()[0] != GATE_TEMPLATE.splitlines()[0]


def test_valid_wallet_normalizes_and_refuses_junk():
    keypair = Keypair()
    address = str(keypair.pubkey())
    assert valid_wallet(f"  {address}  ") == address
    assert valid_wallet("not-a-wallet") is None
    assert valid_wallet(None) is None
    assert valid_wallet("1" * 200) is None


# -- sessions ------------------------------------------------------------------------


def test_session_round_trips_and_expires():
    key = generate_key()
    token = mint(key, "WalletAAA", now=1000.0, ttl_seconds=60)
    assert read(key, token, now=1000.0) == "WalletAAA"
    assert read(key, token, now=1059.0) == "WalletAAA"
    assert read(key, token, now=1060.0) is None


def test_session_refuses_a_tampered_payload_and_a_foreign_key():
    key, other = generate_key(), generate_key()
    token = mint(key, "WalletAAA", now=1000.0, ttl_seconds=60)
    version, _body, signature = token.split(".")
    forged = mint(key, "WalletBBB", now=1000.0, ttl_seconds=60).split(".")[1]
    assert read(key, f"{version}.{forged}.{signature}", now=1000.0) is None
    assert read(other, token, now=1000.0) is None
    assert read(key, "garbage", now=1000.0) is None
    assert read(key, None, now=1000.0) is None


def test_session_cookie_is_host_prefixed_secure_httponly():
    cookie = set_cookie("t0k3n", ttl_seconds=600)
    assert cookie.startswith("__Host-dregg_portal=")
    for attribute in ("Path=/", "Secure", "HttpOnly", "SameSite=Lax", "Max-Age=600"):
        assert attribute in cookie
    assert "Max-Age=0" in clear_cookie()
    assert from_cookie_header(f"other=1; {COOKIE_NAME}=abc; x=2") == "abc"
    assert from_cookie_header("other=1") is None


def test_session_key_file_must_not_be_group_readable(tmp_path: Path):
    path = tmp_path / "session.key"
    write_key(path, generate_key())
    path.chmod(0o640)
    with pytest.raises(SessionKeyError):
        read_key(path)


def test_keygen_refuses_to_replace_an_existing_key(tmp_path: Path):
    path = tmp_path / "session.key"
    write_key(path, generate_key())
    with pytest.raises(FileExistsError):
        write_key(path, generate_key())


# -- the roster ----------------------------------------------------------------------


def test_format_tokens_matches_the_bot_exactly():
    """The web must render a balance in the same characters the DM does."""

    for raw in (0, 1, 999, 888_888_000_000, 1_234_567_891_234, 10**18 + 7):
        assert format_tokens(raw, DECIMALS) == gateway_format_tokens(raw, DECIMALS)


def test_decide_reports_held_required_and_gap_like_the_bot():
    roster = parse_roster(roster_dict(now=1000.0, holders={"W": holder(NEED - 8_000_000, "grace")}))
    standing = decide(roster, "W")
    assert standing.entitled is True  # grace still reads
    assert standing.held_raw == NEED - 8_000_000
    assert standing.required_raw == NEED
    assert standing.gap_raw == 8_000_000


def test_an_unknown_wallet_is_an_absence_not_a_zero_balance():
    roster = parse_roster(roster_dict(now=1000.0, holders={}))
    standing = decide(roster, "Stranger")
    assert standing.known is False
    assert standing.entitled is False
    assert standing.origin == "absent"


def test_per_member_threshold_override_is_honored():
    roster = parse_roster(
        roster_dict(now=1000.0, holders={"W": holder(1 * 10**DECIMALS, "ok", threshold_tokens=1)})
    )
    standing = decide(roster, "W")
    assert standing.required_raw == 1 * 10**DECIMALS
    assert standing.entitled is True


def test_roster_freshness_bands():
    roster = parse_roster(roster_dict(now=1000.0, holders={}))
    assert roster.freshness(1000.0) == "fresh"
    assert roster.freshness(1000.0 + 7 * 3600) == "stale"
    assert roster.freshness(1000.0 + 100 * 3600) == "very-stale"


def test_a_corrupt_roster_raises_rather_than_parsing_into_an_empty_one(tmp_path: Path):
    from dregg_portal.roster import RosterError

    path = tmp_path / "roster.json"
    path.write_text("{not json")
    with pytest.raises(RosterError):
        load_roster(path)
    path.write_text(json.dumps({"schema": "something-else"}))
    with pytest.raises(RosterError):
        load_roster(path)


# -- nonces --------------------------------------------------------------------------


def test_a_nonce_can_only_be_consumed_once(tmp_path: Path):
    store = PortalStore(tmp_path / "s.sqlite")
    store.put_challenge(Challenge("n1", "W", "message", 100.0, 200.0))
    assert store.consume("n1", now=150.0) is not None
    assert store.consume("n1", now=150.0) is None
    store.close()


def test_an_expired_nonce_is_not_returned(tmp_path: Path):
    store = PortalStore(tmp_path / "s.sqlite")
    store.put_challenge(Challenge("n1", "W", "message", 100.0, 200.0))
    assert store.consume("n1", now=201.0) is None
    store.close()


def test_rate_buckets_close_and_reopen_on_the_next_window(tmp_path: Path):
    store = PortalStore(tmp_path / "s.sqlite")
    assert all(store.allow("scope", "ip", limit=3, now=1000.0) for _ in range(3))
    assert store.allow("scope", "ip", limit=3, now=1000.0) is False
    assert store.allow("scope", "ip", limit=3, now=1000.0 + 3600) is True
    store.close()


def test_client_address_takes_the_last_forwarded_hop():
    """A forged XFF prefix must not let a caller reset its own rate bucket."""

    assert client_address({"x-forwarded-for": "1.2.3.4, 9.9.9.9"}, "127.0.0.1") == "9.9.9.9"
    assert client_address({}, "127.0.0.1") == "127.0.0.1"


# -- the gate, end to end ------------------------------------------------------------

GATED_ROUTES = ["", "screen", "record", "coin/" + "1" * 40, "wallet/" + "1" * 40, "me"]


def test_no_gated_bytes_leave_without_a_session(portal):
    """Walk every gated route with no cookie. None of them may return artifact content."""

    instance, clock, artifacts = portal
    write_roster(artifacts, roster_dict(now=clock.t, holders={"W": holder(NEED)}))
    for route in GATED_ROUTES:
        response = instance.handle("GET", f"/portal/{route}", {}, b"", "1.1.1.1")
        assert b"the feed" not in response.body, route
        assert b"the desk" not in response.body, route
        if route == "":
            assert response.status == 200  # the front door is public copy, not an artifact
        else:
            assert response.status == 401, route


def test_a_session_for_a_holder_opens_the_gated_pages(portal):
    instance, clock, artifacts = portal
    write_roster(artifacts, roster_dict(now=clock.t, holders={"WalletFull": holder(NEED)}))
    headers = session_for(instance, "WalletFull", clock)
    response = instance.handle("GET", "/portal/screen", headers, b"", "1.1.1.1")
    assert response.status == 200
    assert b"the feed" in response.body


def test_a_short_balance_is_refused_with_held_required_and_gap(portal):
    instance, clock, artifacts = portal
    short = NEED - 100_000_000
    write_roster(artifacts, roster_dict(now=clock.t, holders={"WalletShort": holder(short, "ejected")}))
    headers = session_for(instance, "WalletShort", clock)
    response = instance.handle("GET", "/portal/screen", headers, b"", "1.1.1.1")
    assert response.status == 403
    page = response.body.decode()
    assert b"the feed" not in response.body
    assert format_tokens(short, DECIMALS) in page
    assert format_tokens(NEED, DECIMALS) in page
    assert format_tokens(NEED - short, DECIMALS) in page


def test_a_stale_roster_never_revokes_a_seat(portal):
    """The web mirror of 'a provider error never ejects anyone'."""

    instance, clock, artifacts = portal
    write_roster(artifacts, roster_dict(now=clock.t - 30 * 86_400, holders={"W": holder(NEED)}))
    headers = session_for(instance, "W", clock)
    response = instance.handle("GET", "/portal/screen", headers, b"", "1.1.1.1")
    assert response.status == 200
    assert b"the feed" in response.body
    assert b"VERY STALE" in response.body  # served, and loudly dated


def test_a_missing_roster_fails_closed_and_says_which_case_it_is(portal):
    instance, clock, _artifacts = portal
    headers = session_for(instance, "W", clock)
    response = instance.handle("GET", "/portal/screen", headers, b"", "1.1.1.1")
    assert response.status == 503
    assert b"the feed" not in response.body
    body = response.body.decode()
    assert "has not been told who holds" in body
    assert "merely OLD would still be served" in body


def test_a_page_without_a_freshness_marker_is_refused_not_served(portal):
    instance, clock, artifacts = portal
    write_roster(artifacts, roster_dict(now=clock.t, holders={"W": holder(NEED)}))
    (artifacts / "gated" / "screen.html").write_text("<p>UNSTAMPED-CANARY-77</p>")
    headers = session_for(instance, "W", clock)
    response = instance.handle("GET", "/portal/screen", headers, b"", "1.1.1.1")
    assert response.status == 500
    assert b"UNSTAMPED-CANARY-77" not in response.body


def test_the_freshness_banner_is_computed_at_read_time(portal):
    instance, clock, artifacts = portal
    write_roster(artifacts, roster_dict(now=clock.t, holders={"W": holder(NEED)}))
    headers = session_for(instance, "W", clock, ttl=86_400)
    fresh = instance.handle("GET", "/portal/screen", headers, b"", "1.1.1.1").body
    assert b"STALE" not in fresh
    clock.t += 10 * 3600  # the artifact did not change; only the clock did
    later = instance.handle("GET", "/portal/screen", headers, b"", "1.1.1.1").body
    assert b"STALE" in later


def test_path_traversal_cannot_reach_outside_the_gated_root(portal, tmp_path: Path):
    instance, clock, artifacts = portal
    write_roster(artifacts, roster_dict(now=clock.t, holders={"W": holder(NEED)}))
    (tmp_path / "secret.html").write_text("SECRET")
    headers = session_for(instance, "W", clock)
    for attempt in ("coin/../../secret", "wallet/..%2f..%2fsecret", "coin/../../../etc/passwd"):
        response = instance.handle("GET", f"/portal/{attempt}", headers, b"", "1.1.1.1")
        assert b"SECRET" not in response.body
        assert response.status == 404


def test_every_response_carries_no_store_and_varies_on_cookie(portal):
    instance, clock, artifacts = portal
    write_roster(artifacts, roster_dict(now=clock.t, holders={"W": holder(NEED)}))
    headers = session_for(instance, "W", clock)
    probes = [
        ("GET", "/portal/", {}, b""),
        ("GET", "/portal/signin", {}, b""),
        ("GET", "/portal/screen", headers, b""),
        ("GET", "/portal/me", headers, b""),
        ("GET", "/portal/health", {}, b""),
        ("POST", "/portal/api/nonce", {}, b"{}"),
    ]
    for method, path, hdrs, body in probes:
        response = instance.handle(method, path, hdrs, body, "1.1.1.1")
        fields = dict(response.headers())
        assert fields["Cache-Control"] == "private, no-store", path
        assert fields["Vary"] == "Cookie", path


# -- the sign-in api -----------------------------------------------------------------


def test_full_signin_flow_with_a_real_signature(portal):
    instance, clock, artifacts = portal
    keypair = Keypair()
    wallet = str(keypair.pubkey())
    write_roster(artifacts, roster_dict(now=clock.t, holders={wallet: holder(NEED)}))

    minted = instance.handle(
        "POST", "/portal/api/nonce", {}, json.dumps({"wallet": wallet}).encode(), "1.1.1.1"
    )
    assert minted.status == 200
    issued = json.loads(minted.body)
    signature = str(keypair.sign_message(issued["message"].encode()))

    established = instance.handle(
        "POST",
        "/portal/api/session",
        {},
        json.dumps({"wallet": wallet, "nonce": issued["nonce"], "signature": signature}).encode(),
        "1.1.1.1",
    )
    assert established.status == 200
    assert json.loads(established.body)["entitled"] is True
    cookie = dict(established.headers())["Set-Cookie"]

    token = cookie.split(";")[0].split("=", 1)[1]
    served = instance.handle("GET", "/portal/screen", {"cookie": f"{COOKIE_NAME}={token}"}, b"", "1.1.1.1")
    assert served.status == 200
    assert b"the feed" in served.body


def test_a_signature_from_the_wrong_key_is_refused(portal):
    instance, clock, artifacts = portal
    holder_key, impostor = Keypair(), Keypair()
    wallet = str(holder_key.pubkey())
    write_roster(artifacts, roster_dict(now=clock.t, holders={wallet: holder(NEED)}))
    issued = json.loads(
        instance.handle(
            "POST", "/portal/api/nonce", {}, json.dumps({"wallet": wallet}).encode(), "1.1.1.1"
        ).body
    )
    forged = str(impostor.sign_message(issued["message"].encode()))
    response = instance.handle(
        "POST",
        "/portal/api/session",
        {},
        json.dumps({"wallet": wallet, "nonce": issued["nonce"], "signature": forged}).encode(),
        "1.1.1.1",
    )
    assert response.status == 401
    assert "Set-Cookie" not in dict(response.headers())


def test_a_nonce_cannot_be_replayed(portal):
    instance, clock, artifacts = portal
    keypair = Keypair()
    wallet = str(keypair.pubkey())
    write_roster(artifacts, roster_dict(now=clock.t, holders={wallet: holder(NEED)}))
    issued = json.loads(
        instance.handle(
            "POST", "/portal/api/nonce", {}, json.dumps({"wallet": wallet}).encode(), "1.1.1.1"
        ).body
    )
    payload = json.dumps(
        {
            "wallet": wallet,
            "nonce": issued["nonce"],
            "signature": str(keypair.sign_message(issued["message"].encode())),
        }
    ).encode()
    assert instance.handle("POST", "/portal/api/session", {}, payload, "1.1.1.1").status == 200
    assert instance.handle("POST", "/portal/api/session", {}, payload, "1.1.1.1").status == 400


def test_signature_is_still_proven_when_the_roster_is_missing(portal):
    """An outage must not make a person re-run the ceremony once it is over."""

    instance, _clock, _artifacts = portal
    keypair = Keypair()
    wallet = str(keypair.pubkey())
    issued = json.loads(
        instance.handle(
            "POST", "/portal/api/nonce", {}, json.dumps({"wallet": wallet}).encode(), "1.1.1.1"
        ).body
    )
    response = instance.handle(
        "POST",
        "/portal/api/session",
        {},
        json.dumps(
            {
                "wallet": wallet,
                "nonce": issued["nonce"],
                "signature": str(keypair.sign_message(issued["message"].encode())),
            }
        ).encode(),
        "1.1.1.1",
    )
    body = json.loads(response.body)
    assert response.status == 200
    assert body["entitled"] is False
    assert "no holder roster" in body["reason"]
    assert "Set-Cookie" in dict(response.headers())


def test_nonce_minting_is_rate_limited_per_address(portal):
    instance, _clock, _artifacts = portal
    wallet = str(Keypair().pubkey())
    payload = json.dumps({"wallet": wallet}).encode()
    statuses = [
        instance.handle("POST", "/portal/api/nonce", {}, payload, "9.9.9.9").status for _ in range(10)
    ]
    assert 429 in statuses


# -- what must never be in the client ------------------------------------------------


def test_no_secret_material_reaches_any_rendered_page(portal):
    instance, clock, artifacts = portal
    write_roster(artifacts, roster_dict(now=clock.t, holders={"W": holder(NEED)}))
    headers = session_for(instance, "W", clock)
    key_hex = instance.session_key.hex()
    probes = (("/portal/", {}), ("/portal/signin", {}), ("/portal/me", headers), ("/portal/health", {}))
    for path, hdrs in probes:
        body = instance.handle("GET", path, hdrs, b"", "1.1.1.1").body
        assert key_hex.encode() not in body
        assert b"helius" not in body.lower()
        assert b"api-key" not in body.lower()
        assert b"tg_user_id" not in body


def test_health_reports_liveness_without_holder_data(portal):
    instance, clock, artifacts = portal
    write_roster(artifacts, roster_dict(now=clock.t, holders={"SecretWalletName": holder(NEED)}))
    response = instance.handle("GET", "/portal/health", {}, b"", "1.1.1.1")
    assert response.status == 200
    assert b"SecretWalletName" not in response.body
    assert json.loads(response.body)["roster"]["wallets"] == 1


def test_the_signin_page_never_asks_for_a_transaction(portal):
    instance, _clock, _artifacts = portal
    page = instance.handle("GET", "/portal/signin", {}, b"", "1.1.1.1").body.decode()
    assert "no transaction is requested" in page
    for forbidden in ("signTransaction", "signAndSendTransaction", "signAllTransactions"):
        assert forbidden not in page


# -- reuse of the signer's crypto ----------------------------------------------------


def test_the_signin_page_reuses_the_signer_pages_crypto_byte_for_byte():
    page = Path("dregg_gate/signer/index.html").read_text(encoding="utf-8")
    js = wallet_crypto()
    for block in ("nacl", "b58", "deeplink-crypto"):
        body = extract(block)
        assert body in page
        assert body in js
    assert NACL_SHA256 in js


def test_a_missing_marker_in_the_signer_page_fails_loudly(tmp_path: Path):
    from dregg_portal.signerjs import SignerExtractError

    broken = tmp_path / "index.html"
    broken.write_text("<html>no markers here</html>")
    with pytest.raises(SignerExtractError):
        wallet_crypto(page=broken)


# -- config refusals -----------------------------------------------------------------


def test_config_refuses_a_public_bind(tmp_path: Path):
    path = tmp_path / "portal.toml"
    path.write_text('[service]\nbind_host = "0.0.0.0"\n')
    with pytest.raises(PortalConfigError):
        Config.load(path)


def test_config_refuses_an_unknown_key_so_a_provider_key_cannot_be_slipped_in(tmp_path: Path):
    path = tmp_path / "portal.toml"
    path.write_text('[service]\nhelius_key = "abc"\n')
    with pytest.raises(PortalConfigError):
        Config.load(path)


def test_the_config_schema_carries_no_provider_or_bot_credential():
    fields = set(Config.__dataclass_fields__)
    for forbidden in ("helius", "telegram", "token", "api_key", "secret", "mint", "threshold"):
        assert not any(forbidden in name for name in fields), forbidden


def test_gate_database_is_only_ever_opened_read_only():
    """The publisher must not be able to write to, or lock, the bot's live state."""

    source = Path("dregg_portal/publish.py").read_text(encoding="utf-8")
    assert "mode=ro" in source
    # Not the flock-taking class, and not a single write: both checked against CODE, with
    # the prose stripped, so an explanatory comment cannot fail (or pass) this test.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    ).split('"""')
    code = "".join(code[::2])
    assert "GateState" not in code
    for statement in ("INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE"):
        assert statement not in code, statement


def test_the_deploy_set_imports_nothing_the_public_box_should_not_hold():
    """dregg_portal's SERVICE half must not drag the bot's transport onto the anchor."""

    import ast

    allowed_first_party = {"dregg_gate", "dregg_site", "dregg_portal"}
    forbidden_leaf = {"dregg_gate.gateway", "dregg_gate.telegram", "dregg_gate.helius", "dregg_gate.state"}
    service_modules = [
        "app", "config", "challenge", "render", "roster",
        "session", "signerjs", "store", "service",
    ]
    for name in service_modules:
        tree = ast.parse(Path(f"dregg_portal/{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                root = node.module.split(".")[0]
                if root.startswith("dregg"):
                    assert root in allowed_first_party, f"{name}: {node.module}"
                    assert node.module not in forbidden_leaf, f"{name}: {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root.startswith("dregg"):
                        assert root in allowed_first_party, f"{name}: {alias.name}"


def test_sqlite_is_the_only_database_the_service_opens(tmp_path: Path):
    store = PortalStore(tmp_path / "s.sqlite")
    tables = {
        row[0]
        for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    # Nonces and rate buckets. Nothing durable, nothing anyone would miss.
    assert tables == {"challenges", "buckets"}
    store.close()


def test_state_file_is_created_private(tmp_path: Path):
    path = tmp_path / "s.sqlite"
    store = PortalStore(path)
    assert oct(path.stat().st_mode)[-3:] == "600"
    store.close()


def test_store_refuses_a_symlinked_state_path(tmp_path: Path):
    from dregg_portal.store import StoreError

    real = tmp_path / "real.sqlite"
    sqlite3.connect(real).close()
    link = tmp_path / "link.sqlite"
    link.symlink_to(real)
    with pytest.raises(StoreError):
        PortalStore(link)


def test_clock_is_injectable_so_nothing_here_reads_the_wall_clock_by_surprise(portal):
    instance, clock, _artifacts = portal
    assert instance.clock() == clock.t
    assert instance.clock() != time.time()


def test_the_signin_script_refuses_to_render_with_a_placeholder_left_in(tmp_path: Path, monkeypatch):
    """A page whose wallet buttons point at ``__PORTAL_BASE__`` fails in the browser only."""

    from dregg_portal import render

    broken = tmp_path / "signin.js"
    # Single-quoted: the substitution targets the double-quoted form, so this is exactly
    # the near-miss that would otherwise ship a page whose buttons point at a literal.
    broken.write_text("var BASE = '__PORTAL_BASE__';")
    monkeypatch.setattr(render, "SIGNIN_JS", broken)
    with pytest.raises(render.SignInPageError, match="__PORTAL_BASE__"):
        render.signin_script(page_url="https://x/portal/signin", app_url="https://x", base="/portal")


def test_the_signin_script_uses_the_extracted_crypto_and_defines_none_of_it():
    """One copy of the wallet crypto in the tree: the script CALLS it, never redefines it."""

    script = Path("dregg_portal/signin.js").read_text(encoding="utf-8")
    for symbol in ("b58encode", "b58decode", "dlSharedSecret", "dlEncryptPayload", "dlDecryptPayload"):
        assert symbol in script, symbol
        assert f"function {symbol}(" not in script, symbol
    assert "nacl.box.keyPair()" in script


def test_the_signin_page_posts_only_to_its_own_origin():
    script = Path("dregg_portal/signin.js").read_text(encoding="utf-8")
    assert 'fetch(BASE + path' in script
    assert "http://" not in script
    # The only absolute URLs are the two wallet universal-link bases the user is sent TO.
    absolute = {line.strip() for line in script.splitlines() if "https://" in line}
    assert absolute == {
        'var PHANTOM_UL  = "https://phantom.app/ul/v1/";',
        'var SOLFLARE_UL = "https://solflare.com/ul/v1/";',
    }


def test_the_deploy_set_actually_imports_on_its_own(tmp_path: Path):
    """Copy exactly what deploy-portal.sh ships, and import it with nothing else on the path.

    The AST check above proves no forbidden module is NAMED. This proves the shipped set is
    COMPLETE — the failure it catches is a service that starts fine here and dies on its
    first import on the anchor, after the Caddyfile has already been reloaded to point at it.
    Kept in step with edge/portal/deploy-portal.sh's DEPLOY_SET by name.
    """

    import shutil
    import subprocess

    deploy_set = [
        "dregg_portal/__init__.py",
        "dregg_portal/__main__.py",
        "dregg_portal/app.py",
        "dregg_portal/challenge.py",
        "dregg_portal/config.py",
        "dregg_portal/render.py",
        "dregg_portal/roster.py",
        "dregg_portal/service.py",
        "dregg_portal/session.py",
        "dregg_portal/signerjs.py",
        "dregg_portal/signin.js",
        "dregg_portal/store.py",
        "dregg_gate/__init__.py",
        "dregg_gate/verify.py",
        "dregg_gate/signer/index.html",
        "dregg_site/__init__.py",
        "dregg_site/chrome.py",
    ]
    for item in deploy_set:
        target = tmp_path / item
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(item), target)

    probe = (
        "import dregg_portal.app, dregg_portal.service;"
        "from dregg_portal.signerjs import wallet_crypto;"
        "from dregg_portal.render import page_front, page_signin;"
        "page_signin(base='/portal', wallet_js=wallet_crypto(),"
        " page_url='https://x/portal/signin', app_url='https://x');"
        "print('ok')"
    )
    result = subprocess.run(
        [__import__("sys").executable, "-c", probe],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_the_rendered_signin_page_is_parseable_javascript():
    """A page whose script has a syntax error renders perfectly and does nothing.

    That failure lives in the browser, where no server log would show it — the exact shape
    of the wasm-bundle regression dregg-infra's Caddyfile records. Skipped, loudly, where
    node is unavailable rather than quietly asserted away.
    """

    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the sign-in script's syntax is unchecked here")
    from dregg_portal.render import page_signin
    from dregg_portal.signerjs import wallet_crypto

    html = page_signin(
        base="/portal",
        wallet_js=wallet_crypto(),
        page_url="https://shitcoims.dregg.studio/portal/signin",
        app_url="https://shitcoims.dregg.studio",
    )
    blocks = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert len(blocks) == 2, "the sign-in page should carry the crypto block and the flow block"
    for index, block in enumerate(blocks):
        result = subprocess.run([node, "--check", "-"], input=block, capture_output=True, text=True)
        assert result.returncode == 0, f"script block {index} does not parse: {result.stderr}"


def test_the_example_config_loads_and_carries_no_credential(tmp_path: Path):
    example = Path("dregg_portal/config.example.toml")
    config = Config.load(example)
    assert config.bind_host == "127.0.0.1"
    assert config.base_path == "/portal"
    text = example.read_text(encoding="utf-8").lower()
    for forbidden in ("helius", "api-key", "api_key", "token", "secret ="):
        assert f"\n{forbidden}" not in text, forbidden
