# Agent Operating Contract

This file applies to every pack lead, specialist, worker, auditor, verifier, and executor.

- Bro is one rank above all agents and packs.
- No agent may call itself Bro.
- Every task requires a machine-readable task contract.
- Every specialist has permanent core skills and must load additional skills when the task needs them.
- Skill loading is mandatory before work, not optional advice.
- The builder and final verifier must be different identities for medium, high, or critical work.
- No agent may expand scope silently.
- No agent may push. Only the Push Executor in the Git & Release Control Pack may attempt push, and only in externally granted release mode.
- Every task longer than 30 minutes triggers a complete canonical reread before the next tool call. A single already-running atomic/volatile operation may finish first; reread happens immediately afterward.
- Review mode is read-only in both policy and technical permissions.
