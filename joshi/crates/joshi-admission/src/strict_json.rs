use serde::{
    Deserialize,
    de::{self, DeserializeOwned, MapAccess, SeqAccess, Visitor},
};
use serde_json::{Map, Number, Value};
use std::{collections::BTreeSet, fmt};
use thiserror::Error;

/// Parsed JSON that retained object order long enough to reconstruct a source-owned digest.
#[derive(Clone, Debug, PartialEq)]
pub enum StrictNode {
    Null,
    Bool(bool),
    Number(Number),
    String(String),
    Array(Vec<Self>),
    Object(Vec<(String, Self)>),
}

impl StrictNode {
    /// Encode this validated tree as compact JSON while preserving object member order.
    ///
    /// # Errors
    ///
    /// Returns an error if a string cannot be encoded as JSON.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, StrictJsonError> {
        let mut output = String::new();
        self.write_compact(&mut output)?;
        Ok(output.into_bytes())
    }

    /// Find an object member by its exact name.
    #[must_use]
    pub fn object_member(&self, name: &str) -> Option<&Self> {
        let Self::Object(entries) = self else {
            return None;
        };
        entries
            .iter()
            .find_map(|(key, value)| (key == name).then_some(value))
    }

    /// Rebuild a compact object containing exactly the named members in the supplied order.
    ///
    /// # Errors
    ///
    /// Returns an error when this is not an object, a member is absent, or encoding fails.
    pub fn canonical_object_members(&self, names: &[&str]) -> Result<Vec<u8>, StrictJsonError> {
        let mut output = String::from("{");
        for (index, name) in names.iter().enumerate() {
            let value = self
                .object_member(name)
                .ok_or_else(|| StrictJsonError::MissingDigestField((*name).to_owned()))?;
            if index != 0 {
                output.push(',');
            }
            output.push_str(&serde_json::to_string(name)?);
            output.push(':');
            value.write_compact(&mut output)?;
        }
        output.push('}');
        Ok(output.into_bytes())
    }

    fn write_compact(&self, output: &mut String) -> Result<(), serde_json::Error> {
        match self {
            Self::Null => output.push_str("null"),
            Self::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
            Self::Number(value) => output.push_str(&value.to_string()),
            Self::String(value) => output.push_str(&serde_json::to_string(value)?),
            Self::Array(values) => {
                output.push('[');
                for (index, value) in values.iter().enumerate() {
                    if index != 0 {
                        output.push(',');
                    }
                    value.write_compact(output)?;
                }
                output.push(']');
            }
            Self::Object(entries) => {
                output.push('{');
                for (index, (key, value)) in entries.iter().enumerate() {
                    if index != 0 {
                        output.push(',');
                    }
                    output.push_str(&serde_json::to_string(key)?);
                    output.push(':');
                    value.write_compact(output)?;
                }
                output.push('}');
            }
        }
        Ok(())
    }

    fn into_value(self) -> Value {
        match self {
            Self::Null => Value::Null,
            Self::Bool(value) => Value::Bool(value),
            Self::Number(value) => Value::Number(value),
            Self::String(value) => Value::String(value),
            Self::Array(values) => Value::Array(values.into_iter().map(Self::into_value).collect()),
            Self::Object(entries) => Value::Object(
                entries
                    .into_iter()
                    .map(|(key, value)| (key, value.into_value()))
                    .collect::<Map<_, _>>(),
            ),
        }
    }
}

impl<'de> Deserialize<'de> for StrictNode {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        deserializer.deserialize_any(NodeVisitor)
    }
}

struct NodeVisitor;

impl<'de> Visitor<'de> for NodeVisitor {
    type Value = StrictNode;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON value without duplicate or dangerous object keys")
    }

    fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
        Ok(StrictNode::Bool(value))
    }
    fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E> {
        Ok(StrictNode::Number(value.into()))
    }
    fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E> {
        Ok(StrictNode::Number(value.into()))
    }
    fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        Number::from_f64(value)
            .map(StrictNode::Number)
            .ok_or_else(|| E::custom("non-finite JSON number"))
    }
    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E> {
        Ok(StrictNode::String(value.to_owned()))
    }
    fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
        Ok(StrictNode::String(value))
    }
    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(StrictNode::Null)
    }
    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(StrictNode::Null)
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element()? {
            values.push(value);
        }
        Ok(StrictNode::Array(values))
    }

    fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut entries = Vec::new();
        let mut names = BTreeSet::new();
        while let Some((key, value)) = map.next_entry::<String, StrictNode>()? {
            if matches!(key.as_str(), "__proto__" | "constructor" | "prototype") {
                return Err(de::Error::custom(format!(
                    "dangerous JSON object key: {key}"
                )));
            }
            if !names.insert(key.clone()) {
                return Err(de::Error::custom(format!(
                    "duplicate JSON object key: {key}"
                )));
            }
            entries.push((key, value));
        }
        Ok(StrictNode::Object(entries))
    }
}

/// Parse bounded JSON without collapsing duplicate or dangerous object keys.
///
/// # Errors
///
/// Returns an error for empty, oversized, malformed, duplicate-key, or dangerous-key input.
pub fn parse_node(bytes: &[u8], maximum: usize) -> Result<StrictNode, StrictJsonError> {
    if bytes.len() > maximum {
        return Err(StrictJsonError::TooLarge {
            actual: bytes.len(),
            maximum,
        });
    }
    if bytes.is_empty() {
        return Err(StrictJsonError::Empty);
    }
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let node = StrictNode::deserialize(&mut deserializer)?;
    deserializer.end()?;
    Ok(node)
}

/// Decode an already validated strict tree into a closed wire type.
///
/// # Errors
///
/// Returns an error when the tree does not satisfy the target type's schema.
pub fn decode_node<T: DeserializeOwned>(node: StrictNode) -> Result<T, StrictJsonError> {
    serde_json::from_value(node.into_value()).map_err(Into::into)
}

/// Strictly parse and decode a bounded JSON message.
///
/// # Errors
///
/// Returns an error when strict parsing or target-schema validation fails.
pub fn parse<T: DeserializeOwned>(bytes: &[u8], maximum: usize) -> Result<T, StrictJsonError> {
    decode_node(parse_node(bytes, maximum)?)
}

#[derive(Debug, Error)]
pub enum StrictJsonError {
    #[error("JSON body is empty")]
    Empty,
    #[error("JSON body is {actual} bytes; maximum is {maximum}")]
    TooLarge { actual: usize, maximum: usize },
    #[error("digest material is missing required field {0}")]
    MissingDigestField(String),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
