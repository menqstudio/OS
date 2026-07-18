import { AppProvider, useApp } from './app/store';
import { Shell } from './components/Shell';
import { CommandPalette } from './components/CommandPalette';
import { Screen } from './features/registry';

function AppInner() {
  const { route } = useApp();
  return (
    <>
      <Shell>
        <Screen route={route} />
      </Shell>
      <CommandPalette />
    </>
  );
}

export function App() {
  return (
    <AppProvider>
      <AppInner />
    </AppProvider>
  );
}
