//! Exact financial wire primitives.

use core::fmt;
use std::str::FromStr;

use joshi_accounting::{
    amount::{SignedAtoms, TotalAtoms},
    basis::{BasisError, ExactRatio, RatioWire},
};
use joshi_domain::{AssetId, ObservationId, StableString, WireU128};
use serde::{Deserialize, Deserializer, Serialize, de};
use thiserror::Error;

/// Evidence-bound asset metadata required to interpret atomic quantities.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AssetDefinitionDto {
    pub asset_id: AssetId,
    pub mint: StableString,
    pub token_program: StableString,
    pub decimals: u8,
    pub definition_observation_id: ObservationId,
}

/// Exact aggregate atoms with their interpretation contract carried at every boundary.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AtomicAmountDto {
    pub asset_id: AssetId,
    pub atoms: WireU128,
    pub decimals: u8,
    pub definition_observation_id: ObservationId,
}

impl AtomicAmountDto {
    #[must_use]
    pub fn from_total(definition: &AssetDefinitionDto, atoms: TotalAtoms) -> Self {
        Self {
            asset_id: definition.asset_id.clone(),
            atoms: WireU128::new(atoms.get()),
            decimals: definition.decimals,
            definition_observation_id: definition.definition_observation_id.clone(),
        }
    }

    #[must_use]
    pub fn from_u64(definition: &AssetDefinitionDto, atoms: u64) -> Self {
        Self {
            asset_id: definition.asset_id.clone(),
            atoms: WireU128::new(u128::from(atoms)),
            decimals: definition.decimals,
            definition_observation_id: definition.definition_observation_id.clone(),
        }
    }
}

/// Signed aggregate atomic movement without an unsafe signed narrowing.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "direction", rename_all = "snake_case", deny_unknown_fields)]
pub enum SignedAtomicAmountDto {
    Increase { amount: AtomicAmountDto },
    Decrease { amount: AtomicAmountDto },
    Unchanged { amount: AtomicAmountDto },
}

impl SignedAtomicAmountDto {
    #[must_use]
    pub fn from_signed(definition: &AssetDefinitionDto, value: SignedAtoms) -> Self {
        match value {
            SignedAtoms::Increase(atoms) => Self::Increase {
                amount: AtomicAmountDto::from_total(definition, atoms),
            },
            SignedAtoms::Decrease(atoms) => Self::Decrease {
                amount: AtomicAmountDto::from_total(definition, atoms),
            },
            SignedAtoms::Unchanged => Self::Unchanged {
                amount: AtomicAmountDto::from_total(definition, TotalAtoms::ZERO),
            },
        }
    }
}

/// Reduced exact rational encoded with canonical signed/unsigned decimal strings.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExactRatioDto {
    pub numerator: String,
    pub denominator: String,
}

impl ExactRatioDto {
    #[must_use]
    pub fn from_exact(value: &ExactRatio) -> Self {
        Self {
            numerator: value.numerator_string(),
            denominator: value.denominator_string(),
        }
    }

    /// Validates canonical reduction and positive denominator.
    ///
    /// # Errors
    ///
    /// Returns the accounting ratio error without normalizing the input.
    pub fn validate(&self) -> Result<(), BasisError> {
        RatioWire {
            numerator: self.numerator.clone(),
            denominator: self.denominator.clone(),
        }
        .parse()
        .map(|_| ())
    }
}

/// Canonical signed `i32` serialized as a JSON string.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct WireI32(i32);

impl WireI32 {
    #[must_use]
    pub const fn new(value: i32) -> Self {
        Self(value)
    }

    #[must_use]
    pub const fn get(self) -> i32 {
        self.0
    }
}

impl fmt::Display for WireI32 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl Serialize for WireI32 {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for WireI32 {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        parse_i32(&value).map(Self).map_err(de::Error::custom)
    }
}

fn parse_i32(value: &str) -> Result<i32, SignedWireError> {
    let digits = value.strip_prefix('-').unwrap_or(value);
    if value.starts_with('+')
        || digits.is_empty()
        || (digits.len() > 1 && digits.starts_with('0'))
        || value == "-0"
        || !digits.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(SignedWireError::NonCanonical);
    }
    i32::from_str(value).map_err(|_| SignedWireError::OutOfRange)
}

/// Invalid signed decimal-string integer.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum SignedWireError {
    #[error("signed wire integer is not canonical")]
    NonCanonical,
    #[error("signed wire integer is outside i32 range")]
    OutOfRange,
}
