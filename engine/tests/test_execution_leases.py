import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

from bro_execution_lease import (
    MAX_EGRESS_DESTINATIONS,
    LeaseError,
    finalize_execution_lease,
    load_execution_lease_from_env,
    quarantine_execution_lease,
    reserve_execution_lease,
    validate_egress_destinations,
    validate_execution_lease,
)


def task(worktree: str):
    return {
        "task_id": "task-lease-1",
        "repository": {
            "full_name": "menqstudio/Bro",
            "branch": "task-lease-1",
            "worktree": worktree,
            "base_commit": "a" * 40,
            "tree_identity": "b" * 64,
        },
    }


def payload(worktree: str, now: int = 1000):
    return {
        "schema": 2,
        "lease_id": "lease-000000000001",
        "nonce": "nonce-000000000001",
        "task_id": "task-lease-1",
        "agent_id": "agt-p01-r01",
        "session_id": "session-1",
        "repository": "menqstudio/Bro",
        "branch": "task-lease-1",
        "worktree": worktree,
        "head_sha": "a" * 40,
        "tree_identity": "b" * 64,
        "allowed_capabilities": ["WRITE_REPOSITORY", "EXECUTE_CODE"],
        "allowed_egress": [],
        "issued_at_epoch": now - 10,
        "expires_at_epoch": now + 100,
        "max_tool_calls": 1,
        "task_class": "standard-builder",
        "protected_scope": [],
        "control_plane_digest": "e" * 64,
        "workspace_id": "ws-test",
    }


class ExecutionLeaseTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("BRO_EXECUTION_LEASE_LEDGER", None)

    def validate(self, value, worktree, now=1000, required=("WRITE_REPOSITORY",)):
        return validate_execution_lease(
            value,
            task=task(worktree),
            agent_id="agt-p01-r01",
            session_id="session-1",
            required_capabilities=required,
            now=now,
        )

    def test_exact_bound_lease_is_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            value = payload(temp)
            lease = self.validate(value, temp)
            self.assertEqual(lease.task_id, "task-lease-1")
            self.assertIn("WRITE_REPOSITORY", lease.allowed_capabilities)

    def test_expired_lease_is_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            value = payload(temp)
            value["expires_at_epoch"] = 999
            with self.assertRaises(LeaseError):
                self.validate(value, temp)

    def test_wrong_task_agent_session_and_repository_bindings_are_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            for field, wrong in (
                ("task_id", "other-task"),
                ("agent_id", "agt-p01-r02"),
                ("session_id", "other-session"),
                ("repository", "other/repo"),
                ("branch", "other-branch"),
                ("head_sha", "c" * 40),
                ("tree_identity", "d" * 64),
            ):
                value = payload(temp)
                value[field] = wrong
                with self.assertRaises(LeaseError, msg=field):
                    self.validate(value, temp)

    def test_missing_required_capability_is_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            value = payload(temp)
            with self.assertRaises(LeaseError):
                self.validate(value, temp, required=("WRITE_EXTERNAL",))

    def test_unknown_task_class_and_capability_over_grant_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            unknown = payload(temp)
            unknown["task_class"] = "root-builder"
            with self.assertRaises(LeaseError):
                self.validate(unknown, temp)
            over = payload(temp)                       # class allows no DESTRUCTIVE
            over["allowed_capabilities"] = ["DESTRUCTIVE"]
            with self.assertRaises(LeaseError):
                self.validate(over, temp, required=("DESTRUCTIVE",))

    # ---- the destination axis (design SS3.1/SS3.2) --------------------------

    def test_absent_allowed_egress_is_a_lease_error_that_names_the_field(self):
        """`[]` is the only way to say "no network". An ABSENT field must be a
        refusal and never a permissive default -- that single decision is what
        separates this axis from USE_NETWORK, which is absent-by-default and
        therefore silently satisfiable everywhere it is not checked. The refusal
        must also NAME the field: an opaque shape error makes `absent =>
        LeaseError` unusable as a control, because nobody can tell which key
        was missing."""
        with tempfile.TemporaryDirectory() as temp:
            value = payload(temp)
            del value["allowed_egress"]
            with self.assertRaises(LeaseError) as caught:
                self.validate(value, temp)
            self.assertIn("allowed_egress", str(caught.exception))

    def test_an_empty_egress_list_is_the_valid_state_at_this_head(self):
        """No class in CLASS_CAPABILITIES holds USE_NETWORK, so every valid
        lease today names no destination. The axis exists and states "none"."""
        with tempfile.TemporaryDirectory() as temp:
            lease = self.validate(payload(temp), temp)
            self.assertEqual(lease.allowed_egress, ())

    def test_naming_a_destination_without_use_network_is_denied(self):
        """A grant must not state an authority it cannot deliver. Because the
        class refuses USE_NETWORK first, this is the refusal every non-empty
        egress list meets at this head."""
        with tempfile.TemporaryDirectory() as temp:
            value = payload(temp)
            value["allowed_egress"] = ["https://api.anthropic.com"]
            with self.assertRaisesRegex(LeaseError, "without USE_NETWORK"):
                self.validate(value, temp)

    def test_unexpressible_destinations_are_refused_not_narrowed(self):
        """Each of these states an authority the enforcement layer cannot
        deliver, so the grant is refused rather than quietly reduced.

        Asserted on THIS refusal's own message. Asserting only `LeaseError`
        let a later refusal answer for these checks: a mutation sweep deleted
        the regex, the ceiling, the duplicate test and the port range, and
        every test stayed green because no lease at this head can hold
        USE_NETWORK, so every non-empty list was already doomed."""
        unexpressible = [
            "https://*.githubusercontent.com",   # a wildcard is one registration from a bypass
            "https://169.254.169.254",           # an IP cannot be re-checked against the NAME
            "https://127.0.0.1:443",
            "http://api.anthropic.com",          # plaintext grants whoever holds the wire
            "https://api.anthropic.com/v1/x",    # CONNECT cannot see a path inside TLS
            "https://API.Anthropic.com",         # folded, the text stops being what a reader compares
            "https://localhost",                 # a single label is not an FQDN
            "https://a.example:0",               # not a port
            "https://a.example:99999",
        ]
        for entry in unexpressible:
            with self.assertRaisesRegex(LeaseError, r"not expressible|port invalid", msg=entry):
                validate_egress_destinations([entry])

    def test_an_expressible_destination_is_accepted_by_the_shape_check(self):
        """So the refusals above are not a check that cannot pass."""
        self.assertEqual(
            validate_egress_destinations(["https://api.anthropic.com:443"]),
            ("https://api.anthropic.com:443",),
        )
        self.assertEqual(validate_egress_destinations([]), ())

    def test_egress_list_shape_is_bounded_and_unique(self):
        with self.assertRaisesRegex(LeaseError, "must be a list of destinations"):
            validate_egress_destinations("https://api.anthropic.com")
        with self.assertRaisesRegex(LeaseError, "must be a list of destinations"):
            validate_egress_destinations([1])
        with self.assertRaisesRegex(LeaseError, "more than 32 destinations"):
            validate_egress_destinations(
                [f"https://h{i}.example" for i in range(MAX_EGRESS_DESTINATIONS + 1)]
            )
        with self.assertRaisesRegex(LeaseError, "duplicate destination"):
            validate_egress_destinations(["https://a.example", "https://a.example"])

    def test_a_malformed_destination_reports_its_own_field_not_use_network(self):
        """The ordering fix, stated as a test: shape is judged before the
        authority coupling, so a wildcard in a lease that cannot hold
        USE_NETWORK says so -- rather than a true sentence about the wrong
        field that sends its reader to the wrong place."""
        with tempfile.TemporaryDirectory() as temp:
            value = payload(temp)
            value["allowed_egress"] = ["https://*.evil.example"]
            with self.assertRaisesRegex(LeaseError, "not expressible"):
                self.validate(value, temp)

    def test_a_schema_1_lease_is_refused(self):
        """v1 and v2 are mutually invalid: `additionalProperties: false` plus an
        exact-set `required` means a v1 lease cannot carry allowed_egress and a
        v2 lease must. Accepting a v1 shape would leave two incompatible
        objects both claiming to be the same version."""
        with tempfile.TemporaryDirectory() as temp:
            value = payload(temp)
            value["schema"] = 1
            with self.assertRaises(LeaseError):
                self.validate(value, temp)

    def test_protected_scope_class_rules_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            std_scope = payload(temp)                  # standard may not carry scope
            std_scope["protected_scope"] = ["runtime/x.py"]
            with self.assertRaises(LeaseError):
                self.validate(std_scope, temp)
            sec_empty = payload(temp)                  # security must name its scope
            sec_empty["task_class"] = "security-maintenance"
            with self.assertRaises(LeaseError):
                self.validate(sec_empty, temp)
            glob = payload(temp)                       # exact paths only, no patterns
            glob["task_class"] = "security-maintenance"
            glob["protected_scope"] = ["runtime/**"]
            with self.assertRaises(LeaseError):
                self.validate(glob, temp)

    def test_control_plane_digest_and_workspace_id_bindings_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            value = payload(temp)
            kw = dict(task=task(temp), agent_id="agt-p01-r01", session_id="session-1",
                      required_capabilities=("WRITE_REPOSITORY",), now=1000)
            lease = validate_execution_lease(
                value, control_plane_digest="e" * 64, workspace_id="ws-test", **kw)
            self.assertEqual(lease.control_plane_digest, "e" * 64)
            self.assertEqual(lease.workspace_id, "ws-test")
            with self.assertRaises(LeaseError):        # wrong control plane
                validate_execution_lease(
                    value, control_plane_digest="f" * 64, workspace_id="ws-test", **kw)
            with self.assertRaises(LeaseError):        # wrong workspace
                validate_execution_lease(
                    value, control_plane_digest="e" * 64, workspace_id="other", **kw)

    def test_atomic_reservation_denies_active_reuse_and_consumed_replay(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as ledger:
            os.environ["BRO_EXECUTION_LEASE_LEDGER"] = ledger
            lease = self.validate(payload(temp), temp)
            reserve_execution_lease(lease, "toolu_1")
            with self.assertRaises(LeaseError):
                reserve_execution_lease(lease, "toolu_2")
            finalize_execution_lease(lease, "toolu_1")
            with self.assertRaises(LeaseError):
                reserve_execution_lease(lease, "toolu_3")

    def test_success_consumes_and_failure_quarantines(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as ledger:
            os.environ["BRO_EXECUTION_LEASE_LEDGER"] = ledger
            first = self.validate(payload(temp), temp)
            reserve_execution_lease(first, "toolu_success")
            finalize_execution_lease(first, "toolu_success")
            self.assertEqual(len(list(pathlib.Path(ledger).glob("*.used"))), 1)

            second_payload = payload(temp)
            second_payload["lease_id"] = "lease-000000000002"
            second_payload["nonce"] = "nonce-000000000002"
            second = self.validate(second_payload, temp)
            reserve_execution_lease(second, "toolu_failure")
            quarantine_execution_lease(second, "toolu_failure", "unknown effect")
            self.assertEqual(len(list(pathlib.Path(ledger).glob("*.ambiguous"))), 1)
            with self.assertRaises(LeaseError):
                reserve_execution_lease(second, "toolu_retry")

    def test_wrong_tool_use_id_cannot_settle(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as ledger:
            os.environ["BRO_EXECUTION_LEASE_LEDGER"] = ledger
            lease = self.validate(payload(temp), temp)
            reserve_execution_lease(lease, "toolu_1")
            with self.assertRaises(LeaseError):
                finalize_execution_lease(lease, "toolu_wrong")


class ExecutionLeaseEd25519Tests(unittest.TestCase):
    """Owner Authorization Phase 1: the execution lease is verified with Ed25519
    against the operator-signed trusted-key registry, not HMAC. Only the offline
    issuer key can grant execution capabilities; a builder holding the public
    registry cannot mint a lease, and a wrong-authority or tampered lease is
    refused."""

    NOW = 1000

    def _fixture(self):
        from broctl import build_registry, generate_key, sign_payload
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="bro-lease-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "config").mkdir(parents=True)
        operator = generate_key("operator-root", "op", False)
        issuer = generate_key("issuer", "iss", False)
        (tmp / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry([operator, issuer], self.NOW, 100_000)), encoding="utf-8")
        from _operator_pin import use_operator_pin
        use_operator_pin(self, operator["public_key"])  # external operator-root pin
        wt = pathlib.Path(tempfile.mkdtemp(prefix="bro-wt-"))
        self.addCleanup(shutil.rmtree, wt, ignore_errors=True)
        return tmp, wt, operator, issuer, sign_payload

    def _sign(self, sign_payload, key, lease_payload):
        body = {"artifact_type": "execution-lease", "key_id": key["key_id"], **lease_payload}
        return sign_payload(key["private_key"], body)

    def _load(self, tmp, wt, signed):
        path = tmp / "lease.signed.json"
        path.write_text(json.dumps(signed), encoding="utf-8")
        with patch.dict(os.environ, {"BRO_EXECUTION_LEASE": str(path)}):
            return load_execution_lease_from_env(
                task=task(str(wt)), agent_id="agt-p01-r01", session_id="session-1",
                required_capabilities=("WRITE_REPOSITORY",), now=self.NOW, root=tmp)

    def test_issuer_signed_lease_loads(self):
        tmp, wt, _operator, issuer, sign = self._fixture()
        lease = self._load(tmp, wt, self._sign(sign, issuer, payload(str(wt), self.NOW)))
        self.assertEqual(lease.task_id, "task-lease-1")
        self.assertIn("WRITE_REPOSITORY", lease.allowed_capabilities)

    def test_operator_key_may_not_sign_a_lease(self):
        tmp, wt, operator, _issuer, sign = self._fixture()
        with self.assertRaises(LeaseError):
            self._load(tmp, wt, self._sign(sign, operator, payload(str(wt), self.NOW)))

    def test_tampered_lease_is_rejected(self):
        tmp, wt, _operator, issuer, sign = self._fixture()
        signed = self._sign(sign, issuer, payload(str(wt), self.NOW))
        signed["payload"]["max_tool_calls"] = 999  # altered after signing
        with self.assertRaises(LeaseError):
            self._load(tmp, wt, signed)


if __name__ == "__main__":
    unittest.main()
