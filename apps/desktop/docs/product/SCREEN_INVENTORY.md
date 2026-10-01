- **Purpose:** Enumerate every primary workspace, global surface, and required screen state in BroPS.
- **Scope:** Canonical screen and surface inventory plus mandatory state coverage. Trilingual product surface (HY/EN/RU).
- **Owner:** Gev.
- **Related:** [NAVIGATION.md](NAVIGATION.md), [WORKSPACES.md](WORKSPACES.md), [GROUP_CHAT.md](GROUP_CHAT.md), [SEARCH_AND_COMMAND_PALETTE.md](SEARCH_AND_COMMAND_PALETTE.md), [USER_FLOWS.md](USER_FLOWS.md), [../architecture/ARCHITECTURE.md](../architecture/ARCHITECTURE.md), [../architecture/DESIGN_SYSTEM.md](../architecture/DESIGN_SYSTEM.md).
- **Last updated:** 2026-07-19.

# BroPS Screen Inventory / Էկրանների ամբողջական ցանկ

Status: Draft canonical

## Primary Workspaces / Հիմնական աշխատանքային տարածքներ

1. Home / Գլխավոր
2. Command / Հրաման
3. Chat / Զրույց
4. Group Chat / Խմբային զրույց
5. Projects / Նախագծեր
6. Tasks / Առաջադրանքներ
7. Agents / Ագենտներ
8. Knowledge / Գիտելիք
9. Memory / Հիշողություն
10. Decisions / Որոշումներ
11. Research / Հետազոտություն
12. Library / Գրադարան
13. Calendar / Օրացույց
14. Automations / Ավտոմատացումներ
15. Approvals / Հաստատումներ
16. Activity / Գործունեություն
17. Notifications / Ծանուցումներ
18. Files / Ֆայլեր
19. Integrations / Ինտեգրացիաներ
20. Analytics / Վերլուծություն
21. Security / Անվտանգություն
22. Settings / Կարգավորումներ
23. Bridge / Կամուրջ — in the sidebar's Intelligence group, after Decisions; routed (`bridge` in `src/app/nav.ts`) after this inventory was drafted, so the 22-screen counts in the sibling documents predate it · sidebar-ի Intelligence խմբում՝ Decisions-ից հետո. ավելացվել ա այս ցանկը գրելուց հետո

## Global Surfaces / Համընդհանուր մակերեսներ

- Global search
- Command palette
- Ask Bro panel
- Notification center
- Approval drawer
- Agent drawer
- Project drawer
- Task drawer
- File preview
- Context inspector
- Execution log

## Required State Coverage / Պարտադիր վիճակներ

Every screen MUST define the ten canonical states in [STATES.md](STATES.md) — loading, empty, populated, error, offline, permission-denied, blocked, awaiting-approval, destructive-confirmation and success — each wherever its "When it applies" condition there can occur. A read-only screen (Activity, Analytics) has no destructive action and therefore no destructive-confirmation. This section listed eight and omitted blocked and awaiting-approval.

Յուրաքանչյուր էկրան ՊԵՏՔ Է ունենա [STATES.md](STATES.md)-ի տասը կանոնական վիճակները՝ loading, empty, populated, error, offline, permission-denied, blocked, awaiting-approval, destructive-confirmation և success՝ ամեն մեկն այնտեղ, որտեղ նրա «When it applies» պայմանը կարող է առաջանալ։ Միայն կարդացվող էկրանը (Activity, Analytics) destructive գործողություն չունի, ուրեմն նաև destructive-confirmation չունի։ Այս բաժինը թվարկում էր ութը՝ առանց blocked-ի ու awaiting-approval-ի։
