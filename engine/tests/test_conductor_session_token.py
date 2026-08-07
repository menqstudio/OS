"""O-3 / M-4: the conductor identity must be signed, and its absence must refuse.

`is_conductor` reads two environment variables — `BRO_ROLE` and `BRO_AGENT_ID` —
and `authorize_conductor_stop` grants the conductor's stop exemption on that
basis. `verify_conductor_session_token` is the compensating control, and it was
switched off in the only way that matters: the policy flag was read with a default
of `False` **and the key was absent from the shipped `.bro/policy.json`**, so
every deployment answered `(True, "identity rests on environment")` and no test in
this suite referenced either symbol. Anything that could set two environment
variables could authorise a conductor stop.

Two properties are pinned here.

**Absence is not permission.** An undeclared flag, a flag of the wrong JSON type,
and an unreadable policy all mean REQUIRED. Only an explicit boolean `false` waives
the requirement, and it is reported as a waiver so the audit ledger records the
word rather than a soothing note.

**The refusal names the missing artifact.** Nothing in this repository can mint a
`conductor-session` token — it is signed offline by the owner's operator-root key
— so the refusal quotes exactly what the owner must provide. A refusal that does
not say what is missing is a refusal somebody deletes.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from bro_policy import (CANONICAL_CONDUCTOR_ID, CONDUCTOR_ROLE,
                        CONDUCTOR_SESSION_ARTIFACT, CONDUCTOR_SESSION_POLICY_KEY,
                        CONDUCTOR_SESSION_TOKEN_ENV, State,
                        conductor_session_token_required,
                        verify_conductor_session_token)
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin

SESSION = "s-conductor-1"


def conductor_state(session: str = SESSION, role: str = CONDUCTOR_ROLE,
                    agent_id: str = CANONICAL_CONDUCTOR_ID) -> State:
    return State("review", role, session, agent_id)


class ShippedPolicyTests(unittest.TestCase):
    """The shipped control-plane policy, not a fixture: the deployed default."""

    def test_the_shipped_policy_requires_a_signed_conductor_session_token(self) -> None:
        # `.bro/policy.json` is inside the protected control-plane digest, so this
        # requirement cannot be switched off by an environment variable — which is
        # the entire point of expressing it here rather than in the env.
        policy = json.loads((ROOT / ".bro" / "policy.json").read_text(encoding="utf-8"))
        self.assertIn(CONDUCTOR_SESSION_POLICY_KEY, policy,
                      "the shipped policy must declare the requirement; an absent key is "
                      "how this control stayed off in every deployment")
        self.assertIs(policy[CONDUCTOR_SESSION_POLICY_KEY], True)
        self.assertEqual(conductor_session_token_required(ROOT)[0], True)


class PolicyRequirementTests(unittest.TestCase):
    """What the flag means when it is absent, malformed, or explicitly set."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="bro-conductor-policy-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".bro").mkdir()

    def write_policy(self, document) -> None:
        (self.root / ".bro" / "policy.json").write_text(json.dumps(document), encoding="utf-8")

    def test_an_absent_key_is_required_not_waived(self) -> None:
        self.write_policy({"schema": 1, "default_mode": "review"})
        required, note = conductor_session_token_required(self.root)
        self.assertTrue(required)
        self.assertIn("does not declare", note)

    def test_a_non_boolean_value_does_not_waive_the_requirement(self) -> None:
        for value in ("false", 0, None, [], {}, "true", 1):
            with self.subTest(value=value):
                self.write_policy({CONDUCTOR_SESSION_POLICY_KEY: value})
                required, note = conductor_session_token_required(self.root)
                self.assertTrue(required, note)
                self.assertIn("must be a JSON boolean", note)

    def test_only_an_explicit_false_waives_and_is_named_a_waiver(self) -> None:
        self.write_policy({CONDUCTOR_SESSION_POLICY_KEY: False})
        required, note = conductor_session_token_required(self.root)
        self.assertFalse(required)
        self.assertIn("EXPLICITLY waives", note)

    def test_true_requires(self) -> None:
        self.write_policy({CONDUCTOR_SESSION_POLICY_KEY: True})
        self.assertTrue(conductor_session_token_required(self.root)[0])

    def test_a_missing_or_unparsable_policy_raises_for_the_caller_to_refuse(self) -> None:
        with self.assertRaises((OSError, ValueError)):
            conductor_session_token_required(self.root)
        self.write_policy([1, 2, 3])
        with self.assertRaises(ValueError):
            conductor_session_token_required(self.root)

    def test_verify_refuses_when_the_protected_policy_cannot_be_read(self) -> None:
        environment = {k: v for k, v in os.environ.items()}
        environment.pop(CONDUCTOR_SESSION_TOKEN_ENV, None)
        with patch.dict(os.environ, environment, clear=True):
            ok, note = verify_conductor_session_token(conductor_state(), self.root)
        self.assertFalse(ok)
        self.assertIn("unreadable", note)


class TokenVerificationTests(unittest.TestCase):
    """Real Ed25519 artifacts against a real operator-signed registry."""

    def setUp(self) -> None:
        self.base = pathlib.Path(tempfile.mkdtemp(prefix="bro-conductor-token-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.keys = {authority: generate_key(authority, f"dev-{authority}", False)
                     for authority in ("operator-root", "builder")}
        use_operator_pin(self, self.keys["operator-root"]["public_key"])
        (self.base / "config").mkdir(parents=True)
        (self.base / ".bro").mkdir()
        now = int(time.time())
        (self.base / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), now - 60, 86400)),
            encoding="utf-8")
        self.require(True)

    def require(self, value: bool) -> None:
        (self.base / ".bro" / "policy.json").write_text(
            json.dumps({"schema": 1, CONDUCTOR_SESSION_POLICY_KEY: value}), encoding="utf-8")

    def payload(self, **overrides) -> dict:
        body = {
            "schema": 1,
            "artifact_type": CONDUCTOR_SESSION_ARTIFACT,
            "key_id": self.keys["operator-root"]["key_id"],
            "session_id": SESSION,
            "agent_id": CANONICAL_CONDUCTOR_ID,
            "role": CONDUCTOR_ROLE,
            "issued_at_epoch": int(time.time()) - 10,
            "expires_at_epoch": int(time.time()) + 3600,
        }
        body.update(overrides)
        return body

    def present(self, document, name: str = "token.json") -> dict:
        path = self.base / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return {CONDUCTOR_SESSION_TOKEN_ENV: str(path)}

    def verify(self, env: dict | None, state: State | None = None) -> tuple[bool, str]:
        environment = {k: v for k, v in os.environ.items()}
        environment.pop(CONDUCTOR_SESSION_TOKEN_ENV, None)
        environment.update(env or {})
        with patch.dict(os.environ, environment, clear=True):
            return verify_conductor_session_token(state or conductor_state(), self.base)

    def sign(self, authority: str = "operator-root", **overrides) -> dict:
        return sign_payload(self.keys[authority]["private_key"], self.payload(**overrides))

    # --- the requirement ------------------------------------------------------------

    def test_required_and_absent_refuses_and_names_what_the_owner_must_provide(self) -> None:
        ok, note = self.verify(None)
        self.assertFalse(ok)
        self.assertIn("no conductor session token presented", note)
        # The refusal must be actionable: the env var, the artifact type and the
        # registry entry the owner has to mint are all named.
        self.assertIn(CONDUCTOR_SESSION_TOKEN_ENV, note)
        self.assertIn(CONDUCTOR_SESSION_ARTIFACT, note)
        self.assertIn("config/trusted-keys.json", note)

    def test_waived_and_absent_proceeds_on_environment_identity_and_says_so(self) -> None:
        self.require(False)
        ok, note = self.verify(None)
        self.assertTrue(ok)
        self.assertIn("EXPLICITLY waives", note)
        self.assertIn("environment", note)

    def test_a_bad_token_refuses_even_when_the_policy_waives_the_requirement(self) -> None:
        """Presented-and-bad is always fail-closed: a waiver excuses absence, never forgery."""
        self.require(False)
        forged = self.sign()
        forged["payload"]["agent_id"] = "agt-p01-r01"
        ok, note = self.verify(self.present(forged))
        self.assertFalse(ok)
        self.assertIn("RED", note)

    # --- the happy path -------------------------------------------------------------

    def test_an_operator_signed_token_bound_to_this_session_verifies(self) -> None:
        ok, note = self.verify(self.present(self.sign()))
        self.assertTrue(ok, note)
        self.assertIn("verified against the trusted-key registry", note)

    # --- everything that must refuse ------------------------------------------------

    def test_a_token_signed_by_a_non_operator_authority_is_refused(self) -> None:
        # A builder key may not speak for the conductor's identity even if the
        # binding fields are perfect: ARTIFACT_AUTHORITY binds conductor-session
        # to operator-root.
        document = sign_payload(self.keys["builder"]["private_key"],
                                self.payload(key_id=self.keys["builder"]["key_id"]))
        ok, note = self.verify(self.present(document))
        self.assertFalse(ok)
        self.assertIn("RED", note)

    def test_a_tampered_payload_is_refused(self) -> None:
        document = self.sign()
        document["payload"]["session_id"] = "s-somebody-else"
        ok, note = self.verify(self.present(document))
        self.assertFalse(ok)
        self.assertIn("RED", note)

    def test_a_token_bound_to_another_session_agent_or_role_is_refused(self) -> None:
        for field, value in (("session_id", "s-other"), ("agent_id", "agt-p01-r01"),
                             ("role", "specialist")):
            with self.subTest(field=field):
                ok, note = self.verify(self.present(self.sign(**{field: value}),
                                                    name=f"token-{field}.json"))
                self.assertFalse(ok)
                self.assertIn("binding mismatch", note)
                self.assertIn(field, note)

    def test_an_expired_or_undated_token_is_refused(self) -> None:
        for expires in (int(time.time()) - 1, "9999999999", None, True):
            with self.subTest(expires=expires):
                ok, note = self.verify(self.present(self.sign(expires_at_epoch=expires),
                                                    name="token-exp.json"))
                self.assertFalse(ok)
                self.assertIn("expired", note)

    def test_an_artifact_of_another_type_may_not_stand_in(self) -> None:
        document = self.sign(artifact_type="workspace-binding")
        ok, note = self.verify(self.present(document))
        self.assertFalse(ok)
        self.assertIn("RED", note)

    def test_a_missing_or_unparsable_token_file_is_refused(self) -> None:
        ok, note = self.verify({CONDUCTOR_SESSION_TOKEN_ENV: str(self.base / "nope.json")})
        self.assertFalse(ok)
        self.assertIn("RED", note)
        broken = self.base / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        ok, note = self.verify({CONDUCTOR_SESSION_TOKEN_ENV: str(broken)})
        self.assertFalse(ok)
        self.assertIn("RED", note)


if __name__ == "__main__":
    unittest.main()
