use std::collections::BTreeMap;

use joshi_domain::{SourceId, StableString};
use serde::{Deserialize, Serialize};

use crate::{MethodContract, RegistryError, SourceContract};

mod decimal {
    use serde::{Deserialize, Deserializer, Serializer, de::Error};
    #[allow(clippy::trivially_copy_pass_by_ref)] // serde's `with` serializer signature is fixed.
    pub fn serialize<S: Serializer>(value: &u64, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&value.to_string())
    }
    pub fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<u64, D::Error> {
        let value = String::deserialize(deserializer)?;
        value
            .parse()
            .map_err(|_| D::Error::custom("invalid decimal integer"))
    }
}

mod decimal_map {
    use joshi_domain::StableString;
    use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error};
    use std::collections::BTreeMap;
    pub fn serialize<S: Serializer>(
        value: &BTreeMap<StableString, u128>,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        let mapped: BTreeMap<&str, String> = value
            .iter()
            .map(|(key, value)| (key.as_str(), value.to_string()))
            .collect();
        mapped.serialize(serializer)
    }
    pub fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<BTreeMap<StableString, u128>, D::Error> {
        let mapped = BTreeMap::<String, String>::deserialize(deserializer)?;
        mapped
            .into_iter()
            .map(|(key, value)| {
                let key =
                    StableString::new(key).map_err(|_| D::Error::custom("invalid stable key"))?;
                let value = value
                    .parse()
                    .map_err(|_| D::Error::custom("invalid decimal integer"))?;
                Ok((key, value))
            })
            .collect()
    }
}

/// Independent dimensions used by a run. No dimension may borrow from another.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BudgetUsage {
    #[serde(with = "decimal")]
    pub requests: u64,
    #[serde(with = "decimal")]
    pub pages: u64,
    #[serde(with = "decimal")]
    pub ingress_bytes: u64,
    #[serde(with = "decimal")]
    pub durable_bytes: u64,
    #[serde(with = "decimal")]
    pub provider_credits: u64,
    #[serde(with = "decimal")]
    pub wall_millis: u64,
    #[serde(with = "decimal")]
    pub events: u64,
    #[serde(with = "decimal_map")]
    pub provider_currency_minor: BTreeMap<StableString, u128>,
    #[serde(with = "decimal_map")]
    pub chain_native_atoms: BTreeMap<StableString, u128>,
}

impl BudgetUsage {
    #[must_use]
    pub fn is_zero(&self) -> bool {
        self.requests == 0
            && self.pages == 0
            && self.ingress_bytes == 0
            && self.durable_bytes == 0
            && self.provider_credits == 0
            && self.wall_millis == 0
            && self.events == 0
            && self.provider_currency_minor.values().all(|v| *v == 0)
            && self.chain_native_atoms.values().all(|v| *v == 0)
    }

    /// # Errors
    ///
    /// Returns [`RegistryError::ArithmeticOverflow`] if any integer dimension overflows.
    pub fn checked_add(&self, other: &Self) -> Result<Self, RegistryError> {
        Ok(Self {
            requests: self
                .requests
                .checked_add(other.requests)
                .ok_or(RegistryError::ArithmeticOverflow)?,
            pages: self
                .pages
                .checked_add(other.pages)
                .ok_or(RegistryError::ArithmeticOverflow)?,
            ingress_bytes: self
                .ingress_bytes
                .checked_add(other.ingress_bytes)
                .ok_or(RegistryError::ArithmeticOverflow)?,
            durable_bytes: self
                .durable_bytes
                .checked_add(other.durable_bytes)
                .ok_or(RegistryError::ArithmeticOverflow)?,
            provider_credits: self
                .provider_credits
                .checked_add(other.provider_credits)
                .ok_or(RegistryError::ArithmeticOverflow)?,
            wall_millis: self
                .wall_millis
                .checked_add(other.wall_millis)
                .ok_or(RegistryError::ArithmeticOverflow)?,
            events: self
                .events
                .checked_add(other.events)
                .ok_or(RegistryError::ArithmeticOverflow)?,
            provider_currency_minor: checked_map_add(
                &self.provider_currency_minor,
                &other.provider_currency_minor,
            )?,
            chain_native_atoms: checked_map_add(
                &self.chain_native_atoms,
                &other.chain_native_atoms,
            )?,
        })
    }

    /// # Errors
    ///
    /// Returns [`RegistryError::BudgetExceeded`] if a dimension would become negative.
    pub fn checked_sub(&self, other: &Self) -> Result<Self, RegistryError> {
        Ok(Self {
            requests: self
                .requests
                .checked_sub(other.requests)
                .ok_or(RegistryError::BudgetExceeded)?,
            pages: self
                .pages
                .checked_sub(other.pages)
                .ok_or(RegistryError::BudgetExceeded)?,
            ingress_bytes: self
                .ingress_bytes
                .checked_sub(other.ingress_bytes)
                .ok_or(RegistryError::BudgetExceeded)?,
            durable_bytes: self
                .durable_bytes
                .checked_sub(other.durable_bytes)
                .ok_or(RegistryError::BudgetExceeded)?,
            provider_credits: self
                .provider_credits
                .checked_sub(other.provider_credits)
                .ok_or(RegistryError::BudgetExceeded)?,
            wall_millis: self
                .wall_millis
                .checked_sub(other.wall_millis)
                .ok_or(RegistryError::BudgetExceeded)?,
            events: self
                .events
                .checked_sub(other.events)
                .ok_or(RegistryError::BudgetExceeded)?,
            provider_currency_minor: checked_map_sub(
                &self.provider_currency_minor,
                &other.provider_currency_minor,
            )?,
            chain_native_atoms: checked_map_sub(
                &self.chain_native_atoms,
                &other.chain_native_atoms,
            )?,
        })
    }

    #[must_use]
    pub fn within(&self, cap: &Self) -> bool {
        self.requests <= cap.requests
            && self.pages <= cap.pages
            && self.ingress_bytes <= cap.ingress_bytes
            && self.durable_bytes <= cap.durable_bytes
            && self.provider_credits <= cap.provider_credits
            && self.wall_millis <= cap.wall_millis
            && self.events <= cap.events
            && map_within(&self.provider_currency_minor, &cap.provider_currency_minor)
            && map_within(&self.chain_native_atoms, &cap.chain_native_atoms)
    }
}

fn checked_map_add(
    left: &BTreeMap<StableString, u128>,
    right: &BTreeMap<StableString, u128>,
) -> Result<BTreeMap<StableString, u128>, RegistryError> {
    let mut out = left.clone();
    for (key, value) in right {
        let entry = out.entry(key.clone()).or_default();
        *entry = entry
            .checked_add(*value)
            .ok_or(RegistryError::ArithmeticOverflow)?;
    }
    Ok(out)
}

fn checked_map_sub(
    left: &BTreeMap<StableString, u128>,
    right: &BTreeMap<StableString, u128>,
) -> Result<BTreeMap<StableString, u128>, RegistryError> {
    let mut out = left.clone();
    for (key, value) in right {
        let entry = out.get_mut(key).ok_or(RegistryError::BudgetExceeded)?;
        *entry = entry
            .checked_sub(*value)
            .ok_or(RegistryError::BudgetExceeded)?;
    }
    out.retain(|_, value| *value != 0);
    Ok(out)
}

fn map_within(actual: &BTreeMap<StableString, u128>, cap: &BTreeMap<StableString, u128>) -> bool {
    actual
        .iter()
        .all(|(key, value)| cap.get(key).is_some_and(|limit| value <= limit))
}

/// A provider-independent estimate reserved before one request, page, frame, or connection.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CostEstimate {
    pub worst_case: BudgetUsage,
    pub max_overshoot: BudgetUsage,
}

/// A reservation token. It carries no provider credential and cannot execute an operation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BudgetReservation {
    #[serde(with = "decimal")]
    pub reservation_id: u64,
    pub run_id: Option<StableString>,
    pub reserved: BudgetUsage,
    pub max_overshoot: BudgetUsage,
    pub settled: bool,
    pub scope: Option<ReservationScope>,
    pub method: Option<MethodContract>,
}

/// Non-secret source/method binding carried by a pre-I/O reservation.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReservationScope {
    pub source_id: SourceId,
    pub method_key: StableString,
}

/// Immutable hard caps plus mutable accounting for one registered run.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RunBudget {
    pub run_id: Option<StableString>,
    pub hard_cap: BudgetUsage,
    pub consumed: BudgetUsage,
    pub reserved: BudgetUsage,
    pub next_reservation_id: u64,
    outstanding: std::collections::BTreeMap<
        u64,
        (
            BudgetUsage,
            Option<ReservationScope>,
            Option<MethodContract>,
        ),
    >,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RunBudgetSnapshot {
    pub hard_cap: BudgetUsage,
    pub consumed: BudgetUsage,
    pub reserved: BudgetUsage,
    pub available: BudgetUsage,
}

impl RunBudget {
    /// # Errors
    ///
    /// Returns [`RegistryError::InvalidValue`] for an all-zero cap.
    pub fn new(hard_cap: BudgetUsage) -> Result<Self, RegistryError> {
        if hard_cap.is_zero() {
            return Err(RegistryError::InvalidValue("empty run budget"));
        }
        Ok(Self {
            run_id: None,
            hard_cap,
            consumed: BudgetUsage::default(),
            reserved: BudgetUsage::default(),
            next_reservation_id: 1,
            outstanding: std::collections::BTreeMap::new(),
        })
    }

    /// Creates a run budget bound to a stable registration occurrence or digest.
    ///
    /// # Errors
    ///
    /// Returns [`RegistryError::InvalidValue`] when the run identity is not stable or the cap is
    /// empty.
    pub fn with_run_id(run_id: StableString, hard_cap: BudgetUsage) -> Result<Self, RegistryError> {
        let mut budget = Self::new(hard_cap)?;
        budget.run_id = Some(run_id);
        Ok(budget)
    }

    /// Reserve the declared worst case before provider I/O. In-flight overshoot is reserved too,
    /// so another operation cannot spend it concurrently.
    ///
    /// # Errors
    ///
    /// Returns a boundedness, arithmetic, or hard-cap refusal.
    pub fn reserve(&mut self, estimate: CostEstimate) -> Result<BudgetReservation, RegistryError> {
        self.reserve_internal(estimate, None, None)
    }

    /// Source-bound reservation used by collectors. It performs structural source admission and
    /// checks one request against the method's declared response/request and provider quota caps.
    ///
    /// # Errors
    ///
    /// Returns a source-admission, method-ceiling, boundedness, arithmetic, or hard-cap refusal.
    pub fn reserve_for_method(
        &mut self,
        source: &SourceContract,
        method_key: &StableString,
        estimate: CostEstimate,
    ) -> Result<BudgetReservation, RegistryError> {
        if self.run_id.is_none() {
            return Err(RegistryError::InvalidValue("run registration required"));
        }
        let method = source.admit_method(method_key)?;
        validate_method_estimate(method, &estimate)?;
        self.reserve_internal(
            estimate,
            Some(ReservationScope {
                source_id: source.source_id.clone(),
                method_key: method_key.clone(),
            }),
            Some(method.clone()),
        )
    }

    fn reserve_internal(
        &mut self,
        estimate: CostEstimate,
        scope: Option<ReservationScope>,
        method: Option<MethodContract>,
    ) -> Result<BudgetReservation, RegistryError> {
        if estimate.worst_case.is_zero() || !estimate.max_overshoot.within(&estimate.worst_case) {
            return Err(RegistryError::UnboundedReservation);
        }
        let reservation = estimate.worst_case.checked_add(&estimate.max_overshoot)?;
        let total = self
            .consumed
            .checked_add(&self.reserved)?
            .checked_add(&reservation)?;
        if !total.within(&self.hard_cap) {
            return Err(RegistryError::BudgetExceeded);
        }
        let id = self.next_reservation_id;
        self.next_reservation_id = self
            .next_reservation_id
            .checked_add(1)
            .ok_or(RegistryError::ArithmeticOverflow)?;
        self.reserved = self.reserved.checked_add(&reservation)?;
        self.outstanding
            .insert(id, (reservation.clone(), scope.clone(), method.clone()));
        Ok(BudgetReservation {
            reservation_id: id,
            run_id: self.run_id.clone(),
            reserved: estimate.worst_case,
            max_overshoot: estimate.max_overshoot,
            settled: false,
            scope,
            method,
        })
    }

    /// Settles an exact request/frame and releases its reservation. The observed amount may be
    /// lower than reserved, but cannot exceed reserved plus the declared bounded overshoot.
    ///
    /// # Errors
    ///
    /// Returns a reservation-identity, boundedness, arithmetic, or hard-cap refusal.
    #[allow(clippy::needless_pass_by_value)]
    pub fn settle(
        &mut self,
        reservation: &mut BudgetReservation,
        actual: BudgetUsage,
    ) -> Result<(), RegistryError> {
        if reservation.settled
            || reservation.reservation_id == 0
            || reservation.run_id != self.run_id
        {
            return Err(RegistryError::ReservationMismatch);
        }
        if actual.is_zero() {
            return Err(RegistryError::BudgetExceeded);
        }
        let allowance = reservation
            .reserved
            .checked_add(&reservation.max_overshoot)?;
        if self
            .outstanding
            .get(&reservation.reservation_id)
            .map(|(held, scope, method)| (held, scope, method))
            != Some((&allowance, &reservation.scope, &reservation.method))
        {
            return Err(RegistryError::ReservationMismatch);
        }
        if !actual.within(&allowance) {
            return Err(RegistryError::BudgetExceeded);
        }
        if let Some(method) = self
            .outstanding
            .get(&reservation.reservation_id)
            .and_then(|(_, _, method)| method.as_ref())
        {
            validate_actual(method, &actual)?;
        }
        let held = allowance;
        self.reserved = self.reserved.checked_sub(&held)?;
        let total = self.consumed.checked_add(&actual)?;
        if !total.within(&self.hard_cap) {
            return Err(RegistryError::BudgetExceeded);
        }
        self.consumed = total;
        self.outstanding.remove(&reservation.reservation_id);
        reservation.settled = true;
        Ok(())
    }

    /// # Errors
    ///
    /// Returns an arithmetic refusal if outstanding dimensions cannot be represented.
    pub fn snapshot(&self) -> Result<RunBudgetSnapshot, RegistryError> {
        let used = self.consumed.checked_add(&self.reserved)?;
        let available = self.hard_cap.checked_sub(&used)?;
        Ok(RunBudgetSnapshot {
            hard_cap: self.hard_cap.clone(),
            consumed: self.consumed.clone(),
            reserved: self.reserved.clone(),
            available,
        })
    }
}

fn validate_method_estimate(
    method: &MethodContract,
    estimate: &CostEstimate,
) -> Result<(), RegistryError> {
    if estimate.worst_case.requests == 0 {
        return Err(RegistryError::UnboundedReservation);
    }
    let allowance = estimate.worst_case.checked_add(&estimate.max_overshoot)?;
    let max_response = method
        .max_response_bytes
        .checked_mul(allowance.requests)
        .ok_or(RegistryError::ArithmeticOverflow)?;
    if allowance.ingress_bytes < max_response || allowance.durable_bytes < allowance.ingress_bytes {
        return Err(RegistryError::BudgetExceeded);
    }
    if let Some(limit) = method.quota.hard_limit {
        let observed = match method.quota.unit {
            crate::BillingUnit::Request => u128::from(allowance.requests),
            crate::BillingUnit::Event | crate::BillingUnit::TokenTradeEvent => {
                u128::from(allowance.events)
            }
            crate::BillingUnit::Page => u128::from(allowance.pages),
            crate::BillingUnit::ResponseByte => u128::from(allowance.ingress_bytes),
            crate::BillingUnit::ProviderCredit => u128::from(allowance.provider_credits),
            crate::BillingUnit::ChainNativeAtom => allowance
                .chain_native_atoms
                .values()
                .try_fold(0u128, |sum, value| sum.checked_add(*value))
                .ok_or(RegistryError::ArithmeticOverflow)?,
            crate::BillingUnit::None => 0,
        };
        if observed > u128::from(limit) {
            return Err(RegistryError::BudgetExceeded);
        }
    }
    let units = match method.billing.unit {
        crate::BillingUnit::Request => u128::from(allowance.requests),
        crate::BillingUnit::Page => u128::from(allowance.pages),
        crate::BillingUnit::ResponseByte => u128::from(allowance.ingress_bytes),
        crate::BillingUnit::ProviderCredit => u128::from(allowance.provider_credits),
        crate::BillingUnit::Event | crate::BillingUnit::TokenTradeEvent => {
            u128::from(allowance.events)
        }
        crate::BillingUnit::ChainNativeAtom => allowance
            .chain_native_atoms
            .values()
            .try_fold(0u128, |sum, value| sum.checked_add(*value))
            .ok_or(RegistryError::ArithmeticOverflow)?,
        crate::BillingUnit::None => 0,
    };
    if method.billing.minor_units_per_unit > 0
        && method.billing.currency.is_none()
        && method.billing.unit != crate::BillingUnit::ProviderCredit
        && method.billing.unit != crate::BillingUnit::ChainNativeAtom
    {
        return Err(RegistryError::InvalidContract(
            "charged method lacks currency",
        ));
    }
    let charge = units
        .checked_mul(u128::from(method.billing.minor_units_per_unit))
        .ok_or(RegistryError::ArithmeticOverflow)?;
    if method.billing.minor_units_per_unit > 0 && units == 0 {
        return Err(RegistryError::BudgetExceeded);
    }
    if let Some(currency) = &method.billing.currency
        && allowance
            .provider_currency_minor
            .get(currency)
            .copied()
            .unwrap_or(0)
            < charge
    {
        return Err(RegistryError::BudgetExceeded);
    }
    if method.billing.unit == crate::BillingUnit::ProviderCredit
        && u128::from(allowance.provider_credits) < charge
    {
        return Err(RegistryError::BudgetExceeded);
    }
    if method.billing.unit == crate::BillingUnit::ChainNativeAtom {
        let asset = method
            .billing
            .asset_id
            .as_ref()
            .ok_or(RegistryError::InvalidContract("native billing lacks asset"))?;
        if allowance
            .chain_native_atoms
            .get(asset)
            .copied()
            .unwrap_or(0)
            < charge
        {
            return Err(RegistryError::BudgetExceeded);
        }
    }
    Ok(())
}

fn validate_actual(method: &MethodContract, actual: &BudgetUsage) -> Result<(), RegistryError> {
    if actual.requests == 0 {
        return Err(RegistryError::BudgetExceeded);
    }
    let units = match method.billing.unit {
        crate::BillingUnit::None => 0,
        crate::BillingUnit::Request => u128::from(actual.requests),
        crate::BillingUnit::Page => u128::from(actual.pages),
        crate::BillingUnit::ResponseByte => u128::from(actual.ingress_bytes),
        crate::BillingUnit::ProviderCredit => u128::from(actual.provider_credits),
        crate::BillingUnit::Event | crate::BillingUnit::TokenTradeEvent => {
            u128::from(actual.events)
        }
        crate::BillingUnit::ChainNativeAtom => actual
            .chain_native_atoms
            .values()
            .try_fold(0u128, |sum, value| sum.checked_add(*value))
            .ok_or(RegistryError::ArithmeticOverflow)?,
    };
    if method.billing.minor_units_per_unit > 0 && units == 0 {
        return Err(RegistryError::BudgetExceeded);
    }
    if let Some(limit) = method.quota.hard_limit
        && units > u128::from(limit)
    {
        return Err(RegistryError::BudgetExceeded);
    }
    let charge = units
        .checked_mul(u128::from(method.billing.minor_units_per_unit))
        .ok_or(RegistryError::ArithmeticOverflow)?;
    if let Some(currency) = &method.billing.currency
        && actual
            .provider_currency_minor
            .get(currency)
            .copied()
            .unwrap_or(0)
            < charge
    {
        return Err(RegistryError::BudgetExceeded);
    }
    if method.billing.unit == crate::BillingUnit::ChainNativeAtom {
        let asset = method
            .billing
            .asset_id
            .as_ref()
            .ok_or(RegistryError::InvalidContract("native billing asset"))?;
        if actual.chain_native_atoms.get(asset).copied().unwrap_or(0) < charge {
            return Err(RegistryError::BudgetExceeded);
        }
    }
    let max_response = method
        .max_response_bytes
        .checked_mul(actual.requests)
        .ok_or(RegistryError::ArithmeticOverflow)?;
    if actual.ingress_bytes > max_response || actual.durable_bytes < actual.ingress_bytes {
        return Err(RegistryError::BudgetExceeded);
    }
    Ok(())
}
