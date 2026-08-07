# Owner ceremony — the three artifacts only you can mint

**Who this is for:** Gev. Nobody else can do any of it, which is the point.

Three of the five residual engine items (**O-2**, **O-3**, **O-5**) are closed in code and waiting
on a signature. The engine can verify each artifact today — the type is registered, the consuming
path exists, the tests pass. What it does not have is the artifact, because minting one requires
the offline root that lives on your media and nowhere else.

> **Registering a type opens no path.** Each of the three refuses right now even against a
> flawless, correctly-typed, operator-signed artifact — because the shipped
> `engine/config/trusted-keys.json` grants the type to no key. Pinning a key is what opens it, and
> that is a deliberate second lock, not an oversight. There is a test for each.

You already did the harder half: `apps/desktop/src-tauri/win-live/CUSTODY_CEREMONY.md` is the
ceremony that produced your offline root, and these three reuse it.

---

## Before you start

- The **offline machine** with your root private seed. Nothing below runs on the serving box
  except the last line of each section.
- `broctl.py` already knows all three types — check with
  `python engine/tools/broctl.py sign --help`.
- **`broctl keygen --production` refuses on purpose.** Production roots are generated offline, by
  you, not by a tool running on a networked machine. If you see that refusal, it is working.

Every artifact has the same shape: a `payload` you write, and a detached Ed25519 `signature` over
its JCS-canonical form. `broctl sign` produces the pair.

```powershell
python engine/tools/broctl.py sign `
  --key   <path to your offline operator-root private key> `
  --artifact <one of: conductor-session | evidence-floor-anchor | audit-head> `
  --in    payload.json `
  --out   artifact.signed.json
```

Then, once per key, add it to `engine/config/trusted-keys.json` — `status: "active"`, and the
artifact type listed in `allowed_artifact_types`. That file is itself operator-signed, so rebuild
it with `broctl build-registry` rather than editing by hand.

---


> **Do not hand-type these.** `engine/tools/mint_owner_payloads.py` writes the O-3 and
> O-5 payloads with the epoch computed for you — a wrong `expires_at_epoch` pasted at a
> terminal is invisible until a session refuses. It cannot sign: that needs the offline
> key, and a tool offering both would invite running it on the box that serves.
>
> ```bash
> python3 engine/tools/mint_owner_payloads.py \n>     --key-id gev-operator-root-1 --session-id s-2026-08-08-a \n>     --task-id t-example.1 --head-sequence 5 --hours 8 --out /media/usb/payloads
> ```

## O-3 — conductor session token *(start here, it is the smallest)*

**What it fixes.** Anything that could set an environment variable could claim to be the conductor
and stop work. The check now demands a signed token and fails closed without one — so **conductor
stops refuse right now**, deliberately, until this exists.

`payload.json`:

```json
{
  "artifact_type": "conductor-session",
  "key_id": "<your operator-root key id>",
  "session_id": "<a fresh id for this harness session>",
  "agent_id": "bro-000",
  "role": "bro",
  "expires_at_epoch": 1786000000
}
```

On the serving box:

```powershell
$env:BRO_CONDUCTOR_SESSION_TOKEN = "C:\path\to\artifact.signed.json"
```

**Rotate it per session.** `expires_at_epoch` is judged against the wall clock, not a
caller-supplied one, precisely so a caller who could backdate the clock cannot revive an expired
identity. A long expiry is a long window in which a stolen token is a valid conductor.

---

## O-5 — evidence floor anchor

**What it fixes.** A marker records "this task's evidence has reached step N", so nobody can roll
it back. It used to be a plain file: delete it, re-create it, and the rollback became invisible.
The sequence now travels inside signed bytes, and this anchor is what survives a full wipe.

`payload.json` — **one per task**, and `head_sequence` must match the chain's real head:

```json
{
  "artifact_type": "evidence-floor-anchor",
  "key_id": "<your operator-root key id>",
  "task_id": "<the task this anchor is for>",
  "head_sequence": 5
}
```

On the serving box:

```powershell
$env:BRO_EVIDENCE_FLOOR_ANCHOR = "C:\path\to\artifact.signed.json"
```

The anchor is only *consulted* when a completion declares `head_sequence > 1` and the deployment
holds no durable mark — i.e. exactly the wipe-and-re-provision case. A task at sequence 1 is the
chain's first anchor and needs none.

---

## O-2 — audit head anchor ⚠️ *different in kind — read this one twice*

**What it fixes.** The audit log's "head" file records where the log ends. Whoever could write the
log could rewrite the head, and verification reported *intact*. The head must now carry a
signature.

**This is not a static artifact.** The other two are files you sign once. This one is a **signing
command** the engine invokes whenever it appends:

```powershell
$env:BRO_AUDIT_ANCHOR_SIGNER  = "C:\path\to\signer.exe"   # or a JSON argv array
$env:BRO_AUDIT_ANCHOR_KEY_ID  = "<the key id it signs with>"
```

**The one rule that makes it worth anything:** that command must run as a principal the **ledger's
own writer cannot reach**. A signer the writer can invoke, or a key the writer can read, proves
nothing at all — the writer forges the head and signs it too. The code refuses a signer path that
resolves inside the engine, but it cannot check your account separation for you.

Half-configuration is a loud refusal rather than a silent downgrade: set one variable and not the
other and it stops, rather than quietly falling back to the plaintext head.

---

## Order, and what each unlocks

1. **O-3** — smallest, and it un-blocks conductor stops, which refuse today.
2. **O-5** — one anchor per task you care about.
3. **O-2** — needs the separate-principal decision, so leave time for it.

Then two that are **not** yours:

- **O-4** — closed in code as of this branch. It needs the same treatment as O-3/O-5: mint a
  `control-room-command` artifact per owner command and pin its key. Unlike a session credential
  it is bound to one `command_id` + `task_id` + `command`, so a stolen one replays exactly the
  command that was already signed.
- **O-1** — **not closeable from inside Python.** `-B` stops bytecode being *written*; nothing
  stops CPython *reading* an existing `.pyc`, and a cache planted before the process starts
  shadows the very module that would detect it. Closing it is a deployment decision:
  `PYTHONPYCACHEPREFIX` pointed outside the tree, a read-only control plane, or a launcher that
  clears caches before start. No signature helps.

---

## Then, and only then: the audit

The gate — `platform_governed_execution_supported()` — does **not** open when the five items
close. It needs a separate thing: an **independent audit of the whole chain**, by someone who did
not build it.

**Run it when:** O-1 through O-5 are closed *and* you have decided the O-1 deployment answer.
Auditing before that produces a report whose findings you already know.

**Why a green CI is not it:** CI runs the tests we wrote. Three separate audits on this repository
came back RED on rows the builder had marked closed. That is why `✅` in the ledgers means
*independently confirmed* and `◑` means *the builder's own claim*, and why nothing in this document
is marked `✅`.

**After a green audit, the gate is one line — and it is yours to flip, not mine.**
