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

  // `demonstration_custody` is the OTHER string a committed governed row can carry
  // (production_trust::TrustState::committed_label → governed_messages.trust_state CHECK). It
  // means: the chain ran for real and bound the body for real, under a root anchor that is
  // kit-generated or the compiled-in demonstration key — so it proves nothing about who holds
  // the root. Both failure modes are regressions: promoting it to the production green, and
  // dropping it to no badge at all.
  it('maps demonstration_custody to the demo badge — never the production green', () => {
    const badge = receiptBadge('demonstration_custody');
    expect(badge).toEqual({ tone: 'info', key: 'chat.receiptDemo' });
    expect(badge?.tone).not.toBe('success');
    expect(badge?.key).not.toBe('chat.receiptVerified');
  });

  it('does not silently drop demonstration_custody (a real governed run must still show)', () => {
    expect(receiptBadge('demonstration_custody')).not.toBeNull();
  });

  it('renders no badge for null / undefined (ungoverned or blocked → no message)', () => {
    expect(receiptBadge(null)).toBeNull();
    expect(receiptBadge(undefined)).toBeNull();
  });

  it('fails closed: an unrecognized receipt value renders no badge', () => {
    expect(receiptBadge('totally_unexpected' as unknown as Parameters<typeof receiptBadge>[0])).toBeNull();
  });

  // The cardinal invariant, stated as a closed set rather than case by case: exactly ONE receipt
  // string may reach the production green. Any new arm that also returns tone:'success' — or any
  // near-miss spelling being treated as good enough — fails here.
  it('ONLY trusted_verified earns the production success tone', () => {
    const everythingElse = [
      'demonstration_custody',
      'demonstration_verified',
      'development_untrusted',
      // near-misses and shapes a confused or hostile backend could send
      'trusted_verified_lol',
      'TRUSTED_VERIFIED',
      ' trusted_verified',
      'trusted verified',
      'production',
      'verified',
      '',
      null,
      undefined,
    ];
    expect(receiptBadge('trusted_verified')?.tone).toBe('success');
    for (const receipt of everythingElse) {
      const badge = receiptBadge(receipt as Parameters<typeof receiptBadge>[0]);
      expect(badge?.tone, `${String(receipt)} must not read as production trust`).not.toBe('success');
      expect(badge?.key, `${String(receipt)} must not carry the production label`)
        .not.toBe('chat.receiptVerified');
    }
  });

  // A returned badge must not be a shared object a caller can edit into the green.
  it('returns a fresh object each call (no shared mutable badge to tamper with)', () => {
    const a = receiptBadge('demonstration_custody')!;
    const b = receiptBadge('demonstration_custody')!;
    expect(a).not.toBe(b);
    a.tone = 'success';
    expect(receiptBadge('demonstration_custody')?.tone).toBe('info');
  });
});
