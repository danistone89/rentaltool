#!/usr/bin/env python3
"""Läuft das hier im Echtbetrieb oder auf der Probe-Instanz?

Die Probe-Instanz arbeitet mit einer **Kopie der echten Daten** – echte Gäste,
echte Mitarbeiter, echte E-Mail-Adressen. Ohne Bremse würde ein Klick beim
Ausprobieren eine Mail an eine Putzkraft schicken, eine Nachricht an einen Gast
senden oder eine Datei in die Nextcloud spiegeln.

Deshalb zwei Ebenen:

* `tools/staging_refresh.py` räumt beim Kopieren die Zugangsdaten aus der
  Konfiguration (Mail-Passwörter, Spiegel-Ordner, Sicherungsziel).
* Diese Schalter hier blockieren die Wege **im Code**, unabhängig davon, was in
  der Konfiguration steht. Wer die Konfiguration von Hand wieder füllt, kommt
  trotzdem nicht raus.

Gesetzt wird über `RENTALTOOL_STAGING=1` in der systemd-Unit der Probe-Instanz.
"""
import os

STAGING = (os.environ.get("RENTALTOOL_STAGING", "") or "").lower() \
    not in ("", "0", "false", "nein")

LABEL = "PROBE-INSTANZ"


class NurProbe(RuntimeError):
    """Auf der Probe-Instanz absichtlich blockiert."""


def blocken(was):
    """Auf der Probe-Instanz mit klarer Ansage abbrechen, sonst nichts tun."""
    if STAGING:
        raise NurProbe(f"{LABEL}: {was} wird hier nicht ausgeführt – "
                       f"das ginge an echte Empfänger.")
