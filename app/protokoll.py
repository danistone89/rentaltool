#!/usr/bin/env python3
"""Wer hat was geändert – für die Handvoll Dinge, bei denen das zählt.

Kein Vollprotokoll. Jeden Klick mitzuschreiben erzeugt eine Menge, die niemand
liest, und in der das Wesentliche untergeht. Notiert wird, was **jemand anderem
schadet, wenn es unbemerkt passiert**:

* Konten und Rollen – wer darf plötzlich mehr?
* gelöschte Belege – ein Beweismittel ist weg
* geänderte abgerechnete Zeiten – weicht von dem ab, was beim Steuerbüro liegt
* Monatsabschluss zurückgenommen, Steuermeldung zurückgesetzt

Das Protokoll ist bewusst **nur lesbar**: Es gibt keine Funktion zum Löschen
eines Eintrags. Ein Protokoll, das sich aufräumen lässt, beweist nichts.
"""
import uuid
from datetime import datetime

from app import db

TABELLE = "protokoll"


def _jetzt():
    return datetime.now().isoformat(timespec="seconds")


def notieren(wer, was, ziel="", details=""):
    """Einen Vorgang festhalten.

    `was` ist ein kurzer Schlüssel (siehe die Konstanten unten), `ziel` das
    betroffene Objekt (Benutzername, Beleg-ID, Monat), `details` ein Satz für
    Menschen.
    """
    eintrag = {"id": uuid.uuid4().hex[:12], "ts": _jetzt(), "wer": wer or "?",
               "was": was, "ziel": ziel or "", "details": details or ""}
    db.anlegen(TABELLE, eintrag)
    return eintrag


def eintraege(limit=200):
    """Neueste zuerst."""
    return sorted(db.alle(TABELLE), key=lambda e: e.get("ts", ""), reverse=True)[:limit]


# ---- Die Vorgänge, die notiert werden --------------------------------------
BENUTZER_ANGELEGT = "benutzer_angelegt"
BENUTZER_GELOESCHT = "benutzer_geloescht"
ROLLE_GEAENDERT = "rolle_geaendert"
ZUGANG_ZURUECKGESETZT = "zugang_zurueckgesetzt"
BELEG_GELOESCHT = "beleg_geloescht"
ZEIT_ABGERECHNET_GEAENDERT = "zeit_abgerechnet_geaendert"
MONAT_GEOEFFNET = "monat_geoeffnet"
MELDUNG_ZURUECKGESETZT = "meldung_zurueckgesetzt"

TEXTE = {
    BENUTZER_ANGELEGT: "Benutzer angelegt",
    BENUTZER_GELOESCHT: "Benutzer gelöscht",
    ROLLE_GEAENDERT: "Rolle geändert",
    ZUGANG_ZURUECKGESETZT: "Zugang zurückgesetzt",
    BELEG_GELOESCHT: "Beleg gelöscht",
    ZEIT_ABGERECHNET_GEAENDERT: "Abgerechnete Zeit geändert",
    MONAT_GEOEFFNET: "Abgeschlossenen Monat wieder geöffnet",
    MELDUNG_ZURUECKGESETZT: "Steuermeldung zurückgesetzt",
}


def text_von(was):
    return TEXTE.get(was, was)
