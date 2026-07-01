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

**Externer Spiegel (Nextcloud):** In den Einstellungen lässt sich ein
**Spiegel-Ordner** wählen (erkannte Cloud-Ordner unter `~/Library/CloudStorage`
oder freier Pfad). Jede Festschreibung kopiert die PDF + den Ledger dorthin; der
Nextcloud-Sync lädt sie hoch → Ablage „außer Haus". Über das Archiv (📚) lässt
sich mit **„🔁 Alles nach Nextcloud spiegeln"** der Bestand nachträglich sichern.
Schlägt die Spiegelung fehl, bleibt die lokale Ablage trotzdem gültig.

> Pragmatische Revisionssicherheit (Integrität, Unveränderbarkeit, Nachweis +
> externe Kopie). `archive/` ist gitignored.

## Datenaktualität

Smoobu-Daten werden beim **Berechnen** geladen und **5 Minuten** pro Monats-
zeitraum zwischengespeichert. Der **🔄-Button** leert den Cache und lädt frisch;
unter den Eingaben steht „Daten zuletzt von Smoobu geladen: …". Der Webhook
(`/api/smoobu/webhook`) leert den Cache automatisch bei Änderungen in Smoobu.

## Login & 2FA

Die App ist durch einen **Login** geschützt (Single-User, `app/auth.py`). Beim
ersten Aufruf legst du unter `/login` ein Passwort fest (PBKDF2-gehasht in
`config.auth`). Ausgenommen vom Login-Zwang: die Login-Seite, der Smoobu-Webhook
(`/api/…`) und NiceGUI-Interna.

Optional **2FA mit Google Authenticator** (TOTP): in den Einstellungen unter
„Sicherheit / Login" aktivieren → QR-Code scannen → ab dann Passwort **+**
6-stelliger Code beim Login. Passwort ändern ebenfalls dort.

> Passwort vergessen? In `config.json` unter `auth.password_hash` leeren – beim
> nächsten Aufruf kannst du ein neues festlegen. `config.json` ist gitignored.

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
