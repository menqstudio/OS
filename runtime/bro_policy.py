from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / ".bro" / "policy.json"
MANIFEST_PATH = ROOT / "config" / "canonical-read-manifest.json"

MUTATING_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
MUTATING_SHELL = re.compile(
    r"(?ix)(^|[;&|]\s*)(rm|del|erase|rmdir|remove-item|set-content|add-content|out-file|new-item|move-item|copy-item|"
    r"git\s+(add|commit|push|merge|rebase|reset|checkout|switch|branch|tag|clean)|"
    r"gh\s+(pr|issue|release|workflow|repo)\b|npm\s+install|pnpm\s+add|yarn\s+add|pip\s+install)\b"
)
PUSH = re.compile(r"(?i)\bgit\s+push\b|\bgh\s+pr\s+(create|merge|close)\b")

@dataclass(frozen=True)
class State:
    mode: str
    role: str
    session_id: str


def load_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def tracked_files() -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [p.decode("utf-8") for p in raw.split(b"\0") if p]


def tree_identity() -> str:
    h = hashlib.sha256()
    for rel in tracked_files():
        data = (ROOT / rel).read_bytes()
        h.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def receipt_dir() -> pathlib.Path:
    repo_key = hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:20]
    path = pathlib.Path(tempfile.gettempdir()) / "bro-runtime" / repo_key / "receipts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def receipt_path(session_id: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return receipt_dir() / f"{safe}.json"


def current_state(payload: dict) -> State:
    return State(
        mode=os.getenv("BRO_MODE", load_json(POLICY_PATH)["default_mode"]).strip().lower(),
        role=os.getenv("BRO_ROLE", "bro").strip().lower(),
        session_id=str(payload.get("session_id") or os.getenv("BRO_SESSION_ID") or "unknown"),
    )


def read_all(session_id: str) -> dict:
    files = tracked_files()
    hashes = {}
    total = 0
    for rel in files:
        data = (ROOT / rel).read_bytes()
        total += len(data)
        hashes[rel] = hashlib.sha256(data).hexdigest()
    canonical = load_json(MANIFEST_PATH)["paths"]
    missing = [p for p in canonical if p not in hashes]
    if missing:
        raise RuntimeError(f"canonical files are missing or untracked: {missing}")
    now = int(time.time())
    receipt = {
        "schema": 1,
        "session_id": session_id,
        "commit": git("rev-parse", "HEAD"),
        "tree_identity": tree_identity(),
        "read_at_epoch": now,
        "tracked_files": len(files),
        "tracked_bytes": total,
        "canonical_paths": canonical,
        "hashes": hashes,
        "proof_boundary": "read-to-EOF and hashes; canonical text is separately injected into model context",
    }
    receipt_path(session_id).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def load_receipt(session_id: str) -> dict | None:
    path = receipt_path(session_id)
    if not path.exists():
        return None
    try:
        return load_json(path)
    except Exception:
        return None


def receipt_fresh(session_id: str) -> tuple[bool, str]:
    policy = load_json(POLICY_PATH)
    receipt = load_receipt(session_id)
    if not receipt:
        return False, "missing full-read receipt"
    age = int(time.time()) - int(receipt.get("read_at_epoch", 0))
    if age > int(policy["receipt_max_age_seconds"]):
        return False, f"full-read receipt is stale ({age}s)"
    if receipt.get("tree_identity") != tree_identity():
        return False, "repository tree changed after the full-read receipt"
    return True, "fresh"


def canonical_context() -> str:
    paths = load_json(MANIFEST_PATH)["paths"]
    chunks = []
    for rel in paths:
        text = (ROOT / rel).read_text(encoding="utf-8")
        chunks.append(f"\n===== {rel} =====\n{text}")
    return "BRO CANONICAL STARTUP CONTEXT\n" + "".join(chunks)


def is_mutation(tool_name: str, tool_input: dict) -> bool:
    if tool_name in MUTATING_TOOLS:
        return True
    if tool_name in {"Bash", "PowerShell", "Shell"}:
        cmd = str(tool_input.get("command") or tool_input.get("script") or "")
        return bool(MUTATING_SHELL.search(cmd))
    return False


def is_push(tool_name: str, tool_input: dict) -> bool:
    if tool_name not in {"Bash", "PowerShell", "Shell"}:
        return False
    cmd = str(tool_input.get("command") or tool_input.get("script") or "")
    return bool(PUSH.search(cmd))


def authorize_tool(state: State, tool_name: str, tool_input: dict) -> tuple[bool, str]:
    if state.mode not in {"review", "work", "release"}:
        return False, f"unknown BRO_MODE={state.mode!r}"
    if state.mode == "review" and is_mutation(tool_name, tool_input):
        return False, "review mode is technically read-only"
    if is_push(tool_name, tool_input):
        if state.mode != "release":
            return False, "push is denied outside release mode"
        if state.role != "push-executor":
            return False, "only the push-executor role may attempt push"
        if os.getenv("BRO_EXTERNAL_RELEASE_BOUNDARY") != "confirmed":
            return False, "external credential/permission boundary is not confirmed"
    return True, "allowed"
