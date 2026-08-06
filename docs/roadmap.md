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

### AP-D2 · Bildschirme am Handy nachziehen — offen

Die Bereichs-Kopfzeilen (`_feature_header`) sind für den Monitor gebaut: großes
Symbol, Titel, Unterzeile – am Handy ein Sechstel der Höhe. Dazu Tap-Ziele in
Listen, Abstände, und die Zustände „lädt", „leer", „ging schief" überall gleich.

*Größe:* M.

### AP-D3 · Farb- und Abstandsrollen festschreiben — offen

Farben stehen heute als Tailwind-Klassen verstreut im Code (`text-amber-800`,
`bg-violet-50`). Als benannte Rollen – Hinweis, Warnung, Erfolg, ruhig – an einer
Stelle, damit der nächste Bereich von allein passt. Optional, lohnt erst nach D1.

*Größe:* S–M.

---

## Phase 4 — Buchhaltung & Steuer

### AP10 · Belege bis zur EÜR — offen

Kategorien passend zum EÜR-Workbook, Monatsabschluss, Export, Pflichtfeld- und
Dublettenprüfung. Ziel: Belege landen nicht im Archiv, sondern in der
Buchhaltung.

*Größe:* M.

### AP11 · Steuer-Workflow zu Ende — offen

Status je Monat (offen → erzeugt → gesendet → bezahlt), Fristenerinnerung,
Vollständigkeitsprüfung vor dem Erzeugen.

**Offene Sachfrage ohne Code:** Die Wernerstraße rechnet mit **7 % statt 6 %**
Beherbergungssteuer. Die Gäste zahlen dort zu viel (Rechnung 71: 47,56 € statt
40,76 €), abgeführt werden korrekt 6 %. Gehört in Smoobu/Booking.com korrigiert.

*Größe:* M.

---

## Phase 5 — Rollen & Härtung

### AP12 · Feine Rechte & Login-Härtung — offen

Was darf ein Manager konkret (zuweisen, fremde Zeiten korrigieren, Belege
sehen)? Statt „ganze Bereiche an/aus" (`ROLE_AREAS`). Dazu: Rate-Limit am Login
(das Passwort-Zurücksetzen hat eins, der Login nicht), 2FA für Admins, Dienst
nicht mehr als `root`, Protokoll wer was geändert hat.

*Größe:* M.

---

## Bewusst nicht auf dem Fahrplan

* **Mandantenfähigkeit** (das Tool für fremde Vermieter) – ändert die
  Architektur grundlegend und ist ohne Phase 0–1 nicht sinnvoll.
* **Checklisten wieder einschalten** – bewusst aus (`checklisten_aktiv`), bis
  der Alltag ohne sie rundläuft.
* **Automatisierte Gästekommunikation** – Nachrichten lesen/senden gibt es
  bereits; Vorlagen und Automatik sind ein eigenes Thema.
