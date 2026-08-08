#!/usr/bin/env python3
"""Verrechnungskonto je Plattform – was Booking und Airbnb noch schulden (B4b).

**Warum es das braucht.** Booking und Airbnb zahlen gesammelt und netto aus.
Zwischen der Rechnung an den Gast und dem Geld auf dem Konto liegen Wochen und
eine einbehaltene Provision. Ohne eine laufende Rechnung darüber sieht niemand,
ob ein Monat aufgeht – und ob die Plattform noch etwas schuldet.

Genau dafür führt das Steuerbüro ein Verrechnungskonto. Hier ist es dieselbe
Rechnung:

    Saldo = Σ zugeordnete Rechnungen − Σ Provisionen − Σ Auszahlungen

**Abgeleitet, nicht doppelt gebucht.** Es wäre möglich, je Rechnung und je
Provision eine zweite Bewegung auf einem Plattform-Konto zu erzeugen – echte
doppelte Buchführung. Dagegen sprechen zwei Dinge: die Zahlen stünden zweimal
im Bestand und könnten auseinanderlaufen, und jede Korrektur müsste an beiden
Stellen passieren. Der Saldo lässt sich aus dem berechnen, was ohnehin da ist –
dieselbe Zahl, eine Quelle.

**Die Zuordnung zur Plattform geschieht über die Bewegung**, an der die
Rechnungen hängen: Wer eine Auszahlung von Booking aufteilt, ordnet damit ihre
Rechnungen dem Konto „Booking" zu. Nichts Zusätzliches zu pflegen.
"""
from app import db, konto, zuordnung

# Woran eine Plattform am Zahlungseingang erkannt wird. Bewusst knapp: was hier
# hineinrutscht, landet auf dem falschen Konto.
PLATTFORMEN = [
    {"schluessel": "booking", "name": "Booking.com", "muster": ("booking.com", "booking com")},
    {"schluessel": "airbnb", "name": "Airbnb", "muster": ("airbnb",)},
]


def plattform_von(bewegung):
    """Zu welcher Plattform gehört diese Bewegung? '' wenn zu keiner."""
    text = ((bewegung.get("gegenpartei") or "") + " "
            + (bewegung.get("text") or "")).lower()
    for p in PLATTFORMEN:
        if any(m in text for m in p["muster"]):
            return p["schluessel"]
    return ""


def name_von(schluessel):
    for p in PLATTFORMEN:
        if p["schluessel"] == schluessel:
            return p["name"]
    return schluessel or ""


def _rechnung(ziel_id):
    return db.holen("rechnungen", ziel_id) or {}


def zeilen(schluessel, von="", bis=""):
    """Das Kontoblatt einer Plattform, ältestes zuerst.

    Vier Arten von Zeilen, alle aus den vorhandenen Zuordnungen abgeleitet:

    * **Rechnung** – was der Gast schuldet und die Plattform einzieht (+),
    * **Erlös** – dasselbe, aber ohne Rechnung direkt auf eine Kategorie
      gebucht (+); gehört aufs Konto, sonst fehlte die Gegenseite,
    * **Provision** – was sie einbehält (−),
    * **Auszahlung** – was tatsächlich ankam (−).

    In Summe muss das null ergeben. Tut es das nicht, fehlt etwas.
    """
    raus = []
    for b in konto.alle(von, bis):
        if plattform_von(b) != schluessel or b.get("betrag", 0) <= 0:
            continue
        for z in zuordnung.posten(b["id"]):
            if z["art"] == zuordnung.RECHNUNG:
                r = _rechnung(z.get("ziel_id"))
                raus.append({"datum": b["datum"], "art": "rechnung",
                             "text": " · ".join(x for x in
                                                [f"Nr. {r['nummer']}" if r.get("nummer") else "",
                                                 r.get("gast", "")] if x) or "Rechnung",
                             "betrag": z["betrag"], "bewegung": b["id"]})
            else:
                # Ein negativer Posten ist die einbehaltene Provision; ein
                # positiver ist Erlös, der ohne Rechnung gebucht wurde. Beide
                # gehören aufs Konto, aber nicht in dieselbe Zeile – sonst
                # stünde ein Erlös unter „Provision".
                art = "provision" if z["betrag"] < 0 else "erloes"
                raus.append({"datum": b["datum"], "art": art,
                             "text": z.get("kategorie") or z.get("notiz")
                             or ("Provision" if art == "provision" else "Erlös"),
                             "betrag": z["betrag"], "bewegung": b["id"],
                             # Seit B5 kann am Provisions-Posten der Monatsbeleg
                             # hängen. Daran hängt die Monatsprobe.
                             "beleg_id": (z.get("ziel_id") or ""
                                          if z["art"] == zuordnung.BELEG else "")})
        raus.append({"datum": b["datum"], "art": "auszahlung",
                     "text": "Auszahlung", "betrag": -round(b["betrag"], 2),
                     "bewegung": b["id"]})
    raus.sort(key=lambda x: (x["datum"], {"rechnung": 0, "erloes": 1,
                                          "provision": 2, "auszahlung": 3}[x["art"]]))
    return raus


def saldo(schluessel, von="", bis=""):
    """Was die Plattform nach den erfassten Zeilen noch schuldet.

    Null heißt: alles, was zugeordnet ist, geht auf. Das ist **nicht** dasselbe
    wie „alles erfasst“ – eine Auszahlung, die noch niemand angefasst hat,
    steht in voller Höhe im Saldo, eine Rechnung ohne Auszahlung dagegen gar
    nicht (siehe die Anmerkung unten).
    """
    return round(sum(z["betrag"] for z in zeilen(schluessel, von, bis)), 2)


# Was hier bewusst **nicht** steht: eine Liste „offene Rechnungen je Plattform".
# Sie wäre die naheliegende zweite Frage an ein Verrechnungskonto – schuldet die
# Plattform noch etwas? –, ließe sich aus dem Bestand aber nicht beantworten:
# der Vertriebskanal steht nicht an der Rechnung, sondern an der Buchung, und
# er kommt erst über die Zuordnung zur Auszahlung ans Konto. Eine Funktion, die
# stattdessen *alle* offenen Rechnungen zurückgibt, sähe nach einer Antwort aus
# und wäre keine. Bis der Kanal an der Rechnung steht, sagt der Saldo, dass
# etwas fehlt; welche Rechnung es ist, sagt die Vorschlagsliste (B3).


def uebersicht(von="", bis=""):
    """Je Plattform: Rechnungen, Provision, Auszahlung, Saldo – für die Anzeige."""
    raus = []
    for p in PLATTFORMEN:
        z = zeilen(p["schluessel"], von, bis)
        if not z:
            continue
        raus.append({
            "schluessel": p["schluessel"], "name": p["name"],
            "rechnungen": round(sum(x["betrag"] for x in z
                                    if x["art"] in ("rechnung", "erloes")), 2),
            "provision": round(sum(x["betrag"] for x in z if x["art"] == "provision"), 2),
            "auszahlung": round(sum(x["betrag"] for x in z if x["art"] == "auszahlung"), 2),
            "saldo": round(sum(x["betrag"] for x in z), 2),
            "zeilen": z})
    return raus


def monatsprobe(schluessel, monat, beleg_betrag):
    """Trifft die Summe der Provisionen eines Monats den Monatsbeleg?

    **Die Prüfung, die vorher fälschlich gegen Smoobu lief.** Diesmal gegen eine
    verlässliche Quelle: den Beleg, den die Plattform monatlich schickt und den
    auch das Steuerbüro verwendet. Weicht die Summe ab, fehlt an einer
    Auszahlung eine Rechnung – oder eine Auszahlung ist noch nicht zugeordnet.

    Gibt (summe, beleg, stimmt) zurück.
    """
    z = [x for x in zeilen(schluessel) if x["art"] == "provision"
         and (x["datum"] or "").startswith(monat)]
    summe = round(sum(x["betrag"] for x in z), 2)
    beleg = -abs(round(float(beleg_betrag or 0), 2))
    return summe, beleg, abs(summe - beleg) < 0.02


def monatsuebersicht(schluessel, von="", bis=""):
    """Je Monat: gebuchte Provision und – falls vorhanden – der Monatsbeleg.

    **Die Kontrolle, für die B4b noch die Zahl fehlte.** Booking und Airbnb
    schicken monatlich einen Provisionsbeleg; seit B5 hängt er an den
    Provisions-Posten der Auszahlungen. Deckt seine Summe die gebuchten Posten
    nicht, fehlt eine Auszahlung des Monats – oder an einer fehlt die Rechnung.

    Das ist die Prüfung, die vorher fälschlich gegen Smoobu lief. Diesmal gegen
    die Quelle, die auch das Steuerbüro verwendet.

    **Ohne Beleg wird nichts behauptet** (`beleg`/`stimmt` sind None). Ein
    Monat, dessen Beleg noch nicht da ist, ist kein Fehler – nur unfertig.
    """
    from app import buchhaltung

    je_monat = {}
    for zeile in zeilen(schluessel, von, bis):
        if zeile["art"] != "provision":
            continue
        m = (zeile["datum"] or "")[:7]
        je_monat.setdefault(m, {"monat": m, "provision": 0.0, "belege": set()})
        je_monat[m]["provision"] = round(je_monat[m]["provision"] + zeile["betrag"], 2)
        if zeile.get("beleg_id"):
            je_monat[m]["belege"].add(zeile["beleg_id"])

    raus = []
    for m in sorted(je_monat, reverse=True):
        w = je_monat[m]
        # Mehrere Belege in einem Monat sind möglich (Booking und ein Nachtrag);
        # verglichen wird gegen ihre Summe.
        betraege = [buchhaltung.betrag_zahl((db.holen("belege", i) or {}).get("amount"))
                    for i in sorted(w["belege"])]
        betraege = [x for x in betraege if x is not None]
        soll = -abs(round(sum(betraege), 2)) if betraege else None
        raus.append({"monat": m, "provision": w["provision"], "beleg": soll,
                     "stimmt": None if soll is None
                     else abs(w["provision"] - soll) < 0.02})
    return raus
