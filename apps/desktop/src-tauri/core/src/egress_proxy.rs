//! The egress authorizer — the destination axis, and nothing else.
//!
//! Design: `docs/design/PRODUCTION_HALF_DESIGN.md` §3.2 (how an allowlist is
//! expressed) and §3.3 (which runtime code enforces it).
//!
//! §3.3 is NOT IMPLEMENTED. Nothing in this tree refuses an outbound
//! connection, and this module does not change that: it is the **decision**
//! that §3.3's enforcement point will ask, and it is not the socket, not the
//! jail, and not a wiring.
//!
//! ## Two populations, two allowlists, one authorizer
//!
//! The Owner's rule, and the reason this file takes its allowlist as data
//! rather than reading one:
//!
//! - the **produced agent** runs a customer flow and needs one or two hosts.
//!   Its allowlist is [`crate::agent_bundle::Grant::egress`], written by the
//!   runtime from values it holds, never from a prompt.
//! - the **build agent** writes code and needs a package registry. Its
//!   allowlist is broad, fixed and declared, and it is NOT this module's
//!   business which hosts are on it.
//!
//! Mixing them is how a dependency-install allowlist becomes a customer
//! agent's authority. `EgressGrant` therefore carries [`Population`], so a
//! decision record says which grant admitted or refused a destination and a
//! reader can never mistake one for the other.
//!
//! ## Why this lives in `core` and not in `src`
//!
//! §3.3 is NOT IMPLEMENTED, and where its enforcement point sits is part of
//! what is missing. It names `apps/desktop/src-tauri/src/egress_proxy.rs`.
//! That path was
//! chosen when the enforcement point was assumed to be `ai.rs`'s spawn — the
//! build agent. The produced agent's enforcement point is the `StepKind::Call`
//! arm of `repo.rs`, which is in `core`, and `core` cannot see `src`: the
//! dependency runs `brops` → `brops-core`, one way. An authorizer in `src`
//! would be unreachable from the population that needs it most.
//!
//! ## Deny by default, and refuse rather than narrow
//!
//! An empty grant admits nothing. An entry that states an authority this layer
//! cannot enforce — a wildcard, an IP literal, a path, `http://` — is REFUSED
//! at parse time rather than quietly narrowed, because a grant whose text does
//! not mean what it says is the defect `commands.rs` already records for
//! `scope`.

use serde::{Deserialize, Serialize};

/// Stated, not implied. Every one of these is in the design and NOT in this
/// slice, so no reader has to infer the boundary from what happens to compile.
pub const NOT_IMPLEMENTED: &[&str] = &[
    "the loopback CONNECT listener: this module decides, it does not serve a socket, and \
     nothing in this tree yet accepts a CONNECT",
    "resolve-once-and-pin: the DNS-rebind defence belongs to the code that dials, which \
     does not exist at this head",
    "the network namespace (egress_jail.rs): no process is confined by anything here",
    "call steps: repo.rs still refuses StepKind::Call — this authorizer is not yet wired \
     to the produced agent's flow runner",
    "the build agent's lease field: allowed_egress on the execution lease is design §3.1",
];

/// Which population a grant governs. Not decorative: it is written into every
/// decision record so a build-agent allowance can never be read as a produced
/// agent's authority.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Population {
    /// The factory: an agent that writes code. Broad, fixed, declared.
    Build,
    /// A built agent running a customer flow. Narrow, from its grant.
    Produced,
}

impl Population {
    pub fn as_str(self) -> &'static str {
        match self {
            Population::Build => "build",
            Population::Produced => "produced",
        }
    }
}

/// The most destinations one grant may name. §3.2: "name them" must stay
/// bounded, and an unbounded allowlist is an allowlist nobody reads.
pub const MAX_DESTINATIONS: usize = 32;

/// The default port when an entry names none. `https://` and nothing else is
/// expressible, so the default is the one `https` means.
pub const DEFAULT_PORT: u16 = 443;

/// A destination a grant names: an exact host and an exact port.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Destination {
    pub host: String,
    pub port: u16,
}

impl Destination {
    pub fn render(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}

/// Why an entry could not be admitted into a grant. Distinct, stable strings:
/// they reach a decision record, where a reader compares them.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GrantError {
    /// Not `https://`. A plaintext destination cannot be authenticated, so the
    /// entry would grant "whoever holds the wire", not "that host".
    NotHttps(String),
    /// A path, query or fragment. The only layer that can enforce a
    /// destination sees `CONNECT host:port` and cannot see inside TLS.
    StatesAPath(String),
    /// A wildcard or suffix match. It converts an allowlist into a bypass and
    /// makes subset comparison undecidable.
    Wildcard(String),
    /// An IP literal. It cannot be re-checked against the NAME the grant
    /// stated, and `169.254.169.254` / `127.0.0.1` are the two that turn
    /// egress into privilege escalation.
    IpLiteral(String),
    /// Not lowercase. Folded rather than refused, a grant's text would stop
    /// being the thing a reader compares.
    NotLowercase(String),
    /// Not a hostname this layer can compare exactly.
    MalformedHost(String),
    /// A port that is not 1..=65535.
    MalformedPort(String),
    /// More than [`MAX_DESTINATIONS`].
    TooMany(usize),
    /// The same destination twice. A duplicate means two readings of one
    /// grant disagree about how many authorities it states.
    Duplicate(String),
}

impl GrantError {
    pub fn as_str(&self) -> &'static str {
        match self {
            GrantError::NotHttps(_) => "egress_entry_not_https",
            GrantError::StatesAPath(_) => "egress_entry_states_a_path",
            GrantError::Wildcard(_) => "egress_entry_wildcard",
            GrantError::IpLiteral(_) => "egress_entry_ip_literal",
            GrantError::NotLowercase(_) => "egress_entry_not_lowercase",
            GrantError::MalformedHost(_) => "egress_entry_malformed_host",
            GrantError::MalformedPort(_) => "egress_entry_malformed_port",
            GrantError::TooMany(_) => "egress_grant_too_many_destinations",
            GrantError::Duplicate(_) => "egress_entry_duplicate",
        }
    }
}

/// A parsed, validated allowlist, bound to the grant that stated it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EgressGrant {
    population: Population,
    grant_id: String,
    destinations: Vec<Destination>,
}

impl EgressGrant {
    /// Parse the entries a grant states. Refuses the whole grant if any single
    /// entry is unenforceable: a grant that half-parses is a grant whose
    /// authority nobody can state.
    pub fn parse(
        population: Population,
        grant_id: &str,
        entries: &[String],
    ) -> Result<Self, GrantError> {
        if entries.len() > MAX_DESTINATIONS {
            return Err(GrantError::TooMany(entries.len()));
        }
        let mut destinations: Vec<Destination> = Vec::with_capacity(entries.len());
        for entry in entries {
            let dest = parse_entry(entry)?;
            if destinations.contains(&dest) {
                return Err(GrantError::Duplicate(entry.clone()));
            }
            destinations.push(dest);
        }
        Ok(EgressGrant {
            population,
            grant_id: grant_id.to_string(),
            destinations,
        })
    }

    /// A grant that admits nothing. This is the produced agent's state at this
    /// head, and it is the correct one: `Grant::for_local_only` writes an empty
    /// egress because nothing in that slice may leave the box.
    pub fn empty(population: Population, grant_id: &str) -> Self {
        EgressGrant {
            population,
            grant_id: grant_id.to_string(),
            destinations: Vec::new(),
        }
    }

    pub fn population(&self) -> Population {
        self.population
    }

    pub fn grant_id(&self) -> &str {
        &self.grant_id
    }

    pub fn destinations(&self) -> &[Destination] {
        &self.destinations
    }

    /// Decide one destination. Exact match on host AND port; an empty grant
    /// denies everything.
    ///
    /// The requested host is normalised the way DNS itself defines equality —
    /// ASCII case folding and at most one trailing root dot — and by nothing
    /// else. That normalisation cannot widen the grant: it maps a name onto
    /// the same name, and every other spelling still fails the exact compare.
    pub fn authorize(&self, requested_host: &str, requested_port: u16) -> EgressDecision {
        let host = requested_host.to_string();
        let normalised = match normalise_request_host(requested_host) {
            Some(h) => h,
            None => {
                return self.deny(
                    host,
                    requested_port,
                    format!(
                        "requested host {:?} is not a comparable hostname",
                        requested_host
                    ),
                )
            }
        };
        let matched = self
            .destinations
            .iter()
            .find(|d| d.host == normalised && d.port == requested_port);
        match matched {
            Some(d) => EgressDecision {
                outcome: Outcome::Allowed,
                population: self.population,
                grant_id: self.grant_id.clone(),
                requested_host: host,
                requested_port,
                matched: Some(d.clone()),
                reason: format!(
                    "{} is named by grant {} ({}, {} destination(s))",
                    d.render(),
                    self.grant_id,
                    self.population.as_str(),
                    self.destinations.len()
                ),
            },
            None => self.deny(
                host,
                requested_port,
                format!(
                    "{}:{} is not named by grant {} ({}, {} destination(s))",
                    normalised,
                    requested_port,
                    self.grant_id,
                    self.population.as_str(),
                    self.destinations.len()
                ),
            ),
        }
    }

    fn deny(&self, host: String, port: u16, reason: String) -> EgressDecision {
        EgressDecision {
            outcome: Outcome::Denied,
            population: self.population,
            grant_id: self.grant_id.clone(),
            requested_host: host,
            requested_port: port,
            matched: None,
            reason,
        }
    }
}

/// Allowed or denied. There is no third outcome: a destination this layer
/// cannot decide is denied, and says so.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Outcome {
    Allowed,
    Denied,
}

/// One record per decision, allow and deny alike.
///
/// This is a decision record, and the word "evidence" is deliberately not used
/// for it: nothing here is signed, and `local_write_record.rs` already states
/// that this codebase's Rust-side tamper-evidence is not attestation of the
/// writer. Persisting it is the caller's job, so this module stays testable
/// with no database and no network.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EgressDecision {
    pub outcome: Outcome,
    pub population: Population,
    pub grant_id: String,
    pub requested_host: String,
    pub requested_port: u16,
    pub matched: Option<Destination>,
    pub reason: String,
}

impl EgressDecision {
    pub fn allowed(&self) -> bool {
        self.outcome == Outcome::Allowed
    }

    /// The audit event type. Stable: a reader groups on it.
    pub fn event_type(&self) -> &'static str {
        match self.outcome {
            Outcome::Allowed => "egress.allowed",
            Outcome::Denied => "egress.denied",
        }
    }
}

/// Parse one allowlist entry: `https://` + exact lowercase FQDN + optional
/// port. Nothing else is expressible — see §3.2 for why each exclusion is a
/// decision and not an oversight.
pub fn parse_entry(entry: &str) -> Result<Destination, GrantError> {
    let rest = match entry.strip_prefix("https://") {
        Some(r) => r,
        None => return Err(GrantError::NotHttps(entry.to_string())),
    };
    if rest.contains('*') {
        return Err(GrantError::Wildcard(entry.to_string()));
    }
    if rest.contains('/') || rest.contains('?') || rest.contains('#') {
        return Err(GrantError::StatesAPath(entry.to_string()));
    }
    if rest.contains('[') || rest.contains(']') {
        return Err(GrantError::IpLiteral(entry.to_string()));
    }
    if rest.contains('@') {
        return Err(GrantError::MalformedHost(entry.to_string()));
    }
    let (host, port) = match rest.rsplit_once(':') {
        Some((h, p)) => {
            if p.is_empty() || p.len() > 5 || !p.bytes().all(|b| b.is_ascii_digit()) {
                return Err(GrantError::MalformedPort(entry.to_string()));
            }
            let parsed: u32 = p.parse().map_err(|_| GrantError::MalformedPort(entry.to_string()))?;
            if parsed == 0 || parsed > 65535 {
                return Err(GrantError::MalformedPort(entry.to_string()));
            }
            (h, parsed as u16)
        }
        None => (rest, DEFAULT_PORT),
    };
    validate_host(host, entry)?;
    Ok(Destination {
        host: host.to_string(),
        port,
    })
}

/// An exact lowercase FQDN: at least two labels, each `[a-z0-9]` with interior
/// hyphens, and a final label of letters only — which is what rejects an IPv4
/// literal without a second matcher to keep in step.
fn validate_host(host: &str, entry: &str) -> Result<(), GrantError> {
    if host.is_empty() || !host.is_ascii() {
        return Err(GrantError::MalformedHost(entry.to_string()));
    }
    if host != host.to_ascii_lowercase() {
        return Err(GrantError::NotLowercase(entry.to_string()));
    }
    let labels: Vec<&str> = host.split('.').collect();
    if labels.len() < 2 {
        return Err(GrantError::MalformedHost(entry.to_string()));
    }
    for label in &labels {
        if label.is_empty() || label.len() > 63 {
            return Err(GrantError::MalformedHost(entry.to_string()));
        }
        if !label
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        {
            return Err(GrantError::MalformedHost(entry.to_string()));
        }
        if label.starts_with('-') || label.ends_with('-') {
            return Err(GrantError::MalformedHost(entry.to_string()));
        }
    }
    let tld = labels[labels.len() - 1];
    if tld.bytes().all(|b| b.is_ascii_digit()) {
        return Err(GrantError::IpLiteral(entry.to_string()));
    }
    if tld.len() < 2 || tld.len() > 63 || !tld.bytes().all(|b| b.is_ascii_lowercase()) {
        return Err(GrantError::MalformedHost(entry.to_string()));
    }
    Ok(())
}

/// DNS's own equality and nothing wider: ASCII case folding and at most one
/// trailing root dot. Returns `None` for anything that is not a comparable
/// hostname, which the caller turns into a denial.
fn normalise_request_host(host: &str) -> Option<String> {
    if host.is_empty() || !host.is_ascii() {
        return None;
    }
    let trimmed = host.strip_suffix('.').unwrap_or(host);
    if trimmed.is_empty() || trimmed.ends_with('.') {
        return None;
    }
    Some(trimmed.to_ascii_lowercase())
}

/// Parse the target of a CONNECT request line — `CONNECT host:port HTTP/1.1`.
///
/// The port is mandatory in a CONNECT target (RFC 9110, section 9.3.6), so a missing
/// one is a malformed request and not a destination to guess a default for.
/// Guessing here would let a client reach port 443 by omitting it.
pub fn parse_connect_target(line: &str) -> Option<(String, u16)> {
    let line = line.trim_end_matches(['\r', '\n']);
    let mut parts = line.split(' ');
    if parts.next()? != "CONNECT" {
        return None;
    }
    let target = parts.next()?;
    let version = parts.next()?;
    if parts.next().is_some() || !version.starts_with("HTTP/") {
        return None;
    }
    let (host, port) = target.rsplit_once(':')?;
    if host.is_empty() || port.is_empty() || port.len() > 5 {
        return None;
    }
    if !port.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let parsed: u32 = port.parse().ok()?;
    if parsed == 0 || parsed > 65535 {
        return None;
    }
    Some((host.to_string(), parsed as u16))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn grant(entries: &[&str]) -> EgressGrant {
        let owned: Vec<String> = entries.iter().map(|s| s.to_string()).collect();
        EgressGrant::parse(Population::Produced, "grant-test-1", &owned).unwrap()
    }

    // ---- the RED direction first, exactly as design §3.6 step 4 orders it ----

    /// The proof this slice exists for (design §3.6 step 4, the RED direction
    /// first): a destination the grant did not name is refused, and the refusal
    /// names the grant. §3.6 is PARTIAL — steps 1 and 2 only; the jail, the
    /// live agent turn and the wiring are not in this slice.
    #[test]
    fn a_destination_the_grant_did_not_name_is_refused() {
        let g = grant(&["https://api.anthropic.com"]);
        let d = g.authorize("evil.example", 443);
        assert!(!d.allowed());
        assert_eq!(d.event_type(), "egress.denied");
        assert!(d.reason.contains("evil.example:443"), "reason: {}", d.reason);
        assert!(d.reason.contains("grant-test-1"), "reason: {}", d.reason);
        assert!(d.matched.is_none());
    }

    /// And the GREEN direction, so the refusal above is not a check that
    /// cannot pass.
    #[test]
    fn a_destination_the_grant_named_is_admitted() {
        let g = grant(&["https://api.anthropic.com"]);
        let d = g.authorize("api.anthropic.com", 443);
        assert!(d.allowed());
        assert_eq!(d.event_type(), "egress.allowed");
        assert_eq!(
            d.matched,
            Some(Destination { host: "api.anthropic.com".into(), port: 443 })
        );
        assert!(d.reason.contains("grant-test-1"), "reason: {}", d.reason);
    }

    /// An empty grant is the produced agent's state at this head. It admits
    /// nothing — deny by default, not permit by omission.
    #[test]
    fn an_empty_grant_admits_nothing() {
        let g = EgressGrant::empty(Population::Produced, "grant-empty");
        assert!(!g.authorize("api.anthropic.com", 443).allowed());
        assert!(!g.authorize("localhost", 80).allowed());
        assert!(g.destinations().is_empty());
    }

    /// The port is part of the destination, not decoration.
    #[test]
    fn a_named_host_on_an_unnamed_port_is_refused() {
        let g = grant(&["https://api.anthropic.com"]);
        assert!(!g.authorize("api.anthropic.com", 8443).allowed());
        assert!(g.authorize("api.anthropic.com", 443).allowed());
    }

    #[test]
    fn an_explicit_port_in_the_entry_is_the_port_enforced() {
        let g = grant(&["https://gitlab.example.com:8443"]);
        assert!(g.authorize("gitlab.example.com", 8443).allowed());
        assert!(!g.authorize("gitlab.example.com", 443).allowed());
    }

    // ---- what a grant may not say, refused rather than narrowed ----

    #[test]
    fn a_wildcard_is_refused() {
        assert_eq!(
            parse_entry("https://*.githubusercontent.com"),
            Err(GrantError::Wildcard("https://*.githubusercontent.com".into()))
        );
    }

    #[test]
    fn an_ip_literal_is_refused() {
        assert_eq!(
            parse_entry("https://169.254.169.254"),
            Err(GrantError::IpLiteral("https://169.254.169.254".into()))
        );
        assert_eq!(
            parse_entry("https://127.0.0.1:443"),
            Err(GrantError::IpLiteral("https://127.0.0.1:443".into()))
        );
        assert_eq!(
            parse_entry("https://[::1]:443"),
            Err(GrantError::IpLiteral("https://[::1]:443".into()))
        );
    }

    #[test]
    fn plaintext_http_is_refused() {
        assert_eq!(
            parse_entry("http://api.anthropic.com"),
            Err(GrantError::NotHttps("http://api.anthropic.com".into()))
        );
    }

    #[test]
    fn a_path_or_query_is_refused() {
        assert_eq!(
            parse_entry("https://api.anthropic.com/v1/messages"),
            Err(GrantError::StatesAPath("https://api.anthropic.com/v1/messages".into()))
        );
        assert_eq!(
            parse_entry("https://api.anthropic.com?x=1"),
            Err(GrantError::StatesAPath("https://api.anthropic.com?x=1".into()))
        );
    }

    #[test]
    fn an_uppercase_entry_is_refused_not_folded() {
        assert_eq!(
            parse_entry("https://API.Anthropic.com"),
            Err(GrantError::NotLowercase("https://API.Anthropic.com".into()))
        );
    }

    #[test]
    fn a_single_label_host_is_refused() {
        assert!(matches!(parse_entry("https://localhost"), Err(GrantError::MalformedHost(_))));
    }

    #[test]
    fn a_malformed_port_is_refused() {
        assert!(matches!(parse_entry("https://a.example:0"), Err(GrantError::MalformedPort(_))));
        assert!(matches!(parse_entry("https://a.example:70000"), Err(GrantError::MalformedPort(_))));
        assert!(matches!(parse_entry("https://a.example:https"), Err(GrantError::MalformedPort(_))));
    }

    #[test]
    fn more_than_the_ceiling_is_refused() {
        let entries: Vec<String> =
            (0..MAX_DESTINATIONS + 1).map(|i| format!("https://h{i}.example")).collect();
        assert_eq!(
            EgressGrant::parse(Population::Build, "g", &entries),
            Err(GrantError::TooMany(MAX_DESTINATIONS + 1))
        );
    }

    #[test]
    fn a_duplicate_destination_is_refused() {
        let entries = vec![
            "https://a.example".to_string(),
            "https://a.example:443".to_string(),
        ];
        assert!(matches!(
            EgressGrant::parse(Population::Build, "g", &entries),
            Err(GrantError::Duplicate(_))
        ));
    }

    /// One unenforceable entry refuses the whole grant. A half-parsed grant
    /// states an authority no reader can restate.
    #[test]
    fn one_bad_entry_refuses_the_whole_grant() {
        let entries = vec![
            "https://api.anthropic.com".to_string(),
            "https://*.evil.example".to_string(),
        ];
        assert!(matches!(
            EgressGrant::parse(Population::Produced, "g", &entries),
            Err(GrantError::Wildcard(_))
        ));
    }

    // ---- normalisation is DNS equality and nothing wider ----

    #[test]
    fn dns_equality_is_honoured_and_nothing_wider() {
        let g = grant(&["https://api.anthropic.com"]);
        assert!(g.authorize("API.ANTHROPIC.COM", 443).allowed());
        assert!(g.authorize("api.anthropic.com.", 443).allowed());
        // and nothing wider: a suffix, a prefix and a lookalike all fail
        assert!(!g.authorize("evil-api.anthropic.com", 443).allowed());
        assert!(!g.authorize("api.anthropic.com.evil.example", 443).allowed());
        assert!(!g.authorize("anthropic.com", 443).allowed());
        assert!(!g.authorize("api.anthropic.com..", 443).allowed());
    }

    #[test]
    fn an_incomparable_request_host_is_denied_with_a_reason() {
        let g = grant(&["https://api.anthropic.com"]);
        let d = g.authorize("", 443);
        assert!(!d.allowed());
        assert!(d.reason.contains("not a comparable hostname"), "reason: {}", d.reason);
    }

    // ---- the CONNECT request line ----

    #[test]
    fn a_connect_target_parses_to_a_host_and_a_port() {
        assert_eq!(
            parse_connect_target("CONNECT api.anthropic.com:443 HTTP/1.1\r\n"),
            Some(("api.anthropic.com".to_string(), 443))
        );
    }

    /// A CONNECT target without a port is malformed, not a request for 443.
    /// Defaulting here would hand a client port 443 by omitting it.
    #[test]
    fn a_connect_target_without_a_port_is_not_guessed() {
        assert_eq!(parse_connect_target("CONNECT api.anthropic.com HTTP/1.1"), None);
    }

    #[test]
    fn a_non_connect_line_is_refused() {
        assert_eq!(parse_connect_target("GET http://a.example/ HTTP/1.1"), None);
        assert_eq!(parse_connect_target("CONNECT a.example:443"), None);
        assert_eq!(parse_connect_target("CONNECT a.example:443 HTTP/1.1 extra"), None);
        assert_eq!(parse_connect_target(""), None);
    }

    // ---- the two populations stay distinguishable ----

    /// A decision carries the population, so a build-agent allowance can never
    /// be read as a produced agent's authority.
    #[test]
    fn a_decision_names_the_population_that_made_it() {
        let build = EgressGrant::parse(
            Population::Build,
            "build-egress",
            &["https://registry.npmjs.org".to_string()],
        )
        .unwrap();
        let d = build.authorize("registry.npmjs.org", 443);
        assert!(d.allowed());
        assert_eq!(d.population, Population::Build);
        assert!(d.reason.contains("build"), "reason: {}", d.reason);

        // the same host is NOT reachable from a produced agent's empty grant
        let produced = EgressGrant::empty(Population::Produced, "bundle-grant");
        let d2 = produced.authorize("registry.npmjs.org", 443);
        assert!(!d2.allowed());
        assert_eq!(d2.population, Population::Produced);
    }

    /// Every refusal string is distinct and stable: they reach a decision
    /// record, where a reader compares them.
    #[test]
    fn grant_error_reasons_are_distinct() {
        let all = [
            GrantError::NotHttps(String::new()).as_str(),
            GrantError::StatesAPath(String::new()).as_str(),
            GrantError::Wildcard(String::new()).as_str(),
            GrantError::IpLiteral(String::new()).as_str(),
            GrantError::NotLowercase(String::new()).as_str(),
            GrantError::MalformedHost(String::new()).as_str(),
            GrantError::MalformedPort(String::new()).as_str(),
            GrantError::TooMany(0).as_str(),
            GrantError::Duplicate(String::new()).as_str(),
        ];
        let mut seen: Vec<&str> = all.to_vec();
        seen.sort_unstable();
        seen.dedup();
        assert_eq!(seen.len(), all.len(), "refusal strings must be distinct");
    }

    /// What this module does NOT do is stated, not implied.
    #[test]
    fn the_boundary_of_this_slice_is_stated() {
        assert!(NOT_IMPLEMENTED.iter().any(|s| s.contains("CONNECT listener")));
        assert!(NOT_IMPLEMENTED.iter().any(|s| s.contains("resolve-once-and-pin")));
        assert!(NOT_IMPLEMENTED.iter().any(|s| s.contains("egress_jail.rs")));
    }
}
