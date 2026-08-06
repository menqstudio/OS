import { AppProvider, useApp } from './app/store';
import { Shell } from './components/Shell';
import { CommandPalette } from './components/CommandPalette';
import { ToastProvider, Toaster } from './components/toast';
import { Screen } from './features/registry';
import { Onboarding } from './features/Onboarding';
import { hasBackend } from './services/desktop';

function AppInner() {
  const { route, t } = useApp();
  return (
    <>
      {/* First focusable element: lets keyboard/screen-reader users jump past
          the sidebar + topbar straight to the routed screen. Target is the
          <main id="main-content"> rendered by Shell. */}
      <a className="skip-link" href="#main-content">{t('a11y.skipToContent')}</a>
      {!hasBackend() && <div className="offline-banner" role="status">{t('state.offlineBanner')}</div>}
      <Shell>
        <Screen route={route} />
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
