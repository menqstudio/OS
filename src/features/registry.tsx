import React from 'react';
import type { RouteId } from '../app/nav';
import { Home } from './Home';
import { Generic } from './Generic';
import { Chat } from './Chat';
import { GroupChat } from './GroupChat';
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
  chat: Chat,
  groupChat: GroupChat,
  projects: Projects,
  tasks: Tasks,
  agents: Agents,
  approvals: Approvals,
  notifications: Notifications,
  decisions: Decisions,
  activity: Activity,
};

export function Screen({ route }: { route: RouteId }) {
  const C = screens[route];
  return C ? <C /> : <Generic route={route} />;
}
