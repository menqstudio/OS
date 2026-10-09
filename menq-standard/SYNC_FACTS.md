# sync_facts — one source for a fact several documents repeat / մեկ աղբյուր այն փաստի համար, որը կրկնվում է մի քանի փաստաթղթում

**Status / Կարգավիճակ:** Active — a file of the consumer kit, proposed under `D-029` / Գործող — consumer kit-ի ֆայլ, առաջարկված `D-029`-ով  
**Document class / Փաստաթղթի դաս:** Informative  
**Origin / Ծագում:** the OS repository's `tools/SYNC_FACTS.md`, adapted for the kit; `sync_facts.py` and `test_sync_facts.py` are byte-for-byte copies of the OS files / OS repository-ի `tools/SYNC_FACTS.md`-ը՝ հարմարեցված kit-ի համար. `sync_facts.py`-ը և `test_sync_facts.py`-ը OS-ի ֆայլերի բայթ առ բայթ պատճեններն են

## English

A number, a name or a commit written by hand in nine files is wrong in one of them after the
second change. `sync_facts.py` keeps every declared use of a fact equal to its one source.
It knows nothing about any project: the tool is the same file in every repository, and
`config/doc-facts.json` is the only part that differs.

In a repository that follows MenQ Standard the tool sits in the kit directory (`menq-standard/`
unless the pin names another), and in MenQ Standard itself in `consumer/`:

    python3 menq-standard/sync_facts.py --check     # change nothing; exit 1 and name each stale use
    python3 menq-standard/sync_facts.py --write     # bring every stale use to its source

The tool's own docstring and its RED line still say `tools/sync_facts.py`, the path it has in the
repository it came from. The file is copied byte for byte, so that text was not changed; the path
above is the one to type.

### Declaring a fact

A fact has a name and exactly one source:

    "facts": {
      "release":   {"source": {"value": "2.4.0"}},
      "tests":     {"source": {"json":  {"file": "config/counts.json", "path": "suite.total"}}},
      "round":     {"source": {"regex": {"file": "AUDIT.md", "pattern": "the \\*\\*([A-Z]+)\\*\\* audit"}}},
      "head":      {"source": {"command": ["git", "rev-parse", "--short", "HEAD"]}}
    }

A regex source must match exactly once. A command is a list of arguments, never a shell string.

### Using a fact — two ways

**A marker**, in a Markdown file listed under `"documents"`. Invisible when rendered, usable
mid-sentence; what sits between the two comments belongs to the tool:

    version <!-- fact:release -->2.4.0<!-- /fact -->, <!-- fact:tests|comma -->1,434<!-- /fact --> tests

Filters: `upper`, `lower`, `title`, `comma`.

**A target**, where a marker cannot go — a JSON file, a fenced code block, a file held to a byte
ceiling. The document gains nothing; the configuration says where the fact sits:

    "targets": [{"file": "README.md", "fact": "tests", "pattern": "npm test +# (\\d+) tests"}]

The pattern has exactly one group, that group is the fact, and it must match exactly once in the
file. A pattern that matches twice, or stops matching after an edit, is refused by name.

### What it refuses, changing nothing

An undeclared fact in a marker or target; an unknown filter; a marker that does not close on its
line; a source or target that matches zero times or several; a source that resolves to an empty or
multi-line value; a declared fact nothing uses; a listed file that is not there.

### What it does not do

It writes facts, not prose. It does not find an unmarked, undeclared copy of a fact: a number typed
by hand that no marker and no target covers is invisible to it. Add a fact when it is found in a
second file.

### In a repository that follows the standard

1. The kit brings `sync_facts.py` and `test_sync_facts.py` unchanged. Python 3.9+, no packages.
2. Write `config/doc-facts.json`: the facts that repository repeats, and where each one sits.
3. Run `--check` until it is GREEN; every refusal names the file and the reason.
4. Nothing more is needed for CI: once `config/doc-facts.json` exists, `check_conformance.py check`
   runs `sync_facts.py --check` and is RED when it is. Without that file the checker prints
   `sync_facts: NOT CONFIGURED` and checks no fact.

Line endings: a CRLF checkout is worked on as LF and written back as CRLF, so a pattern written
with `\n` matches on Windows; a file that mixes the two keeps every ending. The first Windows CI
run found both that and a test fixture that doubled its own `\r`.

## Հայերեն

Թիվը, անունը կամ commit-ը, որը ձեռքով գրված է ինը ֆայլում, երկրորդ փոփոխությունից հետո դրանցից
մեկում սխալ է։ `sync_facts.py`-ը փաստի յուրաքանչյուր հայտարարված օգտագործումը պահում է հավասար
նրա մեկ աղբյուրին։ Այն ոչինչ չգիտի որևէ project-ի մասին. գործիքը նույն ֆայլն է ամեն
repository-ում, և միայն `config/doc-facts.json`-ն է տարբերվում։

MenQ Standard-ին հետևող repository-ում գործիքը kit-ի directory-ում է (`menq-standard/`, եթե pin-ը
այլ անուն չի նշում), իսկ MenQ Standard-ում՝ `consumer/`-ում.

    python3 menq-standard/sync_facts.py --check     # ոչինչ չի փոխում. exit 1 և անվանում է ամեն հնացած օգտագործում
    python3 menq-standard/sync_facts.py --write     # ամեն հնացած օգտագործում բերում է իր աղբյուրին

Գործիքի սեփական docstring-ը և RED տողը դեռ գրում են `tools/sync_facts.py`՝ այն ուղին, որն այն ունի
իր սկզբնական repository-ում։ Ֆայլը պատճենված է բայթ առ բայթ, ուստի այդ տեքստը չի փոխվել. պետք է
գրել վերևի ուղին։

### Փաստի հայտարարում

Փաստն ունի անուն և ճիշտ մեկ աղբյուր։ Աղբյուրի չորս տեսակները՝ `value` (մեկ անգամ հայտարարված
արժեք), `json` (JSON ֆայլի դաշտ), `regex` (ֆայլում միակ համընկնման առաջին խումբը) և `command`
(արգումենտների ցանկ), ցույց են տրված անգլերեն բաժնի օրինակում։ Regex աղբյուրը պետք է համընկնի
ճիշտ մեկ անգամ։ Command-ը արգումենտների ցանկ է, երբեք shell տող չէ։

### Փաստի օգտագործում՝ երկու ձև

**Marker**՝ `"documents"`-ում թվարկված Markdown ֆայլում։ Render-ի ժամանակ անտեսանելի է և կարող է
լինել նախադասության մեջտեղում. երկու comment-ի միջև գրվածը պատկանում է գործիքին։ Ձևը ցույց է
տրված անգլերեն բաժնի օրինակում։ Ֆիլտրերը՝ `upper`, `lower`, `title`, `comma`։

**Target**՝ այնտեղ, որտեղ marker չի կարելի դնել. JSON ֆայլ, fenced code block, բայթերի սահման
ունեցող ֆայլ։ Փաստաթղթին ոչինչ չի ավելանում. կոնֆիգուրացիան է ասում, թե որտեղ է փաստը։ Pattern-ը
ունի ճիշտ մեկ խումբ, այդ խումբը փաստն է, և այն պետք է ֆայլում համընկնի ճիշտ մեկ անգամ։ Երկու
անգամ համընկնող կամ խմբագրումից հետո այլևս չհամընկնող pattern-ը մերժվում է անունով։

### Ինչ է մերժում՝ ոչինչ չփոխելով

Marker-ում կամ target-ում չհայտարարված փաստ. անհայտ ֆիլտր. marker, որը չի փակվում իր տողում.
աղբյուր կամ target, որը համընկնում է զրո կամ մի քանի անգամ. աղբյուր, որը տալիս է դատարկ կամ
բազմատող արժեք. հայտարարված փաստ, որը ոչինչ չի օգտագործում. թվարկված ֆայլ, որը չկա։

### Ինչ չի անում

Այն գրում է փաստեր, ոչ թե տեքստ։ Այն չի գտնում փաստի չնշված և չհայտարարված պատճենը. ձեռքով
գրված թիվը, որը ոչ մի marker և ոչ մի target չի ծածկում, նրա համար անտեսանելի է։ Փաստը
հայտարարիր, երբ այն հայտնվում է երկրորդ ֆայլում։

### Ստանդարտին հետևող repository-ում

1. Kit-ը բերում է `sync_facts.py`-ը և `test_sync_facts.py`-ը անփոփոխ։ Python 3.9+, առանց package-ների։
2. Գրիր `config/doc-facts.json`-ը՝ այն փաստերը, որոնք այդ repository-ն կրկնում է, և յուրաքանչյուրի տեղը։
3. Գործարկիր `--check`-ը, մինչև GREEN լինի. ամեն մերժում անվանում է ֆայլը և պատճառը։
4. CI-ի համար ուրիշ ոչինչ պետք չէ. երբ `config/doc-facts.json`-ը կա, `check_conformance.py check`-ը
   գործարկում է `sync_facts.py --check`-ը և RED է, երբ այն RED է։ Առանց այդ ֆայլի checker-ը տպում է
   `sync_facts: NOT CONFIGURED` և ոչ մի փաստ չի ստուգում։

Տողավերջեր. CRLF checkout-ը մշակվում է որպես LF և հետ է գրվում որպես CRLF, ուստի `\n`-ով գրված
pattern-ը համընկնում է նաև Windows-ում. երկուսը խառնող ֆայլը պահում է իր ամեն տողավերջը։ Windows-ի
առաջին CI գործարկումը գտավ և դա, և թեստի fixture, որը կրկնապատկում էր իր `\r`-ը։

<!-- END: CONSUMER_KIT_SYNC_FACTS -->
