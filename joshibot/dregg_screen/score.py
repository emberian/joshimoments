"""Verdicts and the TG-postable line. Scores RANK risk; nothing here convicts.

THE VERDICT SET, and one honest deviation from the brief
--------------------------------------------------------
The brief named four verdicts — CLEAN / BUNDLED / KNOWN-CREW / UNSCORED — and those
four do not tile the outcome space: a launch with a 5% dev buy, no bundle, and no
history fails the validated screen (the dev-buy gate is one of its five conjuncts)
while being neither bundled nor crew-linked. Renaming it CLEAN would detach the emitted
precision numbers from what B1 measured; folding it into BUNDLED would be a lie about
mechanism. So there is a fifth verdict, NOT_CLEAN, for launches that fail the screen on
gates the other names do not describe. Every non-CLEAN verdict carries its reasons.

Precedence (most identifying signal wins):
  UNSCORED    — nonstandard curve, hydration failure, or budget policy; reason attached.
  KNOWN_CREW  — a named fingerprint: dirty-crew Jaccard match, a deployer with recorded
                rips/dumps, or a recidivist birth-slot sniper. The trigger is named.
  BUNDLED     — >= 2 birth-slot buyers (the on-chain bundle shape; needs no Jito id)
                with no known-crew link.
  NOT_CLEAN   — fails remaining gates (dev buy >= 2% of supply).
  CLEAN       — all five validated gates pass, on hydrated (chain-exact) features.

CLEAN is only ever emitted from HYDRATED features: four of the five gates are readable
from the websocket event plus the ledger, but ``n_snipers <= 1`` and the sniper
identities are not, and a CLEAN minted without them would be a different (unvalidated)
screen wearing the validated one's precision numbers.

LANGUAGE DISCIPLINE (baked in, not a style preference)
------------------------------------------------------
The emitted line says what was MEASURED: "matched crew fingerprint #81422 (Jaccard
0.31, 4 shared birth-slot wallets)" — never "scammer", "rugger", or any claim about a
person. Base rates ride along on every line so a reader sees the denominator, and every
line ends by saying the score ranks risk rather than proving intent.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .features import (
    GATE_MAX_DEV_BUY_SHARE,
    GATE_MAX_SNIPERS,
    BirthFeatures,
    CheapFeatures,
)
from .ledger import CrewMatch, DeployerHistory, Ledger

VERDICT_CLEAN = "CLEAN"
VERDICT_BUNDLED = "BUNDLED"
VERDICT_KNOWN_CREW = "KNOWN_CREW"
VERDICT_NOT_CLEAN = "NOT_CLEAN"
VERDICT_UNSCORED = "UNSCORED"


@dataclass(frozen=True, slots=True)
class Score:
    mint: str
    verdict: str
    reasons: tuple[str, ...]
    name: str | None
    symbol: str | None
    creator: str | None
    deployer: str | None
    hydrated: bool
    in_validated_population: bool
    population_notes: tuple[str, ...]
    features: dict[str, Any]
    crew: CrewMatch | None
    history: DeployerHistory
    base_rates: dict[str, Any] = field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        out = {
            "mint": self.mint,
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "name": self.name,
            "symbol": self.symbol,
            "creator": self.creator,
            "deployer": self.deployer,
            "hydrated": self.hydrated,
            "in_validated_population": self.in_validated_population,
            "population_notes": list(self.population_notes),
            "features": self.features,
            "crew_match": asdict(self.crew) if self.crew else None,
            "deployer_history": asdict(self.history),
            "base_rates": self.base_rates,
        }
        out["tg_line"] = tg_line(self)
        return out


def base_rates_from_ledger(ledger: Ledger) -> dict[str, Any]:
    """The measured operating point every score quotes, pulled from the embedded B1 blob."""

    v = (ledger.meta.get("validation") or {}).get("screen_seeded") or {}
    out: dict[str, Any] = {"validated_span": (ledger.meta.get("validation") or {}).get("validated_span")}
    for outcome in ("is_rip", "collapse"):
        o = v.get(outcome) or {}
        if o:
            out[outcome] = {
                "base_rate": o.get("base_rate"),
                "clean_precision": o.get("clean_precision"),
                "clean_ci95": o.get("clean_ci"),
                "admit_rate": o.get("admit_rate"),
            }
    return out


def score_launch(
    cheap: CheapFeatures,
    birth: BirthFeatures | None,
    ledger: Ledger,
    *,
    unscored_reason: str | None = None,
    crew_min_overlap: int = 2,
    crew_min_jaccard: float = 0.10,
    base_rates: dict[str, Any] | None = None,
) -> Score:
    """Score one launch. ``birth`` is None when hydration was not performed (policy,
    budget, or failure) — ``unscored_reason`` then says which, and the cheap gates
    still run so a launch the cheap features already condemn gets its real verdict
    rather than a shrug."""

    hydrated = birth is not None
    deployer = birth.deployer if hydrated else None
    # The corpus deployer is a dev-buy artifact (BIRTH_SQL rank-2 leg); live we always
    # know the creator wallet from the event. History keys off the corpus-rule deployer
    # when hydrated, else the creator — the creator IS the dev-buy recipient whenever
    # one exists, and the parity test holds that equality on real corpus rows.
    history_key = deployer or cheap.creator
    history = ledger.deployer_history(history_key)

    dev_buy_raw = birth.dev_buy_raw if hydrated else cheap.dev_buy_raw_est
    dev_buy_share = dev_buy_raw / 1_000_000_000_000_000

    population_notes: list[str] = []
    if cheap.is_mayhem_mode and not hydrated:
        # Measured 2026-08-29: every hydrated mayhem-flagged create minted 2e15 raw —
        # OUTSIDE the corpus's BORN predicate (exactly 1e15). The vendor's own
        # vTokensInBondingCurve still reads standard on those frames, so the flag is
        # the only cheap witness. Hydration, when it runs, decides authoritatively via
        # minted_raw and replaces this note with a hard nonstandard_curve verdict.
        population_notes.append("vendor_flag:is_mayhem_mode:curve_unverified")
    if not cheap.mint.endswith("pump"):
        population_notes.append("mint_without_pump_suffix")
    if dev_buy_raw == 0:
        # The validated test population was coins WITH an identified deployer, i.e. a
        # dev buy > 0 (cmd_screen filters deployer.notna()). A no-dev-buy launch is
        # scored — live knows the creator, which the corpus could not — but the quoted
        # precision was not measured on its stratum, and the flag says so.
        population_notes.append("no_dev_buy:outside_validated_population")
    in_pop = not population_notes

    features: dict[str, Any] = {
        "dev_buy_raw": dev_buy_raw,
        "dev_buy_share": round(dev_buy_share, 6),
        "dev_buy_source": "chain_exact" if hydrated else "ws_vendor_float",
        "is_mayhem_mode": cheap.is_mayhem_mode,
        "prior_launches": history.launches,
        "prior_rips": history.rips,
        "prior_dumps": history.dumps,
        "prior_grads": history.grads,
    }

    crew: CrewMatch | None = None
    sniper_prior_max = 0
    if hydrated:
        features.update(
            n_snipers=birth.n_snipers,
            n_birth_legs=birth.n_birth_legs,
            birth_partial=birth.partial,
            snipers=list(birth.snipers),
        )
        sniper_prior_max = ledger.sniper_prior_max(birth.snipers)
        features["sniper_prior_max"] = sniper_prior_max
        crew = ledger.crew_match(
            birth.snipers_ex_deployer,
            min_overlap=crew_min_overlap,
            min_jaccard=crew_min_jaccard,
        )

    reasons: list[str] = []
    if hydrated and not birth.born_standard:
        return _finish(
            cheap, VERDICT_UNSCORED,
            [f"nonstandard_curve:minted_raw={birth.minted_raw},decimals={birth.decimals}"],
            deployer, hydrated, False, population_notes, features, None, history,
            base_rates or {},
        )

    # KNOWN_CREW: the three history arms, most specific first. A crew match against a
    # crew with no recorded rips/dumps stays a NOTE (crew continuity is not a record).
    if crew is not None and crew.dirty:
        reasons.append(
            f"crew_fingerprint:#{crew.crew_id}:jaccard={crew.jaccard}:overlap={crew.overlap}"
        )
    if history.rips > 0 or history.dumps > 0:
        reasons.append(
            f"deployer_record:launches={history.launches},rips={history.rips},dumps={history.dumps}"
        )
    if sniper_prior_max > 0:
        reasons.append(f"recidivist_sniper:prior_coins={sniper_prior_max}")
    if reasons:
        if crew is not None and not crew.dirty:
            features["crew_continuity_note"] = asdict(crew)
        return _finish(cheap, VERDICT_KNOWN_CREW, reasons, deployer, hydrated, in_pop,
                       population_notes, features, crew if crew and crew.dirty else None,
                       history, base_rates or {})
    if crew is not None:  # clean-crew continuity, worth carrying but not a verdict
        features["crew_continuity_note"] = asdict(crew)

    if hydrated and birth.n_snipers > GATE_MAX_SNIPERS:
        reasons.append(f"bundled_at_birth:n_snipers={birth.n_snipers}")
        return _finish(cheap, VERDICT_BUNDLED, reasons, deployer, hydrated, in_pop,
                       population_notes, features, None, history, base_rates or {})

    if dev_buy_share >= GATE_MAX_DEV_BUY_SHARE:
        reasons.append(f"dev_buy_share={dev_buy_share:.4f}>= {GATE_MAX_DEV_BUY_SHARE}")
        return _finish(cheap, VERDICT_NOT_CLEAN, reasons, deployer, hydrated, in_pop,
                       population_notes, features, None, history, base_rates or {})

    if not hydrated:
        # Cheap gates all pass; only hydration could mint a CLEAN, and it did not run.
        return _finish(cheap, VERDICT_UNSCORED,
                       [unscored_reason or "not_hydrated", "cheap_gates_passed"],
                       deployer, hydrated, in_pop, population_notes, features, None,
                       history, base_rates or {})

    if birth.partial:
        # A capped same-slot scan can undercount snipers; a CLEAN needs the full slot.
        return _finish(cheap, VERDICT_UNSCORED, ["birth_slot_partial"], deployer, hydrated,
                       in_pop, population_notes, features, None, history, base_rates or {})

    return _finish(cheap, VERDICT_CLEAN, ["all_gates_passed"], deployer, hydrated, in_pop,
                   population_notes, features, None, history, base_rates or {})


def _finish(
    cheap: CheapFeatures,
    verdict: str,
    reasons: list[str],
    deployer: str | None,
    hydrated: bool,
    in_pop: bool,
    population_notes: list[str],
    features: dict[str, Any],
    crew: CrewMatch | None,
    history: DeployerHistory,
    base_rates: dict[str, Any],
) -> Score:
    return Score(
        mint=cheap.mint,
        verdict=verdict,
        reasons=tuple(reasons),
        name=cheap.name,
        symbol=cheap.symbol,
        creator=cheap.creator,
        deployer=deployer,
        hydrated=hydrated,
        in_validated_population=in_pop,
        population_notes=tuple(population_notes),
        features=features,
        crew=crew,
        history=history,
        base_rates=base_rates,
    )


def tg_line(score: Score) -> str:
    """One postable line. Ranks risk, names measurements, convicts nobody."""

    sym = f"${score.symbol.lstrip('$')}" if score.symbol else score.mint[:8]
    f = score.features
    if score.verdict == VERDICT_CLEAN:
        head = (
            f"CLEAN {sym} {score.mint} — no bundle ({f.get('n_snipers', '?')} birth-slot "
            f"buyer{'s' if f.get('n_snipers') != 1 else ''}), dev buy "
            f"{100 * f['dev_buy_share']:.2f}%, deployer record {f['prior_launches']} launches / "
            f"0 rips / 0 dumps, no crew overlap."
        )
        rate = (score.base_rates.get("collapse") or {}).get("clean_precision")
        span = score.base_rates.get("validated_span")
        if rate and span:
            head += f" Screen precision {100 * rate:.2f}% vs collapse ({span})."
    elif score.verdict == VERDICT_KNOWN_CREW:
        bits = []
        if score.crew:
            c = score.crew
            bits.append(
                f"matched crew fingerprint #{c.crew_id} (Jaccard {c.jaccard}, {c.overlap} shared "
                f"birth-slot wallets; that crew's {c.crew_coins} corpus coins carry "
                f"{c.crew_rips} rips / {c.crew_dumps} insider dumps)"
            )
        h = score.history
        if h.rips or h.dumps:
            bits.append(
                f"deployer's corpus record: {h.launches} launches, {h.rips} rips, {h.dumps} dumps"
            )
        if f.get("sniper_prior_max", 0) > 0:
            bits.append(
                f"a birth-slot buyer seen in {f['sniper_prior_max']} prior corpus birth slots"
            )
        head = f"KNOWN-CREW {sym} {score.mint} — " + "; ".join(bits) + "."
    elif score.verdict == VERDICT_BUNDLED:
        head = (
            f"BUNDLED {sym} {score.mint} — {f.get('n_snipers', '?')} buyers in the birth slot "
            f"(a mint nobody had published one slot earlier; that shape does not happen "
            f"organically), dev buy {100 * f['dev_buy_share']:.2f}%."
        )
    elif score.verdict == VERDICT_NOT_CLEAN:
        head = (
            f"NOT-CLEAN {sym} {score.mint} — dev buy {100 * f['dev_buy_share']:.2f}% of supply "
            f"(gate is <2%)."
        )
        if not score.hydrated:
            head += " Birth slot not hydrated (cheap gates already fail)."
    else:
        head = f"UNSCORED {sym} {score.mint} — {'; '.join(score.reasons)}."
    rates = score.base_rates.get("collapse") or {}
    tail = ""
    if rates.get("base_rate") is not None:
        tail = f" Base collapse rate {100 * rates['base_rate']:.2f}%."
    if not score.in_validated_population:
        tail += " Outside the validated population (" + ", ".join(score.population_notes) + ")."
    return head + tail + " Scores rank risk; they do not establish intent."


def json_row(score: Score, extra: dict[str, Any] | None = None) -> str:
    row = score.row()
    if extra:
        row.update(extra)
    return json.dumps(row, separators=(",", ":"), sort_keys=False)
