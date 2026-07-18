import React from 'react';
import type { RouteId } from '../app/nav';
import { Home } from './Home';
import { Generic } from './Generic';
import { Command } from './Command';
import { Chat } from './Chat';
import { GroupChat } from './GroupChat';
import { Projects } from './Projects';
import { Tasks } from './Tasks';
import { Agents } from './Agents';
import { Approvals } from './Approvals';
import { Notifications } from './Notifications';
import { Decisions } from './Decisions';
import { Knowledge } from './Knowledge';
import { Memory } from './Memory';
import { Activity } from './Activity';
import { Settings } from './Settings';

const screens: Partial<Record<RouteId, React.FC>> = {
  home: Home,
  command: Command,
  chat: Chat,
  groupChat: GroupChat,
  projects: Projects,
  tasks: Tasks,
  agents: Agents,
  approvals: Approvals,
  notifications: Notifications,
  decisions: Decisions,
  knowledge: Knowledge,
  memory: Memory,
  activity: Activity,
  settings: Settings,
};

export function Screen({ route }: { route: RouteId }) {
  const C = screens[route];
  return C ? <C /> : <Generic route={route} />;
}
