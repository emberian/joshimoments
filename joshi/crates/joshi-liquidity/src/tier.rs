//! Which fee-tier row a market cap selects, and how far it is from the next one.
//!
//! "Graduated" predicts nothing. Three real mints read on 2026-08-21 and 2026-08-22:
//!
//! ```text
//! BKdJofy…  bonding curve      fee floor 247 bps
//! gV5pNNAf… graduated pool     fee floor  60 bps
//! AxshJi4U… graduated pool     fee floor 249 bps
//! ```
//!
//! The third is graduated and as expensive as the curve, because at a 42.8 SOL market cap it
//! selects the fee program's **first tier row** at 125 basis points a leg. The venue label is not
//! the lever; the row the market cap selects is. And the ladder is steep — on the retained
//! `PumpSwap` configuration the creator component goes 30 bps at the first row, 95 at the second,
//! then 90, 85, 80, … down to 5 at the top — so a coin sitting just under a threshold is a
//! different trade from the same coin just over it.
//!
//! Two things this module refuses to smooth over.
//!
//! **A ladder position is stated against one table.** The retained fee configuration carries more
//! than one tier vector and no retained byte says which one the program applies. They select
//! different rows over a wide populated band: at a 100 SOL market cap one table is still on its
//! first row at 125 basis points a leg while the other has moved to its second at 120. So a
//! position is located in *each* table and [`TierStanding`] carries all of them plus which one the
//! readout's rates were actually taken from.
//!
//! **The first row can apply as a fallback rather than because a threshold was reached.** The
//! deployed selection takes the highest threshold not exceeding the market cap and falls back to
//! the first row when none does. Those are two different situations that produce the same rates,
//! and [`TierPosition::below_first_threshold`] keeps them apart.
//!
//! Nothing here reads the network, and nothing here decides which table applies.

use joshi_market_math::{
    fee::{CreatorFee, FeeSchedule},
    stack::{ExactRatio, StackRefusal},
};

/// One row of a deployed fee-tier table: a market-cap threshold and the rates at or above it.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TierRow {
    /// Market cap, in quote atoms, at or above which this row applies.
    pub threshold_quote_atoms: u128,
    pub schedule: FeeSchedule,
}

impl TierRow {
    /// Total rate this row charges on one leg, in basis points.
    ///
    /// `None` when the creator component was not observed. That is an absent record and never a
    /// zero: a schedule missing its creator leg understates the round trip by up to 95 basis
    /// points on the retained tables, in the flattering direction.
    #[must_use]
    pub fn leg_bps(&self) -> Option<u128> {
        let creator = match self.schedule.creator {
            CreatorFee::Charged(rate) => u128::from(rate.get()),
            CreatorFee::NotApplicable => 0,
            CreatorFee::Unknown => return None,
        };
        Some(
            u128::from(self.schedule.lp.get()) + u128::from(self.schedule.protocol.get()) + creator,
        )
    }
}

/// Which way the leg rate moves at the next threshold.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TierDirection {
    /// The next row charges less. Growth helps.
    Cheaper,
    /// The next row charges more. Growth hurts.
    Dearer,
    Unchanged,
    /// One of the two rows did not state its creator component, so no comparison is stated.
    NotComparable,
}

/// The next row up the ladder and how far this market cap is from it.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NextTier {
    /// Zero-based index of the next row in this table's serialized order.
    pub row_index: usize,
    pub threshold_quote_atoms: u128,
    pub schedule: FeeSchedule,
    /// Quote atoms of market cap between here and that threshold. Always positive.
    pub gap_quote_atoms: u128,
    /// That gap as a fraction of the current market cap. `None` at a zero market cap, where a
    /// fraction of nothing is not a number.
    pub gap_of_market_cap: Option<ExactRatio>,
    pub direction: TierDirection,
}

impl NextTier {
    /// Total rate the next row charges on one leg, in basis points.
    #[must_use]
    pub fn leg_bps(&self) -> Option<u128> {
        TierRow {
            threshold_quote_atoms: self.threshold_quote_atoms,
            schedule: self.schedule,
        }
        .leg_bps()
    }
}

/// Where one market cap sits in one table's ladder.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TierPosition {
    pub market_cap_quote_atoms: u128,
    /// Zero-based index of the row the deployed selection applies.
    pub row_index: usize,
    /// How many rows this table carries, so an ordinal can be read as "row 1 of 25".
    pub row_count: usize,
    pub threshold_quote_atoms: u128,
    pub schedule: FeeSchedule,
    /// True when the market cap is under the first row's own threshold and that row is applying
    /// as the deployed fallback rather than because its threshold was reached.
    pub below_first_threshold: bool,
    /// `None` at the top row, which is an answer: there is no further threshold to cross.
    pub next: Option<NextTier>,
}

impl TierPosition {
    /// Total rate the applying row charges on one leg, in basis points.
    #[must_use]
    pub fn leg_bps(&self) -> Option<u128> {
        TierRow {
            threshold_quote_atoms: self.threshold_quote_atoms,
            schedule: self.schedule,
        }
        .leg_bps()
    }
}

/// One validated fee-tier table.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TierLadder {
    rows: Vec<TierRow>,
}

impl TierLadder {
    /// Validates one table's rows.
    ///
    /// # Errors
    ///
    /// Refuses an empty table and thresholds that are not strictly increasing, because the
    /// deployed selection scans from the top and a table that is not ordered selects a row nobody
    /// can predict from reading it.
    pub fn new(rows: Vec<TierRow>) -> Result<Self, TierError> {
        if rows.is_empty() {
            return Err(TierError::EmptyTable);
        }
        if rows
            .windows(2)
            .any(|pair| pair[0].threshold_quote_atoms >= pair[1].threshold_quote_atoms)
        {
            return Err(TierError::ThresholdsNotIncreasing);
        }
        Ok(Self { rows })
    }

    #[must_use]
    pub fn rows(&self) -> &[TierRow] {
        &self.rows
    }

    /// Locates one market cap in this ladder, exactly as the deployed selection would.
    ///
    /// # Errors
    ///
    /// Propagates wide-arithmetic failure from the gap ratio.
    pub fn locate(&self, market_cap_quote_atoms: u128) -> Result<TierPosition, TierError> {
        let found = self
            .rows
            .iter()
            .rposition(|row| row.threshold_quote_atoms <= market_cap_quote_atoms);
        let row_index = found.unwrap_or(0);
        let row = self.rows[row_index];
        let next = self
            .rows
            .get(row_index + 1)
            .map(|upper| -> Result<NextTier, TierError> {
                let gap = upper
                    .threshold_quote_atoms
                    .checked_sub(market_cap_quote_atoms)
                    .ok_or(TierError::Arithmetic)?;
                let here = row.leg_bps();
                let there = TierRow {
                    threshold_quote_atoms: upper.threshold_quote_atoms,
                    schedule: upper.schedule,
                }
                .leg_bps();
                Ok(NextTier {
                    row_index: row_index + 1,
                    threshold_quote_atoms: upper.threshold_quote_atoms,
                    schedule: upper.schedule,
                    gap_quote_atoms: gap,
                    gap_of_market_cap: match ExactRatio::new(gap, market_cap_quote_atoms) {
                        Ok(ratio) => Some(ratio),
                        Err(StackRefusal::UndefinedRatio) => None,
                        Err(_) => return Err(TierError::Arithmetic),
                    },
                    direction: match (here, there) {
                        (Some(here), Some(there)) if there < here => TierDirection::Cheaper,
                        (Some(here), Some(there)) if there > here => TierDirection::Dearer,
                        (Some(_), Some(_)) => TierDirection::Unchanged,
                        _ => TierDirection::NotComparable,
                    },
                })
            })
            .transpose()?;
        Ok(TierPosition {
            market_cap_quote_atoms,
            row_index,
            row_count: self.rows.len(),
            threshold_quote_atoms: row.threshold_quote_atoms,
            schedule: row.schedule,
            below_first_threshold: found.is_none(),
            next,
        })
    }
}

/// How the rates in a readout were chosen when the retained tables did not agree.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TierBasis {
    /// Every retained table selected the same rates at this market cap, so nothing was chosen.
    EveryTableAgreed,
    /// The tables selected different rates and no retained byte says which applies. The readout
    /// uses the most expensive of them, which errs against the trade and never for it.
    WorstOfDisagreeingTables,
}

/// Every retained table's own ladder position at one market cap, and which one was applied.
///
/// This exists because the fee configuration carries more than one tier vector, and a readout that
/// printed a single row would be asserting an answer the bytes do not contain.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TierStanding {
    pub market_cap_quote_atoms: u128,
    /// One position per retained table, in the configuration's serialized order.
    pub per_table: Vec<TierPosition>,
    /// Index into [`Self::per_table`] whose rates the readout actually used.
    pub applied_table_index: usize,
    pub basis: TierBasis,
}

impl TierStanding {
    /// Locates one market cap in every retained table and states which position was applied.
    ///
    /// # Errors
    ///
    /// Refuses an empty table set, an `applied_table_index` outside it, and propagates every
    /// ladder refusal.
    pub fn locate(
        ladders: &[TierLadder],
        market_cap_quote_atoms: u128,
        applied_table_index: usize,
        basis: TierBasis,
    ) -> Result<Self, TierError> {
        if ladders.is_empty() {
            return Err(TierError::NoTables);
        }
        if applied_table_index >= ladders.len() {
            return Err(TierError::AppliedTableOutOfRange {
                index: applied_table_index,
                tables: ladders.len(),
            });
        }
        let per_table = ladders
            .iter()
            .map(|ladder| ladder.locate(market_cap_quote_atoms))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Self {
            market_cap_quote_atoms,
            per_table,
            applied_table_index,
            basis,
        })
    }

    /// The position whose rates the readout used.
    #[must_use]
    pub fn applied(&self) -> &TierPosition {
        &self.per_table[self.applied_table_index]
    }

    /// True when every retained table put this market cap on rows charging the same leg rate.
    ///
    /// Rate agreement, not row agreement: two tables can reach the same rates through differently
    /// numbered rows, and it is the rate that costs money.
    #[must_use]
    pub fn tables_agree_on_leg_rate(&self) -> bool {
        let first = self.per_table[0].leg_bps();
        self.per_table
            .iter()
            .all(|position| position.leg_bps() == first)
    }
}

/// Exactly why a ladder could not be read. An absent row is never a zero.
#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum TierError {
    #[error("a fee tier table with no rows selects nothing")]
    EmptyTable,
    #[error(
        "fee tier thresholds are not strictly increasing, so the deployed top-down scan selects a \
         row that cannot be predicted by reading the table"
    )]
    ThresholdsNotIncreasing,
    #[error("no retained fee tier table was supplied")]
    NoTables,
    #[error("the applied table index {index} is outside the {tables} retained tables")]
    AppliedTableOutOfRange { index: usize, tables: usize },
    #[error("checked arithmetic failed")]
    Arithmetic,
}

#[cfg(test)]
mod tests {
    use super::*;
    use joshi_market_math::fee::FeeBps;

    fn schedule(lp: u16, protocol: u16, creator: u16) -> FeeSchedule {
        FeeSchedule {
            lp: FeeBps::new(lp).expect("lp"),
            protocol: FeeBps::new(protocol).expect("protocol"),
            creator: CreatorFee::Charged(FeeBps::new(creator).expect("creator")),
        }
    }

    fn row(threshold: u128, lp: u16, protocol: u16, creator: u16) -> TierRow {
        TierRow {
            threshold_quote_atoms: threshold,
            schedule: schedule(lp, protocol, creator),
        }
    }

    /// The head of the first tier vector on the `PumpSwap` fee configuration retained at slot
    /// 440840124, in quote atoms. These are the bytes, not a paraphrase of them.
    fn retained_table_zero() -> TierLadder {
        TierLadder::new(vec![
            row(0, 2, 93, 30),
            row(420_000_000_000, 20, 5, 95),
            row(1_470_000_000_000, 20, 5, 90),
            row(2_460_000_000_000, 20, 5, 85),
        ])
        .expect("the retained rows are ordered")
    }

    /// The head of the second tier vector on the same account, which disagrees with the first.
    fn retained_table_one() -> TierLadder {
        TierLadder::new(vec![
            row(0, 2, 93, 30),
            row(59_000_000_000, 20, 5, 95),
            row(300_000_000_000, 20, 5, 90),
            row(500_000_000_000, 20, 5, 85),
        ])
        .expect("the retained rows are ordered")
    }

    #[test]
    fn a_graduated_pool_under_the_first_threshold_is_on_the_first_row_at_125_bps_a_leg() {
        // The measurement this module exists for: a graduated pool at a 42.8 SOL market cap is as
        // expensive as a live bonding curve, because it selects the first row.
        let position = retained_table_zero()
            .locate(42_800_000_000)
            .expect("locates");
        assert_eq!(position.row_index, 0);
        assert_eq!(position.row_count, 4);
        assert_eq!(position.leg_bps(), Some(125));
        assert!(
            !position.below_first_threshold,
            "the first row's own threshold is zero, so it applies because it was reached"
        );
        let next = position.next.expect("a row above exists");
        assert_eq!(next.threshold_quote_atoms, 420_000_000_000);
        assert_eq!(next.gap_quote_atoms, 377_200_000_000);
        assert_eq!(next.leg_bps(), Some(120));
        assert_eq!(next.direction, TierDirection::Cheaper);
        // 8.81x the current market cap away, which is the honest reading of "not close".
        assert_eq!(
            next.gap_of_market_cap.expect("a nonzero cap").bps_ceil(),
            Ok(88_131)
        );
    }

    #[test]
    fn the_two_retained_tables_disagree_over_a_populated_band_and_the_worse_one_is_named() {
        // A 100 SOL market cap: the first table is still on its first row at 125 basis points a
        // leg, the second has already moved to its 95-basis-point creator row at 120.
        let ladders = [retained_table_zero(), retained_table_one()];
        let standing = TierStanding::locate(
            &ladders,
            100_000_000_000,
            0,
            TierBasis::WorstOfDisagreeingTables,
        )
        .expect("locates in both");
        assert_eq!(standing.per_table[0].leg_bps(), Some(125));
        assert_eq!(standing.per_table[1].leg_bps(), Some(120));
        assert!(!standing.tables_agree_on_leg_rate());
        assert_eq!(
            standing.applied().leg_bps(),
            Some(125),
            "the worse of the two"
        );
        assert_eq!(standing.basis, TierBasis::WorstOfDisagreeingTables);
    }

    #[test]
    fn where_the_tables_agree_the_standing_says_nothing_was_chosen() {
        let ladders = [retained_table_zero(), retained_table_one()];
        let standing =
            TierStanding::locate(&ladders, 10_000_000_000, 0, TierBasis::EveryTableAgreed)
                .expect("locates in both");
        assert!(standing.tables_agree_on_leg_rate());
        assert_eq!(standing.basis, TierBasis::EveryTableAgreed);
        // Same rate, and on this cap the same row too.
        assert_eq!(standing.per_table[0].row_index, 0);
        assert_eq!(standing.per_table[1].row_index, 0);
    }

    #[test]
    fn the_top_row_has_no_next_threshold_and_that_is_an_answer() {
        let position = retained_table_zero()
            .locate(500_000_000_000_000)
            .expect("locates");
        assert_eq!(position.row_index, 3);
        assert!(position.next.is_none());
    }

    #[test]
    fn a_first_row_applying_as_a_fallback_is_not_the_same_as_one_whose_threshold_was_reached() {
        // The deployed selection falls back to the first row when no threshold is met. That is a
        // different situation from reaching the first threshold and it is reported as one.
        let ladder =
            TierLadder::new(vec![row(1_000, 2, 93, 30), row(2_000, 20, 5, 95)]).expect("ordered");
        let below = ladder.locate(400).expect("locates");
        assert!(below.below_first_threshold);
        assert_eq!(below.row_index, 0);
        // The next rate change is the second row, not the first row's own threshold, because
        // reaching that threshold changes no rate.
        let next = below.next.expect("a row above exists");
        assert_eq!(next.threshold_quote_atoms, 2_000);
        assert_eq!(next.gap_quote_atoms, 1_600);

        let reached = ladder.locate(1_000).expect("locates");
        assert!(!reached.below_first_threshold);
        assert_eq!(reached.row_index, 0);
    }

    #[test]
    fn a_creator_component_nobody_observed_is_not_comparable_and_never_a_zero() {
        let ladder = TierLadder::new(vec![
            TierRow {
                threshold_quote_atoms: 0,
                schedule: FeeSchedule {
                    lp: FeeBps::new(20).expect("lp"),
                    protocol: FeeBps::new(5).expect("protocol"),
                    creator: CreatorFee::Unknown,
                },
            },
            row(1_000, 20, 5, 95),
        ])
        .expect("ordered");
        let position = ladder.locate(0).expect("locates");
        assert_eq!(position.leg_bps(), None);
        assert_eq!(
            position.next.expect("a row above").direction,
            TierDirection::NotComparable
        );
    }

    #[test]
    fn an_unordered_or_empty_table_is_refused_rather_than_located() {
        assert_eq!(TierLadder::new(Vec::new()), Err(TierError::EmptyTable));
        assert_eq!(
            TierLadder::new(vec![row(1_000, 20, 5, 95), row(1_000, 20, 5, 90)]),
            Err(TierError::ThresholdsNotIncreasing)
        );
    }

    #[test]
    fn a_zero_market_cap_reports_no_fraction_rather_than_a_zero_one() {
        let position = retained_table_zero().locate(0).expect("locates");
        let next = position.next.expect("a row above");
        assert_eq!(next.gap_quote_atoms, 420_000_000_000);
        assert!(
            next.gap_of_market_cap.is_none(),
            "a fraction of a zero market cap is not a number"
        );
    }

    #[test]
    fn an_applied_index_outside_the_retained_tables_is_refused() {
        let ladders = [retained_table_zero()];
        assert_eq!(
            TierStanding::locate(&ladders, 1, 3, TierBasis::EveryTableAgreed),
            Err(TierError::AppliedTableOutOfRange {
                index: 3,
                tables: 1
            })
        );
    }
}
