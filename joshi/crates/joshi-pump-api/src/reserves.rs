//! The only supported way to read a coin's bonding-curve reserves, and the reason it refuses.
//!
//! MEASURED 2026-08-22. A coin whose `complete` flag was `true` was observed on `/coins` carrying
//! `virtual_sol_reserves` of 30000000000 and `real_sol_reserves` of 0 — the untouched pump launch
//! constants — while its market cap fell from about 111 million to about 3 million USD inside
//! ninety-seven seconds. Its `market_cap` in SOL moved with the crash; its reserves did not move
//! at all. Once a coin graduates off the pump bonding curve the provider stops maintaining those
//! four numbers, and anything that reconstructs curve state from them afterwards derives a
//! confident, precise, completely wrong price for a coin that no longer trades on that curve.
//!
//! Nothing in this module can hand back a reserve quartet for a graduated coin, or for a coin
//! whose curve state could not be read. [`OnCurveReserves`] has no public constructor and no
//! public fields, so the only way to hold all four numbers together is to have gone through
//! [`price_bearing_reserves`] and to have had it say yes.
//!
//! An individual reserve lexeme is of course still visible in the retained bytes and in the
//! record's tagged fields — this crate never hides provider data. What it will not do is assemble
//! them into something a caller can treat as curve state. The tag on each of those fields says
//! `provider_launch_constant_after_graduation_never_a_price_input` for exactly that reason.

use std::fmt;

use crate::normalize::NormalizedRecord;

/// Whether a coin's reserves are still being maintained by the provider.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CurveState {
    /// `complete` is false: the coin is still on its pump bonding curve.
    OnCurve,
    /// `complete` is true: the coin has graduated and its reserve fields are frozen constants.
    Graduated,
    /// The record carried no readable `complete` flag. An unknown curve state is not a live one.
    Unknown,
}

/// Why a reserve read was refused. Every variant is a refusal to produce a number, never a
/// substitute number.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReserveRefusal {
    /// The coin has graduated; its reserve fields are launch constants and mean nothing.
    Graduated,
    /// The record did not say whether the coin has graduated, so its reserves cannot be trusted.
    CurveStateUnknown,
    /// The record is missing a reserve the curve needs, so the quartet is incomplete.
    ReserveAbsent(&'static str),
}

impl fmt::Display for ReserveRefusal {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Graduated => formatter.write_str(
                "this coin has graduated off the pump bonding curve; its reserve fields are frozen \
                 launch constants and no price may be derived from them",
            ),
            Self::CurveStateUnknown => formatter.write_str(
                "this record carries no readable `complete` flag, so whether its reserves are \
                 still maintained is unknown and they may not be used",
            ),
            Self::ReserveAbsent(name) => write!(
                formatter,
                "this record carries no {name}, so the curve quartet is incomplete"
            ),
        }
    }
}

impl std::error::Error for ReserveRefusal {}

/// A complete reserve quartet for a coin that is still on its bonding curve.
///
/// No public fields and no public constructor: the only way to obtain one is
/// [`price_bearing_reserves`], which refuses for a graduated or unknown-state coin. Each value is
/// the provider's exact JSON number lexeme, never parsed here.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OnCurveReserves {
    virtual_sol: String,
    virtual_token: String,
    real_sol: String,
    real_token: String,
    virtual_quote: Option<String>,
    real_quote: Option<String>,
}

impl OnCurveReserves {
    #[must_use]
    pub fn virtual_sol(&self) -> &str {
        &self.virtual_sol
    }

    #[must_use]
    pub fn virtual_token(&self) -> &str {
        &self.virtual_token
    }

    #[must_use]
    pub fn real_sol(&self) -> &str {
        &self.real_sol
    }

    #[must_use]
    pub fn real_token(&self) -> &str {
        &self.real_token
    }

    /// Present only when the provider carried it; a coin quoted in SOL may report the quote pair
    /// and the sol pair as the same numbers, and a coin quoted in something else may not.
    #[must_use]
    pub fn virtual_quote(&self) -> Option<&str> {
        self.virtual_quote.as_deref()
    }

    #[must_use]
    pub fn real_quote(&self) -> Option<&str> {
        self.real_quote.as_deref()
    }
}

/// What the record says about whether this coin is still on its curve.
#[must_use]
pub fn curve_state(record: &NormalizedRecord) -> CurveState {
    match lexeme(record, "complete") {
        Some("false") => CurveState::OnCurve,
        Some("true") => CurveState::Graduated,
        _ => CurveState::Unknown,
    }
}

/// The reserve quartet, but only for a coin whose reserves the provider is still maintaining.
///
/// # Errors
///
/// Refuses for a graduated coin, for a coin whose curve state the record does not state, and for
/// a record missing any member of the quartet. A refusal is never accompanied by a fallback.
pub fn price_bearing_reserves(
    record: &NormalizedRecord,
) -> Result<OnCurveReserves, ReserveRefusal> {
    match curve_state(record) {
        CurveState::Graduated => return Err(ReserveRefusal::Graduated),
        CurveState::Unknown => return Err(ReserveRefusal::CurveStateUnknown),
        CurveState::OnCurve => {}
    }
    let need = |name: &'static str| {
        lexeme(record, name)
            .map(str::to_owned)
            .ok_or(ReserveRefusal::ReserveAbsent(name))
    };
    Ok(OnCurveReserves {
        virtual_sol: need("virtual_sol_reserves")?,
        virtual_token: need("virtual_token_reserves")?,
        real_sol: need("real_sol_reserves")?,
        real_token: need("real_token_reserves")?,
        virtual_quote: lexeme(record, "virtual_quote_reserves").map(str::to_owned),
        real_quote: lexeme(record, "real_quote_reserves").map(str::to_owned),
    })
}

fn lexeme<'a>(record: &'a NormalizedRecord, name: &str) -> Option<&'a str> {
    record
        .fields
        .iter()
        .find(|field| field.field == name)
        .and_then(|field| field.value.as_deref())
}
