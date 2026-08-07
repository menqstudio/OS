# Bro delegation — captured stream evidence

**Status:** captured live on 2026-08-07. **Verdict: Bro delegates for real; the backend parser in
`apps/desktop/src-tauri/src/ai.rs` does not see it.**

This file exists so nobody has to re-derive the stream shape. Everything below was observed from a
real `claude` run, not read off a description. The Rust assertions that pin it live in the
`mod tests` block of `apps/desktop/src-tauri/src/ai.rs` (search `CAPTURED_SPAWN_LINE`).

- CLI: `C:\Users\Admin\.local\bin\claude.exe`, `claude_code_version: "2.1.220"`
- Model reported by the CLI: `claude-opus-5[1m]`
- Session: `921a5614-9ef4-4536-98bb-7291ec66442b` (probe 1), `apiKeySource: "none"`

---

## 1. Method

1. **Real argv, not a retyped one.** `claude_args(<system file>, streaming = true, model = None,
   agent = true)` was dumped straight out of the `brops` crate by a temporary test, giving 71
   arguments. The dump also produced `bro_agent_system_suffix(Some(<dir>))` verbatim.
2. The CLI was launched with **exactly** that argv (as an argv *list*, no shell re-quoting), with:
   - `cwd` = a throwaway project directory (a copy of `tools/`, `.claude/agents/`, `CLAUDE.md`,
     `START_HERE.md`) — deliberately *not* the shared worktree, because agent mode runs with
     `--permission-mode acceptEdits` and other agents were writing there;
   - the system prompt file = the app's real chat persona (`commands.rs`) + the agent suffix;
   - stdin = `transcript(messages) + "\n\nReply to the latest User message."`, exactly as
     `claude_cli_stream` writes it.
3. Raw stdout captured line-by-line; then `delegation_spawns` / `delegation_settlements` (the real
   functions, compiled from `ai.rs`) were run over every captured line.

The task given to Bro: *have a `reader` specialist report exactly how many files are in `tools/`;
give it `scope: tools` and `prohibited_scope: .claude`; do not count them yourself.*

---

## 2. Did Bro delegate? Yes.

He spawned a `reader`, it ran 13 tool calls in 44.4 s, returned "28 files", and Bro reported 28
back in Armenian. Exit code 0, empty stderr, `result.subtype: "success"`, `num_turns: 2`.

113 stdout lines, by type:

| line `type` | count | note |
|---|---|---|
| `system` | 21 | `init`, `status`, and **14 delegation-specific ones** (§5) |
| `stream_event` | 54 | `message_start` / `content_block_start` / `content_block_delta` ×44 / `content_block_stop` / `message_delta` / `message_stop` |
| `assistant` | 17 | 1 text, 1 delegation spawn, 1 thinking, 14 = the specialist's own tool calls |
| `user` | 15 | 14 carry a `tool_result` block |
| `rate_limit_event` | 1 | |
| `result` | 1 | |

---

## 3. THE FINDING — the spawn block is named `Agent`, not `Task`

`ai.rs::delegation_spawns` skips any block whose `name` is not `"Task"`. **The live CLI never
emitted `"Task"` anywhere in the stream** (`grep` count: 0). It emitted `"name": "Agent"`.

Running the real parser over the whole capture:

```
TOTAL spawns=0 settled=14      (probe 1)
TOTAL spawns=0 settled=8       (probe 2)
```

**Zero `delegationSpawned` frames on a turn where a specialist genuinely ran.** And because the
frontend (`apps/desktop/src/features/delegation.ts::applyDelegationEvent`) deliberately drops a
`settled` whose id it never saw spawned, the net user-visible result is: **the delegation surface
stays completely empty.**

The verbatim spawn line (`usage`/`diagnostics` elided; nothing renamed or re-nested):

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-5",
    "id": "msg_011CdoZkSEptkagQsguUhJZ1",
    "type": "message",
    "role": "assistant",
    "content": [
      {
        "type": "tool_use",
        "id": "toolu_018eiZUCt21zUYTGZ5C8Esau",
        "name": "Agent",
        "input": {
          "subagent_type": "reader",
          "description": "Count files in tools/",
          "run_in_background": false,
          "prompt": "Objective: …\n\nscope: tools\nprohibited_scope: .claude\n\n…"
        },
        "caller": { "type": "direct" }
      }
    ],
    "stop_reason": null,
    "usage": { … }
  },
  "parent_tool_use_id": null,
  "session_id": "921a5614-9ef4-4536-98bb-7291ec66442b",
  "uuid": "05a10517-01ff-4391-9a8e-c7d668791820",
  "timestamp": "2026-08-07T14:43:26.767Z",
  "request_id": "req_011CdoZkR67odePgEmS5x3GD"
}
```

Field by field, against what the parser expects:

| what the parser reads | present in the capture? | value |
|---|---|---|
| `message.content[]` (via `content_blocks`) | ✅ correct depth | array of 1 |
| `block.type == "tool_use"` | ✅ | `"tool_use"` |
| `block.name == "Task"` | ❌ **MISMATCH** | `"Agent"` |
| `block.id` | ✅ | `"toolu_018eiZUCt21zUYTGZ5C8Esau"` |
| `block.input.subagent_type` | ✅ | `"reader"` |
| `block.input.description` | ✅ | `"Count files in tools/"` |
| `block.input.prompt` | ✅ | the task text |
| — (not read) | extra field | `block.input.run_in_background: false` |
| — (not read) | extra field | `block.caller: {"type":"direct"}` |

Everything except the name is exactly what the parser assumes. Renaming only that field in the
captured line makes it parse completely — id, subagent type, description, prompt, tier tools
(`Read`/`Grep`/`Glob`, `agent_definition`), `scope: ["tools"]`, `prohibited_scope: [".claude"]`.
That is asserted in `the_same_captured_block_parses_completely_once_it_is_called_task`.

**Note the name split is real, not a doc error:** the CLI's *grant* name is `Task` — the `system`
`init` line reports `"tools": ["Task","Bash","Edit","Glob","Grep","Read","Write"]`, i.e. the app's
`--tools "… Task"` was accepted and is what enabled the spawn. Only the *wire block* is `Agent`.
A fix must therefore change the stream filter, **not** the `--tools` string.

The same name also appears earlier, on the partial-message stream (line 13), with an empty input:

```json
{"type":"stream_event","event":{"type":"content_block_start","index":1,
 "content_block":{"type":"tool_use","id":"toolu_018eiZUCt21zUYTGZ5C8Esau","name":"Agent",
 "input":{},"caller":{"type":"direct"}}}, …}
```

so the `assistant` line really is the first place the delegation is fully known — that part of the
design comment is correct.

---

## 4. The return line — matched, but always `unknown`

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "tool_use_id": "toolu_018eiZUCt21zUYTGZ5C8Esau",
        "type": "tool_result",
        "content": [
          { "type": "text", "text": "## Answer: 28 files\n\n…" },
          { "type": "text", "text": "agentId: ad6ea6bdb26047adf (use SendMessage …)\n<usage>subagent_tokens: 25800\ntool_uses: 13\nduration_ms: 44384</usage>" }
        ]
      }
    ]
  },
  "parent_tool_use_id": null,
  "session_id": "921a5614-9ef4-4536-98bb-7291ec66442b",
  "uuid": "dda30f55-3a4b-4782-8d3f-f470a8cb873f",
  "timestamp": "2026-08-07T14:44:11.166Z",
  "tool_use_result": {
    "status": "completed",
    "prompt": "…",
    "agentId": "ad6ea6bdb26047adf",
    "agentType": "reader",
    "content": "[{'type': 'text', 'text': '…'}]",
    "resolvedModel": "claude-opus-5[1m]",
    "totalDurationMs": 48123,
    "totalTokens": 23710,
    "totalToolUseCount": 7,
    "usage": { … },
    "toolStats": { "readCount": 1, "searchCount": 2, "bashCount": 4, "editFileCount": 0, … }
  }
}
```

`delegation_settlements` **does** match this: right depth, right block type, `tool_use_id` present
and equal to the spawn id, and `tool_result_text` handles the array-of-text-blocks form correctly.

Two observations:

1. **`is_error` is ABSENT on a delegation that completed successfully** — in both captures. So the
   parser's `None ⇒ "unknown"` rule means a successful delegation is reported as `unknown`, always.
   That rule is honest (better than rounding up to `ok`), but the outcome is therefore never
   informative on this route. The authoritative status is `tool_use_result.status: "completed"`, a
   **top-level sibling of `message`** — a field nothing in `ai.rs` reads. `tool_use_result` also
   carries `agentType` (`"reader"`), `agentId`, `totalDurationMs` and `toolStats`.
   *Not verified:* what a **failed** delegation looks like. Both probes succeeded, so whether
   `is_error: true` appears there is unknown — do not assume it does.
2. The summary is the join of **both** text blocks, so the CLI's `agentId: … <usage>…</usage>`
   footer rides along into whatever the surface renders.

---

## 5. The `system` lines the parser ignores entirely

The CLI already reports the full delegation lifecycle on `{"type":"system"}` lines, keyed by
`tool_use_id` — richer and earlier than what the `assistant`/`user` arms try to reconstruct:

| subtype | when | fields |
|---|---|---|
| `task_started` | at spawn | `task_id`, `tool_use_id`, `description`, `subagent_type`, `task_type: "local_agent"`, `prompt` |
| `task_progress` | ×13, per specialist step | `task_id`, `tool_use_id`, `description`, `subagent_type`, `usage{total_tokens,tool_uses,duration_ms}`, `last_tool_name` |
| `task_updated` | at end | `task_id`, `patch: {"status":"completed","end_time":1786113851162}` |
| `task_notification` | at end | `task_id`, `tool_use_id`, `status: "completed"`, `output_file`, `summary` |

`task_started` alone carries every field `DelegationSpawn` needs, under a stable name, and
`task_updated`/`task_notification` carry the real outcome. Worth considering as the primary source
if this is fixed.

---

## 6. The specialist's own tool calls appear on the SAME line types

While the `reader` ran, its internal `Glob`/`Read`/`Grep` calls streamed as ordinary `assistant`
lines and their returns as ordinary `user` lines. They differ only by:

- `parent_tool_use_id` = the delegation's `tool_use_id` (non-null), and
- extra top-level `subagent_type` / `task_description` fields.

`ai.rs` reads neither. **13 of the 14 `tool_result` blocks in probe 1 were the specialist's own**,
and `delegation_settlements` emitted a `DelegationSettled` for every one — carrying its output:
summaries of 9, 14, 876, 891 and **8 521** characters (a `Read` of `CLAUDE.md`). `commands.rs`
forwards them all as `delegationSettled` frames; the frontend discards them by id.

So today nothing is *displayed* wrongly — but the specialist's file contents and search output
cross the IPC on a channel named for delegation, and if the `Agent`/`Task` fix ever makes the id of
a nested `Agent`-in-`Agent` spawn known, those would start landing on the surface. Filtering
`parent_tool_use_id.is_null()` in the backend would be the cheap fix.

---

## 7. Other things that were checked

**All three tiers are offered; so are CLI built-ins the app never defined.** The `system` `init`
line reports:

```json
"agents": ["builder","claude","claude-code-guide","Explore","general-purpose","Plan","reader","runner","statusline-setup"]
```

- ✅ `reader`, `runner`, `builder` are all present — `--agents` works, and the code comment
  claiming `--setting-sources ""` hides the 262 pack roles is **confirmed**: not one
  `pack--role` name appears, even though `.claude/agents/` was in cwd.
- ⚠️ The built-ins were **not** suppressed. Bro can spawn `general-purpose`, `Explore`, `Plan`,
  `claude`, `claude-code-guide`, `statusline-setup`. `delegation_tools` resolves none of them, so
  such a spawn would render with **no `tools` field at all** ("unknown capability") while the agent
  actually holds whatever the built-in grants — for `general-purpose`, that is `*`. The narrowest-
  tier discipline in Bro's system prompt is the only thing steering him away from them.
- Also not suppressed by `--setting-sources ""`: user-level **skills and slash commands**
  (`init` listed 18 skills, 48 slash commands). Only settings/agents/hooks were excluded.

**The Bash deny-list DOES reach a spawned specialist.** Probe 2 asked Bro to delegate three shell
commands to a `runner`. Inside the subagent:

| command | `is_error` | result text |
|---|---|---|
| `python --version` | `false` | `Python 3.13.14` |
| `env` | `true` | `Permission to use Bash with command env has been denied.` |
| `sh -c "echo hi"` | `true` | `Permission to use Bash with command sh -c "echo hi" has been denied.` |

So `--disallowedTools` is inherited by subagents — the deny-list is not just a Bro-level boundary.
A second, separate gate also fired on a compound command:
`This Bash command contains multiple operations. The following parts require approval: …` for
`ls -la … 2>&1; echo "---exit:$?"`. Note this means **`;`-chained commands are refused for
specialists**, which will cost `runner`/`builder` tiers some ordinary shell ergonomics.

Note `is_error` **is** present (`true`/`false`) on ordinary tool results — it is specifically the
`Agent`/Task return that omits it.

**`parse_task_grant` against real Bro output.** When Bro put the label on its own line
(`scope: tools`), it read back exactly. In probe 2 he wrote it inline with prose:

```
SCOPE: `tools` (repo-relative). Everything outside that path is READ-ONLY.
PROHIBITED_SCOPE: `.claude` — do not read, write, or touch anything under it.
```

and the reader returned
`scope = ["tools","(repo-relative)","Everything","outside","that","path","is","READ-ONLY"]`.
Nothing enforces these strings, so this is a display defect, not a containment one — but a card
listing `Everything` and `READ-ONLY` as granted paths is not showing the owner a grant.

---

## 8. Summary of defects, in severity order

Status as of 2026-08-07, the same day the capture was taken. Four of the five were closed in
`ai.rs` on the strength of this document; each fix is pinned by a test holding the captured line
verbatim, so a regression fails against the real wire shape rather than against a fixture someone
wrote from memory — which is how defect 1 happened in the first place.

1. ✅ **`delegation_spawns` filtered on `name == "Task"`; the CLI emits `"Agent"`.** Delegation was
   100% invisible in the app. Both names are now accepted: we do not control this wire format and
   have observed exactly one CLI version, so accepting a name that never arrives costs nothing
   while missing the one that does cost the whole feature.
2. ✅ **A successful delegation reported `outcome: "unknown"`** because `is_error` is absent on a
   delegation return, though ordinary tool results carry it. `tool_use_result.status` — a
   top-level sibling of `message` — is now read, and only for values whose meaning is
   unambiguous. Anything unrecognised stays `unknown`.
3. ✅ **Every nested specialist tool return was emitted as a settlement**, one carrying 8_521
   characters of file text across the IPC. Both the spawn and settle readers now skip a line whose
   `parent_tool_use_id` is non-null. The frontend dropped them by unknown id, so nothing rendered
   — but the text crossed the boundary anyway, and a surface that never asked for a file's
   contents is the wrong place to first learn they are being sent.
4. ✅ **CLI built-in agent types (`general-purpose`, `Explore`, `Plan`, …) were spawnable and
   resolved to no known capability.** Closed by an actual refusal plus an honest residue, both
   re-verified against the live CLI on 2026-08-07 (§10).

   The roster was re-captured first, because the list above was a session old. It had not moved:
   CLI 2.1.220 still offers the same nine names, six of them the CLI's own.

   Neither of the two candidates was taken as stated. **Reporting a spawn as REFUSED would have
   been a second untruth**: by the time an `Agent` block reaches the stream the specialist has
   already started, so this parser can only describe, never refuse — a card reading REFUSED over
   an agent that ran for forty seconds is the same class of error as the blank it replaced. And
   **resolving the built-ins' real tool lists is not available to us**: we have never read them,
   and a tool list nobody read is the one output that could actively mislead. So:

   - **The refusal moved to where refusing is possible — argv.** `tool_args` now passes
     `Task(<name>)` **and** `Agent(<name>)` to `--disallowedTools` for all six built-ins. Verified
     live, not inferred from a flag reference: the CLI returned, on the delegation's own
     `tool_result` with `is_error: true`,
     `Agent type 'general-purpose' has been denied by permission rule 'Agent(general-purpose)' from cliArg.`
     Both name forms are passed because a `Task(…)` pattern came back named as an `Agent(…)`
     rule — the same `Task`/`Agent` split as §3, and not a coin worth flipping on a boundary.
     In the same turn a `reader` still spawned, ran and answered, so this costs the tiers nothing;
     `denying_the_builtins_leaves_task_and_the_three_tiers_working` pins that both statically and
     against the captured init frame.
   - **What a deny list cannot cover is now named rather than blank.** `DelegationSpawn` carries
     `origin` — `Tier` / `PackRole` / `CliBuiltin` / `Unrecognized` — answering a question about
     the NAME, which is always knowable, instead of about the tool list, which usually is not.
     `AgentOrigin::Tier` is the only value meaning Bro's choice bounded the specialist. No tool
     list is invented for a built-in anywhere: `tools`/`tools_source` stay absent, exactly as
     before. `delegation_tools` also now refuses to let a built-in borrow a `.claude/agents/
     <name>.md` that merely shares its filename — no such file exists today, and one added
     tomorrow would have dressed a built-in in a narrow grant.
   - **Bro is told.** His system prompt said "grant the narrowest tier" while silently assuming
     every name on offer was a tier. It now names all six built-ins, says that spawning one
     leaves the capability decision unmade rather than granting something wide or narrow, and
     says the app refuses them.

   **Still open, and it is the reporting half.** `commands.rs::delegation_frame` does not carry
   `origin` onto the wire, and `commands.rs` was out of scope here — so today the origin is
   established and tested but does not reach the screen. What the surface needs is one
   `obj.insert("agentOrigin", json!(d.origin.as_str()))` beside the existing `tools`/`toolsSource`
   pair, and a reader in `features/delegation.ts` that renders any value other than `app_tier` as
   a warning rather than as the blank `toolsSource: 'unresolved'` currently produces. Until then
   a denied built-in is still visible to the owner — the spawn is parsed and the settlement
   reports `error` with the CLI's refusal text as its summary — but it is visible as a failure,
   not as an attempt to reach outside the capability model.
5. ✅ **`parse_task_grant` turned an inline prose sentence into a path list** — Bro's real
   "SCOPE: `tools` (repo-relative). Everything outside that path is READ-ONLY" became eight granted
   paths including `(repo-relative)` and `READ-ONLY`. The reader is now all-or-nothing per line:
   one token that is not a path discards the line, because a precise validated list of places
   nobody named is worse than saying no scope was stated.

---

## 9. Reproducing

```powershell
# 1. dump the real argv out of the crate (temporary test, see git history of ai.rs)
$env:BROPS_ARGV_DUMP="<scratch>\argv.json"
cargo test --manifest-path apps\desktop\src-tauri\Cargo.toml -p brops --lib zz_dump_real_argv -- --nocapture

# 2. run the CLI with that argv list verbatim (python subprocess, argv as a list — no shell),
#    cwd = a throwaway project dir, transcript on stdin, stdout > capture.jsonl

# 3. run the real parser over the capture (temporary test)
$env:BROPS_CAPTURE="<scratch>\capture.jsonl"
cargo test --manifest-path apps\desktop\src-tauri\Cargo.toml -p brops --lib zz_check_parser_against_capture -- --nocapture
```

The permanent, capture-derived assertions are in `ai.rs`'s `mod tests`; run them with

```powershell
cargo test --manifest-path apps\desktop\src-tauri\Cargo.toml -p brops --lib
```

---

## 10. Re-capture of 2026-08-07 (defect 4)

Same method as §1, same CLI (`2.1.220`), same throwaway cwd. Five runs. Every argv was dumped out
of the crate by the temporary `zz_dump_real_argv` test of §9 — none was retyped, and the two that
carry deny patterns were dumped **after** the change, so what was probed is what ships.

| run | argv | what it established |
|---|---|---|
| A | 71 args (pre-change) | The roster had not moved in a session: `agents` = `["builder","claude","claude-code-guide","Explore","general-purpose","Plan","reader","runner","statusline-setup"]`, `tools` = `["Task","Bash","Edit","Glob","Grep","Read","Write"]`. |
| B | 71 args (pre-change) | Asked for `general-purpose` by name, Bro **spawned it** — an `Agent` block with `subagent_type: "general-purpose"` — and the specialist then ran `Bash` under it. A built-in was genuinely reachable, and `delegation_tools` resolved nothing for it. |
| C | 71 + 6 `Task(<name>)` | The CLI **refused**: `is_error: true`, text `Agent type 'general-purpose' has been denied by permission rule 'Agent(general-purpose)' from cliArg.` Note it answered a `Task(…)` pattern by naming an `Agent(…)` rule. |
| D | 71 + 12 (both forms) | Same refusal, and in the SAME turn a `reader` spawned 11 s later, ran, and returned its count. The deny costs the tiers nothing. |
| E | 83 args, **as shipped** | Asked to spawn `Explore`, Bro declined to attempt it at all, giving the system prompt's own reason — and said he could not quote a refusal text because he never made the call rather than inventing one. He then delegated the real work to a `reader`, which ran and answered. |

Sessions: `b1847222-63c0-4ccf-ad8d-08a7faeaa550` (A + B, one run),
`e8409224-dbaa-4934-b2a4-4f08214dd659` (D). The four new `CAPTURED_*` constants in `ai.rs`'s
`mod tests` are verbatim lines from those two runs, abridged only by dropping `usage` /
`diagnostics` / roster-irrelevant init fields.

Run E is why the prompt fix is not merely belt-and-braces: the wall in argv stops a spawn, but a
Bro who keeps walking into it burns a turn and lands a failed delegation on the owner's screen
each time. Told what the built-ins are, he stops before the wall.

Two things run B established that are worth keeping separate from the fix: a built-in spawn
carries the **same** `Agent` block shape as a tier, so nothing on the wire distinguishes them —
only the name does; and `is_error` **is** present on a refused delegation, though §4 records it as
absent on one that completes. The CLI reports the refusal and not the success.
