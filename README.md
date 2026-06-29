# Beherbergungssteuer Dresden

Lokale Webapp, die aus den Smoobu-Buchungen die monatliche
Beherbergungssteuer-Anmeldung für Dresden berechnet und das **amtliche Formular
(Vdr 22.040/5) pixelgenau als PDF** erzeugt.

Berechnung & Web-UI: reine Python-Standardbibliothek. Für die PDF-Erzeugung wird
zusätzlich **PyMuPDF** benötigt (`pip install -r requirements.txt`).

## Start

```bash
cd apps/beherbergungssteuer
pip install -r requirements.txt   # nur für PDF nötig (PyMuPDF)
./run-local.sh                    # = python3 app/server.py
```

Dann <http://localhost:3001/> öffnen, Jahr/Monat + Apartments wählen,
**Berechnen** → Ergebnis, Buchungsliste und **„📄 Amtliches Formular (PDF)
herunterladen"** (Route `/pdf`).

## Amtliches PDF-Formular

Dresden bietet das Formular nur über ein Online-System (intelliform) an, kein
Blanko-Download. Daher wurde aus einer eingereichten PDF einmalig eine
Blanko-Vorlage erzeugt: `templates/anmeldung_blank.pdf` – variable Werte (Zahlen,
Datum, Jahr, Monatskreuz, abgabe-spezifische Dokument-ID) per Redaction entfernt,
Betreiberdaten/Kassenzeichen/Layout erhalten (Generator: `tools/make_blank.py`).

`app/pdf_form.py` setzt je Monat nur die berechneten Werte koordinatengenau ein
und kreuzt den Monat an. Ändern sich Betreiberdaten/Kassenzeichen, Vorlage mit
`tools/make_blank.py` aus einer aktuellen PDF neu erzeugen.

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
python3 -m unittest discover tests   # Golden-Test gegen Dez 2025
```
