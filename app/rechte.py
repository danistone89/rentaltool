#!/usr/bin/env python3
"""Wer was darf – benannt, an einer Stelle.

Vorher gab es zwei Grobraster: `ROLE_AREAS` schaltete **ganze Bereiche** an und
aus, und im Code stand acht Mal `if _is_admin()`. Dazwischen lag nichts. Ein
Manager, der Reinigungen verteilt und Arbeitszeiten korrigiert, brauchte dafür
entweder Administratorrechte – also auch Benutzerverwaltung, Einstellungen und
Steuer – oder er konnte es nicht.

Hier steht stattdessen, **was** jemand darf, nicht **wo** er hindarf. Die
Bereiche bleiben in `ROLE_AREAS`; die beiden Fragen sind verschieden:
„sieht er die Belege?" und „darf er einen löschen?".

Die Linie zwischen Manager und Betreiber ist bewusst gezogen: **der Manager
führt den Tag, der Betreiber verantwortet Nachweis und Geld.** Was einmal an
das Steuerbüro gemeldet oder als Beleg abgelegt wurde, fasst nur der Betreiber
noch an – nicht aus Misstrauen, sondern weil eine Korrektur dort Folgen
außerhalb der App hat.
"""

# ---- Die Fähigkeiten, einzeln benannt --------------------------------------
ZUWEISEN = "zuweisen"                      # Reinigung zuweisen, tauschen
ZEITEN_FREMDE = "zeiten_fremde"            # Arbeitszeit anderer erfassen/ändern
ZEITEN_ABGERECHNET = "zeiten_abgerechnet"  # bereits gemeldete Zeiten noch ändern
AUFTRAG_ZURUECK = "auftrag_zuruecksetzen"  # Zuweisung + Checkliste + Zeiten lösen
BELEGE_BUCHEN = "belege_buchen"            # Kategorie geben, Monat abschließen
BELEGE_LOESCHEN = "belege_loeschen"        # Beleg endgültig entfernen
BENUTZER = "benutzer"                      # Konten anlegen, Rollen ändern
EINSTELLUNGEN = "einstellungen"            # Konfiguration der Anwendung
STEUER = "steuer"                          # Anmeldung erzeugen, senden, bezahlen

ALLE = [ZUWEISEN, ZEITEN_FREMDE, ZEITEN_ABGERECHNET, AUFTRAG_ZURUECK,
        BELEGE_BUCHEN, BELEGE_LOESCHEN, BENUTZER, EINSTELLUNGEN, STEUER]

# Klartext für die Anzeige – der Schlüssel taugt nicht als Beschriftung.
LABELS = {
    ZUWEISEN: "Reinigungen zuweisen und tauschen",
    ZEITEN_FREMDE: "Arbeitszeiten anderer erfassen und korrigieren",
    ZEITEN_ABGERECHNET: "Bereits abgerechnete Zeiten ändern",
    AUFTRAG_ZURUECK: "Auftrag zurücksetzen",
    BELEGE_BUCHEN: "Belege kategorisieren, Monat abschließen",
    BELEGE_LOESCHEN: "Belege löschen",
    BENUTZER: "Benutzer verwalten",
    EINSTELLUNGEN: "Einstellungen ändern",
    STEUER: "Beherbergungssteuer melden und bezahlen",
}


# ---- Was jede Rolle mitbringt ----------------------------------------------
# Der Manager führt den Tag: verteilen, nachtragen, aufräumen. Nicht dabei sind
# die drei Dinge mit Wirkung nach außen – ein gelöschter Beleg ist ein
# verlorenes Beweismittel, und eine geänderte abgerechnete Zeit weicht von dem
# ab, was beim Steuerbüro liegt.
ROLLE_RECHTE = {
    "admin": set(ALLE),
    "manager": {ZUWEISEN, ZEITEN_FREMDE, AUFTRAG_ZURUECK, BELEGE_BUCHEN},
    "putzkraft": set(),
}


def rechte_von(rolle):
    """Die Fähigkeiten dieser Rolle. Unbekannte Rolle heißt: keine."""
    return set(ROLLE_RECHTE.get(rolle or "", set()))


def darf(rolle, recht):
    """Darf diese Rolle das?

    Bewusst eine reine Funktion über die Rolle statt über die Sitzung: so lässt
    sie sich ohne Oberfläche prüfen, und die Regel steht nicht im Bildschirm,
    sondern im Modul.
    """
    return recht in rechte_von(rolle)
