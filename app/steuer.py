#!/usr/bin/env python3
"""Berechnung der Beherbergungssteuer Dresden (Satzung v. 7.5.2015).

Validiert gegen das amtliche Formular Dez 2025:
  verbleibende Übernachtungen = 137, Umsätze = 5.698,29 €, Steuer = 341,90 €.

Regeln (siehe Satzung + Vorgaben des Betreibers):
  * Monatszuordnung nach ABREISEdatum (§6: Steuer entsteht mit Abreise).
    Reicht eine Buchung in den Folgemonat, zählt sie im Folgemonat.
  * Nur BEREITS STATTGEFUNDENE Buchungen: Abreise <= heute. Geplante/künftige
    Buchungen werden nicht berechnet.
  * Übernachtungen = Personen (Erw.+Kinder) × Nächte.
  * Ausgeschlossen: Stornos (type "cancellation") und Blockierungen
    (is-blocked-booking).
  * Airbnb-Buchungen werden separat aus Smoobu berechnet und ausgewiesen –
    Airbnb meldet und führt die Steuer selbst an Dresden ab, daher fließen sie
    nicht in die steuerpflichtigen Umsätze ein.
  * Steuerbasis je Buchung = Buchungspreis OHNE die durchlaufende
    Übernachtungssteuer (Reinigungsgebühr bleibt enthalten). Die vom Gast
    gezahlte Übernachtungssteuer ist ein Durchlaufposten und wird nicht erneut
    besteuert. Der Smoobu-"price" ist IMMER brutto inklusive dieser Steuer:
      - steht sie als Zeile in "price-details" -> diesen Betrag abziehen,
      - fehlt die Zeile (Direktbuchungen immer, Booking.com zeitweise)
        -> price / 1,06 herausrechnen.
    Validiert gegen die erzeugten Gastrechnungen (siehe TestGastrechnungen).
  * Steuer = 6 % der steuerpflichtigen Umsätze, kaufmännisch gerundet.

Validiert gegen zwei Monate: Dez 2025 (5.698,29 € / 341,90 €) und
Mai 2026 (7.155,86 € Umsatz).
"""
import re
import calendar
from datetime import date

CANCELLED = "cancellation"


def _d(s):
    y, m, dd = (int(x) for x in s.split("-"))
    return date(y, m, dd)


def _pricedetail(price_details, label):
    """Betrag einer Zeile aus dem 'price-details'-Freitext ziehen, sonst 0.0."""
    m = re.search(label + r"\s*-\s*EUR\s*([0-9.,]+)", price_details or "")
    if not m:
        return 0.0
    return float(m.group(1).replace(",", ""))


def month_range(year, month):
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def ohne_citytax(booking, steuersatz=0.06, airbnb_channel="Airbnb"):
    """(Betrag ohne durchlaufende Beherbergungssteuer, enthaltene Steuer).

    Der Smoobu-"price" ist immer der Bruttobetrag INKLUSIVE der vom Gast
    gezahlten Beherbergungssteuer – die muss raus, sonst besteuern wir die
    Steuer. Steht sie als Zeile in "price-details", nehmen wir den echten
    Betrag (deckt auch ab, dass Booking.com für die Wernerstraße mit 7 %
    rechnet). Fehlt die Zeile – bei Direktbuchungen IMMER, bei Booking.com
    zeitweise auch – steckt sie trotzdem im Preis und wird herausgerechnet.
    Belegt durch Rechnung 60 (Anja Ernst, Direktbuchung): 400,07 € brutto =
    312,42 Übernachtung + 65,00 Reinigung + 22,65 Übernachtungssteuer;
    400,07 / 1,06 = 377,42 = genau die Basis der Rechnung.

    Eine einzige Stelle für diese Regel: die Steueranmeldung und die
    Auswertung (app/kennzahlen.py) müssen dieselbe Zahl bekommen.
    """
    price = float(booking.get("price") or 0.0)
    citytax = _pricedetail(booking.get("price-details"), "Übernachtungssteuer")
    is_airbnb = (booking.get("channel") or {}).get("name", "") == airbnb_channel
    if citytax or is_airbnb:
        return round(price - citytax, 2), round(citytax, 2)
    base = round(price / (1.0 + steuersatz), 2)
    return base, round(price - base, 2)


def classify(booking, year, month, airbnb_channel="Airbnb", today=None,
             steuersatz=0.06):
    """Eine Buchung für den Zielmonat aufbereiten oder None, wenn irrelevant.

    Relevanz: nicht storniert, nicht blockiert, gültiger Zeitraum, Abreise im
    Zielmonat UND Abreise bereits erfolgt (<= today).
    """
    if booking.get("is-blocked-booking"):
        return None
    if booking.get("type") == CANCELLED:
        return None
    arr_s, dep_s = booking.get("arrival"), booking.get("departure")
    if not arr_s or not dep_s:
        return None
    arr, dep = _d(arr_s), _d(dep_s)
    nights = (dep - arr).days
    if nights <= 0:
        return None
    if not (dep.year == year and dep.month == month):
        return None
    if today is not None and dep > today:
        return None  # Buchung hat noch nicht stattgefunden

    persons = (booking.get("adults") or 0) + (booking.get("children") or 0)
    price = float(booking.get("price") or 0.0)
    channel = (booking.get("channel") or {}).get("name", "")
    is_airbnb = channel == airbnb_channel
    base, citytax = ohne_citytax(booking, steuersatz=steuersatz,
                                 airbnb_channel=airbnb_channel)

    return {
        "id": booking.get("id"),
        "guest": booking.get("guest-name", ""),
        "apartment": (booking.get("apartment") or {}).get("name", ""),
        "channel": channel,
        "is_airbnb": is_airbnb,
        "arrival": arr_s,
        "departure": dep_s,
        "nights": nights,
        "adults": booking.get("adults") or 0,
        "children": booking.get("children") or 0,
        "persons": persons,
        "overnights": persons * nights,
        "price": round(price, 2),
        "citytax": round(citytax, 2),
        "base": round(base, 2),  # Preis ohne durchlaufende ÜN-Steuer
    }


def compute(bookings, year, month, *, steuersatz=0.06, airbnb_channel="Airbnb",
            steuerbefreite_umsaetze=0.0, airbnb_overnights_override=None,
            today=None):
    """Steuererklärung für (year, month) aus Roh-Buchungen berechnen.

    today: Stichtag für "bereits stattgefunden" (Default date.today()).
    Gibt ein Dict mit allen Formularwerten und der Einzelbuchungsliste zurück.
    """
    if today is None:
        today = date.today()
    rows = [c for c in (classify(b, year, month, airbnb_channel, today, steuersatz)
                        for b in bookings) if c]
    rows.sort(key=lambda r: (r["is_airbnb"], r["departure"], r["guest"]))

    remaining = [r for r in rows if not r["is_airbnb"]]
    airbnb = [r for r in rows if r["is_airbnb"]]

    remaining_on = sum(r["overnights"] for r in remaining)
    airbnb_on_smoobu = sum(r["overnights"] for r in airbnb)
    airbnb_on = airbnb_on_smoobu if airbnb_overnights_override is None else int(airbnb_overnights_override)

    remaining_umsatz = round(sum(r["base"] for r in remaining), 2)
    steuerpflichtig = round(remaining_umsatz - steuerbefreite_umsaetze, 2)
    steuer = round(steuerpflichtig * steuersatz, 2)

    return {
        "year": year,
        "month": month,
        "steuersatz": steuersatz,
        # Formularfelder (Seite 2):
        "uebernachtungen_insgesamt": remaining_on + airbnb_on,
        "uebernachtungen_airbnb": airbnb_on,
        "uebernachtungen_airbnb_smoobu": airbnb_on_smoobu,
        "uebernachtungen_verbleibend": remaining_on,
        "umsatz_verbleibend": remaining_umsatz,
        "umsatz_steuerbefreit": round(steuerbefreite_umsaetze, 2),
        "umsatz_steuerpflichtig": steuerpflichtig,
        "beherbergungssteuer": steuer,
        # Detail:
        "rows": rows,
        "remaining_rows": remaining,
        "airbnb_rows": airbnb,
    }
