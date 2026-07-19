import React from 'react';
import './ui.css';
import { statusTone, type Tone } from '../domain/enums';
import type { AsyncState } from '../hooks/useAsync';

export function Card({ children, className = '', style }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return <div className={`card ${className}`} style={style}>{children}</div>;
}

export function Panel({ title, actions, children }: { title?: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card>
      <div className="panel">
        {(title || actions) && (
          <div className="panel-head">
            {title && <div className="panel-title">{title}</div>}
            {actions}
          </div>
        )}
        {children}
      </div>
    </Card>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <div className="page-title">{title}</div>
        {subtitle && <div className="page-subtitle">{subtitle}</div>}
      </div>
      {actions}
    </div>
  );
}

type BtnVariant = 'default' | 'primary' | 'danger' | 'ghost';
export function Button({ children, variant = 'default', small, onClick, title, type = 'button', disabled }:
  { children: React.ReactNode; variant?: BtnVariant; small?: boolean; onClick?: () => void; title?: string; type?: 'button' | 'submit'; disabled?: boolean }) {
  const cls = variant === 'default' ? '' : `btn--${variant}`;
  return <button type={type} title={title} disabled={disabled} className={`btn ${cls} ${small ? 'btn--sm' : ''}`} onClick={onClick}>{children}</button>;
}

export function Badge({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: Tone }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function StatusPill({ status }: { status: string }) {
  const tone = statusTone[status] ?? 'neutral';
  return <Badge tone={tone}>{status.replace(/_/g, ' ')}</Badge>;
}

export function EmptyState({ title, hint, glyph = '◍' }: { title: string; hint?: string; glyph?: string }) {
  return (
    <div className="empty">
      <div className="empty-glyph">{glyph}</div>
      <div className="empty-title">{title}</div>
      {hint && <div className="muted" style={{ marginTop: 4 }}>{hint}</div>}
    </div>
  );
}

export function Avatar({ name }: { name: string }) {
  return <span className="avatar">{name.slice(0, 1).toUpperCase()}</span>;
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <span>{children}</span>
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: 18, width: `${90 - i * 8}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ message, onRetry, retryLabel = 'Retry' }: { message: string; onRetry?: () => void; retryLabel?: string }) {
  return (
    <div className="empty">
      <div className="empty-glyph" style={{ color: 'var(--menq-color-danger)' }}>⚠</div>
      <div className="empty-title">Couldn’t load from the backend</div>
      <div className="muted" style={{ marginTop: 4, maxWidth: 460, marginInline: 'auto' }}>{message}</div>
      {onRetry && <div style={{ marginTop: 12 }}><Button small onClick={onRetry}>{retryLabel}</Button></div>}
    </div>
  );
}

/** Uniform loading / error / empty / populated rendering around a list command. */
export function Async<T>({
  state,
  emptyTitle = 'Nothing here yet',
  emptyHint,
  children,
}: {
  state: AsyncState<T[]>;
  emptyTitle?: string;
  emptyHint?: string;
  children: (data: T[]) => React.ReactNode;
}) {
  if (state.loading && state.data === null) return <Skeleton rows={4} />;
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  const data = state.data ?? [];
  if (data.length === 0) return <EmptyState title={emptyTitle} hint={emptyHint} />;
  return <>{children(data)}</>;
}

export function FormRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="form-row">
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className="input" {...props} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className="textarea" {...props} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className="select" {...props} />;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="modal-title">{title}</div>
        {children}
      </div>
    </div>
  );
}

/** Destructive-action confirmation. Blocks a delete/overwrite behind an
 *  explicit second step so nothing irreversible happens on a single click. */
export function ConfirmDialog({
  title, message, confirmLabel, cancelLabel, onConfirm, onCancel,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal title={title} onClose={onCancel}>
      <div className="muted" style={{ marginBottom: 16 }}>{message}</div>
      <div className="form-actions">
        <Button variant="ghost" onClick={onCancel}>{cancelLabel}</Button>
        <Button variant="danger" onClick={onConfirm}>{confirmLabel}</Button>
      </div>
    </Modal>
  );
}
