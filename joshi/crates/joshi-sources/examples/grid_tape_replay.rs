//! Sweeping a declared grid-ladder ensemble over a retained Duck tape — socket, polled, or both.
//!
//! ```text
//! grid_tape_replay --mint <address> [--socket-root <dir>] [--polled-root <dir>]
//!     --hypothesis "<the operator's words>" [--known-first "<prior knowledge>"]
//!     [--out <path>] [--declared-by ember] [--declared-at-unix-ms n]
//!     [--network-fee-lamports 7422]
//!     [--fee-lp-bps 20] [--fee-protocol-bps 5] [--fee-creator-bps 5]
//!     [--spacings-bps a,b,..] [--half-bands-bps a,b,..] [--clips-sol a,b,..]
//!     [--chop-band-bps 667] [--split-num 1] [--split-den 2]
//! ```
//!
//! Two recorder shapes are accepted, read-only, and never both required:
//!
//! * `--socket-root`: a `coin_tape_live record` catalog (`joshi-coin-tape`) of `PumpPortal`
//!   websocket trade frames. Frames state post-trade reserves; the arrival clock is event-grade,
//!   so availability equals receipt.
//! * `--polled-root`: a `joshi-pump-product-read` state dir of retained `trades` pages, polled on
//!   a cadence. Pages state NO reserves; every event's reserve pair is DERIVED from the row's own
//!   three stated legs through `joshi_liquidity::trade_derive` and falsified against the tape's
//!   own evolution. Availability is the receive instant of the first page holding the row, so the
//!   poll cadence is priced into every fill's haircut rather than assumed away.
//!
//! When both roots are given the panel replays the socket tape (the better decision clock) and
//! the two recordings are reconciled fill-by-fill by transaction signature over their overlap;
//! agreement and disagreement counts travel in the panel. Disagreement is a finding, not a
//! nuisance.
//!
//! This opens no live socket, reads no account, signs nothing and submits nothing.

use std::{
    collections::BTreeMap,
    error::Error,
    path::{Path, PathBuf},
    time::Duration,
};

use joshi_domain::{SourceId as DomainSourceId, StableString};
use joshi_liquidity::{
    grid::{
        GridFrame, GridSweepAxes, GridSweepDeclaration, GridSweepPanelV1, GridTapeEvent,
        TapeCoverage, TwoSourceReconciliationV1,
    },
    paper::{DeclaredHypothesis, VenueBinding},
    readout::VenueKind,
    replay::atoms_from_decimal_literal,
    round_trip::{DeclaredFixedCosts, self_round_trip},
    trade_derive::{
        ChainRow, ChainRowState, CurveLegs, StatedPostPrice, TradeDirection,
        reconstruct_pumpswap_chain, stated_post_price,
    },
};
use joshi_market_math::{
    fee::{CreatorFee, FeeBps, FeeSchedule},
    stack::{ExactCurveState, VenueFormula},
};
use joshi_sources::{FrameDirection, RetainedFrameEnvelope};
use joshi_store::{SqliteStore, StoreConfig, StoreMode, VerifyDepth};
use serde_json::Value;
use sha2::{Digest, Sha256};

const SOCKET_SOURCE_ID: &str = "pumpportal.websocket.data.v1";
const SOCKET_CATALOG_ID: &str = "joshi-coin-tape";
const POLLED_SOURCE_ID: &str = "pump.api.product.v1";
const POLLED_CATALOG_ID: &str = "joshi-pump-product-read";
const READBACK_LIMIT: usize = 200_000;
const SOL_DECIMALS: u8 = 9;
const PUMP_TOKEN_DECIMALS: u8 = 6;
/// Network fee observed on a landed `PumpSwap` sell in Study M0's fixture, 2026-08-21.
const DEFAULT_NETWORK_FEE_LAMPORTS: u128 = 7_422;
/// The term the deployed `PumpSwap` step adds to the quote vault balance a websocket frame
/// states. Read at pool byte 245; identical across 29 of 42 mainnet pools surveyed 2026-08-22.
/// The DERIVED states of a polled tape need no such term: the derivation recovers the effective
/// reserve directly.
const SOCKET_UNATTRIBUTED_QUOTE_SIDE_ATOMS: u128 = 17_584_505_288;
/// The coin this run was built around. Only its default prior text is bound to it.
const DUCK_MINT: &str = "Gu29wuSbMdQKPpkmZ4wpiURgQbYohpBFpwPbzJLbz8Mr";
const DUCK_PRIOR: &str = "Ember watched the coin live before any rule was declared: 1-second \
candles chopping between roughly 42k and 48k USD market cap, and a venue readout minutes before \
the tape measured about 190 bps abort round trip and about 256 bps hurdle at 0.25 SOL on the \
worse-branch fee tier. The band axis below is built from exactly that chop prior and the spacing \
axis from exactly that floor, so nothing chosen here was blind to this coin's morning. AND MORE: \
before this panel was finished, its builders had ALREADY measured the recorded window end to end \
on the parallel socket tape — it contains a FULL COLLAPSE, price falling about 87 percent \
(4.97e-7 to 6.39e-8 SOL per token) across roughly 1,689 events and 647 SOL of flow (929 buys, \
760 sells), with the event-clock variance signature rising through lag 8 then falling by lag \
128+ (short-horizon momentum cascades inside a one-way collapse). Every number below was \
computed KNOWING the tape is a chop-then-collapse window; nothing here is a discovery about \
this tape, and a grid ladder that holds through this window ends almost entirely in tokens \
worth a fraction of what it paid — which the terminal-inventory columns state explicitly.";

#[allow(clippy::too_many_lines)] // One declaration assembled in the order its parts bind.
fn main() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let mint = flag(&arguments, "--mint").ok_or_else(usage)?;
    let words = flag(&arguments, "--hypothesis").ok_or_else(usage)?;
    let socket_root = flag(&arguments, "--socket-root").map(PathBuf::from);
    let polled_root = flag(&arguments, "--polled-root").map(PathBuf::from);
    if socket_root.is_none() && polled_root.is_none() {
        return Err(usage());
    }
    let declared_by = flag(&arguments, "--declared-by").unwrap_or_else(|| "ember".to_owned());
    let declared_at: i64 = parse(&arguments, "--declared-at-unix-ms", 1_787_600_000_000)?;
    let network_fee: u128 = parse(
        &arguments,
        "--network-fee-lamports",
        DEFAULT_NETWORK_FEE_LAMPORTS,
    )?;
    let schedule = FeeSchedule {
        lp: FeeBps::new(parse(&arguments, "--fee-lp-bps", 20)?)?,
        protocol: FeeBps::new(parse(&arguments, "--fee-protocol-bps", 5)?)?,
        creator: CreatorFee::Charged(FeeBps::new(parse(&arguments, "--fee-creator-bps", 5)?)?),
    };
    let chop_band_bps: u32 = parse(&arguments, "--chop-band-bps", 667)?;
    let row_fee_candidates: Vec<u32> = list_u32(&arguments, "--row-fee-candidates-bps")?
        .unwrap_or_else(|| vec![95, 30, 100, 120, 125]);
    let split_numerator: u32 = parse(&arguments, "--split-num", 1)?;
    let split_denominator: u32 = parse(&arguments, "--split-den", 2)?;
    let known = flag(&arguments, "--known-first")
        .or_else(|| (mint == DUCK_MINT).then(|| DUCK_PRIOR.to_owned()));
    let known = known.ok_or(
        "--known-first is required: a replay's rules are not blind, and this panel will not be \
         built without a statement of what its declarer already knew about this tape",
    )?;
    let out = flag(&arguments, "--out").map(PathBuf::from);

    let socket = socket_root
        .as_deref()
        .map(|root| load_socket_tape(root, &mint, schedule))
        .transpose()?;
    let polled = polled_root
        .as_deref()
        .map(|root| load_polled_tape(root, &mint, schedule, &row_fee_candidates))
        .transpose()?;
    let reconciliation = match (&socket, &polled) {
        (Some(socket), Some(polled)) => Some(reconcile(socket, polled)),
        _ => None,
    };
    // The socket tape carries the better decision clock; the polled tape stands in when the
    // socket recorder was refused.
    let tape = socket
        .as_ref()
        .or(polled.as_ref())
        .expect("one tape loaded");

    let costs = DeclaredFixedCosts {
        provenance: format!(
            "network fee of {network_fee} lamports per landed transaction, from the landed \
             PumpSwap sell in Study M0's fixture on 2026-08-21, charged once per would-walk; no \
             rent, because the associated token account is assumed already funded, which \
             flatters every cell equally"
        ),
        per_transaction_quote_atoms: network_fee,
        transactions: 2,
        flat_route_quote_atoms: 0,
        unrecovered_rent_quote_atoms: 0,
    };
    let axes = axes(&arguments, tape, &costs, chop_band_bps)?;
    let mut stated = vec![format!(
        "FEE SCHEDULE. No tape states a fee rate. This run declares lp {} bps, protocol {} bps, \
         creator {} bps on every state. For a polled tape the declaration is falsified by the \
         derivation itself: a wrong schedule fails to reproduce the rows' own legs to the atom.",
        schedule.lp.get(),
        schedule.protocol.get(),
        match schedule.creator {
            CreatorFee::Charged(rate) => rate.get(),
            CreatorFee::NotApplicable | CreatorFee::Unknown => 0,
        }
    )];
    stated.extend(tape.stated.clone());
    // When a second recording exists, its own declarations still belong in the panel: the
    // reconciliation block compares the two, and a reader must see what the other tape had to
    // declare to exist at all.
    if let (Some(socket_tape), Some(polled_tape)) = (&socket, &polled) {
        let secondary = if std::ptr::eq(tape, socket_tape) {
            polled_tape
        } else {
            socket_tape
        };
        stated.extend(secondary.stated.iter().map(|line| {
            format!(
                "FROM THE {} TAPE (reconciled above): {line}",
                secondary.kind
            )
        }));
    }
    let declaration = GridSweepDeclaration {
        panel_id: format!("grid-{}-{}", short(&mint), tape.kind),
        tape_id: tape.tape_id.clone(),
        tape_provenance: tape.provenance.clone(),
        tape_digest_sha256: tape.digest.clone(),
        mint: mint.clone(),
        venue: VenueBinding {
            venue: VenueKind::PumpSwapPool,
            venue_account: "not read: every state here is priced from the tape's own frames or \
                            derived from its own stated legs; no pool account was read"
                .to_owned(),
            binding: "the recorder was pointed at this mint's trade stream, and every retained \
                      row is a fill of it"
                .to_owned(),
        },
        hypothesis: DeclaredHypothesis {
            operator_words_verbatim: words,
            declared_by,
            declared_at_unix_ms: declared_at,
        },
        costs,
        base_decimals: PUMP_TOKEN_DECIMALS,
        quote_decimals: SOL_DECIMALS,
        what_was_known_about_this_tape: known,
        stated_but_not_in_the_tape: stated,
        coverage: tape.coverage.clone(),
        reconciliation,
        split_numerator,
        split_denominator,
    };
    let panel = GridSweepPanelV1::build(&declaration, &tape.frames, &axes)?;
    print!("{}", panel.render_text());
    if let Some(path) = out {
        std::fs::write(&path, panel.render_json())?;
        println!("wrote {}", path.display());
    }
    Ok(())
}

/// One loaded tape, whichever recorder produced it.
struct LoadedTape {
    kind: &'static str,
    tape_id: String,
    provenance: String,
    digest: String,
    frames: Vec<GridFrame>,
    coverage: TapeCoverage,
    /// Loader-measured declarations for the panel's stated-but-not-in-the-tape block.
    stated: Vec<String>,
    /// signature -> (event ms, base atoms), for two-source reconciliation.
    signatures: BTreeMap<String, (i64, u128)>,
}

// --- the sweep's axes, derived from measurements and stated priors, never bare numbers ----------

fn axes(
    arguments: &[String],
    tape: &LoadedTape,
    costs: &DeclaredFixedCosts,
    chop_band_bps: u32,
) -> Result<GridSweepAxes, Box<dyn Error>> {
    let clips = list_u128_sol(arguments, "--clips-sol")?
        .unwrap_or_else(|| vec![50_000_000, 100_000_000, 250_000_000]);
    let clip_reason = "0.25 SOL is the clip the venue hurdle was measured at moments before \
                       recording; 0.1 and 0.05 SOL probe whether amortizing the fixed cost over \
                       fewer atoms or shrinking traversal wins"
        .to_owned();
    // The spacing ladder is multiples of the venue's own measured structural floor at the
    // anchor state, spanning below it (so the flag mechanism is exercised, not asserted),
    // at it, and above it.
    let anchor = tape
        .frames
        .iter()
        .find_map(|frame| match frame {
            GridFrame::Event(event) => Some(event.state),
            GridFrame::Refused { .. } => None,
        })
        .ok_or_else(|| {
            let reasons: Vec<&str> = tape
                .frames
                .iter()
                .filter_map(|frame| match frame {
                    GridFrame::Refused { reason, .. } => Some(reason.as_str()),
                    GridFrame::Event(_) => None,
                })
                .take(3)
                .collect();
            format!(
                "the tape holds no evaluable event to anchor the axes at; the first refusals \
                 say why: {}",
                reasons.join(" | ")
            )
        })?;
    let middle_clip = clips[clips.len() / 2];
    let venue_bps = self_round_trip(&anchor, middle_clip, costs)?
        .all_in_cost
        .bps_ceil()?;
    let floor = u32::try_from(venue_bps.max(1)).unwrap_or(u32::MAX);
    let spacings = list_u32(arguments, "--spacings-bps")?.unwrap_or_else(|| {
        let mut ladder: Vec<u32> = [
            floor.div_ceil(2),
            floor,
            floor.saturating_mul(3).div_ceil(2),
            floor.saturating_mul(2),
            floor.saturating_mul(3),
            floor.saturating_mul(4),
        ]
        .into_iter()
        .collect();
        ladder.dedup();
        ladder
    });
    let spacing_reason = format!(
        "multiples 1/2, 1, 3/2, 2, 3, 4 of the {floor} bps all-in round-trip floor MEASURED at \
         this tape's anchor state for the {middle_clip}-atom clip — spanning below the floor (to \
         show the structural flag bite in the surface), at it, and above it. No spacing here is a \
         bare number; the whole axis moves with the venue."
    );
    let half_bands = list_u32(arguments, "--half-bands-bps")?.unwrap_or_else(|| {
        let mut ladder: Vec<u32> = [
            chop_band_bps.div_ceil(2),
            chop_band_bps,
            chop_band_bps.saturating_mul(2),
        ]
        .into_iter()
        .collect();
        ladder.dedup();
        ladder
    });
    let band_reason = format!(
        "1/2, 1, and 2 times the declared chop prior of {chop_band_bps} bps half-band (the \
         42k-48k USD market-cap chop Ember watched before declaring, ~±667 bps around its \
         middle). This is PRIOR KNOWLEDGE of this coin's morning, stated as such in the \
         known-first block, not a fitted number."
    );
    Ok(GridSweepAxes {
        spacings_bps: spacings,
        spacing_reason,
        half_bands_bps: half_bands,
        band_reason,
        clips_quote_atoms: clips,
        clip_reason,
    })
}

// --- socket tape --------------------------------------------------------------------------------

#[allow(clippy::too_many_lines)] // One loader: retained frames to grid events, in order.
fn load_socket_tape(
    root: &Path,
    mint: &str,
    schedule: FeeSchedule,
) -> Result<LoadedTape, Box<dyn Error>> {
    let store = SqliteStore::open(store_config(root, SOCKET_CATALOG_ID)?, StoreMode::ReadOnly)?;
    let verification = store.verify(VerifyDepth::Full)?;
    if verification.integrity != "ok" {
        return Err("the reopened socket catalog failed verification".into());
    }
    let source_id = DomainSourceId::new(SOCKET_SOURCE_ID)?;
    let Some(stored) = store.source_observations_as_known(&source_id, None, READBACK_LIMIT)? else {
        return Err("the socket catalog holds no observations".into());
    };
    if stored.truncated {
        return Err("the socket catalog holds more frames than this read-back asked for".into());
    }
    let mut raw: Vec<(u64, i64, Vec<u8>)> = Vec::new();
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
        raw.push((sequence, received, envelope.body.clone()));
    }
    raw.sort_by_key(|(sequence, _, _)| *sequence);
    let mut frames = Vec::new();
    let mut signatures = BTreeMap::new();
    let mut hasher = Sha256::new();
    let mut kept = 0_u32;
    for (ordinal, received, body) in &raw {
        let Ok(text) = core::str::from_utf8(body) else {
            continue;
        };
        let Ok(value) = serde_json::from_str::<Value>(text) else {
            continue;
        };
        if value.get("signature").is_none() || value["mint"].as_str() != Some(mint) {
            continue;
        }
        hasher.update(ordinal.to_be_bytes());
        hasher.update(received.to_be_bytes());
        hasher.update(body);
        kept += 1;
        if value["pool"].as_str() != Some("pump-amm") {
            frames.push(GridFrame::Refused {
                ordinal: *ordinal,
                event_unix_ms: *received,
                reason: format!(
                    "the frame states pool {:?}; this grid run prices only pump-amm states",
                    value["pool"].as_str().unwrap_or("<absent>")
                ),
            });
            continue;
        }
        let quote = frame_reserve(text, &value, "solInPool", SOL_DECIMALS);
        let base = frame_reserve(text, &value, "tokensInPool", PUMP_TOKEN_DECIMALS);
        let (Some(quote), Some(base)) = (quote, base) else {
            frames.push(GridFrame::Refused {
                ordinal: *ordinal,
                event_unix_ms: *received,
                reason: "the frame states no reconstructable solInPool / tokensInPool pair"
                    .to_owned(),
            });
            continue;
        };
        if quote == 0 || base == 0 {
            frames.push(GridFrame::Refused {
                ordinal: *ordinal,
                event_unix_ms: *received,
                reason: "the frame states a zero reserve".to_owned(),
            });
            continue;
        }
        if let Some(signature) = value["signature"].as_str() {
            let token_atoms = value["tokenAmount"]
                .as_f64()
                .and_then(|_| literal_atoms(text, "tokenAmount", PUMP_TOKEN_DECIMALS))
                .unwrap_or(0);
            signatures.insert(signature.to_owned(), (*received, token_atoms));
        }
        frames.push(GridFrame::Event(GridTapeEvent {
            ordinal: *ordinal,
            event_unix_ms: *received,
            available_unix_ms: *received,
            state: ExactCurveState {
                formula: VenueFormula::PumpSwapExactQuoteIn,
                base_atoms: base,
                effective_quote_atoms: quote + SOCKET_UNATTRIBUTED_QUOTE_SIDE_ATOMS,
                schedule,
            },
        }));
    }
    Ok(LoadedTape {
        kind: "socket",
        tape_id: format!("{SOCKET_CATALOG_ID}:{}", root.display()),
        provenance: format!(
            "reopened the durable socket catalog at {} read-only and verified it in full; every \
             frame is the exact bytes a coin_tape_live record run retained, in catalog order; \
             the digest covers exactly this mint's frames",
            root.display()
        ),
        digest: hex(hasher),
        frames,
        coverage: TapeCoverage {
            pages_read: kept,
            duplicates_dropped: 0,
            gaps: Vec::new(),
            availability_statement: "socket tape: the recorder held a live subscription, so each \
                                     event's availability clock IS its receive instant; \
                                     availability delay is zero by construction and the haircut \
                                     for it prices only the chain-to-receipt landing delay. A \
                                     socket still states nothing about frames it never received."
                .to_owned(),
        },
        stated: vec![format!(
            "RESERVE COMPOSITION (socket frames). A pump-amm frame states the pool's quote VAULT \
             balance; the deployed step uses that balance plus the unattributed term this \
             codebase locates at pool byte 245, declared here at \
             {SOCKET_UNATTRIBUTED_QUOTE_SIDE_ATOMS} atoms (the value 29 of 42 surveyed pools \
             carry). The polled tape needs no such declaration, and where the two tapes overlap \
             the reconciliation block is the cross-check."
        )],
        signatures,
    })
}

/// Recovers one reserve from the frame's own decimal literal, cross-checked against the parser's
/// float so a mis-scanned literal cannot pass silently.
fn frame_reserve(text: &str, value: &Value, key: &str, decimals: u8) -> Option<u128> {
    let atoms = literal_atoms(text, key, decimals)?;
    let stated = value[key].as_f64()?;
    let scale = 10_f64.powi(i32::from(decimals));
    #[allow(clippy::cast_precision_loss)] // A cross-check on the scan, not the arithmetic.
    let recovered = atoms as f64 / scale;
    ((recovered - stated).abs() <= stated.abs() * 1e-9).then_some(atoms)
}

fn literal_atoms(text: &str, key: &str, decimals: u8) -> Option<u128> {
    let needle = format!("\"{key}\":");
    let start = text.find(&needle)? + needle.len();
    let rest = &text[start..];
    let end = rest
        .find(|character: char| !matches!(character, '0'..='9' | '.' | '+' | '-' | 'e' | 'E'))
        .unwrap_or(rest.len());
    (end > 0)
        .then(|| atoms_from_decimal_literal(&rest[..end], decimals).ok())
        .flatten()
        .map(|recovered| recovered.atoms)
}

// --- polled tape --------------------------------------------------------------------------------

struct PolledRow {
    slot_index_id: String,
    signature: String,
    event_unix_ms: i64,
    available_unix_ms: i64,
    direction: TradeDirection,
    trader_quote_atoms: u128,
    base_atoms: u128,
    price_literal: String,
    program: String,
}

/// The declared curve-leg readings of one row, in precedence order.
type RowCandidates = Vec<(String, CurveLegs)>;

/// Resolves one row's stated quote into every declared curve-leg reading, in precedence order,
/// for the chain reconstructor to pick from by exact reproduction.
///
/// MEASURED 2026-08-24 on the Duck's own polled pages: most buy rows state the CURVE leg (the
/// raw consideration, no fee), a minority state the trader's total with a fee on top, and sell
/// rows state the trader's receipt with a fee deducted — and the FEE ITSELF varies row by row
/// (95 bps and 30 bps both measured on one tape, plausibly creator-fee-exempt routes beside
/// charged ones, and tier moves as the market cap collapses). Every declared candidate fee is
/// tried; the chain's exact floor windows are sharp at near-atom scale, so a wrong reading does
/// not reproduce and cannot be silently picked.
#[allow(clippy::too_many_lines)] // Every declared reading of one row, listed in one place.
fn prepare_row(
    row: &PolledRow,
    schedule: FeeSchedule,
    row_fee_candidates: &[u32],
) -> Result<(StatedPostPrice, RowCandidates), String> {
    if row.program != "pump_amm" {
        return Err(format!(
            "states program {:?}; this run derives only pump_amm states",
            row.program
        ));
    }
    if row.trader_quote_atoms == 0 || row.base_atoms == 0 {
        return Err("states a zero leg; a fill that moved nothing pins nothing".to_owned());
    }
    let price = stated_post_price(&row.price_literal, SOL_DECIMALS, PUMP_TOKEN_DECIMALS)
        .map_err(|refusal| refusal.to_string())?;
    let legs = |raw: u128, lp: u128| CurveLegs {
        direction: row.direction,
        raw_quote_atoms: raw,
        lp_retained_atoms: lp,
        base_atoms: row.base_atoms,
    };
    let lp_bps = u128::from(schedule.lp.get());
    let declared_total = lp_bps
        + u128::from(schedule.protocol.get())
        + match schedule.creator {
            CreatorFee::Charged(rate) => u128::from(rate.get()),
            CreatorFee::NotApplicable | CreatorFee::Unknown => 0,
        };
    let mut candidates: RowCandidates = Vec::new();
    let push = |candidates: &mut RowCandidates, name: String, held: CurveLegs| {
        if candidates
            .iter()
            .all(|(_, existing)| existing.raw_quote_atoms != held.raw_quote_atoms)
        {
            candidates.push((name, held));
        }
    };
    match row.direction {
        TradeDirection::Buy => {
            push(
                &mut candidates,
                "curve_leg_stated".to_owned(),
                legs(row.trader_quote_atoms, 0),
            );
            for &fee_bps in row_fee_candidates {
                let fee = u128::from(fee_bps);
                let fee_of = |raw: u128| (raw * fee).div_ceil(10_000);
                let centre = row.trader_quote_atoms * 10_000 / (10_000 + fee);
                for raw in centre.saturating_sub(4)..=centre.saturating_add(4) {
                    if raw > 0 && raw + fee_of(raw) == row.trader_quote_atoms {
                        push(
                            &mut candidates,
                            format!("trader_leg_fee_{fee_bps}_on_top"),
                            legs(raw, 0),
                        );
                    }
                }
            }
            // The declared schedule's own deployed split of a trader-leg total.
            let lp = (row.trader_quote_atoms * lp_bps).div_ceil(10_000);
            if let Some(after_lp) = row.trader_quote_atoms.checked_sub(lp) {
                let protocol = (after_lp * u128::from(schedule.protocol.get())).div_ceil(10_000);
                let creator = match schedule.creator {
                    CreatorFee::Charged(rate) => {
                        (after_lp * u128::from(rate.get())).div_ceil(10_000)
                    }
                    CreatorFee::NotApplicable | CreatorFee::Unknown => 0,
                };
                if let Some(raw) = after_lp
                    .checked_sub(protocol)
                    .and_then(|value| value.checked_sub(creator))
                    && raw > 0
                {
                    push(
                        &mut candidates,
                        "trader_leg_declared_schedule".to_owned(),
                        legs(raw, lp),
                    );
                }
            }
        }
        TradeDirection::Sell => {
            for &fee_bps in row_fee_candidates {
                let fee = u128::from(fee_bps);
                if fee >= 10_000 {
                    continue;
                }
                let fee_of = |raw: u128| (raw * fee).div_ceil(10_000);
                let centre = row.trader_quote_atoms * 10_000 / (10_000 - fee);
                for raw in centre.saturating_sub(4)..=centre.saturating_add(4) {
                    if raw > fee_of(raw) && raw - fee_of(raw) == row.trader_quote_atoms {
                        push(
                            &mut candidates,
                            format!("trader_leg_fee_{fee_bps}_deducted"),
                            legs(raw, 0),
                        );
                    }
                }
            }
            push(
                &mut candidates,
                "curve_leg_stated".to_owned(),
                legs(row.trader_quote_atoms, 0),
            );
            if declared_total < 10_000 {
                let centre = row.trader_quote_atoms * 10_000 / (10_000 - declared_total);
                for raw in centre.saturating_sub(6)..=centre.saturating_add(6) {
                    let lp = (raw * lp_bps).div_ceil(10_000);
                    let protocol = (raw * u128::from(schedule.protocol.get())).div_ceil(10_000);
                    let creator = match schedule.creator {
                        CreatorFee::Charged(rate) => {
                            (raw * u128::from(rate.get())).div_ceil(10_000)
                        }
                        CreatorFee::NotApplicable | CreatorFee::Unknown => 0,
                    };
                    if raw > lp + protocol + creator
                        && raw - lp - protocol - creator == row.trader_quote_atoms
                        && candidates
                            .iter()
                            .all(|(_, held)| held.raw_quote_atoms != raw)
                    {
                        push(
                            &mut candidates,
                            "trader_leg_declared_schedule".to_owned(),
                            legs(raw, lp),
                        );
                    }
                }
            }
        }
    }
    Ok((price, candidates))
}

#[allow(clippy::too_many_lines)] // One loader: pages to deduplicated, derived, falsified events.
fn load_polled_tape(
    root: &Path,
    mint: &str,
    schedule: FeeSchedule,
    row_fee_candidates: &[u32],
) -> Result<LoadedTape, Box<dyn Error>> {
    let store = SqliteStore::open(store_config(root, POLLED_CATALOG_ID)?, StoreMode::ReadOnly)?;
    let verification = store.verify(VerifyDepth::Full)?;
    if verification.integrity != "ok" {
        return Err("the reopened polled catalog failed verification".into());
    }
    let source_id = DomainSourceId::new(POLLED_SOURCE_ID)?;
    let Some(stored) = store.source_observations_as_known(&source_id, None, READBACK_LIMIT)? else {
        return Err("the polled catalog holds no observations".into());
    };
    if stored.truncated {
        return Err("the polled catalog holds more pages than this read-back asked for".into());
    }
    // Pages in poll order: the body observation of each acquisition, with its receive instant.
    let mut pages: Vec<(i64, Vec<u8>)> = Vec::new();
    let mut foreign_pages = 0_u32;
    for observation in &stored.observations {
        let id = observation.observation_id.as_str();
        if id.ends_with(":attempt") {
            // The envelope names the mint the page was requested for; a page for another mint
            // must not silently join this tape.
            if let Ok(envelope) = serde_json::from_slice::<Value>(&observation.payload)
                && let Some(requested) = envelope["resolvedPublicPath"]["mint"].as_str()
                && requested != mint
            {
                foreign_pages += 1;
            }
            continue;
        }
        if !id.ends_with(":body") {
            continue;
        }
        let received = i64::try_from(
            observation.received_at.as_datetime().unix_timestamp_nanos() / 1_000_000,
        )?;
        pages.push((received, observation.payload.clone()));
    }
    if foreign_pages > 0 {
        return Err(format!(
            "{foreign_pages} retained pages were requested for a different mint; this state dir \
             does not hold one coin's tape"
        )
        .into());
    }
    pages.sort_by_key(|(received, _)| *received);
    let mut hasher = Sha256::new();
    let mut rows: BTreeMap<String, PolledRow> = BTreeMap::new();
    let mut duplicates = 0_u32;
    let mut gaps: Vec<String> = Vec::new();
    let mut gap_starts: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
    let mut previous_page: Option<(String, String)> = None; // (oldest, newest) keys of the page
    let mut poll_receipts: Vec<i64> = Vec::new();
    for (index, (received, body)) in pages.iter().enumerate() {
        hasher.update(received.to_be_bytes());
        hasher.update(body);
        poll_receipts.push(*received);
        let value: Value = serde_json::from_slice(body)?;
        let Some(trades) = value["trades"].as_array() else {
            gaps.push(format!(
                "page {index} carries no trades array and its coverage is unknown"
            ));
            continue;
        };
        if trades.is_empty() {
            previous_page = None;
            continue;
        }
        let key_of = |row: &Value| {
            row["slotIndexId"]
                .as_str()
                .map(str::to_owned)
                .ok_or("a trade row carries no slotIndexId")
        };
        let newest = key_of(&trades[0])?;
        let oldest = key_of(&trades[trades.len() - 1])?;
        if let Some((_, previous_newest)) = &previous_page
            && oldest > *previous_newest
        {
            gaps.push(format!(
                "between the page received at {received} ms and the one before it, retained \
                 coverage is provably discontinuous: the newer page's oldest fill ({oldest}) is \
                 newer than the older page's newest ({previous_newest}). The coin printed more \
                 fills in one poll interval than the page limit holds; how many is unknowable \
                 from this tape, and nothing was interpolated."
            ));
            gap_starts.insert(oldest.clone());
        }
        previous_page = Some((oldest, newest));
        for row in trades {
            let slot_index_id = key_of(row)?;
            if rows.contains_key(&slot_index_id) {
                duplicates += 1;
                continue; // first page holding the fill fixes its availability clock
            }
            let row_name = slot_index_id.clone();
            let text = move |key: &str| {
                row[key]
                    .as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| format!("row {row_name} states no {key}"))
            };
            let timestamp = time::OffsetDateTime::parse(
                &text("timestamp")?,
                &time::format_description::well_known::Rfc3339,
            )?;
            let event_unix_ms = i64::try_from(timestamp.unix_timestamp_nanos() / 1_000_000)?;
            let direction = match text("type")?.as_str() {
                "buy" => TradeDirection::Buy,
                "sell" => TradeDirection::Sell,
                other => {
                    rows.insert(
                        slot_index_id.clone(),
                        PolledRow {
                            slot_index_id,
                            signature: text("tx").unwrap_or_default(),
                            event_unix_ms,
                            available_unix_ms: *received,
                            direction: TradeDirection::Buy,
                            trader_quote_atoms: 0,
                            base_atoms: 0,
                            price_literal: String::new(),
                            program: format!("unknown trade type {other:?}"),
                        },
                    );
                    continue;
                }
            };
            let quote = atoms_from_decimal_literal(&text("quoteAmount")?, SOL_DECIMALS)
                .map_or(0, |recovered| recovered.atoms);
            let base = atoms_from_decimal_literal(&text("baseAmount")?, PUMP_TOKEN_DECIMALS)
                .map_or(0, |recovered| recovered.atoms);
            rows.insert(
                slot_index_id.clone(),
                PolledRow {
                    slot_index_id,
                    signature: text("tx")?,
                    event_unix_ms,
                    available_unix_ms: *received,
                    direction,
                    trader_quote_atoms: quote,
                    base_atoms: base,
                    price_literal: text("priceSol")?,
                    program: text("program")?,
                },
            );
        }
    }
    // slotIndexId is fixed-width lexicographic, so BTreeMap order IS chain order.
    let ordered: Vec<&PolledRow> = rows.values().collect();
    let mut signatures = BTreeMap::new();
    let mut chain_input: Vec<ChainRow> = Vec::new();
    let mut chain_source: Vec<usize> = Vec::new();
    let mut prepare_refusals: BTreeMap<usize, String> = BTreeMap::new();
    let mut force_gap = false;
    for (position, row) in ordered.iter().enumerate() {
        signatures.insert(row.signature.clone(), (row.event_unix_ms, row.base_atoms));
        match prepare_row(row, schedule, row_fee_candidates) {
            Ok((price, candidates)) => {
                chain_input.push(ChainRow {
                    // A row this loader could not read still moved the pool, so the chain may
                    // not be evolved across it any more than across a page gap.
                    gap_before: force_gap || gap_starts.contains(&row.slot_index_id),
                    price,
                    candidates,
                });
                chain_source.push(position);
                force_gap = false;
            }
            Err(reason) => {
                prepare_refusals.insert(position, reason);
                force_gap = true;
            }
        }
    }
    let chain = reconstruct_pumpswap_chain(&chain_input, schedule);
    let mut outcomes: Vec<Option<&ChainRowState>> = vec![None; ordered.len()];
    for (chain_index, state) in chain.rows.iter().enumerate() {
        outcomes[chain_source[chain_index]] = Some(state);
    }
    let mut frames = Vec::new();
    let mut derive_refusals = 0_u32;
    let mut conventions: BTreeMap<String, u32> = BTreeMap::new();
    for (position, row) in ordered.iter().enumerate() {
        let ordinal = u64::try_from(position)?;
        match outcomes[position] {
            Some(ChainRowState::Anchored {
                convention, post, ..
            }) => {
                *conventions.entry(convention.clone()).or_insert(0) += 1;
                frames.push(GridFrame::Event(GridTapeEvent {
                    ordinal,
                    event_unix_ms: row.event_unix_ms,
                    available_unix_ms: row.available_unix_ms.max(row.event_unix_ms),
                    state: *post,
                }));
            }
            Some(ChainRowState::Unresolved { reason }) => {
                derive_refusals += 1;
                frames.push(GridFrame::Refused {
                    ordinal,
                    event_unix_ms: row.event_unix_ms,
                    reason: format!(
                        "row {} ({}) supports no state: {reason}",
                        row.slot_index_id,
                        row.direction.label()
                    ),
                });
            }
            None => {
                derive_refusals += 1;
                frames.push(GridFrame::Refused {
                    ordinal,
                    event_unix_ms: row.event_unix_ms,
                    reason: format!(
                        "row {} ({}) supports no state: {}",
                        row.slot_index_id,
                        row.direction.label(),
                        prepare_refusals
                            .get(&position)
                            .map_or("unreadable row", String::as_str)
                    ),
                });
            }
        }
    }
    let convention_counts = conventions
        .iter()
        .map(|(name, count)| format!("{name} x{count}"))
        .collect::<Vec<_>>()
        .join(", ");
    let mut cadences: Vec<i64> = poll_receipts
        .windows(2)
        .map(|pair| pair[1] - pair[0])
        .collect();
    cadences.sort_unstable();
    let median_cadence = cadences
        .get(cadences.len() / 2)
        .copied()
        .unwrap_or_default();
    Ok(LoadedTape {
        kind: "polled",
        tape_id: format!("{POLLED_CATALOG_ID}:{}", root.display()),
        provenance: format!(
            "reopened the durable product-read catalog at {} read-only and verified it in full; \
             every page is the exact response bytes one bounded trades read retained through \
             source admission; the digest covers the retained pages in poll order",
            root.display()
        ),
        digest: hex(hasher),
        frames,
        coverage: TapeCoverage {
            pages_read: u32::try_from(pages.len()).unwrap_or(u32::MAX),
            duplicates_dropped: duplicates,
            gaps,
            availability_statement: format!(
                "polled tape: each event's availability clock is the receive instant of the \
                 FIRST retained page holding its slotIndexId — the poll cadence (median \
                 {median_cadence} ms here) is the floor under how fast any rule could really \
                 have reacted, and each fill's haircut carries its own measured delay. Event \
                 time is the provider's own per-fill timestamp at one-second resolution; event \
                 order is slotIndexId, the chain's own order."
            ),
        },
        stated: vec![
            format!(
                "DERIVED RESERVES. A trades page states no reserve. Every state here is DERIVED \
                 from its row's own three stated legs (quoteAmount, baseAmount, priceSol) by \
                 exact inversion of the deployed arithmetic, and {derive_refusals} rows refused \
                 derivation rather than accept a guess."
            ),
            format!(
                "ROW QUOTE CONVENTION, measured not assumed. The provider mixes what \
                 quoteAmount means row by row; each row was resolved by exact reproduction \
                 against declared candidate fees {row_fee_candidates:?} bps: \
                 {convention_counts}. \
                 A row no candidate reproduces is a refusal above."
            ),
            format!("CHAIN RECONSTRUCTION. {}", chain.statement),
        ],
        signatures,
    })
}

// --- two-source reconciliation ------------------------------------------------------------------

fn reconcile(socket: &LoadedTape, polled: &LoadedTape) -> TwoSourceReconciliationV1 {
    let clock = |tape: &LoadedTape| {
        let times: Vec<i64> = tape.signatures.values().map(|(ms, _)| *ms).collect();
        (
            times.iter().copied().min().unwrap_or(0),
            times.iter().copied().max().unwrap_or(0),
        )
    };
    let (socket_first, socket_last) = clock(socket);
    let (polled_first, polled_last) = clock(polled);
    let start = socket_first.max(polled_first);
    let end = socket_last.min(polled_last);
    let inside = |ms: i64| ms >= start && ms <= end;
    let mut matched = 0_u32;
    let mut socket_only = 0_u32;
    let mut polled_only = 0_u32;
    let mut base_disagreements = 0_u32;
    for (signature, (ms, socket_base)) in &socket.signatures {
        if !inside(*ms) {
            continue;
        }
        match polled.signatures.get(signature) {
            None => socket_only += 1,
            Some((_, polled_base)) => {
                matched += 1;
                if socket_base.abs_diff(*polled_base) > 1 {
                    base_disagreements += 1;
                }
            }
        }
    }
    for (signature, (ms, _)) in &polled.signatures {
        if inside(*ms) && !socket.signatures.contains_key(signature) {
            polled_only += 1;
        }
    }
    let statement = format!(
        "two independent recordings of the same market, reconciled fill-by-fill by transaction \
         signature over their overlapping window: {matched} fills appear in both, {socket_only} \
         only on the socket, {polled_only} only in the polled pages, and {base_disagreements} \
         matched fills disagree on the base leg beyond one atom. The two tapes keep different \
         clocks (socket receive vs provider fill timestamp), so a fill within a few seconds of \
         either edge can land on one side only for clock reasons; fills missing DEEP inside the \
         overlap are the finding. This provider has already been measured once acknowledging a \
         subscription while delivering nothing, so a stated reconciliation replaces trust."
    );
    TwoSourceReconciliationV1 {
        socket_tape_id: socket.tape_id.clone(),
        polled_tape_id: polled.tape_id.clone(),
        overlap_start_unix_ms: start,
        overlap_end_unix_ms: end,
        matched_by_signature: matched,
        socket_only,
        polled_only,
        base_leg_disagreements: base_disagreements,
        statement,
    }
}

// --- plumbing -----------------------------------------------------------------------------------

fn store_config(root: &Path, catalog_id: &str) -> Result<StoreConfig, Box<dyn Error>> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 4 * 1024 * 1024,
        busy_timeout: Duration::from_secs(5),
        catalog_id: StableString::new(catalog_id)?,
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 64 * 1024 * 1024,
    })
}

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

fn short(mint: &str) -> String {
    mint.chars().take(8).collect()
}

fn usage() -> Box<dyn Error> {
    "usage: grid_tape_replay --mint <address> [--socket-root <dir>] [--polled-root <dir>] \
     --hypothesis \"<words>\" [--known-first \"<prior>\"] [--out <path>] [--declared-by ember] \
     [--declared-at-unix-ms n] [--network-fee-lamports 7422] [--fee-lp-bps 20] \
     [--fee-protocol-bps 5] [--fee-creator-bps 5] [--row-fee-bps 95] [--spacings-bps a,b] \
     [--half-bands-bps a,b] [--clips-sol 0.05,0.25] [--chop-band-bps 667] [--split-num 1] \
     [--split-den 2]; at least one root is required"
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

fn list_u32(arguments: &[String], name: &str) -> Result<Option<Vec<u32>>, Box<dyn Error>> {
    let Some(value) = flag(arguments, name) else {
        return Ok(None);
    };
    let mut out = Vec::new();
    for part in value.split(',') {
        out.push(
            part.trim()
                .parse::<u32>()
                .map_err(|error| format!("invalid {name} entry {part:?}: {error}"))?,
        );
    }
    Ok(Some(out))
}

fn list_u128_sol(arguments: &[String], name: &str) -> Result<Option<Vec<u128>>, Box<dyn Error>> {
    let Some(value) = flag(arguments, name) else {
        return Ok(None);
    };
    let mut out = Vec::new();
    for part in value.split(',') {
        let recovered = atoms_from_decimal_literal(part.trim(), SOL_DECIMALS)
            .map_err(|error| format!("invalid {name} entry {part:?}: {error}"))?;
        if recovered.atoms == 0 {
            return Err(format!("{name} entry {part:?} is zero").into());
        }
        out.push(recovered.atoms);
    }
    Ok(Some(out))
}
