import { useState } from 'react';
import { useApp } from '../app/store';
import { desktop, type TrustSelftest as TrustSelftestResult } from '../services/desktop';
import { Mark } from './Ambient';

/**
 * TrustSelftestPanel — an owner-visible, on-demand run of the REAL governed
 * trust chain (challenge → supervisor lease → attest → isolated-signer signature →
 * verify_and_accept → trusted_verified) with real ed25519 crypto.
 *
 * It is deliberately HONEST about two things, shown prominently in the result:
 *  1. The crypto is real — a genuine trusted_verified receipt, never a faked boolean.
 *  2. The root of trust is the compiled-in demonstration anchor, not an offline-HSM
 *     key, and live AI turns still run fail-closed. So this PROVES the machinery; it
 *     does not claim production-grade custody or flip any real turn to "verified".
 */
export function TrustSelftestPanel() {
  const { lang } = useApp();
  const tr = (en: string, hy: string, ru: string) => (lang === 'hy' ? hy : lang === 'ru' ? ru : en);
  const [state, setState] = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [result, setResult] = useState<TrustSelftestResult | null>(null);
  const [error, setError] = useState<string>('');

  const run = async () => {
    setState('running');
    setError('');
    setResult(null);
    try {
      const r = await desktop.governedTrustSelftest();
      setResult(r);
      setState('done');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setState('error');
    }
  };

  const passed = result?.available === true && result.bound && result.production_verified;

  return (
    <section className="sec-section surface soft reveal trust-selftest" aria-label={tr('Trust chain self-test', 'Վստահության շղթայի ինքնաստուգում', 'Самопроверка цепочки доверия')}>
      <span className="sec-idx micro" aria-hidden="true">◇</span>
      <span className="eyebrow">{tr('LIVE TRUST CHAIN', 'ԿԵՆԴԱՆԻ ՎՍՏԱՀՈՒԹՅԱՆ ՇՂԹԱ', 'ЖИВАЯ ЦЕПОЧКА ДОВЕРИЯ')}</span>
      <h2>{tr('Governed trust-chain self-test', 'Կառավարվող վստահության շղթայի ինքնաստուգում', 'Самопроверка управляемой цепочки доверия')}</h2>
      <p className="ts-desc">
        {tr(
          'Runs the real in-process chain — challenge → lease → attest → sign → verify — and reports the genuine receipt. It never flips live AI turns.',
          'Գործարկում է իրական in-process շղթան՝ մարտահրավեր → lease → attest → ստորագրություն → ստուգում — և զեկուցում է իսկական ստացականը։ Երբեք չի փոխում կենդանի AI քայլերը։',
          'Запускает реальную in-process цепочку — вызов → аренда → аттестация → подпись → проверка — и сообщает подлинную квитанцию. Никогда не меняет статус живых ИИ-ходов.',
        )}
      </p>

      <div className="ts-actions">
        <button type="button" className="iconbtn ts-run" onClick={run} disabled={state === 'running'} style={{ width: 'auto', padding: '0 16px' }}>
          {state === 'running'
            ? tr('Running…', 'Ընթացքում…', 'Выполняется…')
            : tr('Run trust self-test', 'Գործարկել ինքնաստուգումը', 'Запустить самопроверку')}
        </button>
        <Mark state={state === 'running' ? 'thinking' : passed ? 'live' : 'idle'} size={22} />
      </div>

      <div className="ts-out" aria-live="polite">
        {state === 'idle' && (
          <p className="muted micro">{tr('Not run yet.', 'Դեռ չի գործարկվել։', 'Ещё не запускалось.')}</p>
        )}
        {state === 'error' && (
          <p className="pill warn" role="status">{tr('Self-test failed: ', 'Ինքնաստուգումը ձախողվեց՝ ', 'Самопроверка не удалась: ') + error}</p>
        )}
        {state === 'done' && result && !result.available && (
          <p className="pill off" role="status">
            {tr('Unavailable on this platform (Windows build only).', 'Անհասանելի այս հարթակում (միայն Windows-ի բիլդ)։', 'Недоступно на этой платформе (только сборка Windows).')}
          </p>
        )}
        {state === 'done' && passed && (
          <div className="ts-pass">
            <div className="chain" aria-hidden="true">
              <b className="done">challenge</b>
              <b className="done">lease</b>
              <b className="done">attest</b>
              <b className="done">sign</b>
              <b className="done">verify</b>
              <b className="now">trusted_verified</b>
            </div>
            <p className="ts-verdict">
              <span className="pill info">{tr('SELF-TEST PASSED', 'ԻՆՔՆԱՍՏՈՒԳՈՒՄ՝ ԱՆՑԱԾ', 'САМОПРОВЕРКА ПРОЙДЕНА')}</span>
              {result.demonstration_custody && (
                <span className="pill warn">{tr('DEMONSTRATION CUSTODY', 'ՑՈՒՑԱԴՐԱԿԱՆ ՊԱՀՊԱՆՈՒԹՅՈՒՆ', 'ДЕМОНСТРАЦИОННОЕ ХРАНЕНИЕ')}</span>
              )}
              <span className="mono ts-detail">{result.detail}</span>
            </p>
            {result.answer && (
              <p className="ts-answer" role="note">
                <b>
                  {result.answer_is_from_a_model
                    ? tr('Model reply produced inside the chain + verified: ', 'Մոդելի պատասխան՝ արտադրված շղթայի ներսում + ստուգված՝ ', 'Ответ модели, произведённый внутри цепочки и проверенный: ')
                    : tr('Built-in placeholder — NO model produced this. Bound + verified by the chain: ', 'Ներկառուցված լրացուցիչ տեքստ — սա ՈՉ ՄԻ մոդել չի արտադրել։ Կապված + ստուգված շղթայի կողմից՝ ', 'Встроенная заглушка — её НЕ произвела никакая модель. Связана и проверена цепочкой: ')}
                </b>
                <span className="ts-answer-body">{result.answer}</span>
              </p>
            )}
            {!result.answer_is_from_a_model && result.answer && (
              /* The chain genuinely bound these bytes — that part is true. What would be false is
                 letting the verdict imply a model answered. Say which, and why there is no model. */
              <p className="ts-caveat" role="note">
                <span className="pill warn">{tr('NO MODEL RAN', 'ՄՈԴԵԼ ՉԻ ԱՇԽԱՏԵԼ', 'МОДЕЛЬ НЕ ЗАПУСКАЛАСЬ')}</span>{' '}
                {result.answer_source === 'builtin_placeholder_model_failed'
                  ? tr('A model was configured but did not run or returned nothing; the chain bound the built-in placeholder instead.', 'Մոդելը կարգավորված էր, բայց չաշխատեց կամ ոչինչ չվերադարձրեց. շղթան կապեց ներկառուցված լրացուցիչ տեքստը։', 'Модель была настроена, но не запустилась или ничего не вернула; цепочка связала встроенную заглушку.')
                  : tr('No model is configured for the self-test (BROPS_SELFTEST_MODEL_CMD), so the chain bound the built-in placeholder. This proves the CHAIN, not the model.', 'Ինքնաստուգման համար մոդել կարգավորված չէ (BROPS_SELFTEST_MODEL_CMD), ուստի շղթան կապեց ներկառուցված տեքստը։ Սա ապացուցում է ՇՂԹԱՆ, ոչ թե մոդելը։', 'Для самопроверки модель не настроена (BROPS_SELFTEST_MODEL_CMD), поэтому цепочка связала встроенную заглушку. Это доказывает ЦЕПОЧКУ, а не модель.')}
              </p>
            )}
            <p className="ts-caveat" role="note">
              <b>{tr('Honest posture: ', 'Ազնիվ դիրք՝ ', 'Честная позиция: ')}</b>
              {result.custody_note}
            </p>
          </div>
        )}
      </div>

      <style>{TS_STYLE}</style>
    </section>
  );
}

const TS_STYLE = `
.trust-selftest h2 { margin: 2px 0 8px; }
.trust-selftest .ts-desc { margin: 0 0 14px; color: var(--ink-muted); max-width: 72ch; line-height: 1.5; }
.trust-selftest .ts-actions { display: flex; align-items: center; gap: 12px; margin: 4px 0 14px; }
.trust-selftest .ts-run { height: 34px; border: 1px solid rgb(var(--cyan-rgb)/.4); color: var(--cyan); border-radius: var(--r-sm); background: rgb(var(--cyan-rgb)/.06); }
.trust-selftest .ts-run:hover:not(:disabled) { background: rgb(var(--cyan-rgb)/.12); }
.trust-selftest .ts-run:disabled { opacity: .6; cursor: default; }
.trust-selftest .ts-out { min-height: 24px; }
.trust-selftest .ts-pass { display: flex; flex-direction: column; gap: 10px; }
.trust-selftest .ts-verdict { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 0; }
.trust-selftest .ts-detail { font-size: var(--t-small); color: var(--ink-muted); }
.trust-selftest .ts-caveat {
  margin: 2px 0 0; padding: 11px 13px; border-radius: var(--r-sm);
  border: 1px solid rgb(var(--warning-rgb)/.28); background: rgb(var(--warning-rgb)/.06);
  color: var(--ink-muted); font-size: var(--t-small); line-height: 1.55; max-width: 74ch;
}
.trust-selftest .ts-caveat b { color: var(--warning); }
`;
