import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_authorization import classify_tool_action, load_tool_registry


class AuthorizationKernelTests(unittest.TestCase):
    def test_registry_loads_and_defines_unknown(self):
        registry = load_tool_registry(ROOT)
        self.assertEqual(registry["schema"], 1)
        self.assertIn("UNKNOWN", registry["capability_classes"])
        self.assertEqual(registry["policy"], "unknown-tool-or-action-deny")

    def test_registered_read_tool_is_read_only(self):
        result = classify_tool_action("Read", {"file_path": "README.md"}, ROOT)
        self.assertEqual(result.action, "read")
        self.assertEqual(result.capabilities, ("READ_LOCAL",))
        self.assertFalse(result.mutating)
        self.assertFalse(result.unknown)

    def test_registered_write_tool_is_scoped_mutation(self):
        result = classify_tool_action("Write", {"file_path": "runtime/x.py"}, ROOT)
        self.assertTrue(result.mutating)
        self.assertTrue(result.requires_task)
        self.assertTrue(result.requires_scope)
        self.assertTrue(result.requires_work_grant)
        self.assertEqual(result.targets, ("runtime/x.py",))
        self.assertIn("WRITE_REPOSITORY", result.capabilities)

    def test_unknown_tool_is_fail_closed(self):
        result = classify_tool_action(
            "CustomMcpMutation", {"operation": "delete_everything"}, ROOT
        )
        self.assertTrue(result.unknown)
        self.assertTrue(result.mutating)
        self.assertEqual(result.capabilities, ("UNKNOWN",))

    def test_read_only_git_is_classified_as_local_read(self):
        result = classify_tool_action("Bash", {"command": "git status"}, ROOT)
        self.assertFalse(result.mutating)
        self.assertFalse(result.unknown)
        self.assertEqual(result.capabilities, ("READ_LOCAL",))

    def test_git_mutation_is_repository_write(self):
        result = classify_tool_action(
            "PowerShell", {"command": "git update-ref refs/heads/x HEAD"}, ROOT
        )
        self.assertTrue(result.mutating)
        self.assertTrue(result.requires_scope)
        self.assertIn("WRITE_REPOSITORY", result.capabilities)

    def test_push_is_external_publish_with_credentials(self):
        result = classify_tool_action(
            "Shell", {"command": "git push origin HEAD:task-123"}, ROOT
        )
        self.assertTrue(result.mutating)
        self.assertTrue(result.push)
        self.assertFalse(result.requires_scope)
        self.assertIn("WRITE_EXTERNAL", result.capabilities)
        self.assertIn("PUBLISH", result.capabilities)
        self.assertIn("USE_NETWORK", result.capabilities)
        self.assertIn("USE_CREDENTIAL", result.capabilities)

    def test_unknown_executable_is_unknown_capability(self):
        result = classify_tool_action(
            "Bash", {"command": "custom-tool --do-anything"}, ROOT
        )
        self.assertTrue(result.unknown)
        self.assertTrue(result.mutating)

    def test_delete_command_has_delete_capability(self):
        result = classify_tool_action("PowerShell", {"command": "Remove-Item x"}, ROOT)
        self.assertTrue(result.mutating)
        self.assertIn("DELETE", result.capabilities)
        self.assertIn("WRITE_REPOSITORY", result.capabilities)


if __name__ == "__main__":
    unittest.main()
