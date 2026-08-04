# Windows Broker Trust-Chain — Builder-Side Adversarial Audit (2026-08-04)

**Status: NOT GREEN. Central guarantee HOLDS. Two P0 found; both addressed. Shipped gate stays CLOSED.**

## What this is (and is not)

This is a **builder-side** adversarial audit performed at the Owner's direction, using five independent
fresh-context reviewers, each tasked to **break** one dimension of the production trust chain (not confirm it).
It is **not** the independent external Architect CODE-audit — the Owner designated the builder as auditor for
this pass. The independent audit remains the gold standard and a prerequisite (with Owner approval) before the
shipped Windows gate can ever flip. `CURRENT_CODE_AUDIT: ARCHITECT_PENDING` is unchanged.

## Scope

`core/src/{windows_broker,key_manifest,production_trust,governed_verification}.rs`,
`win-live/src/{tcb,resolver,pipe,execution,proof,servers,seedstore,config}.rs` + bins,
`broker/src/{main,manifest_resolver,tcb,chain_executor}.rs`. Five dimensions: trust-forgery/root-pin,
anti-rollback/epoch, pipe/peer-SID auth, token/isolation/executor-binding, key-custody/separation.

## What HOLDS (central guarantee — CLEAN)

- **No fresh production forgery.** The production root pin (`3c83c2bc…`) cannot be swapped or read from config;
  a demonstration-root-signed manifest is rejected on the production path; `verify_strict` rejects malleable /
  non-canonical / short signatures; the demo-pinning constructors are `pub(crate)`. Without the offline root
  private you cannot mint a production `trusted_verified`.
- **Output→receipt binding is airtight.** The bytes hashed == signed == committed == the executor's captured
  stdout; the broker re-hashes its own in-memory buffer at `verify_and_accept`.
- **Root private never on the serving box** (`config.json root_seed=""`); no key material logged.
- **Server-side peer-SID gate** is fail-closed, kernel-attested (`ImpersonateNamedPipeClient`), verify-before-
  dispatch, correct `RevertToSelf`, no accept/read TOCTOU.
- **Pure verifier predicates** (privilege allowlist, STARTUPINFOEX handle-list incl. the duplicate-slot check,
  image hash + mandatory Authenticode floor, integrity gate) are sound as logic.

## Findings and disposition

| # | Sev | Finding | Disposition |
|---|-----|---------|-------------|
| P0-2 | P0 | **Pipe squat + broker impersonation.** Server pipes: NULL DACL + no `FIRST_PIPE_INSTANCE` (squattable); client omits `SECURITY_IDENTIFICATION` (default SecurityImpersonation) → a rogue local server relays a broker-SID token onward and passes the peer-SID gate. | **FIXED (`f28b559`)** — client now passes `SECURITY_SQOS_PRESENT \| SECURITY_IDENTIFICATION`; server creates with `FILE_FLAG_FIRST_PIPE_INSTANCE`. Windows-compiles clean; Owner re-ran the live-turn proof → still `trusted_verified`. |
| P0-1 | P0/P1 | **Anti-rollback floor forgeable.** `FLOOR_SEED_HEX` is a PUBLIC source constant, so the floor signature is not a defense against a source-reader who can write the deploy dir → replay an older, revoked-key manifest to `trusted_verified`. Broker (Linux) path doesn't verify the floor at all. | **HONESTLY CORRECTED (`f28b559`)** — no fake verification added (public-key signature = theatre). All false "cannot forge floor.sig" claims replaced with the reality: the signature is a corruption check; the real boundary is the deploy-dir OS write-ACL (broker-principal-only). Real closure (ACL enforcement + per-deploy sealed floor key + TPM counter) specified in [`WINDOWS_ANTIROLLBACK_HARDENING.md`](../WINDOWS_ANTIROLLBACK_HARDENING.md) as a gate prerequisite. |
| dim1-P2 | P2 | **`production_verified` decoupled from root custody** — self-test returns `production_verified=true` under the demo anchor. | **FIXED (`6fdedb8`)** — explicit `demonstration_custody` flag + a distinct UI "DEMONSTRATION CUSTODY" badge; boolean can no longer be read as production trust. |
| dim4-P1 | P1 | **Executor is a fixed placeholder** (`b"BROPS windows governed output v1"`), and the live spawn applies **none** of the containment (`verify_image` / restricted token / handle-list are not wired to it). Disclosed milestone gaps. | **OPEN (gated)** = the roadmap's P0-2 (executor → real model) + P0-3 (wire containment into the live spawn). Needs the model image + real session-0 isolation. |
| dim5-P1 | P1 | **Serving seeds plaintext at rest** during the provision→first-start TOFU window; permanently plaintext off-Windows. | **OPEN (design tradeoff)** — the lazy per-account DPAPI TOFU is deliberate for the cross-account deployment; tighten via a keys-dir ACL at provision + provision-immediately-before-start. |
| dim5-P2 | P2 | **receipt vs attestation `key_usage` not encoded in the manifest** (both keys carry the same `allowed_protocols`). Not exploitable in the wired flow (attestation verify is manifest-independent + pinned pubkey; receipt bind is to a fixed signer key_id). | **OPEN** — encode `key_usage` + give the attest key `[ATTESTATION_PROTOCOL]`; coordinated with the resolver, needs re-provision + re-verify. |
| dim4-P2 | P2 | `restricted_launch` reports a hardcoded integrity + a decorative (expected-vs-itself) handle-list; `bInheritHandles=FALSE`. | **OPEN (gated)** — part of the real session-0 syscall wiring (P0-3). |

## Bottom line

The crypto, root-custody, and output-binding are **sound** — the production custody proof (the offline root
driving a live `trusted_verified`) is honest. The defects are **rollback/revocation**, **local pipe
impersonation** (both P0, addressed), **custody hardening**, and the **disclosed "not-wired-yet" milestone
gaps**. This audit **confirms the shipped `platform_governed_execution_supported()` must stay `false`** until
the OPEN items land, an **independent** audit passes, and the Owner approves. Nothing here flips a badge.
