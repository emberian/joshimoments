//! Exact decoders for the read-only Solana account and block responses this crate fetches.
//!
//! Nothing here reinterprets or normalizes a provider payload. Each function reads one retained
//! response body and returns the exact values that body states, refusing anything it cannot read
//! literally. No refusal carries provider prose, a URL, or a credential: a JSON-RPC error is
//! reported by its numeric code only, because provider message text is not trusted to be free of
//! an authenticated endpoint.

use base64::{Engine as _, engine::general_purpose::STANDARD as BASE64};
use serde_json::Value;
use thiserror::Error;

/// One account exactly as the provider stated it, with its data already base64-decoded.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetainedAccount {
    /// The address this crate asked for. The response body does not restate it.
    pub address: String,
    /// Owning program stated by the provider.
    pub owner: String,
    pub lamports: u64,
    pub executable: bool,
    /// Exact account data bytes.
    pub data: Vec<u8>,
}

/// One requested address and the account the provider returned for it, if any.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AccountEntry {
    pub address: String,
    /// `None` is the provider stating the account does not exist at this slot. That is a fact the
    /// bytes support, and it is kept distinct from a decode failure.
    pub account: Option<RetainedAccount>,
}

/// A whole `getMultipleAccounts` or `getAccountInfo` response, bound to its context slot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AccountSetResponse {
    /// The slot at which the provider evaluated this query, from `result.context.slot`.
    pub context_slot: u64,
    pub entries: Vec<AccountEntry>,
}

impl AccountSetResponse {
    /// Returns the account the provider returned for one requested address.
    ///
    /// # Errors
    ///
    /// Refuses an address this response does not cover and an address the provider reported absent.
    pub fn require(&self, address: &str) -> Result<&RetainedAccount, AccountResponseError> {
        let entry = self
            .entries
            .iter()
            .find(|entry| entry.address == address)
            .ok_or_else(|| AccountResponseError::AddressNotRequested(address.to_owned()))?;
        entry
            .account
            .as_ref()
            .ok_or_else(|| AccountResponseError::AccountAbsentAtSlot(address.to_owned()))
    }
}

/// The exact block clock a `getBlock` response states for one slot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BlockClock {
    /// The slot this crate asked about. The response body does not restate it.
    pub slot: u64,
    /// Whole-second chain timestamp. The provider states no sub-second component.
    pub block_time_unix_s: i64,
    pub block_height: Option<u64>,
    pub blockhash: String,
}

/// Refusals from reading a retained Solana JSON-RPC response body.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum AccountResponseError {
    #[error("retained response body is not JSON")]
    NotJson,
    #[error("provider returned JSON-RPC error code {0:?}; message withheld")]
    JsonRpcError(Option<i64>),
    #[error("retained response body states no result")]
    MissingResult,
    #[error("retained response body states no result.context.slot")]
    MissingContextSlot,
    #[error("retained response body states {found} account values for {requested} addresses")]
    ValueArity { requested: usize, found: usize },
    #[error("account value field {0} is missing or not the stated type")]
    MalformedAccountField(&'static str),
    #[error("account data is not the base64 encoding this reader requested")]
    DataEncodingNotBase64,
    #[error("account data is not valid base64")]
    InvalidBase64,
    #[error("address {0} is not covered by this response")]
    AddressNotRequested(String),
    #[error("provider states account {0} does not exist at this slot")]
    AccountAbsentAtSlot(String),
    #[error("retained block body states no {0}")]
    MissingBlockField(&'static str),
}

/// Reads a `getMultipleAccounts` response over the exact address list that was requested.
///
/// The requested addresses are supplied by the caller because the response body does not restate
/// them; pairing is positional, exactly as the JSON-RPC method defines it.
///
/// # Errors
///
/// Refuses a non-JSON body, a JSON-RPC error, a missing context slot, an arity mismatch between
/// the requested addresses and the returned values, and any malformed account value.
pub fn read_multiple_accounts(
    body: &[u8],
    requested: &[String],
) -> Result<AccountSetResponse, AccountResponseError> {
    let result = result_of(body)?;
    let context_slot = context_slot(&result)?;
    let values = result
        .get("value")
        .and_then(Value::as_array)
        .ok_or(AccountResponseError::MalformedAccountField("value"))?;
    if values.len() != requested.len() {
        return Err(AccountResponseError::ValueArity {
            requested: requested.len(),
            found: values.len(),
        });
    }
    let entries = requested
        .iter()
        .zip(values)
        .map(|(address, value)| {
            Ok(AccountEntry {
                address: address.clone(),
                account: read_account_value(address, value)?,
            })
        })
        .collect::<Result<Vec<_>, AccountResponseError>>()?;
    Ok(AccountSetResponse {
        context_slot,
        entries,
    })
}

/// Reads a single-account `getAccountInfo` response for one requested address.
///
/// # Errors
///
/// Refuses the same conditions as [`read_multiple_accounts`].
pub fn read_account_info(
    body: &[u8],
    requested: &str,
) -> Result<AccountSetResponse, AccountResponseError> {
    let result = result_of(body)?;
    let context_slot = context_slot(&result)?;
    let value = result
        .get("value")
        .ok_or(AccountResponseError::MalformedAccountField("value"))?;
    Ok(AccountSetResponse {
        context_slot,
        entries: vec![AccountEntry {
            address: requested.to_owned(),
            account: read_account_value(requested, value)?,
        }],
    })
}

/// Reads the whole-second chain clock a `getBlock` response states for one slot.
///
/// # Errors
///
/// Refuses a non-JSON body, a JSON-RPC error, and a body that states no `blockTime`.
pub fn read_block_clock(body: &[u8], slot: u64) -> Result<BlockClock, AccountResponseError> {
    let result = result_of(body)?;
    let block_time_unix_s = result
        .get("blockTime")
        .and_then(Value::as_i64)
        .ok_or(AccountResponseError::MissingBlockField("blockTime"))?;
    let blockhash = result
        .get("blockhash")
        .and_then(Value::as_str)
        .ok_or(AccountResponseError::MissingBlockField("blockhash"))?
        .to_owned();
    Ok(BlockClock {
        slot,
        block_time_unix_s,
        block_height: result.get("blockHeight").and_then(Value::as_u64),
        blockhash,
    })
}

fn result_of(body: &[u8]) -> Result<Value, AccountResponseError> {
    let parsed: Value = serde_json::from_slice(body).map_err(|_| AccountResponseError::NotJson)?;
    if let Some(error) = parsed.get("error") {
        return Err(AccountResponseError::JsonRpcError(
            error.get("code").and_then(Value::as_i64),
        ));
    }
    parsed
        .get("result")
        .cloned()
        .ok_or(AccountResponseError::MissingResult)
}

fn context_slot(result: &Value) -> Result<u64, AccountResponseError> {
    result
        .pointer("/context/slot")
        .and_then(Value::as_u64)
        .ok_or(AccountResponseError::MissingContextSlot)
}

fn read_account_value(
    address: &str,
    value: &Value,
) -> Result<Option<RetainedAccount>, AccountResponseError> {
    if value.is_null() {
        return Ok(None);
    }
    let owner = value
        .get("owner")
        .and_then(Value::as_str)
        .ok_or(AccountResponseError::MalformedAccountField("owner"))?
        .to_owned();
    let lamports = value
        .get("lamports")
        .and_then(Value::as_u64)
        .ok_or(AccountResponseError::MalformedAccountField("lamports"))?;
    let executable = value
        .get("executable")
        .and_then(Value::as_bool)
        .ok_or(AccountResponseError::MalformedAccountField("executable"))?;
    let encoded = value
        .get("data")
        .and_then(Value::as_array)
        .ok_or(AccountResponseError::MalformedAccountField("data"))?;
    let [payload, encoding] = encoded.as_slice() else {
        return Err(AccountResponseError::MalformedAccountField("data"));
    };
    if encoding.as_str() != Some("base64") {
        return Err(AccountResponseError::DataEncodingNotBase64);
    }
    let payload = payload
        .as_str()
        .ok_or(AccountResponseError::MalformedAccountField("data"))?;
    let data = BASE64
        .decode(payload)
        .map_err(|_| AccountResponseError::InvalidBase64)?;
    Ok(Some(RetainedAccount {
        address: address.to_owned(),
        owner,
        lamports,
        executable,
        data,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    const MULTI: &str = r#"{"jsonrpc":"2.0","result":{"context":{"apiVersion":"3.0.0","slot":440672288},
        "value":[{"data":["AQID","base64"],"executable":false,"lamports":7,"owner":"OwnerOne",
        "rentEpoch":18446744073709551615,"space":3},null]},"id":1}"#;

    fn requested() -> Vec<String> {
        vec!["AddrOne".to_owned(), "AddrTwo".to_owned()]
    }

    #[test]
    fn a_multiple_account_response_keeps_exact_bytes_and_its_context_slot() {
        let parsed = read_multiple_accounts(MULTI.as_bytes(), &requested()).expect("decodes");
        assert_eq!(parsed.context_slot, 440_672_288);
        let account = parsed.require("AddrOne").expect("first account");
        assert_eq!(account.data, vec![1, 2, 3]);
        assert_eq!(account.owner, "OwnerOne");
        assert_eq!(account.lamports, 7);
    }

    #[test]
    fn a_null_account_is_an_absence_the_provider_stated_not_a_decode_failure() {
        let parsed = read_multiple_accounts(MULTI.as_bytes(), &requested()).expect("decodes");
        assert_eq!(parsed.entries[1].account, None);
        assert_eq!(
            parsed.require("AddrTwo"),
            Err(AccountResponseError::AccountAbsentAtSlot(
                "AddrTwo".to_owned()
            ))
        );
    }

    #[test]
    fn an_arity_mismatch_is_refused_rather_than_silently_zipped() {
        let one = vec!["AddrOne".to_owned()];
        assert_eq!(
            read_multiple_accounts(MULTI.as_bytes(), &one),
            Err(AccountResponseError::ValueArity {
                requested: 1,
                found: 2
            })
        );
    }

    #[test]
    fn a_provider_error_is_reported_by_code_and_never_by_message() {
        let body = br#"{"jsonrpc":"2.0","error":{"code":-32602,
            "message":"bad https://mainnet.helius-rpc.com/?api-key=SECRET"},"id":1}"#;
        let refusal = read_multiple_accounts(body, &requested()).expect_err("refuses");
        assert_eq!(refusal, AccountResponseError::JsonRpcError(Some(-32_602)));
        let rendered = format!("{refusal} {refusal:?}");
        assert!(!rendered.contains("api-key"));
        assert!(!rendered.contains("helius"));
    }

    #[test]
    fn a_non_base64_encoding_is_refused_because_this_reader_asked_for_base64() {
        let body = br#"{"jsonrpc":"2.0","result":{"context":{"slot":1},
            "value":{"data":["AQID","base58"],"executable":false,"lamports":1,"owner":"o"}},"id":1}"#;
        assert_eq!(
            read_account_info(body, "AddrOne"),
            Err(AccountResponseError::DataEncodingNotBase64)
        );
    }

    #[test]
    fn a_block_response_states_a_whole_second_chain_clock() {
        let body = br#"{"jsonrpc":"2.0","result":{"blockHeight":418721947,
            "blockTime":1787310191,"blockhash":"Anu2Rp23iCVqLacqjVW4Q1muk9cgvcLFndohMEFG3CbM",
            "parentSlot":440672287,"previousBlockhash":"5uxZAdWeybCJk3H7ujDguUQY1XNHf7ETyVNzQMpcnDRm"},"id":1}"#;
        let clock = read_block_clock(body, 440_672_288).expect("decodes");
        assert_eq!(clock.block_time_unix_s, 1_787_310_191);
        assert_eq!(clock.block_height, Some(418_721_947));
        assert_eq!(clock.slot, 440_672_288);
    }

    #[test]
    fn a_block_without_a_time_is_a_named_gap() {
        let body = br#"{"jsonrpc":"2.0","result":{"blockhash":"h","parentSlot":1},"id":1}"#;
        assert_eq!(
            read_block_clock(body, 2),
            Err(AccountResponseError::MissingBlockField("blockTime"))
        );
    }
}
