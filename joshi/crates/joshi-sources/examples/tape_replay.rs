//! Replaying one retained coin tape through declared rule variants, offline and for free.
//!
//! ```text
//! tape_replay --root <tape dir> --mint <address> --hypothesis "<the operator's words>"
//!             [--out <path>] [--clip-sol 0.05] [--max-hold-seconds 60]
//!             [--entry-deadline-seconds 120] [--stop-bps 300]
//!             --known-first "<what the declarer already knew about this tape>"
//!             [--network-fee-lamports 7422] [--declared-by ember] [--sweep]
//! ```
//!
//! This reopens the durable catalog a `coin_tape_live record` run left behind, read-only, rebuilds
//! one venue state per retained trade frame for the named mint, and hands the ordered frames to
//! [`joshi_liquidity::replay::ReplayPanelV1`], which runs them through an unremovable baseline and
//! every declared variant on the same [`joshi_liquidity::paper::PaperDeskV1`] the live desk uses.
//! It opens no socket, reads no account, constructs nothing, signs nothing and submits nothing.
//!
//! **What the tape states, measured on 2026-08-22 over 1,734 retained trade frames.** No frame
//! carries a timestamp, a `blockTime` or a slot, so the only time axis is the recorder's own
//! receive instant. Reserves are post-trade and stated in whole units, not atoms: a `pool:"pump"`
//! frame states `vSolInBondingCurve`/`vTokensInBondingCurve`, which *are* the tuple the bonding
//! curve's own formula walks; a `pool:"pump-amm"` frame states `solInPool`/`tokensInPool`, which
//! are the pool's vault balances and are *not* the reserve the deployed swap uses.
//!
//! **What this driver therefore has to declare, and how the declaration is falsified.** The
//! `PumpSwap` constant-product step adds a term this codebase locates at pool byte 245 and
//! declines to name; a survey of 42 mainnet pools on 2026-08-22 found the same value,
//! 17,584,505,288 atoms, on 29 of them. This driver declares that term, and declares the fee
//! schedules Study M0 read from the fee program's configuration account. Both declarations are
//! then checked against the tape's own reserve evolution, and the same check is run again with
//! the term set to zero as a control. The control is printed beside the declaration precisely so
//! that a reader can see the declaration is doing work rather than being assumed.

use std::{
    error::Error,
    path::{Path, PathBuf},
    time::Duration,
};

use joshi_domain::{SourceId as DomainSourceId, StableString};
use joshi_liquidity::{
    paper::{DeclaredHypothesis, EntryRule, VenueBinding},
    readout::{FeeRateSource, VenueKind},
    replay::{
        DeclaredVariant, ReplayDeclaration, ReplayPanelV1, TapeFrame, atoms_from_decimal_literal,
        check_reserve_evolution,
    },
    round_trip::DeclaredFixedCosts,
};
use joshi_market_math::{
    fee::{CreatorFee, FeeBps, FeeSchedule},
    stack::ExactCurveState,
};
use joshi_sources::{FrameDirection, RetainedFrameEnvelope};
use joshi_store::{SqliteStore, StoreConfig, StoreMode, VerifyDepth};
use serde_json::Value;
use sha2::{Digest, Sha256};

const SOURCE_ID: &str = "pumpportal.websocket.data.v1";
const CATALOG_ID: &str = "joshi-coin-tape";
const INLINE_BLOB_MAX_BYTES: u64 = 4 * 1024 * 1024;
const MAX_OBSERVATIONS_PER_BATCH: usize = 64;
const MAX_RAW_BYTES_PER_BATCH: u64 = 64 * 1024 * 1024;
const BUSY_TIMEOUT: Duration = Duration::from_secs(5);
const READBACK_LIMIT: usize = 200_000;
const DEFAULT_CLIP_LAMPORTS: u128 = 50_000_000;
/// Network fee observed on a landed `PumpSwap` sell in Study M0's fixture, 2026-08-21.
const DEFAULT_NETWORK_FEE_LAMPORTS: u128 = 7_422;
const SOL_DECIMALS: u8 = 9;
const PUMP_TOKEN_DECIMALS: u8 = 6;

/// The term the deployed `PumpSwap` step adds to the quote vault balance, declared here because
/// the tape states only the vault balance. Read at pool byte 245; identical across 29 of 42
/// mainnet pools surveyed on 2026-08-22, which is what a protocol-wide constant looks like and
/// still does not name it.
const DECLARED_UNATTRIBUTED_QUOTE_SIDE_ATOMS: u128 = 17_584_505_288;

/// Rates Study M0 read from the Pump fee program's configuration account for the graduated pool:
/// 20 bps to the pool, 5 to the protocol, 5 to the creator. The 20 is the one leg the tape can
/// check by itself, because it is the only component that stays in the pool.
const POOL_LP_BPS: u16 = 20;
const POOL_PROTOCOL_BPS: u16 = 5;
const POOL_CREATOR_BPS: u16 = 5;

/// The same, for the bonding curve: nothing to a provider that does not exist, 95 to the protocol
/// and 30 to the creator.
const CURVE_LP_BPS: u16 = 0;
const CURVE_PROTOCOL_BPS: u16 = 95;
const CURVE_CREATOR_BPS: u16 = 30;

fn main() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let root = PathBuf::from(flag(&arguments, "--root").ok_or_else(usage)?);
    let mint = flag(&arguments, "--mint").ok_or_else(usage)?;
    let words = flag(&arguments, "--hypothesis").ok_or_else(usage)?;
    let declared_by = flag(&arguments, "--declared-by").unwrap_or_else(|| "ember".to_owned());
    let clip = flag(&arguments, "--clip-sol")
        .map(|value| parse_sol(&value))
        .transpose()?
        .unwrap_or(DEFAULT_CLIP_LAMPORTS);
    let max_hold_seconds: i64 = parse(&arguments, "--max-hold-seconds", 60)?;
    let entry_deadline_seconds: i64 = parse(&arguments, "--entry-deadline-seconds", 120)?;
    let stop_bps: u32 = parse(&arguments, "--stop-bps", 300)?;
    let network_fee: u128 = parse(
        &arguments,
        "--network-fee-lamports",
        DEFAULT_NETWORK_FEE_LAMPORTS,
    )?;
    let declared_at: i64 = parse(&arguments, "--declared-at-unix-ms", 1_787_500_000_000)?;
    let known = flag(&arguments, "--known-first");
    let is_a_sweep = arguments.iter().any(|value| value == "--sweep");
    let out = flag(&arguments, "--out").map(PathBuf::from);

    let read = read_tape(&root)?;
    let (frames, reconstruction, control_states, digest) = build_frames(&read, &mint)?;
    if frames.is_empty() {
        return Err(format!("the tape holds no trade frame for {mint}").into());
    }
    let control = check_reserve_evolution(&control_states);

    let venue = venue_of(&frames, &mint)?;
    let declaration = ReplayDeclaration {
        panel_id: format!("replay-{}-{}", short(&mint), venue.venue.label()),
        tape_id: format!("{CATALOG_ID}:{}", root.display()),
        tape_provenance: format!(
            "reopened the durable catalog at {} read-only in a later process and verified it in \
             full; every frame below is the exact bytes a coin_tape_live record run retained \
             through source admission, in the order the catalog states. The digest covers exactly \
             the frames this panel replayed — this mint's, in tape order, ordinal and receive \
             instant and body — and not the whole retained tape",
            root.display()
        ),
        tape_digest_sha256: digest,
        mint: mint.clone(),
        venue: venue.clone(),
        hypothesis: DeclaredHypothesis {
            operator_words_verbatim: words,
            declared_by,
            declared_at_unix_ms: declared_at,
        },
        declared_clip_quote_atoms: clip,
        costs: DeclaredFixedCosts {
            provenance: format!(
                "network fee of {network_fee} lamports per landed transaction, twice, from the \
                 landed PumpSwap sell in Study M0's fixture on 2026-08-21; no rent, because the \
                 associated token account is assumed already funded, which flatters the trade"
            ),
            per_transaction_quote_atoms: network_fee,
            transactions: 2,
            flat_route_quote_atoms: 0,
            unrecovered_rent_quote_atoms: 0,
        },
        base_decimals: PUMP_TOKEN_DECIMALS,
        quote_decimals: SOL_DECIMALS,
        shared_max_hold_ms: max_hold_seconds * 1_000,
        shared_entry_deadline_ms: entry_deadline_seconds * 1_000,
        abandon_after_consecutive_refused_frames: 25,
        stated_but_not_in_the_tape: stated_but_not_in_the_tape(&venue, &reconstruction, &control),
        what_was_known_about_this_tape: known.ok_or(
            "--known-first is required: a replay's rules are not blind, and this panel will not \
             be built without a statement of what its declarer already knew about this tape",
        )?,
        is_a_sweep,
    };
    let panel = ReplayPanelV1::build(&declaration, &frames, &variants(stop_bps))?;
    print!("{}", panel.render_text());
    if let Some(path) = out {
        std::fs::write(&path, panel.render_json())?;
        println!("wrote {}", path.display());
    }
    Ok(())
}

/// The variants, declared here in source before any tape is read, one dimension moving at a time.
fn variants(stop_bps: u32) -> Vec<DeclaredVariant> {
    vec![
        DeclaredVariant {
            name: "immediate_take_profit_60bps".to_owned(),
            declared_because: "60 bps is the graduated pool's own measured round-trip fee floor. \
                               A take-profit at the floor is the tightest rule that can clear the \
                               venue at all, and it is here to find out whether taking the first \
                               tick above the floor beats holding to the clock."
                .to_owned(),
            entry: EntryRule::Immediate,
            take_profit_net_bps: 60,
            stop_loss_net_bps: stop_bps,
        },
        DeclaredVariant {
            name: "immediate_take_profit_100bps".to_owned(),
            declared_because: "one percent net of all-in cost, the centre of the take-profit \
                               family and the live desk's own default."
                .to_owned(),
            entry: EntryRule::Immediate,
            take_profit_net_bps: 100,
            stop_loss_net_bps: stop_bps,
        },
        DeclaredVariant {
            name: "immediate_take_profit_200bps".to_owned(),
            declared_because: "twice the centre. Wider than the centre on the same entry and the \
                               same stop, so the pair brackets the centre and the panel shows the \
                               direction the family moves in rather than one point of it."
                .to_owned(),
            entry: EntryRule::Immediate,
            take_profit_net_bps: 200,
            stop_loss_net_bps: stop_bps,
        },
        DeclaredVariant {
            name: "microdip_25bps_take_profit_100bps".to_owned(),
            declared_because: "a shallow dip: 25 bps under the first retained frame's marginal \
                               pool price. The hunch under it is that waiting for any dip at all \
                               buys a better entry than the first frame; 25 bps is under half the \
                               venue's own fee floor, so it is a dip a fee floor could hide."
                .to_owned(),
            entry: EntryRule::MicrodipBps { trigger_bps: 25 },
            take_profit_net_bps: 100,
            stop_loss_net_bps: stop_bps,
        },
        DeclaredVariant {
            name: "microdip_100bps_take_profit_100bps".to_owned(),
            declared_because: "a deep dip: 100 bps under the first retained frame, which is well \
                               past the venue's fee floor and therefore a move rather than a \
                               rounding. Paired with the shallow dip on the same exit rules, so \
                               the only thing that moves between them is how long the rule waits."
                .to_owned(),
            entry: EntryRule::MicrodipBps { trigger_bps: 100 },
            take_profit_net_bps: 100,
            stop_loss_net_bps: stop_bps,
        },
    ]
}

fn stated_but_not_in_the_tape(
    venue: &VenueBinding,
    reconstruction: &Reconstruction,
    control: &joshi_liquidity::replay::ReserveEvolutionCheck,
) -> Vec<String> {
    let mut stated = vec![
        format!(
            "FEE RATES. The tape states no fee rate on any frame. This replay declares the rates \
             Study M0 read from the Pump fee program's configuration account — {} — and applies \
             them to every frame without re-selecting a tier, because a tape carries no market \
             cap to select one at. Only the pool's own retained leg is checkable from the tape.",
            match venue.venue {
                VenueKind::PumpSwapPool => format!(
                    "{POOL_LP_BPS} bps to the pool, {POOL_PROTOCOL_BPS} to the protocol, \
                     {POOL_CREATOR_BPS} to the creator"
                ),
                VenueKind::PumpBondingCurve => format!(
                    "{CURVE_LP_BPS} bps to a provider that does not exist, {CURVE_PROTOCOL_BPS} \
                     to the protocol, {CURVE_CREATOR_BPS} to the creator"
                ),
            }
        ),
        "CREATOR-FEE APPLICABILITY. Whether a creator fee is charged is a property of the venue \
         account, which a trade frame does not carry. This replay declares it charged, which is \
         the choice that makes every trade here look worse rather than better."
            .to_owned(),
        format!(
            "ATOM GRID. The tape states reserves in whole units, not atoms. Atoms are recovered \
             by shifting the literal's own digits, never by scaling a float. {} of {} reserve \
             literals named an exact atom count; the worst any literal sat off the atom grid was \
             {} millionths of one atom, which at these reserve sizes is under one part in a \
             billion of the price and is reported rather than dropped.",
            reconstruction.exact, reconstruction.total, reconstruction.worst_micro_atoms
        ),
    ];
    if venue.venue == VenueKind::PumpSwapPool {
        stated.push(format!(
            "RESERVE COMPOSITION. A pump-amm frame states the pool's quote VAULT balance, and the \
             deployed constant-product step uses that balance plus a term this codebase locates \
             at pool byte 245 and declines to name. This replay declares that term at \
             {DECLARED_UNATTRIBUTED_QUOTE_SIDE_ATOMS} atoms, the value a 42-pool survey on \
             2026-08-22 found on 29 of them. CONTROL: replayed with the term at zero instead, the \
             same tape reproduces its own reserve evolution on {} of {} sell pairs, against the \
             declared term's result in this panel's tape block. A declaration that reproduces the \
             tape and a control that does not is the whole evidence that the term is real here.",
            control.sell_pairs_reproduced_to_the_atom, control.sell_pairs
        ));
    }
    stated
}

/// How far the feed's own decimal literals sat off the atom grid, over the whole tape.
struct Reconstruction {
    total: u32,
    exact: u32,
    worst_micro_atoms: u128,
}

struct ReadTape {
    frames: Vec<(u64, i64, Vec<u8>)>,
}

fn read_tape(root: &Path) -> Result<ReadTape, Box<dyn Error>> {
    let store = SqliteStore::open(catalog_config(root)?, StoreMode::ReadOnly)?;
    let verification = store.verify(VerifyDepth::Full)?;
    if verification.integrity != "ok" {
        return Err("the reopened catalog failed verification".into());
    }
    let source_id = DomainSourceId::new(SOURCE_ID)?;
    let Some(stored) = store.source_observations_as_known(&source_id, None, READBACK_LIMIT)? else {
        return Err("the catalog holds no observations for this source".into());
    };
    if stored.truncated {
        return Err("the catalog holds more frames than this read-back asked for".into());
    }
    let mut frames = Vec::with_capacity(stored.observations.len());
    for observation in &stored.observations {
        let envelope: RetainedFrameEnvelope = serde_json::from_slice(&observation.payload)?;
        if envelope.direction == FrameDirection::OutboundControl {
            continue;
        }
        let sequence: u64 = observation
            .acquisition_id
            .as_str()
            .rsplit(':')
            .next()
            .and_then(|value| value.parse().ok())
            .ok_or("a retained acquisition id states no frame sequence")?;
        let received = i64::try_from(
            observation.received_at.as_datetime().unix_timestamp_nanos() / 1_000_000,
        )?;
        frames.push((sequence, received, envelope.body.clone()));
    }
    frames.sort_by_key(|(sequence, _, _)| *sequence);
    Ok(ReadTape { frames })
}

/// Rebuilds one venue state per retained trade frame for the named mint.
///
/// A frame for another subject is not this mint's tape and is dropped. A frame for this mint that
/// states no usable reserve pair is a recorded refusal, never an interpolation.
#[allow(clippy::type_complexity, clippy::too_many_lines)]
fn build_frames(
    read: &ReadTape,
    mint: &str,
) -> Result<(Vec<TapeFrame>, Reconstruction, Vec<ExactCurveState>, String), Box<dyn Error>> {
    let mut frames = Vec::new();
    let mut control = Vec::new();
    let mut hasher = Sha256::new();
    let mut reconstruction = Reconstruction {
        total: 0,
        exact: 0,
        worst_micro_atoms: 0,
    };
    for (ordinal, received, body) in &read.frames {
        let Ok(text) = core::str::from_utf8(body) else {
            continue;
        };
        let Ok(value) = serde_json::from_str::<Value>(text) else {
            continue;
        };
        if value.get("signature").is_none() {
            continue;
        }
        if value["mint"].as_str() != Some(mint) {
            continue;
        }
        hasher.update(ordinal.to_be_bytes());
        hasher.update(received.to_be_bytes());
        hasher.update(body);
        let pool = value["pool"].as_str().unwrap_or_default();
        let (quote_key, base_key, formula, schedule, term) = match pool {
            "pump" => (
                "vSolInBondingCurve",
                "vTokensInBondingCurve",
                VenueKind::PumpBondingCurve,
                schedule(CURVE_LP_BPS, CURVE_PROTOCOL_BPS, CURVE_CREATOR_BPS)?,
                0,
            ),
            "pump-amm" => (
                "solInPool",
                "tokensInPool",
                VenueKind::PumpSwapPool,
                schedule(POOL_LP_BPS, POOL_PROTOCOL_BPS, POOL_CREATOR_BPS)?,
                DECLARED_UNATTRIBUTED_QUOTE_SIDE_ATOMS,
            ),
            other => {
                frames.push(TapeFrame::Refused {
                    ordinal: *ordinal,
                    receive_unix_ms: *received,
                    reason: format!(
                        "the frame states pool {other:?}, whose reserve fields and fee \
                         convention this replay has not established; nothing was substituted"
                    ),
                });
                continue;
            }
        };
        let quote = reserve(text, &value, quote_key, SOL_DECIMALS);
        let base = reserve(text, &value, base_key, PUMP_TOKEN_DECIMALS);
        let (Some(quote), Some(base)) = (quote, base) else {
            frames.push(TapeFrame::Refused {
                ordinal: *ordinal,
                receive_unix_ms: *received,
                reason: format!(
                    "the frame states pool {pool:?} but no reconstructable {quote_key} / \
                     {base_key} pair, so it supports no state a quote can be walked against"
                ),
            });
            continue;
        };
        for recovered in [&quote, &base] {
            reconstruction.total += 1;
            if recovered.off_grid_micro_atoms == 0 {
                reconstruction.exact += 1;
            }
            reconstruction.worst_micro_atoms = reconstruction
                .worst_micro_atoms
                .max(recovered.off_grid_micro_atoms);
        }
        if base.atoms == 0 || quote.atoms == 0 {
            frames.push(TapeFrame::Refused {
                ordinal: *ordinal,
                receive_unix_ms: *received,
                reason: "the frame states a zero reserve; a state with a zero reserve is not a \
                         state a quote can be computed at"
                    .to_owned(),
            });
            continue;
        }
        control.push(ExactCurveState {
            formula: formula.formula(),
            base_atoms: base.atoms,
            effective_quote_atoms: quote.atoms,
            schedule,
        });
        frames.push(TapeFrame::State {
            ordinal: *ordinal,
            receive_unix_ms: *received,
            state: ExactCurveState {
                formula: formula.formula(),
                base_atoms: base.atoms,
                effective_quote_atoms: quote.atoms + term,
                schedule,
            },
            fee_source: FeeRateSource::CarriedFromPriorReading {
                established_by: format!(
                    "Study M0's read of the Pump fee program configuration account for the {} \
                     program, 2026-08-21: lp {} bps, protocol {} bps, creator {} bps",
                    formula.label(),
                    schedule.lp.get(),
                    schedule.protocol.get(),
                    match schedule.creator {
                        CreatorFee::Charged(rate) => rate.get(),
                        CreatorFee::NotApplicable | CreatorFee::Unknown => 0,
                    }
                ),
                not_read_here_because:
                    "a replay reads no account: this state came from a retained websocket trade \
                     frame, which states no fee rate, no market cap and no tier"
                        .to_owned(),
            },
        });
    }
    Ok((frames, reconstruction, control, hex(hasher)))
}

/// Lowercase hex of a finished digest.
fn hex(hasher: Sha256) -> String {
    hasher
        .finalize()
        .iter()
        .fold(String::new(), |mut held, byte| {
            use core::fmt::Write as _;
            let _ = write!(held, "{byte:02x}");
            held
        })
}

/// Recovers one reserve from the frame's own decimal literal, and cross-checks the recovery
/// against the parser's float so a mis-scanned literal cannot pass silently.
fn reserve(
    text: &str,
    value: &Value,
    key: &str,
    decimals: u8,
) -> Option<joshi_liquidity::replay::ReconstructedAtoms> {
    let literal = literal(text, key)?;
    let recovered = atoms_from_decimal_literal(literal, decimals).ok()?;
    let stated = value[key].as_f64()?;
    let scale = 10_f64.powi(i32::from(decimals));
    #[allow(clippy::cast_precision_loss)] // A cross-check on the scan, not the arithmetic.
    let recovered_as_float = recovered.atoms as f64 / scale;
    if (recovered_as_float - stated).abs() > stated.abs() * 1e-9 {
        return None;
    }
    Some(recovered)
}

/// The exact decimal literal one key states, from the frame's own bytes.
fn literal<'a>(text: &'a str, key: &str) -> Option<&'a str> {
    let needle = format!("\"{key}\":");
    let start = text.find(&needle)? + needle.len();
    let rest = &text[start..];
    let end = rest
        .find(|character: char| !matches!(character, '0'..='9' | '.' | '+' | '-' | 'e' | 'E'))
        .unwrap_or(rest.len());
    (end > 0).then(|| &rest[..end])
}

fn venue_of(frames: &[TapeFrame], mint: &str) -> Result<VenueBinding, Box<dyn Error>> {
    let state = frames
        .iter()
        .find_map(TapeFrame::state)
        .ok_or("no retained frame for this mint supports a state")?;
    let venue = match state.formula {
        joshi_market_math::stack::VenueFormula::PumpBondingCurve => VenueKind::PumpBondingCurve,
        joshi_market_math::stack::VenueFormula::PumpSwapExactQuoteIn => VenueKind::PumpSwapPool,
    };
    Ok(VenueBinding {
        venue,
        venue_account: match venue {
            VenueKind::PumpBondingCurve => "not read: the frame names a bondingCurveKey and this \
                 replay prices from the frame's own reserves, so that account was never read"
                .to_owned(),
            VenueKind::PumpSwapPool => {
                "not stated: a pump-amm trade frame names no pool account".to_owned()
            }
        },
        binding: format!(
            "the frame states mint {mint} and pool {}, and the reserve pair it carries is the one \
             that venue's formula walks; no account was read to confirm it, and the binding rests \
             on the frame's own two fields",
            match venue {
                VenueKind::PumpBondingCurve => "pump",
                VenueKind::PumpSwapPool => "pump-amm",
            }
        ),
    })
}

fn schedule(lp: u16, protocol: u16, creator: u16) -> Result<FeeSchedule, Box<dyn Error>> {
    Ok(FeeSchedule {
        lp: FeeBps::new(lp)?,
        protocol: FeeBps::new(protocol)?,
        creator: CreatorFee::Charged(FeeBps::new(creator)?),
    })
}

fn catalog_config(root: &Path) -> Result<StoreConfig, Box<dyn Error>> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: INLINE_BLOB_MAX_BYTES,
        busy_timeout: BUSY_TIMEOUT,
        catalog_id: StableString::new(CATALOG_ID)?,
        max_observations_per_batch: MAX_OBSERVATIONS_PER_BATCH,
        max_raw_bytes_per_batch: MAX_RAW_BYTES_PER_BATCH,
    })
}

fn short(mint: &str) -> String {
    mint.chars().take(8).collect()
}

fn usage() -> Box<dyn Error> {
    "usage: tape_replay --root <tape dir> --mint <address> --hypothesis \"<words>\" [--out <path>] \
     [--clip-sol 0.05] [--max-hold-seconds 60] [--entry-deadline-seconds 120] [--stop-bps 300] \
     --known-first \"<what the declarer already knew about this tape>\" [--network-fee-lamports 7422] \
     [--declared-by ember] [--declared-at-unix-ms n] [--sweep]"
        .into()
}

fn flag(arguments: &[String], name: &str) -> Option<String> {
    arguments
        .iter()
        .position(|value| value == name)
        .and_then(|index| arguments.get(index + 1))
        .cloned()
}

fn parse<T: std::str::FromStr>(
    arguments: &[String],
    name: &str,
    default: T,
) -> Result<T, Box<dyn Error>>
where
    T::Err: std::fmt::Display,
{
    match flag(arguments, name) {
        None => Ok(default),
        Some(value) => value
            .parse::<T>()
            .map_err(|error| format!("invalid {name}: {error}").into()),
    }
}

fn parse_sol(value: &str) -> Result<u128, Box<dyn Error>> {
    let recovered = atoms_from_decimal_literal(value, SOL_DECIMALS)?;
    if recovered.atoms == 0 {
        return Err("a zero clip is not a clip".into());
    }
    Ok(recovered.atoms)
}
