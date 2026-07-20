-- Full-text search index. A single standalone FTS5 table holds a searchable
-- (title, body) pair per entity, tagged with its kind + id. Triggers keep it in
-- sync with every source table; the migration backfills existing rows. Queried
-- with MATCH (tokenized, prefix, multi-term AND) instead of raw LIKE substrings.
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    entity_id UNINDEXED,
    kind      UNINDEXED,
    title,
    body,
    tokenize = 'unicode61'
);

-- Backfill existing rows (all source tables already exist by migration 0009).
INSERT INTO search_index(entity_id, kind, title, body)
    SELECT id, 'project', name, COALESCE(description, '') FROM projects;
INSERT INTO search_index(entity_id, kind, title, body)
    SELECT id, 'task', title, COALESCE(description, '') FROM tasks;
INSERT INTO search_index(entity_id, kind, title, body)
    SELECT id, 'knowledge', title, COALESCE(body, '') || ' ' || COALESCE(tags, '') FROM knowledge_notes;
INSERT INTO search_index(entity_id, kind, title, body)
    SELECT id, 'decision', title, COALESCE(rationale, '') FROM decisions;
INSERT INTO search_index(entity_id, kind, title, body)
    SELECT id, 'agent', display_name, COALESCE(role, '') FROM agents;
INSERT INTO search_index(entity_id, kind, title, body)
    SELECT id, 'conversation', title, kind FROM conversations;
INSERT INTO search_index(entity_id, kind, title, body)
    SELECT id, 'memory', content, content FROM memory_entries;

-- Keep the index in sync. For each table: insert on create, delete+reinsert on
-- update (FTS5 has no in-place row update), delete on delete.

-- projects
CREATE TRIGGER IF NOT EXISTS trg_search_projects_ai AFTER INSERT ON projects BEGIN
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'project', new.name, COALESCE(new.description, ''));
END;
CREATE TRIGGER IF NOT EXISTS trg_search_projects_au AFTER UPDATE ON projects BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'project', new.name, COALESCE(new.description, ''));
END;
CREATE TRIGGER IF NOT EXISTS trg_search_projects_ad AFTER DELETE ON projects BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
END;

-- tasks
CREATE TRIGGER IF NOT EXISTS trg_search_tasks_ai AFTER INSERT ON tasks BEGIN
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'task', new.title, COALESCE(new.description, ''));
END;
CREATE TRIGGER IF NOT EXISTS trg_search_tasks_au AFTER UPDATE ON tasks BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'task', new.title, COALESCE(new.description, ''));
END;
CREATE TRIGGER IF NOT EXISTS trg_search_tasks_ad AFTER DELETE ON tasks BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
END;

-- knowledge_notes
CREATE TRIGGER IF NOT EXISTS trg_search_knowledge_ai AFTER INSERT ON knowledge_notes BEGIN
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'knowledge', new.title, COALESCE(new.body, '') || ' ' || COALESCE(new.tags, ''));
END;
CREATE TRIGGER IF NOT EXISTS trg_search_knowledge_au AFTER UPDATE ON knowledge_notes BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'knowledge', new.title, COALESCE(new.body, '') || ' ' || COALESCE(new.tags, ''));
END;
CREATE TRIGGER IF NOT EXISTS trg_search_knowledge_ad AFTER DELETE ON knowledge_notes BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
END;

-- decisions
CREATE TRIGGER IF NOT EXISTS trg_search_decisions_ai AFTER INSERT ON decisions BEGIN
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'decision', new.title, COALESCE(new.rationale, ''));
END;
CREATE TRIGGER IF NOT EXISTS trg_search_decisions_au AFTER UPDATE ON decisions BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'decision', new.title, COALESCE(new.rationale, ''));
END;
CREATE TRIGGER IF NOT EXISTS trg_search_decisions_ad AFTER DELETE ON decisions BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
END;

-- agents
CREATE TRIGGER IF NOT EXISTS trg_search_agents_ai AFTER INSERT ON agents BEGIN
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'agent', new.display_name, COALESCE(new.role, ''));
END;
CREATE TRIGGER IF NOT EXISTS trg_search_agents_au AFTER UPDATE ON agents BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'agent', new.display_name, COALESCE(new.role, ''));
END;
CREATE TRIGGER IF NOT EXISTS trg_search_agents_ad AFTER DELETE ON agents BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
END;

-- conversations
CREATE TRIGGER IF NOT EXISTS trg_search_conversations_ai AFTER INSERT ON conversations BEGIN
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'conversation', new.title, new.kind);
END;
CREATE TRIGGER IF NOT EXISTS trg_search_conversations_au AFTER UPDATE ON conversations BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'conversation', new.title, new.kind);
END;
CREATE TRIGGER IF NOT EXISTS trg_search_conversations_ad AFTER DELETE ON conversations BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
END;

-- memory_entries
CREATE TRIGGER IF NOT EXISTS trg_search_memory_ai AFTER INSERT ON memory_entries BEGIN
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'memory', new.content, new.content);
END;
CREATE TRIGGER IF NOT EXISTS trg_search_memory_au AFTER UPDATE ON memory_entries BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
    INSERT INTO search_index(entity_id, kind, title, body) VALUES (new.id, 'memory', new.content, new.content);
END;
CREATE TRIGGER IF NOT EXISTS trg_search_memory_ad AFTER DELETE ON memory_entries BEGIN
    DELETE FROM search_index WHERE entity_id = old.id;
END;
