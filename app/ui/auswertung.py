#!/usr/bin/env python3
"""Kennzahlen-Blatt: was die Wohnungen einbringen und was sie kosten.

Die Rechnung steht in `app/kennzahlen.py` – hier wird sie nur gezeigt. Ein
Monat, eine Tabelle, darüber vier Zahlen, darunter die teuersten Reinigungen.

Bewusst nüchtern: keine Diagramme, keine Farbverläufe. Bei zwei bis fünfzehn
Wohnungen ist eine Tabelle schneller zu lesen als jedes Bild, und eine Zahl,
die man abschreiben kann, ist mehr wert als eine, die man aus einem Balken
schätzt.
"""
from datetime import date

from nicegui import ui

from app import bookings, data, kennzahlen, receipts, timetrack
from app.ui.basis import (CFG, USERS, _apts, _eur, _has_rates, _rate_defaults, t)

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]


def _prozent(anteil):
    return f"{anteil * 100:.0f} %"


def _stunden(minuten):
    return f"{minuten // 60}:{minuten % 60:02d} h"


def _buchungen_des_monats(jahr, monat):
    """Alle Buchungen, die den Monat berühren – auch die über den Rand.

    Der Zeitraum wird großzügig gewählt: eine Buchung vom 25. des Vormonats bis
    zum 3. bringt Nächte in diesen Monat, taucht in einer Monatsabfrage aber
    nicht auf.
    """
    von = date(jahr, monat, 1)
    bis = date(jahr + (monat == 12), (monat % 12) + 1, 1)
    from datetime import timedelta
    return data._reservations((von - timedelta(days=62)).isoformat(),
                              (bis + timedelta(days=2)).isoformat())


def block():
    """Der Reiter „Kennzahlen" in der Übersicht."""
    heute = date.today()
    stand = {"jahr": heute.year, "monat": heute.month}
    rumpf = ui.column().classes("w-full gap-3")

    def zeichnen():
        rumpf.clear()
        with rumpf:
            try:
                _inhalt(stand)
            except Exception as ex:      # Smoobu weg, Daten unvollständig …
                ui.label(t("Kennzahlen nicht verfügbar: {fehler}", fehler=ex)) \
                    .classes("text-sm text-red-700")

    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
        j = ui.select(list(range(heute.year - 3, heute.year + 1)), value=stand["jahr"],
                      label="Jahr").props("dense outlined").classes("w-[110px]")
        m = ui.select({i + 1: MONATE[i] for i in range(12)}, value=stand["monat"],
                      label="Monat").props("dense outlined").classes("w-[150px]")
        j.on_value_change(lambda e: (stand.update(jahr=e.value), zeichnen()))
        m.on_value_change(lambda e: (stand.update(monat=e.value), zeichnen()))
        ui.space()
        ui.button(icon="refresh", on_click=lambda: (data.clear_cache(), zeichnen())) \
            .props("flat round").tooltip("Frisch von Smoobu laden")
    zeichnen()
    return rumpf


def _kachel(label, wert, zusatz="", icon="insights", ton="text-primary"):
    with ui.card().classes("rounded-xl shadow-sm border border-slate-100 p-3 gap-0 "
                           "items-start min-w-[150px] flex-grow"):
        with ui.row().classes("items-center gap-1"):
            ui.icon(icon).classes(ton + " text-lg")
            ui.label(label).classes("text-xs text-gray-500")
        ui.label(wert).classes("text-2xl font-bold text-slate-800 leading-tight")
        if zusatz:
            ui.label(zusatz).classes("text-xs text-gray-400")


def _inhalt(stand):
    jahr, monat = stand["jahr"], stand["monat"]
    apts = _apts()
    buchungen = _buchungen_des_monats(jahr, monat)
    zeiten = timetrack.entries()
    belege = receipts.list_receipts(2000)
    ergebnis = kennzahlen.monat(jahr, monat, buchungen, zeiten, belege, apts,
                                USERS, _rate_defaults(),
                                steuersatz=float(CFG.get("steuersatz", 0.06)),
                                airbnb_channel=CFG.get("airbnb_channel_name", "Airbnb"))
    s = ergebnis["summe"]

    with ui.row().classes("w-full gap-2 flex-wrap"):
        _kachel("Auslastung", _prozent(s["auslastung"]),
                f"{s['naechte']} von {s['verfuegbar']} Nächten", "hotel")
        _kachel("Umsatz", _eur(s["umsatz"]),
                f"{_eur(s['umsatz_je_nacht'])} je Nacht", "payments")
        if _has_rates():
            _kachel("Reinigung", _eur(s["reinigung_kosten"]),
                    _stunden(s["reinigung_minuten"]), "cleaning_services", "text-amber-600")
        else:
            _kachel("Reinigung", _stunden(s["reinigung_minuten"]),
                    "keine Stundensätze hinterlegt", "cleaning_services", "text-amber-600")
        _kachel("Material", _eur(s["material"]), "aus den Belegen", "shopping_cart",
                "text-amber-600")
        _kachel("Deckungsbeitrag", _eur(s["deckungsbeitrag"]),
                "Umsatz − Reinigung − Material", "savings",
                "text-green-600" if s["deckungsbeitrag"] >= 0 else "text-red-600")

    ui.label("Je Wohnung").classes("text-sm font-semibold text-gray-500 mt-2")
    spalten = [
        {"name": "wohnung", "label": "Wohnung", "field": "wohnung", "align": "left"},
        {"name": "auslastung", "label": "Auslastung", "field": "auslastung_txt", "align": "right"},
        {"name": "naechte", "label": "Nächte", "field": "naechte", "align": "right"},
        {"name": "buchungen", "label": "Buchungen", "field": "buchungen", "align": "right"},
        {"name": "umsatz", "label": "Umsatz", "field": "umsatz_txt", "align": "right"},
        {"name": "jenacht", "label": "je Nacht", "field": "je_nacht_txt", "align": "right"},
        {"name": "reinigung", "label": "Reinigung", "field": "reinigung_txt", "align": "right"},
        {"name": "material", "label": "Material", "field": "material_txt", "align": "right"},
        {"name": "db", "label": "Deckungsbeitrag", "field": "db_txt", "align": "right"},
    ]
    reihen = []
    for z in ergebnis["zeilen"] + [s]:
        reihen.append({
            "wohnung": z["wohnung"],
            "auslastung_txt": _prozent(z["auslastung"]),
            "naechte": z["naechte"], "buchungen": z.get("buchungen", 0),
            "umsatz_txt": _eur(z["umsatz"]),
            "je_nacht_txt": _eur(z["umsatz_je_nacht"]),
            "reinigung_txt": (_eur(z["reinigung_kosten"]) if _has_rates()
                              else _stunden(z["reinigung_minuten"])),
            "material_txt": _eur(z["material"]),
            "db_txt": _eur(z["deckungsbeitrag"]),
        })
    ui.table(columns=spalten, rows=reihen, row_key="wohnung") \
        .props("flat dense bordered").classes("w-full").mark("kennzahlen-tabelle")

    with ui.row().classes("w-full items-start gap-2 no-wrap text-xs text-gray-500 mt-1"):
        ui.icon("info").classes("text-gray-400 text-base shrink-0 mt-0.5")
        ui.label("Umsatz ohne die durchlaufende Beherbergungssteuer – dieselbe "
                 "Regel wie in der Steueranmeldung. Nächte über den Monatswechsel "
                 "zählen dort, wo sie liegen; die Steueranmeldung ordnet dagegen "
                 "die ganze Buchung dem Abreisemonat zu (§ 6). Der Deckungsbeitrag "
                 "ist kein Gewinn: Portalprovisionen, Nebenkosten, Abschreibung "
                 "und die eigene Arbeitszeit stecken nicht darin.")

    _teuerste_reinigungen(zeiten, buchungen)


def _teuerste_reinigungen(zeiten, buchungen):
    """Was jede Reinigung gekostet hat – die Frage, für die es bisher Zettel
    und Stift brauchte."""
    liste = kennzahlen.reinigung_je_buchung(zeiten, buchungen, USERS, _rate_defaults())
    if not liste:
        return
    ui.label("Reinigungen mit erfasster Zeit").classes(
        "text-sm font-semibold text-gray-500 mt-3")
    teuerste = sorted(liste, key=lambda x: x[2], reverse=True)[:10]
    for b, minuten, kosten in teuerste:
        with ui.row().classes("w-full items-center gap-2 no-wrap text-sm border-b "
                              "border-slate-100 py-1"):
            ui.icon("cleaning_services").classes("text-gray-400 text-base")
            with ui.column().classes("gap-0 min-w-0 flex-grow"):
                ui.label((b.get("apartment") or {}).get("name", "")) \
                    .classes("truncate")
                ui.label(f"{b.get('departure', '')} · "
                         + (bookings.assignee_of(b.get("id")) or "—")) \
                    .classes("text-xs text-gray-500")
            ui.label(_stunden(minuten)).classes("text-xs text-gray-500 shrink-0")
            ui.label(_eur(kosten) if _has_rates() else "").classes(
                "font-medium shrink-0 w-[80px] text-right")
