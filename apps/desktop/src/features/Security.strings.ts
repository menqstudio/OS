// Page-local trilingual strings for the Security (Trust & Defense) view.
// Every VISIBLE string that used to live inline in a `tr('en','hy')` call now
// lives here with en/hy/ru. This ONLY re-sources presentation text — it never
// changes the fail-closed trust semantics (integrity / CHAIN-READ-FAILED /
// blocked posture) of Security.tsx.
export const STR = {
  // Honest posture / integrity labels
  blocked: { en: 'Blocked', hy: 'Արգելափակված', ru: 'Заблокировано' },
  verifying: { en: 'Verifying…', hy: 'Ստուգվում է…', ru: 'Проверка…' },
  chainReadFailed: {
    en: 'Chain read failed',
    hy: 'Շղթայի ընթերցումը ձախողվեց',
    ru: 'Не удалось прочитать цепочку',
  },
  integrityUnverified: {
    en: 'Integrity unverified',
    hy: 'Ամբողջականությունը չհաստատված',
    ru: 'Целостность не подтверждена',
  },
  readingChain: {
    en: 'Reading the evidence chain…',
    hy: 'Կարդում ենք ապացույցների շղթան…',
    ru: 'Чтение цепочки доказательств…',
  },
  integrityDetailBroken: {
    en: 'The evidence-chain read failed — the desktop cannot confirm integrity. The engine adjudicates; retry the read in the posture section below.',
    hy: 'Ապացույցների շղթայի ընթերցումը ձախողվեց — աշխատասեղանը չի կարող հաստատել ամբողջականությունը։ Շարժիչը որոշում է. կրկնեք ընթերցումը ստորև։',
    ru: 'Чтение цепочки доказательств не удалось — рабочий стол не может подтвердить целостность. Решение принимает движок; повторите чтение в разделе состояния ниже.',
  },
  integrityDetailBlocked: {
    en: 'Chain integrity is adjudicated by the engine (Ed25519). The read-only evidence-chain command is not wired into the desktop yet, so integrity cannot be confirmed here.',
    hy: 'Շղթայի ամբողջականությունը որոշում է շարժիչը (Ed25519)։ Միայն-ընթերցման ապացույցների շղթայի հրամանը դեռ միացված չէ աշխատասեղանին, ուստի ամբողջականությունն այստեղ չի հաստատվում։',
    ru: 'Целостность цепочки определяет движок (Ed25519). Команда чтения цепочки доказательств (только чтение) ещё не подключена к рабочему столу, поэтому целостность здесь подтвердить нельзя.',
  },

  // 0 · Manifest / integrity hero
  integrityHeading: {
    en: 'Evidence-chain integrity',
    hy: 'Ապացույցների շղթայի ամբողջականություն',
    ru: 'Целостность цепочки доказательств',
  },
  adjudicatedByEngine: {
    en: 'Adjudicated by the engine · Ed25519',
    hy: 'Որոշում է շարժիչը · Ed25519',
    ru: 'Определяет движок · Ed25519',
  },
  engineReason: {
    en: 'Engine reason: ',
    hy: 'Շարժիչի պատճառ՝ ',
    ru: 'Причина от движка: ',
  },
  engineSurfacesNoneConfirmed: {
    en: 'Engine surfaces — none confirmed',
    hy: 'Շարժիչի մակերեսներ — չհաստատված',
    ru: 'Поверхности движка — ни одна не подтверждена',
  },
  digestChip: { en: 'DIGEST', hy: 'DIGEST', ru: 'ДАЙДЖЕСТ' },
  chainChip: { en: 'CHAIN', hy: 'ՇՂԹԱ', ru: 'ЦЕПЬ' },
  leasesChip: { en: 'LEASES', hy: 'ՎԱՐՁ.', ru: 'АРЕНДЫ' },
  unverifiedLower: { en: 'unverified', hy: 'չհաստատված', ru: 'не подтверждено' },

  // 1 · Posture strip
  postureHint: {
    en: 'Live posture counts from the engine audit summary.',
    hy: 'Կենդանի ցուցանիշներ շարժիչի աուդիտի ամփոփումից։',
    ru: 'Актуальные показатели состояния из сводки аудита движка.',
  },

  // 2 · Control-plane digest
  digestTitle: {
    en: 'Control-plane digest',
    hy: 'Կառավարման հարթության ամփոփ (digest)',
    ru: 'Дайджест плоскости управления',
  },
  digestHint: {
    en: 'Read-only protected-control-plane digest.',
    hy: 'Միայն-ընթերցման պաշտպանված կառավարման հարթության digest։',
    ru: 'Дайджест защищённой плоскости управления (только чтение).',
  },
  digestBlockedNote: {
    en: 'The protected control-plane digest is held by the engine and mirrored read-only; the engine chain read is not answering yet, so no digest is shown (never a fabricated one).',
    hy: 'Պաշտպանված կառավարման հարթության digest-ը պահվում է շարժիչում և արտացոլվում է միայն ընթերցմամբ. շարժիչի շղթայի ընթերցումը դեռ չի պատասխանում, ուստի digest ցույց չի տրվում (երբեք կեղծ)։',
    ru: 'Дайджест защищённой плоскости управления хранится в движке и отражается только для чтения; чтение цепочки движка пока не отвечает, поэтому дайджест не показывается (и никогда не подделывается).',
  },

  // 3 · Residual-item tracker
  residualTitle: {
    en: 'Residual items (O-1..O-5)',
    hy: 'Մնացորդային կետեր (O-1..O-5)',
    ru: 'Остаточные пункты (O-1..O-5)',
  },
  residualHint: {
    en: 'Deferred engine security items; each closed by its own audited task.',
    hy: 'Հետաձգված շարժիչի անվտանգության կետեր. յուրաքանչյուրը փակվում է առանձին աուդիտով։',
    ru: 'Отложенные пункты безопасности движка; каждый закрывается отдельной аудируемой задачей.',
  },
  unverified: { en: 'Unverified', hy: 'Չհաստատված', ru: 'Не подтверждено' },

  // Residual names (O-1..O-5)
  'residual.O-1': { en: 'Bytecode-shadow', hy: 'Բայթկոդի ստվեր', ru: 'Теневой байткод' },
  'residual.O-2': { en: 'Audit-head anchor', hy: 'Աուդիտի գլխի խարիսխ', ru: 'Якорь головы аудита' },
  'residual.O-3': { en: 'Conductor session token', hy: 'Դիրիժորի սեսիայի թոքեն', ru: 'Токен сессии дирижёра' },
  'residual.O-4': { en: 'Control-room actor', hy: 'Կառավարման սենյակի դերակատար', ru: 'Актор диспетчерской' },
  'residual.O-5': { en: 'Evidence high-water', hy: 'Ապացույցի վերին սահման', ru: 'Верхняя граница доказательств' },

  // 4 · Key & lease registry
  registryTitle: {
    en: 'Key & lease registry',
    hy: 'Բանալիների և վարձակալությունների ռեեստր',
    ru: 'Реестр ключей и аренд',
  },
  registryHint: {
    en: 'Ownership held by the engine Ed25519 system.',
    hy: 'Սեփականությունը պահվում է շարժիչի Ed25519 համակարգում։',
    ru: 'Владение хранится в системе Ed25519 движка.',
  },
  registryBlockedNote: {
    en: 'By design the desktop caches no keys or leases; the registry lives in the engine and no read command is wired here.',
    hy: 'Ըստ նախագծման աշխատասեղանը չի պահում բանալիներ կամ վարձակալություններ. ռեեստրը շարժիչում է, ընթերցման հրաման այստեղ միացված չէ։',
    ru: 'По замыслу рабочий стол не кэширует ключи или аренды; реестр находится в движке, и команда чтения здесь не подключена.',
  },

  // Page chrome
  eyebrowCore: {
    en: 'TRUST & DEFENSE CORE',
    hy: 'ՎՍՏԱՀՈՒԹՅԱՆ ՄԻՋՈՒԿ',
    ru: 'ЯДРО ДОВЕРИЯ И ЗАЩИТЫ',
  },
  navHint: {
    en: 'Press 1–6, or [ and ] to move between sections.',
    hy: 'Սեղմեք 1–6, կամ [ և ] բաժինների միջև տեղափոխվելու համար։',
    ru: 'Нажмите 1–6 или [ и ] для перехода между разделами.',
  },
} as const;
