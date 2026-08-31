"""Birth-slot feature extraction, replicated exactly from ``studies/operator_crime.py``.

THE PARITY OBLIGATION
---------------------
The screen B1 validated is a conjunction of five birth-time gates whose inputs are
defined by SQL in ``studies/operator_crime.py``. This module re-derives those inputs
from Helius ``getTransaction`` responses instead of the bulk parquet corpus, and the
whole point of the file is that the two derivations are THE SAME FUNCTION on the same
chain facts. Each definition below cites the SQL it mirrors; the parity test in
``tests/test_dregg_screen.py`` runs this extractor over real corpus birth slots
(reconstructed into Helius wire shape) and asserts equality against the study's own
``panel.parquet`` row. A drifted feature here does not crash — it silently detaches the
live verdicts from the validated precision numbers, which is the one failure this lane
is not allowed to have.

The corpus identities being mirrored:

* a LEDGER row is a per-(transaction, token-account) net balance change:
  ``delta = sum(post.amount) - sum(pre.amount)`` matched by ``account_index``, with a
  ``pre`` leg that has no ``post`` (closed account) appended negated, zero deltas
  dropped (``LEDGER_SQL``). Helius ``meta.pre/postTokenBalances`` carry exactly those
  legs, with ``amount`` as a STRING of raw units — parsed as int, never float, because
  the corpus docstring forbids exactly that float.
* BIRTH: the create transaction's legs, ranked by delta descending. Rank 1 is the
  curve seed and its owner is ``curve_owner``; rank 2, if positive, is the dev buy and
  its owner is ``deployer`` (``BIRTH_SQL``). Membership (``BORN``) is
  ``minted_raw == 1e15 AND decimals == 6`` — net supply minted from nothing, invariant
  to the dev buy. Anything else (mayhem mode, 9-decimal impostors wearing the ``pump``
  suffix) is OUT of the validated population and says so.
* SNIPERS: every owner with a net POSITIVE delta summed across the whole birth slot,
  other than the curve owner (``SNIPERS_SQL``). The deployer IS a sniper when it dev
  buys — the corpus counts it, so we count it. Failed transactions are excluded: every
  row of the corpus was a success (``err = ''`` on all 106,639,238 rows), so a reverted
  same-slot buy must not become a phantom sniper here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

# -- constants lifted verbatim from studies/operator_crime.py --------------------------

PUMP_SUPPLY_RAW = 1_000_000_000_000_000  # 1e9 tokens at 6 decimals
PUMP_DECIMALS = 6

# -- curve-seed constants (studies/third_stratum.py, chain-verified 2026-08-29) --------
#
# Pump runs a QUOTE-MINT variant of the standard curve: CreateEvent.quote_mint = USDC,
# virtual_quote_reserves = 4_292_000_000 raw USDC ($4,292 = 30 SOL x $143.07 -- the
# dollar-denominated clone of the standard seed), with that same integer mirrored into
# virtual_sol_reserves. Supply is exactly 1e15 at 6 decimals, so the BORN predicate
# cannot see it; the witnesses are the CreateEvent reserves (authoritative, decoded from
# the create's own logs) and the curve's USDC vault leg in the create transaction
# (corpus-side equivalent; 20/20 chain-concordant, RESULT_third_stratum.md T1).
# Measured birth share: 0.96% (2026-08-05..14) -> 1.39% (2026-08-26..28).

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SEED_STANDARD_LAMPORTS = 30_000_000_000
SEED_QUOTE_USDC_RAW = 4_292_000_000

# The five gates of the validated CLEAN screen (cmd_screen), with the study's names.
GATE_MAX_SNIPERS = 1  # "no bundle at birth (n_snipers <= 1)"
GATE_MAX_DEV_BUY_SHARE = 0.02  # "dev buy under 2% of supply"
# prior_rips == 0, prior_dumps == 0, sniper_prior_max == 0 complete the conjunction.


@dataclass(frozen=True, slots=True)
class Leg:
    """One netted token-account leg, the unit LEDGER_SQL calls a balance change."""

    owner: str
    delta_raw: int
    decimals: int


def tx_success(tx: Mapping[str, Any]) -> bool:
    """Corpus membership check: every corpus row was a success (``err = ''``)."""

    meta = tx.get("meta") or {}
    return meta.get("err") is None


def mint_legs(tx: Mapping[str, Any], mint: str) -> list[Leg]:
    """Net per-token-account deltas for ``mint`` in one transaction.

    Mirrors LEDGER_SQL's inside-the-row netting: subtract the matching ``pre`` from
    every ``post`` by ``accountIndex``, append pre-only legs negated, drop zeros.
    Amounts are Helius strings of raw units; ``int()`` keeps them exact. A leg whose
    balance entry carries no ``owner`` cannot be attributed and is dropped — the corpus
    tape always carried owners, so on parity data this branch never fires.
    """

    meta = tx.get("meta") or {}
    pre = {
        b["accountIndex"]: b
        for b in meta.get("preTokenBalances") or []
        if b.get("mint") == mint
    }
    post = {
        b["accountIndex"]: b
        for b in meta.get("postTokenBalances") or []
        if b.get("mint") == mint
    }
    legs: list[Leg] = []
    for idx, b in post.items():
        owner = b.get("owner")
        if not owner:
            continue
        amount = int(b["uiTokenAmount"]["amount"])
        before = int(pre[idx]["uiTokenAmount"]["amount"]) if idx in pre else 0
        delta = amount - before
        if delta != 0:
            legs.append(Leg(owner=owner, delta_raw=delta, decimals=int(b["uiTokenAmount"]["decimals"])))
    for idx, b in pre.items():
        if idx in post:
            continue
        owner = b.get("owner")
        if not owner:
            continue
        amount = int(b["uiTokenAmount"]["amount"])
        if amount != 0:
            legs.append(Leg(owner=owner, delta_raw=-amount, decimals=int(b["uiTokenAmount"]["decimals"])))
    return legs


@dataclass(frozen=True, slots=True)
class BirthFeatures:
    """Everything the screen reads from the birth slot, in the study's vocabulary."""

    mint: str
    born_standard: bool  # BORN: minted_raw == 1e15 AND decimals == 6
    minted_raw: int
    decimals: int | None
    curve_owner: str | None  # BIRTH_SQL rank-1 leg owner (the bonding curve account)
    deployer: str | None  # BIRTH_SQL rank-2 positive leg owner; None when no dev buy
    dev_buy_raw: int  # coalesce(rank-2 delta, 0)
    n_birth_legs: int
    n_snipers: int  # SNIPERS_SQL: net-positive owners in the birth slot, ex curve
    snipers: tuple[str, ...]  # the sniper set itself (deployer INCLUDED, as the corpus does)
    partial: bool = False  # true when the same-slot tx list was capped — n_snipers is a floor
    notes: tuple[str, ...] = field(default=())
    # Curve-seed identification (third stratum). quote_curve means the bonding curve is
    # priced in a quote token (USDC), NOT SOL — outside the population every validated
    # precision number was measured on, while staying token-side identical to it.
    quote_curve: bool = False
    curve_quote_mint: str | None = None  # the quote token's mint when quote_curve
    curve_seed_source: str = "birth_legs"  # "create_event" (authoritative) | "birth_legs"
    curve_seed_vsol: int | None = None  # CreateEvent.virtual_sol_reserves when decoded

    @property
    def dev_buy_share(self) -> float:
        return self.dev_buy_raw / PUMP_SUPPLY_RAW

    @property
    def snipers_ex_deployer(self) -> tuple[str, ...]:
        """The crew-match set. cmd_graph drops the deployer from its own coins' sniper
        sets because the dev buy puts it there BY CONSTRUCTION — same-deployer overlap
        would be positive on an empty hypothesis. Crew matching inherits that rule."""

        return tuple(s for s in self.snipers if s != self.deployer)


def detect_curve_seed(
    mint: str,
    create_tx: Mapping[str, Any],
    curve_owner: str | None,
) -> tuple[bool, str | None, str, int | None]:
    """Identify the curve's seed denomination from the create transaction alone.

    Returns ``(quote_curve, quote_mint, source, seed_vsol)``.

    Two witnesses, strongest first (both validated in studies/third_stratum.py —
    RESULT_third_stratum.md T1: 20/20 chain concordance, 100% corpus coverage):

    1. The pump ``CreateEvent`` decoded from the create's OWN ``logMessages`` with
       invoke-stack attribution — a ``Program data:`` line is only trusted when the
       runtime's invoke/success bracketing says pump was executing (any program can
       emit any eight discriminator bytes). Carries ``quote_mint`` and the exact seed.
    2. The curve's quote-token vault leg: a quote-curve create initializes a USDC
       token account OWNED BY THE CURVE in the same transaction. This is the corpus
       predicate, and it needs only the token balances already fetched.

    When logs are absent (some RPC shapes, and every parity-test row reconstructed
    from the corpus) witness 2 decides; a create with neither witness is standard —
    the same default the validated corpus population was built on.
    """

    logs = (create_tx.get("meta") or {}).get("logMessages")
    if logs:
        try:
            from shitcoims_intelligence.pump import AdvisoryPumpEvent, decode_pump_event
            from shitcoims_intelligence.pump_layouts import PUMP_PROGRAM_ID
            from shitcoims_tape.recorder import attribute_program_data

            for entry in attribute_program_data(list(logs)).entries:
                if entry.program_id != PUMP_PROGRAM_ID:
                    continue
                got = decode_pump_event(program_id=PUMP_PROGRAM_ID, data=entry.payload)
                if (
                    isinstance(got, AdvisoryPumpEvent)
                    and got.event_name == "CreateEvent"
                    and str(got.fields["mint"]) == mint
                ):
                    quote = str(got.fields["quote_mint"])
                    vsol = int(got.fields["virtual_sol_reserves"])  # type: ignore[arg-type]
                    is_quote = vsol != SEED_STANDARD_LAMPORTS
                    return (is_quote, quote if is_quote else None, "create_event", vsol)
        except Exception:  # decode is advisory; the leg witness still decides
            pass

    if curve_owner:
        meta = create_tx.get("meta") or {}
        for b in meta.get("postTokenBalances") or []:
            if b.get("mint") == USDC_MINT and b.get("owner") == curve_owner:
                return (True, USDC_MINT, "birth_legs", None)
    return (False, None, "birth_legs", None)


def extract_birth_features(
    mint: str,
    create_tx: Mapping[str, Any],
    same_slot_txs: Sequence[Mapping[str, Any]] = (),
    *,
    partial: bool = False,
) -> BirthFeatures:
    """The feature builder. ``create_tx`` is the create transaction (known from the
    PumpPortal event's signature — which is also why no first-key scan is needed: the
    mint cannot be touched before it exists, so the create IS the first transaction).
    ``same_slot_txs`` are the OTHER successful transactions of the birth slot that
    touch the mint; pass what hydration found, with ``partial=True`` if it was capped.
    """

    notes: list[str] = []
    birth = sorted(mint_legs(create_tx, mint), key=lambda leg: -leg.delta_raw)
    minted_raw = sum(leg.delta_raw for leg in birth)
    decimals = birth[0].decimals if birth else None
    born = minted_raw == PUMP_SUPPLY_RAW and decimals == PUMP_DECIMALS
    curve_owner = birth[0].owner if birth else None
    deployer: str | None = None
    dev_buy_raw = 0
    if len(birth) >= 2 and birth[1].delta_raw > 0:
        deployer = birth[1].owner
        dev_buy_raw = birth[1].delta_raw

    # SNIPERS_SQL: sum per owner over the WHOLE slot (create included), ex curve owner.
    by_owner: dict[str, int] = {}
    for tx in (create_tx, *same_slot_txs):
        if not tx_success(tx):
            notes.append("skipped_failed_tx")
            continue
        for leg in mint_legs(tx, mint):
            by_owner[leg.owner] = by_owner.get(leg.owner, 0) + leg.delta_raw
    snipers = tuple(sorted(o for o, d in by_owner.items() if d > 0 and o != curve_owner))

    quote_curve, quote_mint, seed_source, seed_vsol = detect_curve_seed(
        mint, create_tx, curve_owner
    )

    return BirthFeatures(
        mint=mint,
        born_standard=born,
        minted_raw=minted_raw,
        decimals=decimals,
        curve_owner=curve_owner,
        deployer=deployer,
        dev_buy_raw=dev_buy_raw,
        n_birth_legs=len(birth),
        n_snipers=len(snipers),
        snipers=snipers,
        partial=partial,
        notes=tuple(notes),
        quote_curve=quote_curve,
        curve_quote_mint=quote_mint,
        curve_seed_source=seed_source,
        curve_seed_vsol=seed_vsol,
    )


# -- the cheap (websocket-only) layer --------------------------------------------------


@dataclass(frozen=True, slots=True)
class CheapFeatures:
    """What the PumpPortal create frame alone can say, before any Helius spend.

    ``dev_buy_share`` here comes from the vendor's ``initialBuy`` — a vendor FLOAT
    (see shitcoims_scalper.firehose's money warning), printed in whole tokens to six
    decimals, which happens to be raw/1e6 exactly, so for a 2%-of-supply threshold the
    float is safely far from the rounding cliff. It is still marked ``ws_vendor_float``
    and replaced by the chain-exact value whenever the launch is hydrated.
    """

    mint: str
    creator: str | None  # traderPublicKey — known live even with NO dev buy,
    #                       which the corpus's deployer (a dev-buy artifact) is not
    bonding_curve: str | None
    dev_buy_raw_est: int
    name: str | None
    symbol: str | None
    is_mayhem_mode: bool
    pool: str | None
    signature: str | None
    # vendor-float seed estimate: vSolInBondingCurve minus solAmount. Reads exactly 30.0 on
    # every retained standard AND mayhem frame; expected ≈4.292 on a quote-curve frame,
    # but no such frame has been retained yet, so this is a suspicion-only witness —
    # hydration's create-event/leg check decides (detect_curve_seed).
    v_sol_seed_est: float | None = None

    @property
    def dev_buy_share_est(self) -> float:
        return self.dev_buy_raw_est / PUMP_SUPPLY_RAW

    @property
    def quote_seed_suspected(self) -> bool:
        est = self.v_sol_seed_est
        return est is not None and abs(est - SEED_QUOTE_USDC_RAW / 1e9) < 1e-3


def cheap_features_from_event(payload: Mapping[str, Any]) -> CheapFeatures:
    raw_buy = payload.get("initialBuy") or 0
    try:
        dev_buy_raw_est = round(float(raw_buy) * 10**PUMP_DECIMALS)
    except (TypeError, ValueError):
        dev_buy_raw_est = 0
    try:
        v_sol_seed_est = float(payload["vSolInBondingCurve"]) - float(payload.get("solAmount") or 0)
    except (KeyError, TypeError, ValueError):
        v_sol_seed_est = None
    return CheapFeatures(
        mint=str(payload.get("mint", "")),
        creator=payload.get("traderPublicKey"),
        bonding_curve=payload.get("bondingCurveKey"),
        dev_buy_raw_est=dev_buy_raw_est,
        name=payload.get("name"),
        symbol=payload.get("symbol"),
        is_mayhem_mode=bool(payload.get("is_mayhem_mode", False)),
        pool=payload.get("pool"),
        signature=payload.get("signature"),
        v_sol_seed_est=v_sol_seed_est,
    )
