//! The broker's rev-30 **§4.10(g) sidecar-ladder** governed turn — the caller
//! [`brops_core::governed_submit::governed_turn_submit_prepared`] never had.
//!
//! # Why this exists at all, stated as the fact that decided it
//!
//! The direct path's [`crate::manifest_resolver::ProductionResolver`] supplies `system_sha256`,
//! `history_sha256` and `generation_config_sha256` from `$BROPS_BROKER_CONFIG`'s `resolved` block —
//! deployment-static values that are identical on every turn. Its own doc comment called the
//! per-conversation facts "a follow-up protocol slice". So a receipt produced through that path
//! attests the digests the deployment config wrote down, not the digests of what was actually sent.
//! Every signature in the chain is real and every binding holds; they simply bind the wrong bytes.
//!
//! This module is the follow-up slice. Every one of those three digests is DERIVED here, in one pass,
//! by `governed_prepare::prepare_governed_turn_v1b`, from the turn's actual `system` string, the
//! actual conversation history, and the actual validated generation-config object — and the SAME
//! prepared object is what the challenge is asked for, what the submit frame carries, and what the
//! final `Expected` is read from. There is no second copy for anything to drift against.
//!
//! # The ladder, in the order it runs
//!
//!  0. **Keys** — [`crate::manifest_resolver::KeyResolver`]: root-verify the manifest against the TCB
//!     pin, run and PERSIST anti-rollback, resolve both production keys. Before any hop, exactly as the
//!     direct path did, because a turn whose trust anchors are unresolved has nothing to execute.
//!  1. **Content** — [`TurnContent`]: the conversation's `system` + `history`. The one input that makes
//!     the digests per-conversation, so it is a seam with a real production implementation
//!     ([`SqliteTurnContent`]) rather than a config field.
//!  2. **Prepare** — one `prepare_governed_turn_v1b`, which mints the `request_nonce` ONCE and computes
//!     all three digests ONCE.
//!  3. **challenge-authority** `create-pending` → `issue`, over [`crate::chain_hops`] — the same hop
//!     layer, the same reply parser. The facts sent are the PREPARED ones.
//!  4. **submit** — `governed_turn_submit_prepared` over a [`SubmitTransport`]; production is
//!     `brops_core::governed_sidecar::GovernedSidecar`, the tree's one bridge spawn. The four §4.10(g)
//!     cross-bindings are asserted inside it, before a frame exists.
//!  5. **§4.10(f) pull** — `governed_output_pull::pull_output` through fresh one-shot sidecars. The
//!     length+digest gate is aimed at the SIGNED envelope by that function's own API.
//!  6. **§7.1 acceptance** — `verify_and_accept` over the broker's OWN pinned keys and the prepared
//!     object's `IssuedRequest`.
//!
//! # Fail-closed, with no fallback anywhere
//!
//! Every step returns `Err(TurnReason::UpstreamBlocked)` on any refusal, loss, malformation or
//! mismatch, and there is deliberately no arm anywhere in this file that reaches the direct path, a
//! cached result, or a fabricated one. A fallback would leave the old behaviour live while looking
//! replaced, which is worse than not starting.
//!
//! # What this path CANNOT bind, and where that binding went
//!
//! `expected_execution_attempt_id` is `None`. §2.6 gives `accept-open` to the SIDECAR principal, so the
//! attempt id is minted by the supervisor and reaches the broker only as the §4.10(e) transport echo and
//! inside the signed envelope — feeding either back in as "expected" would be this process comparing a
//! value against itself. `run_id` and `task_id` ARE minted here and stay mandatory. What binds one
//! challenge to one attempt is the supervisor's own `governed_turn_acceptance` table
//! (`UNIQUE (challenge_handle)`, `UNIQUE (install_id, request_nonce)`, `UNIQUE (execution_attempt_id)`).
//! That is a durable constraint held by a different party, and it is written here rather than left for a
//! reader to reconstruct.

use std::sync::{Arc, Mutex};

use serde_json::{json, Value};

use brops_core::governed_bridge_result::SignedTurnResult;
use brops_core::governed_message_store::AcceptedOutput;
use brops_core::governed_output_pull::{pull_output, PullError};
use brops_core::governed_prepare::{
    prepare_governed_turn_v1b, resolve_governed_generation_config_v1b, GovernedChatMsg,
    PreparedGovernedTurnV1B, HISTORY_ROLES,
};
use brops_core::governed_submit::{
    governed_turn_submit_prepared, ChallengeDocument, GovernedTurnExecutionV1B, SubmitTransport,
};
use brops_core::governed_turn_ipc::{TurnReason, ValidatedRequest};
use brops_core::governed_verification::{
    verify_and_accept, AcceptanceLedger, BrokerContext, Freshness, OwnedReceiptEnvelope, PinnedKeys,
    SupervisorAttestation,
};

use crate::chain_executor::{GovernedTurnChain, HopConnector, SystemWallClock, WallClock};
use crate::chain_hops::{hop_roundtrip, parse_reply, Principal};
use crate::manifest_resolver::KeyResolver;

// =================================================================================================
// The seams
// =================================================================================================

/// The turn's actual content: the `system` string that will be sent and hashed, and the already-selected
/// history window in the order it will be sent and hashed.
///
/// **This is the seam the whole change is about.** It is not `Option`al and it has no default: a
/// deployment that cannot say what the conversation is cannot produce a governed turn, and the
/// alternative — reading three digests out of a config file — is the defect this module replaces.
///
/// It returns the RAW material rather than digests, deliberately. Digests are computed exactly once, by
/// `prepare_governed_turn_v1b`, from the same bytes that are sent; an implementation that could return a
/// digest could return one that disagrees with its own bytes, and there would be no way to tell.
pub trait TurnContent {
    fn resolve(&self, req: &ValidatedRequest) -> Result<TurnMaterial, TurnReason>;
}

/// What [`TurnContent`] hands back. Public fields: it is a value, not an authority — every bound that
/// matters (role enum, per-message cap, message count, 8 MiB conversation ceiling) is applied by
/// `prepare_governed_turn_v1b`, which is the one place they are applied for any caller.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TurnMaterial {
    pub system: String,
    pub history: Vec<GovernedChatMsg>,
}

/// The broker-minted per-turn run identities (§4.10(g): backend-generated, never renderer-supplied).
///
/// Separate from `broker_orchestrator::BrokerIds` — those two are the broker_turn_id and the request
/// nonce, which the orchestrator mints before this chain is entered. These are the §4.1 challenge's
/// `run_id`/`task_id`, and they are minted HERE because they must be the values the challenge is asked
/// for AND the values `verify_and_accept` is told to expect.
pub trait TurnIds {
    fn new_run_id(&self) -> String;
    fn new_task_id(&self) -> String;
}

/// Production: fresh UUID v4 per turn, from the same mint the broker's other identities use.
pub struct UuidTurnIds;
impl TurnIds for UuidTurnIds {
    fn new_run_id(&self) -> String {
        brops_core::id()
    }
    fn new_task_id(&self) -> String {
        brops_core::id()
    }
}

// =================================================================================================
// The production content source
// =================================================================================================

/// Reads the conversation out of the desktop's `messages` table (migration `0003_conversations.sql`)
/// and pairs it with the agent's `system` string.
///
/// **`system` comes from configuration and `history` does not, and that asymmetry is correct.** The
/// system prompt is a property of the agent the deployment installed; the conversation is a property of
/// what the user said. The defect this module replaces was not "a value came from config", it was that
/// `system_sha256` was ITSELF a config value — a digest that could disagree with the bytes it claimed to
/// describe, with nothing comparing them. Here the string is configured and the digest is computed from
/// it, so the two cannot diverge.
///
/// Fail-closed: an unopenable DB, an unreadable row, a `role` outside the closed §4.10(g) set, or a
/// non-UTF8 body all Block. There is no "skip the bad row" arm — a history with a message missing is a
/// different conversation, and hashing it would commit the chain to bytes the user never saw.
pub struct SqliteTurnContent {
    messages_db_path: String,
    system: String,
    /// How many of the most recent messages form the window. The window rule lives with the caller
    /// (`prepare_governed_turn_v1b` deliberately does not trim), and this is that caller.
    window: usize,
}

impl SqliteTurnContent {
    pub fn new(messages_db_path: impl Into<String>, system: impl Into<String>, window: usize) -> Self {
        SqliteTurnContent {
            messages_db_path: messages_db_path.into(),
            system: system.into(),
            window,
        }
    }

    /// The window read, factored out so a test can drive it against an in-memory connection without a
    /// file on disk. `conn` must already carry the `0003` `messages` table.
    pub fn read_window(
        conn: &rusqlite::Connection,
        conversation_id: &str,
        window: usize,
    ) -> Result<Vec<GovernedChatMsg>, TurnReason> {
        if window == 0 {
            return Err(TurnReason::UpstreamBlocked);
        }
        let mut stmt = conn
            .prepare(
                "SELECT role, body FROM messages WHERE conversation_id = ?1 \
                 ORDER BY created_at DESC, id DESC LIMIT ?2",
            )
            .map_err(|_| TurnReason::UpstreamBlocked)?;
        let rows = stmt
            .query_map(rusqlite::params![conversation_id, window as i64], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })
            .map_err(|_| TurnReason::UpstreamBlocked)?;
        let mut newest_first: Vec<GovernedChatMsg> = Vec::new();
        for row in rows {
            let (role, body) = row.map_err(|_| TurnReason::UpstreamBlocked)?;
            // The closed role set is checked HERE as well as inside `prepare_governed_turn_v1b`, and
            // the duplication is deliberate in exactly one direction: this one turns an unexpected
            // stored role into a Block naming the store, rather than into a `PrepareError` that reads
            // as though the caller passed something bad. Both refuse; neither substitutes a default.
            if !HISTORY_ROLES.contains(&role.as_str()) {
                return Err(TurnReason::UpstreamBlocked);
            }
            newest_first.push(GovernedChatMsg::new(role, body));
        }
        newest_first.reverse(); // chronological — the order that is sent, and therefore hashed
        Ok(newest_first)
    }
}

impl TurnContent for SqliteTurnContent {
    fn resolve(&self, req: &ValidatedRequest) -> Result<TurnMaterial, TurnReason> {
        let conn = rusqlite::Connection::open(&self.messages_db_path)
            .map_err(|_| TurnReason::UpstreamBlocked)?;
        let history = Self::read_window(&conn, &req.conversation_id, self.window)?;
        // A conversation with no messages is not a turn. Refusing here rather than hashing the empty
        // history keeps "there was nothing to send" from producing a signed receipt for nothing.
        if history.is_empty() {
            return Err(TurnReason::UpstreamBlocked);
        }
        Ok(TurnMaterial { system: self.system.clone(), history })
    }
}

// =================================================================================================
// The chain
// =================================================================================================

/// The broker-side §4.10(g) ladder as a [`GovernedTurnChain`], so it drops into the existing
/// `ChainExecutor` (and therefore into the existing `CustodyResolver` discipline) without a second
/// executor type.
pub struct LadderChain {
    keys: Box<dyn KeyResolver>,
    connector: Box<dyn HopConnector>,
    content: Box<dyn TurnContent>,
    transport: Box<dyn SubmitTransport>,
    ids: Box<dyn TurnIds>,
    ledger: Mutex<Box<dyn AcceptanceLedger>>,
    clock: Arc<dyn WallClock>,
}

impl LadderChain {
    /// Build with the real §7.1 wall clock. Every production construction goes through here; only
    /// [`with_clock`](LadderChain::with_clock) can replace it, and only a freshness test does.
    pub fn new(
        keys: Box<dyn KeyResolver>,
        connector: Box<dyn HopConnector>,
        content: Box<dyn TurnContent>,
        transport: Box<dyn SubmitTransport>,
        ids: Box<dyn TurnIds>,
        ledger: Box<dyn AcceptanceLedger>,
    ) -> Self {
        LadderChain {
            keys,
            connector,
            content,
            transport,
            ids,
            ledger: Mutex::new(ledger),
            clock: Arc::new(SystemWallClock),
        }
    }

    pub fn with_clock(mut self, clock: Arc<dyn WallClock>) -> Self {
        self.clock = clock;
        self
    }

    /// One framed request→reply roundtrip to the challenge authority. The op is read off the request
    /// being sent, so the echo check cannot be satisfied by a constant that drifted from the builder —
    /// the same discipline, and the same `chain_hops::parse_reply`, the direct path uses.
    fn hop(&self, principal: Principal, request: &Value) -> Result<Value, TurnReason> {
        let op = request
            .get("op")
            .and_then(Value::as_str)
            .ok_or(TurnReason::UpstreamBlocked)?
            .to_string();
        let bytes = serde_json::to_vec(request).map_err(|_| TurnReason::UpstreamBlocked)?;
        let mut conn = self.connector.connect(principal).map_err(|e| e.to_turn_reason())?;
        let reply = hop_roundtrip(conn.as_mut(), &bytes).map_err(|e| e.to_turn_reason())?;
        parse_reply(&op, &reply).map_err(|e| e.to_turn_reason())
    }

    /// §4.1: obtain the signed challenge for exactly the PREPARED facts.
    ///
    /// `requested_at_ms` is not a fresh clock read — it is `prepared.context().requested_at` parsed
    /// back. It has to be: `submit_frame`'s `RequestSha256` cross-binding compares
    /// `prepared.request_sha256()` against the authority's own recomputation, and `requested_at` is one
    /// of the eight §2.2 fields both sides hash. A second `now()` here would differ by however long
    /// preparation took and the turn would Block on a binding that is really a clock skew.
    /// [`tests::the_challenge_facts_are_the_prepared_facts`] is that equality, as arithmetic.
    fn issue_challenge(
        &self,
        prepared: &PreparedGovernedTurnV1B,
        run_id: &str,
        task_id: &str,
    ) -> Result<ChallengeDocument, TurnReason> {
        let ctx = prepared.context();
        let requested_at_ms: i64 =
            ctx.requested_at.parse().map_err(|_| TurnReason::UpstreamBlocked)?;
        let create_pending = json!({
            "op": "create-pending",
            "run_id": run_id,
            "task_id": task_id,
            "workspace_id": ctx.workspace_id,
            "install_id": ctx.install_id,
            "request_nonce": ctx.request_nonce,
            "system_sha256": ctx.system_sha256,
            "history_sha256": ctx.history_sha256,
            "generation_config_sha256": ctx.generation_config_sha256,
            "requested_at_ms": requested_at_ms,
        });
        let reply = self.hop(Principal::ChallengeAuthority, &create_pending)?;
        let pending_id = reply
            .get("pending_challenge_id")
            .and_then(Value::as_str)
            .ok_or(TurnReason::UpstreamBlocked)?
            .to_string();

        let issue = json!({ "op": "issue", "pending_challenge_id": pending_id });
        let reply = self.hop(Principal::ChallengeAuthority, &issue)?;
        let document = reply.get("challenge").ok_or(TurnReason::UpstreamBlocked)?;
        // The bytes §4.10(a0) will re-hash. `serde_json::to_vec` over a `Value` object is
        // sorted-key/compact — the same JCS shortcut `ReceiptEnvelope::payload_jcs` and the ladder's
        // Python half (`_canonical_bytes`) both take for this fixed ASCII key set, so the handle the
        // supervisor computes is the handle this side committed to.
        let bytes = serde_json::to_vec(document).map_err(|_| TurnReason::UpstreamBlocked)?;
        ChallengeDocument::from_bytes(&bytes).map_err(|e| e.to_turn_reason())
    }

    /// §4.10(f): pull the output back through fresh one-shot sidecars and let
    /// [`pull_output`] gate it against the SIGNED envelope. A local transport failure is
    /// [`PullError::Transport`] and never a stream verdict — the distinction §4.10(f) P1-5 fixes.
    fn pull(
        &self,
        envelope: &brops_core::governed_verification::ReceiptEnvelope,
        signed: &SignedTurnResult,
    ) -> Result<Vec<u8>, TurnReason> {
        pull_output(envelope, signed.output_stream_id(), |request| {
            self.transport.call(request).map_err(PullError::Transport)
        })
        .map_err(|_| TurnReason::UpstreamBlocked)
    }
}

impl GovernedTurnChain for LadderChain {
    fn run_verified(
        &self,
        req: &ValidatedRequest,
        broker_turn_id: &str,
        request_nonce: &str,
    ) -> Result<AcceptedOutput, TurnReason> {
        // (0) Trust anchors first — before a hop, before the conversation is even read. A manifest that
        //     does not verify, an epoch below the persisted floor, or a revoked/expired key is a turn
        //     that must not start.
        let keys = self.keys.resolve_keys()?;

        // (1) THE PER-CONVERSATION MATERIAL. Everything below hashes THIS.
        let material = self.content.resolve(req)?;

        // (2) One preparation: the nonce minted once, the three digests computed once, from the bytes
        //     that are actually sent.
        //
        //     `request_nonce` here is `prepared`'s, NOT the orchestrator's — the two mints are a known
        //     seam (`prepare_governed_turn_v1b`'s own doc records it: §4.10(g) step 1 makes preparation
        //     the mint, while `broker_orchestrator` already keyed a durable `broker_turns` row on its
        //     own). The prepared one wins here because it is the one bound into `request_sha256`, and
        //     therefore the one the authority signs and the one `Expected` must carry; the
        //     orchestrator's remains the durable turn key. They are not reconciled locally, and the
        //     unused binding is named rather than silently shadowed.
        let _orchestrator_nonce = request_nonce;
        let now_ms = self.clock.now_ms().ok_or(TurnReason::UpstreamBlocked)?;
        let now_u64 = u64::try_from(now_ms).map_err(|_| TurnReason::UpstreamBlocked)?;
        let generation_config =
            resolve_governed_generation_config_v1b().map_err(|_| TurnReason::UpstreamBlocked)?;
        let prepared = prepare_governed_turn_v1b(
            &material.system,
            &material.history,
            generation_config,
            now_u64,
            &keys.workspace_id,
            &keys.install_id,
        )
        .map_err(|_| TurnReason::UpstreamBlocked)?;

        // (3) The broker's own run identities, and the §4.1 challenge over the prepared facts.
        let run_id = self.ids.new_run_id();
        let task_id = self.ids.new_task_id();
        let challenge = self.issue_challenge(&prepared, &run_id, &task_id)?;

        // (4) §4.10(g). `governed_turn_submit_prepared` asserts all four cross-bindings BEFORE it
        //     writes a frame, then drives one one-shot sidecar and strict-decodes the §4.6 reply. A
        //     governed refusal comes back as an Err arm, so the success path cannot be reached by
        //     forgetting to match one.
        let execution =
            GovernedTurnExecutionV1B::new(&req.conversation_id, &run_id, &task_id, prepared.clone())
                .map_err(|e| e.to_turn_reason())?;
        let signed = governed_turn_submit_prepared(&execution, &challenge, self.transport.as_ref())
            .map_err(|e| e.to_turn_reason())?;

        // (5) The §4.9 envelope, strict-parsed from the exact bytes the signer signed.
        let envelope_value: Value = serde_json::from_slice(signed.envelope_jcs())
            .map_err(|_| TurnReason::UpstreamBlocked)?;
        let owned = OwnedReceiptEnvelope::from_payload(&envelope_value)?;
        let envelope = owned.as_receipt_envelope();
        // §7.1 echo equality. Worth exactly what its own doc says — a consistency check on the
        // transport, never a second opinion about the turn — and free, so it runs before the pull
        // spends a round trip per chunk.
        signed.check_echoes(&envelope)?;

        // (6) §4.10(f) egress. The bytes are gated against the SIGNED length and digest by
        //     `pull_output`'s own API, which takes no expected-length parameter precisely so that no
        //     caller (including this one) can aim it at the §4.10(e) transport echo.
        let output = self.pull(&envelope, &signed)?;

        // (7) §7.1 acceptance over the broker's OWN pinned keys and the prepared object's Expected.
        //     Nothing here is read off the wire: the keys came from the root-signed manifest, and
        //     every one of the eight request fields came from `prepared`.
        let message_id = format!("m-{broker_turn_id}");
        let pinned = PinnedKeys {
            isolated_signer_key_id: &keys.isolated_signer_key_id,
            isolated_signer_public_key: &keys.isolated_signer_public_key,
            supervisor_attestation_key_id: &keys.supervisor_attestation_key_id,
            supervisor_attestation_public_key: &keys.supervisor_attestation_public_key,
        };
        let expected = prepared.issued_request();
        let attestation = SupervisorAttestation {
            evidence_jcs: signed.attestation_evidence_jcs(),
            signature_b64: signed.attestation_signature_b64(),
        };
        let ctx = BrokerContext {
            broker_turn_id,
            message_id: &message_id,
            conversation_id: &req.conversation_id,
            author: &keys.author,
            expected_run_id: &run_id,
            expected_task_id: &task_id,
            // See the module note. This principal did not obtain the lease and therefore holds no
            // independent attempt id; the alternative is comparing the envelope against itself.
            expected_execution_attempt_id: None,
        };
        // The clock is read HERE, at acceptance, not at turn start: the receipt ages while the ladder
        // runs, and the question §7.1 asks is how old it is when it is committed.
        let accept_ms = self.clock.now_ms().ok_or(TurnReason::UpstreamBlocked)?;
        let mut ledger = self.ledger.lock().map_err(|_| TurnReason::UpstreamBlocked)?;
        verify_and_accept(
            &expected,
            &envelope,
            signed.envelope_signature_b64(),
            &attestation,
            &pinned,
            &output,
            &ctx,
            ledger.as_mut(),
            &Freshness::at(accept_ms),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use brops_core::governed_prepare::GovernedGenerationConfig;
    use brops_core::receipt::sha256_hex;
    use std::cell::RefCell;
    use std::rc::Rc;

    fn req(conversation_id: &str) -> ValidatedRequest {
        ValidatedRequest {
            conversation_id: conversation_id.into(),
            agent: Some("Bro".into()),
            client_request_id: "3f2504e0-4f89-41d3-9a0c-0305e82c3301".into(),
        }
    }

    fn msgs(pairs: &[(&str, &str)]) -> Vec<GovernedChatMsg> {
        pairs.iter().map(|(r, c)| GovernedChatMsg::new(*r, *c)).collect()
    }

    fn config() -> GovernedGenerationConfig {
        resolve_governed_generation_config_v1b().expect("the frozen defaults validate")
    }

    // ---------------------------------------------------------------------------------------------
    // THE POINT OF THE CHANGE, as arithmetic rather than as a comment
    // ---------------------------------------------------------------------------------------------

    /// Two different conversations must produce two different `history_sha256`.
    ///
    /// This is the whole difference between this path and the direct one. `ProductionResolver`'s
    /// `ResolvedFacts` reads that digest from `$BROPS_BROKER_CONFIG`, so on that path this assertion is
    /// false by construction — the same 64 hex characters for every conversation the deployment ever
    /// runs. Here the digest is `SHA256(history_jcs(messages))` over the messages the content source
    /// returned, so it moves when the conversation does.
    #[test]
    fn the_history_digest_follows_the_conversation_not_the_config() {
        let a = prepare_governed_turn_v1b(
            "sys", &msgs(&[("user", "what is the floor")]), config(), 1_900_000_000_000, "ws", "inst",
        )
        .unwrap();
        let b = prepare_governed_turn_v1b(
            "sys", &msgs(&[("user", "what is the ceiling")]), config(), 1_900_000_000_000, "ws", "inst",
        )
        .unwrap();
        assert_ne!(
            a.context().history_sha256,
            b.context().history_sha256,
            "a per-conversation digest that does not move with the conversation is a config constant"
        );
        // ... and the `system` digest is the digest OF the system bytes, not an independent value.
        assert_eq!(a.context().system_sha256, sha256_hex(b"sys"));
        // ... and the two turns are different requests, so the §2.2 envelope digest differs too.
        assert_ne!(a.request_sha256(), b.request_sha256());
    }

    /// `create-pending`'s `requested_at_ms` must be `prepared.context().requested_at` parsed back, and
    /// not a second clock read.
    ///
    /// The arithmetic: `requested_at` is one of the eight §2.2 fields `request_sha256` is computed
    /// over, and `submit_frame` refuses with `CrossBinding::RequestSha256` when the authority's
    /// recomputation disagrees. Two clock reads differ by the preparation time, so a fresh `now()` in
    /// `issue_challenge` would make every turn Block on what is really a skew. Asserted on the value
    /// the hop actually sends.
    #[test]
    fn the_challenge_facts_are_the_prepared_facts() {
        let now = 1_900_000_123_456i64;
        let prepared = prepare_governed_turn_v1b(
            "sys", &msgs(&[("user", "hi")]), config(), now as u64, "ws", "inst",
        )
        .unwrap();
        let ctx = prepared.context();
        assert_eq!(ctx.requested_at, now.to_string());
        let sent_back: i64 = ctx.requested_at.parse().unwrap();
        assert_eq!(sent_back, now);
        // The eight-field envelope digest is stable across a re-read of the same context, which is the
        // property the equality above exists to preserve.
        assert_eq!(prepared.request_sha256(), prepared.issued_request().request_sha256());
    }

    // ---------------------------------------------------------------------------------------------
    // The content source
    // ---------------------------------------------------------------------------------------------

    fn messages_db(rows: &[(&str, &str, &str, &str)]) -> rusqlite::Connection {
        let conn = rusqlite::Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, \
             role TEXT NOT NULL, author TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);",
        )
        .unwrap();
        for (id, conv, role, body) in rows {
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, author, body, created_at) \
                 VALUES (?1, ?2, ?3, 'u', ?4, ?1)",
                rusqlite::params![id, conv, role, body],
            )
            .unwrap();
        }
        conn
    }

    #[test]
    fn the_window_is_the_newest_messages_in_chronological_order() {
        let conn = messages_db(&[
            ("001", "c1", "user", "first"),
            ("002", "c1", "assistant", "second"),
            ("003", "c1", "user", "third"),
            ("004", "c2", "user", "other conversation"),
        ]);
        let got = SqliteTurnContent::read_window(&conn, "c1", 2).unwrap();
        assert_eq!(got, msgs(&[("assistant", "second"), ("user", "third")]));
        // The other conversation is not in it — a window that leaked another thread would hash bytes
        // this turn never sent.
        let all = SqliteTurnContent::read_window(&conn, "c1", 10).unwrap();
        assert_eq!(all.len(), 3);
    }

    /// A stored `role` outside the closed §4.10(g) set Blocks. It is never mapped to `user`, and never
    /// dropped: both would hash a conversation different from the one on disk while looking like it
    /// had worked.
    #[test]
    fn an_unknown_role_blocks_rather_than_being_coerced() {
        let conn = messages_db(&[("001", "c1", "tool", "not one of the three")]);
        assert!(matches!(
            SqliteTurnContent::read_window(&conn, "c1", 10),
            Err(TurnReason::UpstreamBlocked)
        ));
    }

    #[test]
    fn a_zero_window_and_a_missing_table_both_block() {
        let conn = messages_db(&[("001", "c1", "user", "x")]);
        assert!(matches!(
            SqliteTurnContent::read_window(&conn, "c1", 0),
            Err(TurnReason::UpstreamBlocked)
        ));
        let empty = rusqlite::Connection::open_in_memory().unwrap();
        assert!(matches!(
            SqliteTurnContent::read_window(&empty, "c1", 10),
            Err(TurnReason::UpstreamBlocked)
        ));
    }

    #[test]
    fn a_conversation_with_no_messages_is_not_a_turn() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("messages.db");
        {
            let conn = rusqlite::Connection::open(&path).unwrap();
            conn.execute_batch(
                "CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, \
                 role TEXT NOT NULL, author TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);",
            )
            .unwrap();
        }
        let src = SqliteTurnContent::new(path.to_string_lossy().to_string(), "sys", 10);
        assert!(matches!(src.resolve(&req("c-empty")), Err(TurnReason::UpstreamBlocked)));
        // An unopenable database is the same refusal, never an empty history.
        let missing = SqliteTurnContent::new(
            dir.path().join("no-such-dir").join("messages.db").to_string_lossy().to_string(),
            "sys",
            10,
        );
        assert!(matches!(missing.resolve(&req("c1")), Err(TurnReason::UpstreamBlocked)));
    }

    // ---------------------------------------------------------------------------------------------
    // The chain's fail-closed ordering
    // ---------------------------------------------------------------------------------------------

    struct NoKeys;
    impl KeyResolver for NoKeys {
        fn resolve_keys(&self) -> Result<crate::manifest_resolver::ResolvedKeys, TurnReason> {
            Err(TurnReason::UpstreamBlocked)
        }
    }

    /// Counts its calls through a handle the TEST keeps, so "the conversation was never read" is an
    /// assertion rather than a comment. The first version of this owned its counter privately, and a
    /// mutation that moved `resolve_keys` to run AFTER `content.resolve` survived every test in this
    /// module — a counter nobody can read is not a counter.
    #[derive(Clone)]
    struct CountingContent(Rc<RefCell<usize>>);
    impl TurnContent for CountingContent {
        fn resolve(&self, _req: &ValidatedRequest) -> Result<TurnMaterial, TurnReason> {
            *self.0.borrow_mut() += 1;
            Ok(TurnMaterial { system: "s".into(), history: msgs(&[("user", "hi")]) })
        }
    }

    /// Real-shaped pinned keys, so a test can reach past rung 0.
    struct Keys;
    impl KeyResolver for Keys {
        fn resolve_keys(&self) -> Result<crate::manifest_resolver::ResolvedKeys, TurnReason> {
            Ok(crate::manifest_resolver::ResolvedKeys {
                isolated_signer_key_id: "signer-1".into(),
                isolated_signer_public_key: [7u8; 32],
                supervisor_attestation_key_id: "sup-1".into(),
                supervisor_attestation_public_key: [9u8; 32],
                workspace_id: "ws".into(),
                install_id: "inst".into(),
                author: "Bro".into(),
            })
        }
    }

    /// A challenge-authority that answers from a script and KEEPS every request it was sent, so the
    /// facts the hop actually put on the wire can be asserted rather than assumed.
    struct RecordingHops {
        /// ONE shared script across every connection. It was a per-connector `RefCell` taken with
        /// `mem::take` on first connect, so the second hop found an empty queue and the whole test
        /// Blocked — the fake, not the code. Recorded because a fake that drains itself is the kind of
        /// double whose failure reads as a real refusal.
        replies: Rc<RefCell<Vec<Vec<u8>>>>,
        sent: Rc<RefCell<Vec<Value>>>,
    }
    struct RecordingConn {
        replies: Rc<RefCell<Vec<Vec<u8>>>>,
        sent: Rc<RefCell<Vec<Value>>>,
    }
    impl crate::chain_hops::HopConn for RecordingConn {
        fn send_all(&mut self, frame: &[u8]) -> Result<(), crate::chain_hops::HopError> {
            let body = brops_core::ipc_framing::decode_one(frame)
                .map_err(crate::chain_hops::HopError::Frame)?;
            self.sent
                .borrow_mut()
                .push(serde_json::from_slice(body).map_err(|_| crate::chain_hops::HopError::BadReply)?);
            Ok(())
        }
        fn recv_all(&mut self) -> Result<Vec<u8>, crate::chain_hops::HopError> {
            let mut q = self.replies.borrow_mut();
            if q.is_empty() {
                return Err(crate::chain_hops::HopError::Unavailable);
            }
            let next = q.remove(0);
            brops_core::ipc_framing::encode_frame(&next).map_err(crate::chain_hops::HopError::Frame)
        }
    }
    impl HopConnector for RecordingHops {
        fn connect(
            &self,
            _p: Principal,
        ) -> Result<Box<dyn crate::chain_hops::HopConn>, crate::chain_hops::HopError> {
            // One fresh connection per hop, sharing the script and the transcript.
            Ok(Box::new(RecordingConn {
                replies: Rc::clone(&self.replies),
                sent: Rc::clone(&self.sent),
            }))
        }
    }

    struct NeverConnects;
    impl HopConnector for NeverConnects {
        fn connect(
            &self,
            _p: Principal,
        ) -> Result<Box<dyn crate::chain_hops::HopConn>, crate::chain_hops::HopError> {
            Err(crate::chain_hops::HopError::Unavailable)
        }
    }

    struct NeverCalled;
    impl SubmitTransport for NeverCalled {
        fn call(&self, _frame: &Value) -> Result<Value, String> {
            panic!("the transport must not be reached once an earlier rung has refused");
        }
    }

    struct NoLedger;
    impl AcceptanceLedger for NoLedger {
        fn claim(
            &mut self,
            _receipt_id: &str,
            _request_nonce: &str,
        ) -> Result<(), brops_core::governed_verification::LedgerRefusal> {
            panic!("the ledger must not be reached once an earlier rung has refused");
        }
    }

    fn chain(
        keys: Box<dyn KeyResolver>,
        connector: Box<dyn HopConnector>,
        content: Box<dyn TurnContent>,
    ) -> LadderChain {
        LadderChain::new(
            keys,
            connector,
            content,
            Box::new(NeverCalled),
            Box::new(UuidTurnIds),
            Box::new(NoLedger),
        )
    }

    /// Keys are resolved BEFORE the conversation is read and before any hop. A manifest that does not
    /// verify must not cause a database read or a socket connect, and the counter proves the ordering
    /// rather than the comment asserting it.
    #[test]
    fn an_unresolvable_manifest_blocks_before_anything_else_runs() {
        let content = CountingContent(Rc::new(RefCell::new(0)));
        let reads = Rc::clone(&content.0);
        let chain = chain(Box::new(NoKeys), Box::new(NeverConnects), Box::new(content));
        assert!(matches!(
            chain.run_verified(&req("c1"), "bt-1", "nonce-1"),
            Err(TurnReason::UpstreamBlocked)
        ));
        assert_eq!(
            *reads.borrow(),
            0,
            "an unresolvable manifest must Block BEFORE the conversation is read: a turn whose trust \
             anchors do not resolve has nothing to prepare, and reading first would put a database \
             hit and a nonce mint behind a wall that was already shut"
        );
    }

    /// A lost challenge-authority hop Blocks, and the submit transport is never reached — there is no
    /// arm anywhere that falls back to the direct path or to a fabricated challenge. `NeverCalled`
    /// panics if it is, so this test fails loudly rather than silently if a fallback is ever added.
    #[test]
    fn a_lost_authority_hop_blocks_and_never_reaches_the_sidecar() {
        let content = CountingContent(Rc::new(RefCell::new(0)));
        let reads = Rc::clone(&content.0);
        let chain = chain(Box::new(Keys), Box::new(NeverConnects), Box::new(content));
        assert!(matches!(
            chain.run_verified(&req("c1"), "bt-1", "nonce-1"),
            Err(TurnReason::UpstreamBlocked)
        ));
        // The conversation WAS read this time — rung 0 passed — which is what makes the counter in
        // the previous test evidence of ordering rather than of nothing ever running.
        assert_eq!(*reads.borrow(), 1);
    }

    /// The facts `create-pending` puts on the wire are the PREPARED facts, asserted on the bytes the
    /// hop actually sent.
    ///
    /// The arithmetic, and why it is a test: `requested_at` is one of the eight §2.2 fields
    /// `request_sha256` is computed over, and `submit_frame` refuses with
    /// `CrossBinding::RequestSha256` when the authority's own recomputation disagrees. So a
    /// `requested_at_ms` that is off by ONE from `prepared.context().requested_at` — a second clock
    /// read, an off-by-one, a "strictly in the past" adjustment copied from the Python driver — makes
    /// every turn Block on what is really a skew. A mutation that added `+ 1` here survived every
    /// other test in this module.
    #[test]
    fn the_create_pending_hop_sends_exactly_the_prepared_facts() {
        let now = 1_900_000_123_456i64;
        let prepared = prepare_governed_turn_v1b(
            "sys", &msgs(&[("user", "hi")]), config(), now as u64, "ws", "inst",
        )
        .unwrap();
        let ctx = prepared.context().clone();
        let document = json!({
            "payload": {
                "task_id": "task-1",
                "run_id": "run-1",
                "generation_config_sha256": ctx.generation_config_sha256,
                "request_sha256": prepared.request_sha256(),
                "install_id": ctx.install_id,
                "request_nonce": ctx.request_nonce,
            },
            "sig": "not-verified-here",
        });
        let sent = Rc::new(RefCell::new(Vec::new()));
        let hops = RecordingHops {
            replies: Rc::new(RefCell::new(vec![
                serde_json::to_vec(
                    &json!({"ok": true, "op": "create-pending", "pending_challenge_id": "p1"}),
                )
                .unwrap(),
                serde_json::to_vec(&json!({"ok": true, "op": "issue", "challenge": document}))
                    .unwrap(),
            ])),
            sent: Rc::clone(&sent),
        };
        let chain = chain(
            Box::new(Keys),
            Box::new(hops),
            Box::new(CountingContent(Rc::new(RefCell::new(0)))),
        );
        let doc = chain.issue_challenge(&prepared, "run-1", "task-1").expect("the hops answer");

        let transcript = sent.borrow();
        assert_eq!(transcript.len(), 2, "create-pending then issue, one connection each");
        let cp = &transcript[0];
        assert_eq!(cp["op"], "create-pending");
        // THE arithmetic: the integer sent equals the canonical decimal string prepared holds.
        assert_eq!(cp["requested_at_ms"].as_i64().unwrap(), now);
        assert_eq!(cp["requested_at_ms"].as_i64().unwrap().to_string(), ctx.requested_at);
        // ... and every other fact is the prepared one, not a second derivation.
        assert_eq!(cp["system_sha256"], ctx.system_sha256);
        assert_eq!(cp["history_sha256"], ctx.history_sha256);
        assert_eq!(cp["generation_config_sha256"], ctx.generation_config_sha256);
        assert_eq!(cp["request_nonce"], ctx.request_nonce);
        assert_eq!(cp["workspace_id"], ctx.workspace_id);
        assert_eq!(cp["install_id"], ctx.install_id);
        assert_eq!(cp["run_id"], "run-1");
        assert_eq!(cp["task_id"], "task-1");
        assert_eq!(transcript[1]["op"], "issue");
        assert_eq!(transcript[1]["pending_challenge_id"], "p1");

        // The document is carried as the EXACT bytes, and those bytes cross-bind to the prepared
        // object — which is what `submit_frame` will assert a moment later.
        assert_eq!(doc.request_sha256(), prepared.request_sha256());
        assert_eq!(doc.generation_config_sha256(), ctx.generation_config_sha256);
        assert_eq!(doc.request_nonce(), ctx.request_nonce);
        assert_eq!(doc.bytes(), serde_json::to_vec(&document).unwrap().as_slice());
    }

    /// The module contains no fallback to the direct path. Asserted against the SOURCE, the same way
    /// `governed_bridge_result` asserts its own missing accessors: a reviewer reading a promise in a
    /// doc comment cannot tell whether it is still true, and this can.
    ///
    /// Two details make it a real check rather than a green one. It scans only the half of the file
    /// ABOVE the test module, because the needles below are needles; and each needle is ASSEMBLED at
    /// runtime, so the scanner's own literals cannot satisfy it either. The first version of this test
    /// failed against itself, which is the cheapest available demonstration that a source scan must
    /// exclude its own text.
    #[test]
    fn the_ladder_has_no_arm_that_reaches_the_direct_chain() {
        let whole = include_str!("ladder_executor.rs");
        let production = whole.split("#[cfg(te").next().expect("split always yields a head");
        assert!(production.len() > 1000, "the production half must be what is scanned");
        for forbidden in [
            format!("Governed{}::", "Chain"),
            format!("Linux{}Execution", "Governed"),
            format!("Linux{}TurnChain", "Governed"),
        ] {
            assert!(
                !production.contains(&forbidden),
                "the ladder must not name `{forbidden}`: a fallback leaves the old behaviour live                  while looking replaced"
            );
        }
    }
}
