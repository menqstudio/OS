#!/usr/bin/env python3
"""The production half has a finish line now — and this gate is RED until it is crossed.

**Read this first: this gate is RED BY DESIGN, and will stay RED until the production half
exists.** That is not a defect, a misconfiguration, or a job to rerun. It is the whole point.

WHY IT EXISTS
-------------
Every other piece of work in this repository has a gate, and therefore has a measurable
"done": 39 hardcoded audit actors, a path-mangling ``lstrip("./")``, 242 declared negative
tests, the README's counts. The production half — the thing a paying customer would actually
receive — has had none. Nothing goes red if it is never built, so it loses every scheduling
contest to work whose finish line a machine can see. Not because it matters less. Because
"finished" was not measurable for it.

So the gate is written first and left failing. Its RED output is the deliverable: someone
reading a CI log should be able to answer *"when does a customer see something?"* from these
five lines and nothing else.

**A gate that cannot fail yet measures nothing.** The converse is the trap this file is
walking into deliberately: a gate that cannot *pass* yet measures nothing either. So
``tools/test_check_produced_artifact.py`` builds a synthetic tree that satisfies all five
conditions and asserts this gate goes GREEN on it. The gate has been observed passing; it is
not a function that can only refuse.

THE FIVE CONDITIONS
-------------------
All five must hold. Any one absent is RED.

  1. At least one artifact exists in the produced-agent store, with a DEFINED SCHEMA — not a
     row whose ``action`` is the string ``verb: argument``. (``automations.action`` is that
     string today; ``execute_action`` at ``apps/desktop/src-tauri/core/src/repo.rs`` is
     ``split_once(':')`` plus a three-arm match over ``notify`` / ``task`` / ``note``.)
  2. That artifact carries a flow with MORE THAN ONE STEP.
  3. It carries a grant — capabilities, paths, domains — WRITTEN BY THE RUNTIME. A grant that
     is present only in a prompt is prose, and prose is what ``scope``/``prohibited_scope``
     already is. Prose does not enforce.
  4. ``run_due()`` has invoked it at least once and a run row exists. Today
     ``apps/desktop/src-tauri/src/lib.rs`` calls it and throws the result away with ``let _``.
  5. A receipt for that run carries ``enforcement_regime``. A ``grep -rn enforcement_regime``
     over this tree printed nothing at all on 2026-08-30.

HOW IT LOOKS, AND WHY THIS WAY
------------------------------
Nothing it inspects exists yet, so the design question is not *what* to check but *how to
check for the absence of a thing whose shape nobody has agreed to*. A gate that hardcodes a
guessed shape gets edited to match whatever gets built, and an edited gate is a mirror rather
than a check.

**This gate hardcodes no shape.** It reads ``config/produced-artifact-contract.json``, which
declares WHERE each fact lives and WHAT it is called — every locator ships ``null``, meaning
"the implementation has not decided", and each ``null`` is one of the five RED lines. Filling
a locator in does not make the gate green; it makes the gate go and look, and an absent thing
is still RED. The field-level definition of an artifact lives in the JSON Schema the contract
points at, so this file holds no opinion about it either.

Two controls stop the contract being satisfiable by editing alone:

  * **The evidence must be PRODUCED, not COMMITTED.** The gate refuses a store, a runs file
    or a receipts file that ``git ls-files`` reports as tracked. A checked-in fixture is a
    fixture. Only a run can make this evidence.
  * **Condition 4 is re-grounded in the tree.** The gate finds ``fn run_due`` in the Rust
    source before it will believe a run row that names it, so the evidence cannot cite a
    function that does not exist.

WHAT THIS GATE CANNOT DO — read before trusting it
--------------------------------------------------
  * It cannot tell a genuine end-to-end export from one a producer script fabricated. It
    establishes that the evidence was produced rather than committed, and that its parts
    cross-reference each other; it does not attest the producer.
  * Condition 3 establishes that the grant is in the artifact's bytes rather than in prose,
    and that it names a runtime writer. It cannot prove which process wrote the file.
  * Schema validation is PARTIAL and stated as partial: ``required`` presence plus the
    declared ``type`` per property. It is not a JSON Schema implementation and does not
    pretend to be one — stdlib only, no dependency.

NOT YET A REQUIRED CHECK, AND THAT DEFERRAL IS ITSELF UNDER A GATE
-------------------------------------------------------------------
This context is deliberately ABSENT from ``config/required-checks.json`` at the commit that
introduced it. ``main`` carries 33 required contexts with ``enforce_admins: true``, so a
required context that can never pass blocks EVERY merge, and fixes were in flight. Adding it
is a separate, deliberate step, to be taken once that queue drains.

"Once the queue drains" is an intention, and every deferred enforcement in this repository
has ended as a correctly written control wired to nothing. So the deferral is a DATED entry in
``config/deferred-enforcement.json``, and ``tools/check_repo_state.py::verify_deferred_enforcement``
— which runs inside the ALREADY-REQUIRED context ``Repo-state · live GitHub truth verifier`` —
turns RED once ``deferred_until`` passes while the context is still absent. The trigger is a
date and not a state on purpose: a state is controlled by the same person who owes the
enforcement, so "once the queue drains" is satisfied by never adding a task. A date is not.

Usage:  python3 tools/check_produced_artifact.py [--root DIR]
Exit 0 + "GREEN: ..." when all five hold; exit 1 + one line per condition otherwise.
Stdlib only, offline.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

CONTRACT = "config/produced-artifact-contract.json"

#: Rust sources searched for the scheduler entry point condition 4 names. Condition 4 will not
#: believe a run row citing `run_due` unless a `fn run_due` is actually defined in the tree.
RUST_ROOT = "apps/desktop/src-tauri"

#: `verb: argument` — the entire grammar of `automations.action` today. Condition 1 refuses an
#: "artifact" that is only this string, because that shape is what already exists and what the
#: production half is supposed to replace.
VERB_ARG_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_-]*\s*:\s*\S")

#: A grant that lives here, or a writer that names one of these, is a grant stated in prose.
PROMPTISH_RE = re.compile(r"(^|/)prompts?(/|$)|\.(md|markdown|txt|prompt)$", re.IGNORECASE)

_JSON_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "number": (int, float), "integer": int, "null": type(None),
}


class Condition:
    """One of the five, with the single line it prints whether it holds or not."""

    def __init__(self, number: int, title: str) -> None:
        self.number = number
        self.title = title
        self.ok = False
        self.detail = "not evaluated"

    def fail(self, detail: str) -> None:
        self.ok, self.detail = False, detail

    def passes(self, detail: str) -> None:
        self.ok, self.detail = True, detail

    def line(self) -> str:
        mark = "MET    " if self.ok else "MISSING"
        return f"  {self.number}. {mark} — {self.title}: {self.detail}"


def _git_tracked(root: pathlib.Path, rel: str) -> bool | None:
    """True/False when git can answer, None when it cannot (a temp dir, no git binary).

    None is not a failure. A synthetic tree under /tmp is not a repository, and refusing to
    evaluate there would make the GREEN case untestable — which is the state this whole file
    exists to argue against.
    """
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "--", rel],
                             capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return None
    if out.returncode != 0:
        return None
    return bool((out.stdout or "").strip())


def _load_json(path: pathlib.Path):
    """Parsed JSON, or a string describing why not. Callers distinguish by isinstance."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return f"unreadable ({exc})"
    except ValueError as exc:
        return f"not readable JSON ({exc})"


def _load_jsonl(path: pathlib.Path):
    """List of parsed rows, or a string describing why not."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"unreadable ({exc})"
    rows = []
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            rows.append(json.loads(raw))
        except ValueError as exc:
            return f"line {n} is not readable JSON ({exc})"
    return rows


def _declared(contract: dict, *keys: str):
    """The contract value at a dotted location, or None when it is null/absent/blank."""
    node = contract
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if isinstance(node, str) and not node.strip():
        return None
    return node


def _resolve_inside(base: pathlib.Path, rel: str) -> pathlib.Path | None:
    """`base/rel`, or None when it escapes `base`. A flow or grant reference that climbs out
    of its own artifact directory is not part of the artifact."""
    try:
        candidate = (base / rel).resolve()
        candidate.relative_to(base.resolve())
    except (ValueError, OSError):
        return None
    return candidate


def _schema_problems(manifest: dict, schema: dict) -> list[str]:
    """PARTIAL validation: `required` presence, and the declared `type` of present properties.

    Deliberately not a JSON Schema implementation. Named as partial here and in the docstring
    so nobody reads a GREEN from it as full conformance.
    """
    problems: list[str] = []
    required = schema.get("required")
    if not isinstance(required, list) or not required:
        return ["the schema declares no non-empty `required` list, so it defines nothing"]
    for name in required:
        if name not in manifest:
            problems.append(f"missing required field `{name}`")
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, spec in properties.items():
            if name not in manifest or not isinstance(spec, dict):
                continue
            declared = spec.get("type")
            expected = _JSON_TYPES.get(declared) if isinstance(declared, str) else None
            if expected is None:
                continue
            value = manifest[name]
            if expected is not bool and isinstance(value, bool):
                problems.append(f"`{name}` is a boolean where the schema declares {declared}")
            elif not isinstance(value, expected):
                problems.append(f"`{name}` is {type(value).__name__} where the schema declares {declared}")
    return problems


def _find_artifact(root: pathlib.Path, contract: dict, c1: Condition):
    """Evaluate condition 1 and return (artifact_dir, manifest) when it holds, else (None, None)."""
    store_rel = _declared(contract, "store_root")
    if store_rel is None:
        c1.fail(f"{CONTRACT} declares no `store_root` — there is no produced-agent store, and "
                "no decision yet about where one would live")
        return None, None
    store = root / str(store_rel)
    if not store.is_dir():
        c1.fail(f"`{store_rel}` does not exist — the store is declared and nothing has produced it")
        return None, None
    tracked = _git_tracked(root, str(store_rel))
    if tracked:
        c1.fail(f"`{store_rel}` is tracked in git — a committed fixture is a fixture, not a "
                "product; this evidence must be produced by a run")
        return None, None

    manifest_name = _declared(contract, "manifest_filename")
    if manifest_name is None:
        c1.fail(f"{CONTRACT} declares no `manifest_filename` — nothing says what an artifact's "
                "index file is called")
        return None, None

    candidates = sorted(d for d in store.iterdir() if d.is_dir() and (d / str(manifest_name)).is_file())
    if not candidates:
        c1.fail(f"`{store_rel}` holds no directory containing `{manifest_name}` — the store "
                "exists and is empty of artifacts")
        return None, None

    artifact = candidates[0]
    manifest = _load_json(artifact / str(manifest_name))
    if isinstance(manifest, str):
        c1.fail(f"`{artifact.name}/{manifest_name}` is {manifest}")
        return None, None
    if not isinstance(manifest, dict):
        c1.fail(f"`{artifact.name}/{manifest_name}` is a {type(manifest).__name__}, not an object")
        return None, None

    substantive = {k: v for k, v in manifest.items() if not k.endswith("_help")}
    if set(substantive) <= {"action"} and isinstance(manifest.get("action"), str) \
            and VERB_ARG_RE.match(manifest["action"]):
        c1.fail(f"`{artifact.name}` carries only `action: {manifest['action']!r}` — that is the "
                "`verb: argument` string `automations.action` already holds, which the Owner's "
                "condition 1 excludes by name")
        return None, None

    schema_rel = _declared(contract, "artifact_schema")
    if schema_rel is None:
        c1.fail(f"an artifact exists at `{store_rel}/{artifact.name}` but {CONTRACT} declares no "
                "`artifact_schema`, so its schema is undefined and condition 1 says DEFINED")
        return None, None
    schema_path = root / str(schema_rel)
    if not schema_path.is_file():
        c1.fail(f"the declared schema `{schema_rel}` does not exist")
        return None, None
    schema = _load_json(schema_path)
    if isinstance(schema, str) or not isinstance(schema, dict):
        c1.fail(f"the declared schema `{schema_rel}` is {schema if isinstance(schema, str) else 'not an object'}")
        return None, None
    problems = _schema_problems(manifest, schema)
    if problems:
        c1.fail(f"`{artifact.name}/{manifest_name}` does not satisfy `{schema_rel}`: "
                + "; ".join(problems))
        return None, None

    c1.passes(f"`{store_rel}/{artifact.name}` satisfies `{schema_rel}` (partial validation: "
              f"required fields present, declared types match)")
    return artifact, manifest


def _check_flow(contract: dict, artifact, manifest, c2: Condition) -> None:
    # The contract locators are checked BEFORE the dependency on condition 1, so that every one
    # of the five lines says something about ITSELF. Five copies of "condition 1 is not met"
    # would be true and useless, and this output is the deliverable.
    key = _declared(contract, "manifest_keys", "flow")
    if key is None:
        c2.fail(f"{CONTRACT} declares no `manifest_keys.flow` — nothing says where an "
                "artifact's flow is named")
        return
    steps_key_declared = _declared(contract, "flow_steps_key")
    if steps_key_declared is None:
        c2.fail(f"{CONTRACT} declares no `flow_steps_key` — nothing says what a step list is called")
        return
    if artifact is None:
        c2.fail("no artifact to carry a flow — condition 1 is not met")
        return
    ref = manifest.get(key)
    if not isinstance(ref, str) or not ref.strip():
        c2.fail(f"the manifest carries no `{key}` — the artifact declares no flow at all")
        return
    path = _resolve_inside(artifact, ref)
    if path is None or not path.is_file():
        c2.fail(f"the manifest's `{key}` names `{ref}`, which is not a file inside the artifact")
        return
    flow = _load_json(path)
    if isinstance(flow, str) or not isinstance(flow, dict):
        c2.fail(f"`{ref}` is {flow if isinstance(flow, str) else 'not an object'}")
        return
    steps_key = _declared(contract, "flow_steps_key")
    if steps_key is None:
        c2.fail(f"{CONTRACT} declares no `flow_steps_key` — nothing says what a step list is called")
        return
    steps = flow.get(steps_key)
    if not isinstance(steps, list):
        c2.fail(f"`{ref}` has no list at `{steps_key}` — a flow with no steps is not a flow")
        return
    if len(steps) <= 1:
        c2.fail(f"`{ref}` has {len(steps)} step(s); condition 2 requires more than one, because "
                "a single step is the one-shot action that already exists")
        return
    c2.passes(f"`{ref}` carries {len(steps)} steps")


def _check_grant(contract: dict, artifact, manifest, c3: Condition) -> None:
    key = _declared(contract, "manifest_keys", "grant")
    if key is None:
        c3.fail(f"{CONTRACT} declares no `manifest_keys.grant` — nothing says where an "
                "artifact's grant is named")
        return
    axes_declared = _declared(contract, "grant_axis_keys")
    if not isinstance(axes_declared, list) or not axes_declared:
        c3.fail(f"{CONTRACT} declares no `grant_axis_keys` — nothing says what a grant grants")
        return
    if _declared(contract, "grant_writer_key") is None:
        c3.fail(f"{CONTRACT} declares no `grant_writer_key` — nothing records which runtime "
                "component wrote the grant, so `written by the runtime` is unverifiable")
        return
    if artifact is None:
        c3.fail("no artifact to carry a grant — condition 1 is not met")
        return
    ref = manifest.get(key)
    if not isinstance(ref, str) or not ref.strip():
        c3.fail(f"the manifest carries no `{key}` — the artifact declares no grant, and an "
                "absent grant is a refusal, never `unrestricted`")
        return
    if PROMPTISH_RE.search(ref):
        c3.fail(f"the grant is `{ref}` — a prompt or a document. A grant present only in a "
                "prompt is prose, and condition 3 excludes it by name")
        return
    path = _resolve_inside(artifact, ref)
    if path is None or not path.is_file():
        c3.fail(f"the manifest's `{key}` names `{ref}`, which is not a file inside the artifact")
        return
    grant = _load_json(path)
    if isinstance(grant, str) or not isinstance(grant, dict):
        c3.fail(f"`{ref}` is {grant if isinstance(grant, str) else 'not an object'}")
        return

    axes = _declared(contract, "grant_axis_keys")
    if not isinstance(axes, list) or not axes:
        c3.fail(f"{CONTRACT} declares no `grant_axis_keys` — nothing says what a grant grants")
        return
    filled = [a for a in axes if grant.get(a) not in (None, [], {}, "")]
    if not filled:
        c3.fail(f"`{ref}` is empty on every declared axis ({', '.join(map(str, axes))}) — a "
                "grant that grants nothing was written by nobody")
        return

    writer_key = _declared(contract, "grant_writer_key")
    if writer_key is None:
        c3.fail(f"{CONTRACT} declares no `grant_writer_key` — nothing records which runtime "
                "component wrote the grant, so `written by the runtime` is unverifiable")
        return
    writer = grant.get(writer_key)
    if not isinstance(writer, str) or not writer.strip():
        c3.fail(f"`{ref}` carries no `{writer_key}` — the grant does not say what wrote it")
        return
    if PROMPTISH_RE.search(writer):
        c3.fail(f"`{ref}` records its writer as `{writer}` — a prompt or a document wrote it, "
                "which is condition 3's exact exclusion")
        return
    c3.passes(f"`{ref}` grants on {', '.join(map(str, filled))}, written by `{writer}`")


def _run_due_defined(root: pathlib.Path) -> bool:
    rust = root / RUST_ROOT
    if not rust.is_dir():
        return False
    for path in rust.rglob("*.rs"):
        try:
            if re.search(r"\bfn\s+run_due\b", path.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def _check_run(root: pathlib.Path, contract: dict, artifact, manifest, c4: Condition):
    """Evaluate condition 4; return the matching run row's id when it holds, else None."""
    invoked_by_value = _declared(contract, "run_invoked_by") or "run_due"
    if not _run_due_defined(root):
        c4.fail(f"no `fn run_due` is defined under `{RUST_ROOT}` — a run row citing "
                f"`{invoked_by_value}` would name a function that does not exist")
        return None
    runs_rel = _declared(contract, "runs_path")
    if runs_rel is None:
        c4.fail(f"{CONTRACT} declares no `runs_path` — no run log exists and no decision says "
                "where one would live")
        return None
    if artifact is None:
        c4.fail("no artifact for a run to have invoked — condition 1 is not met")
        return None
    runs_path = root / str(runs_rel)
    if not runs_path.is_file():
        c4.fail(f"`{runs_rel}` does not exist — `run_due()` has invoked nothing")
        return None
    if _git_tracked(root, str(runs_rel)):
        c4.fail(f"`{runs_rel}` is tracked in git — a committed run log records no run")
        return None
    rows = _load_jsonl(runs_path)
    if isinstance(rows, str):
        c4.fail(f"`{runs_rel}` is {rows}")
        return None

    keys = {name: _declared(contract, "run_keys", name) for name in ("run_id", "artifact_id", "invoked_by")}
    undeclared = sorted(n for n, v in keys.items() if v is None)
    if undeclared:
        c4.fail(f"{CONTRACT} declares no `run_keys.{'`, `run_keys.'.join(undeclared)}` — a run "
                "row cannot be read without knowing what its fields are called")
        return None

    id_key = _declared(contract, "manifest_keys", "artifact_id")
    if id_key is None:
        c4.fail(f"{CONTRACT} declares no `manifest_keys.artifact_id` — nothing connects a run "
                "row to the artifact it ran")
        return None
    artifact_id = manifest.get(id_key)
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        c4.fail(f"the manifest carries no `{id_key}`, so no run row can reference this artifact")
        return None

    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get(keys["artifact_id"]) != artifact_id:
            continue
        if row.get(keys["invoked_by"]) != invoked_by_value:
            continue
        run_id = row.get(keys["run_id"])
        if isinstance(run_id, str) and run_id.strip():
            c4.passes(f"`{runs_rel}` records run `{run_id}` of `{artifact_id}`, invoked by "
                      f"`{invoked_by_value}`")
            return run_id
    c4.fail(f"`{runs_rel}` holds {len(rows)} row(s) and none of them is `{invoked_by_value}` "
            f"invoking `{artifact_id}`")
    return None


def _check_receipt(root: pathlib.Path, contract: dict, run_id, c5: Condition) -> None:
    receipts_rel = _declared(contract, "receipts_path")
    if receipts_rel is None:
        c5.fail(f"{CONTRACT} declares no `receipts_path` — no receipt store exists and no "
                "decision says where one would live")
        return
    if run_id is None:
        c5.fail("no run to have a receipt — condition 4 is not met")
        return
    path = root / str(receipts_rel)
    if not path.is_file():
        c5.fail(f"`{receipts_rel}` does not exist — the run produced no receipt")
        return
    if _git_tracked(root, str(receipts_rel)):
        c5.fail(f"`{receipts_rel}` is tracked in git — a committed receipt attests nothing")
        return
    rows = _load_jsonl(path)
    if isinstance(rows, str):
        c5.fail(f"`{receipts_rel}` is {rows}")
        return

    keys = {name: _declared(contract, "receipt_keys", name) for name in ("run_id", "enforcement_regime")}
    undeclared = sorted(n for n, v in keys.items() if v is None)
    if undeclared:
        c5.fail(f"{CONTRACT} declares no `receipt_keys.{'`, `receipt_keys.'.join(undeclared)}` — "
                "a receipt cannot be read without knowing what its fields are called")
        return

    seen = 0
    for row in rows:
        if not isinstance(row, dict) or row.get(keys["run_id"]) != run_id:
            continue
        seen += 1
        regime = row.get(keys["enforcement_regime"])
        if isinstance(regime, str) and regime.strip():
            c5.passes(f"`{receipts_rel}` has a receipt for run `{run_id}` carrying "
                      f"`{keys['enforcement_regime']}` = `{regime}`")
            return
    if seen:
        c5.fail(f"`{receipts_rel}` has {seen} receipt(s) for run `{run_id}` and none carries a "
                f"non-empty `{keys['enforcement_regime']}`")
    else:
        c5.fail(f"`{receipts_rel}` has no receipt for run `{run_id}`")


def evaluate(root: pathlib.Path) -> list[Condition]:
    """The five conditions, in the Owner's order, each with the one line it prints."""
    c1 = Condition(1, "a produced artifact with a defined schema")
    c2 = Condition(2, "its flow has more than one step")
    c3 = Condition(3, "it carries a runtime-written grant")
    c4 = Condition(4, "run_due() has invoked it and a run row exists")
    c5 = Condition(5, "a receipt for that run carries enforcement_regime")
    conditions = [c1, c2, c3, c4, c5]

    contract_path = root / CONTRACT
    contract = _load_json(contract_path)
    if isinstance(contract, str) or not isinstance(contract, dict):
        why = contract if isinstance(contract, str) else "not an object"
        for c in conditions:
            c.fail(f"{CONTRACT} is {why} — the gate reads its locators from that file and can "
                   "measure nothing without it")
        return conditions

    artifact, manifest = _find_artifact(root, contract, c1)
    _check_flow(contract, artifact, manifest, c2)
    _check_grant(contract, artifact, manifest, c3)
    run_id = _check_run(root, contract, artifact, manifest, c4)
    _check_receipt(root, contract, run_id, c5)
    return conditions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)

    conditions = evaluate(root)
    missing = [c for c in conditions if not c.ok]
    if not missing:
        print("GREEN: the production half is reachable — all five conditions hold. "
              + " ".join(f"({c.number}) {c.detail}" for c in conditions))
        return 0

    contract = _load_json(root / CONTRACT)
    producer = _declared(contract, "producer_command") if isinstance(contract, dict) else None

    print("RED: the production half does not exist yet. This gate is RED BY DESIGN until it "
          "does — it is not a job to rerun.", file=sys.stderr)
    print("", file=sys.stderr)
    print("When does a customer see something? When these five lines all read MET:", file=sys.stderr)
    for c in conditions:
        print(c.line(), file=sys.stderr)
    print("", file=sys.stderr)
    print(f"{len(missing)} of 5 outstanding. The locators are declared in {CONTRACT}; a null "
          "there means the implementation has not decided yet, and filling one in makes this "
          "gate go and look rather than go green.", file=sys.stderr)
    if producer:
        print(f"Evidence is produced by: {producer}", file=sys.stderr)
    else:
        print("No `producer_command` is declared, so nothing yet produces this evidence.",
              file=sys.stderr)
    print("This context is NOT in config/required-checks.json. That deferral is a DATED entry in "
          "config/deferred-enforcement.json, enforced by "
          "tools/check_repo_state.py::verify_deferred_enforcement — which runs inside a context "
          "that IS required, so the date has teeth.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
