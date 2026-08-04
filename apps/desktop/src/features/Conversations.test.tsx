import { describe, it, expect } from 'vitest';
import { receiptBadge } from './Conversations';

describe('receiptBadge — governed receipt trust badge (Wave 3a slice 3)', () => {
  it('maps development_untrusted to an amber dev badge', () => {
    expect(receiptBadge('development_untrusted')).toEqual({
      tone: 'warning',
      key: 'chat.receiptDev',
    });
  });

  it('maps trusted_verified to a green Verified badge', () => {
    expect(receiptBadge('trusted_verified')).toEqual({
      tone: 'success',
      key: 'chat.receiptVerified',
    });
  });

  it('maps demonstration_verified to a DISTINCT info badge, never the production green', () => {
    const badge = receiptBadge('demonstration_verified');
    expect(badge).toEqual({ tone: 'info', key: 'chat.receiptDemo' });
    // Cardinal honesty invariant: demonstration custody must never render as the production
    // success ("Verified") badge — a regression flipping this arm to tone:'success' must fail here.
    expect(badge?.tone).not.toBe('success');
  });

  it('renders no badge for null / undefined (ungoverned or blocked → no message)', () => {
    expect(receiptBadge(null)).toBeNull();
    expect(receiptBadge(undefined)).toBeNull();
  });

  it('fails closed: an unrecognized receipt value renders no badge', () => {
    expect(receiptBadge('totally_unexpected' as unknown as Parameters<typeof receiptBadge>[0])).toBeNull();
  });
});
