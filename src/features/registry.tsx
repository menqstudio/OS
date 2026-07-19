import React from 'react';
import type { RouteId } from '../app/nav';
import { Home } from './Home';
import { Generic } from './Generic';
import { Command } from './Command';
import { Chat } from './Chat';
import { GroupChat } from './GroupChat';
import { Knowledge } from './Knowledge';
import { Memory } from './Memory';
import { Files } from './Files';
import { Calendar } from './Calendar';
import { Automations } from './Automations';
import { Integrations } from './Integrations';
import { Analytics } from './Analytics';
import { Security } from './Security';
import { Projects } from './Projects';
import { Tasks } from './Tasks';
import { Agents } from './Agents';
import { Approvals } from './Approvals';
import { Notifications } from './Notifications';
import { Decisions } from './Decisions';
import { Activity } from './Activity';

// Screens backed by real Tauri commands (SQLite). Everything else falls through
// to <Generic>, which honestly reports that the workspace has no backend yet.
const screens: Partial<Record<RouteId, React.FC>> = {
  home: Home,
  command: Command,
  chat: Chat,
  groupChat: GroupChat,
  projects: Projects,
  tasks: Tasks,
  agents: Agents,
  knowledge: Knowledge,
  memory: Memory,
  decisions: Decisions,
  calendar: Calendar,
  automations: Automations,
  approvals: Approvals,
  activity: Activity,
  notifications: Notifications,
  files: Files,
  integrations: Integrations,
  analytics: Analytics,
  security: Security,
};

export function Screen({ route }: { route: RouteId }) {
  const C = screens[route];
  return C ? <C /> : <Generic route={route} />;
}
