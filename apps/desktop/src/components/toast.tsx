// Lightweight toast notifications. `ToastProvider` holds the queue, `useToast`
// returns a `toast(message, tone?)` function usable from any screen, and
// `<Toaster/>` renders the stack (auto-dismiss, click to dismiss). No external
// dependency — just React context + timers.

import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';

export type ToastTone = 'success' | 'error' | 'info';

export interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

type ToastFn = (message: string, tone?: ToastTone) => void;

interface ToastContextValue {
  toasts: ToastItem[];
  toast: ToastFn;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

/** How long a toast stays on screen before auto-dismissing (ms). */
const TOAST_TTL = 3000;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((ts) => ts.filter((x) => x.id !== id));
  }, []);

  const toast = useCallback<ToastFn>((message, tone = 'info') => {
    const id = (nextId.current += 1);
    setToasts((ts) => [...ts, { id, message, tone }]);
    window.setTimeout(() => dismiss(id), TOAST_TTL);
  }, [dismiss]);

  const value = useMemo<ToastContextValue>(() => ({ toasts, toast, dismiss }), [toasts, toast, dismiss]);

  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

/** Returns `toast(message, tone?)`. Must be called under a `ToastProvider`. */
export function useToast(): ToastFn {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx.toast;
}

/** Renders the current toast stack (bottom-right). Safe to render anywhere
 * inside the provider. */
export function Toaster() {
  const ctx = useContext(ToastContext);
  if (!ctx) return null;
  const { toasts, dismiss } = ctx;
  return (
    <div className="toaster" aria-live="polite" aria-atomic="false">
      {toasts.map((tst) => (
        <button
          key={tst.id}
          type="button"
          className={`toast toast--${tst.tone}`}
          onClick={() => dismiss(tst.id)}
        >
          {tst.message}
        </button>
      ))}
    </div>
  );
}
