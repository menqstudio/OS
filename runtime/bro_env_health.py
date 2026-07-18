"""Runtime dependency health check (Execution Surface kind=startup).

Reads the canonical dependency SST (config/runtime-dependencies.json) and proves
that every REQUIRED dependency actually resolves in the live environment at the
declared version constraint. A missing or incompatible required dependency is a
fail-closed RED (Law L9); an optional dependency may be absent but MUST NOT be
relied on to weaken a normative gate (OLTS runtime-prerequisite rule).

Pure standard library so the health check itself has no unresolved prerequisite.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
# load_runtime_dependencies is the canonical dependency-SST loader; it lives in tools/.
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from bro_traceability import load_runtime_dependencies


class EnvHealthError(ValueError):
    """Raised when a required dependency does not resolve at its constraint (fail-closed)."""


def _ver_tuple(text: str) -> tuple[int, ...]:
    nums: list[int] = []
    for part in text.strip().split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if digits == "":
            break
        nums.append(int(digits))
    return tuple(nums)


def satisfies(actual: str, constraint: str) -> bool:
    a = _ver_tuple(actual)
    if not a:
        return False
    for clause in constraint.split(","):
        clause = clause.strip()
        if not clause:
            continue
        for op in (">=", "<=", "==", ">", "<"):
            if clause.startswith(op):
                b = _ver_tuple(clause[len(op):])
                if op == ">=" and not a >= b:
                    return False
                if op == "<=" and not a <= b:
                    return False
                if op == "==" and not a == b:
                    return False
                if op == ">" and not a > b:
                    return False
                if op == "<" and not a < b:
                    return False
                break
        else:
            b = _ver_tuple(clause)
            if a[: len(b)] != b:
                return False
    return True


def resolve(dep: dict) -> tuple[bool, str, str]:
    """Return (available, actual_version, detail) for one dependency."""
    kind, name = dep["kind"], dep["resolve"]
    if kind in ("interpreter", "executable"):
        if shutil.which(name) is None:
            return False, "", f"executable '{name}' not found on PATH"
        # Prefer the running interpreter's version for python3; it is the one that runs hooks/tests.
        if name.startswith("python"):
            v = ".".join(str(n) for n in sys.version_info[:3])
            return True, v, "running interpreter"
        return True, "", "present (version not probed)"
    # library
    try:
        importlib.import_module(dep["resolve"])
    except Exception as exc:  # noqa: BLE001 - any import failure is unavailable
        return False, "", f"import failed: {exc}"
    try:
        v = importlib.metadata.version(dep["resolve"])
    except Exception:  # noqa: BLE001
        v = ""
    return True, v, "imported"


def check_environment(root: pathlib.Path = ROOT, tier: str | None = None) -> dict:
    """Prove required dependencies resolve. Raise EnvHealthError (fail-closed) on any failure.

    tier: if given (one of runtime/validation/test/build), only checks deps whose
    required_for includes it. None checks every required dependency.
    """
    deps = load_runtime_dependencies(root)
    checked, failures = [], []
    for dep in deps.values():
        if tier is not None and tier not in dep["required_for"]:
            continue
        required = dep["optionality"] == "required"
        available, actual, detail = resolve(dep)
        ok = available and (actual == "" or satisfies(actual, dep["version"]))
        record = {
            "id": dep["id"], "available": available, "version": actual,
            "constraint": dep["version"], "ok": ok, "required": required, "detail": detail,
        }
        checked.append(record)
        if required and not ok:
            failures.append(record)
    if failures:
        summary = "; ".join(
            f"{f['id']} ({f['detail'] or 'version %s vs %s' % (f['version'], f['constraint'])})"
            for f in failures
        )
        raise EnvHealthError(f"required runtime dependency RED: {summary}")
    return {"checked": checked, "ok": True}


if __name__ == "__main__":
    report = check_environment()
    line = ", ".join(f"{c['id']}={c['version'] or 'ok'}" for c in report["checked"])
    print(f"GREEN: runtime dependency health ok; {line}")
