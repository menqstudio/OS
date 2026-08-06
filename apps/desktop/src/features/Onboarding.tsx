import { useState } from 'react';
import { useApp } from '../app/store';
import { Modal, Button } from '../components/ui';
import { STR } from './Onboarding.strings';

// First-run onboarding: a short, honest, 3-step intro shown ONCE. Gated on a localStorage flag
// (consistent with how theme/language are stored — no backend, no DB), so it never reappears after
// it is completed or skipped. Dismissing via the scrim counts as "seen".
const STORAGE_KEY = 'brops.onboarded';

const STEPS = [
  { title: 'welcomeTitle', body: 'welcomeBody' },
  { title: 'howTitle', body: 'howBody' },
  { title: 'honestTitle', body: 'honestBody' },
] as const;

function seenOnboarding(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    // storage unavailable (private mode / sandbox) — don't nag; treat as seen.
    return true;
  }
}

export function Onboarding() {
  const { lang } = useApp();
  const L = (k: keyof typeof STR) => STR[k][lang] ?? STR[k].en;
  const [open, setOpen] = useState(() => !seenOnboarding());
  const [step, setStep] = useState(0);

  if (!open) return null;

  const finish = () => {
    try {
      window.localStorage.setItem(STORAGE_KEY, '1');
    } catch {
      /* ignore — the in-memory `open=false` still dismisses it for this session */
    }
    setOpen(false);
  };

  const s = STEPS[step];
  const isLast = step === STEPS.length - 1;

  return (
    <Modal title={L(s.title)} onClose={finish}>
      <p style={{ margin: '0 0 18px', lineHeight: 1.6, maxWidth: '54ch' }}>{L(s.body)}</p>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <span className="micro muted">{L('stepOf')} {step + 1}/{STEPS.length}</span>
        <div style={{ display: 'flex', gap: 8 }}>
          {step > 0 && (
            <Button variant="ghost" onClick={() => setStep((n) => n - 1)}>{L('back')}</Button>
          )}
          {!isLast && (
            <Button variant="ghost" onClick={finish}>{L('skip')}</Button>
          )}
          {isLast ? (
            <Button variant="primary" onClick={finish}>{L('done')}</Button>
          ) : (
            <Button variant="primary" onClick={() => setStep((n) => n + 1)}>{L('next')}</Button>
          )}
        </div>
      </div>
    </Modal>
  );
}
