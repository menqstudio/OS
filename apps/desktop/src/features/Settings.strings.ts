// -------------------------------------------------------------------------------------------------
// Page-scoped trilingual copy for Settings.tsx (EN + HY + RU). Per the thin-page convention this
// page inlines its own strings for surfaces not yet in the shared i18n dictionaries — it never edits
// the shared i18n files. Keys already present in i18n/en.ts + hy.ts + ru.ts are used through `t()`.
// Formerly-bilingual "ARM · ENGLISH" eyebrows/pills are collapsed to a single localized string per
// language. Technical identifiers and brand names (MENQ OS, v0.9, MenQ, Bro/ԲՐՈ/БРО) are preserved.
// -------------------------------------------------------------------------------------------------
export const STR = {
  // — decorative eyebrows (were bilingual, now one localized string each) —
  eyebrowControlRoom: {
    en: 'CONTROL ROOM',
    hy: 'ԿԱՌԱՎԱՐՄԱՆ ԿԵՆՏՐՈՆ',
    ru: 'ЦЕНТР УПРАВЛЕНИЯ',
  },
  eyebrowRuntimeConsole: {
    en: 'RUNTIME CONSOLE',
    hy: 'ԳՈՐԾԱՐԿԱՅԻՆ ՎԱՀԱՆԱԿ',
    ru: 'КОНСОЛЬ СРЕДЫ ВЫПОЛНЕНИЯ',
  },

  // — engine-bay status pill (were bilingual) —
  bayUnavailable: { en: 'UNAVAILABLE', hy: 'ԱՆՀԱՍԱՆԵԼԻ', ru: 'НЕДОСТУПНО' },
  bayChecking: { en: 'CHECKING', hy: 'ՍՏՈՒԳՈՒՄ', ru: 'ПРОВЕРКА' },
  bayError: { en: 'ERROR', hy: 'ՍԽԱԼ', ru: 'ОШИБКА' },
  bayUnset: { en: 'UNSET', hy: 'ՉԿԱՐԳԱՎՈՐՎԱԾ', ru: 'НЕ ЗАДАНО' },
  bayRunning: { en: 'RUNNING', hy: 'ԳՈՐԾԱՐԿՎԱԾ', ru: 'ЗАПУЩЕНО' },
  bayOffline: { en: 'OFFLINE', hy: 'ԱՆՋԱՏ', ru: 'ОФФЛАЙН' },

  // — dock captions —
  capProvider: { en: 'PROVIDER', hy: 'ՄԱՏԱԿԱՐԱՐ', ru: 'ПРОВАЙДЕР' },
  capModel: { en: 'MODEL', hy: 'ՄՈԴԵԼ', ru: 'МОДЕЛЬ' },
  capRuntime: { en: 'RUNTIME · BRO', hy: 'ԳՈՐԾԱՐԿՈՒՄ · ԲՐՈ', ru: 'СРЕДА · БРО' },

  // — appearance / language panel —
  appearanceDesc: {
    en: 'Visual theme and interface language. Preferences are saved to this device.',
    hy: 'Տեսքի ոճ և ինտերֆեյսի լեզու։ Նախապատվությունները պահվում են այս սարքում։',
    ru: 'Визуальная тема и язык интерфейса. Настройки сохраняются на этом устройстве.',
  },
  themeDesc: {
    en: 'Choose a light or dark interface. Motion is reduced automatically when your system asks for it.',
    hy: 'Ընտրեք բաց կամ մուգ ինտերֆեյս։ Շարժումը նվազում է ինքնաշխատ, երբ համակարգը դա պահանջում է։',
    ru: 'Выберите светлый или тёмный интерфейс. Анимация автоматически уменьшается, когда этого требует система.',
  },
  languageDesc: {
    en: 'Interface language for BroPS.',
    hy: 'BroPS-ի ինտերֆեյսի լեզուն։',
    ru: 'Язык интерфейса BroPS.',
  },
  accentLabel: { en: 'ACCENT', hy: 'ՇԵՇՏ', ru: 'АКЦЕНТ' },
  accentNote: { en: 'verified · MenQ', hy: 'հաստատված · MenQ', ru: 'подтверждено · MenQ' },

  // — governed-provider toggle —
  governedToggleLabel: { en: 'Governed provider', hy: 'Կառավարվող մատակարար', ru: 'Управляемый провайдер' },
  governedToggleDesc: {
    en: 'Set by the backend environment under the fail-closed policy. This control is read-only — the desktop app never holds keys or leases and cannot route turns through the wall from here.',
    hy: 'Սահմանվում է backend-ի միջավայրի կողմից՝ fail-closed քաղաքականությամբ։ Այս կարգավորումը միայն կարդալու համար է. desktop ծրագիրը երբեք չի պահում բանալիներ կամ վարձակալություններ և չի կարող այստեղից ուղղորդել շրջադարձերը պատի միջով։',
    ru: 'Задаётся серверной средой согласно политике fail-closed. Этот элемент доступен только для чтения — настольное приложение никогда не хранит ключи или аренды и не может маршрутизировать обращения через стену отсюда.',
  },
  runtimeDesc: {
    en: 'The provider, model and Bro runtime are resolved by the backend environment and shown read-only. Data flows provider → model → Bro; the desktop app cannot re-seat the engine from here.',
    hy: 'Մատակարարը, մոդելը և Բրո շարժիչը որոշվում են backend միջավայրի կողմից և ցուցադրվում են միայն կարդալու համար։ Տվյալները հոսում են մատակարար → մոդել → Բրո. desktop ծրագիրն այստեղից չի կարող վերաձեռնարկել շարժիչը։',
    ru: 'Провайдер, модель и среда выполнения Bro определяются серверной средой и отображаются только для чтения. Данные идут провайдер → модель → Bro; настольное приложение не может переустановить движок отсюда.',
  },
  noModel: { en: 'No model loaded', hy: 'ՉԿԱ ԲԵՌՆՎԱԾ ՄՈԴԵԼ', ru: 'Модель не загружена' },
  sidecarHealthyDesc: {
    en: 'The governance engine responded and the governed path is available.',
    hy: 'Կառավարման շարժիչը պատասխանեց, և կառավարվող ուղին հասանելի է։',
    ru: 'Движок управления ответил, и управляемый путь доступен.',
  },
  sidecarInactiveDesc: {
    en: 'The resolved provider is ungoverned, so no governance sidecar is engaged. Turns are not verified.',
    hy: 'Ընտրված մատակարարը չկառավարվող է, ուստի կառավարման կողմնակի ծառայությունը ներգրավված չէ։ Շրջադարձերը չեն ստուգվում։',
    ru: 'Выбранный провайдер неуправляемый, поэтому вспомогательная служба управления не задействована. Обращения не проверяются.',
  },
  blockedTitle: {
    en: 'Sidecar misconfigured — governed path is fail-closed',
    hy: 'Կողմնակի ծառայությունը սխալ է կարգավորված — կառավարվող ուղին fail-closed է',
    ru: 'Вспомогательная служба настроена неверно — управляемый путь в режиме fail-closed',
  },
  blockedGuideIntro: {
    en: 'The governed provider is enabled but the sidecar did not become ready, so every governed turn is blocked (no result is produced). To restore the governed path:',
    hy: 'Կառավարվող մատակարարը միացված է, բայց կողմնակի ծառայությունը պատրաստ չդարձավ, ուստի յուրաքանչյուր կառավարվող շրջադարձ արգելափակված է (արդյունք չի ստեղծվում)։ Կառավարվող ուղին վերականգնելու համար՝',
    ru: 'Управляемый провайдер включён, но вспомогательная служба не готова, поэтому каждое управляемое обращение блокируется (результат не создаётся). Чтобы восстановить управляемый путь:',
  },
  blockedStep1: {
    en: 'Confirm the governance engine / broker service is running in the backend environment.',
    hy: 'Հաստատեք, որ կառավարման շարժիչը / broker ծառայությունը աշխատում է backend միջավայրում։',
    ru: 'Убедитесь, что движок управления / служба брокера запущены в серверной среде.',
  },
  blockedStep2: {
    en: 'Provision the trust root so signed receipts can be verified (do not fall back to ungoverned).',
    hy: 'Ապահովեք վստահության արմատը, որպեսզի ստորագրված անդորրագրերը ստուգվեն (մի անցեք չկառավարվողի)։',
    ru: 'Обеспечьте корень доверия, чтобы подписанные квитанции можно было проверить (не переходите в неуправляемый режим).',
  },
  blockedStep3: {
    en: 'Re-check status once the sidecar is configured.',
    hy: 'Կրկին ստուգեք վիճակը, երբ կողմնակի ծառայությունը կարգավորված է։',
    ru: 'Повторно проверьте состояние после настройки вспомогательной службы.',
  },
  recheck: { en: 'Re-check', hy: 'Կրկին ստուգել', ru: 'Проверить снова' },

  // — system identity panel —
  systemHeading: { en: 'System', hy: 'Համակարգ', ru: 'Система' },
  aboutProductLabel: { en: 'Product', hy: 'Արտադրանք', ru: 'Продукт' },
  aboutVersionLabel: { en: 'Version', hy: 'Տարբերակ', ru: 'Версия' },
  aboutGovernanceLabel: { en: 'Governance', hy: 'Կառավարում', ru: 'Управление' },

  // — governance posture (finding: this row used to state "Fail-closed, verified-
  //   receipt-mandatory" UNCONDITIONALLY, while the shipped default resolves an
  //   ungoverned provider and every reply streams ungoverned. The row now reports the
  //   ACTUAL runtime state from ai_status, including an explicit unknown.) —
  govUnknown: {
    en: 'Unknown — not verified here',
    hy: 'Անհայտ — այստեղ չի ստուգվում',
    ru: 'Неизвестно — здесь не проверяется',
  },
  govUnknownNote: {
    en: 'There is no desktop backend to ask in this window, so the governance state of AI '
      + 'replies cannot be checked from here. Treat it as unverified.',
    hy: 'Այս պատուհանում հարցնելու backend չկա, ուստի AI պատասխանների կառավարման վիճակը '
      + 'այստեղից չի կարող ստուգվել։ Համարեք այն չստուգված։',
    ru: 'В этом окне нет серверной части, у которой можно спросить, поэтому состояние '
      + 'управления AI-ответами отсюда не проверить. Считайте его непроверенным.',
  },
  govChecking: { en: 'Checking…', hy: 'Ստուգվում է…', ru: 'Проверка…' },
  govCheckingNote: {
    en: 'Reading the provider the backend actually resolved.',
    hy: 'Կարդում ենք այն մատակարարը, որը backend-ը իրականում ընտրել է։',
    ru: 'Читаем провайдера, которого действительно выбрала серверная часть.',
  },
  govUnavailableNote: {
    en: 'The backend did not report a provider status, so the governance state of AI replies '
      + 'is unknown. Treat it as unverified.',
    hy: 'Backend-ը մատակարարի վիճակ չհաղորդեց, ուստի AI պատասխանների կառավարման վիճակն անհայտ է։ '
      + 'Համարեք այն չստուգված։',
    ru: 'Серверная часть не сообщила статус провайдера, поэтому состояние управления '
      + 'AI-ответами неизвестно. Считайте его непроверенным.',
  },
  govNoProvider: {
    en: 'No provider — no model runs',
    hy: 'Մատակարար չկա — մոդել չի աշխատում',
    ru: 'Провайдера нет — модель не запускается',
  },
  govNoProviderNote: {
    en: 'No AI provider is resolved, so no model call happens at all. Nothing is governed here '
      + 'because nothing runs.',
    hy: 'AI մատակարար ընտրված չէ, ուստի մոդելի կանչ ընդհանրապես տեղի չի ունենում։ Այստեղ ոչինչ '
      + 'չի կառավարվում, որովհետև ոչինչ չի աշխատում։',
    ru: 'AI-провайдер не выбран, поэтому вызова модели вообще не происходит. Здесь нечем '
      + 'управлять, потому что ничего не выполняется.',
  },
  govUngoverned: {
    en: 'Not governed — replies are not verified',
    hy: 'Չկառավարվող — պատասխանները չեն ստուգվում',
    ru: 'Не управляется — ответы не проверяются',
  },
  govUngovernedNote: {
    en: 'The resolved provider runs on the ungoverned path: replies stream straight from the '
      + 'model with no lease, no signed receipt and no verification. Fail-closed, '
      + 'verified-receipt-mandatory governance applies only when the backend resolves the '
      + 'governed engine provider — it does not apply to this session.',
    hy: 'Ընտրված մատակարարն աշխատում է չկառավարվող ուղով. պատասխանները հոսում են ուղիղ մոդելից՝ '
      + 'առանց lease-ի, առանց ստորագրված անդորրագրի և առանց ստուգման։ Fail-closed, պարտադիր '
      + 'ստուգված անդորրագրով կառավարումը գործում է միայն այն դեպքում, երբ backend-ը ընտրում է '
      + 'կառավարվող շարժիչի մատակարարը — այս սեսիային այն չի վերաբերում։',
    ru: 'Выбранный провайдер работает по неуправляемому пути: ответы идут напрямую от модели — '
      + 'без аренды, без подписанной квитанции и без проверки. Управление в режиме fail-closed '
      + 'с обязательной проверенной квитанцией действует, только когда серверная часть выбирает '
      + 'провайдер управляемого движка — к этой сессии оно не относится.',
  },
  govGovernedBlocked: {
    en: 'Governed — fail-closed, currently blocking',
    hy: 'Կառավարվող — fail-closed, ներկայում արգելափակում է',
    ru: 'Управляется — fail-closed, сейчас блокирует',
  },
  govGovernedBlockedNote: {
    en: 'The governed engine is the resolved provider, so a reply is delivered only against a '
      + 'verified receipt. The sidecar is not ready, so governed turns produce no reply at all '
      + 'rather than falling back to an ungoverned one.',
    hy: 'Ընտրված մատակարարը կառավարվող շարժիչն է, ուստի պատասխան տրվում է միայն ստուգված '
      + 'անդորրագրի դիմաց։ Կողմնակի ծառայությունը պատրաստ չէ, ուստի կառավարվող շրջադարձերն '
      + 'ընդհանրապես պատասխան չեն տալիս՝ չկառավարվողի անցնելու փոխարեն։',
    ru: 'Выбранный провайдер — управляемый движок, поэтому ответ выдаётся только при проверенной '
      + 'квитанции. Вспомогательная служба не готова, поэтому управляемые обращения не выдают '
      + 'ответа вовсе, а не переходят в неуправляемый режим.',
  },
  govGoverned: {
    en: 'Governed — verified receipt required',
    hy: 'Կառավարվող — պահանջվում է ստուգված անդորրագիր',
    ru: 'Управляется — требуется проверенная квитанция',
  },
  govGovernedNote: {
    en: 'The governed engine is the resolved provider: model calls run behind the wall and a '
      + 'reply is delivered only if its signed receipt verifies. A turn that cannot be verified '
      + 'is blocked, never downgraded to an ungoverned reply.',
    hy: 'Ընտրված մատակարարը կառավարվող շարժիչն է. մոդելի կանչերն աշխատում են պատի հետևում, և '
      + 'պատասխան տրվում է միայն եթե ստորագրված անդորրագիրը ստուգվում է։ Չստուգվող շրջադարձն '
      + 'արգելափակվում է, երբեք չի իջեցվում չկառավարվող պատասխանի։',
    ru: 'Выбранный провайдер — управляемый движок: вызовы модели идут за стеной, и ответ '
      + 'выдаётся, только если его подписанная квитанция проходит проверку. Обращение, которое '
      + 'нельзя проверить, блокируется и никогда не понижается до неуправляемого ответа.',
  },
  providerNotConfiguredHint: {
    en: 'No AI provider is resolved by the backend environment. Configure one to enable turns.',
    hy: 'Backend միջավայրը AI մատակարար չի ընտրել։ Կարգավորեք մեկը՝ շրջադարձերը միացնելու համար։',
    ru: 'Серверная среда не выбрала AI-провайдера. Настройте его, чтобы включить обращения.',
  },

  // — live-region announcements —
  themeChanged: { en: 'Theme set to', hy: 'Տեսքի ոճը սահմանված է՝', ru: 'Тема установлена:' },
  languageChanged: { en: 'Language set to', hy: 'Լեզուն սահմանված է՝', ru: 'Язык установлен:' },
} as const;
