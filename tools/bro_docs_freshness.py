from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_REVIEWED_AT = "2026-07-15"
EXPECTED_BRANCH = "main"
EXPECTED_MERGED_PR = 3
EXPECTED_MERGE_COMMIT = "bec6c77f622065ee302acf23d26d4c73329a400a"
EXPECTED_STATUS = "execution-control-plane-v2-merged-orchestration-phase0-spec-active"


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
    registered = [
        item.get("path")
        for item in docs
        if isinstance(item, dict) and item.get("reviewed") is True
    ]
    actual = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file()
        and (path.suffix.lower() in {".md", ".markdown"} or path.name == "SKILL.md")
    )
    if sorted(registered) != actual:
        raise DocsError("documentation inventory differs from manifest")

    stale = {
        "NEXT_CHAT.md": [
            "Continue only in `menqstudio/Bro` on branch `bro-execution-control-plane-v2`",
            "draft PR `#2`",
            "Wait for Gev's explicit merge approval",
        ],
        "ROADMAP.md": [
            "**Branch:** `bro-execution-control-plane-v2`",
            "**Draft PR:** `#2`",
            "## Remaining release gate",
        ],
        "docs/EXECUTION_CONTROL_PLANE_V2_SPEC.md": [
            "owner-approved merge pending",
            "PR #2 remains draft/open/unmerged",
            "Runtime behavior changed by this commit: None",
        ],
        "README.md": [
            "The PR remains draft/open/unmerged",
            "remaining gate is Gev's explicit approval",
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
