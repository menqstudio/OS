-- The task_dependencies table already exists from 0001_initial. This migration
-- only adds lookup indexes for the dependency queries (blockers of a task, and
-- reverse lookups). Edges are (task_id depends on depends_on_id).
CREATE INDEX IF NOT EXISTS idx_task_deps_task ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_task_deps_depends_on ON task_dependencies(depends_on_id);
