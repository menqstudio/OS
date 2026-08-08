//! The exact byte-for-byte serialization `engine/runtime/bro_signature.py` signs over.
//!
//! ```python
//! def canonical_bytes(value: dict[str, Any]) -> bytes:
//!     return json.dumps(value, sort_keys=True, separators=(",", ":"),
//!                       ensure_ascii=False).encode("utf-8")
//! ```
//!
//! Every signature this crate produces is verified on the Python side against those
//! bytes, so a difference of one byte is a signature that does not verify — not a
//! cosmetic difference. That is why this is written out rather than delegated to
//! `serde_json::to_vec`:
//!
//! * `serde_json::Map` is a `BTreeMap` only while the `preserve_order` feature is off.
//!   Features are additive across a Cargo workspace, so any crate anywhere in the
//!   graph enabling it would silently switch this to insertion order. Keys are sorted
//!   here, explicitly, at every level.
//! * `serde_json` writes floats; Python's `repr` for floats does not agree with it in
//!   general. Non-integer numbers are therefore REFUSED rather than serialized — no
//!   payload in this crate has one.
//! * `ensure_ascii=False` means Python emits non-ASCII verbatim. `serde_json` does too
//!   today, but it would be free to change that; the escaping rule is pinned here to
//!   Python's `json.encoder.ESCAPE` set: the quote, the backslash, and U+0000..U+001F.
//!
//! Key ordering: Python sorts `str` by Unicode code point. Rust's `str: Ord` compares
//! UTF-8 bytes, and UTF-8 byte order equals code-point order for all well-formed
//! strings, so sorting with `str::cmp` is the same ordering.
//!
//! **A test cannot currently observe that sort, and this says so rather than implying
//! otherwise.** Deleting `entries.sort_by(...)` leaves every test in this crate green,
//! because with `preserve_order` off `serde_json::Map` IS a `BTreeMap` and its
//! iteration order is already sorted — the explicit sort is insurance against a future
//! in which some crate in this workspace turns that feature on, and the only way to
//! make a test see it is to turn the feature on, which would change the production
//! build to prove a point about the production build. The mutation is recorded as a
//! known survivor instead of being deleted as "dead": the day it stops being dead is
//! the day every signature this crate produces would otherwise stop verifying.

use serde_json::Value;

/// A value this canonicalizer refuses to serialize, because Python would not produce
/// the same bytes for it. Never a silent best effort.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NonCanonical {
    pub path: String,
    pub reason: String,
}

impl std::fmt::Display for NonCanonical {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "cannot canonicalize {}: {}", self.path, self.reason)
    }
}

/// `json.dumps(value, sort_keys=True, separators=(",",":"), ensure_ascii=False)` as UTF-8.
pub fn canonical_bytes(value: &Value) -> Result<Vec<u8>, NonCanonical> {
    let mut out = Vec::with_capacity(256);
    write_value(value, "$", &mut out)?;
    Ok(out)
}

fn write_value(value: &Value, path: &str, out: &mut Vec<u8>) -> Result<(), NonCanonical> {
    match value {
        Value::Null => out.extend_from_slice(b"null"),
        Value::Bool(true) => out.extend_from_slice(b"true"),
        Value::Bool(false) => out.extend_from_slice(b"false"),
        Value::Number(n) => {
            // Integers only. `json.dumps` writes an `int` with `repr`, which for any
            // integer is the plain decimal form serde_json also writes. Floats are
            // where the two diverge, so they are refused.
            if let Some(u) = n.as_u64() {
                out.extend_from_slice(u.to_string().as_bytes());
            } else if let Some(i) = n.as_i64() {
                out.extend_from_slice(i.to_string().as_bytes());
            } else {
                return Err(NonCanonical {
                    path: path.to_string(),
                    reason: format!(
                        "{n} is not an integer; Python and Rust do not agree on float text, so \
                         a float would sign bytes the verifier never reconstructs"
                    ),
                });
            }
        }
        Value::String(s) => write_string(s, out),
        Value::Array(items) => {
            out.push(b'[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                write_value(item, &format!("{path}[{i}]"), out)?;
            }
            out.push(b']');
        }
        Value::Object(map) => {
            let mut entries: Vec<(&String, &Value)> = map.iter().collect();
            entries.sort_by(|a, b| a.0.cmp(b.0));
            out.push(b'{');
            for (i, (key, item)) in entries.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                write_string(key, out);
                out.push(b':');
                write_value(item, &format!("{path}.{key}"), out)?;
            }
            out.push(b'}');
        }
    }
    Ok(())
}

/// Python's `json` string escaping with `ensure_ascii=False`: only the quote, the
/// backslash and the C0 controls are escaped; the five short forms are used where
/// Python uses them and every other control becomes `\u00xx` in lowercase hex.
fn write_string(s: &str, out: &mut Vec<u8>) {
    out.push(b'"');
    for ch in s.chars() {
        match ch {
            '"' => out.extend_from_slice(br#"\""#),
            '\\' => out.extend_from_slice(br"\\"),
            '\u{08}' => out.extend_from_slice(br"\b"),
            '\u{0c}' => out.extend_from_slice(br"\f"),
            '\n' => out.extend_from_slice(br"\n"),
            '\r' => out.extend_from_slice(br"\r"),
            '\t' => out.extend_from_slice(br"\t"),
            c if (c as u32) < 0x20 => {
                out.extend_from_slice(format!("\\u{:04x}", c as u32).as_bytes());
            }
            c => {
                let mut buf = [0u8; 4];
                out.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
            }
        }
    }
    out.push(b'"');
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn text(v: &Value) -> String {
        String::from_utf8(canonical_bytes(v).unwrap()).unwrap()
    }

    #[test]
    fn keys_are_sorted_at_every_level_and_separators_are_compact() {
        let v = json!({"b": 1, "a": {"z": 0, "y": [ {"q": 2, "p": 3} ]}});
        assert_eq!(text(&v), r#"{"a":{"y":[{"p":3,"q":2}],"z":0},"b":1}"#);
    }

    #[test]
    fn escaping_matches_pythons_ensure_ascii_false_set() {
        // Quote and backslash escaped; the five short forms; other C0 as \u00xx;
        // DEL and non-ASCII verbatim, because ensure_ascii is False.
        let v = json!({"k": "a\"b\\c\u{08}\u{0c}\n\r\t\u{01}\u{7f}\u{e9}"});
        assert_eq!(
            text(&v),
            "{\"k\":\"a\\\"b\\\\c\\b\\f\\n\\r\\t\\u0001\u{7f}\u{e9}\"}"
        );
    }

    #[test]
    fn floats_are_refused_rather_than_silently_serialized() {
        let err = canonical_bytes(&json!({"x": 1.5})).unwrap_err();
        assert_eq!(err.path, "$.x");
        assert!(err.reason.contains("not an integer"), "{}", err.reason);
    }

    #[test]
    fn negative_and_large_integers_round_trip_as_plain_decimals() {
        assert_eq!(
            text(&json!({"a": -1, "b": 253402300799i64})),
            r#"{"a":-1,"b":253402300799}"#
        );
    }

    #[test]
    fn null_and_booleans_and_empty_containers() {
        assert_eq!(
            text(&json!({"a": null, "b": true, "c": false, "d": [], "e": {}})),
            r#"{"a":null,"b":true,"c":false,"d":[],"e":{}}"#
        );
    }
}
