"""Tests for the npm supply-chain gate (`.github/supply-chain/npm_audit_filter.py`).

The gate's whole job is to turn `npm audit --json` into an exit code, so the only
question worth testing is: **which inputs are allowed to produce exit 0?**

The audit finding this file answers: an npm ERROR document
(`{"error": {"code": "ENOLOCK", ...}}`) is valid JSON with no `vulnerabilities`
and no `advisories`, so the severity walk returned `[]`, and the gate printed
`PASS: no un-waived high/critical vulnerabilities` and exited 0. An audit that
could not run was reported as an audit that found nothing.

So the tests below are split deliberately:

  * `PassOnlyOnARealCleanAuditTests` — every way the audit can fail to produce a
    result must exit 1. Delete `classify_document`'s error/shape branches and
    these go red.
  * `RealFindingsStillDecideTests` — the fail-closed door must not have swallowed
    the actual severity/allowlist behaviour: a real clean audit still passes, a
    real critical still blocks, and a waived one is still waived.
"""

import importlib.util
import json
import pathlib
import sys
import unittest

# The filter lives under `.github/` (not importable as a package path), so load it
# by file. The repo root is the parent of `engine/`.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FILTER_PATH = REPO_ROOT / ".github" / "supply-chain" / "npm_audit_filter.py"

_spec = importlib.util.spec_from_file_location("npm_audit_filter", FILTER_PATH)
naf = importlib.util.module_from_spec(_spec)
sys.modules["npm_audit_filter"] = naf
_spec.loader.exec_module(naf)


class _TmpDoc:
    """Write a document to a temp file and yield its path (context manager)."""

    def __init__(self, payload, raw=None):
        self.payload = payload
        self.raw = raw

    def __enter__(self):
        import tempfile

        self._fh = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        self._fh.write(self.raw if self.raw is not None else json.dumps(self.payload))
        self._fh.close()
        return self._fh.name

    def __exit__(self, *exc):
        try:
            pathlib.Path(self._fh.name).unlink()
        except OSError:
            pass
        return False


def _run(doc=None, *, raw=None, extra=()):
    """Run the gate over `doc` exactly as the workflow does; return its exit code."""
    with _TmpDoc(doc, raw) as path:
        return naf.main([path, "--threshold", "high", *extra])


# A real npm v7 audit that genuinely found nothing. This is the ONLY shape that
# may exit 0 — every other zero-findings document below is a failure to audit.
CLEAN_V7 = {
    "auditReportVersion": 2,
    "vulnerabilities": {},
    "metadata": {
        "vulnerabilities": {"info": 0, "low": 0, "moderate": 0,
                            "high": 0, "critical": 0, "total": 0},
        "dependencies": {"total": 42},
    },
}


class PassOnlyOnARealCleanAuditTests(unittest.TestCase):
    def test_npm_error_document_fails_closed(self):
        # THE regression. Parses fine, no `vulnerabilities`, no `advisories`.
        # Before the fix this printed PASS and exited 0.
        doc = {"error": {"code": "ENOLOCK",
                         "summary": "This command requires an existing lockfile.",
                         "detail": "npm audit needs a package-lock.json"}}
        self.assertEqual(_run(doc), 1)

    def test_npm_error_document_is_not_rescued_by_an_empty_vulns_map(self):
        # An error document that ALSO carries an empty map must still fail: the
        # error key is checked first, so "npm failed but emitted a skeleton" is
        # not readable as clean.
        doc = {"error": {"code": "ENETUNREACH", "summary": "registry unreachable"},
               "vulnerabilities": {}}
        self.assertEqual(_run(doc), 1)

    def test_unrecognised_shape_fails_closed(self):
        # Neither v7 nor v6. A future/renamed schema must refuse, not read as clean.
        self.assertEqual(_run({"auditReportVersion": 3, "findings": []}), 1)

    def test_empty_object_fails_closed(self):
        self.assertEqual(_run({}), 1)

    def test_metadata_contradicting_an_empty_walk_fails_closed(self):
        # npm's own counts say there ARE criticals; the map we walk is empty. The
        # document is not the shape this filter reads, so a PASS would be false.
        doc = {"vulnerabilities": {},
               "metadata": {"vulnerabilities": {"high": 1, "critical": 1, "total": 2}}}
        self.assertEqual(_run(doc), 1)

    def test_non_object_json_fails_closed(self):
        self.assertEqual(_run(raw="[]"), 1)

    def test_unparseable_json_fails_closed(self):
        self.assertEqual(_run(raw="not json at all"), 1)

    def test_empty_input_fails_closed(self):
        self.assertEqual(_run(raw="   \n"), 1)

    def test_npm_exit_code_outside_the_audit_ran_set_fails_closed(self):
        # Even over a perfectly clean document: npm exiting 254 means no audit
        # happened, so the document is not evidence of anything.
        self.assertEqual(_run(CLEAN_V7, extra=("--npm-exit-code", "254")), 1)

    def test_npm_exit_codes_meaning_the_audit_ran_are_accepted(self):
        # 0 = nothing at npm's level, 1 = npm found something. Both are results.
        self.assertEqual(_run(CLEAN_V7, extra=("--npm-exit-code", "0")), 0)
        self.assertEqual(_run(CLEAN_V7, extra=("--npm-exit-code", "1")), 0)

    def test_classify_document_raises_the_typed_error(self):
        with self.assertRaises(naf.AuditUnavailable):
            naf.classify_document({"error": {"code": "ENOLOCK"}})
        with self.assertRaises(naf.AuditUnavailable):
            naf.classify_document({"metadata": {}})
        self.assertEqual(naf.classify_document(CLEAN_V7), "v7")
        self.assertEqual(naf.classify_document({"advisories": {}}), "v6")

    def test_collect_findings_no_longer_returns_empty_for_a_non_audit(self):
        # The severity walk must not answer "[] findings" for a document that was
        # never an audit -- that answer was the whole defect.
        with self.assertRaises(naf.AuditUnavailable):
            naf.collect_findings({"error": {"code": "ENOLOCK"}},
                                 naf.SEVERITY_RANK["high"])


class RealFindingsStillDecideTests(unittest.TestCase):
    """The fail-closed door must not have replaced the actual gate."""

    def test_a_genuinely_clean_v7_audit_passes(self):
        self.assertEqual(_run(CLEAN_V7), 0)

    def test_a_critical_v7_finding_blocks(self):
        doc = {
            "vulnerabilities": {
                "lodash": {
                    "name": "lodash", "severity": "critical",
                    "via": [{"source": 1065, "title": "Prototype Pollution",
                             "url": "https://github.com/advisories/GHSA-p6mc-m468-83gg",
                             "severity": "critical"}],
                }
            },
            "metadata": {"vulnerabilities": {"high": 0, "critical": 1, "total": 1}},
        }
        self.assertEqual(_run(doc), 1)

    def test_a_moderate_finding_does_not_block_at_the_high_threshold(self):
        doc = {
            "vulnerabilities": {
                "tar": {"name": "tar", "severity": "moderate",
                        "via": [{"source": 7, "title": "path traversal",
                                 "severity": "moderate"}]}
            },
            "metadata": {"vulnerabilities": {"moderate": 1, "high": 0,
                                             "critical": 0, "total": 1}},
        }
        self.assertEqual(_run(doc), 0)

    def test_a_waived_critical_passes_and_an_unwaived_one_does_not(self):
        import tempfile

        doc = {
            "vulnerabilities": {
                "lodash": {"name": "lodash", "severity": "critical",
                           "via": [{"source": 1065, "title": "Prototype Pollution",
                                    "severity": "critical"}]}
            },
            "metadata": {"vulnerabilities": {"high": 0, "critical": 1, "total": 1}},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("# tracked upstream\nlodash  # waived here\n")
            allow = fh.name
        try:
            self.assertEqual(_run(doc, extra=("--allow", allow)), 0)
            self.assertEqual(_run(doc), 1)
        finally:
            pathlib.Path(allow).unlink(missing_ok=True)

    def test_a_v6_advisories_document_still_blocks_on_high(self):
        doc = {
            "advisories": {
                "1065": {"module_name": "lodash", "severity": "high",
                         "title": "Prototype Pollution",
                         "url": "https://npmjs.com/advisories/1065"}
            },
            "metadata": {"vulnerabilities": {"high": 1, "critical": 0, "total": 1}},
        }
        self.assertEqual(_run(doc), 1)


if __name__ == "__main__":
    unittest.main()
