import React from 'react';
import './ui.css';
import { statusTone, type Tone } from '../domain/enums';

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
export function Button({ children, variant = 'default', small, onClick, title, type = 'button' }:
  { children: React.ReactNode; variant?: BtnVariant; small?: boolean; onClick?: () => void; title?: string; type?: 'button' | 'submit' }) {
  const cls = variant === 'default' ? '' : `btn--${variant}`;
  return <button type={type} title={title} className={`btn ${cls} ${small ? 'btn--sm' : ''}`} onClick={onClick}>{children}</button>;
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
