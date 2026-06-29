# templates/

Hier gehört die Blanko-Vorlage `anmeldung_blank.pdf` hin – sie wird **nicht**
eingecheckt (`.gitignore`), weil sie deine Betreiberdaten + Kassenzeichen enthält.

## Vorlage erzeugen

Dresden bietet das Formular (Vdr 22.040/5) nur über das Online-System an, es gibt
keinen Blanko-Download. Erzeuge die Vorlage daher einmalig aus einer bereits
eingereichten PDF:

```bash
python3 tools/make_blank.py /pfad/zu/deiner/eingereichten_anmeldung.pdf
```

Das Skript entfernt alle variablen Werte (Zahlen, Datum, Jahr, Monatskreuz,
Dokument-ID) und legt `templates/anmeldung_blank.pdf` an. Betreiberdaten,
Kassenzeichen und Layout bleiben erhalten.

Ohne diese Datei funktioniert die Berechnung und die Web-UI weiterhin – nur der
PDF-Download (`/pdf`) ist deaktiviert.
