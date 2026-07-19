import { AppProvider, useApp } from './app/store';
import { Shell } from './components/Shell';
import { CommandPalette } from './components/CommandPalette';
import { ToastProvider, Toaster } from './components/toast';
import { Screen } from './features/registry';
import { hasBackend } from './services/desktop';

function AppInner() {
  const { route, t } = useApp();
  return (
    <>
      {!hasBackend() && <div className="offline-banner" role="status">{t('state.offlineBanner')}</div>}
      <Shell>
        <Screen route={route} />
      </Shell>
      <CommandPalette />
      <Toaster />
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
