"""Live / integration traceability validator (Execution Surface kind=validator, live).

The static validator (bro_traceability) may emit at most STATIC_PROVEN. This module
discharges the LIVE_PROVEN obligations OLTS defers to integration:

  * runtime prerequisites actually resolve in the live environment,
  * each law's bound allow AND deny test cases actually pass when executed through
    the WIRED interpreter named in .claude/settings.json (not sys.executable),
  * a law with a hook-kind primary surface additionally requires the live wired
    hook command to deny FOR THE EXPECTED CAUSE (the anti-dead-wiring proof).

A law is derived ENFORCED only when every required link is LIVE_PROVEN; otherwise it
stays STATIC_ONLY. Nothing is asserted -- status is computed from real runs
(Verifiability MP-11).

Two things a passing test cannot establish, and which this module therefore does not
let a passing test stand in for (T-153):

  * that the surface a record NAMES exists. Every declared execution surface must
    resolve to a definition; a record pointing at a function that was renamed or
    deleted is not enforced by it, however green the tests bound beside it are.
  * that a law the record itself declares ADVISORY is enforced. A record whose
    failure_behavior.class is ADVISORY_OBSERVATION says, in the registry's own
    vocabulary, that nothing normative enforces the law today (L13: its validator
    exists and is tested, and no promotion flow calls it). Such a law is derived
    NOT_ENFORCED and never LIVE_PROVEN, is named on the last line, and is not counted
    among the enforced. Its bound cases must still pass -- exactly the condition that
    used to print ENFORCED for it -- so declaring a law advisory admits nothing that
    was refused before; it only stops the report calling it something it is not.

Negatives must assert WHY, not merely THAT (the rule ci/live/run_live_turn.sh spells
out in `expect_blocked`). This probe used to accept ANY denial, and the O-1 bytecode
gate showed what that costs: once `assert_no_bytecode_shadow` began refusing on a
__pycache__ under a digest root, a `compileall` run BEFORE this validator made the
wall refuse for the cache instead of for the scope -- and the probe stayed green
while proving something else entirely. So this module now (a) refuses to run the
proof at all under a bytecode shadow, and (b) requires the refusal it does observe
to name `missing BRO_WORKSPACE_BINDING`.

Run it with `python -B`: without the flag the import of the runtime modules below
mints the very __pycache__ that (a) refuses on, before validate_live can run.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "runtime"))

from bro_env_health import check_environment
from bro_protected import (WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT,
                           WRITABLE_CONTROL_PLANE_ENV,
                           bytecode_shadow_offenders, load_protected_manifest)
from bro_traceability import load_runtime_dependencies, symbol_defined

# The exact cause the anti-dead-wiring negative exists to demonstrate: the wall
# refusing an action whose scope cannot be proven. Any OTHER refusal -- a missing
# session-state directory, a bytecode shadow, a broken deployment -- is a green tick
# on a proof that was never taken.
WIRING_EXPECTED_CAUSE = "missing BRO_WORKSPACE_BINDING"


def wired_interpreter(root: pathlib.Path) -> str | None:
    # A malformed/absent settings.json means nothing is wired; treat it as no
    # interpreter (a clean RED via assurance_failures) rather than an uncaught traceback.
    try:
        settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
        token = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"].split()[0]
    except (OSError, json.JSONDecodeError, KeyError, IndexError, AttributeError):
        return None
    return shutil.which(token)


def wired_pretool_argv(root: pathlib.Path) -> list[str] | None:
    """The FIRST `||` alternative of the wired PreToolUse command, as a real argv.

    Resolving the whole command rather than only its interpreter token is what makes
    the proof below a proof about the WIRED wall: `-B` is part of the wiring (O-1),
    and a probe that dropped it would launch an interpreter that mints bytecode under
    a digest root -- i.e. manufacture the shadow whose refusal then masks the refusal
    under test.
    """
    try:
        settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
        command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    except (OSError, json.JSONDecodeError, KeyError, IndexError, AttributeError):
        return None
    try:
        tokens = shlex.split(str(command).split("||")[0].strip(), posix=True)
    except ValueError:
        return None
    if not tokens:
        return None
    interpreter = shutil.which(tokens[0])
    if interpreter is None:
        return None
    return [interpreter] + [t.replace("$CLAUDE_PROJECT_DIR", str(root)) for t in tokens[1:]]


def wired_hook_refusal(root: pathlib.Path, argv: list[str]) -> tuple[str, str]:
    """Run the WIRED PreToolUse command on an out-of-scope action; return
    (permissionDecision, permissionDecisionReason) verbatim, so the caller can
    require the refusal to name its cause instead of counting it.
    """
    with tempfile.TemporaryDirectory(prefix="bro-live-wire-") as state_dir:
        env = {k: v for k, v in os.environ.items() if k != "BRO_WORKSPACE_BINDING"}
        env["BRO_MODE"] = "review"
        # The freeze gate is evaluated BEFORE the workspace gate, so a probe run with
        # no session-state directory is refused for the missing directory and never
        # reaches the scope check it claims to prove. Hand it a real, empty one: the
        # ONLY thing missing from this environment must be the workspace binding.
        env["BRO_SESSION_STATE_DIR"] = str(pathlib.Path(state_dir).resolve())
        # Same shape, one gate along. A CI checkout is writable by the account running it and
        # cannot be otherwise, so the O-1 read-half gate fires first and the probe is refused for
        # a writable control plane — never reaching the scope check it exists to prove. That is
        # exactly the masking this file already guards against for bytecode, so it is handled the
        # same way: acknowledge it HERE, for this one probe, and say so in the output. It is not a
        # weakening — the acknowledgement is scoped to a subprocess whose only job is to observe
        # which refusal the wired hook produces, and `assert_control_plane_not_writable` still
        # governs every real enforcement path.
        env[WRITABLE_CONTROL_PLANE_ENV] = WRITABLE_CONTROL_PLANE_ACKNOWLEDGEMENT
        result = subprocess.run(
            argv,
            input=json.dumps({
                "session_id": "live-wire",
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
                "tool_use_id": "toolu_wire",
            }),
            text=True, capture_output=True, cwd=str(root), env=env,
        )
    if result.returncode != 0:
        return "", (f"the wired hook exited {result.returncode}: "
                    f"{(result.stderr or '').strip()[:400]}")
    for line in reversed(result.stdout.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            block = payload.get("hookSpecificOutput") or {}
            return (str(block.get("permissionDecision") or ""),
                    str(block.get("permissionDecisionReason") or ""))
    return "", f"the wired hook printed no decision: {result.stdout.strip()[:400]}"


def _class_of_case(root: pathlib.Path, rel_file: str, case: str) -> str | None:
    tree = ast.parse((root / rel_file).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == case:
                    return node.name
    return None


def run_case(root: pathlib.Path, interpreter: str, rel_file: str, case: str) -> bool:
    cls = _class_of_case(root, rel_file, case)
    if cls is None:
        return False
    module = pathlib.Path(rel_file).stem
    result = subprocess.run(
        # -B: importing a bound test case writes tests/__pycache__ -- under a digest
        # root -- and the very next thing this validator does is assert that the wall
        # refuses for SCOPE. Without the flag the probe plants the shadow that
        # changes its own answer.
        [interpreter, "-B", "-m", "unittest", f"{module}.{cls}.{case}"],
        cwd=str(root / "tests"), capture_output=True, text=True,
    )
    return result.returncode == 0


def live_wiring_denies(root: pathlib.Path, interpreter: str) -> bool:
    return (run_case(root, interpreter, "tests/test_live_hook_deny.py", "test_wired_interpreter_resolves_on_path")
            and run_case(root, interpreter, "tests/test_live_hook_deny.py", "test_wired_command_denies_out_of_scope"))


#: The registry's own word for a law nothing normative enforces. `bro_traceability` refuses it
#: on a MUST / MUST_NOT / SHALL record, so a law can carry it only by also giving up the claim.
ADVISORY_CLASS = "ADVISORY_OBSERVATION"


def declared_advisory(record: dict) -> bool:
    """True when the record itself says the law is not normatively enforced."""
    return (record.get("failure_behavior") or {}).get("class") == ADVISORY_CLASS


def derive_live_status(root: pathlib.Path, record: dict, *, prereq_ok: bool,
                       tests_ok: bool, wiring_ok: bool) -> dict:
    """One law's live status, from what was observed and what the record declares.

    Split out of `validate_live` so the derivation can be driven without launching the
    wired interpreter seventeen times: the three observations come in, the verdict goes
    out, and nothing here runs a subprocess.

    `bound_checks_pass` is the conjunction that used to be the whole of ENFORCED --
    prerequisites resolve, every bound case passes, and for a hook-primary law the wired
    hook denies for the expected cause -- now with one more term: every surface the record
    names resolves to a definition. A law whose record names a function that does not exist
    is not enforced by that function.

    ENFORCED / LIVE_PROVEN additionally requires that the record does not declare the law
    advisory. For such a law the status is NOT_ENFORCED whatever its tests say: they show
    what its validator would refuse, not that anything calls it.
    """
    surfaces = record["execution_surfaces"]
    has_hook = any(s["kind"] == "hook" and s["path_role"] == "primary" for s in surfaces)
    surfaces_defined = all(symbol_defined(root, s["module"], s["symbol"]) for s in surfaces)
    surface_ok = bool(tests_ok and surfaces_defined and (wiring_ok if has_hook else True))
    bound_checks_pass = bool(prereq_ok and tests_ok and surface_ok)
    advisory = declared_advisory(record)
    enforced = bound_checks_pass and not advisory
    if advisory:
        status = "NOT_ENFORCED"
    else:
        status = "ENFORCED" if enforced else "STATIC_ONLY"
    return {
        "id": record["id"],
        "enforcement_status": status,
        "effective_proof_level": "LIVE_PROVEN" if enforced else "STATIC_PROVEN",
        "declared_advisory": advisory,
        "bound_checks_pass": bound_checks_pass,
        "live": {"prereq": prereq_ok, "tests": tests_ok, "surface": surface_ok,
                 "surfaces_defined": surfaces_defined,
                 "hook_surface": has_hook, "wiring": wiring_ok},
    }


def validate_live(root: pathlib.Path = ROOT) -> dict:
    interpreter = wired_interpreter(root)
    # FIRST, before anything is run: a bytecode shadow under a digest root makes the
    # wall refuse for the shadow, so no refusal observed after this point can be
    # attributed to the property being probed. Recorded, not silently tolerated.
    shadow = bytecode_shadow_offenders(root, load_protected_manifest(root))

    argv = wired_pretool_argv(root)
    if argv is None:
        decision, reason = "", "no wired PreToolUse command resolves from .claude/settings.json"
    else:
        decision, reason = wired_hook_refusal(root, argv)
    # A negative that accepts ANY refusal certifies nothing about the check it names.
    wiring_ok = bool(
        not shadow
        and decision == "deny"
        and WIRING_EXPECTED_CAUSE in reason
        and interpreter is not None
        and live_wiring_denies(root, interpreter)
    )

    # Prerequisite resolution is a live, global fact.
    try:
        check_environment(root)
        prereq_ok = True
    except Exception:  # noqa: BLE001
        prereq_ok = False

    registry = json.loads((root / "laws" / "registry.json").read_text(encoding="utf-8"))
    records = [law for law in registry.get("laws", []) if isinstance(law, dict) and "responsibility" in law]

    derived = []
    for record in records:
        interp = interpreter or sys.executable
        tests_ok = all(run_case(root, interp, t["file"], t["case"]) for t in record["tests"])
        derived.append(derive_live_status(root, record, prereq_ok=prereq_ok,
                                          tests_ok=tests_ok, wiring_ok=wiring_ok))
    return {
        "wired_interpreter": interpreter,
        "wiring_denies": wiring_ok,
        "wiring_decision": decision,
        "wiring_reason": reason,
        "bytecode_shadow": shadow,
        "prerequisites_resolve": prereq_ok,
        "laws": len(records),
        "derived": derived,
    }


def assurance_failures(report: dict) -> list[str]:
    """Reasons the live-wiring assurance is NOT satisfied; empty means fully enforced.

    This is what turns the report from a description into a gate. A green report is not
    "the files exist" — it is: an interpreter is really wired, prerequisites really
    resolve, the wired hook really denies an out-of-scope action, and every law's
    allow/deny cases really pass through that interpreter. Anything short is dead
    wiring and must fail closed.
    """
    failures = []
    if report["wired_interpreter"] is None:
        failures.append("no wired interpreter resolves from .claude/settings.json")
    if not report["prerequisites_resolve"]:
        failures.append("runtime prerequisites do not resolve in the live environment")
    # Reported BEFORE the wiring failure, because it is the cause of it: under a
    # shadow the wall refuses for the cache, and the anti-dead-wiring negative would
    # otherwise read as a proof of enforcement it never took.
    if report["bytecode_shadow"]:
        failures.append(
            "compiled bytecode under a digest root masks the wiring proof: the wall "
            "refuses for the shadow, not for the scope this probe tests — run the "
            "live validation on a clean tree with `python -B` and place any "
            f"`compileall` AFTER it; offenders: {report['bytecode_shadow']}")
    if not report["wiring_denies"]:
        failures.append(
            "the wired hook does not deny an out-of-scope action for the expected "
            f"cause (dead wiring): wanted a refusal naming '{WIRING_EXPECTED_CAUSE}', "
            f"got {report['wiring_decision'] or '<no decision>'}: "
            f"{report['wiring_reason']}")
    if not report["derived"]:
        failures.append("no laws with a responsibility were found to validate")
    # A law the registry declares advisory is NOT_ENFORCED by declaration, so "not ENFORCED" is
    # not by itself its failure -- but everything that used to make it ENFORCED is still
    # required of it, read from `bound_checks_pass` and absent-means-failed. The set of states
    # this gate accepts is therefore the one it accepted before; what changed is that such a
    # law is no longer counted, or printed, as enforced.
    static_only = [d["id"] for d in report["derived"]
                   if d["enforcement_status"] != "ENFORCED" and not d.get("declared_advisory")]
    if static_only:
        failures.append(f"laws not LIVE_PROVEN: {', '.join(static_only)}")
    advisory_broken = [d["id"] for d in report["derived"]
                       if d.get("declared_advisory") and d.get("bound_checks_pass") is not True]
    if advisory_broken:
        failures.append(
            "laws declared advisory whose bound cases, surfaces or prerequisites do not hold "
            f"live: {', '.join(advisory_broken)} — a law that is not enforced still owes the "
            "tests that say what its validator would refuse")
    overclaimed = [d["id"] for d in report["derived"]
                   if d.get("declared_advisory") and (
                       d["enforcement_status"] == "ENFORCED"
                       or d.get("effective_proof_level") == "LIVE_PROVEN")]
    if overclaimed:
        failures.append(
            f"laws declared advisory but reported as enforced: {', '.join(overclaimed)}")
    return failures


def advisory_laws(report: dict) -> list[str]:
    """Ids of the laws the registry declares advisory, in report order."""
    return [d["id"] for d in report["derived"] if d.get("declared_advisory")]


if __name__ == "__main__":
    report = validate_live()
    enforced = sum(1 for d in report["derived"] if d["enforcement_status"] == "ENFORCED")
    print(f"wired_interpreter={report['wired_interpreter']} wiring_denies={report['wiring_denies']} "
          f"prerequisites_resolve={report['prerequisites_resolve']}")
    # The refusal, printed verbatim — the log should show WHICH denial was observed,
    # not merely that one was (ci/live/run_live_turn.sh `expect_blocked` does the same).
    print(f"  wired refusal: {report['wiring_decision'] or '<no decision>'}: {report['wiring_reason']}")
    if report["bytecode_shadow"]:
        print(f"  bytecode shadow under digest roots: {report['bytecode_shadow']}")
    for d in report["derived"]:
        print(f"  {d['id']:<4} {d['enforcement_status']:<12} {d['effective_proof_level']:<13} {d['live']}")
    print(f"LIVE-VALIDATED: {enforced}/{report['laws']} ENFORCED")
    advisory = advisory_laws(report)
    if advisory:
        print(f"  declared advisory, NOT enforced at runtime: {', '.join(advisory)}")

    failures = assurance_failures(report)
    if failures:
        for reason in failures:
            print(f"RED: live-wiring assurance failed — {reason}", file=sys.stderr)
        raise SystemExit(1)
    # The count on the GREEN line is the enforced laws only. It read "17/17" while L13's
    # validator had no caller; a law the registry declares advisory is named beside the count
    # rather than folded into it.
    suffix = (f"; {len(advisory)} declared advisory and NOT enforced at runtime "
              f"({', '.join(advisory)})") if advisory else ""
    print(f"GREEN: live-wiring assurance — {enforced}/{report['laws']} laws LIVE_PROVEN{suffix}")
