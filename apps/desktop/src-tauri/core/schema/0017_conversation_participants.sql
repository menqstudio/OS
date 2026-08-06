-- Group-chat participants: the explicit roster of who is in a conversation room.
--
-- Until now a group room's responders were inferred (the first two agents, or an @mention).
-- This makes membership FIRST-CLASS so the create-modal can pick a set of specialists, the
-- reply fan-out targets exactly the room, and each agent's prompt can name who else is present.
--
-- A row is one participant (an agent display name, or a human author) in one conversation. The
-- pair is unique; deleting the conversation cascades the roster away. `messages.author` is
-- unchanged — this table records MEMBERSHIP, not messages.
CREATE TABLE IF NOT EXISTS conversation_participants (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (conversation_id, name)
);

CREATE INDEX IF NOT EXISTS idx_conversation_participants_conv
    ON conversation_participants (conversation_id);
