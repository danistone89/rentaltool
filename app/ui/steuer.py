"""Beherbergungssteuer: Berechnung anzeigen, Formular erzeugen, Archiv.

Der Verwaltungsteil ist bewusst nur deutsch – Steuerbegriffe haben keine
belastbare englische Entsprechung, und diesen Bereich bedient nur der Betreiber.
"""

import os
from nicegui import ui
from datetime import date
from app import archive, data, mailer

from app.ui.basis import (CFG, t)

try:
    from app import pdf_form
except Exception:  # PyMuPDF optional
    pdf_form = None

DEFAULT_BETREFF = "Beherbergungssteuer-Anmeldung {monat} {jahr}"
DEFAULT_TEXT = (
    "Sehr geehrte Damen und Herren,\n\n"
    "anbei übersende ich die Steueranmeldung zur Beherbergungssteuer für "
    "{monat} {jahr} (Kassenzeichen {kassenzeichen}).\n\n"
    "Festgesetzte Beherbergungssteuer: {steuer} €.\n\n"
    "Mit freundlichen Grüßen\n{name}")


def _mail_context(r):
    """Platzhalter-Werte für die E-Mail-Vorlagen."""
    betr = CFG.get("betreiber", {})
    return {
        "periode": f"{r['year']}-{r['month']:02d}",
        "jahr": r["year"],
        "monat": data.MONATE[r["month"]],
        "steuer": data.euro(r["beherbergungssteuer"]),
        "umsatz": data.euro(r["umsatz_steuerpflichtig"]),
        "kassenzeichen": betr.get("kassenzeichen", ""),
        "name": (betr.get("name", "") + " " + betr.get("zusatz", "")).strip(),
    }


# ---------------------------------------------------------------- Archiv
def open_archive():
    all_ok, results = archive.verify()
    status_by_seq = {res["seq"]: res for res in results}
    entries = list(reversed(archive.list_entries()))  # neueste zuerst
    with ui.dialog() as dialog, ui.card().classes("w-[820px] max-w-full"):
        with ui.row().classes("w-full items-center"):
            ui.label("📚 Archiv – revisionssicher abgelegte Anmeldungen").classes("text-xl font-bold")
            ui.space()
            badge = "✓ Integrität geprüft" if all_ok else "⚠️ Integrität verletzt!"
            ui.label(badge).classes("text-sm " + ("text-green-700" if all_ok else "text-red-700"))
        if not entries:
            ui.label("Noch keine Dokumente abgelegt.").classes("text-slate-500")
        for e in entries:
            res = status_by_seq.get(e["seq"], {"ok": True, "issues": []})
            with ui.card().classes("w-full p-3"):
                with ui.row().classes("w-full items-center gap-3"):
                    ok_icon = "✅" if res["ok"] else "❌"
                    ui.label(f"{ok_icon} {e['period']} · Revision {e['revision']}").classes("font-semibold")
                    ui.label(e["ts"].replace("T", " ")).classes("text-xs text-slate-500")
                    ui.label(f"Steuer {data.euro(e['values'].get('beherbergungssteuer', 0))} €") \
                        .classes("text-xs")
                    ui.space()

                    def _dl(entry=e):
                        try:
                            ui.download.content(archive.read_pdf(entry["file"]),
                                                os.path.basename(entry["file"]),
                                                media_type="application/pdf")
                        except FileNotFoundError:
                            ui.notify("Datei fehlt im Archiv!", type="negative")
                    ui.button("PDF", on_click=_dl).props("flat dense")
                ui.label(f"SHA-256: {e['sha256']}").classes("text-xs text-slate-400 font-mono")
                if not res["ok"]:
                    ui.label("⚠️ " + "; ".join(res["issues"])).classes("text-xs text-red-700")
        with ui.row().classes("w-full justify-between items-center"):
            def do_mirror_all():
                if not archive.has_mirror(CFG):
                    ui.notify("Kein Spiegel gesetzt (Einstellungen).", type="warning")
                    return
                try:
                    n = archive.mirror_all(CFG)
                    ui.notify(f"{n} Dokument(e) nach {archive.mirror_label(CFG)} gespiegelt.",
                              type="positive")
                except Exception as ex:
                    ui.notify(f"Spiegelung fehlgeschlagen: {ex}", type="negative", timeout=9000)
            if archive.has_mirror(CFG):
                ui.button(f"🔁 Alles nach {archive.mirror_label(CFG)} spiegeln",
                          on_click=do_mirror_all).props("flat")
            else:
                ui.label("Kein externer Spiegel gesetzt (→ Einstellungen)").classes("text-xs text-slate-400")
            ui.button("Schließen", on_click=dialog.close).props("flat")
    dialog.open()


# ---------------------------------------------------------------- Ergebnis
def _kpi(container, label, value, icon="analytics", accent=False):
    with container:
        cls = "p-4 rounded-xl shadow-sm border " + \
            ("border-[#C8A96E]/40 bg-[#faf7f0]" if accent else "border-slate-100")
        with ui.card().classes(cls):
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.icon(icon).classes("text-xl " + ("text-[#C8A96E]" if accent else "text-primary"))
                ui.label(label).classes("text-xs text-slate-500")
            ui.label(value).classes("text-2xl font-bold mt-1 text-primary")


def _satz_label(satz):
    """0.06 -> '6 %', 0.065 -> '6,5 %'."""
    p = round(satz * 100, 4)
    s = f"{p:g}".replace(".", ",")
    return f"{s} %"


def _summen_tabelle(r, satz):
    """Alle Summen einer Anmeldung als Tabelle.

    Beantwortet die Frage, an der man sich sonst verrechnet: WELCHE Summe ist
    die Bemessungsgrundlage? Nicht die Summe der Rechnungsbeträge – aus der
    muss erst die vom Gast mitbezahlte Beherbergungssteuer raus. Die Spalte
    rechts sagt, welche Zeile tatsächlich ins amtliche Formular wandert.
    """
    rem = r["remaining_rows"]
    s_rechnung = round(sum(x["price"] for x in rem), 2)
    s_citytax = round(sum(x["citytax"] for x in rem), 2)
    s_zeilen = round(sum(round(x["base"] * r["steuersatz"], 2) for x in rem), 2)
    e = data.euro

    # (Art, Bezeichnung, Wert, Herkunft)
    zeilen = [
        ("head", "Übernachtungen", "", ""),
        ("line", "Übernachtungen insgesamt",
         str(r["uebernachtungen_insgesamt"]), "Formular"),
        ("line", "davon über Airbnb gebucht (Airbnb meldet selbst)",
         str(r["uebernachtungen_airbnb"]), "Formular"),
        ("sum", "= verbleibende Übernachtungen",
         str(r["uebernachtungen_verbleibend"]), "Formular"),
        ("head", f"Beträge – nur die {len(rem)} verbleibenden Buchungen, ohne Airbnb", "", ""),
        ("line", "Summe Rechnungsbeträge (was die Gäste insgesamt gezahlt haben)",
         e(s_rechnung) + " €", "nachrichtlich"),
        ("minus", "− darin enthaltene Beherbergungssteuer (Durchlaufposten)",
         "− " + e(s_citytax) + " €", "nachrichtlich"),
        ("sum", "= Umsätze aus verbleibenden Übernachtungen (Bemessungsgrundlage)",
         e(r["umsatz_verbleibend"]) + " €", "Formular"),
        ("minus", "− steuerbefreite Umsätze",
         "− " + e(r["umsatz_steuerbefreit"]) + " €", "Formular"),
        ("sum", "= steuerpflichtige Umsätze",
         e(r["umsatz_steuerpflichtig"]) + " €", "Formular"),
        ("result", f"× {satz} = Beherbergungssteuer",
         e(r["beherbergungssteuer"]) + " €", "Formular"),
    ]

    with ui.card().classes("w-full").mark("summen"):
        ui.label("Summen dieser Anmeldung").classes("font-medium")
        ui.label("Welche Summe wofür – die rechte Spalte zeigt, was ins amtliche "
                 "Formular eingetragen wird.").classes("text-xs text-slate-500")
        with ui.element("div").classes(
                "w-full grid grid-cols-[1fr_auto_auto] gap-x-4 gap-y-0 mt-2 "
                "border border-slate-200 rounded-lg overflow-hidden"):
            def zelle(text, cls):
                ui.label(text).classes("px-3 py-1.5 " + cls)

            for art, bez, wert, herkunft in zeilen:
                if art == "head":
                    zelle(bez, "text-xs font-semibold uppercase tracking-wide "
                               "text-slate-500 bg-slate-100 pt-2")
                    zelle("", "bg-slate-100")
                    zelle("", "bg-slate-100")
                    continue
                basis = {
                    "line":   ("text-sm text-slate-700", "text-sm tabular-nums text-slate-700"),
                    "minus":  ("text-sm text-slate-600", "text-sm tabular-nums text-slate-600"),
                    "sum":    ("text-sm font-semibold text-slate-800 border-t border-slate-200",
                               "text-sm font-semibold tabular-nums text-slate-800 "
                               "border-t border-slate-200"),
                    "result": ("text-base font-bold text-primary border-t-2 border-slate-300 "
                               "bg-[#faf7f0]",
                               "text-base font-bold tabular-nums text-primary "
                               "border-t-2 border-slate-300 bg-[#faf7f0]"),
                }[art]
                zelle(bez, basis[0])
                zelle(wert, basis[1] + " text-right")
                zelle(herkunft, "text-xs text-slate-400 self-center whitespace-nowrap"
                      + (" bg-[#faf7f0]" if art == "result" else ""))

        if s_zeilen != r["beherbergungssteuer"]:
            ui.label(f"Hinweis: Die Steuer-Spalte der Buchungstabelle aufsummiert ergibt "
                     f"{e(s_zeilen)} €. Der Cent-Unterschied entsteht, weil die Steuer auf die "
                     f"Gesamtsumme gerechnet wird und nicht je Buchung – angemeldet wird "
                     f"{e(r['beherbergungssteuer'])} €.").classes("text-xs text-slate-500 mt-2")


def render_result(container, result):
    container.clear()
    r = result
    with container:
        grid = ui.grid(columns=4).classes("w-full gap-4 max-md:grid-cols-2")
        _kpi(grid, "ÜN insgesamt", str(r["uebernachtungen_insgesamt"]), icon="hotel")
        _kpi(grid, "verbleibende ÜN", str(r["uebernachtungen_verbleibend"]), icon="nights_stay")
        _kpi(grid, "steuerpfl. Umsatz", data.euro(r["umsatz_steuerpflichtig"]) + " €", icon="payments")
        _kpi(grid, "Beherbergungssteuer", data.euro(r["beherbergungssteuer"]) + " €",
             icon="account_balance", accent=True)

        ui.label(f"Airbnb-ÜN (berechnet): {r['uebernachtungen_airbnb']} – fließen nicht in die "
                 f"Steuer ein (Airbnb meldet selbst).").classes("text-xs text-slate-500")

        satz = _satz_label(r["steuersatz"])

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
            {"name": "price", "label": "Rechnungsbetrag €", "field": "price", "align": "right"},
            {"name": "citytax", "label": "− enth. BSt €", "field": "citytax", "align": "right"},
            {"name": "base", "label": "= Bemessungsgrundlage €", "field": "base", "align": "right"},
            {"name": "steuer", "label": f"Steuer € ({satz})", "field": "steuer", "align": "right"},
        ]
        rows = []
        for x in r["rows"]:
            # Airbnb wird nicht besteuert – dann bleiben Basis und Steuer leer,
            # sonst summiert sich die Spalte nicht auf den steuerpfl. Umsatz.
            leer = x["is_airbnb"]
            rows.append({
                "departure": x["departure"], "guest": x["guest"],
                "apartment": x["apartment"], "channel": x["channel"],
                "arrival": x["arrival"], "nights": x["nights"],
                "persons": x["persons"], "overnights": x["overnights"],
                "price": data.euro(x["price"]),
                "citytax": "—" if leer else ("–" + data.euro(x["citytax"]) if x["citytax"] else "0,00"),
                "base": "—" if leer else data.euro(x["base"]),
                "steuer": "—" if leer else data.euro(round(x["base"] * r["steuersatz"], 2)),
            })
        _summen_tabelle(r, satz)

        with ui.card().classes("w-full"):
            ui.label(f"Buchungen ({len(rows)}) – Abreise im Monat, bereits stattgefunden").classes("font-medium")
            # Legende zu den vier Betragsspalten. Bewusst NICHT "Bruttopreis" für die
            # Basis – das liest sich wie "alles inklusive" und ist genau die
            # Verwechslung, die hier droht.
            with ui.row().classes("w-full items-center gap-2 flex-wrap text-xs text-slate-600 "
                                  "bg-slate-50 border border-slate-200 rounded-lg px-3 py-2"):
                ui.icon("functions").classes("text-slate-400 text-base")
                ui.label("Rechnungsbetrag (was der Gast zahlt)").classes("font-medium")
                ui.label("−").classes("text-slate-400")
                ui.label("darin enthaltene Beherbergungssteuer (Durchlaufposten)")
                ui.label("=").classes("text-slate-400")
                ui.label("Bemessungsgrundlage (Beherbergungsentgelt inkl. 7 % USt)").classes("font-medium")
                ui.label(f"× {satz} =").classes("text-slate-400")
                ui.label("Steuer").classes("font-medium")
            ui.table(columns=cols, rows=rows, row_key="departure").classes("w-full").props("dense flat")

        # PDF erzeugen (gemeinsame Logik)
        def build_pdf():
            if pdf_form is None:
                ui.notify("PDF benötigt PyMuPDF (pip install -r requirements.txt)", type="negative")
                return None
            if not os.path.exists(pdf_form.TEMPLATE):
                ui.notify("Blanko-Vorlage fehlt – siehe templates/README.md", type="negative")
                return None
            return pdf_form.render_pdf(r, CFG, datum=date.today().strftime("%d.%m.%Y"))

        def _values():
            return {k: r[k] for k in (
                "uebernachtungen_insgesamt", "uebernachtungen_airbnb",
                "uebernachtungen_verbleibend", "umsatz_verbleibend",
                "umsatz_steuerbefreit", "umsatz_steuerpflichtig", "beherbergungssteuer")}

        period = f"{r['year']}-{r['month']:02d}"
        fname = f"Beherbergungssteuer_{period}.pdf"

        def _archive_and_mirror(pdf):
            """PDF ablegen + (falls konfiguriert) spiegeln. Gibt (entry, zusatz_text)."""
            entry = archive.archive_pdf(pdf, period, _values())
            extra = ""
            if archive.has_mirror(CFG):
                try:
                    archive.mirror_entry(entry, CFG)
                    extra = f" · in {archive.mirror_label(CFG)} gesichert"
                except Exception as ex:  # Spiegel-Fehler darf lokale Ablage nicht kippen
                    ui.notify(f"Lokal abgelegt, aber Spiegelung fehlgeschlagen: {ex}",
                              type="warning", timeout=9000)
            return entry, extra

        def festschreiben():
            pdf = build_pdf()
            if pdf is None:
                return
            entry, extra = _archive_and_mirror(pdf)
            ui.download.content(pdf, f"Beherbergungssteuer_{period}_v{entry['revision']}.pdf",
                                media_type="application/pdf")
            ui.notify(f"Revisionssicher abgelegt: Revision {entry['revision']} · "
                      f"SHA-256 {entry['sha256'][:12]}…{extra}", type="positive", timeout=7000)

        def vorschau():
            pdf = build_pdf()
            if pdf is not None:
                ui.download.content(pdf, fname, media_type="application/pdf")

        def open_send():
            ec = CFG.get("email", {})
            if not (ec.get("empfaenger") and ec.get("absender") and ec.get("app_password")):
                ui.notify("E-Mail noch nicht eingerichtet – Absender, App-Passwort und "
                          "Empfänger in den Einstellungen setzen.", type="warning", timeout=9000)
                return
            ctx = _mail_context(r)
            with ui.dialog() as dlg, ui.card().classes("w-[720px] max-w-full"):
                ui.label("✉️ Anmeldung per E-Mail senden").classes("text-xl font-bold")
                cc = f" · Cc: {ec['cc']}" if ec.get("cc") else ""
                ui.label(f"An: {ec['empfaenger']}{cc}   (Absender: {ec['absender']})") \
                    .classes("text-sm text-slate-600")
                subj = ui.input("Betreff", value=mailer.render(ec.get("betreff_vorlage") or DEFAULT_BETREFF, ctx)) \
                    .classes("w-full")
                body = ui.textarea("Text", value=mailer.render(ec.get("text_vorlage") or DEFAULT_TEXT, ctx)) \
                    .classes("w-full").props("autogrow outlined")
                ui.label(f"📎 Anhang: Beherbergungssteuer_{period}_v(neu).pdf") \
                    .classes("text-xs text-slate-500")

                def do_send():
                    pdf = build_pdf()
                    if pdf is None:
                        return
                    entry, extra = _archive_and_mirror(pdf)
                    try:
                        mailer.send_form(
                            CFG, pdf,
                            f"Beherbergungssteuer_{period}_v{entry['revision']}.pdf",
                            ctx, subject=subj.value, body=body.value)
                    except mailer.MailError as ex:
                        ui.notify(f"Abgelegt (Rev. {entry['revision']}), aber Versand "
                                  f"fehlgeschlagen: {ex}", type="negative", timeout=11000)
                        dlg.close()
                        return
                    ui.notify(f"✅ Gesendet an {ec['empfaenger']} · abgelegt als "
                              f"Revision {entry['revision']}{extra}", type="positive", timeout=8000)
                    dlg.close()

                with ui.row().classes("w-full justify-end"):
                    ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
                    ui.button("Senden", on_click=do_send).props("unelevated")
            dlg.open()

        with ui.row().classes("gap-2 items-center flex-wrap"):
            ui.button("📥 Erzeugen & ablegen", on_click=festschreiben).props("unelevated")
            ui.button("✉️ Ablegen & per E-Mail senden", on_click=open_send).props("unelevated")
            ui.button("👁 Nur Vorschau", on_click=vorschau).props("flat")
            existing = sum(1 for e in archive.list_entries() if e["period"] == period)
            if existing:
                ui.label(f"⚠️ Für {period} bereits {existing} Ablage(n) – Erzeugen legt "
                         "eine neue Revision an.").classes("text-xs text-amber-700")
