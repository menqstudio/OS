import { AppProvider, useApp } from './app/store';
import { Shell } from './components/Shell';
import { CommandPalette } from './components/CommandPalette';
import { ToastProvider, Toaster } from './components/toast';
import { Screen } from './features/registry';

function AppInner() {
  const { route } = useApp();
  return (
    <>
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
