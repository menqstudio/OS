# The reachability gate — "something is implemented and nothing calls it"

> **What this file is.** The short normative note for `tools/check_reachability.py` and
> `config/reachability-declarations.json` (CI job `Reachability · nothing implemented-and-uncalled`
> in `.github/workflows/supply-chain.yml`). The gate's own docstring is the long form; this page
> exists so the declared OPEN gaps have somewhere to be tracked and so a reviewer can see, in one
> place, what the gate does and does not prove.

## 1. The defect it makes RED

Five separate times in one week this repository shipped something that nothing called:

- a capability policy with no enforcement path;
- 262 agent definitions the app could not see;
- two backend commands with no frontend wrapper;
- five engine security functions with zero callers.

Each read as protection while doing nothing, and each was found by a human audit rather than by
the build. A gate that checks a thing *exists* cannot tell you the thing is *reached*, so
reachability is now itself a checked claim.

## 2. What it checks

1. **Tauri commands.** Every command in `generate_handler!` (`apps/desktop/src-tauri/src/lib.rs`)
   is invoked from `apps/desktop/src/**` **production** code — `apps/desktop/src/services/desktop.ts`
   is the intended single typed boundary — or is declared in
   `config/reachability-declarations.json` with a reason and a written note.
   A command that is *defined* with `#[tauri::command]` but never registered is also RED.
2. **Engine security symbols.** The five named in `docs/PHASE_10_PRODUCTION_ITEMS.md`
   (`assert_no_bytecode_shadow`, `head_anchor_payload`, `attach_head_anchor`,
   `require_conductor_session_token`, `verify_conductor_session_token`) each carry an expectation:
   `must_have_caller` (RED if the caller disappears) or `declared_unreachable` (RED if a caller
   appears, so the exception cannot outlive the condition).
3. **Capability grants.** Every `allow-*`/`deny-*` in
   `apps/desktop/src-tauri/capabilities/default.json` corresponds to a registered command and
   vice versa (except `check_capabilities.INTENTIONALLY_UNGATED`, imported rather than copied).
   An `allow`-granted command with no caller is reported as invokable surface with no user.

**What counts as a caller.** A mention in a comment is not a call — comments are stripped before
matching. A reference from the symbol's own tests is not a caller — that is exactly how
`assert_no_bytecode_shadow` looked green. On the frontend a command counts as called only when its
name is a string literal in the **argument position** of a call, so
`const DENIED_DECIDE_COMMAND = 'decide_approval'` — a constant that exists in order never to be
invoked — is correctly *not* a call.

## 3. What it cannot prove

It is a static text scan, not a call graph. Stated in the gate's output on every run and in its
docstring, because a gate that overstates its coverage is the same lie one level up:

- **dynamic dispatch is invisible in both directions** — a computed `invoke(name, …)` reads as
  unreachable (a false red the declarations file absorbs), and any argument-position string
  literal reads as reached even when the enclosing call is not `invoke` (a false green);
  `getattr` / registry / dynamic-import indirection on the Python side is not seen at all;
- **reachability is one level deep, not transitive** — a caller that nothing itself calls still
  counts, so an island of mutually-referencing dead code passes;
- it cannot tell whether a **user** can reach the path (a flag that is off, an earlier throw);
- it says nothing about whether the callee **does what it claims** (that is
  `tools/check_spec_references.py`, and ultimately a human audit);
- for a `policy_flag` it proves the flag is **read**, never that it is **set**.

## 4. Declared exceptions — the open ones

Full text and observed state live in `config/reachability-declarations.json`. Summarised:

| Surface | Reason | Why |
|---|---|---|
| `decide_approval` | capability-denied | `deny-decide-approval` (T-011): approving needs renderer-independent native confirmation. Having no caller is the enforced state. |
| `post_message` | superseded | `post_user_message` fixes the role server-side; `post_message` only validates it. Residual allow-granted surface. |
| `reply_in_conversation` | superseded | Non-streaming twin of `stream_reply` on the same governed pipeline; every chat surface uses the streaming sibling. |
| `set_run_step_status` | superseded | Steps transition through `stream_run_step` / `advance_run`; a renderer that could stamp a step status could claim work it never did. |
| **`create_decision`** | **not-yet-wired (OPEN)** | **Tracked here.** The Decisions page is a read-only mirror and offers no create control, yet the command is registered and `allow`-granted. Closes either by wiring a create control on the Decisions page, **or** by flipping the grant to `deny` because authoring governance decisions from the webview is not wanted. Until one is chosen this is invokable surface with no user. |

**Engine symbols — state observed 2026-08-07, the day the gate was written.** Two of the five
changed state *while it was being written*, by concurrent agents closing O-1 and O-3 in the
working tree. The gate re-derives all of this on every run; the table is the record of what one
run saw, not a source of truth.

| Engine symbol | Expectation | Residual item |
|---|---|---|
| `assert_no_bytecode_shadow` | **must_have_caller** | O-1 (HIGH) — the canonical "implemented and nothing calls it", and **it gained callers under the gate**: `bro_control_plane.py:80` (in `_bind_workspace`, before any binding loads) and `:267` (the settlement path, a second process the binding path never covers). The gate now defends those call sites. It does **not** verify the rest of O-1 closure (hooks running `python -B`, `compileall` scoped off digest roots, the stray-`.pyc` regression test); O-1's status is owned by `PHASE_10_PRODUCTION_ITEMS.md`. |
| `head_anchor_payload` | declared_unreachable | O-2 (MEDIUM, OPEN) — no producer for the signed audit-head anchor. **Zero callers, confirmed by this run.** |
| `attach_head_anchor` | declared_unreachable | O-2 (MEDIUM, OPEN) — the consumer half of the same dead path. **Zero callers, confirmed by this run.** |
| `verify_conductor_session_token` | **must_have_caller** | O-3 — genuinely called from `bro_completion.py`; the one of the five that was never dead. The gate now protects that call site, because losing it would silently return conductor identity to a plain environment-variable claim. |
| `require_conductor_session_token` | **must_have_caller** (policy flag, `read_via`) | O-3 (MEDIUM) — read through `CONDUCTOR_SESSION_POLICY_KEY` in `bro_policy.py`, which now treats an *undeclared* requirement as a *required* one. Still **absent from `engine/.bro/policy.json`**. Proving the flag is *read* is what this gate does; proving it is *set* needs an operator-signed artifact only the Owner can mint and is outside this gate by construction. |

Closing O-2 is engine security work under the golden rule (deliberate, tested, never rushed) and
is **not** closeable by editing CI or this gate.

**The gate turns RED when a defect is FIXED, and that is deliberate.** When a caller lands for a
`declared_unreachable` symbol, the gate fails and asks for the expectation to be flipped to
`must_have_caller`. That is the point: the fix gets *recorded* — and from then on defended —
instead of being silently absorbed by an exception that outlives the condition it described. This
happened for real, twice, during the gate's own construction.

## 5. Running it

```bash
python tools/check_reachability.py            # the gate
cd tools && python -m unittest test_check_reachability   # its self-tests
```
