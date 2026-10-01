import { AppProvider, useApp } from './app/store';
import { Shell } from './components/Shell';
import { CommandPalette } from './components/CommandPalette';
import { ToastProvider, Toaster } from './components/toast';
import { RouteView } from './app/routes';
import { Onboarding } from './features/Onboarding';

function AppInner() {
  const { route, t } = useApp();
  return (
    <>
      {/* First focusable element: lets keyboard/screen-reader users jump past
          the sidebar + topbar straight to the routed screen. Target is the
          <main id="main-content"> rendered by Shell. */}
      <a className="skip-link" href="#main-content">{t('a11y.skipToContent')}</a>
      {/* No no-backend banner here. There were two — this one ("Preview mode … Changes will not be
          saved.") and the Shell's — rendered together with different wording, and the Shell's said
          each panel shows an error state while the panels show the calm offline one. The Shell
          keeps the single banner; see the comment there. */}
      <Shell>
        <RouteView route={route} />
      </Shell>
      <CommandPalette />
      <Toaster />
      {/* First-run onboarding overlay (localStorage-gated; shows once). */}
      <Onboarding />
    </>
  );
}

export function App() {
  return (
    <AppProvider>
      <ToastProvider>
        <AppInner />
      </ToastProvider>
    </AppProvider>
  );
}
