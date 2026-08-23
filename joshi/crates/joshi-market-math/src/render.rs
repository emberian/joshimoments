//! Deterministic JSON rendering in which every integer is a string.
//!
//! A `u128` reserve or a `u64` atom count does not survive a JSON number in every reader, and an
//! artifact whose numbers change meaning when reparsed is not evidence. These helpers render
//! objects with caller-controlled key order and no dependency on any serializer's defaults, so an
//! artifact's bytes are a function of its values and nothing else. [`crate::would_quote`] and the
//! paper-episode artifact both render through here.

use core::fmt::Write as _;

/// One JSON object with keys in exactly the given order.
#[must_use]
pub fn object(pairs: &[(&str, String)]) -> String {
    let mut out = String::from("{");
    for (index, (key, value)) in pairs.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        out.push_str(&quoted(key));
        out.push(':');
        out.push_str(value);
    }
    out.push('}');
    out
}

/// One JSON array in exactly the given order.
#[must_use]
pub fn array(items: &[String]) -> String {
    let mut out = String::from("[");
    for (index, item) in items.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        out.push_str(item);
    }
    out.push(']');
    out
}

/// An integer rendered as a JSON string, so reparsing cannot lose width or sign.
#[must_use]
pub fn integer(value: &impl ToString) -> String {
    quoted(&value.to_string())
}

/// A JSON string with every control character and quote escaped.
#[must_use]
pub fn quoted(value: &str) -> String {
    let mut out = String::with_capacity(value.len() + 2);
    out.push('"');
    for character in value.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            control if control < ' ' => {
                let _ = write!(out, "\\u{:04x}", u32::from(control));
            }
            other => out.push(other),
        }
    }
    out.push('"');
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn json_strings_escape_every_control_character_and_quote() {
        assert_eq!(quoted("a\"b\\c\nd\u{1}"), "\"a\\\"b\\\\c\\nd\\u0001\"");
    }

    #[test]
    fn every_integer_renders_as_a_string_so_reparsing_cannot_lose_width() {
        assert_eq!(
            integer(&u128::MAX),
            "\"340282366920938463463374607431768211455\""
        );
        assert_eq!(integer(&-1_i64), "\"-1\"");
    }

    #[test]
    fn objects_keep_the_caller_key_order() {
        assert_eq!(
            object(&[("z", integer(&1)), ("a", quoted("x"))]),
            "{\"z\":\"1\",\"a\":\"x\"}"
        );
        assert_eq!(array(&[integer(&1), quoted("x")]), "[\"1\",\"x\"]");
    }
}
