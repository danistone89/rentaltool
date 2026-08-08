#!/usr/bin/env python3
"""Eine Portal-Auszahlung in einem Zug zuordnen (B11d).

**Wozu.** Bis hierher war die Zuordnung einer Sammelauszahlung Handarbeit: eine
Bewegung über 859,89 €, dahinter zwei Reservierungen, deren Rechnungen zusammen
985,95 € ausmachen – und die Differenz ist die einbehaltene Provision. Welche
zwei Rechnungen das sind, stand nirgends. Man suchte sie aus einer Liste
offener Rechnungen zusammen, bis der Rest ungefähr wie eine Provision aussah.

Mit dem Auszahlungsbericht (B11b/c) steht es fest. Die Kette:

    Bankbewegung → Auszahlung → Reservierungsnummer → Smoobu-Buchung → Rechnung

Dieses Modul geht sie entlang und legt vor, was es tun würde. **Geschrieben
wird erst auf Zuruf** – und nur, was belegt ist.

**Was gebucht wird und warum.** Je Reservierung ein Posten über den
*Rechnungsbetrag*, nicht über den Auszahlungsanteil. Sonst wäre der Umsatz um
die Provision zu niedrig und die Provision tauchte als Ausgabe nie auf. Was
dann noch fehlt, bis die Bewegung aufgeht, **ist** die einbehaltene Provision –
und der Bericht sagt, wie hoch sie sein müsste. Weichen die beiden Zahlen
voneinander ab, wird das gezeigt statt geglättet: dann stimmt eine Rechnung
nicht mit dem überein, was das Portal abgerechnet hat.

**Nichts wird geraten.** Eine Reservierung ohne Rechnung wird übersprungen, und
solange eine fehlt, entsteht kein Provisionsposten – der Rest wäre dann nicht
nur Provision. Die Bewegung bleibt offen und damit sichtbar.
"""
from app import db, portalbericht, rechnung, zuordnung


def _rechnungen_nach_buchung():
    """Rechnung je Smoobu-Buchung. Entwürfe zählen nicht – sie sind nie
    hinausgegangen, und eine Auszahlung bezahlt keinen Entwurf."""
    raus = {}
    for r in db.alle(rechnung.TABELLE):
        if not r.get("buchung") or r.get("status") == rechnung.ENTWURF:
            continue
        raus.setdefault(str(r["buchung"]), r)
    return raus


def _nach_referenz(buchungen):
    """Smoobu-Buchung je Reservierungsnummer des Portals.

    `reference-id` ist bei Booking die zehnstellige Reservierungsnummer, bei
    Airbnb der Bestätigungscode `HM…` – in beiden Fällen genau das, was im
    Auszahlungsbericht steht.
    """
    raus = {}
    for b in (buchungen or {}).values():
        ref = str(b.get("reference-id") or "").strip()
        if ref:
            raus.setdefault(ref, b)
    return raus


def _brutto(r):
    return round((r.get("summen") or {}).get("brutto", 0.0), 2)


def vorschau(bewegung, buchungen=None):
    """Was eine Übernahme tun würde – ohne etwas zu schreiben. None ohne Bericht.

    Je Reservierung eine Zeile mit dem, was gefunden wurde, und dem Grund, wenn
    nichts gefunden wurde. Ein Vorschlag, den man nicht nachvollziehen kann,
    wird entweder blind übernommen oder ignoriert – beides ist schlecht.
    """
    a = portalbericht.zu_bewegung(bewegung)
    if not a:
        return None
    nach_ref = _nach_referenz(buchungen)
    nach_buchung = _rechnungen_nach_buchung()

    zeilen, summe = [], 0.0
    for r in a.get("reservierungen", []):
        nummer = str(r.get("nummer") or "")
        b = nach_ref.get(nummer)
        rech = nach_buchung.get(str(b.get("id"))) if b else None
        schon = (zuordnung.bewegung_zu(zuordnung.RECHNUNG, rech["id"])
                 if rech else "")
        zeile = {"reservierung": r, "buchung": b, "rechnung": rech,
                 "betrag": _brutto(rech) if rech else 0.0,
                 "schon": schon, "problem": ""}
        if not b:
            zeile["problem"] = "Reservierung nicht in Smoobu gefunden"
        elif not rech:
            zeile["problem"] = "zu dieser Buchung gibt es noch keine Rechnung"
        elif schon and schon != bewegung.get("id"):
            zeile["problem"] = "Rechnung hängt schon an einer anderen Bewegung"
        elif schon:
            zeile["problem"] = "schon zugeordnet"
        else:
            summe += zeile["betrag"]
        zeilen.append(zeile)

    summe = round(summe, 2)
    offen = round(bewegung.get("betrag", 0.0) - zuordnung.summe(bewegung["id"])
                  - summe, 2)
    laut_bericht = round(sum(r.get("provision", 0.0) + r.get("gebuehr", 0.0)
                             for r in a.get("reservierungen", [])), 2)
    vollstaendig = all(not z["problem"] or z["problem"] == "schon zugeordnet"
                       for z in zeilen)
    return {
        "auszahlung": a, "zeilen": zeilen,
        # Was neu gebucht würde, und was danach noch offen bliebe.
        "rechnungssumme": summe, "rest": offen,
        # Was das Portal laut eigenem Bericht einbehalten hat. Beides muss
        # zusammenpassen; tut es das nicht, weicht eine Rechnung von dem ab,
        # was abgerechnet wurde.
        "laut_bericht": laut_bericht,
        # Zwei verschiedene Arten von Abweichung, und sie brauchen verschiedene
        # Antworten (beide am Bestand vom 8.8.2026 aufgetreten):
        #
        # `weicht_ab` – es bliebe WENIGER uebrig, als das Portal einbehalten
        # hat. Die Rechnung ist niedriger als das, was das Portal dem Gast
        # berechnet hat; bei den uebernommenen Smoobu-Rechnungen ist das die
        # Beherbergungssteuer, die dort nicht auf der Rechnung stand. Die
        # Rechnungen gehoeren trotzdem an diese Auszahlung – nur der Rest ist
        # dann nicht bloss Provision und darf nicht so gebucht werden.
        #
        # `deckt_nicht` – es bliebe MEHR einbehalten, als das Portal sagt. Dann
        # bezahlt diese Auszahlung die Rechnungen gar nicht: Airbnb zahlt einen
        # langen Aufenthalt in Monatsraten aus (86 Naechte, 6.102,99 EUR in drei
        # Raten). Hier waere die Zuordnung schlicht falsch – 4.540 EUR haetten
        # unter „Provision" gestanden.
        "weicht_ab": vollstaendig and offen - laut_bericht >= 0.02,
        "deckt_nicht": vollstaendig and offen - laut_bericht <= -0.02,
        "vollstaendig": vollstaendig,
        "kategorie": provisionskategorie(),
    }


def provisionskategorie():
    """Welche Kategorie der Betrieb zuletzt für eine einbehaltene Provision
    verwendet hat – '' beim ersten Mal.

    Es gibt dafür **keine** Vorgabe: die Vorgabekategorien sind wörtlich die
    SUMIF-Kriterien des Buchhaltungs-Workbooks, und eine dazuerfundene liefe
    still ins Leere. Statt eine zu erfinden, merkt sich das Werkzeug die, die
    schon einmal an einem Provisionsposten stand.
    """
    letzte = ""
    for z in sorted(db.alle(zuordnung.TABELLE), key=lambda z: z.get("angelegt", "")):
        if z.get("art") == zuordnung.KATEGORIE and z.get("betrag", 0) < 0 \
                and z.get("kategorie") and z.get("notiz", "").startswith("Provision"):
            letzte = z["kategorie"]
    return letzte


def uebernehmen(bewegung, kategorie="", buchungen=None):
    """Die Vorschau schreiben. Gibt (angelegt, meldung) zurück.

    Übersprungen wird alles, was ein Problem trägt. Der Provisionsposten
    entsteht nur, wenn **jede** Reservierung ihre Rechnung hat – sonst wäre der
    Rest nicht nur Provision, sondern auch eine fehlende Rechnung, und die
    verschwände unter der falschen Kategorie.
    """
    v = vorschau(bewegung, buchungen)
    if not v:
        return 0, "Zu dieser Bewegung gibt es keine Auszahlung im Bericht."
    if v["deckt_nicht"]:
        return 0, ("Diese Auszahlung deckt die gefundenen Rechnungen nicht – "
                   f"es blieben {v['rest']:.2f} € einbehalten, laut Bericht "
                   f"sind es {v['laut_bericht']:.2f} €. Meist ist es ein langer "
                   "Aufenthalt, den das Portal in Raten auszahlt: dann gehört "
                   "je Rate ein Teilbetrag der Rechnung dazu, von Hand.")
    angelegt = []
    with db.transaktion():
        for z in v["zeilen"]:
            if z["problem"] or not z["rechnung"]:
                continue
            satz, _ = zuordnung.hinzufuegen(
                bewegung["id"], zuordnung.RECHNUNG, z["betrag"],
                ziel_id=z["rechnung"]["id"], bewegung=bewegung,
                notiz=f"Rechnung {z['rechnung'].get('nummer') or ''} "
                      f"· Auszahlung {v['auszahlung']['schluessel']}".strip())
            if satz:
                angelegt.append(satz)
        rest = round(v["rest"], 2)
        # `kategorie` steht hier als ausgesprochene Voraussetzung, obwohl
        # `zuordnung.hinzufuegen` einen Posten ohne Kategorie ohnehin abweist –
        # ein Posten, der nur einen Betrag traegt, steht in keiner Auswertung.
        if v["vollstaendig"] and not v["weicht_ab"] and kategorie \
                and abs(rest) >= zuordnung.GENAU:
            satz, _ = zuordnung.hinzufuegen(
                bewegung["id"], zuordnung.KATEGORIE, rest, kategorie=kategorie,
                bewegung=bewegung,
                notiz=f"Provision {v['auszahlung']['schluessel']}")
            if satz:
                angelegt.append(satz)

    teile = [f"{len(angelegt)} Posten angelegt"]
    fehlend = [z for z in v["zeilen"] if z["problem"]
               and z["problem"] != "schon zugeordnet"]
    if fehlend:
        teile.append(f"{len(fehlend)} Reservierungen ohne Rechnung – "
                     "der Rest bleibt offen")
    elif not kategorie and abs(v["rest"]) >= zuordnung.GENAU:
        teile.append("die Provision braucht noch eine Kategorie")
    if v["weicht_ab"]:
        teile.append(f"Achtung: laut Bericht {v['laut_bericht']:.2f} € "
                     f"Provision, hier bleiben {v['rest']:.2f} € – der Rest ist "
                     "nicht nur Provision und wurde deshalb nicht gebucht")
    return len(angelegt), " · ".join(teile)
