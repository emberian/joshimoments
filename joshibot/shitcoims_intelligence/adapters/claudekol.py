"""Quarantined reader for the public ClaudeKOL action feed.

Provenance: the public SPA at https://claudekol.fun/ embeds a Supabase anon
client and renders selected rows from its ``actions`` table. This adapter has
GET-only access, treats every title/body/symbol as a claim, and can corroborate
signed trade claims only through an independently supplied chain verifier.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from solders.pubkey import Pubkey
from solders.signature import Signature

from ..helius import WalletTransaction
from .common import (
    AdvisoryAdapterError,
    QuarantinedRecord,
    SourceProvenance,
    bounded_text,
    ensure_bounded_response,
    response_json,
    safe_transport_error,
)

SOURCE_ID = "claudekol_public_actions"
SPA_ORIGIN = "https://claudekol.fun"
SPA_URL = f"{SPA_ORIGIN}/"
SUPABASE_ORIGIN = "https://fbwzsmpytdjgbjpwkafy.supabase.co"
ACTIONS_URL = f"{SUPABASE_ORIGIN}/rest/v1/actions"
CANONICAL_WALLET = "6s5RoARKg1oc4eWvGof1FwTzPuPLkToP4iS1N4Mgqvz"
ADAPTER_VERSION = "claudekol-public-actions-v1"
MAX_ACTIONS = 50
MAX_JSON_BYTES = 256 * 1024
MAX_SPA_BYTES = 64 * 1024
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
_ASSET = re.compile(r'src="(/assets/index-[A-Za-z0-9_-]{1,80}\.js)"')
_ANON_KEY = re.compile(
    rb'"https://fbwzsmpytdjgbjpwkafy\.supabase\.co",[A-Za-z_$][\w$]*="(eyJ[A-Za-z0-9_.-]{80,2048})"'
)
_LABEL = re.compile(r"\$([A-Za-z0-9][A-Za-z0-9._-]{0,31})")


@dataclass(frozen=True, slots=True)
class ClaudeKolChainVerification:
    """Canonical facts produced by an independent Helius/chain adapter."""

    wallet: str
    signature: str
    landed: bool
    succeeded: bool
    mint: str | None
    token_delta_raw: int | None
    slot: int | None
    source_id: str = "helius"


VerificationHook = Callable[
    [str, str, str], Awaitable[ClaudeKolChainVerification]
]
HeliusTransactionLookup = Callable[[str, str], Awaitable[WalletTransaction | None]]


def helius_verification_hook(lookup: HeliusTransactionLookup) -> VerificationHook:
    """Adapt an independent Helius transaction lookup to claim reconciliation.

    The lookup is deliberately supplied by the intelligence runtime/store; the
    ClaudeKOL source never gets a Helius credential and cannot mark itself as
    verified. Missing transactions remain explicit unlanded observations.
    """

    async def verify(wallet: str, mint: str, signature: str) -> ClaudeKolChainVerification:
        transaction = await lookup(wallet, signature)
        if transaction is None:
            return ClaudeKolChainVerification(
                wallet=wallet,
                signature=signature,
                landed=False,
                succeeded=False,
                mint=None,
                token_delta_raw=None,
                slot=None,
            )
        delta = sum(
            item.raw_delta for item in transaction.token_deltas if item.mint == mint
        )
        has_mint = any(item.mint == mint for item in transaction.token_deltas)
        return ClaudeKolChainVerification(
            wallet=transaction.wallet,
            signature=transaction.signature,
            landed=True,
            succeeded=transaction.succeeded,
            mint=mint if has_mint else None,
            token_delta_raw=delta if has_mint else None,
            slot=transaction.slot,
        )

    return verify


@dataclass(frozen=True, slots=True)
class ClaudeKolAction:
    source_event_id: str
    source_created_at: datetime
    kind: str
    title_claim: str
    body_claim: str
    symbol_claim: str | None
    mint_claim: str | None
    canonical_mint: str | None
    signature_claim: str | None
    canonical_signature: str | None
    nominal_sol_claim: float | None
    nominal_usd_claim: float | None
    allocation_pct_claim: float | None
    multiple_claim: float | None
    callout_url_claim: str | None
    verification: ClaudeKolChainVerification | None
    independently_verified: bool
    conflicts: tuple[str, ...]
    provenance: SourceProvenance
    policy_effect: str = "observe"
    can_execute: bool = False


@dataclass(frozen=True, slots=True)
class ClaudeKolBatch:
    actions: tuple[ClaudeKolAction, ...]
    quarantined: tuple[QuarantinedRecord, ...]
    provenance: SourceProvenance


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(repr(value).encode("utf-8", errors="replace")[:16_384]).hexdigest()[:24]


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("timestamp_missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp_missing_timezone")
    return parsed.astimezone(UTC)


def _number(meta: dict[str, Any], key: str) -> float | None:
    value = meta.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if abs(number) <= 1_000_000_000_000 else None


def _mint(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 44:
        raise ValueError("invalid_mint_claim")
    try:
        return str(Pubkey.from_string(value))
    except Exception as exc:
        raise ValueError("invalid_mint_claim") from exc


def _signature(value: Any) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, str) or len(value) > 100:
        return None, "invalid_signature_claim"
    try:
        return str(Signature.from_string(value)), None
    except Exception:
        return None, "invalid_signature_claim"


def _safe_callout_url(value: Any, mint: str | None) -> str | None:
    if value is None:
        return None
    text = bounded_text(value, limit=512)
    if text is None or mint is None:
        return None
    expected = f"https://pump.fun/coin/{mint}"
    return expected if text.rstrip("/") == expected else None


class ClaudeKolAdapter:
    """Read the public feed. It has no signer, keypair, or execution capability."""

    def __init__(self, http: httpx.AsyncClient, *, public_anon_key: str | None = None) -> None:
        self._http = http
        self._public_anon_key = self._validate_anon_key(public_anon_key) if public_anon_key else None

    @staticmethod
    def _validate_anon_key(value: str) -> str:
        if not re.fullmatch(r"eyJ[A-Za-z0-9_.-]{80,2048}", value):
            raise AdvisoryAdapterError("ClaudeKOL public anon credential format changed")
        return value

    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._http.get(
                url,
                follow_redirects=False,
                timeout=httpx.Timeout(10, connect=4),
                **kwargs,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise safe_transport_error("ClaudeKOL public feed", exc) from exc

    async def _discover_public_anon_key(self) -> str:
        homepage = await self._get(SPA_URL, headers={"accept": "text/html"})
        html = ensure_bounded_response(homepage, limit=MAX_SPA_BYTES, source="ClaudeKOL SPA")
        try:
            match = _ASSET.search(html.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise AdvisoryAdapterError("ClaudeKOL SPA was not valid UTF-8") from exc
        if match is None:
            raise AdvisoryAdapterError("ClaudeKOL SPA bundle reference changed")
        bundle_url = f"{SPA_ORIGIN}{match.group(1)}"
        bundle_response = await self._get(bundle_url, headers={"accept": "text/javascript"})
        bundle = ensure_bounded_response(
            bundle_response, limit=MAX_BUNDLE_BYTES, source="ClaudeKOL SPA bundle"
        )
        key_match = _ANON_KEY.search(bundle)
        if key_match is None:
            raise AdvisoryAdapterError("ClaudeKOL public Supabase configuration changed")
        return self._validate_anon_key(key_match.group(1).decode("ascii"))

    async def _credential(self) -> str:
        if self._public_anon_key is None:
            self._public_anon_key = await self._discover_public_anon_key()
        return self._public_anon_key

    async def actions(
        self,
        *,
        limit: int = 50,
        verifier: VerificationHook | None = None,
    ) -> ClaudeKolBatch:
        if not 1 <= limit <= MAX_ACTIONS:
            raise ValueError(f"limit must be between 1 and {MAX_ACTIONS}")
        provenance = SourceProvenance(
            source_id=SOURCE_ID,
            source_url=SPA_URL,
            endpoint_family="public SPA Supabase actions select",
            adapter_version=ADAPTER_VERSION,
            contract_status="reverse_engineered_public_client_unstable",
        )
        public_key = await self._credential()
        params = {
            "select": "id,kind,title,body,created_at,mint,meta",
            "kind": "neq.speech",
            "order": "created_at.desc",
            "limit": str(limit),
        }
        response = await self._get(
            ACTIONS_URL,
            params=params,
            headers={
                "accept": "application/json",
                "apikey": public_key,
                "authorization": f"Bearer {public_key}",
            },
        )
        body = response_json(
            response, limit=MAX_JSON_BYTES, source="ClaudeKOL public action feed"
        )
        if not isinstance(body, list) or len(body) > limit:
            raise AdvisoryAdapterError("ClaudeKOL public action feed schema changed")

        parsed: list[ClaudeKolAction] = []
        quarantined: list[QuarantinedRecord] = []
        for row in body:
            try:
                action = await self._parse_row(row, provenance=provenance, verifier=verifier)
            except (KeyError, TypeError, ValueError) as exc:
                source_event_id = None
                if isinstance(row, dict):
                    source_event_id = bounded_text(row.get("id"), limit=64)
                quarantined.append(
                    QuarantinedRecord(
                        source_id=SOURCE_ID,
                        source_event_id=source_event_id,
                        reason=f"schema_or_identity_drift:{str(exc)[:80]}",
                        fingerprint=_fingerprint(row),
                    )
                )
                continue
            parsed.append(action)

        labels_by_mint: dict[str, set[str]] = defaultdict(set)
        for action in parsed:
            if action.canonical_mint and action.symbol_claim:
                labels_by_mint[action.canonical_mint].add(action.symbol_claim)
        resolved: list[ClaudeKolAction] = []
        for action in parsed:
            labels = labels_by_mint.get(action.canonical_mint or "", set())
            if len(labels) > 1:
                claims = ",".join(f"${label}" for label in sorted(labels, key=str.casefold))[:300]
                action = dataclasses.replace(
                    action,
                    conflicts=(*action.conflicts, f"label_claim_conflict:{claims}"),
                )
            resolved.append(action)
        return ClaudeKolBatch(tuple(resolved), tuple(quarantined), provenance)

    async def _parse_row(
        self,
        row: Any,
        *,
        provenance: SourceProvenance,
        verifier: VerificationHook | None,
    ) -> ClaudeKolAction:
        if not isinstance(row, dict) or len(row) > 12:
            raise ValueError("row_not_bounded_mapping")
        required_strings = ("id", "kind", "title", "body", "created_at")
        if any(not isinstance(row.get(field), str) for field in required_strings):
            raise ValueError("required_claim_type_changed")
        source_event_id = str(uuid.UUID(str(row["id"])))
        kind = bounded_text(row["kind"], limit=40)
        title = bounded_text(row["title"], limit=240)
        body = bounded_text(row["body"], limit=2_000, allow_empty=True)
        if kind is None or title is None or body is None:
            raise ValueError("required_claim_missing")
        created_at = _timestamp(row["created_at"])
        canonical_mint = _mint(row.get("mint"))
        meta = row.get("meta") or {}
        if not isinstance(meta, dict) or len(meta) > 24:
            raise ValueError("meta_schema_drift")
        signature, signature_conflict = _signature(meta.get("sig"))
        conflicts: list[str] = []
        if signature_conflict:
            conflicts.append(signature_conflict)
        if kind in {"trade_open", "trade_close"} and canonical_mint is None:
            conflicts.append("mint_claim_missing")
        symbol_match = _LABEL.search(title)
        symbol_claim = bounded_text(symbol_match.group(1), limit=32) if symbol_match else None
        verification: ClaudeKolChainVerification | None = None
        independently_verified = False
        if verifier is not None and canonical_mint is not None and signature is not None:
            try:
                verification = await verifier(CANONICAL_WALLET, canonical_mint, signature)
            except Exception as exc:
                conflicts.append(f"independent_verification_failed:{type(exc).__name__}")
            else:
                matches = True
                if verification.wallet != CANONICAL_WALLET:
                    conflicts.append("verified_wallet_conflict")
                    matches = False
                if verification.signature != signature:
                    conflicts.append("verified_signature_conflict")
                    matches = False
                if verification.mint != canonical_mint:
                    conflicts.append("verified_mint_conflict")
                    matches = False
                delta = verification.token_delta_raw
                direction_matches = (
                    delta is not None
                    and ((kind == "trade_open" and delta > 0) or (kind == "trade_close" and delta < 0))
                )
                if kind in {"trade_open", "trade_close"} and not direction_matches:
                    conflicts.append("verified_trade_direction_conflict")
                    matches = False
                independently_verified = (
                    matches and verification.landed and verification.succeeded and delta is not None
                )
        return ClaudeKolAction(
            source_event_id=source_event_id,
            source_created_at=created_at,
            kind=kind,
            title_claim=title,
            body_claim=body,
            symbol_claim=symbol_claim,
            mint_claim=bounded_text(row.get("mint"), limit=44),
            canonical_mint=canonical_mint,
            signature_claim=bounded_text(meta.get("sig"), limit=100),
            canonical_signature=signature,
            nominal_sol_claim=_number(meta, "sol"),
            nominal_usd_claim=_number(meta, "usd"),
            allocation_pct_claim=_number(meta, "pct"),
            multiple_claim=_number(meta, "multiple"),
            callout_url_claim=_safe_callout_url(meta.get("url"), canonical_mint),
            verification=verification,
            independently_verified=independently_verified,
            conflicts=tuple(conflicts),
            provenance=provenance,
        )
