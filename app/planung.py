#!/usr/bin/env python3
"""Wer macht welche Reinigung – Stammzuständigkeit, Abwesenheiten, Vorschläge.

Bisher war jede Zuweisung Handarbeit: Buchung öffnen, „Tauschen/Zuweisen",
Person aus einer Liste wählen. Bei zwei Wohnungen geht das. Bei zehn ist es
jeden Sonntagabend eine halbe Stunde, und der eine Tag, den man übersieht,
fällt erst am Morgen auf.

Drei Bausteine, alle ohne Oberfläche und damit prüfbar:

* **Stammzuständigkeit** je Wohnung (`config.json` → `zustaendigkeit`): wer
  macht diese Wohnung normalerweise? Das ist die Antwort auf 90 % der Fälle.
* **Abwesenheiten** (Tabelle `abwesenheiten`): wer ist wann nicht da? Ein
  Vorschlag, der jemanden im Urlaub einträgt, ist schlimmer als keiner – man
  verlässt sich darauf und merkt es zu spät.
* **Vorschlag**: Stammkraft, wenn sie da ist; sonst wer an dem Tag am wenigsten
  zu tun hat. Nie jemand, der abwesend ist.

Der Vorschlag ist ein **Vorschlag**. Er wird nie automatisch gespeichert – man
sieht ihn, ändert ihn bei Bedarf und bestätigt. Automatisches Zuweisen ohne
Blick darauf würde genau die Fehler machen, die niemand sucht, weil ja „das
System" zugewiesen hat.
"""
from datetime import date, timedelta

from app import data, db

TABELLE = "abwesenheiten"


# ------------------------------------------------------------ Stammzuständigkeit
def _cfg():
    return data.CONFIG.setdefault("zustaendigkeit", {})


def stammkraft(apt_id):
    """Wer macht diese Wohnung normalerweise? (oder None)"""
    return _cfg().get(str(apt_id)) or None


def stammkraft_setzen(apt_id, benutzer):
    if benutzer:
        _cfg()[str(apt_id)] = benutzer
    else:
        _cfg().pop(str(apt_id), None)
    data.save_config()


def stammkraefte():
    return dict(_cfg())


# ------------------------------------------------------------ Abwesenheiten
def abwesenheit_anlegen(benutzer, von, bis, grund=""):
    """Zeitraum eintragen (von/bis einschließlich, ISO-Datum)."""
    if bis < von:
        raise ValueError("Das Ende liegt vor dem Anfang.")
    satz = {"id": f"{benutzer}-{von}-{bis}", "user": benutzer,
            "von": von, "bis": bis, "grund": grund or ""}
    db.speichern(TABELLE, satz["id"], satz)
    return satz


def abwesenheiten(benutzer=None, ab=None):
    """Einträge, optional nur für einen Mitarbeiter und nur ab einem Datum."""
    alle = db.finden(TABELLE, benutzer=benutzer) if benutzer else db.alle(TABELLE)
    if ab:
        alle = [a for a in alle if a["bis"] >= ab]
    return sorted(alle, key=lambda a: a["von"])


def abwesenheit_loeschen(sid):
    return db.loeschen(TABELLE, sid)


def ist_abwesend(benutzer, tag, eintraege=None):
    """Ist dieser Mitarbeiter an diesem Tag weg? `tag` als ISO-Datum.

    `eintraege` erspart bei vielen Abfragen den Datenbankzugriff je Aufruf.
    """
    for a in (eintraege if eintraege is not None else abwesenheiten(benutzer)):
        if a["user"] == benutzer and a["von"] <= tag <= a["bis"]:
            return True
    return False


def abwesend_am(tag, eintraege=None):
    """Alle, die an diesem Tag weg sind."""
    return {a["user"] for a in (eintraege if eintraege is not None else abwesenheiten())
            if a["von"] <= tag <= a["bis"]}


# ------------------------------------------------------------ Vorschlag
def vorschlag(job, mitarbeiter, last=None, eintraege=None):
    """Wer sollte diese Reinigung machen? (oder None, wenn niemand kann)

    `mitarbeiter`: {benutzername: anzeigename} der in Frage kommenden Leute.
    `last`: {benutzername: anzahl} bereits verplanter Reinigungen – damit sich
    ein Stapel nicht auf einer Person häuft.
    """
    tag = job["departure"]
    weg = abwesend_am(tag, eintraege)
    moeglich = [m for m in mitarbeiter if m not in weg]
    if not moeglich:
        return None
    stamm = stammkraft(job.get("apartment_id"))
    if stamm in moeglich:
        return stamm
    last = last or {}
    # Gleichstand nach Name auflösen, damit derselbe Bestand immer denselben
    # Vorschlag ergibt – ein Plan, der sich bei jedem Aufruf ändert, ist keiner.
    return sorted(moeglich, key=lambda m: (last.get(m, 0), m))[0]


def vorschlaege(jobs, mitarbeiter, bereits=None):
    """[(job, vorgeschlagener)] für eine Liste offener Reinigungen.

    `bereits`: schon vergebene Reinigungen je Mitarbeiter (aus dem Bestand), damit
    der Vorschlag die vorhandene Last mitzählt und nicht bei null anfängt.
    """
    eintraege = abwesenheiten()
    last = dict(bereits or {})
    out = []
    for job in sorted(jobs, key=lambda j: (j["departure"], j.get("apartment_name", ""))):
        wer = vorschlag(job, mitarbeiter, last, eintraege)
        if wer:
            last[wer] = last.get(wer, 0) + 1
        out.append((job, wer))
    return out


def last_je_mitarbeiter(jobs, zuweisung):
    """{benutzer: anzahl} über bereits zugewiesene Reinigungen."""
    out = {}
    for j in jobs:
        wer = zuweisung(j["id"])
        if wer:
            out[wer] = out.get(wer, 0) + 1
    return out


def naechste_tage(jobs, tage=14, ab=None):
    """Offene Reinigungen der nächsten Tage – der Planungshorizont."""
    ab = ab or date.today()
    bis = (ab + timedelta(days=tage)).isoformat()
    return [j for j in jobs if ab.isoformat() <= j["departure"] <= bis]
