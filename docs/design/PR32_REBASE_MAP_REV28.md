# docs/design/PR32_REBASE_MAP_REV28.md

**PR #32 → rev-28 rebase/adapt MAP · DEPENDENCY-SAFE ANALYSIS · NON-NORMATIVE**

> This is a preparation map only. It changes **no** code, **no** architecture, and **no** design
> text. It does **not** amend the rev-28 addendum (§0–§9 remain the sole normative source), does
> **not** touch the PR #31 audit candidate, and does **not** prejudge the Architect verdict. See §4.

---

## 0. What this is, and provenance

`current_state.json` records PR #32 (`impl/wave-3b1b-execution-binding`, base
`feat/wave-3b1-isolated-signer`, head `0e7ee1af0b96ca768cabe43c71d9caec30230430`, `draft: true`,
`is_rc: false`, `parent_pr: 31`) as **UNAPPROVED Draft/WIP 3b-1B code with NO authority over the
design**, that **"predates PR #31's rebase and still needs its own rebase,"** and that is **frozen
from architectural expansion until the design is Architect design-GREEN**. Its CI is 8/8 at
`0e7ee1a` — and CI-green is explicitly **NOT** design/audit-green (`stop_gates`).

The design gate is `CURRENT_DESIGN_GATE: PENDING_REAUDIT`, `CURRENT_DESIGN_CANDIDATE: rev-28`,
`CURRENT_LAST_REVIEWED: rev-27`, `CURRENT_LAST_VERDICT: RED` (2 P0 + 4 P1 at `0e41ef6`). rev-28
remediates the rev-27 RED but is **UNREVIEWED**; it does **not** inherit that verdict.

**Scope of this map (honest bound).** I did **not** read PR #32's branch diff — it is a separate
branch, not checked out, and reading/altering it is out of this dependency-safe task. This map is
therefore derived from the **design delta rev-27 → rev-28** (the two P0 remediations, addendum §0,
§2.1, §2.6, §2.7) applied to *"a WIP impl predating rev-28"* exactly as `current_state.json`
describes PR #32. Where the WIP embodies a rev-27-era assumption that rev-28 inverts, this map flags
it as a surface that *would be* invalidated — a prediction to confirm against the branch **after**
design-GREEN, not an assertion about specific lines.

The two rev-28 remediations that drive every invalidation below:
- **P0-1 — split the RENDERER from the trusted desktop VERIFIER/BROKER.** rev-27 wrongly folded the
  trusted Rust/Tauri backend (the final cryptographic verifier + persistence authority) into the
  "untrusted client." rev-28 defines **nine roles** and **seven runtime service UIDs**, with the
  broker a distinct TCB principal from the renderer.
- **P0-2 — make the launcher contract executable + privilege-safe (Model A).** rev-27 set
  `O_CLOEXEC` on the data FDs 3–6 (which would close the executor's only I/O at `fexecve`) and used
  an invalid privilege-drop order (`setresuid` before `setgroups`/`setresgid`) with an
  under-specified capability model. rev-28 locks FD-survival + the exact syscall sequence.

---

## 1. Part 1 — WIP surfaces INVALIDATED by rev-28

### 1.A The renderer / verifier-broker / challenge-authority split (P0-1, §0, §2.1, §2.6)

rev-28 topology (addendum §0): nine roles — **(1) Renderer/session UI** (interactive login identity,
fully untrusted, owns no key/DB/manifest/trust-state, reaches only the broker via a **closed
command** e.g. `{conversation_id, agent?}`); **(2) Trusted desktop verifier/BROKER** (dedicated
service UID/SID, **separate process** from the renderer, owns the receipt DB + pinned manifest +
orchestration + **final verification**, resolves `system`/`history`/`generation_config`/workspace/
install/run/task IDs itself, never accepts renderer-supplied hashes/prepared-objects/verdicts/
receipt-fields); **(3) `desktop-challenge-authority`** (separate dedicated UID/SID, owns the
challenge key + pending store, accepts create-pending/issue **only from the broker UID**). The
**seven runtime service UIDs** required pairwise-distinct and ≠ login are: verifier/broker (#2),
challenge-authority (#3), sidecar (#4), supervisor (#5), recorder (#6), executor (#8), signer (#9);
the renderer (#1) is the login role (a service UID it must **not** be); the launcher (#7) is a
root/TCB setuid file (**not** a service UID).

A WIP predating rev-28 would have the following surfaces **INVALIDATED**:

| # | rev-27-era WIP assumption (predicted) | rev-28 requirement that invalidates it |
|---|---|---|
| A1 | Trusted backend orchestration + **final verification** + receipt-DB/manifest ownership living **in-process with the webview**, or under the login/renderer identity | The broker is a **separate process under a dedicated service UID** (`brops-verifier`); `verify_distinct_principals()` **Blocks** if broker UID == login/renderer UID (§2.6, §9(i)) |
| A2 | Renderer/frontend passing `system`/`history`/`generation_config`/hashes/nonces/prepared objects/verdicts/receipt fields into the trust path | Renderer may send **only** the closed command `{conversation_id, agent?}`; the **broker resolves every authoritative input itself** from trusted backend state; any renderer-supplied authoritative input path is denied (§0 role 1–2, §9(j)) |
| A3 | A renderer-emitted / frontend-emitted "Verified" state, or rendering before the verification transaction commits | Only the **broker's committed verification transaction** creates a `Verified` message; the broker "permits rendering only after the verification transaction commits" (§0 role 2, §9(j)) |
| A4 | Challenge-authority create-pending/issue IPC allowlisting the **desktop-UI / login / renderer UID** as caller (rev-27 wording) | Authority accepts create-pending/issue **only from the trusted verifier/broker UID**; `SO_PEERCRED` allowlist targets the **broker** principal; renderer/login denied on both messages (§0 role 3, §2.1, §9(i)) |
| A5 | A `verify_distinct_principals()` that counts a **launcher runtime UID**, or fewer than seven service UIDs, or omits the login-distinct check | Exactly **seven** service UIDs pairwise-distinct **and** ≠ login (`login UID ∉ {the seven}`); the launcher is **not** in the set (root/TCB setuid, checked by `verify_tcb_integrity()`) (§2.6, §9(l)) |
| A6 | Provisioning that runs the broker under the login user, or shares broker/authority/sidecar UIDs | Installer MUST create seven dedicated service accounts, run the **renderer under login only**, never run the broker in-process with the renderer, and never land two principals on one UID (§2.6 provisioning + negatives) |

### 1.B The launcher FD-survival + privilege-drop contract (P0-2, §2.7, §4.7)

rev-28 Model A launcher (addendum §2.7): a **root/TCB-owned setuid helper** (mode `4750`, owner
root/TCB, group = recorder group), invoked **only** by the evidence-recorder runner (#6) by direct
`fork`+`execve` (no IPC/socket), that verifies caller/lease/hashes/FDs/target-UID/cgroup, drops
privilege by the exact locked sequence, and `fexecve`s the pinned executor image.

A WIP predating rev-28 would have the following surfaces **INVALIDATED**:

| # | rev-27-era WIP assumption (predicted) | rev-28 requirement that invalidates it |
|---|---|---|
| B1 | `O_CLOEXEC` / `FD_CLOEXEC` set on the data FDs **3/4/5/6** | Those four FDs MUST **survive both** exec boundaries; the launcher **explicitly CLEARS `FD_CLOEXEC`** (`fcntl(fd, F_SETFD, flags & ~FD_CLOEXEC)`) on each. rev-27's `O_CLOEXEC` "would have closed the executor's only I/O at exec" (§2.7 FD-survival) |
| B2 | Privilege drop ordered `setresuid` **before** `setgroups`/`setresgid` | Order is load-bearing: **`setgroups([])` → `setresgid(exec)` → drop bounding/ambient via `CAP_SETPCAP` → `setresuid(exec)`** — after the UID drop the process can no longer change groups/GID (§2.7 step 3–6) |
| B3 | Claim that the helper holds "only `{CAP_SETUID, CAP_SETGID}`" at entry | A setuid-root helper **starts fully privileged** (eff UID root, full cap set); it must *reduce to* those then to **zero**; removing the **bounding** set requires **`CAP_SETPCAP`** held at entry (§2.7 bootstrap-privilege correction) |
| B4 | Missing the final zero-capability verify, or `PR_SET_NO_NEW_PRIVS`, or the empty-`getgroups()` check | Step 8 **fail-closed verify**: `getresuid`/`getresgid` == (exec,exec,exec), `getgroups()` empty, **all five cap sets == 0**, else abort no-exec; then step 9 `prctl(PR_SET_NO_NEW_PRIVS, 1)` (§2.7 step 7–9) |
| B5 | Executor image opened by path / re-looked-up, or without `O_NOFOLLOW`, or counted among FDs 3–6 | Executor-image FD opened **`O_NOFOLLOW|O_RDONLY|O_CLOEXEC`**, `fstat` + **re-hash vs lease `executor_executable_sha256`**, then `fexecve` **that exact fd** (bytes hashed == bytes executed, no TOCTOU); it is **not** one of FDs 3–6 (§2.7 exec-time integrity, §4.7) |
| B6 | Leftover/inherited FDs not closed; variable argv; inherited env | **`close_range(7, ~0U, 0)`** for all others; **fixed closed argv** (lease handle + pinned executor index + cgroup path); **environment fully cleared** (no `LD_PRELOAD`/`PATH`/`BROPS_*`); any extra argv or non-empty env ⇒ refuse (§2.7 argv/env + FD rules) |
| B7 | Launcher exposed as an IPC/socket service, or invocable by sidecar/desktop/supervisor/signer/login | **Direct exec only**, no socket/request-parsing surface; invoker checked (`getresuid`) to be **exactly the recorder** (#6); any other caller ⇒ `tcb_integrity_violation` (§2.7 invoking-principal + IPC boundary) |
| B8 | Launcher provisioned as a persistent **runtime UID** among the distinct principals | Model A: launcher is a **root/TCB-owned setuid file, NOT a runtime UID**; it is verified by `verify_tcb_integrity()` and is **excluded** from `verify_distinct_principals()` (§2.6, §2.7) |

### 1.C Adjacent surfaces rev-28 also pins (confirm, likely partial in WIP)

- **Model identity** (§2 Principals): `model_profile_id` MUST be the **pure function**
  `"cfg-sha256:" + generation_config_sha256`, matching `^cfg-sha256:[0-9a-f]{64}$` — **not** a
  registry/lookup/mutable map. The **`GOVERNED_EXECUTION_ALLOWLIST`** is an **execution gate only**;
  it MUST NOT map a hash to an identity nor be consulted by identity derivation or historical
  verification (§7). A WIP using a lookup-based profile id is invalidated.
- **Platform capability gate** §0.1: real-mode enabled **iff** all five primitives verify (distinct
  principals, local-IPC peer auth, ownership/ACL isolation, privilege-dropping verified exec, TCB
  code integrity); otherwise **no lease, every turn Blocks, never `trusted_verified`** — no
  partial/degraded mode. **Windows** (§0.W) stays **false** until a separately-audited Windows
  broker exists; `windows_production_isolation: not_done` is a release blocker, not a TODO gap.
- **Challenge single-envelope chain** §2.1: the desktop mints + pre-stores the `request_nonce`; the
  authority **never** mints the nonce and **recomputes** `request_sha256` itself; create-pending (A)
  never carries `request_sha256` (that field ⇒ `malformed`); issue (B) signs from the authority's
  own stored row only. A WIP with an authority-minted nonce or a caller-supplied `request_sha256` is
  invalidated.
- **Time model** §1: every governed-turn field is integer epoch **milliseconds** ending in `_ms`;
  the reused `bro_evidence` `issued_at_epoch` stays legacy **seconds** and is never compared to any
  ms window. A WIP mixing units is invalidated by the §1 negative tests.

---

## 2. Part 2 — Exact adaptation steps once rev-28 is design-GREEN

Each step is gated on **design-GREEN at the exact `AUDIT_CANDIDATE_HEAD`** and **PR #31 merged**
(§3). Numbering mirrors Part 1.

**P0-1 topology (A1–A6):**
1. **Split the Tauri app into two processes.** Extract the trusted orchestration + final
   verification + receipt-DB/manifest ownership out of the webview into a **separate local broker
   service** running under a dedicated `brops-verifier` service UID/SID. The webview becomes the
   renderer only.
2. **Define the closed renderer→broker command.** Reduce the renderer's outward interface to
   `{conversation_id, agent?}` and remove every path by which the renderer supplies
   `system`/`history`/`generation_config`/hashes/nonces/prepared objects/verdicts/receipt fields.
3. **Move authoritative input resolution into the broker.** The broker resolves `system`/`history`/
   `generation_config`/workspace/install/run/task IDs from trusted backend state, builds the
   immutable `PreparedGovernedTurnV1B`, issues the challenge (via the authority), verifies the
   isolated-signer envelope + supervisor attestation, consumes the nonce, enforces receipt-id
   uniqueness + freshness, persists accepted output, and **gates rendering on the committed
   verification transaction**.
4. **Repoint the challenge-authority IPC allowlist to the broker UID.** `SO_PEERCRED` (Linux)
   allowlists the **broker** principal on both create-pending (A) and issue (B); the renderer/login
   and sidecar UIDs are denied.
5. **Provisioning.** Create the seven dedicated service accounts (`brops-verifier`,
   `brops-challenge`, `brops-sidecar`, `brops-supervisor`, `brops-recorder`, `brops-executor`,
   `brops-signer`), run the renderer under the interactive login identity, and install the launcher
   as a root/TCB-owned setuid `4750` binary.
6. **Implement `verify_distinct_principals()`** for the seven service UIDs (present, pairwise
   distinct, all ≠ login, `login ∉ {seven}`); check the launcher's root/TCB ownership via
   `verify_tcb_integrity()`, **not** by counting it as a principal.

**P0-2 launcher (B1–B8):**
7. **Clear `FD_CLOEXEC` on data FDs 3/4/5/6** (`fcntl F_SETFD & ~FD_CLOEXEC`); verify each input FD
   is `O_RDONLY`/`S_ISREG`/offset-0 store inode and FD 6 is the output pipe; `close_range(7, ~0U, 0)`
   for everything else.
8. **Open the executor image `O_NOFOLLOW|O_RDONLY|O_CLOEXEC`**, `fstat` owner/mode, **re-hash vs the
   lease `executor_executable_sha256`**, and `fexecve` that exact fd.
9. **Implement the exact 11-step drop sequence** (§2.7): entry verify (caller == recorder via
   `getresuid`, immutable argv, empty env, exact FD set, lease/hashes/cgroup/target UID-GID) →
   root-required cgroup/pgroup/rlimit setup → `setgroups([])` → `setresgid(exec)` → drop bounding +
   ambient via `CAP_SETPCAP` → `setresuid(exec)` → `capset` eff/perm/inh = 0 → **verify all five cap
   sets == 0, uid/gid == exec, groups empty** → `PR_SET_NO_NEW_PRIVS` → normalize signals/umask/rlimits
   → `fexecve` with **only FDs 3–6** open.
10. **Enforce the direct-exec boundary** (fork + execve, no socket); refuse any non-recorder caller,
    extra/unknown argv, or non-empty env.
11. **Install the launcher as root/TCB setuid `4750`** and exclude it from the distinct-principal set;
    cover it only in `verify_tcb_integrity()`.

**Adjacent (1.C):**
12. Make `model_profile_id` the deterministic `"cfg-sha256:" + generation_config_sha256`; keep the
    `GOVERNED_EXECUTION_ALLOWLIST` an execution gate only (never an identity source, never consulted
    by §7).
13. Wire the §0.1 five-primitive gate fail-closed; keep Windows `false` until the §0.W broker is
    separately audited.
14. Ensure the §2.1 single-envelope nonce chain (desktop-minted nonce, authority-recomputed
    `request_sha256`, no caller `request_sha256`) and the §1 ms/seconds discipline hold.
15. Add the **§9 acceptance matrices**: the real-executable recorder→launcher→`fexecve` integration
    test (FD survival + privilege drop proven), the launcher negative matrix (§2.7), the
    principal-topology + launcher-model matrix (§9 (i)–(n)), and the renderer-isolation proofs.

---

## 3. Part 3 — Ordered rebase / adapt checklist

Do **not** begin any step below until the one before it is satisfied. Steps 0–2 are hard gates.

- [ ] **0. DESIGN GATE.** `CURRENT_DESIGN_GATE` flips `PENDING_REAUDIT → GREEN` at the exact
  `AUDIT_CANDIDATE_HEAD` marker on PR #31 (Architect design audit passes). Until then PR #32 stays
  **Draft, frozen from architectural expansion**; touch nothing. (rev-28 does not inherit the rev-27
  RED — see §4.)
- [ ] **1. CARRIER MERGE.** PR #31 merges only after design-GREEN + implementation + code-audit
  GREEN + CI GREEN. On the main push, `carrier_transition` post-merge gate
  `VERIFY_MAIN_REBASE_PR32` applies (`check_repo_state.py` fails closed if canonical state still
  describes PR #31 as open/pending).
- [ ] **2. MAIN VERIFY + RESYNC.** Verify the actual main commit + main-push CI GREEN; re-sync
  `config/current_state.json` (`next_action_by_carrier.merged`): remove `current_workflow_pr` #31,
  set the new active state, so main is never self-stale.
- [ ] **3. REBASE.** Rebase `impl/wave-3b1b-execution-binding` onto the approved implementation
  sequence / new base (PR #32 `base` `feat/wave-3b1-isolated-signer` is now merged); resolve
  conflicts; keep PR #32 **Draft**, `is_rc: false`.
- [ ] **4. APPLY P0-1** topology adaptation — §2 steps 1–6 (broker extraction first; it is the
  root change every downstream trust check depends on).
- [ ] **5. APPLY P0-2** launcher adaptation — §2 steps 7–11.
- [ ] **6. APPLY ADJACENT** pins — §2 steps 12–14 (identity function + allowlist gate; §0.1 platform
  gate; §2.1 nonce chain; §1 ms discipline).
- [ ] **7. TESTS** — §2 step 15: the real-executable integration test + all §9 negative matrices +
  the isolation proofs; run engine + isolation exact-head CI (restore/extend the 8/8 to the rev-28
  matrix). **CI-green ≠ design/audit-green.**
- [ ] **8. CODE AUDIT.** Submit for the Architect **code** audit at the exact head; PR #32 stays
  frozen from architectural expansion; no push capability (only the Git & Release Control Pack can
  prepare a push).
- [ ] **9. STOP-GATES HOLD** throughout: `NoTrustedManifest` fail-closed; **no** production
  `trusted_verified`; Windows real-mode stays `false` until the §0.W broker is separately audited (a
  Linux isolation proof is not a Windows production proof).

---

## 4. Part 4 — Explicit non-prejudgment / dependency-safety note

- **Nothing here changes the disputed architecture.** The rev-28 addendum §0–§9 remains the **sole**
  normative source. This document adds, removes, and edits **no** normative text and proposes **no**
  code or architecture change. It is a preparation map to be executed **only after** the design is
  Architect design-GREEN.
- **Nothing here prejudges the verdict.** rev-28 is `PENDING_REAUDIT` and **UNREVIEWED**; it does
  **not** inherit the rev-27 RED (that verdict is recorded on `last_reviewed_candidate` rev-27 at
  `0e41ef6`). This map does **not** assert rev-28 will pass, and does **not** substitute for the
  Architect design audit. If rev-28 is revised or REDed again, **this map is superseded** and must
  be re-derived from the then-current normative text.
- **The PR #31 audit candidate is untouched.** This analysis reads `current_state.json` and the
  queued rev-28 addendum as read-only context; it does not alter the AUDIT_CANDIDATE_HEAD anchor,
  the carrier, or PR #31's contents.
- **PR #32 stays Draft/WIP/frozen and authority-less.** It holds UNAPPROVED code with **no authority
  over the design**; this map does not merge, push, execute, un-draft, or expand it, and confers it
  no approval. All actions in §3 are contingent and gated.
- **Review-mode discipline.** No filesystem mutation, commit, push, branch, PR write, or environment
  change was performed. This document is returned as analysis output only; it was **not** written
  into the read-only OS repository.

---

## Appendix — Verification receipt (performed for this analysis; honest results)

Ran against `C:\Users\Admin\Desktop\OS` (read-only; no mutations):

- `config/current_state.json` — **valid JSON** (`json.load` OK).
- `.github/workflows/ci.yml` — **valid YAML** (`yaml.safe_load` OK); **9 jobs**
  (`cockpit-frontend, cockpit-core, cockpit-host, engine, bridge, coordination, repo-state,
  capabilities, signer-isolation`); **18/18** `uses:` steps pinned by **full 40-hex commit SHA**;
  **0** unpinned actions. Confirms the stated "actions pinned by full commit SHA" invariant.
- Stdlib-only python gates referenced by CI (`tools/check_coordination.py`,
  `tools/check_repo_state.py`, `tools/check_capabilities.py`); compiled
  `tools/check_repo_state.py` and `tools/check_coordination.py` with `py_compile` — **both compile
  clean**.
- Addendum sections read for this map: §0 scope/topology (nine roles, seven service UIDs), §0.1
  platform gate, §0.W Windows stance, §1 time model, §2 principals/identity, §2.1 challenge
  authority, §2.6 distinct-principal linchpin, §2.7 launcher Model A, §3 artifact matrix, §9
  acceptance criteria; plus §4.3/§4.7/§7 by reference.
- **Not verified (out of dependency-safe scope):** PR #32's branch diff was **not** read (separate
  branch, not checked out). Part 1 invalidations are predictions from the rev-27→rev-28 design
  delta, to be confirmed against the branch **after** design-GREEN — not line-level assertions.