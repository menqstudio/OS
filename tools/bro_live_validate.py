"""Live / integration traceability validator (Execution Surface kind=validator, live).

The static validator (bro_traceability) may emit at most STATIC_PROVEN. This module
discharges the LIVE_PROVEN obligations OLTS defers to integration:

  * runtime prerequisites actually resolve in the live environment,
  * each law's bound allow AND deny test cases actually pass when executed through
    the WIRED interpreter named in .claude/settings.json (not sys.executable),
  * a law with a hook-kind primary surface additionally requires the live wired
    hook command to deny (the anti-dead-wiring proof).

A law is derived ENFORCED only when every required link is LIVE_PROVEN; otherwise it
stays STATIC_ONLY. Nothing is asserted -- status is computed from real runs
(Verifiability MP-11).
"""
from __future__ import annotations

import ast
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "runtime"))

from bro_env_health import check_environment
from bro_traceability import load_runtime_dependencies


def wired_interpreter(root: pathlib.Path) -> str | None:
    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    token = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"].split()[0]
    return shutil.which(token)


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
        [interpreter, "-m", "unittest", f"{module}.{cls}.{case}"],
        cwd=str(root / "tests"), capture_output=True, text=True,
    )
    return result.returncode == 0


def live_wiring_denies(root: pathlib.Path, interpreter: str) -> bool:
    return (run_case(root, interpreter, "tests/test_live_hook_deny.py", "test_wired_interpreter_resolves_on_path")
            and run_case(root, interpreter, "tests/test_live_hook_deny.py", "test_wired_command_denies_out_of_scope"))


def validate_live(root: pathlib.Path = ROOT) -> dict:
    interpreter = wired_interpreter(root)
    wiring_ok = interpreter is not None and live_wiring_denies(root, interpreter)

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
        has_hook = any(s["kind"] == "hook" and s["path_role"] == "primary" for s in record["execution_surfaces"])
        surface_ok = tests_ok and (wiring_ok if has_hook else True)
        enforced = bool(prereq_ok and tests_ok and surface_ok)
        derived.append({
            "id": record["id"],
            "enforcement_status": "ENFORCED" if enforced else "STATIC_ONLY",
            "effective_proof_level": "LIVE_PROVEN" if enforced else "STATIC_PROVEN",
            "live": {"prereq": prereq_ok, "tests": tests_ok, "surface": surface_ok,
                     "hook_surface": has_hook, "wiring": wiring_ok},
        })
    return {
        "wired_interpreter": interpreter,
        "wiring_denies": wiring_ok,
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
    if not report["wiring_denies"]:
        failures.append("the wired hook does not deny an out-of-scope action (dead wiring)")
    if not report["derived"]:
        failures.append("no laws with a responsibility were found to validate")
    static_only = [d["id"] for d in report["derived"] if d["enforcement_status"] != "ENFORCED"]
    if static_only:
        failures.append(f"laws not LIVE_PROVEN: {', '.join(static_only)}")
    return failures


if __name__ == "__main__":
    report = validate_live()
    enforced = sum(1 for d in report["derived"] if d["enforcement_status"] == "ENFORCED")
    print(f"wired_interpreter={report['wired_interpreter']} wiring_denies={report['wiring_denies']} "
          f"prerequisites_resolve={report['prerequisites_resolve']}")
    for d in report["derived"]:
        print(f"  {d['id']:<4} {d['enforcement_status']:<11} {d['effective_proof_level']:<12} {d['live']}")
    print(f"LIVE-VALIDATED: {enforced}/{report['laws']} ENFORCED")

    failures = assurance_failures(report)
    if failures:
        for reason in failures:
            print(f"RED: live-wiring assurance failed — {reason}", file=sys.stderr)
        raise SystemExit(1)
    print(f"GREEN: live-wiring assurance — {enforced}/{report['laws']} laws LIVE_PROVEN")
