//! Portfolio truth as a pure derivation from one durable catalog.
//!
//! This binary opens a catalog read-only, walks the wallet sweep observations it already holds,
//! and derives one `PortfolioStatementV1`: per-mint holdings in raw atoms with the exact
//! observations and durable commits behind every number, labelled price objects where the catalog
//! holds any, and a coverage section that names what the observations cannot say. It performs no
//! network I/O, writes nothing, and never renders an absent record as a zero.

use std::{collections::BTreeMap, error::Error, path::Path, time::Duration};

use joshi_accounting::portfolio::{
    AssetRef, BalanceEventV1, CatalogCutoff, ChainContinuity, ChainHeadRef, DlmmPositionLineV1,
    HoldingV1, LegInventory, NamedAbsence, ObservationRef, OpeningInventory, PortfolioInput,
    PortfolioStatementV1, PriceStatus, SignaturePageCoverage, derive_statement,
};
use joshi_domain::{ObservationId, SourceId, StableString, WireU64};
use joshi_sources::{MeteoraPositionV2, read_account_info};
use joshi_store::{DurableSourceObservation, SqliteStore, StoreConfig, StoreMode};
use joshi_wallet_source::{
    AcquisitionResponseContext, AcquisitionSurface, Commitment, PublicKey, RawTransactionFact,
    StoredLocatorClass, balance_events_for_wallet, chain_head_slot, classify_locator,
    normalize_stored_body, parse_retained_envelope, signature_page_entries,
};
use time::OffsetDateTime;

const DEFAULT_SOURCE: &str = "helius.http.solana.v1";
const DEFAULT_LIMIT: usize = 10_000;

struct Options {
    catalog: String,
    wallet: PublicKey,
    sources: Vec<String>,
    limit: usize,
    json: bool,
    /// Operator-supplied display labels per mint. Display only; never part of the statement.
    labels: BTreeMap<String, String>,
}

fn usage() -> Box<dyn Error> {
    "usage: joshi-portfolio --catalog <dir> --wallet <pubkey> [--source <id>]... \
     [--limit <n>] [--label <mint>=<name>]... [--json]"
        .into()
}

impl Options {
    fn parse(arguments: &[String]) -> Result<Self, Box<dyn Error>> {
        let mut catalog = None;
        let mut wallet = None;
        let mut sources = Vec::new();
        let mut limit = DEFAULT_LIMIT;
        let mut json = false;
        let mut labels = BTreeMap::new();
        let mut cursor = arguments.iter();
        while let Some(flag) = cursor.next() {
            match flag.as_str() {
                "--catalog" => catalog = Some(cursor.next().ok_or_else(usage)?.clone()),
                "--wallet" => {
                    wallet = Some(PublicKey::new(cursor.next().ok_or_else(usage)?.clone())?);
                }
                "--source" => sources.push(cursor.next().ok_or_else(usage)?.clone()),
                "--limit" => limit = cursor.next().ok_or_else(usage)?.parse()?,
                "--label" => {
                    let raw = cursor.next().ok_or_else(usage)?;
                    let (mint, name) = raw.split_once('=').ok_or_else(usage)?;
                    labels.insert(mint.to_owned(), name.to_owned());
                }
                "--json" => json = true,
                _ => return Err(usage()),
            }
        }
        if sources.is_empty() {
            sources.push(DEFAULT_SOURCE.to_owned());
        }
        Ok(Self {
            catalog: catalog.ok_or_else(usage)?,
            wallet: wallet.ok_or_else(usage)?,
            sources,
            limit,
            json,
            labels,
        })
    }
}

fn catalog_config(root: &Path) -> Result<StoreConfig, Box<dyn Error>> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: StableString::new("joshi-portfolio-readback")?,
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    })
}

fn main() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let options = Options::parse(&arguments)?;
    let store = SqliteStore::open(
        catalog_config(Path::new(&options.catalog))?,
        StoreMode::ReadOnly,
    )?;
    let statement = derive_from_catalog(&store, &options)?;
    if options.json {
        println!("{}", serde_json::to_string_pretty(&statement)?);
    } else {
        print!("{}", render(&statement, &options.labels));
    }
    Ok(())
}

/// One retained transaction fact plus the stored observation it was read back from.
struct ObservedFact {
    fact: RawTransactionFact,
    provenance: ObservationRef,
}

#[allow(clippy::too_many_lines)] // One derivation keeps its coverage accounting in one place.
fn derive_from_catalog(
    store: &SqliteStore,
    options: &Options,
) -> Result<PortfolioStatementV1, Box<dyn Error>> {
    let mut cutoff: Option<CatalogCutoff> = None;
    let mut facts: Vec<ObservedFact> = Vec::new();
    let mut pages: Vec<(ObservationRef, Vec<joshi_wallet_source::SignaturePageEntry>)> = Vec::new();
    let mut chain_head: Option<ChainHeadRef> = None;
    let mut positions: Vec<DlmmPositionLineV1> = Vec::new();
    let mut notes: Vec<StableString> = Vec::new();
    let mut extra_absences: Vec<NamedAbsence> = Vec::new();
    let mut unrecognized = 0_u64;
    let mut account_reads_not_positions = 0_u64;

    for source in &options.sources {
        let source_id = SourceId::new(source.as_str())?;
        let Some(observations) =
            store.source_observations_as_known(&source_id, None, options.limit)?
        else {
            continue;
        };
        if observations.truncated {
            notes.push(StableString::new(format!(
                "source {source} holds more observations than the read limit {}; \
                 this statement is derived from the first {} only",
                options.limit,
                observations.observations.len()
            ))?);
        }
        let candidate = CatalogCutoff {
            commit_seq: observations.through_commit_seq,
            committed_at: observations.through_committed_at,
        };
        if cutoff
            .as_ref()
            .is_none_or(|existing| existing.commit_seq < candidate.commit_seq)
        {
            cutoff = Some(candidate);
        }
        for observation in &observations.observations {
            read_observation(
                observation,
                options,
                &mut facts,
                &mut pages,
                &mut chain_head,
                &mut positions,
                &mut notes,
                &mut unrecognized,
                &mut account_reads_not_positions,
            )?;
        }
    }

    let cutoff = cutoff.ok_or("no observations found for the requested sources")?;

    // Balance events, one per boundary transition, each citing its stored observation.
    let mut balance_events: Vec<BalanceEventV1> = Vec::new();
    for observed in &facts {
        balance_events.extend(balance_events_for_wallet(
            &observed.fact,
            &options.wallet,
            &observed.provenance,
        )?);
    }

    // Page coverage: which listed signatures have a retained transaction observation.
    let fetched: std::collections::BTreeSet<&str> = facts
        .iter()
        .map(|observed| observed.fact.transaction.signature.as_str())
        .collect();
    let signature_pages = pages
        .into_iter()
        .map(|(provenance, entries)| {
            let listed = u64::try_from(entries.len()).unwrap_or(u64::MAX);
            let unfetched: Vec<StableString> = entries
                .iter()
                .filter(|entry| !fetched.contains(entry.signature.as_str()))
                .map(|entry| StableString::new(entry.signature.as_str()))
                .collect::<Result<_, _>>()?;
            let fetched_count =
                listed.saturating_sub(u64::try_from(unfetched.len()).unwrap_or(u64::MAX));
            Ok(SignaturePageCoverage {
                provenance,
                listed,
                fetched: fetched_count,
                unfetched_signatures: unfetched,
            })
        })
        .collect::<Result<Vec<_>, Box<dyn Error>>>()?;

    notes.push(StableString::new(
        "transaction facts are read back at a 'confirmed' commitment floor; the sweep's \
         requested commitment is not retained in the catalog",
    )?);
    if unrecognized > 0 {
        notes.push(StableString::new(format!(
            "{unrecognized} retained observation(s) carry a locator this reader does not \
             classify; they contributed nothing to this statement"
        ))?);
    }
    if account_reads_not_positions > 0 {
        notes.push(StableString::new(format!(
            "{account_reads_not_positions} retained account-read observation(s) did not decode \
             as DLMM positions and contributed nothing to this statement"
        ))?);
    }
    for page in &signature_pages {
        if !page.unfetched_signatures.is_empty() {
            extra_absences.push(NamedAbsence {
                name: StableString::new("unfetched_page_signatures")?,
                why: StableString::new(format!(
                    "{} of {} signatures on the observed page have no retained transaction \
                     observation; balances are explained only insofar as the fetched \
                     transactions chain contiguously",
                    page.unfetched_signatures.len(),
                    page.listed
                ))?,
            });
        }
    }

    let input = PortfolioInput {
        wallet: options.wallet.domain_account_id()?,
        catalog_cutoff: cutoff,
        balance_events,
        prices: Vec::new(),
        positions,
        provider_assertions: Vec::new(),
        signature_pages,
        chain_head,
        extra_absences,
        notes,
    };
    Ok(derive_statement(input)?)
}

#[allow(clippy::too_many_arguments)] // One observation dispatch touches every accumulator once.
fn read_observation(
    observation: &DurableSourceObservation,
    options: &Options,
    facts: &mut Vec<ObservedFact>,
    pages: &mut Vec<(ObservationRef, Vec<joshi_wallet_source::SignaturePageEntry>)>,
    chain_head: &mut Option<ChainHeadRef>,
    positions: &mut Vec<DlmmPositionLineV1>,
    notes: &mut Vec<StableString>,
    unrecognized: &mut u64,
    account_reads_not_positions: &mut u64,
) -> Result<(), Box<dyn Error>> {
    let envelope = match parse_retained_envelope(&observation.payload) {
        Ok(envelope) => envelope,
        Err(error) => {
            notes.push(StableString::new(format!(
                "observation {} could not be read back ({error}); it stays retained and \
                 contributes nothing here",
                observation.observation_id
            ))?);
            return Ok(());
        }
    };
    let provenance = ObservationRef {
        observation_id: ObservationId::new(observation.observation_id.as_str())?,
        commit_seq: observation.commit_seq,
    };
    let class = observation
        .source_locator_redacted
        .as_deref()
        .map_or(StoredLocatorClass::Unrecognized, classify_locator);
    match class {
        StoredLocatorClass::WalletSurface(surface) => {
            if surface == AcquisitionSurface::SolanaGetSignaturesForAddress
                && let Some(entries) = signature_page_entries(&envelope.body)
            {
                pages.push((provenance.clone(), entries));
            }
            let context = AcquisitionResponseContext {
                surface,
                scope_ids: vec![StableString::new(format!(
                    "portfolio:{}",
                    options.wallet.as_str()
                ))?],
                requested_public_keys: vec![options.wallet.clone()],
                mint_filter: None,
                commitment: Commitment::Confirmed,
                available_at: observation.available_at,
                cursor_before: None,
                coverage_gap_ids: Vec::new(),
                coverage_ids: Vec::new(),
                transaction_versions: Vec::new(),
            };
            let batch = normalize_stored_body(
                &envelope.body,
                ObservationId::new(observation.observation_id.as_str())?,
                &context,
            )?;
            for fact in batch.raw_transactions {
                facts.push(ObservedFact {
                    fact,
                    provenance: provenance.clone(),
                });
            }
        }
        StoredLocatorClass::ChainSlot => {
            if let Some(slot) = chain_head_slot(&envelope.body)
                && chain_head
                    .as_ref()
                    .is_none_or(|existing| existing.slot.get() < slot)
            {
                *chain_head = Some(ChainHeadRef {
                    slot: WireU64::new(slot),
                    provenance,
                });
            }
        }
        StoredLocatorClass::AccountRead => {
            // The response does not restate the requested address and the redacted locator does
            // not retain it, so a decoded position is identified by its observation, not by a
            // claimed address.
            let placeholder = format!("unstated:{}", observation.observation_id);
            match read_account_info(&envelope.body, &placeholder) {
                Ok(response) => {
                    let mut decoded_any = false;
                    for entry in &response.entries {
                        let Some(account) = &entry.account else {
                            continue;
                        };
                        if let Ok(position) = MeteoraPositionV2::decode(account) {
                            positions.push(position_line(&position, &provenance)?);
                            decoded_any = true;
                        }
                    }
                    if !decoded_any {
                        *account_reads_not_positions += 1;
                    }
                }
                Err(_) => *account_reads_not_positions += 1,
            }
        }
        StoredLocatorClass::Unrecognized => *unrecognized += 1,
    }
    Ok(())
}

fn position_line(
    position: &MeteoraPositionV2,
    provenance: &ObservationRef,
) -> Result<DlmmPositionLineV1, Box<dyn Error>> {
    Ok(DlmmPositionLineV1 {
        position_address: StableString::new(position.address.as_str())?,
        lb_pair: StableString::new(position.lb_pair.as_str())?,
        owner: StableString::new(position.owner.as_str())?,
        lower_bin_id: position.lower_bin_id,
        upper_bin_id: position.upper_bin_id,
        bin_count: position.bin_count(),
        pending_fee_x_atoms_floor: WireU64::new(position.pending_fee_x_atoms_fixed_slots),
        pending_fee_y_atoms_floor: WireU64::new(position.pending_fee_y_atoms_fixed_slots),
        last_updated_at_unix_seconds: position.last_updated_at,
        legs: LegInventory::NotDerivable {
            reason: StableString::new(
                "token-leg amounts require the pair's bin-array reserves, which this catalog \
                 does not retain",
            )?,
        },
        provenance: provenance.clone(),
    })
}

/// Renders atoms as an exact decimal string at the asset's stated decimals.
fn format_atoms(atoms: u128, decimals: u8) -> String {
    let scale = 10_u128.pow(u32::from(decimals));
    if scale == 1 {
        return atoms.to_string();
    }
    let whole = atoms / scale;
    let fraction = atoms % scale;
    let rendered = format!("{fraction:0>width$}", width = decimals as usize);
    let trimmed = rendered.trim_end_matches('0');
    if trimmed.is_empty() {
        whole.to_string()
    } else {
        format!("{whole}.{trimmed}")
    }
}

fn block_time_render(seconds: Option<&WireU64>) -> String {
    seconds
        .and_then(|value| i64::try_from(value.get()).ok())
        .and_then(|value| OffsetDateTime::from_unix_timestamp(value).ok())
        .map_or_else(
            || "block time unstated".to_owned(),
            |datetime| format!("block time {datetime}"),
        )
}

fn asset_heading(asset: &AssetRef, labels: &BTreeMap<String, String>) -> String {
    match asset {
        AssetRef::Native => "SOL (native, 9 decimals)".to_owned(),
        AssetRef::Token { mint, decimals } => {
            let label = labels
                .get(mint.as_str())
                .map(|name| format!("{name} (operator label) — "))
                .unwrap_or_default();
            format!("{label}mint {mint} ({decimals} decimals)")
        }
    }
}

#[allow(clippy::too_many_lines)] // One renderer keeps the whole statement shape visible.
fn render(statement: &PortfolioStatementV1, labels: &BTreeMap<String, String>) -> String {
    use std::fmt::Write as _;
    let mut out = String::new();
    let _ = writeln!(out, "PORTFOLIO STATEMENT {}", statement.contract_version);
    let _ = writeln!(out, "wallet {}", statement.wallet);
    let _ = writeln!(
        out,
        "derived at catalog commit {} (committed {})",
        statement.catalog_cutoff.commit_seq, statement.catalog_cutoff.committed_at
    );
    if let Some(head) = &statement.coverage.chain_head {
        let _ = writeln!(
            out,
            "chain head at sweep: slot {} [{} @ commit {}]",
            head.slot, head.provenance.observation_id, head.provenance.commit_seq
        );
    }
    let _ = writeln!(out);
    let _ = writeln!(
        out,
        "HOLDINGS — balances exact at their stated slots; a missing row is not a zero"
    );
    for holding in &statement.holdings {
        render_holding(&mut out, holding, labels);
    }
    if statement.holdings.is_empty() {
        let _ = writeln!(out, "  (no balance-affecting observations for this wallet)");
    }

    let _ = writeln!(out);
    let _ = writeln!(out, "POSITIONS");
    for position in &statement.positions {
        let _ = writeln!(
            out,
            "  DLMM position {} on pair {} (owner {})",
            position.position_address, position.lb_pair, position.owner
        );
        let _ = writeln!(
            out,
            "    bins {}..={} ({} bins), last updated {}",
            position.lower_bin_id,
            position.upper_bin_id,
            position.bin_count,
            position.last_updated_at_unix_seconds
        );
        match &position.legs {
            LegInventory::NotDerivable { reason } => {
                let _ = writeln!(out, "    legs: not derivable — {reason}");
            }
            LegInventory::Stated {
                x_atoms, y_atoms, ..
            } => {
                let _ = writeln!(out, "    legs: x {x_atoms} atoms, y {y_atoms} atoms");
            }
        }
        let _ = writeln!(
            out,
            "    [{} @ commit {}]",
            position.provenance.observation_id, position.provenance.commit_seq
        );
    }
    if statement.positions.is_empty() {
        let _ = writeln!(out, "  (none derivable from this catalog — see coverage)");
    }

    let _ = writeln!(out);
    let _ = writeln!(out, "VALUATION — {}", statement.valuation.composition_note);
    for sum in &statement.valuation.priced_sums {
        let _ = writeln!(
            out,
            "  {} {} over {} holding(s), price kind {}, {}",
            sum.amount, sum.quote, sum.holdings, sum.price_kind, sum.rounding
        );
    }

    let _ = writeln!(out);
    let _ = writeln!(out, "COVERAGE");
    match (
        &statement.coverage.observed_slot_lower,
        &statement.coverage.observed_slot_upper,
    ) {
        (Some(lower), Some(upper)) => {
            let _ = writeln!(
                out,
                "  observed balance transitions span slots {lower}..{upper}"
            );
        }
        _ => {
            let _ = writeln!(out, "  no balance transitions observed");
        }
    }
    for page in &statement.coverage.signature_pages {
        let _ = writeln!(
            out,
            "  signature page [{} @ commit {}]: {} listed, {} fetched",
            page.provenance.observation_id, page.provenance.commit_seq, page.listed, page.fetched
        );
        for signature in &page.unfetched_signatures {
            let _ = writeln!(out, "    unfetched: {signature}");
        }
    }
    for absence in &statement.coverage.named_absences {
        let _ = writeln!(out, "  absent, by name: {} — {}", absence.name, absence.why);
    }
    for note in &statement.coverage.notes {
        let _ = writeln!(out, "  note: {note}");
    }
    out
}

fn render_holding(out: &mut String, holding: &HoldingV1, labels: &BTreeMap<String, String>) {
    use std::fmt::Write as _;
    let decimals = holding.asset.decimals();
    let _ = writeln!(out, "  {}", asset_heading(&holding.asset, labels));
    let _ = writeln!(
        out,
        "    total {} ({} atoms across {} boundary account(s))",
        format_atoms(holding.total_atoms.get(), decimals),
        holding.total_atoms,
        holding.boundaries.len()
    );
    for boundary in &holding.boundaries {
        if let Some(account) = &boundary.boundary_account {
            let _ = writeln!(out, "    boundary {account}");
        }
        let _ = writeln!(
            out,
            "      {} as of slot {} ({}), sig {}",
            format_atoms(u128::from(boundary.balance_atoms.get()), decimals),
            boundary.as_of.slot,
            block_time_render(boundary.as_of.block_time_seconds.as_ref()),
            boundary.as_of.signature
        );
        let _ = writeln!(
            out,
            "      [{} @ commit {}]",
            boundary.as_of.provenance.observation_id, boundary.as_of.provenance.commit_seq
        );
        let derivation = &boundary.derivation;
        let opening = match &derivation.opening {
            OpeningInventory::ObservedZeroStart => {
                "opening observed at zero; fully explained by observed transitions".to_owned()
            }
            OpeningInventory::UnobservedOpening { atoms } => format!(
                "explained from slot {} onward; earlier balance {} is opening inventory, \
                 unobserved",
                derivation.explained_from_slot,
                format_atoms(u128::from(atoms.get()), decimals)
            ),
        };
        let _ = writeln!(out, "      {opening}");
        match &derivation.continuity {
            ChainContinuity::Contiguous => {
                let _ = writeln!(
                    out,
                    "      chain: contiguous across {} observed transition(s)",
                    derivation.events.len()
                );
            }
            ChainContinuity::Broken { breaks } => {
                let _ = writeln!(
                    out,
                    "      chain: BROKEN in {} place(s); the balance between the named \
                     transitions is unexplained",
                    breaks.len()
                );
                for gap in breaks {
                    let _ = writeln!(
                        out,
                        "        {} post {} != {} pre {}",
                        gap.prior_signature,
                        gap.prior_post_atoms,
                        gap.next_signature,
                        gap.next_pre_atoms
                    );
                }
            }
        }
    }
    match &holding.price {
        PriceStatus::Priced { price, value } => {
            let kind = match &price.kind {
                joshi_accounting::portfolio::PriceKind::ProviderMark { provider } => {
                    format!("provider mark by {provider}")
                }
                joshi_accounting::portfolio::PriceKind::VenueMarginal { venue } => {
                    format!("venue marginal at {venue}")
                }
            };
            let _ = writeln!(
                out,
                "    price: {} {} per token ({kind}, as of {}) -> value {} {} ({})",
                price.price_per_token,
                price.quote,
                price.as_of,
                value.amount,
                value.quote,
                value.rounding
            );
        }
        PriceStatus::Absent { note } => {
            let _ = writeln!(out, "    price: absent — {note}; value: absent, not zero");
        }
    }
}
