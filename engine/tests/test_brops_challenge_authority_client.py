from __future__ import annotations

import io
import json
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("runtime", "tools"):
    sys.path.insert(0, str(ROOT / sub))

import brops_challenge_authority_client as client


class AuthorityClientTests(unittest.TestCase):
    def frame(self):
        return {
            "protocol": "brops.governed-challenge-issue.v1",
            "pending_challenge_id": "pending-1",
        }

    @mock.patch.dict("os.environ", {"BROPS_CHALLENGE_SOCKET": "/tmp/a.sock"})
    @mock.patch("brops_challenge_authority_client.brops_socket.request")
    def test_explicit_refusal_is_terminal(self, request):
        request.return_value = {
            "protocol": "brops.governed-challenge-issue-result.v1",
            "status": "refused", "reason": "pending_expired",
        }
        out = io.StringIO(); err = io.StringIO()
        self.assertEqual(client.run(io.StringIO(json.dumps(self.frame())), out, err), 0)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(json.loads(out.getvalue())["reason"], "pending_expired")

    @mock.patch.dict("os.environ", {"BROPS_CHALLENGE_SOCKET": "/tmp/a.sock"})
    @mock.patch("brops_challenge_authority_client.time.sleep")
    @mock.patch("brops_challenge_authority_client.brops_socket.request")
    def test_only_transport_failure_retries_three_total(self, request, sleep):
        request.side_effect = [TimeoutError("lost"), TimeoutError("lost"), {
            "protocol": "brops.governed-challenge-issue-result.v1",
            "status": "issued", "challenge_document_b64": "e30",
        }]
        out = io.StringIO(); err = io.StringIO()
        self.assertEqual(client.run(io.StringIO(json.dumps(self.frame())), out, err), 0)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
