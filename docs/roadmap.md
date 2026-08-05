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

### AP2 · Sichere Speicherschicht — offen

Ein Modul für allen Dateizugriff: atomares Schreiben (`os.replace`) und
Dateisperre. Heute macht jedes Modul „ganze Datei lesen → ändern → ganze Datei
überschreiben" (`timetrack.py`, `bookings.py`, `receipts.py`, `housekeeping.py`,
`data.py`). Zwei gleichzeitige Zugriffe = eine Änderung verschwindet
stillschweigend; ein Absturz mitten im Schreiben = kaputte Datei. Bei
`config.json` hieße das: App startet nicht mehr, samt aller Konten.
`tools/useradmin.py:63` macht es bereits richtig – der Rest zieht nach.

*Abhängigkeit:* keine. *Größe:* M.

### AP3 · Staging & Deploy — offen

Zweite Instanz zum Ausprobieren, ein Deploy-Skript (Tests vorher, Smoke-Check
nachher, Rollback-Weg) statt `git pull` + `systemctl restart` von Hand. Dazu
Monitoring: Dienst tot oder Smoobu-Fehler → Meldung. Heute merkt es niemand.

*Abhängigkeit:* keine. *Größe:* M.

---

## Phase 1 — Struktur

### AP4 · `web.py` aufteilen — offen

4.939 Zeilen in einer Datei (63 % des Codes). Schnitt entlang der bestehenden
`build_*`-Funktionen in Bereichs-Module: Buchungen, Reinigung, Zeiten, Belege,
Steuer, Benutzer, Einstellungen, geteilte Bausteine. Verhaltensgleich, die
Testsuite ist das Netz. Ziel: Dateien von 300–700 Zeilen.

*Abhängigkeit:* AP2 sollte vorher stehen (sonst wird der Datenzugriff zweimal
angefasst). *Größe:* M–L.

### AP5 · SQLite statt JSON — offen

Hinter AP2 versteckt und deshalb ohne Bruch: Zeiten, Zuweisungen, Belege und
Reinigungsdaten in eine Datenbank. `config.json` bleibt JSON. Ab ~5 Wohnungen
wirklich nötig, danach nicht mehr schmerzfrei nachrüstbar.

*Abhängigkeit:* AP2. *Größe:* M.

---

## Phase 2 — Alltag des Teams

### AP6 · Echte Handy-App (PWA) — offen

Installierbar auf dem Home-Screen, eigenes Icon, Startbildschirm, sinnvolles
Verhalten ohne Netz. Heute gibt es kein Manifest – die App ist nur eine
Browser-Seite unter einer URL, obwohl die Putzkräfte ausschließlich am Handy
arbeiten. Dazu Feinschliff der Listen auf kleinen Schirmen.

*Größe:* S–M.

### AP7 · Benachrichtigungen, die ankommen — offen

Web-Push statt nur E-Mail: neue Zuweisung, Erinnerung am Vorabend, „bitte Zeit
nachtragen", Schaden gemeldet. Je Nutzer einstellbar, welcher Kanal.

*Größe:* M.

### AP8 · Zuweisung mit Kopf — offen

Standard-Zuständigkeit je Wohnung, Abwesenheiten/Urlaub, Vorschlag beim Öffnen,
Wochenplanung statt Buchung-für-Buchung, „alle offenen zuweisen". Heute ist
jede Zuweisung Handarbeit.

*Größe:* M.

---

## Phase 3 — Betreiber-Auswertung

### AP9 · Kennzahlen-Dashboard — offen

Führt zusammen, was heute nebeneinanderliegt: Auslastung, Umsatz je
Wohnung/Monat, Reinigungsminuten und -kosten je Buchung, Materialkosten aus den
Belegen, Deckungsbeitrag je Wohnung. Die Verknüpfung Zeit ↔ Buchung existiert
bereits (`booking_id` am Zeiteintrag).

*Abhängigkeit:* profitiert stark von AP5. *Größe:* M–L.

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
