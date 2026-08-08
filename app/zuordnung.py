#!/usr/bin/env python3
"""Was zu einer Bankbewegung gehört – als eigener Satz, nicht als Feld (B1).

**Warum das ein eigener Satz sein muss.** Vorher hing an einer Bewegung je ein
Feld: `beleg_id`, `rechnung_id`. Das ist eine 1:1-Beziehung und reicht für den
einfachen Fall – ein Gast überweist genau den Rechnungsbetrag. Für den
Normalfall reicht es nicht:

    Bankbewegung  12.01.2026   +1.794,13 €   Airbnb
    ├─ Rechnung 41                +620,00 €
    ├─ Rechnung 42                +540,00 €
    ├─ Rechnung 43                +780,00 €
    └─ Beleg: Airbnb-Provision    −145,87 €
                                  ──────────
       Rest                          0,00 €

Nachgezählt an den echten Daten: **51 von 65 Zahlungseingängen** sind solche
Sammelauszahlungen – beide Portale zahlen je Wohnung und Auszahlungslauf, nicht
je Reservierung. Der n:m-Fall ist also der Normalfall, nicht die Ausnahme.

**Der Restbetrag ist die ganze Mechanik.** Bewegungsbetrag minus Summe der
Posten. Ist er null, ist die Bewegung fertig; ist er es nicht, fehlt etwas –
meistens genau die Provision. So arbeiten DATEV und lexoffice, und deshalb
braucht es keine Sonderbehandlung für den 1:1-Fall: der ist eine Bewegung mit
genau einem Posten.

**Vorzeichen sind nicht normiert.** Ein Posten trägt das Vorzeichen seiner
Wirkung: Rechnungen einer Auszahlung sind positiv, die Provision negativ. Die
Summe muss stimmen, nicht das einzelne Vorzeichen – sonst ließe sich die
Provision gar nicht gegenbuchen.
"""
import uuid
from datetime import datetime

from app import db

TABELLE = "zuordnungen"

# Worauf ein Posten zeigt. „kategorie" ist der Fall ohne Gegenstück: eine
# Bankgebühr braucht keinen Beleg, soll aber eine Kategorie tragen.
RECHNUNG, BELEG, KATEGORIE = "rechnung", "beleg", "kategorie"
ARTEN = (RECHNUNG, BELEG, KATEGORIE)

# Unter diesem Betrag gilt der Rest als null. Cent-Reste entstehen beim Runden
# der Einzelpositionen; wer auf 0,00 besteht, macht die Maske unbenutzbar.
GENAU = 0.005


def _jetzt():
    return datetime.now().isoformat(timespec="seconds")


def posten(bewegung_id):
    """Alle Posten einer Bewegung, in der Reihenfolge des Anlegens."""
    # Die Spalte heisst `bewegung` (siehe db.TABELLEN), das Feld `bewegung_id`.
    return sorted(db.finden(TABELLE, bewegung=bewegung_id),
                  key=lambda z: z.get("angelegt", ""))


def hinzufuegen(bewegung_id, art, betrag, kategorie="", ziel_id="", notiz=""):
    """Einen Posten anlegen. Gibt (satz, meldung) zurück – `satz` ist None,
    wenn nichts angelegt wurde.

    Geprüft wird nur, was sich nicht heilen lässt: eine unbekannte Art, ein
    Betrag von null, ein fehlendes Ziel bei Rechnung oder Beleg. **Nicht**
    geprüft wird, ob die Summe den Bewegungsbetrag übersteigt – bei einer
    Auszahlung nach Provision ist die Summe der Rechnungen größer als das, was
    ankam. Das ist kein Fehler, sondern der Grund für den Provisionsposten.
    """
    if art not in ARTEN:
        return None, f"Unbekannte Art: {art}"
    try:
        betrag = round(float(betrag), 2)
    except (TypeError, ValueError):
        return None, "Betrag ist keine Zahl."
    if abs(betrag) < GENAU:
        return None, "Ein Posten über 0,00 € sagt nichts."
    if art in (RECHNUNG, BELEG) and not str(ziel_id or "").strip():
        return None, "Ohne Rechnung oder Beleg fehlt das Gegenstück."
    satz = {"id": uuid.uuid4().hex[:12], "bewegung_id": bewegung_id, "art": art,
            "ziel_id": str(ziel_id or ""), "kategorie": kategorie or "",
            "betrag": betrag, "notiz": notiz or "", "angelegt": _jetzt()}
    db.anlegen(TABELLE, satz)
    return satz, "Zugeordnet."


def entfernen(zuordnung_id):
    db.loeschen(TABELLE, zuordnung_id)


def entfernen_zu(bewegung_id):
    """Alle Posten einer Bewegung lösen – für den Neuanfang an einer Zeile."""
    with db.transaktion():
        for z in posten(bewegung_id):
            db.loeschen(TABELLE, z["id"])


def summe(bewegung_id):
    return round(sum(z.get("betrag", 0.0) for z in posten(bewegung_id)), 2)


def rest(bewegung):
    """Was an dieser Bewegung noch offen ist. 0,00 heißt fertig."""
    return round(bewegung.get("betrag", 0.0) - summe(bewegung["id"]), 2)


def ist_fertig(bewegung):
    return abs(rest(bewegung)) < GENAU


def hat_posten(bewegung_id):
    return bool(posten(bewegung_id))


def ziele(bewegung_id, art):
    """Die Ziel-Kennungen einer Art – etwa alle Rechnungen dieser Zahlung."""
    return [z["ziel_id"] for z in posten(bewegung_id)
            if z["art"] == art and z["ziel_id"]]


def bewegungen_zu(art, ziel_id):
    """Umgekehrter Weg: an welchen Bewegungen hängt diese Rechnung oder dieser
    Beleg?

    **Mehrzahl, weil ein Beleg auf mehrere Bewegungen zeigen darf** (B5): der
    Provisionsbeleg von Booking kommt monatlich, die Auszahlungen kommen
    einzeln – 44 im Halbjahr. Ohne diese Richtung ließe sich ein Monatsbeleg
    gar nicht verbuchen.
    """
    return [z["bewegung_id"] for z in db.finden(TABELLE, zart=art, ziel=str(ziel_id))]


def bewegung_zu(art, ziel_id):
    """Die erste Bewegung dazu – für die Frage „ist diese Rechnung bezahlt?".

    Eine Rechnung gehört immer zu genau einer Zahlung; für Belege ist
    `bewegungen_zu` das richtige Werkzeug.
    """
    treffer = bewegungen_zu(art, ziel_id)
    return treffer[0] if treffer else ""


def uebernehmen_aus_feldern(bewegungen):
    """Einmal-Übernahme der alten 1:1-Felder in das neue Modell.

    Vor B1 hing ein Beleg als `beleg_id` an der Bewegung. Diese Zuordnungen
    dürfen nicht verlorengehen, nur weil das Modell sich ändert – sonst wäre
    jede bereits geleistete Arbeit weg. Läuft mehrfach ohne Schaden: was schon
    einen Posten hat, wird übersprungen.
    """
    uebernommen = 0
    with db.transaktion():
        for b in bewegungen:
            alt = (b.get("beleg_id") or "").strip()
            if not alt or hat_posten(b["id"]):
                continue
            hinzufuegen(b["id"], BELEG, b.get("betrag", 0.0),
                        kategorie=b.get("kategorie", ""), ziel_id=alt,
                        notiz="übernommen aus der 1:1-Zuordnung")
            uebernommen += 1
    return uebernommen


def ziel_setzen(zuordnung_id, art, ziel_id):
    """Einem vorhandenen Posten sein Gegenstück geben (B5).

    Aus „nur Kategorie" wird „Beleg": Betrag und Kategorie bleiben, es kommt
    das Papier dazu. Nötig, weil ein nachgereichter Beleg **keinen zusätzlichen
    Posten** erzeugen darf – die Zahlung wäre sonst doppelt gebucht. Der
    Provisionsbeleg einer Plattform kommt regelmäßig erst nach der Buchung.
    """
    z = db.holen(TABELLE, zuordnung_id)
    if z is None or art not in ARTEN or not str(ziel_id or "").strip():
        return None
    z["art"], z["ziel_id"] = art, str(ziel_id)
    db.speichern(TABELLE, zuordnung_id, z)
    return z
