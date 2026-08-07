#!/usr/bin/env python3
"""Kontobewegungen ablegen und abfragen.

Das Lesen der Auszüge steht in `app/kontoauszug.py`; hier geht es nur um die
Ablage. Getrennt, weil das Lesen die heikle Fachlogik ist und ohne Datenbank
prüfbar bleiben soll.

**Ein zweiter Import darf nichts kaputtmachen.** Auszüge überschneiden sich:
wer im Juli und im August exportiert, hat den Juli zweimal. Der Satzschlüssel
ist deshalb der Fingerabdruck der Bewegung (`kontoauszug.schluessel`) und nicht
eine laufende Nummer – dieselbe Bewegung landet auf demselben Satz, egal wie
oft sie eingelesen wird.

**Was einmal zugeordnet ist, bleibt zugeordnet.** Beim erneuten Import werden
die Felder der Bank aufgefrischt, die eigenen Zuordnungen (Beleg, Rechnung,
Kategorie) aber nicht angerührt. Sonst wäre jede Wiederholung ein Rückschritt.
"""
from datetime import datetime

from app import buchhaltung, db, kontoauszug, stammdaten

TABELLE = "bewegungen"

# **Hier stehen keine Namen.** Wer die eigene Privatentnahme bekommt, welche
# Stadtkasse die Beherbergungssteuer einzieht und wie die Bank des Darlehens
# heißt, ist von Betrieb zu Betrieb verschieden – das sind **Stammdaten**, keine
# Fachlogik. Sie werden als Kreditoren gepflegt (Einstellungen → Produkte &
# Kreditoren) und tragen dort eine Klasse aus `buchhaltung.KLASSEN`.
#
# Eine erste Fassung war anders: die Empfänger standen in dieser Datei. Das war
# nicht Software, sondern eine Buchhaltung in Python – für genau einen Betrieb,
# nicht änderbar, ohne den Quelltext anzufassen.

# Felder, die dem Werkzeug gehören und nicht der Bank. Ein erneuter Import
# lässt sie in Ruhe.
_EIGENE = ("beleg_id", "rechnung_id", "kategorie", "klasse", "herkunft",
           "notiz", "geprueft")

def _jetzt():
    return datetime.now().isoformat(timespec="seconds")


def erkennen(bewegung):
    """Was ist das für eine Bewegung? (kategorie, klasse, herkunft).

    Drei Stufen:

    1. **Umbuchung** zwischen eigenen Konten – neutral, kein Geldfluss nach
       außen (siehe `kontoauszug`).
    2. **Kreditor** – dieselbe Erkennung wie bei den Belegen
       (`stammdaten.kreditor_zu`), nur auf dem Empfänger der Bewegung. Er
       bringt Kategorie **und Klasse** mit. Die Klasse entscheidet, ob die
       Zahlung ins Ergebnis eingeht: eine Privatentnahme ist keine Ausgabe.
       Steht am Kreditor keine Klasse, wird sie aus der Kategorie abgeleitet.
    3. **Nichts** – dann bleibt es leer und die Bewegung wartet auf einen
       Menschen. Raten wäre hier schlimmer als schweigen: eine falsche
       Kategorie läuft still ins Ergebnis.

    Eingänge bekommen keine Kategorie: was ein Erlös ist, entscheidet erst die
    Zuordnung zu einer Rechnung (AP20) und die Portalabrechnung (AP23).
    """
    if bewegung.get("umbuchung"):
        return "", "Neutral", "umbuchung"
    k = stammdaten.kreditor_zu(bewegung.get("gegenpartei") or "")
    if k and (k.get("kategorie") or k.get("klasse")):
        klasse = k.get("klasse") or buchhaltung.klasse_fuer(k.get("kategorie", ""))
        return k.get("kategorie", ""), klasse, "kreditor"
    if bewegung.get("betrag", 0) > 0:
        return "", "Einnahme", ""
    return "", "", ""


def zuordnen(bewegungen=None):
    """Erkennung auf alle Bewegungen anwenden, die noch keine Kategorie tragen.

    Was ein Mensch von Hand gesetzt hat, bleibt unangetastet – sonst nähme ein
    späterer Lauf die Korrektur wieder zurück.
    """
    getroffen = 0
    with db.transaktion():
        for b in (bewegungen if bewegungen is not None else db.alle(TABELLE)):
            if b.get("kategorie") or b.get("klasse"):
                continue
            kategorie, klasse, art = erkennen(b)
            if not (kategorie or klasse):
                continue
            db.speichern(TABELLE, b["id"],
                         dict(b, kategorie=kategorie, klasse=klasse, herkunft=art))
            getroffen += 1
    return getroffen


def ohne_zuordnung():
    """Ausgänge, die weder erkannt noch von Hand zugeordnet sind.

    Das ist die Arbeitsliste – und später das Maß dafür, ob die Übergabe ans
    Steuerbüro vollständig ist (AP25).
    """
    return [b for b in alle()
            if b.get("betrag", 0) < 0 and not b.get("umbuchung")
            and not (b.get("kategorie") or "").strip()]


def importieren(rohdaten, heute=None):
    """Einen Auszug einlesen und ablegen.

    Gibt einen Bericht zurück: was gelesen wurde, was neu ist und was schon da
    war. Die Zahl der Dubletten ist keine Panne, sondern der Normalfall bei
    überlappenden Auszügen – sie gehört trotzdem in die Rückmeldung, damit
    niemand rätselt, warum aus 169 Zeilen 12 neue Sätze wurden.
    """
    konto, art, gelesen = kontoauszug.lesen(rohdaten, heute=heute)
    neu = doppelt = 0
    with db.transaktion():
        for b in gelesen:
            vorhanden = db.holen(TABELLE, b["id"])
            if vorhanden is None:
                db.anlegen(TABELLE, dict(b, erfasst=_jetzt()), sid=b["id"])
                neu += 1
            else:
                # Die Bankfelder auffrischen, die eigenen behalten.
                satz = dict(vorhanden)
                satz.update(b)
                for feld in _EIGENE:
                    if feld in vorhanden:
                        satz[feld] = vorhanden[feld]
                db.speichern(TABELLE, b["id"], satz)
                doppelt += 1
    bericht = kontoauszug.zusammenfassung(gelesen)
    bericht.update({"konto": konto, "art": art, "neu": neu, "doppelt": doppelt,
                    "erkannt": zuordnen()})
    return bericht


def alle(von="", bis="", konto=""):
    """Bewegungen im Zeitraum, neueste zuerst. Leere Grenzen = alles."""
    treffer = [b for b in db.alle(TABELLE)
               if (not von or b.get("datum", "") >= von)
               and (not bis or b.get("datum", "") <= bis)
               and (not konto or b.get("konto") == konto)]
    return sorted(treffer, key=lambda b: (b.get("datum", ""), b.get("erfasst", "")),
                  reverse=True)


def konten():
    """Welche Konten liegen im Bestand – für Filter und Anzeige."""
    return sorted({b.get("konto", "") for b in db.alle(TABELLE) if b.get("konto")})


def zeitraum(konto=""):
    """(erster, letzter) Tag im Bestand – oder ('', '')."""
    tage = sorted(b.get("datum", "") for b in db.alle(TABELLE)
                  if b.get("datum") and (not konto or b.get("konto") == konto))
    return (tage[0], tage[-1]) if tage else ("", "")


def monatssummen(konto=""):
    """Je Monat: Geldfluss und – davon getrennt – das betriebliche Ergebnis.

    **Zwei verschiedene Zahlen, und die Verwechslung ist teuer.**

    * `eingang`/`ausgang` sind der reine **Geldfluss**: was auf dem Konto
      passiert ist. Umbuchungen bleiben draußen (der Kreditkarten-Ausgleich ist
      keine Ausgabe, sonst stünden die Kartenkäufe doppelt).
    * `ergebnis` lässt zusätzlich alles weg, was **keine Betriebsausgabe** ist:
      Privatentnahmen, durchlaufende Posten wie die abgeführte
      Beherbergungssteuer, und Bewegungen der Klasse `Neutral`.

    Über das erste Halbjahr 2026 liegen dazwischen mehr als 8.000 € – wer den
    Geldfluss für das Ergebnis hält, rechnet sich arm.

    `unklar` zählt die Ausgänge, die noch niemand zugeordnet hat. Solange die
    Zahl größer als null ist, ist das Ergebnis eine Näherung, und die Anzeige
    soll das sagen dürfen.
    """
    # Klassen, die nicht ins betriebliche Ergebnis gehören.
    raus = {"Privat/prüfen", "Durchlaufend", "Neutral"}
    summen = {}
    for b in db.alle(TABELLE):
        if b.get("umbuchung") or not b.get("datum"):
            continue
        if konto and b.get("konto") != konto:
            continue
        monat = b["datum"][:7]
        e = summen.setdefault(monat, {"eingang": 0.0, "ausgang": 0.0,
                                      "ergebnis": 0.0, "unklar": 0})
        wert = b.get("betrag", 0.0)
        e["eingang" if wert > 0 else "ausgang"] += wert
        if (b.get("klasse") or "") not in raus:
            e["ergebnis"] += wert
        if wert < 0 and not (b.get("kategorie") or "").strip():
            e["unklar"] += 1
    return {m: {k: (v if k == "unklar" else round(v, 2)) for k, v in w.items()}
            for m, w in sorted(summen.items())}
