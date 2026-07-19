//! Typed Tauri commands. React reaches the database only through these; no raw
//! SQL crosses the boundary. Every command maps core errors to strings.

use crate::AppState;
use brops_core::{
    repo, ActivityEvent, Agent, Approval, Automation, Conversation, Decision, Event, Integration,
    KnowledgeNote, MemoryEntry, Message, Metric, NewAutomation, NewEvent, NewKnowledgeNote,
    NewMemoryEntry, NewMessage, NewProject, NewTask, Notification, Project, Run, RunStep,
    SearchResult, SecuritySummary, Task,
};
use tauri::State;

type Conn<'a> = std::sync::MutexGuard<'a, rusqlite::Connection>;

fn locked<'a>(state: &'a State<AppState>) -> Result<Conn<'a>, String> {
    state.db.lock().map_err(|e| e.to_string())
}

// --- projects ---

#[tauri::command]
pub fn list_projects(state: State<AppState>) -> Result<Vec<Project>, String> {
    let conn = locked(&state)?;
    repo::projects::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_project(state: State<AppState>, input: NewProject) -> Result<Project, String> {
    let conn = locked(&state)?;
    repo::projects::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_project_status(state: State<AppState>, id: String, status: String) -> Result<Project, String> {
    let conn = locked(&state)?;
    repo::projects::set_status(&conn, &id, &status).map_err(|e| e.to_string())
}

// --- tasks ---

#[tauri::command]
pub fn list_tasks_by_project(state: State<AppState>, project_id: String) -> Result<Vec<Task>, String> {
    let conn = locked(&state)?;
    repo::tasks::list_by_project(&conn, &project_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_tasks_by_status(state: State<AppState>, status: String) -> Result<Vec<Task>, String> {
    let conn = locked(&state)?;
    repo::tasks::list_by_status(&conn, &status).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_task(state: State<AppState>, input: NewTask) -> Result<Task, String> {
    let conn = locked(&state)?;
    repo::tasks::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_task_status(state: State<AppState>, id: String, status: String) -> Result<Task, String> {
    let conn = locked(&state)?;
    repo::tasks::set_status(&conn, &id, &status).map_err(|e| e.to_string())
}

// --- agents ---

#[tauri::command]
pub fn list_agents(state: State<AppState>) -> Result<Vec<Agent>, String> {
    let conn = locked(&state)?;
    repo::agents::list(&conn).map_err(|e| e.to_string())
}

// --- approvals ---

#[tauri::command]
pub fn list_approvals(state: State<AppState>) -> Result<Vec<Approval>, String> {
    let conn = locked(&state)?;
    repo::approvals::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn decide_approval(
    state: State<AppState>,
    id: String,
    decision: String,
    note: Option<String>,
) -> Result<Approval, String> {
    let conn = locked(&state)?;
    repo::approvals::decide(&conn, &id, &decision, note.as_deref()).map_err(|e| e.to_string())
}

// --- notifications ---

#[tauri::command]
pub fn list_notifications(state: State<AppState>) -> Result<Vec<Notification>, String> {
    let conn = locked(&state)?;
    repo::notifications::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn mark_notification_read(state: State<AppState>, id: String) -> Result<Notification, String> {
    let conn = locked(&state)?;
    repo::notifications::mark_read(&conn, &id).map_err(|e| e.to_string())
}

// --- decisions ---

#[tauri::command]
pub fn list_decisions(state: State<AppState>) -> Result<Vec<Decision>, String> {
    let conn = locked(&state)?;
    repo::decisions::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_decision(state: State<AppState>, title: String, rationale: String) -> Result<Decision, String> {
    let conn = locked(&state)?;
    repo::decisions::create(&conn, &title, "gev", &rationale).map_err(|e| e.to_string())
}

// --- activity ---

#[tauri::command]
pub fn list_activity(state: State<AppState>) -> Result<Vec<ActivityEvent>, String> {
    let conn = locked(&state)?;
    repo::activity::list(&conn).map_err(|e| e.to_string())
}

// --- chat ---

#[tauri::command]
pub fn list_conversations(state: State<AppState>, kind: Option<String>) -> Result<Vec<Conversation>, String> {
    let conn = locked(&state)?;
    repo::chat::list_conversations(&conn, kind.as_deref()).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_conversation(state: State<AppState>, kind: String, title: String) -> Result<Conversation, String> {
    let conn = locked(&state)?;
    repo::chat::create_conversation(&conn, &kind, &title).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_messages(state: State<AppState>, conversation_id: String) -> Result<Vec<Message>, String> {
    let conn = locked(&state)?;
    repo::chat::list_messages(&conn, &conversation_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn post_message(state: State<AppState>, input: NewMessage) -> Result<Message, String> {
    let conn = locked(&state)?;
    repo::chat::post_message(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_conversation(state: State<AppState>, id: String) -> Result<(), String> {
    let conn = locked(&state)?;
    repo::chat::delete_conversation(&conn, &id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn rename_conversation(state: State<AppState>, id: String, title: String) -> Result<Conversation, String> {
    let conn = locked(&state)?;
    repo::chat::rename_conversation(&conn, &id, &title).map_err(|e| e.to_string())
}

// --- knowledge ---

#[tauri::command]
pub fn list_knowledge(state: State<AppState>) -> Result<Vec<KnowledgeNote>, String> {
    let conn = locked(&state)?;
    repo::knowledge::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn search_knowledge(state: State<AppState>, query: String) -> Result<Vec<KnowledgeNote>, String> {
    let conn = locked(&state)?;
    repo::knowledge::search(&conn, &query).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_knowledge(state: State<AppState>, input: NewKnowledgeNote) -> Result<KnowledgeNote, String> {
    let conn = locked(&state)?;
    repo::knowledge::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_knowledge(state: State<AppState>, id: String) -> Result<(), String> {
    let conn = locked(&state)?;
    repo::knowledge::delete(&conn, &id).map_err(|e| e.to_string())
}

// --- memory ---

#[tauri::command]
pub fn list_memory(state: State<AppState>, scope: Option<String>) -> Result<Vec<MemoryEntry>, String> {
    let conn = locked(&state)?;
    repo::memory::list(&conn, scope.as_deref()).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_memory(state: State<AppState>, input: NewMemoryEntry) -> Result<MemoryEntry, String> {
    let conn = locked(&state)?;
    repo::memory::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_memory_pinned(state: State<AppState>, id: String, pinned: bool) -> Result<MemoryEntry, String> {
    let conn = locked(&state)?;
    repo::memory::set_pinned(&conn, &id, pinned).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_memory(state: State<AppState>, id: String) -> Result<(), String> {
    let conn = locked(&state)?;
    repo::memory::delete(&conn, &id).map_err(|e| e.to_string())
}

// --- runs (command) ---

#[tauri::command]
pub fn list_runs(state: State<AppState>) -> Result<Vec<Run>, String> {
    let conn = locked(&state)?;
    repo::runs::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_run(state: State<AppState>, intent: String, plan: String) -> Result<Run, String> {
    let conn = locked(&state)?;
    repo::runs::create(&conn, &intent, &plan).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_run_status(state: State<AppState>, id: String, status: String) -> Result<Run, String> {
    let conn = locked(&state)?;
    repo::runs::set_status(&conn, &id, &status).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn list_run_steps(state: State<AppState>, run_id: String) -> Result<Vec<RunStep>, String> {
    let conn = locked(&state)?;
    repo::runs::list_steps(&conn, &run_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn add_run_step(
    state: State<AppState>,
    run_id: String,
    title: String,
    detail: String,
    requires_approval: bool,
) -> Result<RunStep, String> {
    let conn = locked(&state)?;
    // One transaction so a step asked to be gated is never persisted ungated.
    let tx = conn.unchecked_transaction().map_err(|e| e.to_string())?;
    let step = repo::runs::add_step(&tx, &run_id, &title, &detail).map_err(|e| e.to_string())?;
    let step = if requires_approval {
        repo::runs::set_step_requires_approval(&tx, &step.id, true).map_err(|e| e.to_string())?
    } else {
        step
    };
    tx.commit().map_err(|e| e.to_string())?;
    Ok(step)
}

#[tauri::command]
pub fn set_run_step_status(state: State<AppState>, id: String, status: String) -> Result<RunStep, String> {
    let conn = locked(&state)?;
    repo::runs::set_step_status(&conn, &id, &status).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn advance_run(state: State<AppState>, run_id: String) -> Result<Run, String> {
    let conn = locked(&state)?;
    repo::runs::advance(&conn, &run_id).map_err(|e| e.to_string())
}

// --- AI (live agent replies) ---

#[tauri::command]
pub async fn ai_status() -> Result<crate::ai::AiStatus, String> {
    Ok(crate::ai::status().await)
}

/// Events streamed to the frontend over a Tauri channel while an agent replies.
#[derive(Clone, serde::Serialize)]
#[serde(rename_all = "camelCase", tag = "type")]
pub enum StreamEvent {
    Delta { text: String },
    Done { message: Message },
    Error { message: String },
}

/// Streaming counterpart of `reply_in_conversation`: emits incremental `delta`
/// events as the agent produces text, then a `done` event carrying the
/// persisted message (or an `error` event). Returns Ok even on provider failure
/// — the failure is delivered as an `error` event so the UI can show it inline.
#[tauri::command]
pub async fn stream_reply(
    state: State<'_, AppState>,
    conversation_id: String,
    agent: Option<String>,
    on_event: tauri::ipc::Channel<StreamEvent>,
) -> Result<(), String> {
    let author = agent.unwrap_or_else(|| "Bro".to_string());
    let (system, history) = {
        let conn = locked(&state)?;
        let msgs = repo::chat::list_messages(&conn, &conversation_id).map_err(|e| e.to_string())?;
        let history: Vec<crate::ai::ChatMsg> = msgs
            .iter()
            .map(|m| crate::ai::ChatMsg {
                role: if m.role == "user" { "user".to_string() } else { "assistant".to_string() },
                content: m.body.clone(),
            })
            .collect();
        let system = format!(
            "You are {author}, a specialist agent inside the BroPS workspace — a personal AI operations desktop app for its owner, Gev. Reply concisely, directly, and helpfully to the latest message. Do not claim to have taken actions you cannot actually take."
        );
        (system, history)
    };
    if history.is_empty() {
        let _ = on_event.send(StreamEvent::Error { message: "nothing to reply to".into() });
        return Ok(());
    }
    let ch = on_event.clone();
    let result = crate::ai::generate_stream(&system, &history, move |delta| {
        let _ = ch.send(StreamEvent::Delta { text: delta.to_string() });
    })
    .await;
    match result {
        Ok(full) => {
            // Persist the reply. Any failure here must still deliver a terminal
            // event so the streaming UI never stays stuck "thinking".
            let persisted = {
                let conn = match locked(&state) {
                    Ok(c) => c,
                    Err(e) => {
                        let _ = on_event.send(StreamEvent::Error { message: e });
                        return Ok(());
                    }
                };
                repo::chat::post_message(
                    &conn,
                    NewMessage { conversation_id, role: "agent".to_string(), author, body: full },
                )
            };
            match persisted {
                Ok(message) => {
                    let _ = on_event.send(StreamEvent::Done { message });
                }
                Err(e) => {
                    let _ = on_event.send(StreamEvent::Error { message: e.to_string() });
                }
            }
        }
        Err(e) => {
            let _ = on_event.send(StreamEvent::Error { message: e });
        }
    }
    Ok(())
}

/// Events streamed while a run step is executed by the AI provider.
#[derive(Clone, serde::Serialize)]
#[serde(rename_all = "camelCase", tag = "type")]
pub enum RunStepEvent {
    Delta { text: String },
    Done,
    ApprovalRequired { approval_id: String },
    Error { message: String },
}

/// Outcome of the approval gate for the next runnable step.
enum Gate {
    Ok,
    Pending(String),
    Rejected,
}

/// Execute the next runnable step of a run: ask the AI provider to produce the
/// step's result, streaming it; then store the result (marking the step done)
/// and advance the run. Emits `delta` events, then `done` (or `error`). When no
/// step remains, emits `done` immediately.
#[tauri::command]
pub async fn stream_run_step(
    state: State<'_, AppState>,
    run_id: String,
    on_event: tauri::ipc::Channel<RunStepEvent>,
) -> Result<(), String> {
    let (intent, plan, step, gate) = {
        let conn = locked(&state)?;
        let run = repo::runs::get(&conn, &run_id).map_err(|e| e.to_string())?;
        if matches!(run.status.as_str(), "succeeded" | "failed" | "cancelled") {
            let _ = on_event.send(RunStepEvent::Error { message: format!("run is {}", run.status) });
            return Ok(());
        }
        let step = repo::runs::next_runnable_step(&conn, &run_id).map_err(|e| e.to_string())?;
        // Approval gate: a step flagged requires_approval may not run until an
        // approval for it has been granted. A prior rejection is terminal; if no
        // decision exists yet, request one and move the run to awaiting_approval.
        let gate: Gate = match &step {
            Some(s) if s.requires_approval => {
                if repo::approvals::approved_for(&conn, &s.id).map_err(|e| e.to_string())? {
                    Gate::Ok
                } else if repo::approvals::rejected_for(&conn, &s.id).map_err(|e| e.to_string())? {
                    let _ = repo::runs::set_step_status(&conn, &s.id, "failed");
                    let _ = repo::runs::set_status(&conn, &run_id, "failed");
                    Gate::Rejected
                } else if let Some(pending) =
                    repo::approvals::pending_for(&conn, &s.id).map_err(|e| e.to_string())?
                {
                    Gate::Pending(pending.id)
                } else {
                    let ap = repo::approvals::create(
                        &conn,
                        "Execute run step",
                        &s.title,
                        "A2",
                        "medium",
                        "gev",
                        Some("run_step"),
                        Some(&s.id),
                    )
                    .map_err(|e| e.to_string())?;
                    let _ = repo::runs::set_status(&conn, &run_id, "awaiting_approval");
                    Gate::Pending(ap.id)
                }
            }
            _ => Gate::Ok,
        };
        (run.intent, run.plan, step, gate)
    };
    match gate {
        Gate::Rejected => {
            let _ = on_event.send(RunStepEvent::Error { message: "approval was rejected for this step".into() });
            return Ok(());
        }
        Gate::Pending(approval_id) => {
            let _ = on_event.send(RunStepEvent::ApprovalRequired { approval_id });
            return Ok(());
        }
        Gate::Ok => {}
    }
    let step = match step {
        Some(s) => s,
        None => {
            let _ = on_event.send(RunStepEvent::Done);
            return Ok(());
        }
    };

    let system = "You are an execution agent inside the BroPS workspace — a personal AI operations desktop app for its owner, Gev. Produce the concrete result/output for the current step of a run. Be concise and practical; output only the deliverable for THIS step, not meta commentary.".to_string();
    let user = format!(
        "Goal (intent): {intent}\n\nOverall plan: {plan}\n\nCurrent step to execute: {}\n\nProduce the result for this step now.",
        step.title
    );
    let history = vec![crate::ai::ChatMsg { role: "user".to_string(), content: user }];
    let ch = on_event.clone();
    match crate::ai::generate_stream(&system, &history, move |delta| {
        let _ = ch.send(RunStepEvent::Delta { text: delta.to_string() });
    })
    .await
    {
        Ok(full) => {
            let outcome = {
                let conn = match locked(&state) {
                    Ok(c) => c,
                    Err(e) => {
                        let _ = on_event.send(RunStepEvent::Error { message: e });
                        return Ok(());
                    }
                };
                // Re-check under the re-acquired lock: while we streamed, the run
                // may have been cancelled/finished, or this step may already have
                // been executed by a concurrent run. Bail without a half-write.
                match repo::runs::get(&conn, &run_id) {
                    Ok(run) if matches!(run.status.as_str(), "succeeded" | "failed" | "cancelled") => {
                        let _ = on_event.send(RunStepEvent::Error { message: format!("run is {}", run.status) });
                        return Ok(());
                    }
                    Err(e) => {
                        let _ = on_event.send(RunStepEvent::Error { message: e.to_string() });
                        return Ok(());
                    }
                    _ => {}
                }
                match repo::runs::get_step(&conn, &step.id) {
                    Ok(st) if st.status == "done" => {
                        let _ = on_event.send(RunStepEvent::Done);
                        return Ok(());
                    }
                    Err(e) => {
                        let _ = on_event.send(RunStepEvent::Error { message: e.to_string() });
                        return Ok(());
                    }
                    _ => {}
                }
                repo::runs::set_step_result(&conn, &step.id, &full)
                    .and_then(|_| repo::runs::advance(&conn, &run_id))
            };
            match outcome {
                Ok(_) => {
                    let _ = on_event.send(RunStepEvent::Done);
                }
                Err(e) => {
                    let _ = on_event.send(RunStepEvent::Error { message: e.to_string() });
                }
            }
        }
        Err(e) => {
            let _ = on_event.send(RunStepEvent::Error { message: e });
        }
    }
    Ok(())
}

/// One-shot "Ask Bro": stream an answer to a single prompt WITHOUT a
/// conversation or persistence. Deltas arrive on the channel; completion is
/// signalled by the command returning (no `done` event, nothing is stored).
#[tauri::command]
pub async fn stream_ask(prompt: String, on_event: tauri::ipc::Channel<StreamEvent>) -> Result<(), String> {
    let prompt = prompt.trim().to_string();
    if prompt.is_empty() {
        let _ = on_event.send(StreamEvent::Error { message: "empty prompt".into() });
        return Ok(());
    }
    let system = "You are Bro, the top-level assistant in the BroPS desktop app for its owner, Gev. Answer the question concisely and helpfully. Do not claim to have taken actions you cannot actually take.".to_string();
    let history = vec![crate::ai::ChatMsg { role: "user".to_string(), content: prompt }];
    let ch = on_event.clone();
    if let Err(e) = crate::ai::generate_stream(&system, &history, move |delta| {
        let _ = ch.send(StreamEvent::Delta { text: delta.to_string() });
    })
    .await
    {
        let _ = on_event.send(StreamEvent::Error { message: e });
    }
    Ok(())
}

/// Generate a real agent reply for a conversation and persist it as an
/// `agent`-role message. Reads history under the DB lock, releases it before
/// the network call (so the future stays Send and the UI stays responsive),
/// then writes the reply under the lock again.
#[tauri::command]
pub async fn reply_in_conversation(
    state: State<'_, AppState>,
    conversation_id: String,
    agent: Option<String>,
) -> Result<Message, String> {
    let author = agent.unwrap_or_else(|| "Bro".to_string());
    let (system, history) = {
        let conn = locked(&state)?;
        let msgs = repo::chat::list_messages(&conn, &conversation_id).map_err(|e| e.to_string())?;
        let history: Vec<crate::ai::ChatMsg> = msgs
            .iter()
            .map(|m| crate::ai::ChatMsg {
                role: if m.role == "user" { "user".to_string() } else { "assistant".to_string() },
                content: m.body.clone(),
            })
            .collect();
        let system = format!(
            "You are {author}, a specialist agent inside the BroPS workspace — a personal AI operations desktop app for its owner, Gev. Reply concisely, directly, and helpfully to the latest message. Do not claim to have taken actions you cannot actually take."
        );
        (system, history)
    };
    if history.is_empty() {
        return Err("nothing to reply to".to_string());
    }
    let text = crate::ai::generate(&system, &history).await?;
    let conn = locked(&state)?;
    repo::chat::post_message(
        &conn,
        NewMessage { conversation_id, role: "agent".to_string(), author, body: text },
    )
    .map_err(|e| e.to_string())
}

// --- events (calendar) ---

#[tauri::command]
pub fn list_events(state: State<AppState>) -> Result<Vec<Event>, String> {
    let conn = locked(&state)?;
    repo::events::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_event(state: State<AppState>, input: NewEvent) -> Result<Event, String> {
    let conn = locked(&state)?;
    repo::events::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_event(state: State<AppState>, id: String) -> Result<(), String> {
    let conn = locked(&state)?;
    repo::events::delete(&conn, &id).map_err(|e| e.to_string())
}

// --- automations ---

#[tauri::command]
pub fn list_automations(state: State<AppState>) -> Result<Vec<Automation>, String> {
    let conn = locked(&state)?;
    repo::automations::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn create_automation(state: State<AppState>, input: NewAutomation) -> Result<Automation, String> {
    let conn = locked(&state)?;
    repo::automations::create(&conn, input).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_automation_enabled(state: State<AppState>, id: String, enabled: bool) -> Result<Automation, String> {
    let conn = locked(&state)?;
    repo::automations::set_enabled(&conn, &id, enabled).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_automation(state: State<AppState>, id: String) -> Result<(), String> {
    let conn = locked(&state)?;
    repo::automations::delete(&conn, &id).map_err(|e| e.to_string())
}

// --- integrations ---

#[tauri::command]
pub fn list_integrations(state: State<AppState>) -> Result<Vec<Integration>, String> {
    let conn = locked(&state)?;
    repo::integrations::list(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_integration_status(state: State<AppState>, id: String, status: String) -> Result<Integration, String> {
    let conn = locked(&state)?;
    repo::integrations::set_status(&conn, &id, &status).map_err(|e| e.to_string())
}

// --- global search ---

#[tauri::command]
pub fn search_all(state: State<AppState>, query: String) -> Result<Vec<SearchResult>, String> {
    let conn = locked(&state)?;
    repo::search::global(&conn, &query).map_err(|e| e.to_string())
}

// --- analytics / security (computed, read-only) ---

#[tauri::command]
pub fn get_analytics(state: State<AppState>) -> Result<Vec<Metric>, String> {
    let conn = locked(&state)?;
    repo::analytics::metrics(&conn).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_security_summary(state: State<AppState>) -> Result<SecuritySummary, String> {
    let conn = locked(&state)?;
    repo::security::summary(&conn).map_err(|e| e.to_string())
}
