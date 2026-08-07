"""Zeiterfassung: Liste, Bearbeiten, Kennzahlen, Abrechnungsstatus, CSV.

Mitarbeiter sehen ihre eigenen Zeiten samt Uebersicht; der Admin zusaetzlich die
Auswertung ueber alle und den Abrechnungsstand (siehe README).
"""

from nicegui import ui
from datetime import date
from app import feiertage, lohn, mailer, rechte, timetrack
from app.ui.basis import (CFG, USERS, _MONATE, _billing_month, _billing_period,
                          _cur_user, _d, _darf, _eur, _has_rates, _hours_num,
                          _month_label, _rate_defaults, _t, _zeit_aggregat, t)
from app.ui.standort import (_presence)
from app.ui import ton

def _export_csv(rows, show_user):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow((["Mitarbeiter"] if show_user else []) +
               ["Datum", "Check-in", "Ort ein", "Check-out", "Ort aus", "Dauer"])
    for e in rows:
        w.writerow((([e["user"]] if show_user else []) + [
            _d(e["checkin"]), _t(e["checkin"]),
            _presence(e.get("checkin_ort"), e.get("checkin_dist"), e.get("checkin_loc"), e.get("checkin_ip")),
            _t(e["checkout"]) if e.get("checkout") else "",
            _presence(e.get("checkout_ort"), e.get("checkout_dist"), e.get("checkout_loc"), e.get("checkout_ip"))
            if e.get("checkout") else "",
            timetrack.fmt_dur(timetrack.duration_minutes(e))]))
    ui.download.content(buf.getvalue().encode("utf-8-sig"), "arbeitszeiten.csv",
                        media_type="text/csv")


def _zeit_table(container, rows, show_user, title, export=False):
    container.clear()
    cols = ([{"name": "user", "label": "Mitarbeiter", "field": "user", "align": "left"}]
            if show_user else []) + [
        {"name": "date", "label": "Datum", "field": "date", "align": "left"},
        {"name": "cin", "label": "Check-in", "field": "cin", "align": "left"},
        {"name": "lin", "label": "Ort ein", "field": "lin", "align": "left"},
        {"name": "cout", "label": "Check-out", "field": "cout", "align": "left"},
        {"name": "lout", "label": "Ort aus", "field": "lout", "align": "left"},
        {"name": "dur", "label": "Dauer", "field": "dur", "align": "right"},
    ]
    trows = [{
        "id": e["id"], "user": e["user"], "date": _d(e["checkin"]), "cin": _t(e["checkin"]),
        "lin": _presence(e.get("checkin_ort"), e.get("checkin_dist"), e.get("checkin_loc"), e.get("checkin_ip")),
        "cout": _t(e["checkout"]) if e.get("checkout") else "—",
        "lout": _presence(e.get("checkout_ort"), e.get("checkout_dist"), e.get("checkout_loc"), e.get("checkout_ip"))
                if e.get("checkout") else "—",
        "dur": timetrack.fmt_dur(timetrack.duration_minutes(e)),
    } for e in rows]
    with container:
        with ui.card().classes(ton.KARTE):
            with ui.row().classes("w-full items-center"):
                ui.label(title).classes("font-medium")
                ui.space()
                if export and rows:
                    ui.button("CSV", icon="download",
                              on_click=lambda: _export_csv(rows, show_user)).props("flat dense no-caps")
            if trows:
                ui.table(columns=cols, rows=trows, row_key="id").props("dense flat").classes("w-full")
            else:
                ui.label(t("Noch keine Einträge.")).classes("text-sm text-slate-400")


def _zeit_csv_bytes(rows, show_user):
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow((["Mitarbeiter"] if show_user else []) +
               ["Datum", "Von", "Bis", "Wohnung", "Dauer", "Minuten",
                "Tagesart", "Anlass", "Stundensatz", "Betrag", "Abrechnungsstatus",
                "Ort ein"])
    defaults = _rate_defaults()
    for e in rows:
        mins = timetrack.duration_minutes(e) or 0
        d = timetrack.entry_date(e)
        kind = timetrack.kind_of(e)
        rate = timetrack.rate_for(kind, USERS.get(e["user"]), defaults)
        w.writerow((([e["user"]] if show_user else []) + [
            _d(e["checkin"]), _t(e["checkin"]),
            _t(e["checkout"]) if e.get("checkout") else "",
            e.get("apartment") or "", timetrack.fmt_dur(mins), mins,
            feiertage.LABELS[kind], feiertage.label_of(d),
            f"{rate:.2f}".replace(".", ",") if rate else "",
            f"{timetrack.amount(mins, rate):.2f}".replace(".", ",") if rate else "",
            f"abgerechnet {_d(e['abgerechnet'])}" if timetrack.is_billed(e) else "offen",
            _presence(e.get("checkin_ort"), e.get("checkin_dist"),
                      e.get("checkin_loc"), e.get("checkin_ip"))]))
    return buf.getvalue().encode("utf-8-sig")


def _time_edit_dialog(default_user, apts, admin, staff, entry=None, on_saved=None):
    from datetime import datetime
    apt_opts = {"": t("— keine Wohnung —"), **{v: v for v in apts.values()}}
    d0 = entry["checkin"][:10] if entry else date.today().isoformat()
    von0 = _t(entry["checkin"]) if entry else "09:00"
    bis0 = _t(entry["checkout"]) if entry and entry.get("checkout") else "11:00"
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(t("Zeit bearbeiten") if entry else t("Zeit manuell erfassen")).classes("text-lg font-bold")
        usel = None
        if _darf(rechte.ZEITEN_FREMDE) and not entry:
            usel = ui.select({u: (staff.get(u) or u) for u in staff}, value=default_user,
                             label=t("Mitarbeiter")).props("outlined dense").classes("w-full")
        d = ui.input(t("Datum"), value=d0).props("type=date outlined dense").classes("w-full")
        with ui.row().classes("w-full gap-2"):
            t1 = ui.input(t("Von"), value=von0).props("type=time outlined dense").classes("flex-grow")
            t2 = ui.input(t("Bis"), value=bis0).props("type=time outlined dense").classes("flex-grow")
        aptsel = ui.select(apt_opts, value=(entry.get("apartment") if entry else "") or "",
                           label=t("Wohnung")).props("outlined dense").classes("w-full")

        def save():
            try:
                ci = datetime.fromisoformat(f"{d.value}T{t1.value}")
                co = datetime.fromisoformat(f"{d.value}T{t2.value}")
            except Exception:
                ui.notify(t("Bitte Datum und Uhrzeiten prüfen."), type="warning"); return
            if co <= ci:
                ui.notify(t("Ende muss nach Beginn liegen."), type="warning"); return
            apt = aptsel.value or ""
            if entry:
                timetrack.update_entry(entry["id"], checkin=ci, checkout=co, apartment=apt)
            else:
                timetrack.add_manual(usel.value if usel else default_user, ci, co, apartment=apt)
            dlg.close(); ui.notify(t("Gespeichert ✓"), type="positive")
            if on_saved:
                on_saved()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Speichern"), icon="save", on_click=save).props("unelevated")
    dlg.open()


def _zeit_list(rows, apts, admin, staff, on_change, title, show_user):
    with ui.card().classes(ton.KARTE_ENG):
        with ui.row().classes("w-full items-center"):
            ui.label(title).classes("font-medium")
            ui.space()
            if rows:
                ui.button("CSV", icon="download",
                          on_click=lambda: ui.download.content(
                              _zeit_csv_bytes(rows, show_user), "arbeitszeiten.csv",
                              media_type="text/csv")).props("flat dense no-caps")
        if not rows:
            ui.label(t("Noch keine Einträge.")).classes("text-sm text-slate-400"); return
        for e in rows:
            with ui.row().classes("w-full items-center gap-2 no-wrap border-b border-slate-50 py-1"):
                with ui.column().classes("gap-0 min-w-0 flex-grow"):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.label(f"{_d(e['checkin'])} · {_t(e['checkin'])}–"
                                 + (_t(e['checkout']) if e.get('checkout') else '…')) \
                            .classes("text-sm text-slate-700 truncate")
                        if timetrack.kind_of(e) == feiertage.WOCHENENDE:
                            ui.chip(t(feiertage.label_of(timetrack.entry_date(e)))) \
                                .props("color=amber-7 text-color=white dense square") \
                                .classes("text-[10px] shrink-0")
                        if timetrack.is_billed(e):
                            ui.chip(t("abgerechnet"), icon="lock") \
                                .props("color=green-7 text-color=white dense square") \
                                .classes("text-[10px] shrink-0")
                    sub = []
                    if show_user:
                        sub.append(staff.get(e["user"], e["user"]))
                    if e.get("apartment"):
                        sub.append(e["apartment"])
                    if e.get("manual") or e.get("edited"):
                        sub.append("manuell")
                    if sub:
                        ui.label(" · ".join(sub)).classes("text-xs text-slate-400 truncate")
                ui.label(timetrack.fmt_dur(timetrack.duration_minutes(e))) \
                    .classes("text-sm font-medium shrink-0")
                # Gemeldete Zeiten darf nur der Admin noch anfassen – sonst weicht
                # das, was beim Steuerbüro liegt, von dem hier ab.
                if timetrack.is_billed(e) and not _darf(rechte.ZEITEN_ABGERECHNET):
                    ui.icon("lock").classes("text-slate-300 shrink-0") \
                        .tooltip(t("Ans Steuerbüro gemeldet – nicht mehr änderbar."))
                else:
                    ui.button(icon="edit", on_click=lambda ev=e:
                              _time_edit_dialog(ev["user"], apts, admin, staff, entry=ev, on_saved=on_change)) \
                        .props("flat round dense").tooltip(t("Bearbeiten"))
                    ui.button(icon="delete", on_click=lambda ev=e:
                              (timetrack.delete_entry(ev["id"]), ui.notify(t("Eintrag gelöscht."), type="warning"),
                               on_change())).props("flat round dense color=negative").tooltip(t("Löschen"))


def _mini_kpi(label, wert, zusatz="", icon="schedule", farbe="primary"):
    """Kachel für die Mitarbeiter-Übersicht."""
    with ui.card().classes(ton.KARTENFLAECHE + " p-3 gap-0 min-w-[136px] flex-grow"):
        with ui.row().classes("items-center gap-1 no-wrap"):
            ui.icon(icon).classes(f"text-{farbe} text-base shrink-0")
            ui.label(label).classes("text-[11px] text-slate-500 leading-tight")
        ui.label(wert).classes(f"text-2xl font-bold text-{farbe} leading-tight mt-1")
        if zusatz:
            ui.label(zusatz).classes("text-[11px] text-slate-400 leading-tight")


def _meine_kennzahlen(user):
    """Übersicht für Mitarbeiter: eigene Stunden, Einsätze und Abrechnungsstand.

    Zeitraum ist der Abrechnungsmonat (19.–18.), damit die Zahlen zu dem passen,
    was ans Steuerbüro geht.
    """
    eigene = [e for e in timetrack.entries(user) if e.get("checkout")]
    heute = date.today()
    akt = _billing_month(heute.isoformat())
    monate = sorted({_billing_month(e["checkin"]) for e in eigene}, reverse=True)
    vor = None
    for m in monate:
        if m < akt:
            vor = m
            break

    ucfg, defs = USERS.get(user), _rate_defaults()

    def summe(m):
        return timetrack.summary([e for e in eigene if _billing_month(e["checkin"]) == m],
                                 ucfg, defs)

    s_akt, s_ges = summe(akt), timetrack.summary(eigene, ucfg, defs)
    money = _has_rates()
    st, en = _billing_period(akt)

    with ui.card().classes(ton.KARTE_ENG):
        with ui.row().classes("w-full items-center gap-2"):
            ui.icon("insights").classes("text-primary text-xl")
            ui.label(t("Meine Übersicht")).classes("font-medium")
            ui.space()
            ui.label(f"{_month_label(akt)} · {st.strftime('%d.%m.')}–{en.strftime('%d.%m.')}") \
                .classes("text-xs text-slate-500")
        with ui.row().classes("w-full gap-2 flex-wrap"):
            _mini_kpi(t("Stunden dieser Monat"), _hours_num(s_akt["minutes"]),
                      t("{n} Einsätze", n=s_akt["count"]), "schedule")
            _mini_kpi(t("Ø je Einsatz"),
                      timetrack.fmt_dur(s_akt["avg_minutes"]) if s_akt["count"] else "–",
                      t("{n} Wohnungen", n=len(s_akt["apartments"])) if s_akt["apartments"] else "",
                      "timelapse")
            if s_akt["minutes_wochenende"]:
                _mini_kpi(t("davon Wo.-ende/Feiertag"), _hours_num(s_akt["minutes_wochenende"]),
                          t("Werktags {h}", h=_hours_num(s_akt["minutes_werktag"])),
                          "weekend", "amber-8")
            if vor:
                _mini_kpi(t("Vormonat"), _hours_num(summe(vor)["minutes"]),
                          _month_label(vor), "history", "slate-600")
            _mini_kpi(t("Gesamt erfasst"), _hours_num(s_ges["minutes"]),
                      t("{n} Einsätze", n=s_ges["count"]), "functions", "slate-600")
            if money and s_akt["amount"]:
                _mini_kpi(t("Betrag dieser Monat"), _eur(s_akt["amount"]),
                          t("nach hinterlegtem Stundensatz"), "payments")

        # Abrechnungsstand über alle Zeiten
        offen, abger = s_ges["open_minutes"], s_ges["billed_minutes"]
        with ui.column().classes("w-full gap-1 rounded-lg bg-slate-50 border border-slate-200 p-3"):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.icon("receipt_long").classes("text-slate-500 text-base shrink-0")
                ui.label(t("Abrechnungsstand")).classes(
                    "text-xs font-semibold uppercase tracking-wide text-slate-500")
            with ui.row().classes("w-full items-center gap-4 flex-wrap"):
                with ui.column().classes("gap-0"):
                    ui.label(t("noch offen")).classes("text-[11px] text-slate-500")
                    ui.label(_hours_num(offen) + " " + t("Std")) \
                        .classes("text-lg font-bold text-amber-700 leading-tight")
                    if money and s_ges["open_amount"]:
                        ui.label(_eur(s_ges["open_amount"])).classes("text-[11px] text-slate-500")
                ui.element("div").classes("w-px h-10 bg-slate-200")
                with ui.column().classes("gap-0"):
                    ui.label(t("abgerechnet")).classes("text-[11px] text-slate-500")
                    ui.label(_hours_num(abger) + " " + t("Std")) \
                        .classes("text-lg font-bold text-green-700 leading-tight")
                    if money and s_ges["billed_amount"]:
                        ui.label(_eur(s_ges["billed_amount"])).classes("text-[11px] text-slate-500")
            if offen + abger:
                ui.linear_progress(value=abger / (offen + abger), show_value=False) \
                    .props("color=green rounded track-color=amber-3 size=8px").classes("w-full")
            ui.label(t("„Abgerechnet“ heißt: ans Steuerbüro gemeldet. Diese Einträge "
                       "lassen sich nicht mehr ändern.")).classes("text-[11px] text-slate-400")


def _stb_email_body(ym, rows, staff):
    """Vorlagenbasierten Text für den Steuerberater bauen: je Mitarbeiter Stunden
    getrennt nach Werktag und Wochenende/Feiertag, mit Beträgen aus den
    hinterlegten Stundensätzen. Meldezeitraum endet am 18."""
    start, end = _billing_period(ym)
    monat = _MONATE[int(ym[5:7]) - 1]
    anrede = CFG.get("steuerberater_anrede") or "Sehr geehrte Damen und Herren,"
    intro = (CFG.get("steuerberater_intro") or "anbei die Stunden für {monat}.") \
        .replace("{monat}", monat).replace("{jahr}", ym[:4])
    gruss = CFG.get("steuerberater_gruss") or "Mit freundlichen Grüßen"
    agg = _zeit_aggregat(rows)
    money = _has_rates()
    bis = end.strftime("%d.%m.%Y")

    def zeile(text, mins, betrag):
        s = f"{text}: {_hours_num(mins)} Stunden"
        return s + (f" = {_eur(betrag)}" if money and betrag else "")

    blocks = []
    for u in sorted(agg, key=lambda x: -agg[x]["total_minutes"]):
        a = agg[u]
        lines = [f"{staff.get(u, u)}:"]
        wt = a["minutes"][feiertage.WERKTAG]
        we = a["minutes"][feiertage.WOCHENENDE]
        if we > 0:
            lines.append(zeile("Werktags", wt, a["amount"][feiertage.WERKTAG]))
            lines.append(zeile("Wochenende/Feiertag", we, a["amount"][feiertage.WOCHENENDE]))
            lines.append(f"Gesamt: {_hours_num(a['total_minutes'])} Stunden (bis {bis})"
                         + (f" = {_eur(a['total_amount'])}" if money and a["total_amount"] else ""))
        else:
            lines.append(f"{_hours_num(wt)} Stunden (bis {bis})"
                         + (f" = {_eur(a['amount'][feiertage.WERKTAG])}"
                            if money and a["amount"][feiertage.WERKTAG] else ""))
        note = (USERS.get(u, {}) or {}).get("steuer_notiz", "").strip()
        if note:
            lines.append(note)
        blocks.append("\n".join(lines))
    return anrede + "\n\n" + intro + "\n\n" + "\n\n".join(blocks) + "\n\n" + gruss


def _abrechnen_block(rows, ym, on_change, dlg_slot):
    """Admin: Zeiten eines Abrechnungsmonats als ans Steuerbüro gemeldet markieren.

    Bewusst als eigener Schritt nach dem Versand – der Versand kann scheitern
    oder die Meldung auch per Post/Portal laufen. Rückgängig machen geht.

    `dlg_slot` ist ein Container AUSSERHALB des neu gebauten Bereichs. Läge der
    Bestätigungsdialog darin, würde er beim Neuaufbau mitten in seinem eigenen
    Klick-Handler gelöscht – der Aufbau bricht dann ab und die Seite bleibt leer.
    """
    offen = [e for e in rows if not timetrack.is_billed(e)]
    fertig = [e for e in rows if timetrack.is_billed(e)]
    o_min = sum(timetrack.duration_minutes(e) or 0 for e in offen)
    f_min = sum(timetrack.duration_minutes(e) or 0 for e in fertig)
    wann = sorted({e.get("abgerechnet", "")[:10] for e in fertig if e.get("abgerechnet")})

    def _confirm(titel, text, ok_label, farbe, aktion):
        dlg_slot.clear()                     # nur ein Dialog gleichzeitig
        with dlg_slot:
            with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
                ui.label(titel).classes("text-lg font-bold")
                ui.label(text).classes("text-sm text-slate-600 whitespace-pre-wrap")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Abbrechen", on_click=dlg.close).props("flat")
                    ui.button(ok_label, on_click=lambda: (dlg.close(), aktion())) \
                        .props(f"unelevated no-caps color={farbe}")
        dlg.open()

    def markieren():
        n = timetrack.mark_billed([e["id"] for e in offen], _cur_user())
        ui.notify(f"{n} Einträge als abgerechnet markiert ✓", type="positive")
        on_change()

    def zuruecknehmen():
        n = timetrack.unmark_billed([e["id"] for e in fertig])
        ui.notify(f"Markierung bei {n} Einträgen aufgehoben.", type="warning")
        on_change()

    with ui.column().classes("w-full gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 mt-2"):
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.icon("receipt_long").classes("text-slate-500")
            ui.label("Abrechnungsstatus").classes("font-medium")
            ui.space()
            if offen and not fertig:
                ui.chip("offen", icon="pending").props("color=amber-7 text-color=white dense")
            elif fertig and not offen:
                ui.chip("abgerechnet", icon="check_circle") \
                    .props("color=green-7 text-color=white dense")
            elif fertig and offen:
                ui.chip("teilweise abgerechnet", icon="incomplete_circle") \
                    .props("color=orange-8 text-color=white dense")
        if not rows:
            ui.label("Keine Zeiten in diesem Zeitraum.").classes("text-sm text-slate-400")
            return
        ui.label(f"{len(fertig)} von {len(rows)} Einträgen abgerechnet · "
                 f"offen {_hours_num(o_min)} Std · abgerechnet {_hours_num(f_min)} Std"
                 + (f" · gemeldet am {', '.join(_d(w) for w in wann)}" if wann else "")) \
            .classes("text-sm text-slate-600")
        with ui.row().classes("gap-2 flex-wrap"):
            if offen:
                ui.button(f"Als abgerechnet markieren ({len(offen)})", icon="task_alt",
                          on_click=lambda: _confirm(
                              "Als abgerechnet markieren?",
                              f"{len(offen)} Einträge aus {_month_label(ym)} "
                              f"({_hours_num(o_min)} Stunden) werden als ans Steuerbüro "
                              f"gemeldet markiert.\n\nDie Mitarbeiter können diese Zeiten "
                              f"danach nicht mehr ändern oder löschen.",
                              "Markieren", "positive", markieren)) \
                    .props("unelevated no-caps color=positive")
            if fertig:
                ui.button(f"Markierung aufheben ({len(fertig)})", icon="undo",
                          on_click=lambda: _confirm(
                              "Markierung aufheben?",
                              f"Bei {len(fertig)} Einträgen aus {_month_label(ym)} wird der "
                              f"Status „abgerechnet“ entfernt. Sie sind danach wieder "
                              f"änderbar.\n\nNur nutzen, wenn die Meldung ans Steuerbüro "
                              f"nicht oder falsch rausgegangen ist.",
                              "Aufheben", "negative", zuruecknehmen)) \
                    .props("outline no-caps color=negative")
        ui.label("Der Filter „Mitarbeiter“ oben wirkt mit – so lässt sich auch einzeln "
                 "abrechnen.").classes("text-[11px] text-slate-400")


def _admin_zeiten(apts, staff, on_change, dlg_slot):
    all_entries = [e for e in timetrack.entries() if e.get("checkout")]
    months = sorted({_billing_month(e["checkin"]) for e in all_entries}, reverse=True) \
        or [_billing_month(date.today().isoformat())]
    state = {"month": months[0], "user": None}
    box = ui.column().classes("w-full gap-2")

    def render():
        box.clear()
        with box:
            with ui.row().classes("items-end gap-2 flex-wrap"):
                msel = ui.select({m: _month_label(m) for m in months}, value=state["month"],
                                 label="Abrechnungsmonat").props("outlined dense").classes("min-w-[170px]")
                msel.on_value_change(lambda e: (state.update(month=e.value), render()))
                ppl = {None: "Alle Mitarbeiter",
                       **{u: (staff.get(u) or u) for u in sorted({x["user"] for x in all_entries})}}
                usel = ui.select(ppl, value=state["user"], label="Mitarbeiter") \
                    .props("outlined dense").classes("min-w-[180px]")
                usel.on_value_change(lambda e: (state.update(user=e.value), render()))
            st, en = _billing_period(state["month"])
            ui.label(f"Zeitraum {st.strftime('%d.%m.')}–{en.strftime('%d.%m.%Y')} "
                     "(Meldung zum 19., spätere Stunden im Folgemonat)") \
                .classes("text-xs text-slate-500")
            rows = [e for e in all_entries
                    if _billing_month(e["checkin"]) == state["month"]
                    and (state["user"] is None or e["user"] == state["user"])]
            agg = _zeit_aggregat(rows)
            money = _has_rates()
            total = sum(a["total_minutes"] for a in agg.values())
            total_eur = round(sum(a["total_amount"] for a in agg.values()), 2)
            ui.label(f"{_month_label(state['month'])} · Summe {_hours_num(total)} Stunden"
                     + (f" · {_eur(total_eur)}" if money and total_eur else "")) \
                .classes("font-semibold mt-1")
            for u, a in sorted(agg.items(), key=lambda x: -x[1]["total_minutes"]):
                we = a["minutes"][feiertage.WOCHENENDE]
                with ui.row().classes("w-full items-center gap-2"):
                    ui.icon("person").classes("text-primary")
                    with ui.column().classes("gap-0 flex-grow min-w-0"):
                        ui.label(staff.get(u, u)).classes("truncate")
                        if we > 0:
                            ui.label(f"Werktags {_hours_num(a['minutes'][feiertage.WERKTAG])} · "
                                     f"Wochenende/Feiertag {_hours_num(we)} Std") \
                                .classes("text-xs text-slate-400")
                    with ui.column().classes("gap-0 items-end shrink-0"):
                        ui.label(f"{_hours_num(a['total_minutes'])} Std").classes("font-medium")
                        if money and a["total_amount"]:
                            ui.label(_eur(a["total_amount"])).classes("text-xs text-slate-500")

            def send_stb():
                stb = (CFG.get("steuerberater_email") or "").strip()
                if not stb:
                    ui.notify("Keine Steuerberater-E-Mail (Einstellungen → Steuerberater).",
                              type="warning", timeout=8000); return
                if not rows:
                    ui.notify("Keine Zeiten im Zeitraum.", type="warning"); return
                body = _stb_email_body(state["month"], rows, staff)
                try:
                    mailer.send_document(
                        CFG, stb, f"Arbeitszeiten {_month_label(state['month'])} – LIVARO Suites",
                        body, f"arbeitszeiten_{state['month']}.csv", _zeit_csv_bytes(rows, True))
                    ui.notify(f"An {stb} gesendet ✓", type="positive", timeout=8000)
                except mailer.MailError as ex:
                    ui.notify(f"Versand fehlgeschlagen: {ex}", type="negative", timeout=10000)

            def preview():
                with ui.dialog() as dlg, ui.card().classes("w-[480px] max-w-full gap-2"):
                    ui.label("Vorschau E-Mail an Steuerberater").classes("font-bold")
                    ui.label(_stb_email_body(state["month"], rows, staff)) \
                        .classes("text-sm whitespace-pre-wrap")
                    with ui.row().classes("w-full justify-end"):
                        ui.button("Schließen", on_click=dlg.close).props("flat")
                dlg.open()

            with ui.row().classes("gap-2 mt-2 flex-wrap"):
                ui.button("An Steuerberater senden", icon="send", on_click=send_stb) \
                    .props("unelevated no-caps") \
                    .tooltip(CFG.get("steuerberater_email") or "keine E-Mail konfiguriert")
                ui.button("Vorschau", icon="visibility", on_click=preview).props("outline no-caps")
                ui.button("CSV", icon="download",
                          on_click=lambda: ui.download.content(
                              _zeit_csv_bytes(rows, True), f"arbeitszeiten_{state['month']}.csv",
                              media_type="text/csv")).props("outline no-caps")
            # on_change (nicht das lokale render): _admin_zeiten hält all_entries
            # außerhalb von render() fest – nur der äußere Neuaufbau liest frisch.
            _abrechnen_block(rows, state["month"], on_change, dlg_slot)
            _zeit_list(rows, apts, True, staff, on_change, "Einzelne Einträge", True)
    render()


# ------------------------------------------------- Lohnvorschau (Minijob)
def lohn_vorschau(user, jobs):
    """Was dieser Monat voraussichtlich bringt – und wie nah die Grenze ist.

    Wer sich eine Reinigung nimmt, sah bisher erst am 19., was dabei herauskam.
    Für einen Minijob ist das zu spät: Wird die Grenze überschritten, ist die
    Beschäftigung nicht mehr geringfügig, und das lässt sich rückwirkend nicht
    geradebiegen.

    Ohne gepflegten Stundensatz gibt es keine Vorschau – eine Zahl ohne Satz
    wäre geraten, und geraten hilft hier niemandem.
    """
    ucfg, defs = USERS.get(user), _rate_defaults()
    satz = timetrack.rate_for(feiertage.WERKTAG, ucfg, defs)
    if not satz:
        return

    p = lohn.prognose(user, jobs, ucfg, defs)
    anteil = min(1.0, p["auslastung"])
    # Kein Alarm: mehr zu arbeiten ist erlaubt, der Ueberhang bleibt als
    # Guthaben stehen. Farbe sagt nur, wie voll der Monat ist.
    if p["zeitkonto"]:
        farbe, ton_text = "primary", ton.TITEL
    elif anteil >= 0.85:
        farbe, ton_text = "warning", ton.DRINGEND
    else:
        farbe, ton_text = "primary", ton.ERFOLG

    with ui.card().classes(ton.KARTE_ENG).mark("lohn-vorschau"):
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.icon("savings").classes("text-primary text-xl shrink-0")
            ui.label(t("Voraussichtlich in diesem Monat")).classes("font-semibold")
            ui.space()
            ui.label(f"{_month_label(p['monat'])}").classes(f"text-xs {ton.STILL}")

        with ui.row().classes("items-baseline gap-2 no-wrap"):
            ui.label(_eur(p["auszahlbar"])).classes(
                f"text-3xl font-bold leading-none {ton_text}").mark("lohn-summe")
            ui.label(t("von {grenze} € Grenze", grenze=p["grenze"])).classes(
                f"text-sm {ton.LEISE}")

        ui.linear_progress(value=anteil, show_value=False) \
            .props(f"color={farbe} rounded track-color=grey-3 size=8px").classes("w-full")

        with ui.row().classes("w-full items-center gap-3 flex-wrap"):
            ui.label(t("erfasst {betrag}", betrag=_eur(p["verdient"]))) \
                .classes(f"text-xs {ton.LEISE}")
            if p["einsaetze_offen"]:
                ui.label(t("+ {n} zugewiesene Reinigung(en) ≈ {betrag}",
                           n=p["einsaetze_offen"], betrag=_eur(p["erwartet"]))) \
                    .classes(f"text-xs {ton.LEISE}")
            if p["vortrag"]:
                ui.label(t("+ {betrag} aus dem Zeitkonto", betrag=_eur(p["vortrag"]))) \
                    .classes(f"text-xs {ton.LEISE}")

        if p["zeitkonto"]:
            with ui.row().classes(f"w-full items-center gap-2 no-wrap rounded-lg p-2 "
                                  f"{ton.FLAECHE_RUHIG}").mark("zeitkonto"):
                ui.icon("account_balance_wallet").classes(f"{ton.GEDECKT} text-base shrink-0")
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(t("{betrag} gehen aufs Zeitkonto",
                               betrag=_eur(p["zeitkonto"]))) \
                        .classes(f"text-sm font-medium {ton.TEXT}")
                    ui.label(t("Die Stunden sind nicht weg – sie werden in einem Monat "
                               "mit Luft ausgezahlt.")).classes(f"text-xs {ton.LEISE}")
        elif anteil >= 0.85:
            ui.label(t("Noch {betrag} bis zur Grenze.", betrag=_eur(p["rest"]))) \
                .classes(f"text-xs font-medium {ton.DRINGEND}")

        ui.label(t("Geschätzt mit {min} Min. je Reinigung – dein bisheriger Schnitt.",
                   min=p["dauer_schnitt"])).classes(f"text-xs {ton.STILL}")
