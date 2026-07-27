import { describe, it, expect } from 'vitest';
import {
  statusTone,
  TASK_STATUSES,
  PRIORITIES,
  PROJECT_STATUSES,
  MEMORY_KINDS,
  RUN_STATUSES,
  INTEGRATION_STATUSES,
  STEP_STATUSES,
  type Tone,
} from './enums';

/** Pure data/vocabulary tests — no React, no Tauri, no context. */

describe('statusTone map', () => {
  it('maps representative statuses to the expected visual tone', () => {
    expect(statusTone.inbox).toBe('neutral');
    expect(statusTone.active).toBe('accent');
    expect(statusTone.running).toBe('accent');
    expect(statusTone.blocked).toBe('danger');
    expect(statusTone.review).toBe('warning');
    expect(statusTone.done).toBe('success');
    expect(statusTone.succeeded).toBe('success');
    expect(statusTone.failed).toBe('danger');
    expect(statusTone.awaiting_approval).toBe('warning');
    expect(statusTone.pending).toBe('warning');
    expect(statusTone.approved).toBe('success');
    expect(statusTone.rejected).toBe('danger');
    expect(statusTone.connected).toBe('success');
    expect(statusTone.critical).toBe('danger');
  });

  it('only uses tones from the Tone union', () => {
    const allowed: Tone[] = ['neutral', 'accent', 'success', 'warning', 'danger', 'info'];
    for (const tone of Object.values(statusTone)) {
      expect(allowed).toContain(tone);
    }
  });

  it('returns undefined for an unmapped status (caller falls back to neutral)', () => {
    expect(statusTone['definitely_not_a_status']).toBeUndefined();
  });
});

describe('value lists', () => {
  it('TASK_STATUSES contains the canonical task statuses in order', () => {
    expect(TASK_STATUSES).toEqual([
      'inbox',
      'planned',
      'active',
      'blocked',
      'review',
      'done',
      'cancelled',
    ]);
  });

  it('PRIORITIES contains the canonical priorities', () => {
    expect(PRIORITIES).toEqual(['low', 'normal', 'high', 'critical']);
  });

  it('PROJECT_STATUSES contains the canonical project statuses', () => {
    expect(PROJECT_STATUSES).toEqual(['planned', 'active', 'blocked', 'completed', 'archived']);
  });

  it('MEMORY_KINDS contains the canonical memory kinds', () => {
    expect(MEMORY_KINDS).toEqual(['fact', 'preference', 'note', 'reference']);
  });

  it('RUN_STATUSES contains the canonical run statuses', () => {
    expect(RUN_STATUSES).toEqual([
      'drafted',
      'queued',
      'planning',
      'awaiting_approval',
      'running',
      'paused',
      'succeeded',
      'failed',
      'cancelled',
    ]);
  });

  it('INTEGRATION_STATUSES and STEP_STATUSES expose their allowed sets', () => {
    expect(INTEGRATION_STATUSES).toEqual(['disconnected', 'connected', 'error']);
    expect(STEP_STATUSES).toEqual(['pending', 'active', 'done', 'failed', 'skipped']);
  });

  it('every value list has a tone mapping where a status is display-facing', () => {
    // Task, project and run statuses are surfaced via StatusPill, so each must
    // resolve to a defined tone (guards against a status added without a tone).
    for (const status of [...TASK_STATUSES, ...PROJECT_STATUSES, ...RUN_STATUSES]) {
      expect(statusTone[status], `missing tone for "${status}"`).toBeDefined();
    }
  });
});
