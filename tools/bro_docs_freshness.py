from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_REVIEWED_AT = "2026-07-15"
EXPECTED_BRANCH = "main"
EXPECTED_MERGED_PR = 6
EXPECTED_MERGE_COMMIT = "2395570bc9571e6c721373751a6dbfa2b6a8f75b"
EXPECTED_STATUS = "orchestration-runtime-v1-foundation-merged-control-room-api-v1-next"


class DocsError(ValueError):
    pass


def validate_manifest_metadata(data: dict) -> None:
    expected = {
        "schema": 1,
        "reviewed_at": EXPECTED_REVIEWED_AT,
        "branch": EXPECTED_BRANCH,
        "merged_pr": EXPECTED_MERGED_PR,
        "merge_commit": EXPECTED_MERGE_COMMIT,
        "status": EXPECTED_STATUS,
    }
    for key, value in expected.items():
        if data.get(key) != value:
            raise DocsError(f"documentation manifest metadata stale: {key}")
    for obsolete in ("pr", "base_sha"):
        if obsolete in data:
            raise DocsError(f"documentation manifest contains obsolete metadata: {obsolete}")


def validate_docs(root: pathlib.Path = ROOT) -> int:
    path = root / "config" / "documentation-manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DocsError(f"documentation manifest unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise DocsError("documentation manifest must be an object")
    validate_manifest_metadata(data)

    docs = data.get("documents")
    if not isinstance(docs, list) or not docs:
        raise DocsError("documentation manifest empty")
    registered = [item.get("path") for item in docs if isinstance(item, dict) and item.get("reviewed") is True]
    actual = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file() and (path.suffix.lower() in {".md", ".markdown"} or path.name == "SKILL.md")
    )
    if sorted(registered) != actual:
        raise DocsError("documentation inventory differs from manifest")

    stale = {
        "README.md": [
            "merged PR: `#4`",
            "main merge commit: `61bf9bc4a42b512926bf848b79a0cac063196993`",
            "The next scoped phase is **Orchestration Runtime V1**",
        ],
        "NEXT_CHAT.md": [
            "PR `#4` is closed and merged",
            "main merge commit: `61bf9bc4a42b512926bf848b79a0cac063196993`",
            "Start **Orchestration Runtime V1**",
        ],
        "ROADMAP.md": [
            "**Merged PR:** `#4`",
            "**Merge commit:** `61bf9bc4a42b512926bf848b79a0cac063196993`",
            "1. **Orchestration Runtime V1:**",
        ],
        "docs/ORCHESTRATION_RUNTIME_V1_SPEC.md": [
            "implementation active in PR #6",
            "**Baseline:** `main` at `b5d1a343a8777738d4113e3e28cf27527f04020a`",
            "**Branch:** `orchestration-runtime-v1`",
        ],
        "docs/ORCHESTRATION_CONTROL_ROOM_V1_SPEC.md": [
            "Phase 2 is **Orchestration Runtime V1**",
            "It does not include the durable runtime",
        ],
    }
    for rel, needles in stale.items():
        text = (root / rel).read_text(encoding="utf-8")
        for needle in needles:
            if needle in text:
                raise DocsError(f"stale documentation marker in {rel}: {needle}")
    return len(actual)


if __name__ == "__main__":
    print(f"GREEN: documentation freshness valid; documents={validate_docs()}")
