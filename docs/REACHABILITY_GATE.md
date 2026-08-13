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
3. **`src-tauri` Rust symbols.** Declared symbols under `apps/desktop/src-tauri/**` have a caller
   outside their own module *and* outside `#[cfg(test)]`, carrying the same two expectations as the
   engine symbols. **This was missing until 2026-08-09**, and the omission was not a small one: the
   security core of this product is Rust, and `rustc` warns about an uncalled *private* item while
   saying nothing about a `pub fn` in a library crate. That is exactly the shape
   `core/src/governed_output_stream::{mint,resolve,sweep}` had — public, documented, nine passing
   unit tests, zero production callers, a clean build, and a §4.10(f) ladder the roadmap believed
   was unbuilt while the code read as though it were built.
   A Rust entry needs `module` as well as `defined_in`, because a caller has to **name** the symbol
   (`module::name(`, or a bare call in a file that `use`s it from that module). A bare-name scan
   would have counted `ai.rs`'s own unrelated `resolve()` as a caller of
   `governed_output_stream::resolve` — a false green produced by the gate that exists to prevent
   false greens. The price runs the other way and is stated in the gate's output: a call through a
   trait object, a re-export, or a function pointer is not seen, so `must_have_caller` overstates
   what this can defend and `declared_unreachable` is the expectation it can actually hold.
4. **Capability grants.** Every `allow-*`/`deny-*` in
   `apps/desktop/src-tauri/capabilities/default.json` corresponds to a registered command and
   vice versa (except `check_capabilities.INTENTIONALLY_UNGATED`, imported rather than copied).
   An `allow`-granted command with no caller is reported as invokable surface with no user.

**What counts as a caller.** A mention in a comment is not a call — comments are stripped before
matching. A reference from the symbol's own tests is not a caller — that is exactly how
`assert_no_bytecode_shadow` looked green, and on the Rust side a `#[cfg(test)] mod` is stripped for
the same reason (brace-matching skips string literals, so a `{` inside a SQL statement cannot close
the module early and expose the rest of the file as production code). On the frontend a command
counts as called only when its name is a string literal in the **argument position** of a call, so
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
- for a `policy_flag` it proves the flag is **read**, never that it is **set**;
- **a Rust caller has to be named** — `module::name(`, or a bare call in a file that `use`s it
  from that module. That refusal to guess is what keeps an unrelated same-named function from
  reading as a caller, and the same refusal makes a call through a trait object, a re-export, or
  a function pointer invisible. So on the Rust side `declared_unreachable` is a claim this gate
  can defend and `must_have_caller` is one it can only partly defend.

## 4. Declared exceptions — the open ones

Full text and observed state live in `config/reachability-declarations.json`. Summarised:

| Surface | Reason | Why |
|---|---|---|
| `decide_approval` | capability-denied | `deny-decide-approval` (T-011): approving needs renderer-independent native confirmation. Having no caller is the enforced state. |
| `post_message` | superseded | `post_user_message` fixes the role server-side; `post_message` only validates it. Residual allow-granted surface. |
| `reply_in_conversation` | superseded | Non-streaming twin of `stream_reply` on the same governed pipeline; every chat surface uses the streaming sibling. |
| `set_run_step_status` | superseded | Steps transition through `stream_run_step` / `advance_run`; a renderer that could stamp a step status could claim work it never did. |
| **`create_decision`** | **not-yet-wired (OPEN)** | **Tracked here.** The Decisions page is a read-only mirror and offers no create control, yet the command is registered and `allow`-granted. Closes either by wiring a create control on the Decisions page, **or** by flipping the grant to `deny` because authoring governance decisions from the webview is not wanted. Until one is chosen this is invokable surface with no user. |

**Rust symbols — declared 2026-08-09, the first three the gate has ever seen.**

| Rust symbol | Expectation | Why |
|---|---|---|
| `governed_output_stream::mint` | declared_unreachable | The rev-30 §4.10(f) output-stream ladder, implemented ahead of the transport that would use it. |
| `governed_output_stream::resolve` | declared_unreachable | Same module. **Zero production callers, confirmed by this run**; every reference is inside its own `#[cfg(test)] mod tests`. |
| `governed_output_stream::sweep` | declared_unreachable | Same module. |

Three things about that entry are worth reading before anyone wires a caller, because two of them
were being confused with each other for weeks:

- **It is not the roadmap's "governed streaming".** MASTER_EXECUTION_ROADMAP Phase 1 descopes
  delta-streaming — a governed turn is buffered by construction, since the desktop's authority is a
  signature over the *whole* output. §4.10(f) is the other end of that: a chunked **pull** of an
  already-completed output, checked against the same whole-output digest.
- **Nothing pulls yet.** The shipped broker runs the turn in-process and returns the output inline
  in its single-request/single-response reply, so no `output_stream_id` is ever minted. Only
  `create_schema` has callers (four of them), which is why the table exists and stays empty.
- **The shipped table diverges from the design it cites**, so wiring a caller is a rewrite, not a
  hookup: design §4.10(f) is INSERT-ONCE with `receipt_id`/`execution_attempt_id`/`output_handle`/
  `output_bytes`/`output_sha256`/`retained_until_ms` and a per-install quota of 64; this one has a
  mutable `state` column, a `broker_turn_id` instead of those bindings, and a quota of 8 — and the
  design's server-side `stream_binding_mismatch` cannot be produced at all, because the columns it
  compares do not exist.

`create_schema` is deliberately **not** declared: three sibling modules in `brops-core`
(`broker_turns`, `governed_message_store`, `supervisor_ledger`) export a function of the same
name, and its four call sites qualify it by module, so declaring it would test the module path
rather than the symbol and report a green it has not earned.

**Engine symbols — state re-observed 2026-08-09 by running the gate.** Two of the five changed
state *while the gate was being written* (2026-08-07), by concurrent agents closing O-1 and O-3 in
the working tree, and the row for `head_anchor_payload`/`attach_head_anchor` said something about
O-2 that stopped being true in the same window. The gate re-derives all of this on every run; the
table is the record of what one run saw, not a source of truth. **Line numbers move — run the gate
rather than citing this table.**

| Engine symbol | Expectation | Residual item |
|---|---|---|
| `assert_no_bytecode_shadow` | **must_have_caller** | O-1 (HIGH) — the canonical "implemented and nothing calls it", and **it gained callers under the gate**: `bro_control_plane.py:80` (in `_bind_workspace`, before any binding loads) and `:271` (the settlement path, a second process the binding path never covers). The gate now defends those call sites. It does **not** verify the rest of O-1 closure (hooks running `python -B`, `compileall` scoped off digest roots, the stray-`.pyc` regression test); O-1's status is owned by `PHASE_10_PRODUCTION_ITEMS.md`. |
| `head_anchor_payload` | declared_unreachable | O-2 (MEDIUM, OPEN) — **caller-less on purpose, and no longer for the reason this row used to give.** It is not true that "there is no producer for the signed audit-head anchor": `bro_audit_log.append()` is the **in-band producer** — inside the same exclusive append lock it assembles the payload, signs it through the configured custody (`BRO_AUDIT_ANCHOR_SIGNER` / `BRO_AUDIT_ANCHOR_KEY_ID`), installs it, and refuses to append at all if an anchor is present with no custody configured; a keyed `verify()` then *requires* one. This function is the **owner-facing out-of-band half**, whose caller is a signing command outside the engine by design — a signer the ledger's own writer could reach would prove nothing. **Zero in-repo callers, confirmed by this run**, and that is the enforced state. What keeps O-2 open is the *principal*, not the producer: see below. |
| `attach_head_anchor` | declared_unreachable | O-2 (MEDIUM, OPEN) — the install half of the same owner-facing API: it verifies a signed anchor against the trusted registry and against the ledger's current chain before storing it. Caller-less for the same reason. **Zero callers, confirmed by this run.** |
| `verify_conductor_session_token` | **must_have_caller** | O-3 — genuinely called from `bro_completion.py`; the one of the five that was never dead. The gate now protects that call site, because losing it would silently return conductor identity to a plain environment-variable claim. |
| `require_conductor_session_token` | **must_have_caller** (policy flag, `read_via`) | O-3 (MEDIUM) — read through `CONDUCTOR_SESSION_POLICY_KEY` in `bro_policy.py`, which treats an *undeclared* requirement as a *required* one. **It is present in `engine/.bro/policy.json`, and `true`** — an earlier revision of this row said it was "still absent", which was written before the flag landed and never revisited. Proving the flag is *read* is still all this gate does; proving it is *set* is `engine/.bro/policy.json`'s business and outside the gate by construction. The credential the flag demands is no longer an Owner-only artifact either: first-launch provisioning mints the `conductor-session`. |

**What actually keeps O-2 open**, since the producer no longer does: the anchor is worth its
signature only under a principal the ledger's own writer cannot become. On Windows that principal
is built — a `brops-audit-signer` service under a virtual service account, reached over the
peer-authenticated named pipe by the `brops-anchor-relay` shim — but it ships in **no installer**
and `register::apply` has no entry point outside tests; on POSIX it is specified and has never run.
That is engine/deployment security work under the golden rule (deliberate, tested, never rushed)
and is **not** closeable by editing CI or this gate.

Note also that `config/reachability-declarations.json` carries its own `observed:` notes, dated
2026-08-07. Those are a record of one run, not a claim about now — `require_conductor_session_token`'s
still says "Still absent from engine/.bro/policy.json", which the run above contradicts. The gate's
own output is the current answer.

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
