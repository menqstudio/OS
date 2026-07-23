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

  it('renders no badge for null / undefined (ungoverned or blocked → no message)', () => {
    expect(receiptBadge(null)).toBeNull();
    expect(receiptBadge(undefined)).toBeNull();
  });
});
