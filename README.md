# Beherbergungssteuer Dresden

Lokale Webapp, die aus den Smoobu-Buchungen die monatliche
Beherbergungssteuer-Anmeldung für Dresden berechnet und das **amtliche Formular
(Vdr 22.040/5) pixelgenau als PDF** erzeugt.

**Frontend:** NiceGUI (reines Python, keine Node-Toolchain). **Backend:**
Standardbibliothek (Smoobu/Steuer) + PyMuPDF (PDF). Alles via
`pip install -r requirements.txt`.

## Start

```bash
cd apps/beherbergungssteuer
pip install -r requirements.txt
cp config.example.json config.json   # einmalig: API-Key + Betreiberdaten
./run-local.sh                       # = python3 app/web.py
```

Dann <http://localhost:3001/> öffnen, Jahr/Monat + Apartments wählen,
**Berechnen** → KPIs, Buchungsliste und **„📄 Amtliches Formular (PDF)
herunterladen"**. Einstellungen oben rechts (⚙️).

## Architektur

| Datei | Aufgabe |
|---|---|
| `app/web.py` | NiceGUI-Oberfläche (Seite, Einstellungs-Dialog, Webhook), Entry-Point |
| `app/data.py` | Config, Smoobu-Cache, Berechnungs-Glue |
| `app/steuer.py` | Steuerberechnung (Golden-Tests) |
| `app/smoobu.py` | Smoobu-API-Client |
| `app/pdf_form.py` | Amtliches PDF aus Blanko-Vorlage |
| `app/archive.py` | Revisionssichere Ablage (Hash-Kette, Versionen, Spiegel) |
| `app/mailer.py` | E-Mail-Versand über Gmail (Vorlagen) |
| `app/auth.py` | Login (PBKDF2) + optionale 2FA (TOTP) |
| `app/feiertage.py` | Gesetzliche Feiertage Sachsen + Tagesart (Werktag / Wochenende+Feiertag) |
| `app/i18n.py` | Mehrsprachigkeit DE/EN der Mitarbeiterbereiche (`t()`) |
| `tools/make_blank.py` | Blanko-Vorlage + Unterschrift aus eingereichter PDF |

## Amtliches PDF-Formular

Dresden bietet das Formular nur über ein Online-System (intelliform) an, kein
Blanko-Download. Daher wurde aus einer eingereichten PDF einmalig eine
Blanko-Vorlage erzeugt: `templates/anmeldung_blank.pdf` – ALLE variablen/
personenbezogenen Werte (Zahlen, Datum, Jahr, Monatskreuz, Dokument-ID,
Betreiberdaten, Kassenzeichen, **Unterschrift**) per Redaction entfernt, nur das
Formular-Layout bleibt (Generator: `tools/make_blank.py`). Die Unterschrift wird
dabei nach `assets/signature.png` extrahiert.

`app/pdf_form.py` setzt je Anmeldung ein: Betreiberdaten + Kassenzeichen aus
`config.json`, die berechneten Werte, das Monatskreuz und die Unterschrift
(`assets/signature.png`, Position über `unterschrift_x` einstellbar).

## Revisionssichere Ablage & erneute Erstellung

Über **„📥 Erzeugen & revisionssicher ablegen"** wird das PDF unveränderbar im
Archiv festgeschrieben (Modul `app/archive.py`):

* Datei → `archive/<jahr>/Beherbergungssteuer_<periode>_v<rev>.pdf`,
  auf **schreibgeschützt (0444)** gesetzt, wird **nie überschrieben**.
* **Erneute Erstellung** eines Monats legt eine **neue Revision** an (v2, v3 …) –
  die alte bleibt erhalten (= „berichtigte Anmeldung"). Über **„👁 Nur Vorschau"**
  lässt sich ein PDF unverbindlich ansehen, ohne es abzulegen.
* Jede Ablage wird in einer **append-only Hash-Kette** (`archive/ledger.jsonl`)
  protokolliert (SHA-256 der PDF + `prev_hash`-Verkettung). Das **Archiv** (📚 oben)
  listet alle Ablagen und prüft die Integrität – jede nachträgliche Änderung an
  Datei oder Eintrag wird erkannt.

**Ablage-Ordner (Computer):** In den Einstellungen (Tab „Archiv") einen Ordner
auf dem Computer wählen (Browser „Durchsuchen"); jede Festschreibung wird dorthin
kopiert – z. B. ein Nextcloud-Sync-Ordner oder ein Buchhaltungs-Ordner. Über das
Archiv (📚) sichert **„🔁 Alles … spiegeln"** den Bestand nachträglich. Schlägt
das Kopieren fehl, bleibt die interne Ablage (`archive/`) trotzdem gültig.

Hinweis: Der Ordner liegt dort, wo die App läuft. Lokal = dein Mac; auf dem
Server = der Server (dann ggf. den Ordner via Mount mit der Cloud verbinden).
Die WebDAV-Funktion im Code (`archive.mirror_entry` via `archiv_webdav`) bleibt
verfügbar, ist in der UI aber nicht mehr eingebunden.

> Pragmatische Revisionssicherheit (Integrität, Unveränderbarkeit, Nachweis +
> externe Kopie). `archive/` ist gitignored.

## Datenaktualität

Smoobu-Daten werden beim **Berechnen** geladen und **5 Minuten** pro Monats-
zeitraum zwischengespeichert. Der **🔄-Button** leert den Cache und lädt frisch;
unter den Eingaben steht „Daten zuletzt von Smoobu geladen: …". Der Webhook
(`/api/smoobu/webhook`) leert den Cache automatisch bei Änderungen in Smoobu.

## Login, Benutzer & Rollen

Die App ist durch einen **Login** geschützt (`app/auth.py`, PBKDF2-Hashes in
`config.auth.users`). Beim allerersten Aufruf legst du unter `/login` den
**ersten Administrator** an (Benutzername + Passwort). Ausgenommen vom
Login-Zwang: Login-Seite, Smoobu-Webhook (`/api/…`), NiceGUI-Interna.

**Mehrbenutzer & Rollen:** Über **„Benutzer"** (nur Admin) lassen sich weitere
Konten anlegen, Passwörter zurücksetzen, Rollen ändern oder löschen. Rollen:
`admin` (sieht alles, verwaltet Nutzer/Einstellungen) und `putzkraft`. **Welche
Bereiche eine Rolle sieht, steuert `ROLE_AREAS` in `app/web.py`** (aktuell:
Admin = alles, Putzkraft = noch nichts – wird später definiert). Nutzer ohne
freigeschaltete Bereiche sehen eine Willkommens-/Hinweisseite.

**Mein Konto** (jeder Nutzer): eigenes Passwort ändern und **2FA (Google
Authenticator / TOTP)** aktivieren/deaktivieren → ab dann Login mit Passwort **+**
6-stelligem Code.

## Belegscanner

**Belege → „Beleg scannen"** in zwei Schritten:

1. **Foto aufnehmen** – Kamera öffnet, der Beleg wird mitsamt Rändern
   fotografiert (alternativ ein vorhandenes Foto wählen).
2. **Ecken ziehen** – vier Punkte liegen auf dem eingefrorenen Bild und werden
   per Finger/Maus auf die Belegkanten gezogen. Eine Lupe zeigt den Bereich
   unter dem Finger, der Rest wird abgedunkelt. „Zuschneiden & speichern"
   entzerrt perspektivisch und legt eine **A4-PDF** ab, danach OCR.

Bewusst **ohne automatische Kantenerkennung**: der frühere Versuch mit
OpenCV.js + jscanify traf Belege zu unzuverlässig (Kassenbons auf hellem
Untergrund liefern kaum Kanten) und lud 10 MB WebAssembly. Der Scanner braucht
jetzt **keine Fremdbibliothek** – reines Canvas.

Entzerrt wird **serverseitig** (`receipts.crop_quad`, OpenCV + numpy). Fehlen
die, wird auf einen achsenparallelen Zuschnitt auf das umgebende Rechteck
zurückgefallen (PyMuPDF) – schräg fotografiert bleibt es dann schief, aber der
Rand ist weg.

Wichtig: Das `ui.html` des Scanners muss **`sanitize=False`** setzen, sonst
entfernt NiceGUI `<video>`/`<canvas>` und die Vorschau bleibt schwarz. Kamera
gibt es nur über **HTTPS**.

Der Weg über **„Foto / Datei"** neben dem Scanner bleibt bestehen; dort schneidet
der Server automatisch zu (`receipts.autocrop`).

## Standorterfassung (abschaltbar)

**Einstellungen → Standorte → „Standort bei der Zeiterfassung erfassen"**.
Standard ist **aus**: beim Ein- und Auschecken wird dann weder GPS noch IP
abgefragt oder gespeichert, und die Mitarbeiter werden nicht nach einer
Ortungsfreigabe gefragt. Die Geofence-Liste darunter wirkt nur bei
eingeschaltetem Schalter. Bereits erfasste Standorte älterer Einträge bleiben in
`worklog.json` erhalten.

## Sprache (Deutsch / Englisch)

Die **Mitarbeiterbereiche** – Login, Mein Konto, Buchungen, Reinigungs-
Checklisten, Belege, Zeiterfassung – gibt es auf Deutsch und Englisch. Der
**Verwaltungsteil** (Beherbergungssteuer, Auswertung, Einstellungen,
Benutzerverwaltung) ist bewusst nur deutsch: Steuerbegriffe haben keine
belastbare englische Entsprechung, und diese Bereiche bedient nur der Betreiber.
Ebenfalls deutsch bleiben das **amtliche PDF** und die **Mail an den
Steuerberater** – beides geht an deutsche Empfänger.

Umschalten: **Mein Konto → Sprache** (gilt sofort und wird im Profil
gespeichert) oder als Admin je Mitarbeiter in der **Benutzerverwaltung**. Auf
der Login-Seite lässt sich die Sprache ebenfalls wählen; nach dem Anmelden
gewinnt die im Profil hinterlegte.

Technik: `app/i18n.py` mit `t("deutscher Text")`. **Der deutsche Text ist
zugleich der Schlüssel** – fehlt eine Übersetzung, erscheint unverändert das
Deutsche, eine Lücke kann die Oberfläche also nie leeren. Neue Sprache =
weiteres Wörterbuch in `TRANSLATIONS`.

Nicht übersetzt werden **Inhalte aus den Datendateien** (Checklisten-Punkte,
Wohnungsnamen, Notizen, Inventar) – sie erscheinen so, wie sie angelegt wurden.

> Ausgesperrt? In `config.json` `auth.users` auf `{}` setzen – beim nächsten
> Aufruf legst du den Admin neu an. `config.json` ist gitignored.

## E-Mail-Versand (Gmail)

Über **„✉️ Ablegen & per E-Mail senden"** wird das Formular festgeschrieben und
als PDF-Anhang an einen **fest konfigurierten Empfänger** geschickt (Modul
`app/mailer.py`, SMTP über Gmail). Vor dem Senden erscheint ein Dialog mit
Betreff + Text (aus der Vorlage vorbefüllt, für diesen Versand editierbar).

Einrichtung in den Einstellungen (E-Mail): **Absender** (Gmail-Adresse),
**Gmail App-Passwort** (nicht das normale Passwort – erfordert 2FA), fester
**Empfänger**, optional Cc sowie **Betreff-/Text-Vorlage** mit Platzhaltern
`{monat} {jahr} {periode} {steuer} {umsatz} {kassenzeichen} {name}`. Die Vorlage
wird in `config.json` gespeichert (App-Passwort inklusive – gitignored).

## Einstellungen

Unter **⚙️ Einstellungen** (`/settings`) lassen sich die PDF-Felder bearbeiten:
Betreiberdaten (Name, Adresse, **Telefon**, Kassenzeichen …), Unterschrift-Position,
Steuersatz, Smoobu-API-Key, Airbnb-Kanalname. Gespeichert wird in `config.json`
(lokal, nicht im Repo).

## Rechenregeln (Satzung Dresden v. 7.5.2015 + Vorgaben Betreiber)

* **Monatszuordnung nach Abreisedatum** (§6: Steuer entsteht mit Abreise).
  Reicht eine Buchung in den Folgemonat, zählt sie im Folgemonat.
* **Nur bereits stattgefundene Buchungen** (Abreise ≤ heute). Geplante /
  künftige Buchungen werden nicht berechnet.
* **Übernachtungen = Personen (Erwachsene + Kinder) × Nächte**.
* Ausgeschlossen: Stornos (`type = cancellation`) und Blockierungen.
* **Airbnb** wird separat aus Smoobu berechnet und ausgewiesen; diese ÜN
  fließen NICHT in die steuerpflichtigen Umsätze ein (Airbnb meldet und führt
  selbst an Dresden ab). Override-Feld nur für Ausnahmen.
* **Steuerbasis je Buchung = Buchungspreis ohne durchlaufende
  Übernachtungssteuer** (Smoobu `price` minus die `Übernachtungssteuer`-Zeile;
  Reinigungsgebühr bleibt enthalten). Die vom Gast separat gezahlte
  Übernachtungssteuer ist ein Durchlaufposten und wird nicht erneut besteuert.
* **Steuer = 6 %** der steuerpflichtigen Umsätze, kaufmännisch gerundet.

Validiert gegen zwei Monate:
* **Dezember 2025**: 137 verbl. ÜN · 15 Airbnb · 152 insgesamt · 5.698,29 € ·
  **341,90 € Steuer**. (Das eingereichte Formular hatte Airbnb falsch mit 7
  angegeben – ohne Auswirkung auf die Steuer.)
* **Mai 2026**: 14 Buchungen · 7.155,86 € verbleibender Umsatz.

## Konfiguration

`config.json` enthält API-Key, Steuersatz, Betreiber- und Empfängerdaten
(für das Formular). Anpassen statt im Code ändern.

## Webhook

`POST /api/smoobu/webhook` leert den Buchungs-Cache (TTL 5 min), damit
Änderungen aus Smoobu sofort einfließen. In Smoobu als Webhook-Ziel
`http://<host>:3001/api/smoobu/webhook` eintragen.

## Tests

```bash
python3 -m pytest        # Steuer-Golden-Tests (Dez 2025, Mai 2026) + UI-Test
```

`tests/test_steuer.py` prüft die Berechnung gegen zwei Monate, `tests/test_web.py`
testet die NiceGUI-Oberfläche headless (Seite lädt, „Berechnen" rendert Ergebnis).
