// Delegations reported inside a GROUP room, and the one provenance fact this window may state
// about them.
//
// ---- Why this module exists at all -------------------------------------------------
// The direct chat already draws Bro's delegations: `Conversations.tsx` folds the
// `delegationSpawned` / `delegationSettled` frames off the shared `StreamEvent` channel and
// renders `DelegationSurface` beneath the workspace — but only for `kind === 'direct'`. In a
// group room the same frames are folded and then drawn nowhere. A group room is exactly where
// handing work to a named specialist matters most, so the gap is worth closing.
//
// It is closed HERE rather than there because `Conversations.tsx` is finished and off limits to
// this task. What that leaves is the one live stream the Group Chat screen genuinely owns: the
// consensus deck's own `desktop.streamReply` calls, the asks it sends to participants when a
// round opens (or when it chases the silent ones). Delegations reported by THOSE turns reach
// this module; delegations reported by the room's ordinary chat turns above do not, and the
// surface says so out loud rather than letting a partial list read as the room's whole record.
//
// ---- The two rules this module keeps -----------------------------------------------
//  1. BINDING. A delegation filed under the wrong conversation is worse than one not shown, so
//     the room binding is not re-invented here: every event goes through the direct path's own
//     `applyDelegationEventForConversation`, which admits a spawn only when the payload's own
//     `conversationId` equals the room's. Same function, same equality, same refusal of the
//     one-shot-ask frame (`conversationId: null`).
//  2. PROVENANCE. The frame carries no consensus round, and no requester either — the backend
//     stamps `parent: "Bro"` on every delegation regardless of which participant's turn produced
//     it (`commands.rs::delegation_frame`). So the only link that may be drawn is the one this
//     window itself established: which ask it had started when the frame arrived. That is a fact
//     about this window's own control flow — `collect()` awaits one `streamReply` at a time, so a
//     frame arriving during that await belongs to that ask — and it is labelled as such, never as
//     something the specialist reported and never as a claim that the specialist was told about
//     the decision.
//
// An ask context is recorded ONLY for a delegation this fold newly admitted. A settlement, a
// replayed spawn, or a frame belonging to another room changes nothing, so no delegation can
// acquire a provenance it did not arrive with.

import {
  applyDelegationEventForConversation,
  type Delegation,
  type DelegationEvent,
} from './delegation';

/**
 * What this window had started when a delegation frame arrived.
 *
 * `who` is the participant the deck was asking — the turn that reported the delegation. It is
 * NOT read off the frame (the frame's `parent` is a constant), and it is not a claim that `who`
 * chose the specialist; it names the turn, which is what this window can actually vouch for.
 *
 * `roundId` / `question` are the consensus round that ask belonged to, when there was one:
 * `roundId` is the opening message's id, the same id `readConsensusTranscript` gives a round.
 * Both are `null` for an ask with no round context, and neither is ever guessed from the
 * transcript after the fact — a round chosen after the delegation is known is exactly the
 * connection the events do not carry.
 */
export interface AskContext {
  who: string;
  roundId: string | null;
  question: string | null;
}

/** The room's live delegations plus the ask each one arrived on. */
export interface GroupDelegations {
  /** Folded by the direct path's conversation-scoped reducer. */
  list: Delegation[];
  /** Delegation id → the ask this window was running when that id was first admitted. A
   *  delegation with no entry here is drawn without any consensus context, never with a
   *  borrowed one. */
  askedFor: Readonly<Record<string, AskContext>>;
}

export const NO_GROUP_DELEGATIONS: GroupDelegations = { list: [], askedFor: {} };

/**
 * Fold one live event into a room's delegations, recording provenance for whatever it admitted.
 *
 * `roomId` is the conversation this list belongs to and is passed straight through to
 * `applyDelegationEventForConversation`; nothing here second-guesses that decision. `ask` is
 * `null` when the caller cannot say which ask the frame belongs to — in which case the
 * delegation is still folded (it happened) but gets no context (we cannot say why).
 */
export function applyGroupDelegationEvent(
  prev: GroupDelegations,
  ev: DelegationEvent,
  roomId: string,
  ask: AskContext | null,
): GroupDelegations {
  const list = applyDelegationEventForConversation(prev.list, ev, roomId);
  if (ask === null) return { list, askedFor: prev.askedFor };

  // Only ids this event actually ADDED get the context. A second `spawned` for a known id is
  // dropped by the reducer above, so a replay cannot re-file an existing delegation under a
  // later ask; a settlement adds no id, so it cannot invent one either.
  const known = new Set(prev.list.map((d) => d.id));
  const fresh = list.filter((d) => !known.has(d.id));
  if (fresh.length === 0) return { list, askedFor: prev.askedFor };

  const askedFor: Record<string, AskContext> = { ...prev.askedFor };
  for (const d of fresh) askedFor[d.id] = ask;
  return { list, askedFor };
}

/** One row of the provenance trail: a delegation and the ask it arrived on. Delegations with no
 *  recorded ask are omitted — the trail states what this window started, and it has nothing to
 *  say about one it did not start. The card for that delegation is still drawn. */
export interface DelegationAskRow {
  delegation: Delegation;
  ask: AskContext;
}

export function askTrail(state: GroupDelegations): DelegationAskRow[] {
  const rows: DelegationAskRow[] = [];
  for (const delegation of state.list) {
    const ask = state.askedFor[delegation.id];
    if (ask) rows.push({ delegation, ask });
  }
  return rows;
}
