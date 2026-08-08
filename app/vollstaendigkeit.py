#!/usr/bin/env python3
"""Ist überhaupt alles da? (B8)

**Warum das der wichtigste Prüfstein ist.** Der Überblick (B7) zeigt Zahlen.
Ob sie etwas wert sind, hängt daran, ob *alle* Bewegungen erfasst sind – und
das sieht man ihnen nicht an. Ein fehlender Auszugsmonat macht keinen Fehler,
er macht ein **falsches, plausibel aussehendes Ergebnis**.

Drei Prüfungen, jede mit einer klaren Grenze:

* **Der Saldosprung.** Die Differenz zweier Kontostände muss der Summe der
  Bewegungen dazwischen entsprechen. Stimmt sie nicht, fehlen Bewegungen –
  man weiß nicht welche, aber man weiß *dass*. Möglich erst **ab dem zweiten
  Auszug** eines Kontos: vorher fehlt der Anfangswert.
* **Die Zeitraumlücke.** Decken die eingelesenen Auszüge einen durchgehenden
  Zeitraum ab? Überlappungen sind der Normalfall und keine Lücke.
* **Die offenen Arbeiten.** Restbeträge, fehlende Kategorien und Belege –
  verstreut vorhanden, hier an einer Stelle mit Zahl davor.

**Bewusst kein Ampel-Gesamturteil.** „Alles in Ordnung" wäre eine Behauptung
über Daten, die das Werkzeug nicht kennen kann – etwa ein zweites Konto, von
dem noch nie ein Auszug kam. Gezeigt wird, was geprüft wurde und was dabei
herauskam.
"""
from datetime import date, timedelta

from app import db, konto, zuordnung

TABELLE = "auszuege"


def _tag(text):
    try:
        j, m, t = str(text)[:10].split("-")
        return date(int(j), int(m), int(t))
    except (ValueError, AttributeError):
        return None


def merken(konto_name, kopf):
    """Die Kopfdaten eines Imports ablegen. Ohne Stichtag passiert nichts.

    Derselbe Auszug zweimal eingelesen ergibt **einen** Satz: der Schlüssel ist
    Konto plus Stichtag. Sonst stünde jede Wiederholung als weiterer Prüfpunkt
    da und der Saldovergleich vergliche einen Auszug mit sich selbst.
    """
    if not kopf or not kopf.get("bis") or kopf.get("stand") is None:
        return None
    sid = f"{konto_name}|{kopf['bis']}"
    satz = {"id": sid, "konto": konto_name, "von": kopf.get("von", ""),
            "bis": kopf["bis"], "stand": round(float(kopf["stand"]), 2),
            "erfasst": konto._jetzt()}
    db.speichern(TABELLE, sid, satz) if db.holen(TABELLE, sid) else \
        db.anlegen(TABELLE, satz, sid=sid)
    return satz


def auszuege(konto_name=""):
    """Alle erfassten Auszüge, ältester zuerst."""
    alle = db.alle(TABELLE)
    if konto_name:
        alle = [a for a in alle if a.get("konto") == konto_name]
    return sorted(alle, key=lambda a: (a.get("konto", ""), a.get("bis", "")))


def saldospruenge():
    """Wo die Summe der Bewegungen nicht zur Differenz der Kontostände passt.

    Je Konto werden aufeinanderfolgende Auszüge verglichen:

        Stand(neu) − Stand(alt)  ==  Σ Bewegungen im Zeitraum dazwischen

    Der Zeitraum beginnt am Tag **nach** dem alten Stichtag: dessen Bewegungen
    stecken bereits im alten Kontostand.
    """
    raus = []
    nach_konto = {}
    for a in auszuege():
        nach_konto.setdefault(a.get("konto", ""), []).append(a)
    for konto_name, liste in nach_konto.items():
        for alt, neu in zip(liste, liste[1:]):
            start = _tag(alt["bis"])
            if start is None:
                continue
            von = (start + timedelta(days=1)).isoformat()
            summe = round(sum(b.get("betrag", 0.0)
                              for b in konto.alle(von, neu["bis"], konto_name)), 2)
            erwartet = round(alt["stand"] + summe, 2)
            if abs(erwartet - neu["stand"]) < 0.005:
                continue
            raus.append({"konto": konto_name, "von": von, "bis": neu["bis"],
                         "vorher": alt["stand"], "bewegungen": summe,
                         "erwartet": erwartet, "gemeldet": neu["stand"],
                         "differenz": round(neu["stand"] - erwartet, 2)})
    return raus


def luecken():
    """Zeiträume zwischen zwei Auszügen, für die keiner vorliegt.

    Überlappende Auszüge sind der Normalfall (die Dublettenprüfung fängt sie
    ab) und ergeben keine Lücke.
    """
    raus = []
    nach_konto = {}
    for a in auszuege():
        if a.get("von") and a.get("bis"):
            nach_konto.setdefault(a.get("konto", ""), []).append(a)
    for konto_name, liste in nach_konto.items():
        # Nach Beginn sortieren: ein langer Auszug kann einen kurzen umschliessen.
        liste = sorted(liste, key=lambda a: a["von"])
        gedeckt_bis = None
        for a in liste:
            beginn, ende = _tag(a["von"]), _tag(a["bis"])
            if beginn is None or ende is None:
                continue
            if gedeckt_bis is not None and beginn > gedeckt_bis + timedelta(days=1):
                raus.append({"konto": konto_name,
                             "von": (gedeckt_bis + timedelta(days=1)).isoformat(),
                             "bis": (beginn - timedelta(days=1)).isoformat()})
            gedeckt_bis = max(gedeckt_bis, ende) if gedeckt_bis else ende
    return raus


def bewegungen_mit_rest():
    """Bewegungen, an denen ein Restbetrag offen steht – halb erledigt."""
    return [b for b in konto.alle()
            if not b.get("umbuchung") and zuordnung.hat_posten(b["id"])
            and not zuordnung.ist_fertig(b)]


def posten_ohne_kategorie():
    """Posten der Art „nur Kategorie" ohne Kategorie.

    Seit B6 können keine neuen mehr entstehen; die alten tauchen in keiner
    Auswertung auf und müssen deshalb benannt werden.
    """
    return [z for z in db.alle(zuordnung.TABELLE)
            if z.get("art") == zuordnung.KATEGORIE
            and not (z.get("kategorie") or "").strip()]


def unberuehrt():
    """Ausgaben, an denen noch gar nichts gemacht wurde.

    **Getrennt von `bewegungen_mit_rest`.** `konto.ohne_zuordnung` enthaelt
    beides – angefangene und unberuehrte. In einer Uebersicht nebeneinander
    zaehlte dieselbe Bewegung zweimal, und die Summe der Zahlen waere groesser
    als die Arbeit.
    """
    return [b for b in konto.ohne_zuordnung() if not zuordnung.hat_posten(b["id"])]


def offene_arbeiten():
    """Was noch zu tun ist – die verstreuten Listen an einer Stelle.

    Die Zahlen ueberschneiden sich **nicht**: eine angefangene Bewegung steht
    unter `rest`, eine unberuehrte unter `ohne_kategorie`.
    """
    return {"rest": len(bewegungen_mit_rest()),
            "ohne_kategorie": len(unberuehrt()),
            "ohne_beleg": len(konto.ohne_beleg()),
            "posten_ohne_kategorie": len(posten_ohne_kategorie())}


def befund():
    """Alles auf einen Blick – **ohne Gesamturteil**.

    `saldo_pruefbar` sagt, ob die Saldoprobe überhaupt laufen konnte. Ohne
    diesen Hinweis liest man „keine Saldosprünge" als „Saldo stimmt", und das
    wäre falsch, solange erst ein Auszug vorliegt.
    """
    a = auszuege()
    je_konto = {}
    for x in a:
        je_konto.setdefault(x.get("konto", ""), 0)
        je_konto[x["konto"]] += 1
    return {"auszuege": len(a),
            "konten": sorted(je_konto),
            "saldo_pruefbar": any(n > 1 for n in je_konto.values()),
            "saldospruenge": saldospruenge(),
            "luecken": luecken(),
            "kartenproben": [p for p in kartenproben()
                             if p["pruefbar"] and abs(p["differenz"]) >= 0.005],
            "karte_ohne_auszug": sammelbuchungen_ohne_karte(),
            "offene_arbeiten": offene_arbeiten()}


# Woran die beiden Seiten einer Kreditkartenabrechnung zu erkennen sind. Auf
# dem Girokonto heisst sie „Kreditkartenabrechnung", auf der Karte selbst
# „Ausgleich Kreditkarte" – zwei Namen fuer dieselbe Zahlung.
_AUSGLEICH = "ausgleich kreditkarte"
_ABRECHNUNG = "kreditkartenabrechnung"


def _ist(bewegung, marke):
    return marke in ((bewegung.get("text") or "")
                     + " " + (bewegung.get("gegenpartei") or "")).lower()


def kartenproben():
    """Deckt jeder Ausgleich genau die Kartenkäufe seit dem letzten? (B8)

    **Warum das die wichtigste Probe der Kreditkarte ist.** Auf dem Girokonto
    steht *eine* Sammelbuchung; im Kartenauszug stehen dieselben Beträge
    einzeln. Beide Umbuchungen sind neutral gestellt, die **Einzelkäufe tragen
    die Ausgabe**. Fehlt der Kartenauszug oder ist er unvollständig, fehlen
    genau diese Ausgaben im Ergebnis – ohne dass irgendwo etwas nicht aufgeht.

    Diese Probe macht es sichtbar:

        Ausgleich  ==  − Σ Käufe seit dem letzten Ausgleich

    **Der erste Zyklus ist nicht prüfbar.** Vor dem ersten Ausgleich fehlt der
    Anfangspunkt: seine Käufe können vor dem Importzeitraum liegen. An den
    echten Daten wich genau dieser eine um 22,00 € ab, die übrigen fünf trafen
    auf den Cent.
    """
    raus = []
    je_konto = {}
    for b in konto.alle():
        je_konto.setdefault(b.get("konto", ""), []).append(b)
    for konto_name, liste in je_konto.items():
        liste = sorted(liste, key=lambda b: b.get("datum", ""))
        ausgleiche = [b for b in liste
                      if b.get("umbuchung") and _ist(b, _AUSGLEICH)]
        if not ausgleiche:
            continue
        vorher = None
        for a in ausgleiche:
            kaeufe = [b for b in liste if not b.get("umbuchung")
                      and (vorher is None or b.get("datum", "") > vorher)
                      and b.get("datum", "") <= a.get("datum", "")]
            summe = round(sum(b.get("betrag", 0.0) for b in kaeufe), 2)
            raus.append({"konto": konto_name, "datum": a.get("datum", ""),
                         "ausgleich": round(a.get("betrag", 0.0), 2),
                         "kaeufe": summe, "anzahl": len(kaeufe),
                         "differenz": round(a.get("betrag", 0.0) + summe, 2),
                         "pruefbar": vorher is not None})
            vorher = a.get("datum", "")
    return raus


def sammelbuchungen_ohne_karte():
    """Abrechnungen auf dem Girokonto, zu denen kein Kartenauszug vorliegt.

    Die Frage aus dem Betrieb (8.8.2026): *auf dem Bankimport müsste es eine
    Sammelbuchung zu einem Kreditkartenbelegmonat geben.* Ist sie da und der
    Kartenauszug nicht, dann fehlen **alle Einzelausgaben dieses Monats** im
    Ergebnis – und nichts fällt auf, weil die Sammelbuchung neutral ist.

    Erkannt über den Betrag: zu jeder Abrechnung muss auf einem Kartenkonto ein
    Ausgleich in gleicher Höhe stehen.
    """
    ausgleiche = [round(abs(b.get("betrag", 0.0)), 2) for b in konto.alle()
                  if b.get("umbuchung") and _ist(b, _AUSGLEICH)]
    raus = []
    for b in konto.alle():
        if not b.get("umbuchung") or not _ist(b, _ABRECHNUNG):
            continue
        if round(abs(b.get("betrag", 0.0)), 2) in ausgleiche:
            continue
        raus.append(b)
    return raus
