#!/usr/bin/env python3
"""Nothing calls it — the recurring defect in this repository, made a CI gate.

**Why this gate exists.** Five separate times, something was implemented, shipped, reviewed
and believed, and nothing ever called it. A capability policy with no enforcement path. 262
agent definitions the app could not see. Two backend commands with no frontend wrapper. Five
engine security functions with zero callers. Every one of them READ as protection while doing
nothing, and every one was found by a human audit rather than by the build — because a gate
that checks a thing EXISTS cannot tell you the thing is REACHED.

So reachability is now a claim the build checks, in three places where the defect actually
landed:

  1. Every ``#[tauri::command]`` registered in ``apps/desktop/src-tauri/src/lib.rs`` is invoked
     from ``apps/desktop/src/**`` (production code, not only tests), or is declared in
     ``config/reachability-declarations.json`` WITH A WRITTEN REASON. Unreachable is often
     correct — a capability-denied command, a superseded sibling, a surface behind the
     governed wall. **Unreachable-and-undeclared is the defect**, because that is the state in
     which nobody knows which it is.
  2. Security-critical ``engine/runtime/**`` symbols — the ones
     ``docs/PHASE_10_PRODUCTION_ITEMS.md`` names — have a caller outside their own module and
     outside their own tests. ``assert_no_bytecode_shadow`` is the worked example: it exists,
     it is documented, it raises the right error, and it has never once been called.
  3. Every ``allow-*``/``deny-*`` grant in
     ``apps/desktop/src-tauri/capabilities/default.json`` corresponds to a registered command
     and vice versa — and an ``allow``-granted command with no caller is reported as what it
     is: invokable attack surface with no user.

It also refuses a ``#[tauri::command]`` that is DEFINED but never registered in
``generate_handler!`` — dead IPC code that reads like a working command.

WHAT THIS GATE CANNOT DETECT — read this before trusting it
-----------------------------------------------------------
This is a STATIC TEXT SCAN. It is not a call graph, not a type-checker, and not a proof.
Overstating a gate's coverage is the same lie one level up, so, precisely:

  * **Dynamic dispatch slips past it, in both directions.** A command invoked as
    ``invoke(commandName, …)`` where the name is computed, looked up in a table, or assembled
    from strings reads as UNREACHABLE (a false red, which the declarations file absorbs). A
    command name appearing in the argument position of any call — not just ``invoke`` — reads
    as REACHED (a false green). On the Python side ``getattr(mod, name)()``, dynamic import,
    and decorator/registry indirection are all invisible.
  * **It proves a reference exists, not that the reference runs.** Reachability here is ONE
    level deep, not transitive: a command called only from a function that nothing calls is
    green. An island of mutually-referencing dead code is green.
  * **It cannot tell whether a user can take the path.** A command wired to a button behind a
    feature flag that is off, or a code path that always throws first, is green.
  * **It says nothing about whether the callee does what it claims.** That is
    ``check_spec_references.py``'s job, and ultimately a human audit's.
  * **For the ``policy_flag`` kind it proves the flag is READ, never that it is SET.** Whether
    ``engine/.bro/policy.json`` actually enables it is residual item O-3, outside this gate.
  * **Scope is fixed:** frontend callers are searched only under ``apps/desktop/src/**``;
    Python callers only under ``engine/``, ``bridge/``, ``tools/``. A caller in another crate,
    another binary, a shell script, or a downstream repository is invisible.

What it DOES hold reliably: comments and block comments are stripped before matching, so a
mention in a comment is never a call; and test files are classified separately, so a symbol
whose only callers are its own tests is RED — which is exactly how ``assert_no_bytecode_shadow``
managed to look green.

stdlib only, no network. Run: ``python tools/check_reachability.py [--root DIR]``
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

DECLARATIONS = pathlib.Path("config") / "reachability-declarations.json"
LIB_RS = pathlib.Path("apps/desktop/src-tauri/src/lib.rs")
TAURI_SRC = pathlib.Path("apps/desktop/src-tauri/src")
DEFAULT_CAP = pathlib.Path("apps/desktop/src-tauri/capabilities/default.json")
FRONTEND_SRC = pathlib.Path("apps/desktop/src")
FRONTEND_SUFFIXES = (".ts", ".tsx")
PY_SCAN_DIRS = ("engine", "bridge", "tools")
SKIP_PARTS = {"node_modules", "target", ".git", "__pycache__", "dist"}
WORKFLOWS = pathlib.Path(".github/workflows")
#: A gate that no workflow executes is the uncalled-command defect one level up: it exists,
#: it is documented, it reads as protection, and it protects nothing. This is how
#: tools/check_i18n_parity.py came to be run by no job at all while the roadmap's status
#: board said i18n parity was "enforced in CI".
GATE_GLOB = "check_*.py"

#: Reason categories a declared-unreachable Tauri command may claim. The category alone is not
#: the reason — every entry must ALSO carry prose saying why, which is the whole point of the
#: file. `not-yet-wired` is deliberately available: an honest open gap is worth far more than a
#: fabricated justification, and it is the one category that must name where it is tracked.
COMMAND_REASONS = {
    "capability-denied",
    "superseded",
    "governed-wall",
    "backend-only",
    "not-yet-wired",
}
REASONS_NEEDING_TRACKING = {"not-yet-wired"}

ENGINE_EXPECTATIONS = {"must_have_caller", "declared_unreachable"}
ENGINE_KINDS = {"function", "policy_flag"}

#: A reason has to be a sentence someone thought about. These are the strings people type when
#: they want the gate to be quiet, and "unreachable, no reason given" is not a reason.
MIN_REASON_CHARS = 40
PLACEHOLDER_REASONS = {
    "", "-", "n/a", "na", "none", "todo", "tbd", "unknown", "unused", "dead code",
    "unreachable", "no reason", "no reason given", "not used", "wip", "?",
}


# --------------------------------------------------------------------------------------
# Source scanning
# --------------------------------------------------------------------------------------

def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def strip_c_comments(text: str) -> str:
    """Remove block and line comments. A mention in a comment is not a call — that distinction
    is load-bearing here, because the dead symbols in this repository are all well commented."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"(?m)//[^\n]*", " ", text)


def strip_py_comments(text: str) -> str:
    """Remove `# …`. Docstrings are left in place; the call-shaped match below (`name(`) is
    what keeps a prose mention of a function from counting as a call."""
    return re.sub(r"(?m)#[^\n]*", " ", text)


def registered_commands(root: pathlib.Path) -> set[str]:
    """Command fn names inside `generate_handler![ … ]`, under any module prefix."""
    text = _read(root / LIB_RS)
    match = re.search(r"generate_handler!\s*\[(.*?)\]\s*\)", text, re.DOTALL)
    if not match:
        raise SystemExit("RED: could not find generate_handler![ ... ] in lib.rs")
    body = re.sub(r"//[^\n]*", "", match.group(1))
    return set(re.findall(r"(?:[a-zA-Z_][a-zA-Z0-9_]*::)+([a-z0-9_]+)", body))


def defined_commands(root: pathlib.Path) -> dict[str, str]:
    """`#[tauri::command]`-annotated fn name -> the file defining it."""
    found: dict[str, str] = {}
    base = root / TAURI_SRC
    if not base.is_dir():
        return found
    for path in sorted(base.rglob("*.rs")):
        if SKIP_PARTS & set(path.parts):
            continue
        text = _read(path)
        for match in re.finditer(
            r"#\[tauri::command[^\]]*\]\s*(?:pub\s+)?(?:async\s+)?fn\s+([a-z0-9_]+)", text
        ):
            found.setdefault(match.group(1), path.relative_to(root).as_posix())
    return found


def is_frontend_test(path: pathlib.Path) -> bool:
    parts = path.as_posix()
    return (
        ".test." in path.name
        or ".spec." in path.name
        or "/src/test/" in parts
        or "/__tests__/" in parts
    )


def frontend_callers(
    root: pathlib.Path, commands: set[str]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(production, test) maps of command -> ["file:line", …].

    A command counts as CALLED only when its name appears as a string literal in the ARGUMENT
    POSITION of a call — `foo('cmd')` or `foo(x, 'cmd')`. That is what separates a real
    invocation from `const DENIED_DECIDE_COMMAND = 'decide_approval'`, which names a command
    precisely in order never to call it. See the module docstring: it also means any
    argument-position match counts, not only `invoke`.
    """
    production: dict[str, list[str]] = {}
    tests: dict[str, list[str]] = {}
    base = root / FRONTEND_SRC
    if not base.is_dir():
        return production, tests
    for path in sorted(base.rglob("*")):
        if path.suffix not in FRONTEND_SUFFIXES or SKIP_PARTS & set(path.parts):
            continue
        text = strip_c_comments(_read(path))
        target = tests if is_frontend_test(path) else production
        for match in re.finditer(r"""[(,]\s*['"`]([a-z0-9_]+)['"`]""", text):
            name = match.group(1)
            if name not in commands:
                continue
            line = text.count("\n", 0, match.start()) + 1
            target.setdefault(name, []).append(f"{path.relative_to(root).as_posix()}:{line}")
    return production, tests


def is_python_test(path: pathlib.Path) -> bool:
    return path.name.startswith("test_") or "tests" in path.parts


def python_files(root: pathlib.Path) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for top in PY_SCAN_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if SKIP_PARTS & set(path.parts):
                continue
            out.append(path)
    return sorted(out)


def read_via_binding_error(root: pathlib.Path, name: str, read_via: dict) -> str | None:
    """A declared one-hop indirection has to be TRUE at both ends, or it is just a story.

    `read_via` says "this flag is read through constant X, bound in file Y". The gate refuses
    to follow it unless Y really contains `X = "<flag>"` — otherwise a stale declaration could
    keep pointing the search at a constant that no longer holds the flag, and the gate would
    happily count references to something unrelated as reads of the flag.
    """
    constant = read_via.get("constant")
    bound_in = read_via.get("bound_in")
    if not isinstance(constant, str) or not constant:
        return f"engine symbol `{name}`: read_via needs a `constant` identifier"
    if not isinstance(bound_in, str) or not (root / bound_in).exists():
        return f"engine symbol `{name}`: read_via.bound_in {bound_in!r} does not exist"
    binding = re.compile(
        r"^\s*" + re.escape(constant) + r"""\s*(?::[^=\n]+)?=\s*['"]""" + re.escape(name)
        + r"""['"]""",
        re.MULTILINE,
    )
    if not binding.search(_read(root / bound_in)):
        return (
            f"engine symbol `{name}`: read_via claims it is read through `{constant}`, but "
            f"{bound_in} does not bind {constant} to {name!r}. The declared indirection is not "
            f"real — fix the declaration rather than letting the gate follow a dead pointer."
        )
    return None


def python_callers(
    root: pathlib.Path,
    files: list[pathlib.Path],
    name: str,
    kind: str,
    defined_in: str | None,
    read_via: dict | None = None,
) -> tuple[list[str], list[str]]:
    """(non-test callers, test-only callers) as "file:line" strings.

    `function` matches a CALL shape (`name(`), so a docstring mention or a bare re-export does
    not count. `policy_flag` matches the quoted key in a READ shape — argument or subscript
    position, `.get("name", …)` / `cfg["name"]` — because a config flag is "called" by being
    read, and because the bare quoted string also shows up in prose. (Caught live while writing
    this gate: the docstring of `verify_conductor_session_token` writes
    `"require_conductor_session_token": true` as an example, and a bare-literal match counted
    that as a reader. A mention is not a call, here too.)

    `read_via` follows exactly ONE declared hop of indirection — the flag literal bound to a
    named constant that the enforcement code actually reads — after verifying that binding is
    real (see `read_via_binding_error`). One hop, declared and verified, is the honest middle
    ground between a text scan and a call graph; anything deeper this gate does not claim.

    The defining module is excluded when one is declared — a symbol referencing itself inside
    its own file is exactly how a dead function reads as live.
    """
    if kind == "policy_flag":
        if read_via:
            constant = read_via["constant"]
            # Any reference to the constant EXCEPT its own assignment counts as a read.
            pattern = re.compile(r"\b" + re.escape(constant) + r"\b(?!\s*=[^=])")
        else:
            pattern = re.compile(r"""[(\[,]\s*['"]""" + re.escape(name) + r"""['"]""")
    else:
        pattern = re.compile(r"\b" + re.escape(name) + r"\s*\(")
    outside: list[str] = []
    only_tests: list[str] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if defined_in and rel == defined_in:
            continue
        text = strip_py_comments(_read(path))
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            (only_tests if is_python_test(path) else outside).append(f"{rel}:{line}")
    return outside, only_tests


def capability_grants(root: pathlib.Path) -> dict[str, str]:
    """command fn name -> 'allow' | 'deny' from capabilities/default.json (core:* ignored)."""
    doc = json.loads(_read(root / DEFAULT_CAP) or "{}")
    grants: dict[str, str] = {}
    for perm in doc.get("permissions", []):
        if perm.startswith("core:"):
            continue
        for kind in ("allow", "deny"):
            prefix = f"{kind}-"
            if perm.startswith(prefix):
                grants[perm[len(prefix):].replace("-", "_")] = kind
    return grants


def intentionally_ungated() -> set[str]:
    """Reuse `check_capabilities.INTENTIONALLY_UNGATED` rather than copy it — two lists of the
    same commands in two gates is itself a drift defect."""
    tools_dir = str(pathlib.Path(__file__).resolve().parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import check_capabilities  # noqa: E402  (deliberate: one source of truth for the list)

    return set(check_capabilities.INTENTIONALLY_UNGATED)


# --------------------------------------------------------------------------------------
# Declarations
# --------------------------------------------------------------------------------------

def load_declarations(root: pathlib.Path) -> dict:
    path = root / DECLARATIONS
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"RED: {DECLARATIONS.as_posix()} is missing")
    except ValueError as exc:
        raise SystemExit(f"RED: {DECLARATIONS.as_posix()} is malformed: {exc}")


def bad_reason(text: object) -> bool:
    if not isinstance(text, str):
        return True
    normalized = text.strip().rstrip(".").lower()
    return normalized in PLACEHOLDER_REASONS or len(text.strip()) < MIN_REASON_CHARS


def gate_modules(root: pathlib.Path) -> list[str]:
    """Every gate under tools/, as a repo-relative posix path."""
    return sorted(p.relative_to(root).as_posix() for p in (root / "tools").glob(GATE_GLOB))


def workflow_invocations(root: pathlib.Path) -> set[str]:
    """Gate paths mentioned by any workflow file.

    A text scan, like the rest of this gate: a workflow step that builds the command
    from a variable is invisible, which is a false RED the declarations file absorbs.
    """
    invoked: set[str] = set()
    directory = root / WORKFLOWS
    if not directory.is_dir():
        return invoked
    for workflow in sorted(directory.glob("*.y*ml")):
        text = _read(workflow)
        for gate in gate_modules(root):
            # The gate PATH, i.e. the job actually runs it against the tree. Running only its
            # self-tests deliberately does NOT count: a checker proven correct and never
            # pointed at the repository is the same nothing as a command with no caller.
            if gate in text:
                invoked.add(gate)
    return invoked


def tracking_path_missing(root: pathlib.Path, tracked_by: object) -> bool:
    if not isinstance(tracked_by, str) or not tracked_by.strip():
        return True
    # "docs/FILE.md §Section" -> "docs/FILE.md"
    head = tracked_by.split("§")[0].split("#")[0].strip()
    return not head or not (root / head).exists()


# --------------------------------------------------------------------------------------
# The check
# --------------------------------------------------------------------------------------

def check(root: pathlib.Path) -> tuple[list[str], dict]:
    problems: list[str] = []
    declarations = load_declarations(root)
    declared_commands = declarations.get("tauri_commands", {})
    declared_symbols = declarations.get("engine_symbols", {})

    registered = registered_commands(root)
    defined = defined_commands(root)
    grants = capability_grants(root)
    ungated = intentionally_ungated()
    production, tests = frontend_callers(root, registered)

    # --- 0) a command defined but never registered is dead IPC code -------------------------
    for name, where in sorted(defined.items()):
        if name not in registered:
            problems.append(
                f"command `{name}` is defined with #[tauri::command] in {where} but is NOT in "
                f"generate_handler![ ... ] in {LIB_RS.as_posix()}. Nothing can invoke it; "
                f"either register it or delete it."
            )
    for name in sorted(registered - set(defined)):
        problems.append(
            f"command `{name}` is registered in generate_handler! but no #[tauri::command] fn "
            f"of that name was found under {TAURI_SRC.as_posix()}."
        )

    # --- 1) every registered command is reached, or declared with a written reason -----------
    unreached = sorted(registered - set(production))
    for name in unreached:
        entry = declared_commands.get(name)
        grant = grants.get(name, "ungranted")
        test_only = f"; referenced ONLY from tests: {tests[name][:2]}" if name in tests else ""
        if entry is None:
            problems.append(
                f"command `{name}` is registered ({grant}-granted) and nothing under "
                f"{FRONTEND_SRC.as_posix()}/** invokes it{test_only}. Undeclared-and-"
                f"unreachable is the defect this gate exists for: either wire it, or declare it "
                f"in {DECLARATIONS.as_posix()} with a reason ({sorted(COMMAND_REASONS)}) and a "
                f"note saying why."
            )
            continue
        reason = entry.get("reason")
        note = entry.get("note")
        if reason not in COMMAND_REASONS:
            problems.append(
                f"command `{name}`: reason {reason!r} is not one of {sorted(COMMAND_REASONS)}"
            )
        if bad_reason(note):
            problems.append(
                f"command `{name}`: `note` must say WHY in at least {MIN_REASON_CHARS} "
                f"characters of real prose; got {note!r}. 'unreachable, no reason given' is not "
                f"a reason."
            )
        if reason in REASONS_NEEDING_TRACKING and tracking_path_missing(
            root, entry.get("tracked_by")
        ):
            problems.append(
                f"command `{name}`: reason {reason!r} is an OPEN gap, so `tracked_by` must name "
                f"a file that exists; got {entry.get('tracked_by')!r}."
            )
        if reason == "capability-denied" and grants.get(name) != "deny":
            problems.append(
                f"command `{name}` claims reason 'capability-denied' but "
                f"{DEFAULT_CAP.as_posix()} grants it {grants.get(name)!r}. The declared reason "
                f"must be the real one."
            )

    # --- 2) declarations must not rot --------------------------------------------------------
    for name in sorted(declared_commands):
        if name not in registered:
            problems.append(
                f"{DECLARATIONS.as_posix()} declares `{name}`, which is no longer registered in "
                f"generate_handler!. Delete the stale entry."
            )
        elif name in production:
            problems.append(
                f"`{name}` is declared unreachable but IS now invoked from {production[name][0]}. "
                f"Good — delete its entry from {DECLARATIONS.as_posix()} so the file keeps "
                f"meaning what it says."
            )

    # --- 3) capability grants <-> registered commands ----------------------------------------
    for name in sorted(set(grants) - registered):
        problems.append(
            f"{DEFAULT_CAP.as_posix()} grants `{grants[name]}-{name.replace('_', '-')}` but no "
            f"such command is registered in generate_handler!. A grant for a command that does "
            f"not exist is policy nobody enforces."
        )
    for name in sorted(registered - set(grants) - ungated):
        problems.append(
            f"command `{name}` is registered but has no allow-*/deny-* entry in "
            f"{DEFAULT_CAP.as_posix()} and is not in check_capabilities.INTENTIONALLY_UNGATED."
        )

    # --- 4) declared security-critical engine symbols ----------------------------------------
    py_files = python_files(root)
    engine_state: dict[str, dict] = {}
    for name in sorted(declared_symbols):
        entry = declared_symbols[name]
        kind = entry.get("kind")
        expectation = entry.get("expectation")
        defined_in = entry.get("defined_in")
        if kind not in ENGINE_KINDS:
            problems.append(
                f"engine symbol `{name}`: kind {kind!r} not in {sorted(ENGINE_KINDS)}"
            )
            continue
        if expectation not in ENGINE_EXPECTATIONS:
            problems.append(
                f"engine symbol `{name}`: expectation {expectation!r} not in "
                f"{sorted(ENGINE_EXPECTATIONS)}"
            )
            continue
        if defined_in is not None:
            if not (root / defined_in).exists():
                problems.append(
                    f"engine symbol `{name}`: defined_in {defined_in!r} does not exist"
                )
                continue
            if name not in _read(root / defined_in):
                problems.append(
                    f"engine symbol `{name}`: {defined_in} does not contain it — the declaration "
                    f"has rotted away from the code."
                )
                continue
        read_via = entry.get("read_via")
        if read_via is not None:
            if kind != "policy_flag":
                problems.append(
                    f"engine symbol `{name}`: read_via is only meaningful for a policy_flag"
                )
                continue
            binding_error = read_via_binding_error(root, name, read_via)
            if binding_error:
                problems.append(binding_error)
                continue
        outside, only_tests = python_callers(root, py_files, name, kind, defined_in, read_via)
        engine_state[name] = {
            "callers": outside,
            "test_callers": only_tests,
            "expectation": expectation,
        }
        if expectation == "must_have_caller" and not outside:
            hint = (
                f" It is referenced ONLY by tests ({only_tests[:2]}), which is not a caller — "
                f"that is exactly how a dead security function reads as green."
                if only_tests
                else ""
            )
            problems.append(
                f"security-critical engine symbol `{name}` is declared must_have_caller and has "
                f"ZERO callers outside {defined_in or 'its own definition'} and its tests.{hint}"
            )
        if expectation == "declared_unreachable":
            if bad_reason(entry.get("reason")):
                problems.append(
                    f"engine symbol `{name}`: declared_unreachable needs at least "
                    f"{MIN_REASON_CHARS} characters saying why; got {entry.get('reason')!r}."
                )
            if not entry.get("residual_item") and tracking_path_missing(
                root, entry.get("tracked_by")
            ):
                problems.append(
                    f"engine symbol `{name}`: declared_unreachable must name the residual item "
                    f"(`residual_item`, e.g. O-1) or an existing `tracked_by` file."
                )
            if outside:
                problems.append(
                    f"engine symbol `{name}` is declared unreachable but now HAS a caller "
                    f"({outside[0]}). Good — flip its expectation to must_have_caller so the gate "
                    f"starts protecting the new caller instead of excusing its absence."
                )

    # --- 5) every gate under tools/ is actually EXECUTED by a workflow ----------------------
    # The same defect as an uncalled command, one level up. Added rather than given its own
    # module on purpose: a second gate would have duplicated the declarations file, the
    # reason-quality rules and the declaration-rot rule that already live here, which is the
    # "do not build what exists" rule broken while implementing it.
    declared_gates = declarations.get("tools_gates", {})
    if not isinstance(declared_gates, dict):
        problems.append(f"{DECLARATIONS.as_posix()}: 'tools_gates' must be an object")
        declared_gates = {}
    declared_gates = {k: v for k, v in declared_gates.items() if not k.startswith("$")}
    invoked_gates = workflow_invocations(root)
    all_gates = gate_modules(root)
    for gate in all_gates:
        if gate in invoked_gates:
            if gate in declared_gates:
                problems.append(
                    f"gate `{gate}` is declared un-run in {DECLARATIONS.as_posix()} but IS "
                    f"executed by a workflow. Delete the entry — an exception must not outlive "
                    f"the condition it described."
                )
            continue
        entry = declared_gates.get(gate)
        if entry is None:
            problems.append(
                f"gate `{gate}` is executed by NO workflow under {WORKFLOWS.as_posix()}/. A check "
                f"nobody runs is not a check; it is a file that resembles one. Wire it into a "
                f"workflow, or declare it in {DECLARATIONS.as_posix()} under 'tools_gates' with a "
                f"written reason."
            )
        elif bad_reason(entry.get("reason")):
            problems.append(
                f"gate `{gate}`: an un-run gate needs at least {MIN_REASON_CHARS} characters "
                f"saying why nothing runs it; got {entry.get('reason')!r}."
            )
    for gate in sorted(set(declared_gates) - set(all_gates)):
        problems.append(
            f"{DECLARATIONS.as_posix()}: 'tools_gates' declares `{gate}`, which does not exist."
        )

    summary = {
        "registered": len(registered),
        "reached": len(registered) - len(unreached),
        "declared_commands": len(declared_commands),
        "grants": len(grants),
        "ungated": len(ungated),
        "engine": engine_state,
        "gates": len(all_gates),
        "gates_run": len(invoked_gates),
    }
    return problems, summary


LIMITS = (
    "LIMITS (this gate is a static text scan, not a call graph):\n"
    "  - dynamic dispatch is invisible, in both directions: a computed `invoke(name, ...)` reads\n"
    "    as unreachable, and any argument-position string literal reads as reached even when the\n"
    "    call is not `invoke`; on the Python side getattr / registry / dynamic-import\n"
    "    indirection is not seen at all.\n"
    "  - reachability is ONE level deep, not transitive: a caller that nothing itself calls still\n"
    "    counts, so an island of mutually-referencing dead code passes.\n"
    "  - it cannot tell whether a user can reach the path (feature flags, an earlier throw).\n"
    "  - it says nothing about whether the callee does what it claims.\n"
    "  - indirection is followed for exactly ONE declared, verified hop (`read_via`) and no\n"
    "    further; a constant reached through a second constant reads as unreachable, and any\n"
    "    reference to a declared read_via constant counts as a read.\n"
    "  - `policy_flag` symbols are proven READ, never proven SET in engine/.bro/policy.json.\n"
    "  - scope is fixed: frontend apps/desktop/src/** only; python engine/, bridge/, tools/ only.\n"
    "  What it does hold: comments are stripped (a mention is not a call), and test-only callers\n"
    "  do not count (that is precisely how a dead security function read as green)."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reachability gate: nothing ships unreached AND undeclared."
    )
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()

    problems, summary = check(root)
    if problems:
        print("RED: something is implemented and nothing calls it -")
        for problem in problems:
            print(f"  - {problem}")
        print(f"\n{len(problems)} problem(s).\n")
        print(LIMITS)
        return 1

    engine = summary["engine"]
    live = sorted(n for n, s in engine.items() if s["expectation"] == "must_have_caller")
    dead = sorted(n for n, s in engine.items() if s["expectation"] == "declared_unreachable")
    print(
        f"GREEN: {summary['reached']}/{summary['registered']} registered Tauri commands are "
        f"invoked from apps/desktop/src/**; the remaining "
        f"{summary['registered'] - summary['reached']} are declared with written reasons in "
        f"{DECLARATIONS.as_posix()} ({summary['declared_commands']} entries). "
        f"{summary['grants']} capability grants correspond to registered commands "
        f"({summary['ungated']} commands intentionally ungated)."
    )
    print(
        f"       engine security symbols: {len(live)} enforced with a real caller; "
        f"{len(dead)} declared caller-less against a named residual item."
    )
    for name in dead:
        print(f"         - {name}: ZERO callers, observed by THIS run (declared_unreachable).")
    for name in live:
        print(f"         + {name}: caller {engine[name]['callers'][0]}")
    print()
    print(LIMITS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
