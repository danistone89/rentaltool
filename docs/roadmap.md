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
  **Erneut offen seit AP28** – die Begründung „Hochladen reicht" gilt für
  E-Rechnungen nicht mehr (siehe die offene Frage bei AP28a).
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

### AP14 · Ausgangsrechnung aus der Buchung — ✅ erledigt (7.8.2026)

`app/rechnung.py` (Fachlogik), `app/rechnung_pdf.py` (Layout),
`app/ui/rechnungen.py` (Bereich „Rechnungen", nur Betreiber).

**Rückwärts gerechnet, weil nur der Gesamtbetrag verlässlich ist:** Betrag
minus Beherbergungssteuer minus Reinigung ergibt die Übernachtung. Die erste
Zeile kommt aus `steuer.ohne_citytax` – derselben Funktion, die die
Steueranmeldung trägt. Die Summe der Positionen muss den Smoobu-Betrag auf den
Cent treffen, sonst entsteht kein Entwurf, sondern ein Klärfall.

**Gegengeprüft an 219 echten Buchungen:** 186 teilen sich sauber auf. Die
übrigen sind keine Fehler der Rechnung, sondern Funde in den Daten – 29 mit
abweichender Reinigungsgebühr (die Prüfung schlägt also an), drei ohne Betrag
und eine, deren Reinigungsgebühr größer ist als der ganze Aufenthalt.

**Die Anschrift** kommt aus `/api/guests/<guestId>` über einen Zwischenspeicher:
vier Abrufe für den ganzen Bestand statt einer je Buchung. Fehlt sie und liegt
der Betrag über 250 €, entsteht der Entwurf trotzdem – aber er sagt es, und
ohne sie geht kein Versand.

**Zweistufig:** Ein Entwurf trägt noch keine Nummer und lässt sich wegwerfen.
Erst das Festschreiben vergibt sie, legt die Rechnung revisionssicher ab und
macht sie unveränderlich. Korrigiert wird durch Storno – die Nummer bleibt
vergeben, denn eine verschwundene Rechnungsnummer ist ein Mangel, den jede
Prüfung findet. Ein Nummernkreis je Jahr; nur das Umstellungsjahr beginnt bei
`rechnung_startnummer`, jedes weitere bei 1.

**Versand nie von allein**, einzeln oder als Stapel. `mailer.send_form` kann
jetzt einen anderen Empfänger als den konfigurierten – der ist die Stadt, und
eine Gastrechnung dorthin wäre ein Datenschutzvorfall.

*Nebenbei:* Die eingebauten PDF-Schriften kennen nur Latin-1 – „€" und „–"
werden dort still zu einem Punkt. Auf der Rechnung steht deshalb „EUR" und ein
schlichter Bindestrich, und `_darstellbar()` fängt den Rest ab. Dazu sechs neue
Pflichtfelder im Betreiberprofil (§ 14 Abs. 4 UStG); fehlen sie, sagt es der
Bereich.

36 Tests in `tests/test_rechnung.py`.

*Größe:* L.

### AP14b · Rechnung so aufstellen, wie der Gast sie liest — ✅ erledigt (7.8.2026)

Die Rechnung zeigte drei Spalten (Netto, USt, Brutto), eine Summenstaffel und
darunter einen Steuernachweis. Fachlich vollständig, aber der Gast sucht darin
den Betrag, den er bezahlt hat – und findet ihn erst nach dem Zusammenzählen.

**Der Aufbau folgt jetzt der abgestimmten Vorlage**
(`Beispielrechnung_B2B_Ferienzimmer`), die Gestaltung ausdrücklich nicht:
Logo oben links · Anbieterdaten oben rechts · Anschriftfeld · Titel mit Nummer
und Datum daneben · ein Block Aufenthalt/Gast/Zeitraum · die Aufstellung mit
Netto/USt./Brutto · die Zwischensumme „Beherbergungsleistungen" · die
Beherbergungssteuer mit „nicht steuerbar" · Gesamtbetrag · Steuerinformation ·
Hinweis · eine Fußzeile aus drei Spalten (Betreiber, Steuerdaten,
Bankverbindung). Gesetzt wird zurückhaltend – Haarlinien statt großflächiger
Farbe. Zwei Flächen sind übernommen: die **hell hinterlegte Zwischensumme**
(sonst liest sie sich wie eine weitere Position) und der **Gesamtbetrag in
einem Kasten in der Hausfarbe**.

**Die Abstände folgen DIN 5008 Form A** (ISO 269 regelt nur die Fensterformate
der Umschläge). Zwei Abweichungen der bisherigen Fassung sind damit behoben:
der linke Rand stand auf 22 mm statt 24,1 mm, und die Empfängeranschrift begann
auf 50,7 mm statt in der **Anschriftzone ab 44,7 mm** – im Fenster eines
DIN-Umschlags saß sie damit zu tief. Die Rücksendeangabe stand genau auf der
Zonengrenze und ist jetzt darüber. Vier Tests messen die Millimeter am
erzeugten PDF.

**Ein Logo lässt sich hochladen** (Einstellungen → Betreiber). Es liegt wie die
Fotos im Medienordner; derselbe Name zeigt es in der Oberfläche unter
`/media/…` und im PDF. Ein fehlendes oder unlesbares Bild lässt die Ecke leer,
statt den Beleg zu verhindern.

Die Steuerinformation nennt Entgelt, Satz und Steuerbetrag in einer Zeile
(§ 14 Abs. 4 Nr. 8 UStG); bei mehreren Steuersätzen bekommt jeder eine eigene.

Auf dem Blatt heißt es „Übernachtung / Beherbergung" und „Beherbergungssteuer
Dresden". Die **gespeicherten** Bezeichnungen bleiben unangetastet – an ihnen
hängen Produktpreise, Auswertungen und die festgeschriebenen Rechnungen.

*Nebenbei zwei technische Funde:* Geschrieben wird jetzt mit `fitz.TextWriter`
statt `insert_text` – letzteres kodierte nach Latin-1 und machte aus „€" und
„–" still einen Punkt, weshalb auf der Rechnung „EUR" stand. Und weil ein
TextWriter nur eine Farbe je Durchgang kann, hätte eine Gruppierung nach Farbe
die **Lesereihenfolge** im PDF zerstört (der Gesamtbetrag stand im Textstrom
vor der Aufstellung); `_in_lesereihenfolge()` sortiert vorher zeilenweise.

25 Tests in `tests/test_rechnung_pdf.py`.

*Größe:* M.

### AP14c · Von Smoobu nur noch den Gesamtbetrag glauben — ✅ erledigt (7.8.2026)

Die Beherbergungssteuer wurde übernommen, wenn Smoobu sie auswies. Nachgemessen
an den 135 Buchungen der beiden Fixture-Monate rechnet **Booking.com auf
denselben zwei Wohnungen nach drei Formeln**: 76× sechs Prozent nur auf die
Übernachtung (die Reinigung fehlt in der Basis), 37× sechs Prozent richtig,
18× sieben Prozent (Wernerstraße). Richtig ist nach § 4 Abs. 1 der Satzung und
FAQ 5.2 das Entgelt einschließlich Reinigungsgebühr.

**Was das anrichtete:** Die Gastrechnung wies die Zahl des Portals aus,
angemeldet wurden 6 % der Basis. Über dieselben 135 Buchungen klafften
zwischen beidem **263,31 €**, die in keiner der beiden Zahlen vorkamen –
größter Einzelfall 9,26 € bei einer Rechnung über 991,16 €.

**Jetzt:** von Smoobu kommen nur noch der **Gesamtbetrag** und die
**Reinigungsgebühr**. Die Steuer wird gerechnet (`price / 1,06`), an einer
einzigen Stelle für Rechnung, Anmeldung und Auswertung. Damit gilt für jede
Buchung: Basis + Steuer = Rechnungsbetrag **und** Steuer = 6 % der Basis. Die
Probe geht auf null auf. Rechnet ein Portal zu viel, bleibt der Überhang im
Entgelt – er ist keine Steuer, die wir schulden. Airbnb bleibt unberührt.

**Folge, die eine Entscheidung braucht:** Die Dezember-Anmeldung wurde mit
5.698,29 € / 341,90 € eingereicht, nach der neuen Regel wären es 5.652,71 € /
339,16 € (−2,74 €). Mai 2026 geht in die andere Richtung: +1,27 €. Ob
berichtigt wird, entscheidet der Betreiber.

*Größe:* M.

### AP15 · Eingangsrechnungen mit Kreditor und Kostenstelle — in Arbeit (7.8.2026)

AP13 hat die Kreditoren angelegt und die Erkennung gebaut: `kreditor_zu()` findet
zu einem Händlernamen den Lieferanten, `vorbelegung()` liefert dessen Kategorie
und Wohnung. Beim **Anlegen** eines Belegs wird das schon genutzt.

Was fehlt, ist der Rückweg:

1. **Der Kreditor steht nicht am Beleg.** Nur seine Kategorie fließt ein; wer
   später hineinsieht, erfährt nicht, welcher Lieferant erkannt wurde.
2. **Die Zuordnung lernt nicht.** Setzt man die Kategorie von Hand, merkt sich
   das niemand – beim nächsten Beleg desselben Händlers rät die App wieder.
   Genau das ist die Zeitersparnis, die AP13 versprochen hat.
3. **Die Kostenstelle ist die Wohnung.** Für Verwaltungskosten, die keiner
   Wohnung gehören, gibt es keine Ablage.

**Schritt 1 (dieser):** Kategorie von Hand setzen lernt den Kreditor.
Trifft ein vorhandener Kreditor, bekommt er die Kategorie; trifft keiner, wird
einer angelegt – mit `quelle: "gelernt"`, damit man die selbst entstandenen von
den gepflegten unterscheiden kann. Das Muster ist der normalisierte
Händlername („ROSSMANN 2540" → „rossmann"), also dieselbe Form, die
`kreditor_zu()` beim Suchen benutzt. Der Kreditor wird am Beleg gespeichert
(`kreditor_id`), damit die Zuordnung nachvollziehbar bleibt.

Bewusst **kein** stilles Überschreiben: eine von Hand gepflegte Kategorie am
Kreditor wird nur geändert, wenn sie leer ist oder der Kreditor selbst gelernt
wurde. Sonst kippt ein einzelner falsch zugeordneter Beleg die Stammdaten.

**Schritt 2:** Kreditor am Beleg sichtbar und änderbar.
**Schritt 3:** Kostenstelle als eigenes Feld (Wohnung oder Verwaltung).

*Größe:* M.

---

## Phase 7 — Die Zahlen jederzeit sehen (geprüft und neu gefasst am 7.8.2026)

### Wofür das hier ist – und wofür nicht

**Festgelegt am 7.8.2026:** Das Werkzeug rechnet **nicht für das Finanzamt.**
Steuererklärung, Umsatzsteuer-Voranmeldung und EÜR macht der Steuerberater. Das
Werkzeug soll **einen aktuellen Überblick** geben: was kommt rein, was geht
raus, was bleibt – je Monat und je Wohnung.

**Der Anlass ist der Verzug.** Der Steuerberater hinkt gelegentlich acht bis
zehn Monate hinterher. So lange ist der Betrieb im Blindflug: kein Ergebnis,
keine Kostenentwicklung, keine Grundlage für Preise oder Anschaffungen. Genau
diese Lücke schließt das Werkzeug – heute tut das ein Excel-Workbook von Hand,
und auch das nur bis zum 30.6.

**Was das streicht.** Ein Überblick muss *stimmen*, aber er muss nicht
*prüfungsfest* sein. Damit fallen weg:

| Gestrichen | Warum |
|---|---|
| **USt-Voranmeldung als Formular** (AP21) | Macht der Steuerberater. Bleibt: die Umsatzsteuer als **Liquiditätszahl** – wie viel vom Kontostand gehört dem Finanzamt. |
| **GoBD-Verfahrensdokumentation** | Nötig für eine Buchhaltung *of record*. Die führt der Steuerberater. |
| **Anlagenverzeichnis mit AfA** (AP22) | Die Abschreibung rechnet der Steuerberater. Für den Überblick genügt ein fester Monatswert, damit das Ergebnis nicht zu gut aussieht. |
| **§ 13b in aller Feinheit** | Für die Voranmeldung entscheidend, fürs Ergebnis nicht – die Steuer ist geschuldet und abziehbar zugleich, ein Nullsummenspiel. |
| **Die Zwei-Stichtage-Asymmetrie** | War die Konsequenz der Ist-Versteuerung für eine *korrekte Voranmeldung*. Für den Überblick gilt schlicht: wann das Geld geflossen ist. |

Die Ist-Versteuerung bleibt trotzdem die richtige Grundlage – ein Überblick auf
Zahlungsbasis zeigt, was tatsächlich da ist. Keine Barzahlungen heißt: **alles
läuft über die Bank**, es gibt keine zweite Quelle.

### Was übrig bleibt – und was der erste Durchgang übersah

Nachgesehen im Code: fünf Bausteine fehlten ganz, und die Reihenfolge stimmte
nicht.

### Was fehlt (nachgeprüft, nicht vermutet)

| Fehlt | Warum es auch für einen bloßen Überblick zählt |
|---|---|
| **Vorsteuer je Beleg** | Ein Beleg trägt nur `amount` – brutto. Die Umsatzsteuer ist für den Betrieb ein durchlaufender Posten; wer sie mitzählt, hält seine Kosten für höher, als sie sind. Der Überblick braucht **netto**. |
| **Zahlungsabgleich** | Eine Ausgangsrechnung kennt `entwurf/festgeschrieben/gesendet/storniert` – aber nicht **bezahlt**. Ohne Zahlungsdatum kein Zufluss, und ohne Zufluss kein aktuelles Ergebnis. |
| **Umsatzsteuer als Liquiditätszahl** | Nicht als Formular, sondern als Frage: wie viel vom Kontostand gehört schon dem Finanzamt? Ohne das sieht der Kontostand besser aus als die Lage. |
| **Anlagen und Darlehen** | Nicht als Verzeichnis. Aber **Tilgung ist keine Ausgabe** und **Abschreibung ist eine** – wer beides ignoriert, liest ein Ergebnis, das es nicht gibt. Feste Monatswerte genügen. |
| **Portalprovision** | Siehe unten – der schwerste Fund. |

### Warum die Reihenfolge falsch war

Ein Überblick auf Zahlungsbasis (und die Ist-Versteuerung sagt dasselbe) zählt
den Tag, an dem das Geld fließt. Das Werkzeug bucht Belege heute nach
*Belegdatum* und Rechnungen nach *Rechnungsdatum*.

**Die Kontobewegungen sind deshalb nicht ein Paket neben der Auswertung,
sondern ihr Fundament.** AP17 kann nicht vor AP16 fertig werden.

### Zweiter Durchgang: die Erlösseite fehlte ganz

Die erste Fassung dieser Phase sah nur auf die **Ausgabenseite**. Nachgeprüft:
**„Provision" kommt im Code nicht vor** – nur als Prosa in zwei Kommentaren.
Das ist die größte Lücke von allen:

> **Airbnb und Booking zahlen NETTO aus.** Was auf dem Konto ankommt, ist der
> Gastpreis **minus Provision**. Bucht man diesen Betrag als Erlös, ist die EÜR
> auf **beiden** Seiten zu niedrig: der Erlös um die Provision, die
> Betriebsausgabe um denselben Betrag. Das Ergebnis stimmt zufällig – die
> Umsätze nicht, und die USt-Voranmeldung erst recht nicht.

Dazu kommt: **Nicht jede Einnahme hat eine Rechnung.** Die EÜR muss alles
erfassen, was zugeflossen ist. Ein Zahlungseingang ohne Gegenpart darf kein
stiller Rest bleiben.

Und im Zahlungseingang eines Gastes steckt die **Beherbergungssteuer** – ein
durchlaufender Posten, der kein Erlös ist. Die Zuordnung muss ihn heraustrennen.

### Weitere Funde des zweiten Durchgangs

| Fehlt | Befund |
|---|---|
| **Dauerbelege** | `dauerbeleg` ist ein Textfeld am Kreditor mit Tooltip – mehr nicht. Miete, Darlehen und Smoobu werden monatlich abgebucht, ohne dass jemand einen Beleg fotografiert. Sie müssen ohne Monatsbeleg buchbar sein. |
| **Übernahmestichtag** | Das Workbook ist auf den 30.6.2026 gebucht. Beginnt das Werkzeug zu rechnen, ohne dass ein Stichtag feststeht, zählt das Halbjahr doppelt. |
| **Vollständigkeit und Abstimmung** | Eine Lücke im Bank-CSV meldet niemand – sie sieht aus wie ein ruhiger Monat. Nötig: Saldo-Abgleich, lückenlose Zeiträume, „Bewegung ohne Gegenpart" (das Blatt „Fehlende Belege" des Workbooks). |
| **GoBD-Verfahrensdokumentation** | Pflicht, sobald die Buchhaltung im Werkzeug entsteht. Kommt in keinem Paket vor. |

### Entschieden am 7.8.2026: Ist-Versteuerung, keine Barzahlungen

**Ist-Versteuerung** (§ 20 UStG): die Umsatzsteuer entsteht mit dem
**Zahlungseingang**, nicht mit der Rechnung. Damit hängt die Voranmeldung
(AP21) zwingend am Zahlungsabgleich (AP20) – der teurere der beiden Wege.

**Keine Barzahlungen**: kein Kassenbuch nötig. Und weil damit **jeder** Erlös
über die Bank läuft, ist der Kontoimport (AP16) nicht nur das Fundament der
EÜR, sondern auch das der Umsatzsteuer.

> **Die Asymmetrie, die daraus folgt – und die man leicht übersieht:**
> Die Ist-Versteuerung betrifft nur die **eigene** Umsatzsteuer. Der
> **Vorsteuerabzug** hängt nach § 15 UStG am Rechnungseingang und der
> erbrachten Leistung, **nicht** an der Zahlung (Ausnahme: Anzahlungen).
> Die Voranmeldung zieht also aus **zwei verschiedenen Stichtagen**:
>
> | Zeile | Stichtag | Quelle |
> |---|---|---|
> | Umsatzsteuer 7 %/19 % | Zahlungs**eingang** | AP20 |
> | Vorsteuer | **Rechnungsdatum** des Belegs | AP15/AP19 |
> | § 13b (Booking, Meta) | Leistungs-/Rechnungsmonat | AP19/AP23 |
>
> Ein Werkzeug, das alles über einen Stichtag rechnet, liefert eine falsche
> Voranmeldung. **Vom Steuerberater bestätigen lassen**, bevor AP21 gebaut wird.

Zweite Folge: Gäste zahlen oft **vor** dem Aufenthalt. Bei Ist-Versteuerung
entsteht die Umsatzsteuer schon mit dieser Zahlung – der Umsatzmonat ist also
nicht der Aufenthaltsmonat. Für die Beherbergungssteuer gilt weiter der
**Abreisemonat** (§ 6 der Satzung). Zwei Steuern, zwei Stichtage, dieselbe
Buchung.

### Die Kette, in dieser Reihenfolge

```
Ausgaben:  Beleg (AP15) ──► Vorsteuer (AP19) ──┐
                                               ├──► Zuordnung ──► EÜR (AP17)
Erlöse:    Rechnung (AP14) ──► Provision (AP23)┤     (AP20)         USt-VA (AP21)
                                               │
Geld:      Konto (AP16) ───────────────────────┘
```

AP19 und AP16 hängen nicht voneinander ab und können nebeneinander laufen.
Alles läuft in **AP20** zusammen – das ist das schwerste Paket, nicht AP17.

### AP19 · Vorsteuer und Steuersätze am Beleg — offen *(vor AP17)*

Netto, Steuersatz und Steuerbetrag je Beleg statt nur eines Bruttobetrags; ein
Kennzeichen für **§ 13b** (Booking, Meta) und für „ohne Vorsteuerabzug". Die
OCR liest den Steuerbetrag, wo er auf dem Beleg steht.

**Zusammen mit AP28a bauen.** Bei einer E-Rechnung stehen genau diese Felder
exakt im eingebetteten XML – Raten ist dort weder nötig noch erlaubt. Wer AP19
allein auf die OCR baut, baut den schwierigeren Fall zuerst. *Größe:* M.

### AP16 · Kontobewegungen einlesen — ✅ erledigt (7.8.2026)

Beide Auszüge werden eingelesen: DKB-Business und DKB-VISA-Karte. Gebaut gegen
die **echten Exporte** vom 24.7.2026, nicht gegen erfundene Muster – zwei
Fallen wären sonst nicht aufgefallen.

**Das Format erkennt sich am Inhalt**, nicht am Dateinamen: beide Dateien haben
vier Kopfzeilen (Kontoname, Zeitraum, Saldo) vor der Spaltenzeile, gesucht wird
nach `Buchungsdatum` (Konto) bzw. `Belegdatum` (Karte). Eine fremde Datei sagt
das in einem Satz – eine stumm leere Liste sähe aus wie ein Monat ohne Umsätze.

**Falle 1: die zweistellige Jahreszahl.** Die DKB schreibt `24.07.26`. Ohne
Auslegung wäre das das Jahr 26. Ausgelegt wird ins Jahrhundert von heute; was
mehr als ein Jahr in der Zukunft läge, gilt als Vorjahrhundert (`01.01.99` →
1999).

**Falle 2: der Kreditkarten-Ausgleich steht in BEIDEN Auszügen** – im Girokonto
als Abbuchung („KREDITKARTENABRECHNUNG VISA"), auf der Karte als Gutschrift
(„Ausgleich Kreditkarte"). Wer beide einliest und alles zusammenzählt, zählt
die Kartenkäufe doppelt. Es ist keine Ausgabe, sondern eine **Umbuchung
zwischen eigenen Konten**: erkannt, gekennzeichnet und aus Summen
herausgehalten – aber im Auszug sichtbar, denn passiert ist sie.

**Ein zweiter Import darf nichts kaputtmachen.** Auszüge überschneiden sich.
Der Satzschlüssel ist der Fingerabdruck der Bewegung (Konto, Datum, Betrag,
Text) statt einer laufenden Nummer, die in jedem Export neu beginnt. Beim
erneuten Einlesen werden die Bankfelder aufgefrischt, die eigenen Zuordnungen
(Beleg, Rechnung, Kategorie) **nicht angerührt** – sonst wäre jede Wiederholung
ein Rückschritt.

Neuer Bereich **Konto** in der Oberfläche: Auszug hochladen, Summen je Monat,
Bewegungsliste. Die Rückmeldung nennt bewusst auch die Dubletten – bei
überlappenden Auszügen ist es der Normalfall, dass aus 169 Zeilen 12 neue Sätze
werden.

Gegen die echten Dateien geprüft: 169 + 24 Bewegungen, je 6 Umbuchungen auf
beiden Seiten erkannt, keine Dublette. `app/kontoauszug.py` (Lesen, ohne
Datenbank) und `app/konto.py` (Ablage) getrennt, 26 Tests in
`tests/test_kontoauszug.py`.

*Größe:* L.

### AP23 · Portalabrechnung: brutto buchen, Provision als Ausgabe — offen

Der Erlös ist der **Gastpreis**, die Provision eine **Betriebsausgabe** – auch
wenn nur die Differenz auf dem Konto ankommt. Je Kanal verschieden: Airbnb
zahlt netto aus (earnings-PDF), Booking rechnet die Provision teils getrennt ab.

Fürs Ergebnis ist das ein Nullsummenspiel – für den **Überblick** nicht: ohne
dieses Paket kennt man weder den echten Umsatz noch, was die Portale kosten.
Das ist eine der Zahlen, wegen derer das Werkzeug überhaupt gebaut wird.
*Größe:* M.

### AP24 · Bewegungen erkennen: Dauerbelege und was keine Ausgabe ist — ✅ erledigt (7.8.2026)

**Als nächstes gebaut, weil die echten Daten es so sagen.** Ausgezählt über die
193 eingelesenen Bewegungen: **93 von 122 Ausgängen (76 %, 87 % des Volumens)
gehen an immer denselben Empfänger** – Miete, Hausgeld, Löhne, Wäscherei,
Strom, Wasser, Software, Darlehen. Für keinen davon wird je ein Beleg
fotografiert.

Zum Vergleich: im Bestand liegen **vier** Belege. AP19 (Vorsteuer je Beleg)
zuerst zu bauen hieße, mit dem kleinsten Teil anzufangen.

**Drei der größten Posten sind gar keine Betriebsausgaben:**

| Empfänger | | Summe | |
|---|---:|---:|---|
| Daniel Steinhauß | 8× | −5.335 € | **Privatentnahme** |
| Landeshauptstadt Dresden | 10× | −2.428 € | **abgeführte Beherbergungssteuer**, durchlaufend |
| TARGOBANK | 7× | −1.077 € | Darlehen – **Tilgung ist keine Ausgabe** |

Wer die Kontosummen als Ergebnis liest, rechnet sich um über 8.000 € arm.
Damit fällt der Kern von AP22 hier mit ab.

**Gebaut wird auf Vorhandenem:** `stammdaten.kreditor_zu()` erkennt heute schon
Lieferanten am Händlernamen eines Belegs – dieselbe Erkennung greift auf dem
**Empfänger einer Kontobewegung**. Und `buchhaltung.KLASSEN` unterscheidet
bereits `Ausgabe`, `Privat/prüfen`, `Durchlaufend`, `Neutral`, `Einnahme` –
genau die Trennung, die hier fehlt.

**Ohne dieses Paket ist AP25 unbrauchbar:** „Bewegung ohne Beleg" meldete sonst
93 Dauer-Fehlalarme, jeden Monat dieselben. Eine Liste, die immer rot ist,
liest niemand.

**Gebaut:** `konto.erkennen()` in drei Stufen – Dauerarten zuerst (sie
entscheiden über die Klasse, ein Kreditor-Treffer würde eine Privatentnahme
sonst zur Ausgabe machen), dann die Kreditoren, dann nichts. **Raten wäre
schlimmer als schweigen:** was unbekannt ist, bleibt leer und wartet auf einen
Menschen. Eingänge bekommen keine Kategorie – was ein Erlös ist, entscheiden
erst AP20 und AP23. Was von Hand gesetzt wurde, wird nie überschrieben.

**Zwei Zahlen statt einer:** `monatssummen()` liefert jetzt `geldfluss` **und**
`ergebnis`. Der Geldfluss ist, was auf dem Konto passiert ist; das Ergebnis
lässt Privatentnahmen, durchlaufende Posten und Neutrales weg. Dazu `unklar`,
die Zahl der noch nicht zugeordneten Ausgänge – solange sie größer als null
ist, sagt die Anzeige, dass das Ergebnis eine Näherung ist.

**An den echten Daten:** 154 von 193 Bewegungen erkannt, 39 Ausgänge offen.

| | Geldfluss | Ergebnis |
|---|---:|---:|
| Januar–Juni 2026 | −834,93 € | **6.235,60 €** |

> **Gegenprobe gegen das Workbook:** Es weist für dasselbe Halbjahr
> **6.048,85 €** aus – **3,1 % Unterschied**, bei 33 noch unzugeordneten
> Ausgängen, ungetrennter Darlehenstilgung und fehlender Abschreibung. Der
> Weg über die Kontobewegungen trägt also.

8 neue Tests (34 in `tests/test_kontoauszug.py`), gegengeprüft: ohne die
Dauerarten fallen fünf durch.

*Größe:* M *(vorher S – die Klassen kamen dazu).*

### AP20 · Zahlungsabgleich: Bewegung ↔ Beleg/Rechnung — offen *(das schwerste)*

Hier läuft alles zusammen. Jede Kontobewegung bekommt ihren Gegenpart: eine
Ausgangsrechnung wird **bezahlt** (und trägt ein Zahlungsdatum), ein Beleg wird
beglichen, ein Dauerbeleg erkannt. Erkennung über Betrag, Datum und
Verwendungszweck; was nicht eindeutig ist, bleibt ein **Klärfall** statt still
zu raten.

Drei Fälle, die nicht einfach „Bewegung = Beleg" sind:

* **Plattform-Auszahlung** – ein Betrag für viele Buchungen, netto nach
  Provision (siehe AP23).
* **Zahlungseingang eines Gastes** – darin steckt die Beherbergungssteuer, ein
  durchlaufender Posten, der kein Erlös ist.
* **Eingang ohne Rechnung** – muss trotzdem in die EÜR und darf kein stiller
  Rest bleiben.

**Der Weg muss in beide Richtungen gehen** (geschärft 7.8.2026). Bisher stand
hier nur „Bewegung bekommt ihren Gegenpart". Im Alltag ist der häufigere Weg
der umgekehrte: man sieht eine Abbuchung, zu der der Beleg fehlt, und lädt ihn
**von dort aus** hoch – nicht erst in den Belegen, um ihn danach zu suchen.
Genau das unterscheidet ein Werkzeug von einem Ordner voller Belege.

Also: aus einer Bewegung heraus einen Beleg hochladen oder einen vorhandenen
auswählen, und aus einem Beleg heraus die passende Bewegung.

**✅ Schritt 1 erledigt (7.8.2026):** Beleg an der Buchung – hochladen, lösen,
oder abhaken, dass es keinen gibt. Dazu die Belegpflicht (wann wird überhaupt
einer erwartet) und die Liste „fehlt noch".

> **Schritt 2 – die beiden Wege treffen sich noch nicht.** Nachgefragt am
> 8.8.2026: *„Im Menü gibt es Belege, dort laden Mitarbeiter hoch – werden die
> automatisch den Bankbewegungen zugeordnet?"* **Nein.** Heute laufen zwei
> getrennte Wege nebeneinander:
>
> | Weg | was passiert |
> |---|---|
> | **Belege** (Mitarbeiter, Handy) | Foto/PDF, OCR, Kategorie – **ohne Bezug zum Konto** |
> | **Konto → Beleg hochladen** | landet auch in den Belegen, aber **verknüpft** |
>
> Zwei Folgen, beide unschön:
>
> * Ein Beleg, den die Putzkraft fotografiert, bleibt für das Konto unsichtbar –
>   die Buchung steht weiter in „fehlt noch", obwohl der Beleg längst da ist.
> * **Derselbe Beleg kann zweimal im System landen** (einmal aus der App, einmal
>   an der Buchung). Die Dublettenprüfung von `buchhaltung.dubletten` greift
>   innerhalb der Belege, aber niemand vergleicht die beiden Wege.
>
> Nötig ist deshalb die **automatische Zuordnung**: Betrag, Datum und Händler
> stehen auf beiden Seiten. Ein Vorschlag statt einer stillen Verknüpfung – was
> nicht eindeutig ist, bleibt ein Klärfall. Dazu am Beleg der umgekehrte Weg:
> „passt zu dieser Buchung".

*Größe:* XL *(Schritt 1 davon erledigt).*

### AP25 · Vollständigkeit und Abstimmung — offen *(Pflicht, nicht Kür)*

Für den Überblick wäre eine Lücke ein Schönheitsfehler. **Für die Übergabe ist
sie der Mangel**, den das Steuerbüro Monate später zurückfragt – und dann weiß
niemand mehr, wofür die 84,90 € waren.

Saldo-Abgleich gegen den Kontoauszug, lückenlose Zeiträume beim Import (eine
fehlende Woche sieht sonst aus wie ein ruhiger Monat), und vor allem die Liste
**„Bewegung ohne Beleg"** – das Blatt „Fehlende Belege" des Workbooks, nur
laufend statt einmal im Jahr. Sie ist das Maß dafür, ob die Übergabe
vollständig ist.

> **Belegpflicht gehört an die Kategorie** (ergänzt 7.8.2026, beim Nachprüfen
> gefunden). **Nicht jede Bewegung braucht einen Beleg:** für eine
> Privatentnahme, eine Darlehenstilgung, einen Lohn oder die an die Stadt
> abgeführte Steuer gibt es keinen Lieferantenbeleg. Meldete die Liste alle
> 122 Ausgänge, wäre sie so unbrauchbar wie eine Liste, die immer rot ist –
> genau der Fehler, den AP24 auf der anderen Seite vermieden hat.
>
> Je Kategorie also ein Kennzeichen: **Beleg erwartet – ja/nein**. Erst dann
> misst „Bewegung ohne Beleg" etwas.

*Die GoBD-Verfahrensdokumentation ist am 7.8.2026 entfallen* – sie gehört zu
einer Buchhaltung, die dem Finanzamt vorgelegt wird. Die führt der
Steuerberater. *Größe:* M.

### AP26 · Übernahmestichtag aus dem Workbook — offen

Das Workbook ist auf den 30.6.2026 gebucht. Ohne festen Stichtag zählt das
erste Halbjahr doppelt, sobald das Werkzeug rechnet. Klein, aber es muss vor
der ersten echten EÜR stehen. *Größe:* S.

### AP21 · Umsatzsteuer als Liquiditätszahl — offen *(war: Voranmeldung)*

**Zurückgeschnitten am 7.8.2026.** Die Voranmeldung macht der Steuerberater.
Was bleibt, ist die Frage, die im Alltag zählt: **wie viel vom Kontostand
gehört schon dem Finanzamt?** Vereinnahmte Umsatzsteuer minus Vorsteuer, je
Monat, als eine Zahl neben dem Ergebnis – damit ein guter Kontostand nicht über
eine fällige Zahlung hinwegtäuscht. Kein Formular, keine Feldnummern.
*Größe:* S *(vorher L).*

### AP17 · Der Überblick: Einnahmen, Ausgaben, Ergebnis — offen *(nach AP20, AP26)*

**Das Ziel der ganzen Phase.** Aus den zugeordneten Kontobewegungen: Einnahmen,
Ausgaben und Ergebnis je Monat und je Wohnung, dazu die Entwicklung über das
Jahr und die Umsatzsteuer-Zahl aus AP21. Das, was heute das Workbook liefert –
nur ohne acht Monate Verzug und ohne Handarbeit.

Der CSV-Export in den acht Spalten des Kontenjournals bleibt, solange der
Steuerberater und das Workbook damit arbeiten. Er ist die **Übergabe**, nicht
mehr das Ergebnis. *Größe:* L.

### AP22 · Was das Ergebnis sonst verzerrt: Darlehen und Abschreibung — offen

**Zurückgeschnitten am 7.8.2026** – kein Anlagenverzeichnis, das rechnet der
Steuerberater. Es geht nur darum, dass der Überblick nicht lügt:

* **Tilgung ist keine Ausgabe**, Zins schon. Wer die ganze Rate abzieht, hält
  sein Ergebnis für schlechter, als es ist.
* **Abschreibung ist eine Ausgabe**, taucht aber auf keinem Kontoauszug auf.
  Ohne sie sieht das Ergebnis besser aus, als es ist.
* **Privatentnahmen** sind weder das eine noch das andere und müssen aus dem
  Ergebnis heraus.

Feste Monatswerte, von Hand gepflegt, wie heute im Workbook. *Größe:* S
*(vorher M).*

---

## Phase 8 — Bankbuchhaltung (Konzept vom 8.8.2026)

**Das Konzept steht in `docs/konzept-bankbuchhaltung.md`** – Zielbild,
Datenmodell, die Befunde aus den echten Daten und die Pakete B1–B9. Hier steht
nur der Stand.

Der Anlass: Das heutige Modell hat an der Bewegung **je ein Feld** (`beleg_id`,
`rechnung_id`) und kann damit keine Sammelauszahlung abbilden. Nachgeprüft
wurde außerdem, dass **beide Portale gesammelt auszahlen** – 51 von 65
Zahlungseingängen sind n:m, nicht die Ausnahme.

| | Paket | Größe | Stand |
|---|---|---|---|
| **B1** | Die Zuordnung als eigener Satz | M | ✅ erledigt (8.8.2026) |
| **B2** | Die Zuordnungsmaske mit Restbetrag | L | ✅ erledigt (8.8.2026) |
| **B3** | Ausgangsrechnungen zuordnen | L | ✅ erledigt (8.8.2026) |
| **B4** | Portalprovision gegenbuchen | M | ✅ erledigt (8.8.2026) |
| **B4b** | Verrechnungskonto je Plattform | M | ✅ erledigt (8.8.2026) – ohne „offene Forderung", siehe Konzept |
| **B5** | Eingangsbelege – beide Wege zusammenführen | L | ✅ erledigt (8.8.2026) |
| **B6** | Kategorien an der Zuordnung | S | ✅ erledigt (8.8.2026) |
| **B7** | Der Überblick | L | ✅ erledigt (8.8.2026) |
| **B8** | Vollständigkeit | M | ✅ erledigt (8.8.2026) |
| **B9** | Übergabe ans Steuerbüro | L | ✅ erledigt (8.8.2026) |
| **B10** | Altrechnungen übernehmen (vor dem Ausrollen) | M | ✅ erledigt (8.8.2026) – 78 übernommen, Kreis ab 2026-0079 |
| **B11** | Portal-Auszahlungen aus dem Bericht zuordnen | L | in Arbeit (B11a–d) |

### B11 · Die Auszahlungsberichte der Portale

**Der Anlass (8.8.2026).** 55 Zahlungseingänge über 33.923 € warten auf ihre
Rechnung, und aus den Bankdaten allein ist nicht zu erkennen, welche Rechnung
zu welcher Auszahlung gehört — die Reservierungsnummer steht nicht im
Verwendungszweck. Gefragt: *„woher soll ich denn jetzt wissen, welche Rechnung
zu welchem Auszahlungsbetrag gehört?"*

**Die Antwort liegt in den Berichten der Portale.** Beide wurden geprüft:

| | Booking (`Payout_from_…xlsx`) | Airbnb (`airbnb_.csv`) |
|---|---|---|
| Bank → Auszahlung | `NO.vQmQNcef5aDAINyZ` im Verwendungszweck — **exakt** | kein Bezug; über **Betrag + Datum** |
| an den echten Daten | 46 von 48 (2 nach dem Berichtsende) | **7 von 7 eindeutig** |
| Auszahlung → Buchung | `Reference number` 6180071938 | `Bestätigungs-Code` HM5F9P3HAT |
| Buchung → Smoobu | **75 von 75** über `reference-id` | dasselbe Format |
| Provision | `Commission` je Reservierung | `Servicegebühr` je Buchung |
| zusätzlich | — | Bruttoeinkünfte, Reinigungsgebühr, **von Airbnb abgeführte Steuer** |

Damit ist die Zuordnung kein Schätzen mehr, und die Provision kommt aus der
Quelle des Portals statt aus Smoobu (dessen Zahl der Betrieb am 8.8.2026
ausdrücklich als unzuverlässig bezeichnet hat).

* **B11a · Fingerabdruck härten.** Vorher gefragt: *„wie verhindern wir
  generell, dass Überschneidungen hochgeladen werden?"* Für Bankauszüge ist es
  gelöst (Konto + Datum + Betrag + Zweck + Empfänger; 238 Bewegungen aus drei
  überlappenden Dateien ergaben 238 verschiedene Abdrücke). **Die Restlücke:**
  zwei in *jedem* Feld gleiche Zeilen verschmelzen zu einer. Am Bestand gibt es
  genau einen Beinahe-Fall — 2 × −14,57 € am 31.07. an denselben Empfänger, nur
  der Zweck trennt sie. Deshalb kommt die laufende Nummer innerhalb des Tages
  dazu; weil die DKB ganze Tage exportiert, bleibt sie über Überlappungen
  stabil. **Rückwärtsverträglich:** die Nummer wird erst ab dem *zweiten*
  Vorkommen angehängt — sonst bekäme jede der 238 bereits eingelesenen
  Bewegungen einen neuen Schlüssel, und der nächste Import legte alles ein
  zweites Mal an (gegengeprobt: 0 von 238 Schlüsseln blieben gleich).
  ✅ erledigt (8.8.2026)
* **B11b · Booking-Bericht einlesen.** XLSX (`openpyxl` als neue Abhängigkeit —
  auf dem Server noch nicht vorhanden). Schlüssel ist die Auszahlungsnummer:
  ein zweiter Import derselben Auszahlung ändert nichts, egal welcher Zeitraum
  gewählt wurde.
* **B11c · Airbnb-Bericht einlesen.** CSV, Zeilenart `Payout` mit den
  folgenden `Buchung`-Zeilen. Verknüpfung über Betrag + Datum (±7 Tage).
  **Mehrdeutiges wird gezeigt, nicht geraten** — zahlt Airbnb zweimal denselben
  Betrag in einer Woche, entscheidet der Mensch.
* **B11d · Zuordnen.** Je Auszahlung die Rechnungen mit ihrem **Bruttobetrag**
  und die Provision aus der Quelle des Portals. Vorschau vor dem Schreiben.

Beide Dateien gehen in denselben Upload wie die Kontoauszüge; das Werkzeug
erkennt am Inhalt, was es ist.

**Danach offen (Teil 2, noch nicht begonnen):** ein Bereich „Unterlagen" als
einzige Anlaufstelle für alle Dateien, und eine Checkliste, die den Stand der
Kette zeigt (Auszüge lückenlos? Portal-Berichte da? Zuordnung offen? Belege?),
damit keine Reihenfolge im Kopf zu behalten ist.

### B10 · Die Rechnungen aus dem alten Weg übernehmen

**Der Anlass (8.8.2026):** bis einschließlich der Buchung **Alexander Josan**
sind die Rechnungen über Smoobu erzeugt und verschickt; ab der nächsten soll
das Werkzeug übernehmen. Ohne Übernahme fehlten dem Werkzeug 78 Rechnungen —
und damit die halbe Einnahmenseite, an der die Zahlungseingänge hängen (B3).

**Am Bestand nachgesehen:**

| | |
|---|---|
| PDFs in `Ausgangsrechnungen/` | **78**, lückenlos Nr. 1–78 |
| davon im Rechnungsausgangsbuch | nur 1–59 |
| Alexander Josan | **Nr. 78** – die letzte |
| Text der PDFs maschinenlesbar | **ja**, vollständig |

Die PDFs sind deshalb die Quelle, nicht das Workbook: sie decken alle 78 ab und
tragen Nummer, Datum, Gast, Objekt, Aufenthalt, Netto, USt, Brutto und
Übernachtungssteuer.

* **B10a · Einlesen.** Ein Werkzeug liest die 78 PDFs, legt je Rechnung einen
  Satz an (Status *gesendet*, Merkmal `quelle="smoobu"`) und **kopiert die
  Original-PDF** mit. Probelauf zuerst, Schreiben nur auf ausdrückliche Ansage.
* **B10b · Das Original bleibt das Original.** Für eine übernommene Rechnung
  wird **kein PDF neu gebaut** – der Gast hat ein bestimmtes Dokument bekommen,
  und ein zweites mit anderem Layout unter derselben Nummer wäre ein zweiter
  Beleg zum selben Vorgang. Angezeigt und weitergegeben wird die Datei von
  damals.
* **B10c · Der Nummernkreis.** Die übernommenen behalten ihre Nummer (1–78, so
  wie sie beim Gast liegt). Das Werkzeug beginnt bei **79**; dafür gibt es
  `rechnung_startjahr` / `rechnung_startnummer` bereits.

**Nicht verändert wird, was schon existiert:** keine Neuberechnung der
Beherbergungssteuer, keine Korrektur der Beträge, kein Festschreiben-Lauf. Was
hinausgegangen ist, ist hinausgegangen.

**Probelauf am echten Bestand (8.8.2026):** 78 Rechnungen gelesen, Nr. 1–78,
zusammen **36.847,29 € brutto**, keine unvollständig. Gegen die 59 Zeilen des
Rechnungsausgangsbuchs geprüft — die 30 „Abweichungen" waren keine Lesefehler,
sondern **zwei Begriffe von „Brutto"**: das Workbook führt ihn *ohne*
Übernachtungssteuer, die PDF *mit* (Nr. 36 Peter Queißer: 806,19 gegen 765,93,
Differenz genau die 40,26 € Steuer). Unter dieser Annahme stimmen 58 von 59;
die Reste sind Cent-Differenzen zwischen Dokument und Workbook — dort gilt das
Dokument, das hat der Gast.

Das Werkzeug ist `tools/altrechnungen_uebernehmen.py`, Probelauf ist die
Vorgabe.

**Durchgeführt am 8.8.2026** (Probe-Instanz, auf Ansage): die 48 Testrechnungen
gelöscht, 78 übernommen, `rechnung_startnummer` auf 79. Vorher zeigte der
Abgleich, dass **44 der 48** dieselben Vorgänge waren wie die alten — bei **40
davon auf den Cent derselbe Bruttobetrag**. Das ist zugleich der beste
verfügbare Nachweis, dass die Beherbergungssteuer-Rechnung dieses Werkzeugs
dasselbe ergibt wie das alte System.

**Geklärt: Smoobus Preis trägt.** Ein erster Vergleich meldete zwei Fälle, in
denen `price` nicht dem Rechnungsbetrag entspricht. Beide waren keine Fehler
des Werkzeugs:

* **Anja Ernst** – mein Vergleich hatte **Stornos nicht ausgefiltert**. Sie hat
  drei Sätze (532,74 storniert, 442,00 storniert, 400,07 gültig); die 400,07
  sind Rechnung und Zahlung. Das Werkzeug filtert korrekt
  (`bookings.is_real`) – bei **49 Stornos unter 155 Buchungen** ist dieser
  Filter wesentlich.
* **Katarina Gockel** – die Rechnung wurde **von Hand erstellt** (Ansage vom
  8.8.2026); es zählt, was auf der Rechnung steht.

Sauber gerechnet – nur gültige Buchungen, nur Rechnungen mit
Beherbergungssteuer: **46 von 47** stimmen mit Smoobus Preis überein, der
47. ist die handgemachte.

**Ohne Verbindung zur Buchung bietet das Werkzeug Dubletten an.**
`faellige_buchungen` überspringt eine Buchung nur, wenn `zu_buchung` eine
Rechnung dazu findet – und die sucht über das Feld `buchung`, das eine aus
einer PDF gelesene Rechnung nicht hat. An den echten Daten hätte das Werkzeug
nach der Übernahme **122 Entwürfe** vorgeschlagen, darunter 78 zu gerade
eingelesenen Rechnungen. `buchungen_verknuepfen` verbindet über Gastname und
Anreisetag: **78 von 78 verbunden, keiner offen**, Entwürfe 122 → 44. Von
diesen 44 liegen 39 vor Rechnung Nr. 1 (Oktober–Dezember 2025), 4 nach Josan
(die gehören dem neuen Weg) und **einer dazwischen** – Silvia Erdmann,
29.12.2025–01.01.2026, dort fehlt eine Rechnung.

**Rechnungen erst ab einem Stichtag** (`config.rechnung_ab`, Abreisetag
einschließlich). Ansage vom 8.8.2026: *2025 brauchen wir nicht, es geht nur ab
2026.* Ohne die Grenze schlug das Werkzeug 39 Entwürfe für Aufenthalte aus
Oktober bis Dezember 2025 vor. Mit `2026-01-01` bleiben **fünf**: Silvia
Erdmann (Abreise 01.01.2026) und die vier nach Josan.

> **Ein Irrtum von mir, hier festgehalten, damit er nicht wiederkehrt.** Ich
> hatte gemeldet, 12 Airbnb-Buchungen seien storniert – die Preisdetails tragen
> „Cancellation Host Fee / Cancellation Payout". Nachgeprüft: **alle 12**
> Airbnb-Buchungen tragen das, ausnahmslos. Es ist die Bezeichnung der
> Gebührenaufteilung, keine Stornierung. Monica Huangs Auszahlung von 4.977,29 €
> kam in drei Monatsraten an (1.794,13 + 1.620,51 + 1.562,65) – sie war da. Die
> Rechnungen Nr. 4, 6 und 13 sind richtig. Beinahe hätte ich dem Werkzeug
> beigebracht, jede Airbnb-Buchung zu übergehen.

> **Was dabei auffiel:** `rechnung.aendern` kann die **Positionen** eines
> Entwurfs ändern, die Oberfläche bietet es aber nicht an – dort lässt sich nur
> die Anschrift pflegen. Wer einen Betrag von Hand korrigieren will (wie bei
> Gockel geschehen), kann das im Werkzeug **nicht**. Offener Punkt.

Sie lösen AP20, AP23, AP25 und AP18 ab.

---

## Der zweite Zweck: die Übergabe ans Steuerbüro (festgelegt 7.8.2026)

Das Werkzeug hat **zwei** Aufgaben, nicht eine:

1. **Der laufende Überblick** – für den Betrieb, gegen den Verzug (oben).
2. **Das Sammeln und Übergeben** – am Ende bekommt der Steuerberater alle
   Belege. Gesammelt wird im Werkzeug, abgelegt in der Nextcloud.

Damit ändert sich der Rang von AP18: **es ist kein Anhängsel, sondern der
zweite Ausgang.** Und es stellt eine Anforderung an alles davor, die der
Überblick allein nicht stellt: **Vollständigkeit als Pflicht.** Für eine
Übersicht ist ein fehlender Beleg ein Schönheitsfehler – für die Übergabe ist
er die Rückfrage, die Monate später niemand mehr aufklären kann.

**Vier Belegströme, zwei davon gibt es noch nicht:**

| Strom | Stand |
|---|---|
| Eingangsbelege (Foto/PDF) | ✅ vorhanden, wird gespiegelt |
| Ausgangsrechnungen (PDF) | ✅ vorhanden, revisionssicher abgelegt |
| **Kontoauszüge** | ❌ – kommt mit AP16 |
| **Portalabrechnungen** (Airbnb earnings, Booking) | ❌ – kommt mit AP23 |

### AP18 · Ablage in der Nextcloud: Sammeln und Übergeben — offen *(neu gefasst)*

Heute spiegelt das Werkzeug Datei für Datei in einen Ordner (`archiv_spiegel`,
wahlweise WebDAV) – ohne Ordnung, ohne Vollzähligkeit, ohne Bezug zur Buchung.
Nötig ist eine Ablage, in der das Steuerbüro **allein zurechtkommt**:

* **Ordnung nach Jahr und Monat**, je Strom ein Ordner.
* **Sprechende Dateinamen** mit Datum, Lieferant und Betrag – nicht `a3f9c1.jpg`.
* **Die Kategorie als Beigabe**, nicht als Kontonummer: das Steuerbüro bekommt
  die Belege und die Information, wofür es war – die Kontierung macht es selbst
  (siehe AP27).
* **Eine Belegnummer**, die auf dem Dokument *und* im Buchungssatz steht.
  Ohne sie kann niemand vom einen zum anderen finden.
* **Ein Monat wird abgeschlossen und dann nicht mehr angefasst** – der
  Monatsabschluss gibt es schon, er muss nur die Ablage mitnehmen.

*Größe:* L *(vorher unbeziffert).*

### AP28 · E-Rechnung: empfangen (gilt schon) und senden (ab 2028) — offen

Zwei Hälften mit sehr verschiedener Dringlichkeit. **Die eine ist keine
Vorbereitung, sondern Rückstand.**

#### a) Empfangen — Pflicht seit 1.1.2025

Jedes inländische Unternehmen muss strukturierte Rechnungen **entgegennehmen
können**. Das Werkzeug kann es nicht: Belege laufen als Foto oder PDF durch die
OCR. Eine reine **XRechnung** (XML) lässt sich gar nicht erst sinnvoll
hochladen, und eine **ZUGFeRD**-Rechnung (PDF mit eingebettetem XML) wird wie
ein Bild behandelt – die exakten Daten stecken darin und werden weggeworfen,
während die OCR daneben rät.

> **Das ist kein Aufwand, das ist eine Abkürzung.** Aus dem XML kommen
> Lieferant, Rechnungsnummer, Datum, Netto, Steuersatz und Steuerbetrag
> **exakt** – genau die Felder, für die AP19 gebaut wird. Für jede so
> gelieferte Rechnung entfällt das Raten vollständig.

Nötig: XML aus dem PDF ziehen bzw. eine `.xml` direkt annehmen, die Felder
übernehmen statt zu erkennen, und das **XML unverändert aufbewahren** – ein
PDF-Ausdruck davon genügt der Aufbewahrung nicht (betrifft AP18).

> **Offene Frage: reicht Hochladen noch?**
>
> „Belege aus dem Postfach holen" steht unter *Bewusst nicht auf dem Fahrplan* –
> verworfen am 7.8.2026 mit der Begründung, Hochladen genüge. **Für
> E-Rechnungen trifft diese Begründung nicht mehr zu:** sie kommen praktisch
> immer per Mail, und was am Handy davon fotografiert oder als Bild
> weitergereicht wird, ist keine E-Rechnung mehr – das XML fehlt, und damit
> genau der Teil, der aufbewahrt werden muss und der die Felder liefert.
>
> Drei Wege, noch nicht entschieden:
>
> 1. **Postfachabruf** wie in `rechnung-automation` (Microsoft Graph). Löst es
>    vollständig, bringt aber Postfachzugang, Filterregeln je Absender und
>    Dublettenschutz mit – genau das, was 7.8. zu teuer erschien.
> 2. **Datei-Upload aus der Mail heraus**: der Anhang wird von Hand
>    weitergereicht, aber als Datei (`.pdf`/`.xml`), nicht als Foto. Kostet
>    nichts und deckt den Normalfall – setzt aber Disziplin voraus.
> 3. **Eigene Sammeladresse**, an die Lieferantenrechnungen weitergeleitet
>    werden und die das Werkzeug leert. Zwischen 1 und 2.
>
> Zu klären, bevor AP28a gebaut wird – die Antwort ändert seinen Zuschnitt.

#### b) Senden — für diesen Betrieb ab 1.1.2028

Die Übergangsfristen: bis Ende 2026 dürfen Papier und PDF weiter verwendet
werden, ab 1.1.2027 müssen Unternehmen über 800.000 € Vorjahresumsatz senden,
ab **1.1.2028 alle** – im inländischen **B2B**. Nach den vorliegenden Zahlen
liegt der Betrieb weit unter der Schwelle, es gilt also 2028.

Zwei Einschränkungen, die den Umfang klein halten:

* **Gäste als Privatpersonen sind nicht betroffen.** Die Pflicht gilt B2B. Für
  die große Mehrheit der Rechnungen ändert sich nichts.
* **Betroffen sind Geschäftskunden** – und die gibt es (die abgestimmte Vorlage
  heißt nicht ohne Grund „B2B"). Für sie braucht es ab 2028 ein strukturiertes
  Format.

**Vorschlag ZUGFeRD statt reiner XRechnung.** ZUGFeRD ist ein PDF mit
eingebettetem XML: die Rechnung bleibt lesbar – das eben erst gesetzte Layout
bleibt erhalten – und ist zugleich maschinenlesbar. Eine reine XRechnung wäre
nur XML und für den Gast unbrauchbar. *(Nur wer an Behörden fakturiert, braucht
XRechnung; für Ferienwohnungen der Ausnahmefall.)*

**Technischer Stolperstein:** ZUGFeRD verlangt **PDF/A-3**. Das erzeugt PyMuPDF
nicht von selbst – das ist der eigentliche Aufwand dieses Pakets, nicht das XML.

**Fristen und Schwellen vom Steuerberater bestätigen lassen**, bevor gebaut
wird. *Größe:* a) M · b) L.

### AP27 · Eigene Konten und die Frage „wofür ging das Geld?" — offen

**Entschieden am 7.8.2026: kein Kontenrahmen.** Kein SKR03, kein SKR04, keine
DATEV-Nummern. Die Vorkontierung macht der Betreiber selbst; das Werkzeug muss
sie nicht erraten. Damit ist die Frage, womit das Steuerbüro arbeitet, für
dieses Paket **erledigt** – sie war der einzige Grund, warum es blockiert war.

Was stattdessen gebraucht wird, ist die Frage aus dem Alltag: **Wie viel habe
ich für Putzmittel ausgegeben? Wie viel für Gastgeschenke?** Also eigene
Kategorien, selbst angelegt, und eine Auswertung darüber.

Nachgesehen im Code – zwei Hälften, beide fehlen zur Hälfte:

| | Stand |
|---|---|
| **Eigene Kategorien anlegen** | `buchhaltung.kategorien()` **liest** schon `cfg["beleg_kategorien"]` – es gibt aber **keine Oberfläche**, um welche anzulegen. Der Anschluss fehlt, nicht die Mechanik. |
| **Auswertung je Kategorie** | Gibt es **gar nicht**. „kategorie" kommt in `kennzahlen.py` und der Auswertung nicht vor. |

Also:

1. **Kategorien pflegen** in den Einstellungen – anlegen, umbenennen, löschen.
   Umbenennen muss die vorhandenen Belege und Bewegungen mitnehmen, sonst
   verwaist die Auswertung.
2. **Auswertung je Kategorie**: was ist wofür ausgegeben worden, je Monat, je
   Jahr, je Wohnung. Fließt in AP17 (Überblick) ein, statt eine eigene Seite zu
   bekommen.

Die Vorgabe-Kategorien bleiben wörtlich die des Workbooks (der SUMIF vergleicht
wortgenau) – eigene kommen daneben.

*Größe:* M *(vorher M–L und blockiert).*
