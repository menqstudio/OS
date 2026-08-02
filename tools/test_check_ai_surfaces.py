"""Tests for tools/check_ai_surfaces.py — the AI-entry-point inventory gate."""
from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_ai_surfaces as ai  # noqa: E402

# A miniature commands.rs: one governed surface, one ungoverned, one non-command helper, one non-AI command.
SRC = """
#[tauri::command]
pub async fn stream_reply(x: i32) -> Result<(), String> {
    let governed = crate::ai::governed_turn(&prepared).await;
    let _ = crate::ai::generate_stream(&s, &h, cb).await;
    Ok(())
}

#[tauri::command]
pub async fn reply_in_conversation(x: i32) -> Result<(), String> {
    let text = crate::ai::generate(&s, &h).await?;
    Ok(())
}

pub fn helper_builds_prompt() -> String {
    crate::ai::generate(&s, &h)  // a pub helper WITHOUT #[tauri::command] — not a surface
}

#[tauri::command]
pub fn list_things() -> Result<(), String> { Ok(()) }  // no provider call
"""

# A commands.rs where a command hides the generic provider call behind a NON-command pub helper,
# one call-hop away. This is exactly the bypass the hardened gate must catch.
SRC_HELPER = """
#[tauri::command]
pub async fn sneaky_reply(x: i32) -> Result<(), String> {
    let text = build_and_call(&x).await?;   // no provider call here — it's one hop away
    Ok(())
}

pub async fn build_and_call(x: &i32) -> Result<String, String> {
    let text = crate::ai::generate(&s, &h).await?;   // generic provider, hidden behind a pub helper
    Ok(text)
}

#[tauri::command]
pub async fn governed_via_helper(x: i32) -> Result<(), String> {
    let r = only_governed(&x).await?;   // reaches ONLY the governed entry, one hop away
    Ok(())
}

pub async fn only_governed(x: &i32) -> Result<String, String> {
    let r = crate::ai::governed_turn(&prepared).await?;
    Ok(r)
}

#[tauri::command]
pub fn plain(x: i32) -> Result<(), String> { let _ = pure_helper(); Ok(()) }  // no provider anywhere

pub fn pure_helper() -> i32 { 0 }
"""


def _policy(surfaces):
    return {"surfaces": surfaces}


class ParseTests(unittest.TestCase):
    def test_parses_commands_and_calls(self):
        p = ai.parse_command_ai_calls(SRC)
        self.assertTrue(p["stream_reply"]["is_command"])
        self.assertEqual(set(p["stream_reply"]["calls"]), {"governed_turn", "generate_stream"})
        self.assertEqual(set(p["reply_in_conversation"]["calls"]), {"generate"})
        self.assertFalse(p["helper_builds_prompt"]["is_command"])
        self.assertEqual(p["list_things"]["calls"], [])

    def test_local_calls_detected(self):
        p = ai.parse_command_ai_calls(SRC_HELPER)
        self.assertIn("build_and_call", p["sneaky_reply"]["local_calls"])
        self.assertEqual(p["sneaky_reply"]["calls"], [])  # nothing provider-ish directly
        self.assertFalse(p["build_and_call"]["is_command"])
        self.assertEqual(set(p["build_and_call"]["calls"]), {"generate"})

    def test_self_reference_not_a_local_call(self):
        # `sneaky_reply(` never appears in its own body, but ensure a fn is never its own local-call.
        p = ai.parse_command_ai_calls(SRC_HELPER)
        self.assertNotIn("sneaky_reply", p["sneaky_reply"]["local_calls"])


class ResolveTests(unittest.TestCase):
    def test_one_hop_helper_is_resolved(self):
        parsed = ai.parse_command_ai_calls(SRC_HELPER)
        resolved = ai.resolve_command_surfaces(parsed)
        # only commands are surfaces
        self.assertEqual(set(resolved), {"sneaky_reply", "governed_via_helper", "plain"})
        self.assertEqual(resolved["sneaky_reply"]["direct"], set())
        self.assertEqual(resolved["sneaky_reply"]["effective"], {"generate"})
        self.assertEqual(resolved["sneaky_reply"]["via_helper"], {"build_and_call": {"generate"}})
        self.assertEqual(resolved["governed_via_helper"]["effective"], {"governed_turn"})
        self.assertEqual(resolved["plain"]["effective"], set())  # helper has no provider call

    def test_direct_calls_still_resolved(self):
        parsed = ai.parse_command_ai_calls(SRC)
        resolved = ai.resolve_command_surfaces(parsed)
        self.assertEqual(resolved["stream_reply"]["effective"], {"governed_turn", "generate_stream"})
        # the uncalled pub helper is NOT a surface and does not leak into any command
        self.assertNotIn("helper_builds_prompt", resolved)
        self.assertEqual(resolved["reply_in_conversation"]["effective"], {"generate"})


class CheckTests(unittest.TestCase):
    def _good(self):
        return _policy([
            {"command": "stream_reply", "governance": "ungoverned_tracked", "tracking": "T-017"},
            {"command": "reply_in_conversation", "governance": "ungoverned_tracked", "tracking": "T-017"},
        ])

    def test_good_policy_passes(self):
        self.assertEqual(ai.check(SRC, self._good()), [])

    def test_unclassified_ai_command_fails(self):
        pol = _policy([{"command": "stream_reply", "governance": "ungoverned_tracked", "tracking": "T-017"}])
        probs = ai.check(SRC, pol)
        self.assertTrue(any("reply_in_conversation" in p and "NOT classified" in p for p in probs))

    def test_stale_entry_fails(self):
        pol = self._good()["surfaces"] + [{"command": "no_such_fn", "governance": "excluded", "tracking": "x"}]
        probs = ai.check(SRC, {"surfaces": pol})
        self.assertTrue(any("no_such_fn" in p and "not a fn" in p for p in probs))

    def test_non_ai_command_in_policy_is_stale(self):
        pol = self._good()["surfaces"] + [{"command": "list_things", "governance": "excluded", "tracking": "x"}]
        probs = ai.check(SRC, {"surfaces": pol})
        self.assertTrue(any("list_things" in p and "no longer calls" in p for p in probs))

    def test_untracked_nongoverned_fails(self):
        pol = _policy([
            {"command": "stream_reply", "governance": "ungoverned_tracked"},  # no tracking
            {"command": "reply_in_conversation", "governance": "ungoverned_tracked", "tracking": "T-017"},
        ])
        probs = ai.check(SRC, pol)
        self.assertTrue(any("stream_reply" in p and "no non-empty 'tracking'" in p for p in probs))

    def test_governed_calling_generic_fails(self):
        # stream_reply calls generate_stream (generic) -> cannot be 'governed'.
        pol = _policy([
            {"command": "stream_reply", "governance": "governed"},
            {"command": "reply_in_conversation", "governance": "ungoverned_tracked", "tracking": "T-017"},
        ])
        probs = ai.check(SRC, pol)
        self.assertTrue(any("stream_reply" in p and "labelled 'governed'" in p for p in probs))

    def test_bad_governance_enum_fails(self):
        pol = _policy([
            {"command": "stream_reply", "governance": "kinda", "tracking": "T-017"},
            {"command": "reply_in_conversation", "governance": "ungoverned_tracked", "tracking": "T-017"},
        ])
        probs = ai.check(SRC, pol)
        self.assertTrue(any("stream_reply" in p and "governance must be one of" in p for p in probs))

    # ---- helper-hop hardening ----

    def test_helper_hidden_provider_must_be_classified(self):
        # sneaky_reply reaches ai::generate ONLY through a pub helper; it must still be required in policy.
        probs = ai.check(SRC_HELPER, _policy([]))
        self.assertTrue(any("sneaky_reply" in p and "NOT classified" in p for p in probs),
                        f"helper-hidden surface not flagged: {probs}")
        # the diagnostic must name the laundering helper so the reviewer sees the hop.
        self.assertTrue(any("sneaky_reply" in p and "build_and_call" in p for p in probs))

    def test_helper_hidden_generic_cannot_be_governed(self):
        # labelling the helper-laundered surface 'governed' must fail — the pub helper cannot launder it.
        pol = _policy([
            {"command": "sneaky_reply", "governance": "governed"},
            {"command": "governed_via_helper", "governance": "governed"},
        ])
        probs = ai.check(SRC_HELPER, pol)
        self.assertTrue(any("sneaky_reply" in p and "labelled 'governed'" in p and "build_and_call" in p
                            for p in probs), f"helper-laundered governed not flagged: {probs}")
        # governed_via_helper reaches ONLY governed_turn (via helper) -> legitimately governable, no error.
        self.assertFalse(any("governed_via_helper" in p for p in probs))

    def test_helper_hop_good_policy_passes(self):
        # honest classification of the helper-reached surfaces is accepted.
        pol = _policy([
            {"command": "sneaky_reply", "governance": "ungoverned_tracked", "tracking": "T-999"},
            {"command": "governed_via_helper", "governance": "governed"},
        ])
        self.assertEqual(ai.check(SRC_HELPER, pol), [])

    def test_bare_helper_cannot_be_a_policy_entry(self):
        # build_and_call is a fn but NOT a command — listing it as a surface is invalid.
        pol = _policy([
            {"command": "sneaky_reply", "governance": "ungoverned_tracked", "tracking": "T-999"},
            {"command": "governed_via_helper", "governance": "governed"},
            {"command": "build_and_call", "governance": "ungoverned_tracked", "tracking": "T-999"},
        ])
        probs = ai.check(SRC_HELPER, pol)
        self.assertTrue(any("build_and_call" in p and "not a #[tauri::command]" in p for p in probs))

    def test_real_repo_is_consistent(self):
        # Dogfood: the live repo must pass its own AI-surface gate.
        root = pathlib.Path(__file__).resolve().parents[1]
        src = (root / ai.COMMANDS_RS).read_text(encoding="utf-8")
        policy = json.loads((root / ai.POLICY).read_text(encoding="utf-8"))
        self.assertEqual(ai.check(src, policy), [])


if __name__ == "__main__":
    unittest.main()
