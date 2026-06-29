#!/usr/bin/env python3
"""NiceGUI-Oberfläche für die Beherbergungssteuer-App.

Start:  python3 app/web.py   (Port aus config.json, Default 3001)
Öffnen: http://localhost:3001/

Reines Python-Frontend (NiceGUI). Fachlogik unverändert in
smoobu.py / steuer.py / pdf_form.py; Glue in data.py.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nicegui import app, ui  # noqa: E402

from app import data, smoobu  # noqa: E402
try:
    from app import pdf_form
except Exception:  # PyMuPDF optional
    pdf_form = None

CFG = data.CONFIG

# Apartments einmalig laden (selten geändert)
_APARTMENTS = {}


def _load_apartments():
    if not _APARTMENTS:
        try:
            for a in data.get_apartments():
                _APARTMENTS[a["id"]] = a["name"]
        except smoobu.SmoobuError as ex:
            ui.notify(f"Smoobu: {ex}", type="negative", timeout=8000)
    return _APARTMENTS


# ---------------------------------------------------------------- Webhook
@app.post("/api/smoobu/webhook")
async def smoobu_webhook():
    data.clear_cache()
    return {"ok": True}


# ---------------------------------------------------------------- Einstellungen
def open_settings():
    betr = CFG.setdefault("betreiber", {})
    with ui.dialog() as dialog, ui.card().classes("w-[680px] max-w-full"):
        ui.label("⚙️ Einstellungen").classes("text-xl font-bold")
        ui.label("Betreiberdaten (erscheinen im PDF)").classes("text-sm text-gray-500 mt-2")
        inputs = {}
        with ui.grid(columns=2).classes("w-full gap-3"):
            for key, lbl in data.BETREIBER_FIELDS:
                inputs[key] = ui.input(lbl, value=betr.get(key, "")).classes("w-full")
        ui.label("PDF & Steuer").classes("text-sm text-gray-500 mt-3")
        with ui.grid(columns=2).classes("w-full gap-3"):
            sig_x = ui.number("Unterschrift X (pt, größer = rechts)",
                              value=float(CFG.get("unterschrift_x", 210)), step=5)
            steuer_pct = ui.number("Steuersatz (%)",
                                   value=CFG.get("steuersatz", 0.06) * 100, step=0.1, format="%.1f")
        ui.label("Smoobu").classes("text-sm text-gray-500 mt-3")
        with ui.grid(columns=2).classes("w-full gap-3"):
            api = ui.input("API-Key (leer = unverändert)",
                           password=True, placeholder="•••• unverändert").classes("w-full")
            channel = ui.input("Airbnb-Kanalname (steuerfrei)",
                               value=CFG.get("airbnb_channel_name", "Airbnb")).classes("w-full")

        def save():
            for key in inputs:
                betr[key] = inputs[key].value or ""
            v = sig_x.value
            CFG["unterschrift_x"] = int(v) if v == int(v) else v
            CFG["steuersatz"] = round((steuer_pct.value or 6) / 100, 4)
            if (channel.value or "").strip():
                CFG["airbnb_channel_name"] = channel.value.strip()
            if (api.value or "").strip():
                CFG["smoobu_api_key"] = api.value.strip()
                data.clear_cache()
            data.save_config()
            ui.notify("Einstellungen gespeichert", type="positive")
            dialog.close()

        with ui.row().classes("w-full justify-end mt-3"):
            ui.button("Abbrechen", on_click=dialog.close).props("flat")
            ui.button("Speichern", on_click=save).props("unelevated")
    dialog.open()


# ---------------------------------------------------------------- Ergebnis
def _kpi(container, label, value, accent=False):
    with container:
        with ui.card().classes("p-4 " + ("bg-green-50" if accent else "bg-blue-50")):
            ui.label(label).classes("text-xs text-gray-500")
            cls = "text-2xl font-bold " + ("text-green-700" if accent else "")
            ui.label(value).classes(cls)


def render_result(container, result):
    container.clear()
    r = result
    with container:
        with ui.row().classes("w-full gap-4"):
            grid = ui.grid(columns=4).classes("w-full gap-4")
        _kpi(grid, "ÜN insgesamt", str(r["uebernachtungen_insgesamt"]))
        _kpi(grid, "verbleibende ÜN", str(r["uebernachtungen_verbleibend"]))
        _kpi(grid, "steuerpfl. Umsatz", data.euro(r["umsatz_steuerpflichtig"]) + " €")
        _kpi(grid, "Beherbergungssteuer", data.euro(r["beherbergungssteuer"]) + " €", accent=True)

        ui.label(f"Airbnb-ÜN (berechnet): {r['uebernachtungen_airbnb']} – fließen nicht in die "
                 f"Steuer ein (Airbnb meldet selbst). Basis = Preis ohne durchlaufende "
                 f"Übernachtungssteuer.").classes("text-xs text-gray-500")

        # Buchungstabelle
        cols = [
            {"name": "departure", "label": "Abreise", "field": "departure", "sortable": True, "align": "left"},
            {"name": "guest", "label": "Gast", "field": "guest", "align": "left"},
            {"name": "apartment", "label": "Apartment", "field": "apartment", "align": "left"},
            {"name": "channel", "label": "Kanal", "field": "channel", "align": "left"},
            {"name": "arrival", "label": "Anreise", "field": "arrival", "align": "left"},
            {"name": "nights", "label": "Nächte", "field": "nights", "align": "right"},
            {"name": "persons", "label": "Pers.", "field": "persons", "align": "right"},
            {"name": "overnights", "label": "ÜN", "field": "overnights", "align": "right"},
            {"name": "price", "label": "Gesamtpreis €", "field": "price", "align": "right"},
            {"name": "steuer", "label": "Steuer €", "field": "steuer", "align": "right"},
        ]
        rows = []
        for x in r["rows"]:
            rows.append({
                "departure": x["departure"], "guest": x["guest"],
                "apartment": x["apartment"], "channel": x["channel"],
                "arrival": x["arrival"], "nights": x["nights"],
                "persons": x["persons"], "overnights": x["overnights"],
                "price": data.euro(x["price"]),
                "steuer": "—" if x["is_airbnb"] else data.euro(round(x["base"] * r["steuersatz"], 2)),
            })
        with ui.card().classes("w-full"):
            ui.label(f"Buchungen ({len(rows)}) – Abreise im Monat, bereits stattgefunden").classes("font-medium")
            ui.table(columns=cols, rows=rows, row_key="departure").classes("w-full").props("dense flat")
            with ui.row().classes("gap-6 text-sm mt-1"):
                ui.label(f"Steuerpflichtig (Booking/Website/Direkt): "
                         f"{r['uebernachtungen_verbleibend']} ÜN · {data.euro(r['umsatz_verbleibend'])} € · "
                         f"Steuer {data.euro(r['beherbergungssteuer'])} €").classes("font-semibold")
                ui.label(f"Airbnb: {r['uebernachtungen_airbnb']} ÜN (keine Steuer)").classes("text-gray-500")

        # PDF-Download
        def download_pdf():
            if pdf_form is None:
                ui.notify("PDF benötigt PyMuPDF (pip install -r requirements.txt)", type="negative")
                return
            if not os.path.exists(pdf_form.TEMPLATE):
                ui.notify("Blanko-Vorlage fehlt – siehe templates/README.md", type="negative")
                return
            pdf = pdf_form.render_pdf(r, CFG, datum=date.today().strftime("%d.%m.%Y"))
            ui.download.content(pdf, f"Beherbergungssteuer_{r['year']}-{r['month']:02d}.pdf",
                                media_type="application/pdf")

        ui.button("📄 Amtliches Formular (PDF) herunterladen",
                  on_click=download_pdf).props("unelevated")


# ---------------------------------------------------------------- Hauptseite
@ui.page("/")
def main_page():
    ui.colors(primary="#1f6feb")
    today = date.today()
    apts = _load_apartments()

    with ui.header().classes("items-center justify-between"):
        ui.label("Beherbergungssteuer Dresden").classes("text-lg font-bold")
        ui.button("⚙️ Einstellungen", on_click=open_settings).props("flat color=white")

    with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-4"):
        with ui.card().classes("w-full"):
            with ui.row().classes("items-end gap-4 flex-wrap"):
                year = ui.select(list(range(2023, today.year + 2)), label="Jahr",
                                 value=today.year)
                month = ui.select({m: data.MONATE[m] for m in range(1, 13)}, label="Monat",
                                  value=today.month)
                apt = ui.select(apts or {}, label="Apartments", multiple=True,
                                value=list(apts.keys())).classes("min-w-[220px]").props("use-chips")
                airbnb = ui.number("Airbnb-ÜN (Override)", value=None, format="%d") \
                    .props('placeholder="leer = berechnet" clearable')
                befreit = ui.number("Steuerbefr. Umsatz €", value=0, step=0.01)
                ui.button("Berechnen", on_click=lambda: do_compute()).props("unelevated")
            ui.label("Zuordnung nach Abreisedatum (§6) · nur bereits stattgefundene Buchungen · "
                     "Airbnb wird berechnet, nicht besteuert.").classes("text-xs text-gray-500")

        results = ui.column().classes("w-full gap-4")

        def do_compute():
            try:
                result = data.compute(
                    int(year.value), int(month.value),
                    apt_ids=apt.value or None,
                    airbnb_override=int(airbnb.value) if airbnb.value not in (None, "") else None,
                    befreit=float(befreit.value or 0))
            except smoobu.SmoobuError as ex:
                ui.notify(f"Smoobu: {ex}", type="negative", timeout=8000)
                return
            render_result(results, result)


def run():
    ui.run(host="127.0.0.1", port=int(CFG.get("port", 3001)),
           title="Beherbergungssteuer Dresden", reload=False, show=False)


if __name__ in {"__main__", "__mp_main__"}:
    run()
