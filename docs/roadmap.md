# Fahrplan

Stand: 5. August 2026. Grundlage ist eine Bestandsaufnahme des Systems
(Code, Datenhaltung, Server, Live-Zustand) und drei Festlegungen:

* **Schwerpunkt:** Alltag des Teams, Betreiber-Auswertung, Buchhaltung/Steuer
  und Verlässlichkeit – alle vier.
* **Skalierung:** Wachstum auf 5–15 Wohnungen und mehr Personal in 12 Monaten.
* **Umbau:** `web.py` wird aufgeteilt, **bevor** die Feature-Pakete kommen.

Abgehakt wird hier, nicht im Kopf. Jedes Paket ist einzeln lieferbar und
hinterlässt ein lauffähiges System.

---

## Phase 0 — Fundament

### AP1 · Backup & Datentrennung — ✅ erledigt (5.8.2026)

Betriebsdaten aus dem Projektordner nach `/var/lib/rentaltool` (`app/paths.py`,
`tools/migrate_data.py`), tägliche Sicherung auf die Nextcloud mit echter
Inhaltsprüfung und wöchentlicher Wiederherstellungs-Probe (`tools/backup.py`,
`deploy/*.timer`). Siehe README → „Datenordner" und „Sicherung".

### AP2 · Sichere Speicherschicht — ✅ erledigt (5.8.2026)

`app/store.py` als einziger Weg für Dateizugriff: atomares Schreiben
(Nachbardatei + `fsync` + `os.replace`) und Dateisperre über die ganze Änderung
(`store.edit`). Umgestellt sind `timetrack`, `bookings`, `receipts`,
`housekeeping`, `data.save_config` und das Steuerarchiv (Revision + Ledger unter
einer Sperre, PDF atomar). Gegentest: mit der alten Arbeitsweise überlebten bei
vier gleichzeitigen Prozessen 38 von 100 Einträgen, jetzt 100.
Siehe README → „Speicherschicht".

### AP3 · Staging & Deploy — ✅ erledigt (5.8.2026)

`tools/deploy.sh` rollt mit Tests, Rauchprobe und automatischem Rückweg aus.
Probe-Instanz auf Port 3002 mit eigenem Datenordner, erreichbar über
SSH-Tunnel; gefüllt aus den Echtdaten, aber zweifach entschärft
(`tools/staging_refresh.py` räumt die Konfiguration, `app/mode.py` sperrt
Mail/Gast-Nachrichten/Spiegel im Code). `tools/watchdog.py` prüft alle 10
Minuten Oberfläche, Smoobu, Daten und Alter der Sicherung und meldet nur bei
Wechseln. Siehe README → „Ausrollen, Probe-Instanz, Wächter".

---

## Phase 1 — Struktur

### AP4 · `web.py` aufteilen — ✅ erledigt (6.8.2026)

Aus 4.961 Zeilen in einer Datei wurden `app/web.py` (353 Zeilen Gerüst) und elf
Bereichsmodule unter `app/ui/` von 110 bis 751 Zeilen. Der Schnitt lief
zeilentreu: jede der 175 Definitionen wurde vorher/nachher verglichen, einzige
inhaltliche Änderung sind zwei Seiten-Dekoratoren, die jetzt über
`zugang.seiten_registrieren()` laufen. Siehe README → „Architektur".

### AP5 · SQLite statt JSON — ✅ erledigt (6.8.2026)

Zeiten, Zuweisungen, Belege und Reinigungsdaten liegen in `rentaltool.db`
(`app/db.py`): Satz als JSON, generierte Spalten für die Suche, Transaktionen.
Die Fachmodule arbeiten unverändert mit Dicts. `config.json` und die
Ledger-Datei des Steuerarchivs bleiben Dateien. Übernahme über
`tools/migrate_db.py` mit Gegenlesen; die alten Dateien bleiben als
`*.vor-sqlite` liegen. Siehe README → „Datenhaltung: SQLite".

---

## Phase 2 — Alltag des Teams

### AP6 · Echte Handy-App (PWA) — ✅ erledigt (6.8.2026)

Manifest, Icons aus der Wortbildmarke, Start ohne Adressleiste, sichere Ränder
unter Kamera-Insel und Home-Balken, eigene Offline-Seite statt der
Browser-Fehlerseite, Anleitung zum Einrichten (Safari kennt keinen
Installations-Dialog). Der Service Worker speichert bewusst nur die eigenen
statischen Dateien. Siehe README → „Als App auf dem Handy".

**Vorher geprüft:** PWAs laufen auf dem iPhone; die EU-Abschaltung von
Februar 2024 wurde im März 2024 zurückgenommen, und seit iOS 26 gibt es gar
keine Anforderungen an die Installierbarkeit mehr.

### AP7 · Benachrichtigungen, die ankommen — ✅ erledigt (6.8.2026)

Web Push auf den Sperrbildschirm, zusätzlich zur E-Mail: neue Zuweisung,
Erinnerung am Vorabend (`tools/erinnerung.py`, täglich 18:00), „Arbeitszeit
fehlt", Schaden gemeldet. Je Mitarbeiter abschaltbar, Geräte in „Mein Konto"
sichtbar samt Testnachricht. Verschlüsselung über `pywebpush`; der Test macht
die Nachricht mit dem Schlüssel des Geräts wieder auf. Siehe README →
„Benachrichtigungen".

### AP8 · Zuweisung mit Kopf — ✅ erledigt (6.8.2026)

Stammzuständigkeit je Wohnung, Abwesenheiten zur Selbsteintragung, Vorschlag im
Einzeldialog und „Offene zuweisen" für alle unverteilten Reinigungen der
nächsten 14 Tage auf einem Blatt. Der Vorschlag nimmt die Stammkraft, überspringt
Abwesende und verteilt sonst nach Last; gespeichert wird nie automatisch. Siehe
README → „Zuweisen mit Vorschlag".

---

## Phase 3 — Betreiber-Auswertung

### AP9 · Kennzahlen-Dashboard — ✅ erledigt (6.8.2026)

Übersicht → Kennzahlen: Auslastung, Umsatz (ohne durchlaufende Steuer),
Reinigungs- und Materialkosten sowie Deckungsbeitrag je Wohnung und Monat,
dazu die teuersten Reinigungen. Rechnung in `app/kennzahlen.py` (ohne
Oberfläche, 20 Tests); die Preisregel teilt sie sich mit der Steueranmeldung
(`steuer.ohne_citytax`). Siehe README → „Kennzahlen: was bleibt übrig?".

---

## Phase 3.5 — Bedienung (eingeschoben am 6.8.2026)

Konzept mit Skizzen: <https://claude.ai/code/artifact/5869a152-6598-4a20-9f3e-9194ecf7289c>

Ausgangslage: Die Schublade links stammt aus der Zeit am Rechner. Seit AP6 läuft
die App als Symbol auf dem Home-Bildschirm – dort bedient man sie mit dem Daumen,
und ohne Adressleiste muss die Orientierung ganz aus der Oberfläche kommen.

**Entschieden am 6.8.2026:**

* **Vier Plätze unten**, der vierte ist immer das Menü.
* **Die Leiste richtet sich nach der Rolle.** Putzkraft: Reinigungen · Zeiten ·
  Belege. Verwaltung: Buchungen · Übersicht · Belege. Was nicht hineinpasst –
  Zeiterfassung, Beherbergungssteuer, Benutzer, Einstellungen, Mein Konto –
  liegt im Menü. Die Rechte bleiben in `ROLE_AREAS`.
* **Am Rechner ab 1024 px weiter die Schublade**, erzeugt aus derselben
  Bereichsliste wie die Leiste (zwei gepflegte Listen laufen auseinander).
* **Genau ein Zähler**, auf „Reinigungen", und nur wenn er größer als null ist.

Bewusst nicht: runder Knopf in der Mitte (keine eindeutige Hauptaktion – „Zeit
starten" steht in der Reinigungskarte, wo der Zusammenhang ist), Symbole ohne
Beschriftung, Wischen zwischen Bereichen (in den Buchungen wird schon gewischt).

### AP-D1 · Leiste unten und Menü — ✅ erledigt (6.8.2026)

Leiste unten am Handy, Menü als Blatt von unten, ab 1024 px weiter die Schublade.
Die Kopfzeile trägt nur noch Logo und Probe-Kennzeichen; Benutzer, Einstellungen,
Archiv, Mein Konto, Sprache und Abmelden sind ins Menü gezogen.

Alle drei Ansichten entstehen aus **einer** Quelle: `basis.nav_plan(rolle)` gibt
`(leiste, menue)` zurück – die ersten drei erlaubten Bereiche in der Reihenfolge
aus `ROLE_BAR`, der Rest ins Menü. Freigeschaltet wird dort nichts, die Rechte
bleiben allein in `ROLE_AREAS`. Beschriftungen sind rollenabhängig
(`ROLE_AREA_LABEL`: die Putzkraft liest „Reinigungen", nicht „Buchungen") und in
der Leiste gekürzt (`BAR_KURZ`: „Zeiten", „Steuer").

Der Zähler (`buchungen.nav_zaehler`) sitzt auf „Reinigungen" und ist der einzige
der App: für die Putzkraft, was heute noch ansteht, für die Verwaltung, was in
sieben Tagen niemandem gehört – am Fehlen der Zuweisung gemessen, damit
Überfälliges nicht durchrutscht. Er nutzt dasselbe Abruffenster wie die
Reinigungsliste und kostet Smoobu daher keinen zweiten Aufruf.

Der aktive Platz ist doppelt markiert (Farbe **und** Strich). Der
Checklisten-Durchgang ist kein eigener Platz, sondern hält „Reinigungen" aktiv
(`basis.PLATZ_VON`); liegt der Bereich im Menü, leuchtet der Menü-Platz.

30 Tests in `tests/test_navigation.py`. `tools/uishot.py` kennt die neuen Wege
(`@menue:`) und nimmt das Menü-Blatt mit auf.

*Größe:* M.

### AP-D2 · Bildschirme am Handy nachziehen — ✅ erledigt (6.8.2026)

**Kopfzeile.** Vier Bereiche hatten sie Zeile für Zeile nachgebaut; jetzt steht
sie einmal in `basis.bereichskopf`. Am Handy schrumpfen Symbol und Titel, die
Unterzeile tritt ganz zurück (`hidden sm:block` – sie bleibt im Markup). Das
gibt gut eine Zeile Inhalt zurück; die Reinigungsliste beginnt rund 65 Punkte
weiter oben.

**Die drei Zustände** stehen ebenfalls in `basis`: `leer()`, `stoerung()`,
`laedt()`. Wichtig ist der Unterschied zwischen den ersten beiden. Fällt Smoobu
aus, kamen null Buchungen zurück und die Liste meldete „Keine anstehenden
Reinigungen" – eine Putzkraft hätte daraus geschlossen, sie habe frei. Der
Merker `buchungen.abruf_fehler()` hält fest, ob der Abruf durchkam; ein Ausfall
steht jetzt als Ausfall da, mit Grund und „Nochmal versuchen".

**Tap-Ziele.** Die Aufgabenzeile der Checkliste ist die meistberührte Fläche der
App. Der Text gehört jetzt ins Kästchen statt daneben, damit die ganze Zeile das
Ziel ist (vorher: 20 Punkte, mit Putzhandschuhen aussichtslos), Mindesthöhe
44 Punkte; der Foto-Knopf ist nicht mehr `dense`.

*Bewusst nicht:* Die Abstände blieben, wie sie waren – der Inhaltsrahmen war mit
`p-3 sm:p-6 gap-4 sm:gap-5` schon am Gerät ausgerichtet. Kleine Unterlisten
(„Noch keine Einträge" in der Zeitenliste) haben weiter ihre karge Zeile: ein
Block mit großem Symbol wäre in einer Karte von drei Zeilen unangemessen.

8 Tests in `tests/test_bedienung.py`.

*Größe:* M.

### AP-D3 · Farb- und Abstandsrollen festschreiben — ✅ erledigt (6.8.2026)

Die Rollen stehen in `app/ui/ton.py`. Beim Aufräumen kamen zwei Befunde heraus,
die man einzelnen Bildschirmen nicht ansieht:

**Zwei Neutral-Skalen für eine Aufgabe.** Die hellen Stufen kamen aus `gray`
(191 Stellen: `text-gray-400`, `text-gray-500`), die dunklen aus `slate`. `gray`
ist neutral, `slate` blaustichig – in derselben Karte untereinander sieht man
den Bruch. Jetzt gibt es nur `slate`, mit Namen von `TITEL` bis `ZART`.

**Gleiche Bedeutung in zufälligen Stufen.** „Hinweis" war je nach Fundstelle
`amber-600`, `-700` oder `-800`. Vier Bedeutungen sind übrig: `HINWEIS`,
`DRINGEND` (nur der Wechseltag), `ERFOLG`, `STOERUNG` – jeweils mit `AUF_…` für
Text auf getönter Fläche, wo die hellere Stufe den Kontrast nicht trägt.

Dazu die Karte: ein Rezept, das an 18 Stellen Wort für Wort neu geschrieben
stand, mit Innenabständen zwischen `p-3` und `p-4`. Jetzt `KARTE_ENG` (Normal‑
fall) und `KARTE_WEIT`.

**Was das Paket hält, ist `tests/test_ton.py`** (120 Prüfungen über alle
Module): `gray` darf nirgends mehr vorkommen, Bedeutungsfarben nur in den
Stufen 700/800, das Kartenrezept nur an einer Stelle. Ein einmal aufgeräumtes
System ist nach drei Bereichen wieder unaufgeräumt – der Test ist der Grund,
warum es diesmal hält.

Nebenbefund: Der Namensprüfer (`tools/check_shadowing.py`) meldete sofort zwei
Funktionen mit einem Parameter `ton`, der das neue Modul überschattete. Sie
heißen jetzt `farbe`.

*Größe:* S–M.

---

## Phase 4 — Buchhaltung & Steuer

### AP10 · Belege bis zur EÜR — ✅ erledigt (6.8.2026)

Fachlogik in `app/buchhaltung.py`, Oberfläche im Reiter „Monatsabschluss" der
Belege.

**Die Kategorien sind wörtlich die SUMIF-Kriterien des Workbooks.** Die EÜR zieht
jede Position über einen Textvergleich; ein Buchstabe daneben – „Bertsch" statt
„Bartsch", ein Bindestrich statt des Halbgeviertstrichs – und die Summe bleibt
still auf null. Kein Fehler, keine Meldung, nur eine zu niedrige EÜR. Angeboten
werden die elf belegtypischen plus der Auffangposten
„Eingangsrechnung – Verwendungszweck unklar (prüfen)"; eigene kommen über
`config.beleg_kategorien` dazu. Am 6.8.2026 gegen das Workbook geprüft: alle 26
Kriterien treffen (`test_kategorien_sind_woertlich_die_kriterien_des_workbooks`,
läuft nur mit dem Workbook und `pip install openpyxl`).

**Belegdatum ≠ Uploaddatum.** Ein Beleg vom 29., der am 2. fotografiert wird,
gehört in den alten Monat – sonst wandert die Ausgabe ins nächste Quartal. Die
Liste gruppiert danach, nicht mehr nach `ts`.

**Geprüft wird vor dem Abschluss:** Pflichtfelder (Datum, Betrag, Händler,
Kategorie), der Auffangposten als Klärfall und Dubletten (gleicher Tag, Händler,
Betrag – zwei Leute fotografieren denselben Bon). Der Befund nennt Händler und
Feld; „3 Probleme" schickt nur suchen. Solange etwas offen ist, ist der
Abschluss gesperrt.

**Ausgabe:** CSV in den acht Spalten des Kontenjournals (`;`, utf-8-BOM,
deutsche Beträge, Ausgaben negativ) plus die Sammelmappe als PDF – Aufstellung
und danach jeder Beleg mit Kopfzeile. Angehängt wird von Hand; die
Bereichsgrenze `N` der SUMIF ist dabei nachzuziehen. Die App schreibt bewusst
nicht ins Workbook: die Buchhaltung bleibt, wo sie hingehört.

**Kategorisieren darf nur die Verwaltung** (`admin`, `manager`). Die Putzkraft
fotografiert und schreibt Händler, Betrag und wofür.

49 Tests in `tests/test_buchhaltung.py`. `tools/uishot.py` legt jetzt erfundene
Belege an – darunter einen ohne Kategorie und einen doppelt erfassten, sonst
zeigt das Prüfbild nur den guten Fall.

*Größe:* M.

### AP11 · Steuer-Workflow zu Ende — ✅ erledigt (6.8.2026)

Fachlogik in `app/meldung.py`, Anzeige oben im Steuer-Bereich.

**Status je Monat.** Bisher war das Archiv der einzige Merker, und es kennt nur
„für 2026-05 liegt ein PDF". Ein Monat, der berechnet, aber nie abgeschickt
wurde, sah aus wie einer, den nie jemand angefasst hat. Jetzt: offen → erzeugt →
gesendet → bezahlt. „erzeugt" und „gesendet" setzt die App selbst (sie legt ab
und verschickt), „bezahlt" bestätigt ein Mensch – sie sieht das Bankkonto nicht.
Ein Dokument im Archiv zählt als „erzeugt", damit auch Anmeldungen von vor AP11
richtig dastehen.

**Frist: der 7. des Folgemonats**, für Meldung *und* Überweisung. Fällt sie auf
Wochenende oder Feiertag, zeigt die App den nächsten Werktag (§ 108 Abs. 3 AO);
die Feiertage kommen aus `app/feiertage.py` und gelten für Sachsen. Überfälliges
steht rot mit Tageszahl.

**Vollständigkeitsprüfung** zwischen Ergebnis und „Erzeugen": läuft der Monat
noch, reisen Buchungen erst später ab, fehlt irgendwo ein Abreisedatum (die
fallen sonst still aus der Summe), ist der Monat leer – und ob für den Zeitraum
schon eine Anmeldung raus ist, ein zweites PDF also eine Korrekturmeldung wäre.
Gesperrt wird nichts: manchmal weiß der Mensch mehr als die Prüfung.

**`config.meldungen_ab`** begrenzt, ab wann die App zuständig ist. Ohne das
meldete eine frisch aufgesetzte Instanz zwölf überfällige Monate für Zeiträume,
die längst außerhalb erledigt wurden – im Prüfbild eine Wand aus Rot, die danach
niemand mehr liest. Ohne Einstellung zählt der älteste Monat im Archiv, sonst
der laufende.

32 Tests in `tests/test_meldung.py`.

**Offene Sachfrage ohne Code:** Die Wernerstraße rechnet mit **7 % statt 6 %**
Beherbergungssteuer. Die Gäste zahlen dort zu viel (Rechnung 71: 47,56 € statt
40,76 €), abgeführt werden korrekt 6 %. Gehört in Smoobu/Booking.com korrigiert.

*Größe:* M.

---

## Phase 5 — Rollen & Härtung

### AP12 · Feine Rechte & Login-Härtung — ✅ erledigt (7.8.2026)

**Benannte Rechte** in `app/rechte.py`. Vorher gab es zwei Grobraster:
`ROLE_AREAS` schaltete ganze Bereiche, und im Code stand acht Mal
`if _is_admin()`. Dazwischen nichts – wer Zeiten korrigieren sollte, brauchte
Administratorrechte und damit auch Benutzerverwaltung, Einstellungen und
Steuer. Jetzt steht dort, **was** jemand darf, nicht **wo** er hindarf; die
Bereiche bleiben in `ROLE_AREAS`, weil „sieht er die Belege?" und „darf er
einen löschen?" verschiedene Fragen sind.

Die Linie: **der Manager führt den Tag, der Betreiber verantwortet Nachweis und
Geld.** Manager ja – zuweisen, fremde Zeiten erfassen, Auftrag zurücksetzen,
Belege buchen. Manager nein – Beleg löschen (Beweismittel), abgerechnete Zeiten
ändern (liegt beim Steuerbüro), Benutzer, Einstellungen, Steuer.

**Login-Bremse** in `app/auth.py`: fünf Versuche frei, danach 30 s mit
Verdopplung bis 15 Minuten. Gezählt wird nach eingetipptem Namen, auch wenn es
das Konto nicht gibt – sonst verrät das Ausbleiben der Sperre, welche Namen
existieren. Der zweite Faktor wird mitgebremst: sechs Ziffern sind sonst schnell
durchprobiert.

**2FA für Administratoren:** ein dauerhafter Hinweis mit Direktlink, kein
Aussperren. Eine harte Pflicht bräuchte einen Notausgang über die
Kommandozeile – und wer sich selbst aussperrt, während die Putzkraft vor der
Wohnung steht, ist schlechter dran als vorher.

**Protokoll** (`app/protokoll.py`), sichtbar in der Benutzerverwaltung: Konten,
Rollen, gelöschte Belege, wieder geöffnete Monatsabschlüsse, zurückgesetzte
Steuermeldungen. Kein Vollprotokoll – notiert wird, was jemandem schadet, wenn
es unbemerkt bleibt. Es gibt bewusst keine Funktion zum Löschen eines Eintrags.

**Dienstbenutzer: vorbereitet, nicht ausgerollt.** `deploy/rentaltool.service`
läuft als `rentaltool` statt `root` und ist gehärtet (`ProtectSystem=strict`,
schreibbar nur der Datenordner). Der Weg dorthin samt Rückweg steht in
`docs/UMSTELLUNG-DIENSTBENUTZER.md`; der wahrscheinlichste Stolperstein ist der
rclone-Mount der Nextcloud, der ohne `--allow-other` für den neuen Benutzer
unlesbar ist und die nächtliche Sicherung still scheitern ließe.

*Nebenbefund:* Der PWA-Hinweis aus AP6 stand innerhalb von `content` – und
`activate()` leert das bei jedem Bereichswechsel. Er war also seit AP6 nach dem
ersten Klick weg; gemerkt hat es niemand, weil er ohnehin erst im Browser
sichtbar wird. Hinweise stehen jetzt daneben, nicht darin.

30 Tests in `tests/test_rechte.py`.

*Nachgebessert am 7.8.2026 (Gerätebefund iPhone 17 Pro):* Die Leiste war zu
niedrig – „Buchungen" links und „Menü" rechts lagen in der Rundung der
Displayecke und waren vom Gehäuse angeschnitten. `safe-area-inset-bottom`
allein deckt das nicht ab: der Inset beschreibt den Home-Balken, nicht den
Eckradius. Jetzt 66 statt 56 Punkte hoch, seitlich mindestens 14 Punkte
Abstand (`safe-area-inset-left/right`, falls größer) und unten mindestens 10.
Gemessen am Prüfbild: die Schrift beginnt 24 statt 16 Punkte vom Rand und endet
19 statt 7 Punkte über der Unterkante. Die Höhe steht als CSS-Variable
`--leiste-hoehe`, weil das Menü-Blatt darauf aufsetzt.

*Größe:* M.

---

## Bewusst nicht auf dem Fahrplan

* **Mandantenfähigkeit** (das Tool für fremde Vermieter) – ändert die
  Architektur grundlegend und ist ohne Phase 0–1 nicht sinnvoll.
* **Checklisten wieder einschalten** – bewusst aus (`checklisten_aktiv`), bis
  der Alltag ohne sie rundläuft.
* **Belege aus dem Postfach holen** – am 7.8.2026 verworfen. Technisch möglich
  (`rechnung-automation` liest Postfächer über Microsoft Graph), aber es bringt
  Postfachzugang, Filterregeln je Absender und Dublettenschutz mit. Hochladen
  reicht.
* **Automatisierte Gästekommunikation** – Nachrichten lesen/senden gibt es
  bereits; Vorlagen und Automatik sind ein eigenes Thema.

---

## Phase 6 — Buchhaltung im Werkzeug (eingeschoben am 7.8.2026)

Konzept mit Befunden und Entscheidungen:
<https://claude.ai/code/artifact/386595d4-1535-49d7-9948-2f9ae26159a7>

Ziel: Ausgangsrechnungen entstehen hier statt in Smoobu, Eingangsrechnungen
werden wie in einer Buchhaltung verarbeitet, die Bank kommt als CSV dazu, und am
Ende steht die EÜR. Grundlage sind drei Befunde aus den echten Smoobu-Daten
(85 Buchungen 2026, abgefragt am 7.8.):

* **Die Anschrift gibt es** – nicht an der Buchung, aber an
  `GET /api/guests/<guestId>`. Booking.com liefert sie zu 81 %. Über 250 € *und*
  ohne Anschrift sind nur 12 Buchungen im Jahr, rund zwei im Monat.
* **Die Aufschlüsselung ist lückenhaft** – 78 von 85 tragen eine
  Reinigungsgebühr, 58 eine Übernachtungssteuer, 55 eine Mehrwertsteuer.
  Verlässlich ist allein der Gesamtbetrag.
* **Der Reinigungspreis hängt am Buchungstag**, nicht am Aufenthalt (siehe AP13).

**Entschieden am 7.8.2026:** Anschrift nachtragbar im Entwurf, ohne sie kein
Versand · 7 % jetzt, 19 % vorgesehen · ein Nummernkreis je Jahr, vom Werkzeug
geführt · Versand nur auf Wunsch, einzeln oder als Stapel.

### AP13 · Stammdaten: Produkte, Preise, Kreditoren — ✅ erledigt (7.8.2026)

`app/stammdaten.py`. Drei Produktarten: **Übernachtung** (der Restbetrag),
**Endreinigung** (fester Preis je Wohnung) und **Beherbergungssteuer**
(durchlaufend, keine USt). Steuersätze 7 % und 19 % – letzterer ist vorgesehen,
damit ein künftiges Produkt eine Zahl braucht und keinen Umbau.

**Der tragende Befund: Preise brauchen ein „gültig ab", und gefragt wird mit dem
Buchungstag.** Die Cottaer Straße stieg von 65 € auf 75 €. Nach Anreisedatum
sortiert springen die Beträge neunzehnmal hin und her und sehen aus wie Zufall –
nach *Buchungsdatum* ist es eine saubere Kante: wer vor dem 4.1.2026 gebucht hat,
zahlt 65 (72 Buchungen), wer danach buchte, 75 (27 Buchungen, ausnahmslos). Zwei
Gäste, die im selben Monat anreisen, zahlen also verschieden. Wer die Frage
falsch stellt, rechnet alte Rechnungen falsch nach und merkt es nie, weil beide
Zahlen plausibel aussehen.

Der hinterlegte Preis ist dabei **nicht** die Quelle für die Rechnung – Smoobu
liefert die tatsächlich berechnete Gebühr, und die gilt. Er ist die Gegenprobe
und der Rückfall für die sieben Buchungen ohne Angabe.

**Kreditoren** bringen Kategorie (wörtlich ein SUMIF-Kriterium), Kostenstelle
und Dauerbeleg mit; erkannt werden sie über Muster im Händlernamen, wobei das
längste Muster gewinnt. Zehn bekannte Lieferanten aus dem Kontenjournal stehen
als Vorgabe bereit. Sichtbarer Nutzen sofort: ein neuer Beleg von Rossmann trägt
seine Kategorie schon beim Anlegen.

Gepflegt wird beides in **Einstellungen → Produkte & Kreditoren**. Die
Erstbefüllung läuft ausdrücklich nicht von selbst: was sich von allein anlegt,
traut sich niemand zu ändern.

*Nebenbei:* `basis.spaeter()` gibt es jetzt für den Fall, der im Projekt zum
vierten Mal auftrat – ein Klick, der die Spalte neu aufbaut, in der er selbst
steckt.

34 Tests in `tests/test_stammdaten.py`.

*Nachgezogen am 7.8.2026:* Der Beleg-Upload nahm bis dahin **nur Bilder** an
(`accept="image/*"`). Lieferantenrechnungen kommen aber als PDF per Mail und
werden nicht abfotografiert. Jetzt nimmt er beides. Eine PDF wird dabei **nicht**
zugeschnitten und nicht neu gebaut – sie ist bereits das Dokument; erzeugt wird
nur ein Vorschaubild aus der ersten Seite. Erkannt wird sie am Inhalt
(`%PDF-`), nicht an der Dateiendung, die bei Mail-Anhängen regelmäßig lügt.

Nebengewinn: Aus einer echten PDF wird der **Text gelesen statt geraten** –
Betrag und Lieferant stehen dort exakt, wo die Zeichenerkennung bisher schätzen
musste. Nur eingescanntes Papier (unter 20 Zeichen Textschicht) geht weiterhin
durch die OCR.

*Größe:* S–M.

### AP-L · Lohnvorschau und Minijob-Grenze — ✅ erledigt (7.8.2026)

Eingeschoben vor AP14. Wer sich eine Reinigung nimmt, sah bisher erst am 19.,
was dabei herauskam. Für einen Minijob ist das zu spät: **wird die Grenze
überschritten, ist die Beschäftigung nicht mehr geringfügig** – mit Folgen für
Sozialversicherung und Steuer, die niemand rückwirkend geradebiegt.

In der Zeiterfassung steht jetzt oben, was der Monat voraussichtlich bringt:
bereits erfasst, plus die zugewiesenen Reinigungen, die noch anstehen, mit
Balken gegen die Grenze.

**Die Grenze wird gerechnet, nicht gepflegt** (`app/lohn.py`): Mindestlohn × 130
÷ 3, aufgerundet (§ 8 Abs. 1a SGB IV). Die Formel trifft alle vier bekannten
Werte – 538 (2024), 556 (2025), 603 (2026), 633 (2027). Zu pflegen ist nur der
Mindestlohn; eine fest eingetragene Grenze wäre spätestens im Januar falsch, und
zwar still.

Die Dauer einer noch offenen Reinigung schätzt der **Median** der bisherigen
Einsätze dieses Mitarbeiters – ein einziger vergessener Check-out über Nacht
würde den Durchschnitt für Monate verderben. Ohne Erfahrung 90 Minuten.

**Mehr zu arbeiten ist kein Fehler.** Wer über die Grenze kommt, verliert die
Stunden nicht: Ausgezahlt wird höchstens bis zur Grenze, der Rest bleibt als
**Zeitkonto** stehen und kommt in einem Monat mit Luft dazu. Ohne das müsste
jemand Arbeit ablehnen, die längst getan ist. Der Kontostand wird über alle
abgeschlossenen Monate von vorn gerechnet, nicht gespeichert – so kann er nicht
von den erfassten Zeiten abweichen.

Die Karte zeigt deshalb den **auszahlbaren** Betrag, nicht den erarbeiteten, und
darunter, was aufs Konto geht. Der Balken läuft nie über 100 % – ein voller
Balken mit Überlauf sähe aus wie ein Fehler und ist keiner.

**Für die Verwaltung** steht dieselbe Rechnung als Team-Ansicht in der
Zeiterfassung: alle Mitarbeiter mit Auslastung, Zeitkonto und offenen
Einsätzen, die Vollsten oben. Beim Zuweisen ist genau das die Frage – wer hat
noch Luft? Ohne die Ansicht suchte man sie aus vier Bildschirmen zusammen, und
im Zweifel bekam die Arbeit, wer zuletzt gefragt wurde. Sie hängt am Recht
`ZEITEN_FREMDE`, also an Betreiber und Managerin; die Putzkraft sieht weiterhin
nur die eigene Zahl.

31 Tests in `tests/test_lohn.py`.

*Größe:* S.

### AP-V · Buchungen zwei Monate im Voraus — ✅ erledigt (7.8.2026)

Die Reinigungsliste und der Kalender blickten **21 Tage** nach vorn, zweimal
fest im Quelltext. Am Monatsanfang reichte das kaum über den laufenden Monat
hinaus – wer im August für Oktober planen wollte, sah nichts. Jetzt 60 Tage,
einstellbar unter Einstellungen → Smoobu (`buchungen_vorschau_tage`).

Der Abruf kostet dadurch praktisch nichts mehr: bei knapp hundert Buchungen im
Jahr bleibt auch das größere Fenster eine einzige Seite bei Smoobu.

Nebenbei behoben: Mit 21 Tagen fehlten der Lohnvorschau am Monatsanfang die
Reinigungen der letzten Monatswoche – sie versprach zu wenig. Ein Test hält
jetzt fest, dass das Fenster mindestens bis zum Ende des Abrechnungsmonats
reicht.

*Größe:* S.

### AP14 · Ausgangsrechnung aus der Buchung — offen

### AP15 · Eingangsrechnungen mit Kreditor und Kostenstelle — offen

### AP16 · Kontoauszug einlesen und zuordnen — offen

### AP17 · EÜR im Werkzeug — offen

### AP18 · Ablage in der Nextcloud — offen
