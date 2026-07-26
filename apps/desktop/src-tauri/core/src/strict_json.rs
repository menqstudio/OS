//! Strict JSON parser used by the Wave 3b trust boundary.
//!
//! It rejects duplicate object keys and floating-point numbers, then requires the
//! input bytes to equal the compact, sorted-key serialization of the parsed value.
//! The governed protocols use only ASCII object keys, strings, booleans, arrays and
//! non-negative integers, so this is the RFC-8785/JCS representation for their domain.

use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Number, Value};
use std::fmt;

struct StrictValue(Value);

impl<'de> Deserialize<'de> for StrictValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct V;
        impl<'de> Visitor<'de> for V {
            type Value = StrictValue;

            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("strict JSON without duplicate keys or floating-point numbers")
            }
            fn visit_bool<E>(self, v: bool) -> Result<Self::Value, E> {
                Ok(StrictValue(Value::Bool(v)))
            }
            fn visit_u64<E>(self, v: u64) -> Result<Self::Value, E> {
                Ok(StrictValue(Value::Number(Number::from(v))))
            }
            fn visit_i64<E>(self, v: i64) -> Result<Self::Value, E>
            where E: de::Error {
                if v < 0 {
                    return Err(E::custom("negative numbers are not allowed"));
                }
                Ok(StrictValue(Value::Number(Number::from(v))))
            }
            fn visit_f64<E>(self, _v: f64) -> Result<Self::Value, E>
            where E: de::Error {
                Err(E::custom("floating-point numbers are not allowed"))
            }
            fn visit_str<E>(self, v: &str) -> Result<Self::Value, E>
            where E: de::Error {
                Ok(StrictValue(Value::String(v.to_string())))
            }
            fn visit_string<E>(self, v: String) -> Result<Self::Value, E> {
                Ok(StrictValue(Value::String(v)))
            }
            fn visit_none<E>(self) -> Result<Self::Value, E> {
                Ok(StrictValue(Value::Null))
            }
            fn visit_unit<E>(self) -> Result<Self::Value, E> {
                Ok(StrictValue(Value::Null))
            }
            fn visit_seq<A>(self, mut seq: A) -> Result<Self::Value, A::Error>
            where A: SeqAccess<'de> {
                let mut out = Vec::new();
                while let Some(value) = seq.next_element::<StrictValue>()? {
                    out.push(value.0);
                }
                Ok(StrictValue(Value::Array(out)))
            }
            fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
            where A: MapAccess<'de> {
                let mut out = Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if out.contains_key(&key) {
                        return Err(de::Error::custom(format!("duplicate key `{key}`")));
                    }
                    let value = map.next_value::<StrictValue>()?;
                    out.insert(key, value.0);
                }
                Ok(StrictValue(Value::Object(out)))
            }
        }
        deserializer.deserialize_any(V)
    }
}

pub fn parse_canonical(bytes: &[u8], max_bytes: usize) -> Result<Value, String> {
    if bytes.len() > max_bytes {
        return Err(format!("JSON document is {} bytes, over the {max_bytes}-byte cap", bytes.len()));
    }
    let mut de = serde_json::Deserializer::from_slice(bytes);
    let parsed = StrictValue::deserialize(&mut de).map_err(|e| e.to_string())?.0;
    de.end().map_err(|e| e.to_string())?;
    let canonical = serde_json::to_vec(&parsed).map_err(|e| e.to_string())?;
    if canonical != bytes {
        return Err("JSON document is not canonical JCS".to_string());
    }
    Ok(parsed)
}

pub fn canonical_bytes(value: &Value) -> Result<Vec<u8>, String> {
    serde_json::to_vec(value).map_err(|e| e.to_string())
}

pub fn exact_object<'a>(
    value: &'a Value,
    required: &[&str],
    name: &str,
) -> Result<&'a Map<String, Value>, String> {
    let object = value.as_object().ok_or_else(|| format!("{name} must be an object"))?;
    if object.len() != required.len() {
        return Err(format!("{name} has an unexpected field count"));
    }
    for field in required {
        if !object.contains_key(*field) {
            return Err(format!("{name} is missing `{field}`"));
        }
    }
    Ok(object)
}

pub fn string<'a>(object: &'a Map<String, Value>, field: &str, max: usize) -> Result<&'a str, String> {
    let value = object.get(field).and_then(Value::as_str)
        .ok_or_else(|| format!("`{field}` must be a string"))?;
    if value.is_empty() || value.len() > max {
        return Err(format!("`{field}` must be 1..={max} bytes"));
    }
    Ok(value)
}

pub fn u64_value(object: &Map<String, Value>, field: &str) -> Result<u64, String> {
    object.get(field).and_then(Value::as_u64)
        .ok_or_else(|| format!("`{field}` must be a non-negative integer"))
}

pub fn bool_value(object: &Map<String, Value>, field: &str) -> Result<bool, String> {
    object.get(field).and_then(Value::as_bool)
        .ok_or_else(|| format!("`{field}` must be a boolean"))
}

pub fn lower_hex_64(value: &str, field: &str) -> Result<(), String> {
    if value.len() != 64 || !value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
        return Err(format!("`{field}` must be lowercase 64-hex"));
    }
    Ok(())
}
