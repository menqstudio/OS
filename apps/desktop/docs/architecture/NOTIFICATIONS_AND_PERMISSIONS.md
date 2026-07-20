# Notifications and Permissions

## Notifications
Channels: in-app inbox, desktop notification, badge and optional email integration.
Types: approval required, run completed, run failed, task due, mention, assignment, automation result, security warning and backup status.
Each notification stores severity, source entity, created/read timestamps, action target and deduplication key. Users can configure per-type channel, quiet hours and digest behavior.

## Permission model
Roles: Owner, Admin, Member, Viewer, Agent and Service.
Scopes: workspace, project, conversation, file, task, automation, provider, secret and system setting.
Actions: view, create, edit, delete, execute, approve, export, manage members and manage secrets.
Rules are deny-by-default and evaluated from explicit grants plus ownership. Sensitive actions require fresh authorization and audit events.

## Mandatory approval gates
- File deletion or overwrite
- External message/send/publish
- Secret access or provider-key changes
- Destructive database actions
- Automation enabling with external side effects
- High-cost or high-risk AI runs
- Permission changes

All grants, denials, approvals and notification deliveries MUST be auditable.
