//! Wave 3b-1B §4.10(g) — the trusted-side governed turn PREPARATION (`prepare_governed_turn_v1b`).
//!
//! This is the single immutable object-JCS-hash source the whole 3b-1B chain derives from, and it is
//! the Rust half of a formula whose Python half already ships (`engine/runtime/brops_canonical.py`
//! `governed_generation_config_bytes`). It exists because §4.10(g) forbids reusing the frozen
//! preparation, in as many words:
//!
//! > The frozen `prepare_governed_turn(system, messages, now_ms, workspace_id, install_id,
//! > generation_config: &str)` hashes `generation_config` as a **raw UTF-8 string** … The governed
//! > family instead requires `generation_config_sha256 = SHA256(JCS(flat string→string
//! > generation_config OBJECT))`. Those two hashes **differ**, so 3b-1B MUST NOT reuse the frozen
//! > `&str` preparation — otherwise … **every** legitimate turn Blocks.
//!
//! The two digests are asserted UNEQUAL by a test here, against the frozen fixture's own pinned hex
//! (`receipt.rs::brops_all_formula_parity_matches_python`), so "the frozen path is not silently
//! reused" is a checked claim rather than a comment. The frozen function, its constant and its
//! fixture are untouched (§2.2 KEEP + ADD).
//!
//! ## Which process this belongs to
//!
//! The BROKER service (§0 role #2), not the renderer-hosting Tauri app crate. §0's LOCKED
//! terminology binding resolves every trusted-actor "the desktop"/"backend" in the normative body to "the trusted
//! desktop verifier/BROKER service … in its OWN process, separate from the renderer", and §4.10(g)'s
//! Principal binding repeats it for this exact object: the broker "alone owns … the
//! `PreparedGovernedTurnV1B` object, all hashes/nonces". So this module lives in `brops-core` beside
//! `broker_orchestrator` / `broker_turns` / `governed_verification` — the crate whose broker-side
//! logic the `brops-broker` binary wires — and NOT in `apps/desktop/src-tauri/src/`, which is the
//! renderer-hosting process. `ai::governed_pull_output` is in this tree as the counter-example: it
//! was placed in the app crate by following §4.10(f)'s literal "a private function of the
//! `governed_turn_execute` command", and §0 says that command is a broker-service operation.
//!
//! ## Reuse, not a second spelling
//!
//! `receipt::jcs_bytes` is the already-parity-proven `BTreeMap<String,String>` serializer (Rust
//! `serde_json::to_vec` ↔ Python `json.dumps(sort_keys=True, separators=(",",":"))`), so this module
//! calls it rather than restating JCS. `receipt::IssuedRequest` / `request_envelope_sha256` are
//! likewise reused verbatim for `request_sha256`.
//!
//! ## Nothing here reads a clock, a socket or a file
//!
//! `resolve_governed_generation_config_v1b` is the ONE function that touches the process
//! environment, and it does it through [`resolve_governed_generation_config_from`] so the whole
//! override contract is testable without mutating a global.

use std::collections::BTreeMap;

use crate::receipt::{jcs_bytes, sha256_hex, IssuedRequest};

// =================================================================================================
// §4.10(g) caps — the ingress bounds, mirrored from the real desktop code
// =================================================================================================

/// §4.10(g) `MAX_SYSTEM_BYTES`. Mirrors `ai.rs`'s cap of the same name; an `ai.rs` test asserts the
/// two literals are equal, so a change on either side turns the other RED.
pub const MAX_SYSTEM_BYTES: usize = 262_144;
/// §4.10(g) `MAX_CONVERSATION_BYTES` — the cap on `JCS(history)`, not on the sum of the contents.
pub const MAX_CONVERSATION_BYTES: usize = 8_388_608;
/// §4.10(g) `MAX_MESSAGES`.
pub const MAX_MESSAGES: usize = 1_000;
/// §4.10(g) `MAX_MESSAGE_BYTES` — per `content`, in encoded UTF-8 bytes.
pub const MAX_MESSAGE_BYTES: usize = 1_048_576;

/// §4.10(g)'s cap on `JCS(generation_config)`, a NEW 3b-1B constant (NOT an `ai.rs` cap).
///
/// **No check is written against it, and that is the arithmetic rather than an omission.** The
/// widest object the §4.10(g) field rules can express is 349 bytes — every value at its regex
/// maximum — so this cap is 187.8x away (`349 × 187 = 65263` fits, `349 × 188 = 65612` does
/// not) and cannot fire for any accepted input. The Python half rounds that to "a factor of
/// 188"; the exact integer ratio is 187, and the test below pins BOTH sides of it. Shipping
/// the check would read as protection while protecting nothing (the class §4.10(a)/(c) deleted
/// rather than shipped). The number is pinned by
/// `the_widest_expressible_config_is_349_bytes_against_a_65536_cap` instead, so widening a field
/// regex turns that test RED and the decision gets re-made deliberately. The Python half made the
/// identical call for the identical reason (`bridge/governed_turn_submit.py`, "One cap this module
/// does NOT write").
pub const MAX_GENERATION_CONFIG_BYTES: usize = 65_536;

/// §2.1/§4.1: every id is `<string ≤128>`.
pub const MAX_ID_LEN: usize = 128;

// =================================================================================================
// §4.10(g) — the five FROZEN LITERAL defaults (P0-2 LOCKED, no `e.g.`, no approximate value)
// =================================================================================================

/// `engine_id` — the frozen governed-engine id, reused verbatim from `commands.rs`'s
/// `GOVERNED_GENERATION_CONFIG`. **NOT overridable**: it pins the execution mechanism, so §4.10(g)
/// gives it no `BROPS_GOVERNED_*` variable at all.
pub const GOVERNED_ENGINE_ID: &str = "brops.governed-engine.sidecar.v1";
/// `model` — mirrors `ai.rs::DEFAULT_ANTHROPIC_MODEL` byte-for-byte.
pub const GOVERNED_MODEL: &str = "claude-sonnet-5";
/// `max_output_tokens` — the governed default. The ungoverned `1024` truncates a governed reply.
pub const GOVERNED_MAX_OUTPUT_TOKENS: &str = "4096";
/// `temperature` — greedy/deterministic decode.
pub const GOVERNED_TEMPERATURE: &str = "0.00";
/// `top_p` — full nucleus mass, pairs with `temperature = "0.00"`.
pub const GOVERNED_TOP_P: &str = "1.00";

/// The trusted-host override variable for `model`. Read ONLY from the broker's own process
/// environment — never the renderer, never the sidecar (§4.10(g) "Trusted-host override contract
/// (EXACT — P0-2 LOCKED)").
pub const GOVERNED_MODEL_ENV: &str = "BROPS_GOVERNED_MODEL";
/// See [`GOVERNED_MODEL_ENV`].
pub const GOVERNED_MAX_OUTPUT_TOKENS_ENV: &str = "BROPS_GOVERNED_MAX_OUTPUT_TOKENS";
/// See [`GOVERNED_MODEL_ENV`].
pub const GOVERNED_TEMPERATURE_ENV: &str = "BROPS_GOVERNED_TEMPERATURE";
/// See [`GOVERNED_MODEL_ENV`].
pub const GOVERNED_TOP_P_ENV: &str = "BROPS_GOVERNED_TOP_P";

/// The closed field set, `additionalProperties:false`, in JCS (lexicographic) order — which is also
/// the order the canonical bytes come out in, so the constant and the wire agree by construction.
pub const GOVERNED_GENERATION_CONFIG_FIELDS: [&str; 5] =
    ["engine_id", "max_output_tokens", "model", "temperature", "top_p"];

/// §4.10(g)'s closed `role` enum for a `history` entry.
pub const HISTORY_ROLES: [&str; 3] = ["user", "assistant", "system"];

// =================================================================================================
// Refusals — a closed enum, each reachable BY NAME
// =================================================================================================

/// Why a governed preparation refused. §4.10(g) writes the signature as `Result<…, String>`; this is
/// a typed closed enum instead, for the reason every other refusal set in this crate is one
/// (`TurnReason`, `PullError`, `FrameError`, `StreamRefusal`): a caller can match it, a test can
/// demand a specific member, and a reason cannot be spelled two ways. [`PrepareError::as_str`] gives
/// the stable machine name a Block string would carry, so nothing is lost against the `String` form.
///
/// Every member below is produced by a test in this module.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PrepareError {
    /// `generation_config` is missing a field or carries an unknown one.
    ConfigFieldSet,
    /// A `generation_config` value failed its §4.10(g) regex — exponent form, signed zero, a
    /// precision mismatch, a leading zero, an out-of-alphabet character, or an over-long id.
    ConfigFieldInvalid(&'static str),
    /// A `generation_config` value passed its regex and failed its INTEGER range check. Separate
    /// from the above because `"2.99"` and `"1048577"` are exactly the inputs a regex-only gate
    /// admits, and a test that cannot tell the two refusals apart cannot prove the range check runs.
    ConfigFieldOutOfRange(&'static str),
    /// A `BROPS_GOVERNED_*` override was set to an invalid value. §4.10(g): "a set-but-invalid value
    /// ⇒ the resolver returns `Err` … (fail-closed, never silently defaulted)".
    ConfigOverrideInvalid(&'static str),
    /// `system` exceeds [`MAX_SYSTEM_BYTES`].
    SystemOversize,
    /// `history` carries more than [`MAX_MESSAGES`] entries.
    HistoryTooManyMessages,
    /// One `content` exceeds [`MAX_MESSAGE_BYTES`].
    MessageOversize,
    /// `JCS(history)` exceeds [`MAX_CONVERSATION_BYTES`].
    ConversationOversize,
    /// A `history` entry names a role outside [`HISTORY_ROLES`].
    HistoryRoleInvalid,
    /// `workspace_id` / `install_id` is empty or over [`MAX_ID_LEN`].
    IdInvalid(&'static str),
}

impl PrepareError {
    /// The stable machine name. These are LOCAL preparation refusals, deliberately disjoint from
    /// §4.5's `GOVERNED_REFUSAL_REASONS` and from §4.10(h)'s (**NOT IMPLEMENTED**) internal set: nothing here is a
    /// supervisor verdict, because no supervisor has been contacted when any of them fires.
    pub fn as_str(&self) -> &'static str {
        match self {
            PrepareError::ConfigFieldSet => "config_field_set",
            PrepareError::ConfigFieldInvalid(_) => "config_field_invalid",
            PrepareError::ConfigFieldOutOfRange(_) => "config_field_out_of_range",
            PrepareError::ConfigOverrideInvalid(_) => "config_override_invalid",
            PrepareError::SystemOversize => "system_oversize",
            PrepareError::HistoryTooManyMessages => "history_too_many_messages",
            PrepareError::MessageOversize => "message_oversize",
            PrepareError::ConversationOversize => "conversation_oversize",
            PrepareError::HistoryRoleInvalid => "history_role_invalid",
            PrepareError::IdInvalid(_) => "id_invalid",
        }
    }

    /// The field the refusal is about, where there is one.
    pub fn field(&self) -> Option<&'static str> {
        match self {
            PrepareError::ConfigFieldInvalid(f)
            | PrepareError::ConfigFieldOutOfRange(f)
            | PrepareError::ConfigOverrideInvalid(f)
            | PrepareError::IdInvalid(f) => Some(f),
            _ => None,
        }
    }
}

impl std::fmt::Display for PrepareError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self.field() {
            Some(field) => write!(f, "{}:{}", self.as_str(), field),
            None => f.write_str(self.as_str()),
        }
    }
}

// =================================================================================================
// The §4.10(g) field rules — hand-written, because `brops-core` has no regex dependency
// =================================================================================================
//
// Five character classes and two integer ranges do not justify pulling a regex engine into the
// verification core, and a hand-written matcher over a fixed ASCII class is exactly as auditable as
// the pattern it implements. Each function below carries the pattern it implements, and
// `the_field_rules_accept_and_refuse_exactly_the_designs_examples` drives every accept/reject
// example §4.10(g) lists for the mandatory parity fixture.

/// `^[A-Za-z0-9._-]{1,128}$`
fn is_engine_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_ID_LEN
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
}

/// `^[A-Za-z0-9._:-]{1,128}$` — the model class is the engine class plus `:`.
fn is_model(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_ID_LEN
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-' | b':'))
}

/// `^[1-9][0-9]{0,6}$` — a canonical decimal integer, no leading zero, 1..=7 digits.
fn is_canonical_integer(value: &str) -> bool {
    let b = value.as_bytes();
    (1..=7).contains(&b.len())
        && b[0].is_ascii_digit()
        && b[0] != b'0'
        && b[1..].iter().all(u8::is_ascii_digit)
}

/// `^[0-2]\.[0-9]{2}$` (`high_digit = b'2'`) or `^[01]\.[0-9]{2}$` (`high_digit = b'1'`).
///
/// Exactly one integer digit, a dot, exactly two fraction digits. That shape is what makes
/// [`hundredths`] a lookup rather than a parse: it cannot see an exponent, a sign, or a third
/// fraction digit, so no float ever exists on this path — which is the whole reason §4.10(g)
/// replaced the JSON number with a string.
fn is_fixed_point(value: &str, high_digit: u8) -> bool {
    let b = value.as_bytes();
    b.len() == 4
        && (b'0'..=high_digit).contains(&b[0])
        && b[1] == b'.'
        && b[2].is_ascii_digit()
        && b[3].is_ascii_digit()
}

/// `"1.25"` → `125`, by digits. Only ever called on a value [`is_fixed_point`] has accepted.
fn hundredths(value: &str) -> u32 {
    let b = value.as_bytes();
    u32::from(b[0] - b'0') * 100 + u32::from(b[2] - b'0') * 10 + u32::from(b[3] - b'0')
}

/// One field, validated §4.10(g)-exactly: shape FIRST, then the integer range on the DIGITS.
///
/// The two are separate refusals on purpose. `"2.99"` for `temperature` and `"1048577"` for
/// `max_output_tokens` both pass their regex and fail their bound, so a suite that could not tell
/// `ConfigFieldInvalid` from `ConfigFieldOutOfRange` could not prove the bound is applied at all.
fn validate_field(field: &'static str, value: &str) -> Result<(), PrepareError> {
    let shape_ok = match field {
        "engine_id" => is_engine_id(value),
        "model" => is_model(value),
        "max_output_tokens" => is_canonical_integer(value),
        "temperature" => is_fixed_point(value, b'2'),
        "top_p" => is_fixed_point(value, b'1'),
        _ => false,
    };
    if !shape_ok {
        return Err(PrepareError::ConfigFieldInvalid(field));
    }
    let in_range = match field {
        // `is_canonical_integer` caps the length at 7 digits, so this parse cannot overflow u32.
        "max_output_tokens" => (1..=1_048_576).contains(&value.parse::<u32>().unwrap_or(0)),
        "temperature" => hundredths(value) <= 200,
        "top_p" => hundredths(value) <= 100,
        _ => true,
    };
    if !in_range {
        return Err(PrepareError::ConfigFieldOutOfRange(field));
    }
    Ok(())
}

// =================================================================================================
// The validated flat string→string object
// =================================================================================================

/// The §4.10(g) `generation_config`: a CLOSED FLAT string→string object, validated once and then
/// immutable.
///
/// Fields are private and there is no mutator, so the only way to hold one is through
/// [`GovernedGenerationConfig::validate`] or [`resolve_governed_generation_config_v1b`] — an
/// unvalidated value has no path to a digest, which is the same property
/// `brops_canonical.governed_generation_config_bytes` gets by validating inside the byte formula.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GovernedGenerationConfig {
    engine_id: String,
    max_output_tokens: String,
    model: String,
    temperature: String,
    top_p: String,
}

impl GovernedGenerationConfig {
    /// Validate a candidate flat object into the closed form, or refuse.
    ///
    /// `fields` must carry EXACTLY [`GOVERNED_GENERATION_CONFIG_FIELDS`]: an extra key is as fatal
    /// as a missing one, because JCS would silently hash it and the authority's committed digest
    /// would then disagree with the staged one — a `handle_not_challenge` on a turn nobody tampered
    /// with.
    pub fn validate(fields: &BTreeMap<String, String>) -> Result<Self, PrepareError> {
        if fields.len() != GOVERNED_GENERATION_CONFIG_FIELDS.len()
            || !GOVERNED_GENERATION_CONFIG_FIELDS
                .iter()
                .all(|f| fields.contains_key(*f))
        {
            return Err(PrepareError::ConfigFieldSet);
        }
        for field in GOVERNED_GENERATION_CONFIG_FIELDS {
            validate_field(field, &fields[field])?;
        }
        Ok(GovernedGenerationConfig {
            engine_id: fields["engine_id"].clone(),
            max_output_tokens: fields["max_output_tokens"].clone(),
            model: fields["model"].clone(),
            temperature: fields["temperature"].clone(),
            top_p: fields["top_p"].clone(),
        })
    }

    /// The object as the flat map JCS serializes. Private: the only public views are the canonical
    /// bytes, the digest, and the wire JSON, so no caller can hold a mutable copy of the object the
    /// digest was taken over (§4.10(g) "Encapsulation enforcement").
    fn as_map(&self) -> BTreeMap<String, String> {
        let mut map = BTreeMap::new();
        map.insert("engine_id".to_string(), self.engine_id.clone());
        map.insert("max_output_tokens".to_string(), self.max_output_tokens.clone());
        map.insert("model".to_string(), self.model.clone());
        map.insert("temperature".to_string(), self.temperature.clone());
        map.insert("top_p".to_string(), self.top_p.clone());
        map
    }

    /// `generation_config_bytes = JCS(object)` — the GOVERNED formula (§4.10(g)).
    ///
    /// This rides `receipt::jcs_bytes`, the `BTreeMap<String,String>` serializer already proven
    /// byte-identical to Python `bro_signature.canonical_bytes`. It is emphatically NOT
    /// `generation_config.as_bytes()`: that is the FROZEN formula, it produces a different digest,
    /// and §4.10(g) says reusing it Blocks every legitimate turn.
    pub fn jcs(&self) -> Vec<u8> {
        jcs_bytes(&self.as_map())
    }

    /// `generation_config_sha256 = SHA256(JCS(object))` — the digest the §4.1 challenge commits and
    /// §2.4 staging re-derives from the uploaded bytes.
    pub fn sha256(&self) -> String {
        sha256_hex(&self.jcs())
    }

    /// The `generation_config` value as it rides the §4.10(g) submit frame: a JSON object of five
    /// strings, never a JSON number.
    pub fn to_json(&self) -> serde_json::Value {
        let mut object = serde_json::Map::new();
        for (key, value) in self.as_map() {
            object.insert(key, serde_json::Value::String(value));
        }
        serde_json::Value::Object(object)
    }

    /// §2/§4.3/§7: model identity is a pure formula, never a registry lookup.
    pub fn model_profile_id(&self) -> String {
        format!("cfg-sha256:{}", self.sha256())
    }

    /// Read-only accessor. There is no setter for this or any other field.
    pub fn engine_id(&self) -> &str {
        &self.engine_id
    }
    /// See [`GovernedGenerationConfig::engine_id`].
    pub fn model(&self) -> &str {
        &self.model
    }
    /// See [`GovernedGenerationConfig::engine_id`].
    pub fn max_output_tokens(&self) -> &str {
        &self.max_output_tokens
    }
    /// See [`GovernedGenerationConfig::engine_id`].
    pub fn temperature(&self) -> &str {
        &self.temperature
    }
    /// See [`GovernedGenerationConfig::engine_id`].
    pub fn top_p(&self) -> &str {
        &self.top_p
    }
}

/// The ONE trusted backend source of the full `generation_config` object (§4.10(g) P0-1(B) LOCKED).
///
/// Reads the four overridable fields from the broker's own process environment and nowhere else —
/// never the renderer, never the sidecar. An unset or EMPTY variable yields the frozen literal
/// default; a set-but-invalid value is [`PrepareError::ConfigOverrideInvalid`] and the turn dies
/// fail-closed rather than silently defaulting. `engine_id` has no variable at all: §4.10(g) makes
/// it immutable because it pins the execution mechanism.
pub fn resolve_governed_generation_config_v1b() -> Result<GovernedGenerationConfig, PrepareError> {
    resolve_governed_generation_config_from(|name| std::env::var(name).ok())
}

/// [`resolve_governed_generation_config_v1b`] with the environment injected.
///
/// The whole override contract is exercised through this, so the tests never mutate a process-global
/// (which is racy across parallel test threads and would make the suite's own result depend on
/// scheduling). Production calls it with `std::env::var`, so there is one implementation, not two.
pub fn resolve_governed_generation_config_from<F>(
    lookup: F,
) -> Result<GovernedGenerationConfig, PrepareError>
where
    F: Fn(&str) -> Option<String>,
{
    let overridden =
        |field: &'static str, var: &str, default: &str| -> Result<String, PrepareError> {
            match lookup(var) {
                // §4.10(g): "An unset/empty var ⇒ the frozen literal default".
                None => Ok(default.to_string()),
                Some(v) if v.is_empty() => Ok(default.to_string()),
                Some(v) => match validate_field(field, &v) {
                    Ok(()) => Ok(v),
                    // Re-labelled: a bad OVERRIDE and a bad caller-supplied field are different
                    // faults with different owners, and a deployment reading `config_field_invalid`
                    // would go looking at a renderer that never touched this value.
                    Err(_) => Err(PrepareError::ConfigOverrideInvalid(field)),
                },
            }
        };

    let mut fields = BTreeMap::new();
    // NOT overridable — no variable is consulted, so a `BROPS_GOVERNED_ENGINE_ID` in the environment
    // is inert by construction rather than by a check that could be removed.
    fields.insert("engine_id".to_string(), GOVERNED_ENGINE_ID.to_string());
    fields.insert(
        "max_output_tokens".to_string(),
        overridden(
            "max_output_tokens",
            GOVERNED_MAX_OUTPUT_TOKENS_ENV,
            GOVERNED_MAX_OUTPUT_TOKENS,
        )?,
    );
    fields.insert(
        "model".to_string(),
        overridden("model", GOVERNED_MODEL_ENV, GOVERNED_MODEL)?,
    );
    fields.insert(
        "temperature".to_string(),
        overridden("temperature", GOVERNED_TEMPERATURE_ENV, GOVERNED_TEMPERATURE)?,
    );
    fields.insert(
        "top_p".to_string(),
        overridden("top_p", GOVERNED_TOP_P_ENV, GOVERNED_TOP_P)?,
    );
    GovernedGenerationConfig::validate(&fields)
}

// =================================================================================================
// History
// =================================================================================================

/// One `history` entry: the closed `{role, content}` pair §4.10(g) admits.
///
/// A separate type from `ai::ChatMsg` because that one lives in the renderer-hosting app crate,
/// which this crate cannot depend on (the dependency runs the other way). The DIGEST the two produce
/// must be identical, and `ai.rs`'s `the_governed_history_digest_equals_the_broker_side_formula`
/// asserts exactly that against this module — so the two spellings are pinned to one value rather
/// than trusted to agree.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GovernedChatMsg {
    pub role: String,
    pub content: String,
}

impl GovernedChatMsg {
    /// A `{role, content}` pair. The role is NOT checked here — [`prepare_governed_turn_v1b`]
    /// applies §4.10(g)'s closed enum, so a value that never reaches a digest is never refused
    /// twice.
    pub fn new(role: impl Into<String>, content: impl Into<String>) -> Self {
        GovernedChatMsg { role: role.into(), content: content.into() }
    }
}

/// `history_bytes = JCS([{ "content": …, "role": … }, …])` (§4.10(g), the shipped
/// `brops_canonical.history_bytes`).
///
/// Hashes a JSON STRUCTURE, never a delimiter concat, so user content cannot forge a different
/// message array into the same bytes. `serde_json` of a `Vec<BTreeMap<&str,&str>>` emits sorted keys
/// and compact separators with minimal escaping and no `\u` escaping of non-ASCII — i.e. JCS for
/// this ASCII-keyed string shape, and byte-identical to Python's `json.dumps(sort_keys=True,
/// separators=(",",":"), ensure_ascii=False)`.
pub fn history_jcs(messages: &[GovernedChatMsg]) -> Vec<u8> {
    let array: Vec<BTreeMap<&str, &str>> = messages
        .iter()
        .map(|m| {
            let mut o = BTreeMap::new();
            o.insert("content", m.content.as_str());
            o.insert("role", m.role.as_str());
            o
        })
        .collect();
    serde_json::to_vec(&array).unwrap_or_default()
}

// =================================================================================================
// The prepared turn
// =================================================================================================

/// The canonical governed-request context (§2.2), carrying the OBJECT-JCS
/// `generation_config_sha256`.
///
/// The same shape as `ai::GovernedRequestContext`, on the broker side of the boundary and holding a
/// digest computed by a DIFFERENT formula. They are deliberately not one type: sharing one would be
/// the split authority §4.10(g) forbids, since a value built by the frozen preparation could then be
/// passed where the governed one is required and nothing would say so.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GovernedRequestContext {
    pub workspace_id: String,
    pub install_id: String,
    pub request_nonce: String,
    pub system_sha256: String,
    pub history_sha256: String,
    /// `SHA256(JCS(object))` — never `SHA256(config.as_bytes())`.
    pub generation_config_sha256: String,
    pub requested_at: String,
}

/// One governed turn prepared ONCE (§4.10(g) v1b), the sole source of the object-JCS hash for the
/// entire chain.
///
/// **Fields are private (§4.10(g) "Encapsulation enforcement", P0-1 LOCKED).** There is no
/// constructor other than [`prepare_governed_turn_v1b`], no mutator, and no public copy of the
/// object/JCS/context — every cross-stage read is a read-only accessor, so a tampered or
/// reconstructed object cannot reach submit.
#[derive(Debug, Clone)]
pub struct PreparedGovernedTurnV1B {
    system: String,
    history: Vec<GovernedChatMsg>,
    generation_config: GovernedGenerationConfig,
    generation_config_jcs: Vec<u8>,
    context: GovernedRequestContext,
}

impl PreparedGovernedTurnV1B {
    /// The exact bytes that are SENT and HASHED (raw UTF-8, no trim/NFC/CRLF normalize).
    pub fn system(&self) -> &str {
        &self.system
    }
    /// The exact history that is SENT and HASHED.
    pub fn history(&self) -> &[GovernedChatMsg] {
        &self.history
    }
    /// The validated object — retained, which the frozen struct could not do because it only ever
    /// held the opaque string.
    pub fn generation_config(&self) -> &GovernedGenerationConfig {
        &self.generation_config
    }
    /// `JCS(object)`, computed ONCE in [`prepare_governed_turn_v1b`] and never recomputed.
    pub fn generation_config_jcs(&self) -> &[u8] {
        &self.generation_config_jcs
    }
    /// The canonical request context: the minted nonce plus the three artifact digests.
    pub fn context(&self) -> &GovernedRequestContext {
        &self.context
    }

    /// The §2.2 `IssuedRequest` — (a) the `receipt_challenges` pre-store, and (d) the final
    /// `Expected`. Borrowed from this object's own fields, so the pre-store and the verification
    /// cannot be built from two different values.
    pub fn issued_request(&self) -> IssuedRequest<'_> {
        IssuedRequest {
            workspace_id: &self.context.workspace_id,
            install_id: &self.context.install_id,
            request_nonce: &self.context.request_nonce,
            system_sha256: &self.context.system_sha256,
            history_sha256: &self.context.history_sha256,
            generation_config_sha256: &self.context.generation_config_sha256,
            requested_at: &self.context.requested_at,
        }
    }

    /// The canonical `request_sha256` this turn is bound by, everywhere.
    pub fn request_sha256(&self) -> String {
        self.issued_request().request_sha256()
    }

    /// §4.10(g)'s pre-submit self-check: `SHA256(prepared.generation_config_jcs) ==
    /// prepared.context.generation_config_sha256`.
    ///
    /// **Read what this can and cannot catch.** Both sides are private fields of the same immutable
    /// object minted by one function, so within this process it cannot fail — there is no setter
    /// that could desynchronize them, and no test in this module can make it return `false` without
    /// reaching past the privacy. It is kept because §4.10(g) names it as a submit precondition and
    /// because the day the object gains a second constructor (a deserialization, a store round-trip,
    /// the permitted `prepared_turn_id` state machine) it becomes the check that notices. It is
    /// called by `governed_submit` before the frame is written.
    pub fn self_check(&self) -> bool {
        sha256_hex(&self.generation_config_jcs) == self.context.generation_config_sha256
    }
}

#[cfg(test)]
impl PreparedGovernedTurnV1B {
    /// Build a DESYNCHRONIZED prepared turn — the one thing the public API makes impossible.
    ///
    /// `#[cfg(test)]`, so the shipping crate still has exactly ONE constructor and the §4.10(g)
    /// encapsulation guarantee is intact. It exists because two checks are otherwise unreachable by
    /// name and a mutation pass proved it: deleting `self_check`'s guard, and swapping the
    /// object-recompute in `governed_submit::submit_frame` for a re-read of the stored digest, both
    /// SURVIVED every test until this existed. A guard nothing can produce a failure for is
    /// indistinguishable from a guard that does nothing.
    ///
    /// `pub(crate)`: reachable from `governed_submit`'s tests, which is where the second of those two
    /// checks lives, and from nowhere outside `brops-core` at all.
    pub(crate) fn desynced_for_test(
        base: PreparedGovernedTurnV1B,
        generation_config_jcs: Vec<u8>,
        committed_sha256: Option<String>,
    ) -> PreparedGovernedTurnV1B {
        let mut out = base;
        out.context.generation_config_sha256 =
            committed_sha256.unwrap_or_else(|| sha256_hex(&generation_config_jcs));
        out.generation_config_jcs = generation_config_jcs;
        out
    }
}

fn bounded_id(field: &'static str, value: &str) -> Result<(), PrepareError> {
    if value.is_empty() || value.len() > MAX_ID_LEN {
        return Err(PrepareError::IdInvalid(field));
    }
    Ok(())
}

/// Prepare one governed turn (§4.10(g) v1b) — in ONE pass, producing every downstream value from the
/// same inputs.
///
/// The six steps §4.10(g) locks, in order: (1) validate the flat `generation_config` object — the
/// caller has already done this by holding a [`GovernedGenerationConfig`], which is the only way to
/// obtain one; (2) `generation_config_jcs = JCS(object)` ONCE and `generation_config_sha256 =
/// SHA256(jcs)` — the object-JCS hash, never `as_bytes()`; (3) normalize `system` (raw UTF-8) and
/// `history` (JCS) once; (4) mint `request_nonce = crate::id()` ONCE; (5) build one immutable
/// context/`IssuedRequest`; (6) be the single source of the pre-store, the create-pending request,
/// the submit frame and the final `Expected`.
///
/// **What this does NOT do, and where it disagrees with the shipped tree.** It does not trim the
/// history: the frozen `ai::prepare_governed_turn` calls `trim_history`, and that function is
/// private to the renderer-hosting app crate. §4.10(g) says the prepared object carries "the
/// canonical trimmed history sent AND hashed", so the caller hands this the already-selected window
/// — and that caller is `governed_turn_execute` inside the broker, which resolves `system`/`history`
/// from the message store itself and does not exist yet. Trimming here would put the window rule in
/// two places.
///
/// **It mints the nonce, and the shipped broker also mints one.**
/// `broker_orchestrator::run_governed_turn` takes `request_nonce` from `BrokerIds` and hands it to
/// the executor BEFORE any preparation happens, while §4.10(g) step 1 makes this function the mint.
/// Both cannot be the authority. The design is followed here (this function mints); reconciling the
/// two is a seam named in the report rather than decided locally, because the orchestrator's nonce is
/// already the key of a durable `broker_turns` row.
pub fn prepare_governed_turn_v1b(
    system: &str,
    messages: &[GovernedChatMsg],
    generation_config: GovernedGenerationConfig,
    now_ms: u64,
    workspace_id: &str,
    install_id: &str,
) -> Result<PreparedGovernedTurnV1B, PrepareError> {
    bounded_id("workspace_id", workspace_id)?;
    bounded_id("install_id", install_id)?;

    // (3a) `system` — raw UTF-8, no normalization. The cap is CALLER-SIZED and can fire.
    let system_bytes = system.as_bytes();
    if system_bytes.len() > MAX_SYSTEM_BYTES {
        return Err(PrepareError::SystemOversize);
    }

    // (3b) `history` — the closed role enum and both per-message caps, then the JCS ceiling. All
    // four can fire and none implies another: 1001 one-byte messages canonicalize to ~30 KiB, and a
    // single 1048577-byte message is well inside the 8 MiB conversation cap.
    if messages.len() > MAX_MESSAGES {
        return Err(PrepareError::HistoryTooManyMessages);
    }
    for message in messages {
        if !HISTORY_ROLES.contains(&message.role.as_str()) {
            return Err(PrepareError::HistoryRoleInvalid);
        }
        if message.content.len() > MAX_MESSAGE_BYTES {
            return Err(PrepareError::MessageOversize);
        }
    }
    let history_bytes = history_jcs(messages);
    if history_bytes.len() > MAX_CONVERSATION_BYTES {
        return Err(PrepareError::ConversationOversize);
    }

    // (2) ONCE. Every later reader takes these two values; nothing re-hashes the config.
    let generation_config_jcs = generation_config.jcs();
    let generation_config_sha256 = sha256_hex(&generation_config_jcs);

    let context = GovernedRequestContext {
        workspace_id: workspace_id.to_string(),
        install_id: install_id.to_string(),
        // (4) minted ONCE, here.
        request_nonce: crate::id(),
        system_sha256: sha256_hex(system_bytes),
        history_sha256: sha256_hex(&history_bytes),
        generation_config_sha256,
        requested_at: now_ms.to_string(),
    };

    Ok(PreparedGovernedTurnV1B {
        system: system.to_string(),
        history: messages.to_vec(),
        generation_config,
        generation_config_jcs,
        context,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn defaults() -> GovernedGenerationConfig {
        resolve_governed_generation_config_from(|_| None).expect("the frozen defaults validate")
    }

    fn field_map(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
        pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
    }

    // ---------------------------------------------------------------------------------------------
    // The formula, and the two mandatory §4.10(g) P0-1 assertions
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn the_frozen_defaults_canonicalize_to_the_exact_bytes_and_digest_the_design_prints() {
        let config = defaults();
        assert_eq!(
            String::from_utf8(config.jcs()).unwrap(),
            "{\"engine_id\":\"brops.governed-engine.sidecar.v1\",\"max_output_tokens\":\"4096\",\
             \"model\":\"claude-sonnet-5\",\"temperature\":\"0.00\",\"top_p\":\"1.00\"}"
        );
        // §4.10(g) prints this digest; `engine/tests/test_governed_turn_submit_e2e.py` pins the SAME
        // hex from `brops_canonical.governed_generation_config_sha256`. Rust↔Python parity is
        // therefore a shared literal rather than an argument about two encoders.
        assert_eq!(
            config.sha256(),
            "732b58634d0a83e9b7fdf1ca69db78df145bd9dd79ac8922fed3e79cf5faab22"
        );
        assert_eq!(
            config.model_profile_id(),
            "cfg-sha256:732b58634d0a83e9b7fdf1ca69db78df145bd9dd79ac8922fed3e79cf5faab22"
        );
        // The default object is 137 bytes — the figure `bridge/governed_turn_submit.py` uses to
        // establish that two of the three artifacts always send at least one staging chunk.
        assert_eq!(config.jcs().len(), 137);
    }

    #[test]
    fn the_governed_digest_is_not_the_frozen_raw_string_digest() {
        // §4.10(g) mandatory test (i). The frozen fixture (`receipt.rs:1215-1219`) hashes the
        // raw-UTF-8 STRING form; this asserts the governed OBJECT form differs, which is the whole
        // reason a second preparation exists. If these ever collided, reusing the frozen path would
        // look correct while being the split authority the Architect flagged.
        let frozen = sha256_hex(br#"{"model":"claude","temperature":0}"#);
        assert_eq!(frozen, "963be7a4e0b02ab18478b28a969f38f6c5c5b7f7bbe6bccf67ec9495cb377234");
        assert_ne!(defaults().sha256(), frozen);

        // And the same statement for a config that names the SAME model: the two formulas disagree
        // on every input, not just on the fixture's.
        let same_model = GovernedGenerationConfig::validate(&field_map(&[
            ("engine_id", GOVERNED_ENGINE_ID),
            ("max_output_tokens", "4096"),
            ("model", "claude"),
            ("temperature", "0.00"),
            ("top_p", "1.00"),
        ]))
        .unwrap();
        assert_ne!(same_model.sha256(), sha256_hex(br#"{"model":"claude","temperature":0}"#));
    }

    #[test]
    fn the_jcs_is_the_receipt_primitive_and_never_a_json_number() {
        let json = defaults().to_json();
        for field in GOVERNED_GENERATION_CONFIG_FIELDS {
            assert!(
                json.get(field).and_then(serde_json::Value::as_str).is_some(),
                "{field} must ride the wire as a STRING; a JSON number is the representation \
                 ambiguity §4.10(g) exists to remove"
            );
        }
        // The wire form and the hashed form are the same five pairs — a frame that carried a
        // different object from the one that was hashed is the divergence the whole hop guards.
        assert_eq!(serde_json::to_vec(&json).unwrap(), defaults().jcs());
    }

    // ---------------------------------------------------------------------------------------------
    // The arithmetic, done first (and not written as a check)
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn the_widest_expressible_config_is_349_bytes_against_a_65536_cap() {
        // Every value at its regex maximum: two 128-char ids, a 7-digit integer, two 4-char
        // fixed-point strings. This is the LARGEST object `GovernedGenerationConfig::validate` can
        // ever return, so it is the largest `JCS(generation_config)` this hop can ever produce.
        let widest = GovernedGenerationConfig::validate(&field_map(&[
            ("engine_id", &"e".repeat(MAX_ID_LEN)),
            ("max_output_tokens", "1048576"),
            ("model", &"m".repeat(MAX_ID_LEN)),
            ("temperature", "2.00"),
            ("top_p", "1.00"),
        ]))
        .unwrap();
        assert_eq!(widest.jcs().len(), 349);
        // The ratio, pinned from BOTH sides so it is a fact rather than a rounding: 187 fits and
        // 188 does not. `bridge/governed_turn_submit.py` says "a factor of 188", which is 187.8
        // rounded up; the integer ratio is 187, and both statements describe the same two numbers.
        assert!(
            widest.jcs().len() * 187 < MAX_GENERATION_CONFIG_BYTES,
            "if a field regex is ever widened this assertion is the thing that turns RED"
        );
        assert!(widest.jcs().len() * 188 > MAX_GENERATION_CONFIG_BYTES);
        // `max_output_tokens` is 7 digits at its cap, so the integer bound and the regex bound are
        // the same length — widening the regex to 8 digits would not widen this number.
        assert_eq!("1048576".len(), 7);
    }

    #[test]
    fn the_caps_that_can_fire_are_the_two_caller_sized_ones() {
        let config = defaults();
        // system: 262144 accepted, 262145 refused.
        let at_cap = "s".repeat(MAX_SYSTEM_BYTES);
        assert!(prepare_governed_turn_v1b(&at_cap, &[], config.clone(), 1, "ws", "in").is_ok());
        let over = "s".repeat(MAX_SYSTEM_BYTES + 1);
        assert_eq!(
            prepare_governed_turn_v1b(&over, &[], config.clone(), 1, "ws", "in").unwrap_err(),
            PrepareError::SystemOversize
        );

        // history count: 1000 accepted, 1001 refused — and 1001 one-byte messages are ~30 KiB, far
        // inside MAX_CONVERSATION_BYTES, so this cap is not implied by the conversation cap.
        let many: Vec<GovernedChatMsg> =
            (0..MAX_MESSAGES + 1).map(|_| GovernedChatMsg::new("user", "x")).collect();
        assert!(history_jcs(&many).len() < MAX_CONVERSATION_BYTES);
        assert_eq!(
            prepare_governed_turn_v1b("s", &many, config.clone(), 1, "ws", "in").unwrap_err(),
            PrepareError::HistoryTooManyMessages
        );

        // per-message: 1048577 bytes is over the per-message cap and inside the 8 MiB conversation
        // cap, so this one is not implied either.
        let big = vec![GovernedChatMsg::new("user", "x".repeat(MAX_MESSAGE_BYTES + 1))];
        assert!(history_jcs(&big).len() < MAX_CONVERSATION_BYTES);
        assert_eq!(
            prepare_governed_turn_v1b("s", &big, config, 1, "ws", "in").unwrap_err(),
            PrepareError::MessageOversize
        );
    }

    #[test]
    fn the_conversation_cap_fires_on_the_canonical_bytes_not_on_the_content_sum() {
        // Nine messages of 1 MiB each: every one is inside MAX_MESSAGE_BYTES and the count is inside
        // MAX_MESSAGES, but `JCS(history)` is over the 8 MiB ceiling. That is why the third check
        // exists and why it is applied to the CANONICAL bytes.
        let msgs: Vec<GovernedChatMsg> =
            (0..9).map(|_| GovernedChatMsg::new("user", "y".repeat(MAX_MESSAGE_BYTES))).collect();
        assert!(history_jcs(&msgs).len() > MAX_CONVERSATION_BYTES);
        assert_eq!(
            prepare_governed_turn_v1b("s", &msgs, defaults(), 1, "ws", "in").unwrap_err(),
            PrepareError::ConversationOversize
        );
    }

    // ---------------------------------------------------------------------------------------------
    // The field rules — every accept/reject example §4.10(g) lists for the parity fixture
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn the_field_rules_accept_and_refuse_exactly_the_designs_examples() {
        // (2) boundary values ACCEPTED.
        for (field, value) in [
            ("temperature", "0.00"),
            ("temperature", "1.00"),
            ("temperature", "2.00"),
            ("top_p", "0.00"),
            ("top_p", "1.00"),
            ("max_output_tokens", "1"),
            ("max_output_tokens", "1048576"),
        ] {
            assert_eq!(validate_field(field, value), Ok(()), "{field}={value} must be accepted");
        }
        // (3) exponent form, (4) signed zero, (5) integral-float / precision mismatch,
        // (6) high precision, (7) leading zero — all refused on SHAPE.
        for (field, value) in [
            ("max_output_tokens", "1e0"),
            ("max_output_tokens", "1E2"),
            ("max_output_tokens", "1e3"),
            ("temperature", "-0.00"),
            ("max_output_tokens", "-0"),
            ("temperature", "1"),
            ("temperature", "1.0"),
            ("temperature", "1.000"),
            ("temperature", "0.300000000000000004"),
            ("temperature", "0.9999"),
            ("max_output_tokens", "0256"),
            ("max_output_tokens", "0"),
        ] {
            assert_eq!(
                validate_field(field, value),
                Err(PrepareError::ConfigFieldInvalid(field)),
                "{field}={value} must be refused before canonicalization"
            );
        }
        // (7)/(8) values the REGEX admits and the INTEGER bound refuses. These are the reason the
        // two refusals are distinct members: a single `invalid` would not prove the bound ran.
        for (field, value) in
            [("max_output_tokens", "1048577"), ("temperature", "2.01"), ("top_p", "1.01")]
        {
            assert_eq!(
                validate_field(field, value),
                Err(PrepareError::ConfigFieldOutOfRange(field)),
                "{field}={value} must be refused by the integer bound, not by the regex"
            );
        }
        // `temperature` admits a leading `2`, `top_p` does not — the two patterns genuinely differ.
        assert_eq!(validate_field("top_p", "2.00"), Err(PrepareError::ConfigFieldInvalid("top_p")));
        // `model` admits `:`; `engine_id` does not.
        assert_eq!(validate_field("model", "claude-sonnet-5:beta"), Ok(()));
        assert_eq!(
            validate_field("engine_id", "a:b"),
            Err(PrepareError::ConfigFieldInvalid("engine_id"))
        );
        // Ids are bounded at 128 in both directions.
        assert_eq!(validate_field("model", &"m".repeat(128)), Ok(()));
        assert_eq!(
            validate_field("model", &"m".repeat(129)),
            Err(PrepareError::ConfigFieldInvalid("model"))
        );
        assert_eq!(validate_field("model", ""), Err(PrepareError::ConfigFieldInvalid("model")));
    }

    #[test]
    fn the_field_set_is_closed_in_both_directions() {
        let mut missing = field_map(&[
            ("engine_id", GOVERNED_ENGINE_ID),
            ("max_output_tokens", "4096"),
            ("model", "claude-sonnet-5"),
            ("temperature", "0.00"),
        ]);
        assert_eq!(
            GovernedGenerationConfig::validate(&missing).unwrap_err(),
            PrepareError::ConfigFieldSet
        );
        missing.insert("top_p".into(), "1.00".into());
        assert!(GovernedGenerationConfig::validate(&missing).is_ok());
        // An EXTRA key is as fatal as a missing one: JCS would hash it and the authority's committed
        // digest would then disagree with the staged one.
        missing.insert("seed".into(), "1".into());
        assert_eq!(
            GovernedGenerationConfig::validate(&missing).unwrap_err(),
            PrepareError::ConfigFieldSet
        );
    }

    // ---------------------------------------------------------------------------------------------
    // The trusted-host override contract
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn an_unset_or_empty_override_yields_the_frozen_literal_default() {
        let unset = resolve_governed_generation_config_from(|_| None).unwrap();
        let empty = resolve_governed_generation_config_from(|_| Some(String::new())).unwrap();
        assert_eq!(unset, empty);
        assert_eq!(unset.engine_id(), GOVERNED_ENGINE_ID);
        assert_eq!(unset.model(), GOVERNED_MODEL);
        assert_eq!(unset.max_output_tokens(), GOVERNED_MAX_OUTPUT_TOKENS);
        assert_eq!(unset.temperature(), GOVERNED_TEMPERATURE);
        assert_eq!(unset.top_p(), GOVERNED_TOP_P);
    }

    #[test]
    fn each_of_the_four_overridable_fields_can_be_overridden_and_engine_id_cannot() {
        for (var, value, read) in [
            (GOVERNED_MODEL_ENV, "claude-opus-9", "model"),
            (GOVERNED_MAX_OUTPUT_TOKENS_ENV, "8192", "max_output_tokens"),
            (GOVERNED_TEMPERATURE_ENV, "1.25", "temperature"),
            (GOVERNED_TOP_P_ENV, "0.90", "top_p"),
        ] {
            let config = resolve_governed_generation_config_from(|name| {
                (name == var).then(|| value.to_string())
            })
            .unwrap();
            let actual = match read {
                "model" => config.model(),
                "max_output_tokens" => config.max_output_tokens(),
                "temperature" => config.temperature(),
                _ => config.top_p(),
            };
            assert_eq!(actual, value);
            // An override changes the identity, which is the point: the resulting hash must be added
            // to GOVERNED_EXECUTION_ALLOWLIST or acceptance Blocks `model_profile_unknown`.
            assert_ne!(config.sha256(), defaults().sha256());
        }
        // `engine_id` has NO variable. Setting the obvious name changes nothing.
        let tampered = resolve_governed_generation_config_from(|name| {
            (name == "BROPS_GOVERNED_ENGINE_ID").then(|| "evil.engine".to_string())
        })
        .unwrap();
        assert_eq!(tampered.engine_id(), GOVERNED_ENGINE_ID);
        assert_eq!(tampered, defaults());
    }

    #[test]
    fn a_set_but_invalid_override_fails_closed_and_never_silently_defaults() {
        for (var, bad, field) in [
            (GOVERNED_MODEL_ENV, "claude sonnet 5", "model"),
            (GOVERNED_MAX_OUTPUT_TOKENS_ENV, "1048577", "max_output_tokens"),
            (GOVERNED_TEMPERATURE_ENV, "3.00", "temperature"),
            (GOVERNED_TOP_P_ENV, "1.01", "top_p"),
        ] {
            let err = resolve_governed_generation_config_from(|name| {
                (name == var).then(|| bad.to_string())
            })
            .unwrap_err();
            assert_eq!(err, PrepareError::ConfigOverrideInvalid(field));
            assert_eq!(err.as_str(), "config_override_invalid");
            assert_eq!(err.field(), Some(field));
        }
    }

    // ---------------------------------------------------------------------------------------------
    // The prepared object
    // ---------------------------------------------------------------------------------------------

    #[test]
    fn preparation_derives_every_downstream_value_from_the_one_object() {
        let msgs = [GovernedChatMsg::new("user", "hi"), GovernedChatMsg::new("assistant", "yes")];
        let prepared =
            prepare_governed_turn_v1b("You are Bro.", &msgs, defaults(), 1000, "ws-1", "install-1")
                .unwrap();
        let ctx = prepared.context();

        // The three artifact digests are the formulas, applied to the bytes actually retained.
        assert_eq!(ctx.system_sha256, sha256_hex(prepared.system().as_bytes()));
        assert_eq!(ctx.history_sha256, sha256_hex(&history_jcs(prepared.history())));
        assert_eq!(ctx.generation_config_sha256, sha256_hex(prepared.generation_config_jcs()));
        // And the config digest is the OBJECT-JCS one, not a second representation.
        assert_eq!(ctx.generation_config_sha256, prepared.generation_config().sha256());
        assert!(prepared.self_check());

        // `system` is the frozen §4.0a formula, so it agrees with the shipped Python fixture.
        assert_eq!(
            ctx.system_sha256,
            "245560397a2a5124423b16d544dfda343392cced1fa0981aefb833fba1f8d032"
        );
        assert_eq!(ctx.requested_at, "1000");

        // The IssuedRequest and the request_sha256 come from the SAME fields — the pre-store and the
        // final Expected cannot be built from two different values.
        let issued = prepared.issued_request();
        assert_eq!(issued.request_nonce, ctx.request_nonce);
        assert_eq!(issued.generation_config_sha256, ctx.generation_config_sha256);
        assert_eq!(prepared.request_sha256(), issued.request_sha256());
    }

    #[test]
    fn the_history_canonicalization_matches_the_shipped_cross_language_fixture() {
        // The exact fixture `receipt.rs::brops_all_formula_parity_matches_python` and
        // `engine/tests/test_brops_parity.py` both pin. Non-ASCII stays raw UTF-8 and the keys are
        // ordered content<role — so the broker-side spelling of the formula is the same formula.
        let msgs = [
            GovernedChatMsg::new("user", "hi"),
            GovernedChatMsg::new("assistant", "hello é✈"),
        ];
        assert_eq!(
            history_jcs(&msgs),
            "[{\"content\":\"hi\",\"role\":\"user\"},{\"content\":\"hello é✈\",\"role\":\"assistant\"}]"
                .as_bytes()
        );
        assert_eq!(
            sha256_hex(&history_jcs(&msgs)),
            "fbd46857ec1ed759024d56430d5f00214e9a478b6f94ec3933f498aa7cd14c80"
        );
        // An empty history canonicalizes to `[]` — 2 bytes, never 0. That is why only `system` can
        // produce a zero-byte staged artifact.
        assert_eq!(history_jcs(&[]), b"[]");
    }

    #[test]
    fn a_role_outside_the_closed_enum_is_refused_before_any_digest_exists() {
        let msgs = [GovernedChatMsg::new("tool", "x")];
        assert_eq!(
            prepare_governed_turn_v1b("s", &msgs, defaults(), 1, "ws", "in").unwrap_err(),
            PrepareError::HistoryRoleInvalid
        );
        for role in HISTORY_ROLES {
            let ok = [GovernedChatMsg::new(role, "x")];
            assert!(prepare_governed_turn_v1b("s", &ok, defaults(), 1, "ws", "in").is_ok());
        }
    }

    #[test]
    fn an_unbounded_workspace_or_install_id_is_refused() {
        for field in ["workspace_id", "install_id"] {
            let long = "i".repeat(MAX_ID_LEN + 1);
            let (ws, install) =
                if field == "workspace_id" { (long.as_str(), "in") } else { ("ws", long.as_str()) };
            assert_eq!(
                prepare_governed_turn_v1b("s", &[], defaults(), 1, ws, install).unwrap_err(),
                PrepareError::IdInvalid(field)
            );
        }
        assert_eq!(
            prepare_governed_turn_v1b("s", &[], defaults(), 1, "", "in").unwrap_err(),
            PrepareError::IdInvalid("workspace_id")
        );
    }

    #[test]
    fn the_nonce_is_minted_once_per_preparation_and_never_repeats() {
        let a = prepare_governed_turn_v1b("s", &[], defaults(), 1, "ws", "in").unwrap();
        let b = prepare_governed_turn_v1b("s", &[], defaults(), 1, "ws", "in").unwrap();
        assert_ne!(a.context().request_nonce, b.context().request_nonce);
        // Identical inputs, different nonces ⇒ different request_sha256. The nonce is what makes the
        // envelope one-time.
        assert_ne!(a.request_sha256(), b.request_sha256());
    }

    #[test]
    fn an_eight_digit_token_count_is_refused_by_the_REGEX_not_by_the_range() {
        // `^[1-9][0-9]{0,6}$` bounds the LENGTH at 7, and that bound is load-bearing in its own
        // right: widening it to 8 leaves every accept/reject decision unchanged (the smallest
        // 8-digit value, 10000000, is already outside 1..=1048576) and only relabels the refusal.
        // A mutation pass showed exactly that — the widened regex survived — so the two refusals are
        // pinned apart here rather than left to be the same answer by accident.
        assert_eq!(
            validate_field("max_output_tokens", "10485770"),
            Err(PrepareError::ConfigFieldInvalid("max_output_tokens"))
        );
        assert_eq!(
            validate_field("max_output_tokens", "1048577"),
            Err(PrepareError::ConfigFieldOutOfRange("max_output_tokens"))
        );
    }

    #[test]
    fn system_is_hashed_raw_with_no_trim_and_no_normalization() {
        // §4.10(g): `system_bytes = system.encode("utf-8")` — "raw UTF-8, **no trim/NFC/NFKC/CRLF
        // normalize**". A trim here would be invisible until §2.4 staging re-derived the digest from
        // the untrimmed bytes the frame carries and the supervisor answered `digest_mismatch`, which
        // is a verdict about tampering for a turn nobody tampered with.
        let padded = "  You are Bro.\r\n";
        let prepared =
            prepare_governed_turn_v1b(padded, &[], defaults(), 1, "ws", "in").unwrap();
        assert_eq!(prepared.system(), padded);
        assert_eq!(prepared.context().system_sha256, sha256_hex(padded.as_bytes()));
        assert_ne!(prepared.context().system_sha256, sha256_hex(padded.trim().as_bytes()));
    }

    #[test]
    fn the_conversation_cap_is_exact_at_the_canonical_byte() {
        // The tightest cap on this path, pinned at the byte. Built by MEASUREMENT rather than by
        // arithmetic on paper: seven messages at the per-message ceiling plus one sized to land the
        // canonical bytes exactly on `MAX_CONVERSATION_BYTES`, then one byte past it.
        let full = || GovernedChatMsg::new("user", "y".repeat(MAX_MESSAGE_BYTES));
        let mut msgs: Vec<GovernedChatMsg> = (0..7).map(|_| full()).collect();
        msgs.push(GovernedChatMsg::new("user", ""));
        // ASCII content, so one extra character is exactly one extra canonical byte.
        let base = history_jcs(&msgs).len();
        let pad = MAX_CONVERSATION_BYTES - base;
        assert!(pad <= MAX_MESSAGE_BYTES, "the sizing message must stay inside its own cap");

        msgs.pop();
        msgs.push(GovernedChatMsg::new("user", "y".repeat(pad)));
        assert_eq!(history_jcs(&msgs).len(), MAX_CONVERSATION_BYTES);
        assert!(prepare_governed_turn_v1b("s", &msgs, defaults(), 1, "ws", "in").is_ok());

        msgs.pop();
        msgs.push(GovernedChatMsg::new("user", "y".repeat(pad + 1)));
        assert_eq!(history_jcs(&msgs).len(), MAX_CONVERSATION_BYTES + 1);
        assert_eq!(
            prepare_governed_turn_v1b("s", &msgs, defaults(), 1, "ws", "in").unwrap_err(),
            PrepareError::ConversationOversize
        );
    }

    #[test]
    fn every_prepare_error_has_a_distinct_stable_machine_name() {
        let all = [
            PrepareError::ConfigFieldSet,
            PrepareError::ConfigFieldInvalid("model"),
            PrepareError::ConfigFieldOutOfRange("top_p"),
            PrepareError::ConfigOverrideInvalid("temperature"),
            PrepareError::SystemOversize,
            PrepareError::HistoryTooManyMessages,
            PrepareError::MessageOversize,
            PrepareError::ConversationOversize,
            PrepareError::HistoryRoleInvalid,
            PrepareError::IdInvalid("install_id"),
        ];
        let mut names: Vec<&str> = all.iter().map(PrepareError::as_str).collect();
        names.sort_unstable();
        names.dedup();
        assert_eq!(names.len(), all.len(), "two refusals share a machine name");
        assert_eq!(PrepareError::IdInvalid("install_id").to_string(), "id_invalid:install_id");
        assert_eq!(PrepareError::SystemOversize.to_string(), "system_oversize");
    }
}
