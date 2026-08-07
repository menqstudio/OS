import React from 'react';
import type { RouteId } from '../app/nav';

/**
 * NavIcons — a crisp, self-consistent set of 24×24 stroke icons (Feather/Lucide
 * idiom) for every left-nav RouteId. Each glyph is `stroke="currentColor"` so it
 * inherits the nav item's colour, `fill="none"`, ~1.6px strokes with round caps
 * and joins so it stays legible at 16–18px. Pure presentation — `aria-hidden`.
 */

/** The route → glyph body. Only the inner paths; the <svg> frame is shared. */
function glyph(id: RouteId): React.ReactNode {
  switch (id) {
    case 'home':
      return (
        <>
          <path d="M3 10.5 12 3l9 7.5" />
          <path d="M5 9.5V20h14V9.5" />
          <path d="M9.5 20v-6h5v6" />
        </>
      );
    case 'command':
      return (
        <>
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="m7 9 3 3-3 3" />
          <path d="M13 15h4" />
        </>
      );
    case 'chat':
      return <path d="M20 12a8 8 0 0 1-8 8 8.4 8.4 0 0 1-3.8-.9L4 20l1.1-3.6A8 8 0 1 1 20 12Z" />;
    case 'groupChat':
      return (
        <>
          <path d="M8 12H5l-2 2V6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v1" />
          <path d="M11 17h6l2 2v-6a2 2 0 0 0-2-2h-6a2 2 0 0 0-2 2v2a2 2 0 0 0 2 2Z" />
        </>
      );
    case 'projects':
      return (
        <>
          <path d="m12 3 9 5-9 5-9-5 9-5Z" />
          <path d="m3 13 9 5 9-5" />
        </>
      );
    case 'tasks':
      return (
        <>
          <rect x="4" y="4" width="16" height="16" rx="2.5" />
          <path d="m8.5 12 2.4 2.4L16 9" />
        </>
      );
    case 'agents':
      return (
        <>
          <circle cx="12" cy="5" r="2.4" />
          <circle cx="6" cy="18" r="2.4" />
          <circle cx="18" cy="18" r="2.4" />
          <path d="M10.7 7 7.3 15.8" />
          <path d="M13.3 7 16.7 15.8" />
          <path d="M8.4 18h7.2" />
        </>
      );
    case 'knowledge':
      return (
        <>
          <path d="M12 6c-1.5-1.3-3.7-2-6-2-1 0-1.9.1-3 .4v13c1.1-.3 2-.4 3-.4 2.3 0 4.5.7 6 2" />
          <path d="M12 6c1.5-1.3 3.7-2 6-2 1 0 1.9.1 3 .4v13c-1.1-.3-2-.4-3-.4-2.3 0-4.5.7-6 2" />
          <path d="M12 6v14" />
        </>
      );
    case 'memory':
      return (
        <>
          <rect x="7" y="7" width="10" height="10" rx="1.5" />
          <rect x="10.5" y="10.5" width="3" height="3" rx="0.5" />
          <path d="M10 3v2M14 3v2M10 19v2M14 19v2M3 10h2M3 14h2M19 10h2M19 14h2" />
        </>
      );
    case 'decisions':
      return (
        <>
          <path d="M12 4v15" />
          <path d="M8.5 19h7" />
          <path d="M5 7h14" />
          <path d="M5 7 2.6 12a2.4 2.4 0 0 0 4.8 0L5 7Z" />
          <path d="M19 7l-2.4 5a2.4 2.4 0 0 0 4.8 0L19 7Z" />
        </>
      );
    case 'bridge':
      // A suspension bridge: two piers, the deck, the main cable and its hangers.
      return (
        <>
          <path d="M3 15h18" />
          <path d="M3 15V9" />
          <path d="M21 15V9" />
          <path d="M3 11.5a9 9 0 0 1 18 0" />
          <path d="M8 15v-3.3" />
          <path d="M12 15V9.7" />
          <path d="M16 15v-3.3" />
        </>
      );
    case 'research':
      return (
        <>
          <circle cx="11" cy="11" r="6" />
          <path d="m20 20-3.6-3.6" />
        </>
      );
    case 'library':
      return (
        <>
          <rect x="4" y="4" width="4" height="16" rx="1" />
          <rect x="10" y="4" width="4" height="16" rx="1" />
          <rect x="16" y="4" width="4" height="16" rx="1" />
          <path d="M4 9h16M4 15h16" />
        </>
      );
    case 'calendar':
      return (
        <>
          <rect x="3.5" y="5" width="17" height="15" rx="2" />
          <path d="M3.5 9.5h17" />
          <path d="M8 3v4M16 3v4" />
          <path d="M7.5 13h1.5M11.25 13h1.5M15 13h1.5M7.5 16.5h1.5M11.25 16.5h1.5" />
        </>
      );
    case 'automations':
      return <path d="M13 3 5 13.5h5.5L11 21l8-10.5h-5.5L14 3Z" />;
    case 'approvals':
      return (
        <>
          <path d="M12 3 5 6v5.5c0 4.3 3 7.6 7 9 4-1.4 7-4.7 7-9V6l-7-3Z" />
          <path d="m9 11.8 2.2 2.2L15.5 9.7" />
        </>
      );
    case 'activity':
      return <path d="M3 12h4l2.5-6.5 4.5 13L16.5 12H21" />;
    case 'notifications':
      return (
        <>
          <path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6Z" />
          <path d="M10 20a2 2 0 0 0 4 0" />
        </>
      );
    case 'files':
      return <path d="M3 6.5a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6.5Z" />;
    case 'integrations':
      return (
        <>
          <path d="M9 3v5M15 3v5" />
          <path d="M7 8h10v3a5 5 0 0 1-10 0V8Z" />
          <path d="M12 16v5" />
        </>
      );
    case 'analytics':
      return (
        <>
          <path d="M5 4v16h15" />
          <path d="M9 20v-6M13 20v-9M17 20v-4" />
        </>
      );
    case 'security':
      return (
        <>
          <rect x="4.5" y="10" width="15" height="10" rx="2" />
          <path d="M8 10V7a4 4 0 0 1 8 0v3" />
          <path d="M12 14v2.5" />
        </>
      );
    case 'settings':
      return (
        <>
          <circle cx="12" cy="12" r="3" />
          <path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.3a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.8l-.2.3a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.7l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.3a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.3a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.7v-.5a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.3a2 2 0 0 0-2.7-.8l-.2.1a2 2 0 0 1-2 0l-.4-.3a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2Z" />
        </>
      );
    default:
      return <circle cx="12" cy="12" r="8" />;
  }
}

/** A single left-nav icon. Sizes to its `<i>` box (see `.nav a i svg`). */
export function NavIcon({ id }: { id: RouteId }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {glyph(id)}
    </svg>
  );
}
