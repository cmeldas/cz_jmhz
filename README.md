# JMHZ pro dohody o provedení práce (`cz_jmhz`)

Odoo 20 modul pro **jednotné měsíční hlášení zaměstnavatele** (zákon č. 323/2025 Sb.) jen pro
brigádníky na **dohodu o provedení práce**. Přihlašuje a odhlašuje dohody na ČSSZ a sestavuje
měsíční hlášení jako XML k nahrání na ePortál ČSSZ. Hlavní pracovní poměr ani DPČ nezná.

> **⚠️ Netestováno (not tested).** Modul nebyl ověřen proti ČSSZ (podání na ePortál ani
> testovací prostředí) a není nasazený v provozu; XML se kontroluje jen proti přiloženým XSD.
> Před ostrým použitím je potřeba vše ověřit.

Návrh a právní podklady: [`brigadnici/`](../../brigadnici/README.md) v `odoo_local`.
Technické podklady ČSSZ/MPSV: [Pro vývojáře JMHZ](https://www.cssz.gov.cz/pro-vyvojare-jmhz):
XSD MH 1.4.3.6, XSD REGZEC 1.4.0.4, MH – Pokyny k vyplnění 1.4.14 (revize), Definice externí datové
věty EDV 1.4.0.6, FAQ ze 9. 6. 2026, vzorové XML (`ShopNow_v1_2026-04-09.xml`).

## Co dělá

- **Dohody** (JMHZ → Dohody): brigádník, nástup, do kdy sjednána, druh činnosti (T = první DPP, U, V…
  pro souběžné další), pozice a kód CZ-ISCO, předpokládaný rozsah hodin, místo výkonu práce.
- **Přihláška, změna, odhláška, storno** na ČSSZ (REGZEC akce 1, 3, 2, 8). Modul zkontroluje povinné
  údaje, sestaví XML, ověří ho proti XSD a připraví ke stažení. Po zpracování se do dohody zapíše
  osobní identifikační číslo brigádníka (OIČ) a identifikátor zaměstnání (ID PPV).
- **Měsíční hlášení** (JMHZ → Měsíční hlášení): řádek za každou dohodu, která v měsíci trvala.
  **Částka se zapisuje ručně.** **Hodiny jsou skutečně odpracované**: tlačítko *Načíst hodiny z docházky*
  je sečte ze standardní docházky (`hr.attendance`), u brigádníka bez docházky se zapíšou ručně.
  Z částky se hodiny nikdy nedopočítávají.
- **Daň**: s prohlášením poplatníka záloha se slevou (pod limitem 0 Kč), bez prohlášení srážková daň
  15 % (2026), od roku 2027 záloha bez slevy. V XML se vyplní jen části pro daný režim (chyby
  242/244/245/325 z FAQ ČSSZ).
- **Kontroly** na každém řádku: dosažení rozhodného příjmu (blokuje), dohoda nepřihlášená (blokuje),
  odměna pod minimální mzdou, nesoulad s docházkou, víc než 300 hodin za rok, chybějící prohlášení.
- **Opravné hlášení** se stejným GUID jako řádné podání, opravené formuláře s původním GUID a typem `O`.
  Zamítnuté řádné podání se podává znovu s novým GUID.
- **Výplatní páska** (tlačítko na hlášení) a **mzdový list** za rok (akce *Mzdový list* na brigádníkovi).
- **Cron** (denně, jen v *ostrém režimu*): založí hlášení za minulý měsíc a naplánuje připomínky
  (doplnit částky, lhůta 20. dne, přihláška před nástupem, odhláška do 8 dnů).

Do docházky ani kiosku modul nezasahuje, docházku jen čte. Majitel a rodina bez dohody v modulu nejsou.

## Nastavení

1. Uživateli přidat skupinu **JMHZ / Správce** (zahrnuje HR úředníka; vidí rodná čísla a adresy).
2. JMHZ → Konfigurace → Nastavení: **variabilní symbol** zaměstnavatele od ČSSZ, **kód OSSZ**,
   místo výkonu práce (sídlo: obec a šestimístný kód obce), e-mail pro protokoly, odpovědná osoba.
   **Ostrý režim** zapnout jen na produkci.
3. JMHZ → Konfigurace → Parametry roku: rok 2026 je ověřený. **Rok 2027 je neověřený**
   (rozhodný příjem a sleva zatím nejsou vyhlášené), hlášení za 2027 na to upozorní.

## Postup

**Nový brigádník** (před první směnou):

1. Zaměstnanci → nový zaměstnanec; na záložce **JMHZ** jméno, rodné příjmení, narození, rodné číslo
   (standardní pole *Identifikační číslo*),
   trvalý pobyt (ulice bez čísla + číslo popisné), pojišťovna, vzdělání, hodinová sazba.
   Prohlášení poplatníka zapsat do tabulky na téže záložce.
2. JMHZ → Dohody → nová dohoda → **Přihláška na ČSSZ** → *Stáhnout XML* → nahrát na
   [ePortál ČSSZ](https://eportal.cssz.cz) službou **Podání nahráním dat z účetního systému** →
   v Odoo *Označit jako podané*.
3. Po zpracování doplnit OIČ a ID PPV z protokolu (nebo z ePortálu, služba Seznam zaměstnanců) a
   kliknout na *Přihlášeno*.

**Každý měsíc** (do 20. dne):

1. JMHZ → Měsíční hlášení → nové (nebo založené cronem) → *Načíst dohody* → zapsat částky →
   zkontrolovat hodiny (*Načíst hodiny z docházky*).
2. *Připravit XML* → *Stáhnout XML* → nahrát na ePortál (stejná služba jako výše) → *Označit jako podané*.
3. Po protokolu ČSSZ *Přijato*, případně *Zamítnuto* nebo *Opravné hlášení*.

**Konec dohody**: na dohodě *Odhláška* do 8 dnů po dni, do kterého byla sjednána.

## Ověřeno

- 39 testů (`--test-tags /cz_jmhz`): výpočty daně a fondu, všechna XML proti přibaleným XSD včetně
  oficiálního vzoru ShopNow, celý tok dohoda → přihláška → hlášení → podání → oprava, zámky, cron,
  práva a pravidla více firem, úprava zaměstnance HR úředníkem bez skupiny JMHZ, vykreslení výplatní
  pásky a mzdového listu.
- Formuláře (hlášení, dohoda, záložka JMHZ na zaměstnanci, nastavení) prošly v Odoo 20 v prohlížeči
  (headless Edge) bez chyb v konzoli. PDF výplatní pásky a mzdového listu se v Odoo 20 vygeneruje
  (wkhtmltopdf v kontejneru, ověřeno v `odoo shell`).
- **Neověřeno proti ČSSZ.** Veřejné testovací prostředí ČSSZ neuvádí. První hlášení proto nahrát na ePortál,
  nechat zkontrolovat a porovnat s dosavadním ručním hlášením, než se odešle.

## Co modul zatím neumí

- **Automatické odeslání** datovou schránkou (`iie254d`) ani VREP; XML se nahrává ručně na ePortál.
- **Měsíc nad rozhodným příjmem** (pojistné, kód ELDP, přihláška ke zdravotní pojišťovně): modul ho
  zablokuje a takový měsíc je nutné podat ručně na ePortálu. Hlášení je jedno za zaměstnavatele, takže
  ručně se pak podává celý měsíc.
- **Předregistrace** (PREZEC, dvoukrokové přihlášení) a přihláška cizince (doklady, pracovní oprávnění).
- **Daňové zvýhodnění na děti**, slevy na invaliditu, roční zúčtování a roční úhrny; vyúčtování srážkové
  daně za rok 2026 se podává postaru mimo JMHZ.
- **Storno formuláře** (typ `S`) jednotlivého brigádníka v již podaném hlášení.
- **Potvrzení o zaměstnání** při skončení dohody.

## Údržba

- Každý prosinec doplnit **Parametry roku** a zkontrolovat nové verze XSD na
  [stránce pro vývojáře](https://www.cssz.gov.cz/pro-vyvojare-jmhz). Schémata jsou v `data/xsd/<druh>/<verze>/`,
  výchozí verze v `lib/xsd.py`.
- Čisté funkce bez Odoo (výpočty, XML, XSD) jsou v `lib/`; modely je jen volají.

## Testy

Odoo 20 (stack `odoo20/`, čistá databáze):

```bash
docker compose -f odoo20/docker-compose.yml run --rm odoo odoo -c /etc/odoo/odoo.conf -d t20_jmhz \
  --db-filter '^t20_jmhz$' -i cz_jmhz --without-demo=True --test-enable --test-tags /cz_jmhz --stop-after-init
```

## Odoo 20

Port z 19.0.1.0.0 na **20.0.1.0.0** (modul zatím nemá git repo, verze pro 20 je kopie v `odoo20/addons/cz_jmhz`; chování beze změny):

- **Závislosti**: `hr_hourly_cost` je v 20 sloučený do `hr` (pole `hourly_cost` na zaměstnanci zůstává),
  modul závisí jen na `hr`, `hr_attendance`, `mail`.
- **Práva**: `ir.model.access.csv` a čtyři `ir.rule` (více firem) jsou v 20 jeden model `ir.access`,
  soubor `security/ir.access.csv` (sloupce `operation`, `domain`; řádek bez skupiny je omezení jako dřív
  globální pravidlo). XML ID zůstala stejná.
- **Rodné číslo**: Odoo 20 zrušilo pole `ssnid`. Modul teď bere rodné číslo ze standardního
  *Identifikačního čísla* (`identification_id`, na `hr.version`), na záložce JMHZ je pod popiskem
  „Rodné číslo“ a tiskne se na mzdovém listu.
- **Binární pole** v 20 neberou base64, XML podání se ukládá jako `BinaryBytes` (surové bajty
  s názvem souboru); stahování přes `/web/content/...` beze změny.
- **Časová pásma**: Odoo 20 nepoužívá `pytz`, přepočet docházky na místní den je přes `zoneinfo`.
- **Ikony** tlačítek (stat buttons) jsou v 20 Material Symbols (`send`, `contract`) místo Font Awesome.
- **QWeb**: `t-set` v těle `t-call` je od 20 jen parametr volané šablony, obsah těla ho nevidí
  (upstream převodník `19.1-00-t-call` takové `t-set` přesouvá před `t-call`); proměnná `employee`
  výplatní pásky je proto nastavená před `t-call="web.external_layout"`. Z akcí tisku vypadlo pole
  `report_file`, které 20 nezná.
- **Testy**: kalendář brigádníků je v 20 `calendar_type = "undefined"` (dřív `flexible_hours`, bez `tz`).
- **Oprava (chyba už v 19)**: HR úředník bez skupiny JMHZ / Správce nemohl zaměstnance založit ani
  mu změnit jméno, obojí padalo na AccessError na polích JMHZ (mají `groups`): onchange jména
  předvyplňoval jméno a příjmení pro JMHZ a pole *Daňová rezidence* mělo výchozí hodnotu Česko přímo
  v definici. Onchange se teď pro uživatele bez práva na pole JMHZ přeskočí a výchozí Česko doplňuje
  `default_get` jen Správci JMHZ (prázdná rezidence se v podání bere jako CZ, výstup je stejný).
  Ve verzi pro 19 (`addons19/cz_jmhz`) zatím neopraveno.

### Migrace dat 19 → 20

Na produkci (`dbprod1006`, 6. 10. 2026) modul **není nainstalovaný** a pole `ssnid` je všude prázdné,
skripty jsou pro lokální databáze s modulem (např. `jmhz_test`) a pro budoucí nasazení na 19.

- `migrations/20.0.1.0.0/pre-migrate.py`: smaže z `ir_model_data` stará XML ID modulu na modely
  `ir.model.access` a `ir.rule`. Odoo 20 by jinak odmítlo založit `ir.access` pod stejným XML ID
  (ValidationError v `_load_records`: XML ID ukazuje na jiný model). Práva a pravidla pak 20 založí
  znovu ze `security/ir.access.csv`. Staré řádky tabulek `ir_model_access` / `ir_rule` zůstávají
  (Odoo 20 je nečte). Když XML ID převede už obecný migrační rámec, skript nic neudělá
  (OpenUpgrade 20.0 to dělá pro všechny moduly v `base` pre-migration, `_ir_access_xmlids`; skript je
  pojistka pro aktualizaci bez OpenUpgrade).
- `migrations/20.0.1.0.0/post-migrate.py`: u brigádníků s dohodou JMHZ zkopíruje rodné číslo ze
  sloupce `hr_version.ssnid` do `identification_id`, pokud je prázdné. Rozdílné hodnoty nepřepíše
  a jen je vypíše do logu (rozhodne člověk), stejně jako počet ostatních zaměstnanců s vyplněným
  `ssnid` (ty modul nepřevádí). Sloupec `ssnid` při migraci ještě existuje (OpenUpgrade nic nemaže,
  standardní Odoo ho zahodí až v `_process_end` po všech skriptech).

Ověřeno simulací v `t20_jmhz`: XML ID přepsaná na `ir.model.access` / `ir.rule`, přidaný sloupec
`ssnid`, verze modulu 19.0.1.0.0, `-u cz_jmhz`: 11 XML ID smazáno a založeno znovu jako `ir.access`,
rodné číslo převedeno, rozdíl a cizí zaměstnanec zalogovaní.
