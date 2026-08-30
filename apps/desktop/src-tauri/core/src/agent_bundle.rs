//! The produced agent bundle: what exists at 17:00 that did not exist at 09:00.
//!
//! Design: `docs/design/PRODUCTION_HALF_DESIGN.md` §1–§3. This module implements
//! the first slice `tools/check_produced_artifact.py` measures, and deliberately
//! implements *less* than the design describes. What is here is real; what is not
//! here is named in [`NOT_IMPLEMENTED`] rather than implied.
//!
//! Three properties are load-bearing and each is a refusal, never a fallback:
//!
//! * **The directory is named by its own digest.** The loader computes
//!   `sha256(manifest.json)` and refuses unless it equals the directory name, so a
//!   half-written bundle can never be mistaken for a whole one.
//! * **The file table is total.** Every regular file under the bundle except
//!   `manifest.json` appears exactly once and re-hashes to its declared `sha256`.
//!   A file on disk with no entry is a refusal and an entry with no file is a
//!   refusal — a partial file table is how an unreviewed prompt rides into an
//!   approved bundle.
//! * **An absent grant is a refusal, never "unrestricted".** `Refusal::GrantAbsent`
//!   exists precisely so the two cannot be confused at a call site.
//!
//! The grant is written **by this module**, from values the runtime holds — never
//! from a prompt. `Grant::written_by` records which component wrote it, and
//! [`Grant::is_prose_writer`] refuses a writer that names a Markdown or prompt
//! file, because a grant stated in a prompt is a grant stated in prose. That is
//! the defect `docs/ARCHITECTURE.md` already records for `scope`.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::governed_message_store::sha256_hex;

/// Stated, not implied. Every one of these is in the design and NOT in this slice.
pub const NOT_IMPLEMENTED: &[&str] = &[
    "model steps: a governed turn is refused at this head (governed_verification_unconfigured)",
    "call steps: NOT IMPLEMENTED — §3.3 designs the egress enforcement point and no code in \
     this tree enforces a destination against a grant, so a `call` step is refused",
    "credential bindings: §4's (bundle_digest, slot_id) binding store",
    "approval: the native confirmation writes no approvals.confirmation_digest for a bundle",
    "eval/cases.jsonl: the cases a build was accepted against",
];

/// A step kind. Closed set: a fifth kind is a schema change and therefore a review.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum StepKind {
    /// A governed turn. Refused at this head; present so the vocabulary is whole.
    Model,
    /// An egress named in the grant. Refused at this head — no enforcement point.
    Call,
    /// A local write, the vocabulary `execute_action` already implements.
    Store,
    /// No effect; only `next`.
    Branch,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Requires {
    #[serde(default)]
    pub capabilities: Vec<String>,
    #[serde(default)]
    pub credential_slots: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Step {
    pub id: String,
    pub kind: StepKind,
    /// For `store`: the verb `execute_action` understands.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub verb: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub argument: Option<String>,
    pub requires: Requires,
    /// `null` means "end of flow". Edges must form a DAG over step ids.
    #[serde(default)]
    pub next: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Flow {
    pub schema: u32,
    pub artifact_type: String,
    pub flow_id: String,
    pub entry: String,
    pub max_steps: u32,
    pub max_wall_ms: u64,
    pub steps: Vec<Step>,
}

/// The permission grant. `capabilities` is the axis this slice enforces;
/// `egress` is expressible and empty here, because nothing in this slice may
/// leave the box and a grant must not state an authority nothing can deliver.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Grant {
    pub schema: u32,
    pub artifact_type: String,
    pub capabilities: Vec<String>,
    /// `https://` + exact lowercase FQDN + optional port. No wildcards, no IP
    /// literals, no paths — see design §3.2 for why each is unexpressible.
    pub egress: Vec<String>,
    pub credential_slots: Vec<String>,
    /// Which runtime component wrote this grant. Not decorative: the gate and
    /// [`Grant::is_prose_writer`] both refuse a writer that names prose.
    pub written_by: String,
    pub expires_at_epoch: i64,
}

/// The runtime component that writes a grant. A literal, so it cannot be a path
/// a caller supplies and cannot become a prompt file by configuration.
pub const GRANT_WRITER: &str = "brops_core::agent_bundle::write_grant";

impl Grant {
    /// A writer naming a Markdown or prompt file means the grant came from prose.
    pub fn is_prose_writer(writer: &str) -> bool {
        let w = writer.to_ascii_lowercase();
        w.ends_with(".md") || w.ends_with(".txt") || w.contains("prompt")
    }

    /// Written by the runtime from values it holds. There is no parameter here
    /// that a prompt could reach.
    pub fn for_local_only(expires_at_epoch: i64) -> Self {
        Grant {
            schema: 1,
            artifact_type: "brops.agent-grant.v1".into(),
            capabilities: vec!["READ_LOCAL".into(), "WRITE_LOCAL".into()],
            egress: Vec::new(),
            credential_slots: Vec::new(),
            written_by: GRANT_WRITER.into(),
            expires_at_epoch,
        }
    }

    /// Every capability a flow's steps require must be inside the grant. Checked
    /// at LOAD time, not only at build time: a build-time-only check is a check
    /// the builder can skip.
    pub fn covers(&self, flow: &Flow) -> Result<(), Refusal> {
        for step in &flow.steps {
            for cap in &step.requires.capabilities {
                if !self.capabilities.iter().any(|c| c == cap) {
                    return Err(Refusal::CapabilitiesExceedGrant);
                }
            }
            if !step.requires.credential_slots.is_empty() {
                for slot in &step.requires.credential_slots {
                    if !self.credential_slots.iter().any(|s| s == slot) {
                        return Err(Refusal::CredentialSlotUnbound);
                    }
                }
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct FileEntry {
    pub path: String,
    pub sha256: String,
    pub bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Manifest {
    pub schema: u32,
    pub artifact_type: String,
    pub bundle_id: String,
    pub bundle_version: u64,
    pub display_name: String,
    pub built_for: String,
    pub built_at_epoch: i64,
    pub flow_ref: String,
    pub grant_ref: String,
    /// Total over the bundle: every regular file except `manifest.json`, once.
    pub files: Vec<FileEntry>,
}

/// Typed, closed set. Never free text: a reason a reader has to interpret is a
/// reason a reader will interpret differently next time.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Refusal {
    BundleDigestMismatch,
    FileTableIncomplete,
    FileHashMismatch,
    GrantAbsent,
    /// Present, non-empty, and not decodable. NOT the same fact as absent:
    /// mapping both onto `GrantAbsent` made a malformed grant read as a missing
    /// one, and "someone wrote a broken grant" and "nobody wrote one" call for
    /// different answers.
    GrantUnparseable,
    GrantExpired,
    GrantFromProse,
    CapabilitiesExceedGrant,
    CredentialSlotUnbound,
    FlowUnparseable,
    StepKindNotExecutable,
    Unreadable,
}

impl Refusal {
    /// The stable string that reaches `flow_runs.refusal_reason`.
    pub fn as_str(self) -> &'static str {
        match self {
            Refusal::BundleDigestMismatch => "bundle_digest_mismatch",
            Refusal::FileTableIncomplete => "file_table_incomplete",
            Refusal::FileHashMismatch => "file_hash_mismatch",
            Refusal::GrantAbsent => "grant_absent",
            Refusal::GrantUnparseable => "grant_unparseable",
            Refusal::GrantExpired => "grant_expired",
            Refusal::GrantFromProse => "grant_from_prose",
            Refusal::CapabilitiesExceedGrant => "capabilities_exceed_grant",
            Refusal::CredentialSlotUnbound => "credential_slot_unbound",
            Refusal::FlowUnparseable => "flow_unparseable",
            Refusal::StepKindNotExecutable => "step_kind_not_executable",
            Refusal::Unreadable => "unreadable",
        }
    }
}

/// A verified bundle. Constructing one is the only way to get its flow and grant,
/// so no call site can hold a flow that was never checked against its digest.
#[derive(Debug, Clone, PartialEq)]
pub struct VerifiedBundle {
    pub digest: String,
    pub dir: PathBuf,
    pub manifest: Manifest,
    pub flow: Flow,
    pub grant: Grant,
}

fn read(path: &Path) -> Result<Vec<u8>, Refusal> {
    std::fs::read(path).map_err(|_| Refusal::Unreadable)
}

/// Every regular file under `dir` except `manifest.json`, as bundle-relative
/// slash-separated paths.
fn walk(dir: &Path) -> Result<Vec<String>, Refusal> {
    fn go(root: &Path, at: &Path, out: &mut Vec<String>) -> Result<(), Refusal> {
        for entry in std::fs::read_dir(at).map_err(|_| Refusal::Unreadable)? {
            let entry = entry.map_err(|_| Refusal::Unreadable)?;
            let p = entry.path();
            if p.is_dir() {
                go(root, &p, out)?;
            } else {
                let rel = p.strip_prefix(root).map_err(|_| Refusal::Unreadable)?;
                let rel = rel.to_string_lossy().replace('\\', "/");
                if rel != "manifest.json" {
                    out.push(rel);
                }
            }
        }
        Ok(())
    }
    let mut out = Vec::new();
    go(dir, dir, &mut out)?;
    out.sort();
    Ok(out)
}

/// Load and verify. Every failure is a typed [`Refusal`]; there is no path here
/// that degrades to a weaker check.
pub fn verify(dir: &Path, now_epoch: i64) -> Result<VerifiedBundle, Refusal> {
    let manifest_bytes = read(&dir.join("manifest.json"))?;
    let digest = sha256_hex(&manifest_bytes);

    // The directory is named by its own digest. A bundle whose name and bytes
    // disagree is refused before anything inside it is parsed.
    let named = dir
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_default();
    if named != digest {
        return Err(Refusal::BundleDigestMismatch);
    }

    let manifest: Manifest =
        serde_json::from_slice(&manifest_bytes).map_err(|_| Refusal::FlowUnparseable)?;

    // The file table is TOTAL, checked both ways.
    let on_disk = walk(dir)?;
    let declared: BTreeMap<&str, &FileEntry> =
        manifest.files.iter().map(|f| (f.path.as_str(), f)).collect();
    if declared.len() != manifest.files.len() || on_disk.len() != declared.len() {
        return Err(Refusal::FileTableIncomplete);
    }
    for rel in &on_disk {
        let entry = declared.get(rel.as_str()).ok_or(Refusal::FileTableIncomplete)?;
        let bytes = read(&dir.join(rel))?;
        if sha256_hex(&bytes) != entry.sha256 || bytes.len() as u64 != entry.bytes {
            return Err(Refusal::FileHashMismatch);
        }
    }

    // An absent grant is a refusal, not "no restrictions".
    let grant_path = dir.join(&manifest.grant_ref);
    if !grant_path.is_file() {
        return Err(Refusal::GrantAbsent);
    }
    let grant_bytes = read(&grant_path)?;
    // The ONLY route to `GrantAbsent` for a file that exists. Everything below
    // reports `GrantUnparseable` instead, so a reader can tell "nobody wrote a
    // grant" from "someone wrote a broken one". Deleting this line makes the
    // whitespace-only case report `GrantUnparseable`, which is what the
    // mutation sweep now checks.
    if grant_bytes.iter().all(|b| b.is_ascii_whitespace()) {
        return Err(Refusal::GrantAbsent);
    }
    let grant: Grant =
        serde_json::from_slice(&grant_bytes).map_err(|_| Refusal::GrantUnparseable)?;
    if Grant::is_prose_writer(&grant.written_by) {
        return Err(Refusal::GrantFromProse);
    }
    if now_epoch > grant.expires_at_epoch {
        return Err(Refusal::GrantExpired);
    }

    let flow: Flow = serde_json::from_slice(&read(&dir.join(&manifest.flow_ref))?)
        .map_err(|_| Refusal::FlowUnparseable)?;
    if flow.steps.len() < 2 || flow.steps.len() as u32 > flow.max_steps {
        return Err(Refusal::FlowUnparseable);
    }
    grant.covers(&flow)?;

    Ok(VerifiedBundle { digest, dir: dir.to_path_buf(), manifest, flow, grant })
}

/// What a build asks for. The caller supplies the agent's identity and its work;
/// it does NOT supply the grant, which this module writes.
pub struct BuildSpec {
    pub bundle_id: String,
    pub bundle_version: u64,
    pub display_name: String,
    pub built_for: String,
    pub built_at_epoch: i64,
    pub grant_expires_at_epoch: i64,
    pub steps: Vec<Step>,
}

/// Write a bundle under `store_root`, returning its digest. The directory is
/// named by the digest, so the same spec always lands in the same place and two
/// versions of one agent cannot collide.
pub fn build(store_root: &Path, spec: &BuildSpec) -> Result<String, Refusal> {
    let flow = Flow {
        schema: 1,
        artifact_type: "brops.agent-flow.v1".into(),
        flow_id: format!("flow-{}-{}", spec.bundle_id, spec.bundle_version),
        entry: spec.steps.first().map(|s| s.id.clone()).ok_or(Refusal::FlowUnparseable)?,
        max_steps: 8,
        max_wall_ms: 120_000,
        steps: spec.steps.clone(),
    };
    let grant = Grant::for_local_only(spec.grant_expires_at_epoch);

    let flow_bytes = serde_json::to_vec_pretty(&flow).map_err(|_| Refusal::FlowUnparseable)?;
    let grant_bytes = serde_json::to_vec_pretty(&grant).map_err(|_| Refusal::GrantUnparseable)?;

    let files = vec![
        FileEntry { path: "flow.json".into(), sha256: sha256_hex(&flow_bytes), bytes: flow_bytes.len() as u64 },
        FileEntry { path: "grant.json".into(), sha256: sha256_hex(&grant_bytes), bytes: grant_bytes.len() as u64 },
    ];
    let manifest = Manifest {
        schema: 1,
        artifact_type: "brops.agent-bundle.v1".into(),
        bundle_id: spec.bundle_id.clone(),
        bundle_version: spec.bundle_version,
        display_name: spec.display_name.clone(),
        built_for: spec.built_for.clone(),
        built_at_epoch: spec.built_at_epoch,
        flow_ref: "flow.json".into(),
        grant_ref: "grant.json".into(),
        files,
    };
    // The digest is over the manifest bytes exactly as they land on disk, so a
    // reader can recompute it with `sha256sum manifest.json` and get the
    // directory name. A digest that depends on how it was serialised is not one.
    let manifest_bytes =
        serde_json::to_vec_pretty(&manifest).map_err(|_| Refusal::FlowUnparseable)?;
    let digest = sha256_hex(&manifest_bytes);

    let dir = store_root.join(&digest);
    std::fs::create_dir_all(&dir).map_err(|_| Refusal::Unreadable)?;
    std::fs::write(dir.join("flow.json"), &flow_bytes).map_err(|_| Refusal::Unreadable)?;
    std::fs::write(dir.join("grant.json"), &grant_bytes).map_err(|_| Refusal::Unreadable)?;
    std::fs::write(dir.join("manifest.json"), &manifest_bytes).map_err(|_| Refusal::Unreadable)?;
    Ok(digest)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spec(now: i64) -> BuildSpec {
        BuildSpec {
            bundle_id: "agt-test".into(),
            bundle_version: 1,
            display_name: "Test agent".into(),
            built_for: "customer-test".into(),
            built_at_epoch: now,
            grant_expires_at_epoch: now + 3600,
            steps: vec![
                Step { id: "a".into(), kind: StepKind::Store, verb: Some("knowledge_note".into()),
                       argument: Some("one".into()),
                       requires: Requires { capabilities: vec!["WRITE_LOCAL".into()], credential_slots: vec![] },
                       next: Some("b".into()) },
                Step { id: "b".into(), kind: StepKind::Branch, verb: None, argument: None,
                       requires: Requires { capabilities: vec![], credential_slots: vec![] },
                       next: None },
            ],
        }
    }

    fn built(now: i64) -> (tempfile::TempDir, String) {
        let dir = tempfile::tempdir().unwrap();
        let digest = build(dir.path(), &spec(now)).unwrap();
        (dir, digest)
    }

    /// §1.9 step 1. A digest that depends on the machine is not a digest: the
    /// directory name must be reproducible from the bytes with `sha256sum`.
    #[test]
    fn the_directory_name_is_the_digest_of_its_own_manifest() {
        let (dir, digest) = built(1_000_000);
        let bytes = std::fs::read(dir.path().join(&digest).join("manifest.json")).unwrap();
        assert_eq!(sha256_hex(&bytes), digest);
        assert!(verify(&dir.path().join(&digest), 1_000_000).is_ok());
    }

    /// §1.9 step 2. Flip one byte in a bundle file and the loader refuses by
    /// name -- and does NOT fall back to loading it.
    #[test]
    fn one_flipped_byte_in_a_file_is_refused_by_hash_not_loaded() {
        let (dir, digest) = built(1_000_000);
        let flow = dir.path().join(&digest).join("flow.json");
        let mut bytes = std::fs::read(&flow).unwrap();
        let i = bytes.iter().position(|b| *b == b'a').unwrap();
        bytes[i] = b'z';
        std::fs::write(&flow, &bytes).unwrap();
        assert_eq!(verify(&dir.path().join(&digest), 1_000_000), Err(Refusal::FileHashMismatch));
    }

    /// A file added to the bundle with no entry in the file table is refused:
    /// a partial file table is how an unreviewed prompt rides in.
    #[test]
    fn a_file_the_table_does_not_declare_is_refused() {
        let (dir, digest) = built(1_000_000);
        std::fs::write(dir.path().join(&digest).join("prompts.md"), b"unreviewed").unwrap();
        assert_eq!(verify(&dir.path().join(&digest), 1_000_000), Err(Refusal::FileTableIncomplete));
    }

    /// Replace `grant.json`, re-point the file table at the new bytes and rename
    /// the directory to the new manifest digest -- so a test about the GRANT
    /// rule is not silently answered by the hash rule or the name rule.
    fn rewrite_grant(root: &std::path::Path, digest: &str, body: &[u8]) -> Result<VerifiedBundle, Refusal> {
        let bundle = root.join(digest);
        std::fs::write(bundle.join("grant.json"), body).unwrap();
        let mut m: Manifest =
            serde_json::from_slice(&std::fs::read(bundle.join("manifest.json")).unwrap()).unwrap();
        for f in m.files.iter_mut() {
            if f.path == "grant.json" {
                f.sha256 = sha256_hex(body);
                f.bytes = body.len() as u64;
            }
        }
        let bytes = serde_json::to_vec_pretty(&m).unwrap();
        let renamed = root.join(sha256_hex(&bytes));
        std::fs::rename(&bundle, &renamed).unwrap();
        std::fs::write(renamed.join("manifest.json"), &bytes).unwrap();
        verify(&renamed, 1_000_000)
    }

    /// §1.9 step 3. The refusal is ABSENT GRANT, specifically -- never
    /// "no restrictions". The two must not be confusable at a call site.
    #[test]
    fn a_deleted_grant_is_absent_not_unrestricted() {
        let (dir, digest) = built(1_000_000);
        let bundle = dir.path().join(&digest);
        std::fs::write(bundle.join("grant.json"), b"").unwrap();
        // Emptying it changes its hash, so re-point the file table at the empty
        // bytes: this test is about the grant rule, not the hash rule.
        let mut m: Manifest =
            serde_json::from_slice(&std::fs::read(bundle.join("manifest.json")).unwrap()).unwrap();
        for f in m.files.iter_mut() {
            if f.path == "grant.json" {
                f.sha256 = sha256_hex(b"");
                f.bytes = 0;
            }
        }
        let bytes = serde_json::to_vec_pretty(&m).unwrap();
        let renamed = dir.path().join(sha256_hex(&bytes));
        std::fs::rename(&bundle, &renamed).unwrap();
        std::fs::write(renamed.join("manifest.json"), &bytes).unwrap();
        assert_eq!(verify(&renamed, 1_000_000), Err(Refusal::GrantAbsent));
    }

    /// A grant file of nothing but whitespace is ABSENT, not merely unparseable.
    ///
    /// This test exists because the sweep found the whitespace check tested by
    /// nothing: deleting it left every test green, since `serde_json` refuses
    /// EMPTY bytes on its own and the refusal arrived by a different route. A
    /// grant of "   \n" parses no better, but it is the case a reader would
    /// call "the file is there", and the distinction between absent and
    /// unrestricted is the whole reason `GrantAbsent` exists.
    #[test]
    fn a_whitespace_only_grant_is_absent_too() {
        let (dir, digest) = built(1_000_000);
        let bundle = dir.path().join(&digest);
        let blank: &[u8] = b"   \n\t\n";
        std::fs::write(bundle.join("grant.json"), blank).unwrap();
        let mut m: Manifest =
            serde_json::from_slice(&std::fs::read(bundle.join("manifest.json")).unwrap()).unwrap();
        for f in m.files.iter_mut() {
            if f.path == "grant.json" {
                f.sha256 = sha256_hex(blank);
                f.bytes = blank.len() as u64;
            }
        }
        let bytes = serde_json::to_vec_pretty(&m).unwrap();
        let renamed = dir.path().join(sha256_hex(&bytes));
        std::fs::rename(&bundle, &renamed).unwrap();
        std::fs::write(renamed.join("manifest.json"), &bytes).unwrap();
        assert_eq!(verify(&renamed, 1_000_000), Err(Refusal::GrantAbsent));
    }

    /// A grant that is present but MALFORMED is unparseable, not absent.
    /// Both used to report `GrantAbsent`, which told a reader nobody had written
    /// a grant when somebody had written a broken one.
    #[test]
    fn a_malformed_grant_is_unparseable_not_absent() {
        let (dir, digest) = built(1_000_000);
        assert_eq!(rewrite_grant(dir.path(), &digest, b"{ not json"), Err(Refusal::GrantUnparseable));
    }

    /// A renamed directory is refused before anything inside it is parsed.
    #[test]
    fn a_bundle_whose_name_and_bytes_disagree_is_refused() {
        let (dir, digest) = built(1_000_000);
        let moved = dir.path().join("0".repeat(64));
        std::fs::rename(dir.path().join(&digest), &moved).unwrap();
        assert_eq!(verify(&moved, 1_000_000), Err(Refusal::BundleDigestMismatch));
    }

    /// The grant expires, and an expired grant is refused rather than ignored.
    #[test]
    fn an_expired_grant_is_refused() {
        let (dir, digest) = built(1_000_000);
        assert_eq!(verify(&dir.path().join(&digest), 1_000_000 + 3601), Err(Refusal::GrantExpired));
    }

    /// A grant whose writer names prose is refused: a grant stated in a prompt
    /// is a grant stated in prose, which is the defect ARCHITECTURE.md records.
    #[test]
    fn a_grant_written_by_a_prompt_file_is_refused() {
        for writer in ["prompts/grant.md", "GRANT.md", "system_prompt.txt", "the-prompt"] {
            assert!(Grant::is_prose_writer(writer), "{writer} should be refused");
        }
        assert!(!Grant::is_prose_writer(GRANT_WRITER));
    }

    /// Load-time capability check: a step requiring more than the grant carries
    /// is refused even though the build wrote both.
    #[test]
    fn a_step_requiring_more_than_the_grant_is_refused_at_load() {
        let mut s = spec(1_000_000);
        s.steps[0].requires.capabilities.push("USE_NETWORK".into());
        let dir = tempfile::tempdir().unwrap();
        let digest = build(dir.path(), &s).unwrap();
        assert_eq!(
            verify(&dir.path().join(&digest), 1_000_000),
            Err(Refusal::CapabilitiesExceedGrant)
        );
    }

    /// The grant this runtime writes carries no egress and no credential slot.
    /// Nothing in this slice may leave the box, and a grant must not state an
    /// authority nothing can deliver.
    #[test]
    fn the_runtime_grant_states_no_authority_it_cannot_deliver() {
        let g = Grant::for_local_only(0);
        assert!(g.egress.is_empty());
        assert!(g.credential_slots.is_empty());
        assert_eq!(g.written_by, GRANT_WRITER);
    }

    /// A flow with fewer than two steps is not a flow. Stated as a test so the
    /// gate's condition 2 has a counterpart the code enforces.
    #[test]
    fn a_single_step_flow_is_unparseable() {
        let mut s = spec(1_000_000);
        s.steps.truncate(1);
        s.steps[0].next = None;
        let dir = tempfile::tempdir().unwrap();
        let digest = build(dir.path(), &s).unwrap();
        assert_eq!(verify(&dir.path().join(&digest), 1_000_000), Err(Refusal::FlowUnparseable));
    }

    /// Every refusal string is distinct and stable: they reach
    /// `flow_runs.refusal_reason`, where a reader compares them.
    #[test]
    fn refusal_reasons_are_distinct() {
        let all = [
            Refusal::BundleDigestMismatch, Refusal::FileTableIncomplete, Refusal::FileHashMismatch,
            Refusal::GrantAbsent, Refusal::GrantUnparseable, Refusal::GrantExpired,
            Refusal::GrantFromProse,
            Refusal::CapabilitiesExceedGrant, Refusal::CredentialSlotUnbound,
            Refusal::FlowUnparseable, Refusal::StepKindNotExecutable, Refusal::Unreadable,
        ];
        let mut seen = std::collections::BTreeSet::new();
        for r in all {
            assert!(seen.insert(r.as_str()), "duplicate reason {}", r.as_str());
        }
        assert_eq!(seen.len(), all.len());
    }
}
