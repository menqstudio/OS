# What binds a repository that follows MenQ Standard / Ինչն է պարտադիր MenQ Standard-ին հետևող repository-ի համար

**Status / Կարգավիճակ:** Proposed under `D-029`; in force only from the Owner's merge of the pull request that carries it / Առաջարկված `D-029`-ով. ուժի մեջ է միայն այն պահից, երբ Owner-ը merge անի այն պարունակող pull request-ը  
**Document class / Փաստաթղթի դաս:** Normative  
**Owner / Պատասխանատու:** MenQ Owner  
**Canonical path / Canonical ուղի:** `consumer/CONSUMER_CONTRACT.md`  
**Related decisions / Կապված որոշումներ:** `D-028`, `D-029` (in MenQ Standard: `foundation/ai-collaboration/`; no link, because this file is copied into repositories that do not hold them / MenQ Standard-ում՝ `foundation/ai-collaboration/`. առանց հղման, քանի որ այս ֆայլը պատճենվում է repository-ներ, որոնք դրանք չունեն)

## English

A repository follows MenQ Standard when `check_conformance.py check` is GREEN on it. This document
lists what that program enforces and names the RED line of each item. An item marked **[S]** is
enforced only when the program is given a checkout of the standard (`--standard`); the reusable
workflow always gives one, a bare local run does not, and the output says which happened.

### MUST — checked

1. **Keep a pin.** `.menq-standard.json` at the repository root: the standard's repository
   (`menqstudio/MenQ-Standard`), the version, the full commit the kit was taken from, the kit
   directory, the session-read manifest path, the hash rule, the sha256 of every kit file, and the
   hash and commit of every rendered workflow. RED: `pin is missing`, `pin is malformed: …`.
2. **Hold the whole kit, unchanged, and nothing else in its directory.** RED: `kit file is
   missing: …`, `kit file does not match its pin: …`, `file in the kit directory is not listed in
   the pin: …`.
3. **Hold the conformance workflow as the kit renders it**, `.github/workflows/menq-standard-conformance.yml`,
   so that conformance is judged on every pull request by the standard's copy of the checker. RED:
   `pin is malformed: workflows does not list …`, `workflow file is missing: …`, `workflow file
   does not match its pin: …`.
4. **Meet the bounded session read (`D-028`).** A session-read manifest with an ordered core, a
   declared `total_bytes_max` no greater than 350,000 bytes, every tracked Markdown file reachable
   from the core or an area, and the budget gate GREEN. The gate runs in CI through item 3. RED:
   `session-read manifest is missing: …`, `session-read budget gate is RED: …`.
5. **Keep declared facts equal to their source**, when `config/doc-facts.json` exists. RED:
   `sync_facts --check is RED: …`. Without that file nothing is checked and the output says
   `sync_facts: NOT CONFIGURED`.
6. **[S] Pin the truth.** The pinned commit exists in the standard and is on its `main`; the pinned
   version and every pinned hash equal the standard's `VERSION` and `consumer/KIT_MANIFEST.json`
   at that commit; every rendered workflow is the standard's template rendered at its recorded
   commit. RED: `pin names a commit that does not exist in the standard`, `pin names a commit
   that is not on the standard's …`, `pin names version …, but the standard at … is version …`,
   `pin records … for …; the standard at … has …`, `pin records a hash for … that is not the
   standard's template …`.

### MUST NOT

1. Edit a kit file or a rendered workflow in place. Checked by MUST 2 and 3. A change to the kit is
   proposed in MenQ Standard and arrives as an update.
2. Pin a commit of a fork or of an unmerged branch of the standard. Checked by MUST 6.
3. Declare a session-read budget above 350,000 bytes. Checked by MUST 4.
4. Merge an update pull request automatically, or let a program approve it. **Not checked:** the
   update workflow of the kit never merges and never approves, and a gate in MenQ Standard holds
   its template to that, but no program inside a repository can see that repository's auto-merge
   setting or its other automation.
5. Give the update workflow a token wider than the repository's own Actions token. **Not checked.**

### ADVISORY — not checked by any program

1. Render and enable the update workflow (`install --with-update-workflow`), so the repository
   learns of a new version by itself. A repository without it is conformant and silently stale.
2. Merge or close an update pull request within a time the Owner sets. No deadline exists today.
3. Make the conformance workflow a required status check in branch protection. The checker proves
   the workflow file is present and unmodified; it cannot prove that Actions is enabled, that the
   run happened, or that a RED run blocks a merge.
4. Re-render the workflows (`install --render-workflows`) when an update pull request says a
   template changed. The update job cannot do it: an Actions token may not write workflow files.
5. Configure `sync_facts` as soon as one fact is written in a second file.
6. Read the changelog section in the update pull request before merging it.

### What the standard owes a repository that follows it

1. One number, `VERSION` (`MAJOR.MINOR.PATCH`). A change to the kit or to the reusable workflow
   without a higher version is RED in MenQ Standard (`scripts/check_standard_version.py`).
   The rule for which part moves is written, not checked: MAJOR when a conformant repository can
   turn RED without changing (a new or tightened MUST, a changed pin format, a changed interface
   of the reusable workflow); MINOR for an addition that cannot; PATCH for a correction.
2. `consumer/KIT_MANIFEST.json` equal to the kit files (`scripts/generate_kit_manifest.py --check`).
3. A changelog heading naming every version, so an update pull request can quote what changed.
4. The command lines `check_conformance.py pin-commit --consumer … --standard … --standard-ref …`
   and `check_conformance.py check --consumer … --standard … --standard-ref …` keep their
   meaning: a workflow rendered long ago still calls them.

## Հայերեն

Repository-ն հետևում է MenQ Standard-ին, երբ `check_conformance.py check`-ը նրա վրա GREEN է։ Այս
փաստաթուղթը թվարկում է, թե ինչ է այդ ծրագիրը պարտադրում, և անվանում է ամեն կետի RED տողը։ **[S]**
նշանով կետը պարտադրվում է միայն այն դեպքում, երբ ծրագրին տրված է ստանդարտի checkout
(`--standard`). reusable workflow-ը միշտ տալիս է, իսկ հասարակ local գործարկումը՝ ոչ, և output-ը
ասում է, թե որն է եղել։

### ՊԱՐՏԱԴԻՐ Է (MUST) — ստուգվում է

1. **Պահել pin։** Repository-ի root-ում `.menq-standard.json`՝ ստանդարտի repository-ն
   (`menqstudio/MenQ-Standard`), տարբերակը, այն ամբողջական commit-ը, որից վերցվել է kit-ը, kit-ի
   directory-ն, session-read manifest-ի ուղին, hash-ի կանոնը, kit-ի ամեն ֆայլի sha256-ը և ամեն
   render արված workflow-ի hash-ը ու commit-ը։ RED՝ `pin is missing`, `pin is malformed: …`։
2. **Պահել ամբողջ kit-ը անփոփոխ, և նրա directory-ում ուրիշ ոչինչ։** RED՝ `kit file is missing: …`,
   `kit file does not match its pin: …`, `file in the kit directory is not listed in the pin: …`։
3. **Պահել conformance workflow-ը այնպես, ինչպես kit-ն է render անում**՝
   `.github/workflows/menq-standard-conformance.yml`, որպեսզի conformance-ը ամեն pull request-ում
   գնահատի checker-ի՝ ստանդարտում գտնվող պատճենը։ RED՝ `pin is malformed: workflows does not
   list …`, `workflow file is missing: …`, `workflow file does not match its pin: …`։
4. **Կատարել սահմանափակ session read-ը (`D-028`)։** Session-read manifest՝ հերթականությամբ core-ով,
   հայտարարված `total_bytes_max`՝ 350,000 բայթից ոչ ավելի, ամեն tracked Markdown ֆայլ հասանելի
   core-ից կամ area-ից, և budget gate-ը GREEN։ Gate-ը CI-ում գործարկվում է 3-րդ կետի միջոցով։ RED՝
   `session-read manifest is missing: …`, `session-read budget gate is RED: …`։
5. **Հայտարարված փաստերը պահել հավասար իրենց աղբյուրին**, երբ `config/doc-facts.json`-ը կա։ RED՝
   `sync_facts --check is RED: …`։ Առանց այդ ֆայլի ոչինչ չի ստուգվում, և output-ը գրում է
   `sync_facts: NOT CONFIGURED`։
6. **[S] Pin-ում գրել ճշմարտությունը։** Pin-ի commit-ը կա ստանդարտում և նրա `main`-ի վրա է. pin-ի
   տարբերակը և ամեն hash հավասար են ստանդարտի `VERSION`-ին և `consumer/KIT_MANIFEST.json`-ին այդ
   commit-ում. ամեն render արված workflow ստանդարտի template-ն է՝ render արված իր գրանցված
   commit-ում։ RED՝ `pin names a commit that does not exist in the standard`, `pin names a commit
   that is not on the standard's …`, `pin names version …, but the standard at … is version …`,
   `pin records … for …; the standard at … has …`, `pin records a hash for … that is not the
   standard's template …`։

### ՉԻ ԿԱՐԵԼԻ (MUST NOT)

1. Տեղում խմբագրել kit-ի ֆայլ կամ render արված workflow։ Ստուգվում է MUST 2-ով և 3-ով։ Kit-ի
   փոփոխությունը առաջարկվում է MenQ Standard-ում և գալիս է որպես update։
2. Pin անել ստանդարտի fork-ի կամ չmerge արված branch-ի commit։ Ստուգվում է MUST 6-ով։
3. Հայտարարել 350,000 բայթից մեծ session-read budget։ Ստուգվում է MUST 4-ով։
4. Update pull request-ը merge անել ավտոմատ կամ թույլ տալ, որ ծրագիրը այն approve անի։ **Չի
   ստուգվում.** kit-ի update workflow-ը երբեք merge կամ approve չի անում, և MenQ Standard-ի gate-ը
   նրա template-ը պահում է այդ կանոնի մեջ, բայց repository-ի ներսում ոչ մի ծրագիր չի կարող տեսնել
   այդ repository-ի auto-merge կարգավորումը կամ նրա մյուս ավտոմատացումը։
5. Update workflow-ին տալ repository-ի սեփական Actions token-ից լայն token։ **Չի ստուգվում։**

### ԽՈՐՀՈՒՐԴ (ADVISORY) — ոչ մի ծրագիր չի ստուգում

1. Render անել և միացնել update workflow-ը (`install --with-update-workflow`), որպեսզի repository-ն
   ինքը իմանա նոր տարբերակի մասին։ Առանց դրա repository-ն conformant է և լուռ հնանում է։
2. Update pull request-ը merge անել կամ փակել Owner-ի սահմանած ժամկետում։ Այսօր ժամկետ չկա։
3. Conformance workflow-ը դարձնել required status check branch protection-ում։ Checker-ը
   ապացուցում է, որ workflow-ի ֆայլը կա և փոփոխված չէ. այն չի կարող ապացուցել, որ Actions-ը
   միացված է, որ run-ը եղել է, կամ որ RED run-ը արգելափակում է merge-ը։
4. Նորից render անել workflow-ները (`install --render-workflows`), երբ update pull request-ը ասում
   է, որ template-ը փոխվել է։ Update job-ը դա չի կարող անել. Actions token-ը չի կարող workflow
   ֆայլ գրել։
5. Կարգավորել `sync_facts`-ը հենց որ մեկ փաստ գրվի երկրորդ ֆայլում։
6. Merge անելուց առաջ կարդալ update pull request-ի changelog բաժինը։

### Ինչ է ստանդարտը պարտք իրեն հետևող repository-ին

1. Մեկ թիվ՝ `VERSION` (`MAJOR.MINOR.PATCH`)։ Kit-ի կամ reusable workflow-ի փոփոխությունը առանց
   ավելի բարձր տարբերակի RED է MenQ Standard-ում (`scripts/check_standard_version.py`)։ Թե որ
   մասն է շարժվում՝ գրված կանոն է, ոչ թե ստուգում. MAJOR՝ երբ conformant repository-ն կարող է
   RED դառնալ առանց փոխվելու (նոր կամ խստացված MUST, pin-ի փոխված ձևաչափ, reusable workflow-ի
   փոխված interface). MINOR՝ հավելման համար, որը դա չի կարող անել. PATCH՝ ուղղման համար։
2. `consumer/KIT_MANIFEST.json`-ը հավասար է kit-ի ֆայլերին (`scripts/generate_kit_manifest.py --check`)։
3. Changelog-ի վերնագիր, որը անվանում է ամեն տարբերակ, որպեսզի update pull request-ը կարողանա
   մեջբերել, թե ինչ է փոխվել։
4. `check_conformance.py pin-commit --consumer … --standard … --standard-ref …` և
   `check_conformance.py check --consumer … --standard … --standard-ref …` հրամանների տողերը
   պահում են իրենց իմաստը. վաղուց render արված workflow-ը դեռ կանչում է դրանք։

<!-- END: CONSUMER_CONTRACT -->
