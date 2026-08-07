import { Conversations } from './Conversations';

/**
 * The direct-chat screen.
 *
 * Bro is the conductor — the owner talks to him, he confirms what was meant, and then he puts
 * the work on specialists. Only the first half of that was ever visible. The second half is the
 * delegation surface: who was spawned, at which tier, with which tools and which paths, and what
 * came back.
 *
 * That surface is no longer a sibling of the conversation here. It was one because
 * `Conversations.tsx` was read-only when it was built, so there was no way to reach either the
 * live stream or the selected thread from outside. Both are reachable now, and the surface is
 * rendered INSIDE the workspace (`Conversations.tsx`, beneath `chat-workspace`) where the open
 * conversation and its `StreamEvent` channel both are. Keeping it here would have meant a
 * surface that could not tell which conversation the delegations it drew belonged to — and a
 * delegation filed under the wrong conversation is worse than one not shown.
 */
export function Chat() {
  return <Conversations kind="direct" />;
}
