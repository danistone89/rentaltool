#!/usr/bin/env python3
"""Was die Wohnungen einbringen – und was sie kosten.

Die Zahlen dafür lagen längst da, nur nebeneinander: Buchungen in Smoobu,
Arbeitszeiten im Zeitkonto, Belege in der Ablage. Zusammengeführt hat sie
niemand, und damit blieb die einfachste Frage offen: **was bleibt bei einer
Wohnung im Monat übrig?**

Vier Größen je Wohnung und Monat:

* **Auslastung** – belegte Nächte geteilt durch die Nächte des Monats.
* **Umsatz** – Rechnungsbetrag ohne die durchlaufende Beherbergungssteuer
  (dieselbe Regel wie in der Steueranmeldung, `steuer.ohne_citytax`).
* **Reinigungskosten** – erfasste Arbeitszeit × Stundensatz des Mitarbeiters.
* **Material** – Belege, die dieser Wohnung zugeordnet sind.

Daraus **Deckungsbeitrag = Umsatz − Reinigung − Material**. Das ist bewusst
*nicht* „Gewinn": Zinsen, Abschreibung, Nebenkosten, Portalprovisionen und die
eigene Arbeitszeit stecken nicht drin. Die Zahl beantwortet „trägt diese
Wohnung ihren laufenden Betrieb?", nicht „was verdiene ich?".

**Übernachtungen werden auf die Monate aufgeteilt**, in denen sie liegen: eine
Buchung vom 29.10. bis 2.11. bringt drei Nächte in den Oktober und zwei in den
November, und der Umsatz wird im selben Verhältnis geteilt. Die Steueranmeldung
rechnet anders (ganze Buchung nach Abreisemonat, §6 der Satzung) – das ist kein
Widerspruch, sondern eine andere Frage. Wer beide Zahlen nebeneinanderlegt und
Gleichheit erwartet, sucht lange.
"""
from calendar import monthrange
from datetime import date, timedelta

from app import feiertage, steuer, timetrack


def _d(iso):
    return date.fromisoformat(iso[:10])


def monatstage(jahr, monat):
    return monthrange(jahr, monat)[1]


def naechte_je_monat(buchung):
    """{"JJJJ-MM": nächte} – Nächte dort, wo sie tatsächlich anfallen.

    Gezählt wird die **Nacht**, nicht der Tag: Anreise 29.10., Abreise 1.11.
    sind drei Nächte (29., 30., 31.), alle im Oktober.
    """
    if buchung.get("is-blocked-booking") or buchung.get("type") == "cancellation":
        return {}
    arr, dep = buchung.get("arrival"), buchung.get("departure")
    if not (arr and dep):
        return {}
    a, b = _d(arr), _d(dep)
    out = {}
    tag = a
    while tag < b:
        schluessel = f"{tag.year:04d}-{tag.month:02d}"
        out[schluessel] = out.get(schluessel, 0) + 1
        tag += timedelta(days=1)
    return out


def umsatz_je_monat(buchung, steuersatz=0.06, airbnb_channel="Airbnb"):
    """{"JJJJ-MM": betrag} – Umsatz im Verhältnis der Nächte des Monats."""
    naechte = naechte_je_monat(buchung)
    gesamt = sum(naechte.values())
    if not gesamt:
        return {}
    netto, _steuer = steuer.ohne_citytax(buchung, steuersatz, airbnb_channel)
    out = {m: round(netto * n / gesamt, 2) for m, n in naechte.items()}
    # Rundungsreste dem größten Monat zuschlagen, damit die Summe stimmt.
    rest = round(netto - sum(out.values()), 2)
    if rest and out:
        groesster = max(out, key=lambda m: (naechte[m], m))
        out[groesster] = round(out[groesster] + rest, 2)
    return out


def _betrag(text):
    """„12,34" oder „12.34" -> 12.34; alles andere -> 0.0."""
    roh = str(text or "").strip().replace("€", "").replace(" ", "")
    if not roh:
        return 0.0
    roh = roh.replace(".", "").replace(",", ".") if "," in roh else roh
    try:
        return round(float(roh), 2)
    except ValueError:
        return 0.0


def reinigungskosten(zeiten, jahr, monat, users=None, defaults=None, buchung_wohnung=None):
    """{wohnung: {"minuten": m, "kosten": €}} für den Kalendermonat.

    Zugeordnet wird über die Buchung (genau) und ersatzweise über den am
    Zeiteintrag vermerkten Wohnungsnamen. Ein Einsatz zählt zum Tag des
    Check-in – ein über Mitternacht laufender Einsatz also vollständig zum
    Anfangstag, wie in der Zeiterfassung auch.
    """
    buchung_wohnung = buchung_wohnung or {}
    out = {}
    for e in zeiten:
        if not e.get("checkout"):
            continue
        tag = _d(e["checkin"])
        if (tag.year, tag.month) != (jahr, monat):
            continue
        wohnung = buchung_wohnung.get(str(e.get("booking_id"))) or e.get("apartment") or ""
        if not wohnung:
            continue
        minuten = timetrack.duration_minutes(e) or 0
        satz = timetrack.rate_for(feiertage.kind_of(tag), (users or {}).get(e["user"]),
                                  defaults)
        eintrag = out.setdefault(wohnung, {"minuten": 0, "kosten": 0.0})
        eintrag["minuten"] += minuten
        eintrag["kosten"] = round(eintrag["kosten"] + timetrack.amount(minuten, satz), 2)
    return out


def material(belege, jahr, monat, apts=None):
    """{wohnung: betrag} für den Kalendermonat.

    Belege ohne Wohnung landen unter „ohne Zuordnung" statt still verteilt zu
    werden: eine erfundene Aufteilung sähe genauer aus, als sie ist.
    """
    apts = apts or {}
    out = {}
    for r in belege:
        ts = r.get("ts") or ""
        if len(ts) < 7 or (int(ts[:4]), int(ts[5:7])) != (jahr, monat):
            continue
        betrag = _betrag(r.get("amount"))
        if not betrag:
            continue
        name = r.get("apartment_name") or apts.get(r.get("apartment_id")) or "ohne Zuordnung"
        out[name] = round(out.get(name, 0.0) + betrag, 2)
    return out


def monat(jahr, monat_nr, buchungen, zeiten, belege, apts,
          users=None, defaults=None, steuersatz=0.06, airbnb_channel="Airbnb"):
    """Kennzahlen je Wohnung + Summenzeile für einen Kalendermonat.

    `apts`: {id: name} der Wohnungen – bestimmt auch, welche Zeilen erscheinen
    (eine Wohnung ohne Buchungen ist eine Aussage, keine Leerstelle).
    """
    schluessel = f"{jahr:04d}-{monat_nr:02d}"
    tage = monatstage(jahr, monat_nr)
    namen = {str(i): n for i, n in apts.items()}

    zeilen = {n: {"wohnung": n, "naechte": 0, "verfuegbar": tage, "auslastung": 0.0,
                  "umsatz": 0.0, "buchungen": 0, "gaeste_naechte": 0,
                  "reinigung_minuten": 0, "reinigung_kosten": 0.0,
                  "material": 0.0, "deckungsbeitrag": 0.0}
              for n in apts.values()}

    buchung_wohnung = {}
    for b in buchungen:
        wohnung = (b.get("apartment") or {}).get("name", "")
        buchung_wohnung[str(b.get("id"))] = wohnung
        naechte = naechte_je_monat(b).get(schluessel, 0)
        if not naechte or wohnung not in zeilen:
            continue
        z = zeilen[wohnung]
        z["naechte"] += naechte
        z["buchungen"] += 1
        z["gaeste_naechte"] += naechte * ((b.get("adults") or 0) + (b.get("children") or 0))
        z["umsatz"] = round(z["umsatz"] + umsatz_je_monat(
            b, steuersatz, airbnb_channel).get(schluessel, 0.0), 2)

    for wohnung, werte in reinigungskosten(zeiten, jahr, monat_nr, users, defaults,
                                           buchung_wohnung).items():
        z = zeilen.setdefault(wohnung, {"wohnung": wohnung, "naechte": 0,
                                        "verfuegbar": tage, "auslastung": 0.0,
                                        "umsatz": 0.0, "buchungen": 0,
                                        "gaeste_naechte": 0, "reinigung_minuten": 0,
                                        "reinigung_kosten": 0.0, "material": 0.0,
                                        "deckungsbeitrag": 0.0})
        z["reinigung_minuten"] += werte["minuten"]
        z["reinigung_kosten"] = round(z["reinigung_kosten"] + werte["kosten"], 2)

    for wohnung, betrag in material(belege, jahr, monat_nr, namen).items():
        z = zeilen.setdefault(wohnung, {"wohnung": wohnung, "naechte": 0,
                                        "verfuegbar": 0, "auslastung": 0.0,
                                        "umsatz": 0.0, "buchungen": 0,
                                        "gaeste_naechte": 0, "reinigung_minuten": 0,
                                        "reinigung_kosten": 0.0, "material": 0.0,
                                        "deckungsbeitrag": 0.0})
        z["material"] = round(z["material"] + betrag, 2)

    for z in zeilen.values():
        z["auslastung"] = round(z["naechte"] / z["verfuegbar"], 4) if z["verfuegbar"] else 0.0
        z["deckungsbeitrag"] = round(z["umsatz"] - z["reinigung_kosten"] - z["material"], 2)
        z["umsatz_je_nacht"] = round(z["umsatz"] / z["naechte"], 2) if z["naechte"] else 0.0

    reihen = sorted(zeilen.values(), key=lambda z: z["wohnung"])
    summe = {"wohnung": "Gesamt", "verfuegbar": sum(z["verfuegbar"] for z in reihen)}
    for feld in ("naechte", "buchungen", "gaeste_naechte", "reinigung_minuten"):
        summe[feld] = sum(z[feld] for z in reihen)
    for feld in ("umsatz", "reinigung_kosten", "material", "deckungsbeitrag"):
        summe[feld] = round(sum(z[feld] for z in reihen), 2)
    summe["auslastung"] = (round(summe["naechte"] / summe["verfuegbar"], 4)
                           if summe["verfuegbar"] else 0.0)
    summe["umsatz_je_nacht"] = (round(summe["umsatz"] / summe["naechte"], 2)
                                if summe["naechte"] else 0.0)
    return {"periode": schluessel, "zeilen": reihen, "summe": summe}


def reinigung_je_buchung(zeiten, buchungen, users=None, defaults=None):
    """[(buchung, minuten, kosten)] – was jede Reinigung gekostet hat.

    Die Frage „was kostet mich eine Reinigung in der Wernerstraße?" ließ sich
    bisher nur mit Zettel und Stift beantworten.
    """
    je_buchung = {}
    for e in zeiten:
        if not e.get("checkout") or not e.get("booking_id"):
            continue
        minuten = timetrack.duration_minutes(e) or 0
        satz = timetrack.rate_for(timetrack.kind_of(e), (users or {}).get(e["user"]),
                                  defaults)
        bid = str(e["booking_id"])
        vorher = je_buchung.get(bid, (0, 0.0))
        je_buchung[bid] = (vorher[0] + minuten,
                           round(vorher[1] + timetrack.amount(minuten, satz), 2))
    out = []
    for b in buchungen:
        werte = je_buchung.get(str(b.get("id")))
        if werte:
            out.append((b, werte[0], werte[1]))
    return sorted(out, key=lambda x: x[0].get("departure", ""), reverse=True)
