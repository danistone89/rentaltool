#!/usr/bin/env python3
"""Wo die Betriebsdaten liegen – getrennt vom Programmcode.

Auf dem Server liegt das Repo unter `/opt/rentaltool` und wird per `git pull`
erneuert. Die Betriebsdaten (Konten, Arbeitszeiten, Belege, Steuerarchiv,
Fotos) haben dort nichts zu suchen: ein unbedachtes `git clean`, ein neu
aufgesetzter Server oder ein Deploy aus einem anderen Klon – und sie wären weg.
Der Datenordner kommt deshalb aus der Umgebungsvariablen `RENTALTOOL_DATA`.

**Ohne die Variable bleibt alles wie bisher**: Datenordner = Projektordner. So
laufen lokale Entwicklung und Tests unverändert weiter, und ein vergessenes
`Environment=` in der systemd-Unit fällt beim Start sofort auf (siehe die
Prüfung in `app/data.py`), statt still eine leere App zu starten.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.abspath(os.environ.get("RENTALTOOL_DATA") or ROOT)

# Alles, was zum Datenbestand gehört – Grundlage für Umzug (tools/migrate_data.py)
# und Sicherung (tools/backup.py). Reihenfolge = Anzeige-Reihenfolge.
DATEIEN = ["config.json", "worklog.json", "assignments.json", "receipts.json",
           "checklists.json", "inventory.json", "cleanings.json", "damages.json",
           "restock.json"]
ORDNER = ["media", "archive", "templates", "assets"]


def p(*teile):
    """Pfad im Datenordner."""
    return os.path.join(DATA_DIR, *teile)


def getrennt():
    """Liegen Daten und Code getrennt? (False = alles im Projektordner)"""
    return DATA_DIR != ROOT
