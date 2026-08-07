import { Conversations } from './Conversations';
import { DelegationSurface } from './delegationView';

/**
 * The direct-chat screen: the conversation itself, plus the delegation ledger for it.
 *
 * Bro is the conductor — the owner talks to him, he confirms what was meant, and then he puts
 * the work on specialists. Only the first half of that was ever visible. `DelegationSurface`
 * is the second: who was spawned, at which tier, with which tools and which paths, and what
 * came back.
 *
 * It sits BESIDE the thread rather than inline between the turns, and that is a scope
 * consequence, not a design preference — `Conversations.tsx` is read-only for this task, so
 * there is no slot to render into and no way to read which conversation is selected. Both are
 * one small change away; the report names them exactly.
 */
export function Chat() {
  return (
    <>
      <Conversations kind="direct" />
      <DelegationSurface />
    </>
  );
}
