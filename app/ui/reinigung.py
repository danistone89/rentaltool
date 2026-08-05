"""Reinigung und Qualitaet: Checklisten-Durchgang, Schaeden, Bestand, Uebersicht.

Der Checklisten-Durchgang ist ueber `config.checklisten_aktiv` abschaltbar
(Vorgabe aus, siehe README).

Nutzt `buchungen` normal; `dialog` wird erst im Aufruf geladen, weil beide
einander brauchen.
"""

from nicegui import ui
from datetime import date
from app import bookings, data, housekeeping, mailer, timetrack
from app.ui.basis import (CFG, _apts, _checklisten_an, _cur_user, _d, _is_admin, _photo_button, _photo_thumb, _run_ist, t)
from app.ui import buchungen, dialog  # noqa: F401  (Ringschluss, siehe Kopf)

def _due_today():
    from datetime import date, timedelta
    today = date.today().isoformat()
    d_from = (date.today() - timedelta(days=92)).isoformat()
    try:
        bookings = data._reservations(d_from, today)
    except Exception:
        return []
    out = {}
    for b in bookings:
        if b.get("is-blocked-booking") or b.get("type") == "cancellation":
            continue
        if b.get("departure") == today:
            ap = b.get("apartment") or {}
            if ap.get("id"):
                out[ap["id"]] = ap.get("name")
    return list(out.items())


def _notify_damage(d):
    ec = CFG.get("email", {})
    if not (ec.get("absender") and ec.get("app_password")):
        return
    to = CFG.get("benachrichtigung_email") or ec.get("absender")
    body = (f"Neue Schadensmeldung\n\nApartment: {d['apartment_name']}\n"
            f"Raum: {d['room']}\nDringlichkeit: {d['urgency']}\n"
            f"Gemeldet von: {d['reporter']}\nZeit: {d['ts']}\n\n"
            f"Beschreibung:\n{d['desc']}\n")
    try:
        mailer.send_plain(CFG, to,
                          f"[LIVARO] Schaden {d['apartment_name']} ({d['urgency']})", body)
    except mailer.MailError:
        pass


def open_damage_dialog(apt_id, apt_name, reporter, on_saved=None, booking_id=None):
    photo = {"rel": None}
    with ui.dialog() as dlg, ui.card().classes("w-[460px] max-w-full gap-2"):
        ui.label(t("Schaden melden – {wohnung}", wohnung=apt_name)).classes("text-lg font-bold")
        room = ui.input("Raum/Bereich").props("dense outlined").classes("w-full")
        desc = ui.textarea(t("Was ist beschädigt?")).props("outlined").classes("w-full")
        urg = ui.select(["niedrig", "mittel", "hoch"], value="mittel",
                        label="Dringlichkeit").props("dense outlined").classes("w-full")
        thumb = ui.row()

        def saved(rel):
            photo["rel"] = rel
            thumb.clear()
            with thumb:
                _photo_thumb(f"/media/{rel}", "w-24 h-24")
        with ui.row().classes("items-center gap-2"):
            _photo_button("Foto (optional)", "damage", saved)

        def save():
            if not (desc.value or "").strip():
                ui.notify(t("Bitte Beschreibung angeben."), type="warning"); return
            d = housekeeping.add_damage(apt_id, apt_name, (room.value or "").strip(),
                                        desc.value.strip(), urg.value, photo["rel"], reporter,
                                        booking_id=booking_id)
            _notify_damage(d)
            ui.notify(t("Schaden gemeldet – Danke!"), type="positive")
            dlg.close()
            if on_saved:
                on_saved()
        with ui.row().classes("w-full justify-end"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Melden"), on_click=save).props("unelevated")
    dlg.open()


def _hk_header(title, subtitle):
    with ui.row().classes("w-full items-center gap-3"):
        ui.icon("cleaning_services").classes("text-3xl text-primary")
        with ui.column().classes("gap-0"):
            ui.label(title).classes("text-2xl font-bold text-slate-800 leading-tight")
            ui.label(subtitle).classes("text-sm text-gray-500")


def render_reinigung(activate=None):
    # "reinigung" wird nur noch aus einer Buchung geöffnet -> immer die Checklisten-
    # Durchgangs-Ansicht (auch für Admins, die eine Reinigung inspizieren).
    if not _checklisten_an():
        # Alle Einstiege sind ausgeblendet; wer trotzdem hier landet (alter Link,
        # offener Tab), soll nicht auf einer leeren Seite stehen.
        with ui.column().classes("w-full items-center gap-2 py-10"):
            ui.icon("checklist_rtl").classes("text-5xl text-gray-300")
            ui.label(t("Checklisten sind ausgeschaltet.")).classes("text-gray-600 font-medium")
            ui.label(t("Arbeitszeit starten und beenden reicht.")).classes("text-sm text-gray-500")
            if activate:
                ui.button(t("Zu den Reinigungen"), icon="cleaning_services",
                          on_click=lambda: activate("buchungen")) \
                    .props("unelevated no-caps").classes("mt-2")
        return
    reinigung_putzkraft(activate)


_ROOM_ICONS = {"bad": "bathtub", "wc": "wc", "küche": "kitchen", "kueche": "kitchen",
               "schlafzimmer": "bed", "wohnbereich": "weekend", "wohnzimmer": "weekend",
               "flur": "door_front", "balkon": "balcony", "allgemein": "home"}


def _room_icon(name):
    key = (name or "").lower()
    for k, ic in _ROOM_ICONS.items():
        if k in key:
            return ic
    return "checklist"


def reinigung_putzkraft(activate=None):
    user = _cur_user()
    apts = _apts()
    pre = buchungen._PENDING_REINIGUNG.pop("apt", None)
    ret = buchungen._PENDING_REINIGUNG.pop("return", None)
    bkid = buchungen._PENDING_REINIGUNG.pop("booking", None)
    co = buchungen._PENDING_REINIGUNG.pop("co", None)
    ci = buchungen._PENDING_REINIGUNG.pop("ci", None)
    nxt = buchungen._PENDING_REINIGUNG.pop("next", None)
    same_day = buchungen._PENDING_REINIGUNG.pop("same_day", False)
    state = {"apt": pre, "return": ret, "booking": bkid, "co": co, "ci": ci,
             "next": nxt, "same_day": same_day, "group": True, "collapsed": set()}
    body = ui.column().classes("w-full gap-4")

    def open_apt(aid, anm):
        state["apt"] = (aid, anm); render()

    def _photo_dialog(run, task):
        with ui.dialog() as dlg, ui.card().classes("w-[380px] max-w-full gap-2"):
            ui.label(task["text"]).classes("font-bold")
            with ui.row().classes("gap-3 flex-wrap"):
                if task.get("ref_photo"):
                    with ui.column().classes("items-center gap-0"):
                        _photo_thumb(f"/media/{task['ref_photo']}", "w-24 h-24")
                        ui.label(t("Soll")).classes("text-xs text-gray-400")
                istc = ui.column().classes("items-center gap-1")

                def draw():
                    istc.clear()
                    with istc:
                        p = _run_ist(run["id"], task["id"])
                        if p:
                            _photo_thumb(f"/media/{p}", "w-24 h-24")
                            ui.button("entfernen", on_click=lambda: (
                                housekeeping.update_task(run["id"], task["id"], ist_photo=""),
                                draw(), render())).props("flat dense no-caps size=sm")
                        else:
                            def saved(rel):
                                housekeeping.update_task(run["id"], task["id"], ist_photo=rel)
                                draw(); render()
                            _photo_button("Ist-Foto", "ist", saved)
                            ui.label(t("Ist")).classes("text-xs text-gray-400")
                draw()
            with ui.row().classes("w-full justify-end"):
                ui.button(t("Schließen"), on_click=dlg.close).props("flat")
        dlg.open()

    def _task_row(run, task):
        done = run["tasks"].get(task["id"], {}).get("done", False)
        has_photo = bool(_run_ist(run["id"], task["id"]))
        with ui.row().classes("w-full items-center gap-2 no-wrap py-1"):
            cb = ui.checkbox(value=done).props("dense")
            cb.on_value_change(lambda e, tid=task["id"]:
                               (housekeeping.update_task(run["id"], tid, done=e.value), render()))
            ui.label(task["text"]).classes(
                "flex-grow text-sm " + ("line-through text-gray-400" if done else "text-slate-700"))
            ui.button(icon="photo_camera", on_click=lambda: _photo_dialog(run, task)) \
                .props("flat round dense").classes("text-green-600" if has_photo else "text-primary") \
                .tooltip(t("Foto"))

    def _picker():
        _hk_header("Reinigung", "Checkliste, Fotonachweis, Schäden & Bestand")
        with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-2"):
            due = _due_today()
            if due:
                ui.label(t("Heute fällig (nach Abreise):")).classes("font-medium")
                with ui.row().classes("gap-2 flex-wrap"):
                    for aid, anm in due:
                        ui.button(anm, icon="event_available",
                                  on_click=lambda a=aid, n=anm: open_apt(a, n)) \
                            .props("unelevated no-caps")
            ui.label(t("Apartment wählen:")).classes("text-sm text-gray-500 mt-1")
            with ui.row().classes("items-end gap-2"):
                sel = ui.select(apts, label=t("Apartment")).props("outlined dense").classes("min-w-[240px]")
                ui.button(t("Reinigung starten"), icon="play_arrow",
                          on_click=lambda: (open_apt(sel.value, apts.get(sel.value)) if sel.value
                                            else ui.notify(t("Bitte Apartment wählen."), type="warning"))) \
                    .props("unelevated no-caps")

    def render():
        body.clear()
        with body:
            if state["apt"] is None:
                _picker(); return
            aid, anm = state["apt"]
            run = housekeeping.start_run(aid, anm, user)
            cl = housekeeping.get_checklist(aid)
            all_tasks = [task for r in cl["rooms"] for task in r["tasks"]]
            total = len(all_tasks)
            done = sum(1 for task in all_tasks if run["tasks"].get(task["id"], {}).get("done"))

            # Kopfzeile: zurück + Titel + Menü
            with ui.row().classes("w-full items-center gap-2"):
                ui.button(icon="arrow_back",
                          on_click=lambda: (state.update(apt=None), render())).props("flat round color=primary")
                ui.label(anm).classes("text-xl font-bold text-primary")
                ui.space()
                with ui.button(icon="more_vert").props("flat round color=primary"):
                    with ui.menu():
                        ui.menu_item("Schaden melden", lambda: open_damage_dialog(aid, anm, user, booking_id=state.get("booking")))
                        ui.menu_item("Verbrauch / Wäsche",
                                     lambda: buchungen._restock_dialog({"apartment_id": aid, "apartment_name": anm, "id": state.get("booking")}, user))

            # Wohnungs-Karte mit Zeiten
            with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-4 gap-2"):
                with ui.row().classes("w-full items-center gap-2"):
                    ui.icon("apartment").classes("text-primary text-xl")
                    ui.label(anm).classes("font-bold text-lg")
                if state.get("co") or state.get("ci"):
                    with ui.row().classes("w-full items-center gap-4"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("logout").classes("text-deep-orange")
                            with ui.column().classes("gap-0"):
                                ui.label(t("Check-out")).classes("text-xs text-gray-500")
                                ui.label(state.get("co") or "—").classes("font-semibold")
                        ui.element("div").classes("w-px h-8 bg-slate-200")
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("login").classes("text-green-700")
                            with ui.column().classes("gap-0"):
                                ui.label(t("Check-in")).classes("text-xs text-gray-500")
                                ui.label(state.get("ci") or "—").classes("font-semibold")
                # Für wie viele einzudecken ist – hier, wo tatsächlich gearbeitet wird.
                if state.get("apt") and state.get("booking"):
                    buchungen._prep_panel(state.get("next"), state.get("same_day"))

            # Fortschritt
            with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-4 gap-1"):
                with ui.row().classes("w-full items-center"):
                    ui.label(t("Fortschritt")).classes("font-medium")
                    ui.space()
                    ui.label(f"{done} / {total} erledigt").classes("font-semibold")
                ui.linear_progress(value=(done / total if total else 0), show_value=False) \
                    .props("color=primary rounded track-color=grey-3").classes("w-full")

            # Räume & Aufgaben + Umschalter
            with ui.row().classes("w-full items-center gap-2"):
                ui.label(t("Räume & Aufgaben")).classes("font-medium")
                ui.space()
                ui.label(t("Nach Raum gruppieren")).classes("text-xs text-gray-500")
                sw = ui.switch(value=state["group"]).props("dense")
                sw.on_value_change(lambda e: (state.update(group=e.value), render()))

            if state["group"]:
                collapsed = state["collapsed"]
                for room in cl["rooms"]:
                    rtasks = room["tasks"]
                    if not rtasks:
                        continue
                    rn = room["name"]
                    rdone = sum(1 for task in rtasks if run["tasks"].get(task["id"], {}).get("done"))
                    is_open = rn not in collapsed
                    with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-3 gap-1"):
                        hdr = ui.row().classes("w-full items-center gap-2 cursor-pointer no-wrap")

                        def _toggle(name=rn):
                            (collapsed.discard(name) if name in collapsed else collapsed.add(name))
                            render()
                        hdr.on("click", _toggle)
                        with hdr:
                            with ui.element("div").classes("rounded-full bg-violet-50 p-1 flex"):
                                ui.icon(_room_icon(rn)).classes("text-primary text-lg")
                            ui.label(rn).classes("font-medium")
                            ui.space()
                            ui.label(f"{rdone} / {len(rtasks)} erledigt").classes("text-xs text-gray-500")
                            ui.icon("expand_less" if is_open else "expand_more").classes("text-gray-400")
                        ui.linear_progress(value=(rdone / len(rtasks) if rtasks else 0), show_value=False) \
                            .props("color=primary rounded track-color=grey-3 size=5px").classes("w-full")
                        if is_open:
                            for task in rtasks:
                                _task_row(run, task)
                # Alle aus-/einklappen
                if collapsed:
                    ui.button(t("Alle Aufgaben anzeigen"), icon="more_horiz",
                              on_click=lambda: (collapsed.clear(), render())) \
                        .props("flat no-caps color=primary").classes("w-full")
                else:
                    ui.button(t("Alle einklappen"), icon="unfold_less",
                              on_click=lambda: (state["collapsed"].update(r["name"] for r in cl["rooms"]), render())) \
                        .props("flat no-caps color=primary").classes("w-full")
            else:
                with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-3"):
                    for task in all_tasks:
                        _task_row(run, task)

            # Abschließen
            def finish():
                housekeeping.finish_run(run["id"])
                if state.get("booking"):
                    bookings.mark_checklist_done(state["booking"], user)
                ui.notify(t("Checkliste abgeschlossen ✓"), type="positive")
                if state.get("return") and activate:
                    activate(state["return"])
                else:
                    state.update(apt=None); render()
            ui.button(t("Checkliste abschließen"), icon="check_circle", on_click=finish) \
                .props("unelevated no-caps size=lg").classes("w-full mt-2")
    render()


def reinigung_uebersicht(activate=None):
    _hk_header("Übersicht", "Zusammenfassung aller Reinigungen, Schäden & Bestand")
    apts = _apts()
    listen = _checklisten_an()
    with ui.tabs().props("dense no-caps align=left").classes("w-full") as tabs:
        t_sum = ui.tab("Zusammenfassung", icon="insights")
        t_runs = ui.tab("Durchgänge", icon="fact_check") if listen else None
        t_dmg = ui.tab("Schäden", icon="report_problem")
        t_shop = ui.tab("Einkaufsliste", icon="shopping_cart")
        t_cfg = ui.tab("Konfiguration", icon="tune")
    with ui.tab_panels(tabs, value=t_sum).classes("w-full"):
        with ui.tab_panel(t_sum):
            _admin_summary(activate)
        if t_runs is not None:
            with ui.tab_panel(t_runs):
                _admin_runs()
        with ui.tab_panel(t_dmg):
            _admin_damages()
        with ui.tab_panel(t_shop):
            _admin_shopping()
        with ui.tab_panel(t_cfg):
            _admin_config(apts)


def _sum_kpi(label, value, icon, color="text-primary"):
    with ui.card().classes("rounded-xl shadow-sm border border-slate-100 p-3 items-center gap-0 min-w-[104px]"):
        ui.icon(icon).classes(color + " text-2xl")
        ui.label(str(value)).classes("text-2xl font-bold text-slate-800 leading-tight")
        ui.label(label).classes("text-xs text-gray-500")


def _admin_summary(activate):
    staff = buchungen._staff_users()
    jobs = buchungen._cleaning_jobs()
    statuses = [buchungen._booking_status(j) for j in jobs]
    fertig = statuses.count("abgeschlossen")
    ueberf = statuses.count("nachtragen")
    dmg_open = len(housekeeping.list_damages(only_open=True))
    rest_open = len(housekeeping.list_restock(only_open=True))
    with ui.row().classes("w-full gap-2 flex-wrap"):
        _sum_kpi("Reinigungen", len(jobs), "cleaning_services")
        _sum_kpi("Fertig", fertig, "check_circle", "text-green-600")
        _sum_kpi("Überfällig", ueberf, "warning", "text-red-600")
        _sum_kpi("Offene Schäden", dmg_open, "report_problem", "text-red-600")
        _sum_kpi("Einkäufe offen", rest_open, "shopping_cart", "text-primary")

    if not jobs:
        ui.label("Keine Reinigungen im Zeitraum.").classes("text-gray-500 mt-3"); return
    ui.label("Alle Reinigungen").classes("text-sm font-semibold text-gray-500 mt-3")
    listen = _checklisten_an()
    for j, st in zip(jobs, statuses):
        done_entries = [e for e in timetrack.entries_for_booking(j["id"]) if e.get("checkout")]
        total_min = sum(timetrack.duration_minutes(e) or 0 for e in done_entries)
        who = bookings.assignee_of(j["id"])
        wn = staff.get(who, who) if who else "nicht zugewiesen"
        card = ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 p-3 cursor-pointer") \
            .mark("uebersicht-buchung")
        card.on("click", lambda b=j: dialog.open_booking_dialog(b, _cur_user(), _is_admin(), staff, activate))
        with card:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.icon("home").classes("text-primary shrink-0")
                with ui.column().classes("gap-0 min-w-0 flex-grow"):
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.label(j["apartment_name"]).classes("font-medium truncate flex-grow min-w-0")
                        buchungen._status_chip(j)
                    zeile = [buchungen._dfmt(j["departure"]), wn]
                    if listen:
                        dprog, tprog = buchungen._checklist_progress(j, None)
                        zeile.append(f"Checkliste {dprog}/{tprog}")
                    zeile.append(timetrack.fmt_dur(total_min) if total_min else "0:00 h")
                    ui.label(" · ".join(zeile)).classes("text-xs text-gray-500 truncate")
                ui.icon("chevron_right").classes("text-gray-300 shrink-0")


def _admin_runs():
    runs = housekeeping.list_runs()
    if not runs:
        ui.label("Noch keine Durchgänge.").classes("text-gray-500"); return
    for r in runs:
        cl = housekeeping.get_checklist(r["apartment_id"])
        total = sum(len(room["tasks"]) for room in cl["rooms"])
        done = sum(1 for v in r["tasks"].values() if v.get("done"))
        status = "abgeschlossen" if r.get("finished") else "läuft"
        head = f"{r['apartment_name']} · {r['user']} · {_d(r['started'])} · {done}/{total} Aufgaben · {status}"
        nfotos = sum(1 for v in r["tasks"].values() if v.get("ist_photo"))
        with ui.expansion(head + (f" · {nfotos} Foto(s)" if nfotos else ""),
                          icon="cleaning_services").classes("w-full"):
            for room in cl["rooms"]:
                ui.label(room["name"]).classes("font-medium text-sm mt-2")
                for task in room["tasks"]:
                    st = r["tasks"].get(task["id"], {})
                    with ui.column().classes("w-full gap-1 pl-1 py-1 border-b border-slate-50"):
                        with ui.row().classes("w-full items-center gap-2"):
                            ui.icon("check_circle" if st.get("done") else "radio_button_unchecked") \
                                .classes("text-green-600" if st.get("done") else "text-gray-300")
                            ui.label(task["text"]).classes("text-sm")
                        if task.get("ref_photo") or st.get("ist_photo"):
                            with ui.row().classes("items-end gap-4 pl-7 flex-wrap"):
                                if task.get("ref_photo"):
                                    with ui.column().classes("items-center gap-0"):
                                        _photo_thumb(f"/media/{task['ref_photo']}", "w-16 h-16")
                                        ui.label("Soll").classes("text-xs text-gray-400")
                                if st.get("ist_photo"):
                                    with ui.column().classes("items-center gap-0"):
                                        _photo_thumb(f"/media/{st['ist_photo']}", "w-16 h-16")
                                        ui.label("Ist (Putzkraft)").classes("text-xs text-green-600")


def _admin_damages():
    dmg = housekeeping.list_damages()
    if not dmg:
        ui.label("Keine Schadensmeldungen.").classes("text-gray-500"); return
    for d in dmg:
        color = {"hoch": "text-red-700", "mittel": "text-amber-700"}.get(d["urgency"], "text-gray-600")
        with ui.card().classes("w-full"):
            # Datum/Melder unter den Titel, nicht daneben – nebeneinander läuft
            # die Zeile auf dem Handy über den rechten Rand.
            with ui.row().classes("w-full items-start gap-2 no-wrap"):
                ui.icon("report_problem").classes(color + " shrink-0 mt-0.5")
                with ui.column().classes("gap-0 min-w-0 flex-grow"):
                    with ui.row().classes("items-center gap-2 flex-wrap"):
                        ui.label(f"{d['apartment_name']} · {d['room']}").classes("font-semibold")
                        ui.label(d["urgency"]).classes(f"text-xs {color}")
                    ui.label(f"{_d(d['ts'])} · {d['reporter']}").classes("text-xs text-gray-500")
                if d["status"] == "offen":
                    ui.button("erledigt", icon="check",
                              on_click=lambda i=d["id"]: (housekeeping.set_damage_status(i, "erledigt"),
                                                          render_reinigung_refresh())) \
                        .props("flat dense no-caps")
                else:
                    ui.label("erledigt").classes("text-xs text-green-700")
            ui.label(d["desc"]).classes("text-sm")
            if d.get("photo"):
                _photo_thumb(f"/media/{d['photo']}", "w-40 h-40")


def _admin_shopping():
    items = housekeeping.list_restock(only_open=True)
    if not items:
        ui.label("Einkaufsliste ist leer.").classes("text-gray-500"); return
    for r in items:
        with ui.row().classes("w-full items-start gap-2 no-wrap"):
            ui.icon("shopping_cart").classes("text-primary shrink-0 mt-0.5")
            with ui.column().classes("gap-0 min-w-0 flex-grow"):
                ui.label(f"{r['menge']}× {r['item']}").classes("font-medium")
                ui.label(f"({r['apartment_name']}, {r['kategorie']})").classes("text-xs text-gray-500")
                ui.label(f"{_d(r['ts'])} · {r['reporter']}").classes("text-xs text-gray-400")
            ui.button("gekauft", icon="check",
                      on_click=lambda i=r["id"]: (housekeeping.set_restock_status(i, "erledigt"),
                                                  render_reinigung_refresh())) \
                .props("flat dense no-caps")


def render_reinigung_refresh():
    ui.navigate.to("/")   # einfacher Refresh nach Statusänderung


def _admin_config(apts):
    listen = _checklisten_an()
    ui.label("Checkliste & Bestand je Wohnung. Pro Aufgabe ein Beispielfoto (Soll-Zustand) "
             "aufnehmen – die Putzkraft sieht es dann in der Checkliste."
             if listen else
             "Bestandsliste je Wohnung – daraus wählt die Putzkraft unter "
             "„Verbrauch / Wäsche“. Checklisten sind ausgeschaltet "
             "(Einstellungen → Reinigung).") \
        .classes("text-sm text-gray-500")
    sel = ui.select(apts, label="Wohnung wählen",
                    value=(next(iter(apts), None))).props("outlined dense") \
        .classes("w-full max-w-[320px]")
    box = ui.column().classes("w-full gap-2")

    def render_cfg():
        box.clear()
        aid = sel.value
        if not aid:
            return
        cl = housekeeping.get_checklist(aid)
        inv = housekeeping.get_inventory(aid)
        room_inputs = []   # (room_dict, input)
        task_inputs = []   # (task_dict, input)
        inv_inputs = []    # (item_dict, name_input, kat_select)

        def collect():
            """Aktuelle Feldwerte in die Datenstrukturen übernehmen."""
            for room, f in room_inputs:
                room["name"] = f.value
            for task, f in task_inputs:
                task["text"] = f.value
            for it, nf, kf in inv_inputs:
                it["name"] = nf.value
                it["kategorie"] = kf.value

        def persist(notify=True):
            collect()
            housekeeping.save_checklist(aid, cl)
            housekeeping.save_inventory(aid, inv)
            if notify:
                ui.notify("Konfiguration gespeichert ✓", type="positive")

        with box:
            if listen:
                with ui.row().classes("w-full items-center gap-2"):
                    ui.label("Räume & Aufgaben").classes("font-medium")
                    ui.space()
                    ui.button("Speichern", icon="save", on_click=lambda: persist()) \
                        .props("unelevated no-caps")
                for ri, room in enumerate(cl["rooms"]):
                    with ui.card().classes("w-full gap-1"):
                        with ui.row().classes("w-full items-center gap-2"):
                            rn = ui.input("Raum", value=room["name"]).props("dense outlined").classes("w-56")
                            room_inputs.append((room, rn))
                            ui.space()
                            ui.button(icon="delete", on_click=lambda i=ri: (collect(), cl["rooms"].pop(i), housekeeping.save_checklist(aid, cl), render_cfg())) \
                                .props("flat dense round color=negative")
                        for ti, task in enumerate(room["tasks"]):
                            with ui.column().classes("w-full gap-1 py-1 border-b border-slate-50"):
                                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                                    tt = ui.input("Aufgabe", value=task["text"]).props("dense outlined").classes("flex-grow")
                                    task_inputs.append((task, tt))
                                    ui.button(icon="delete", on_click=lambda i=ti, rm=room: (collect(), rm["tasks"].pop(i), housekeeping.save_checklist(aid, cl), render_cfg())) \
                                        .props("flat dense round color=negative").tooltip("Aufgabe löschen")

                                def ref_saved(rel, tid=task["id"]):
                                    collect()
                                    housekeeping.save_checklist(aid, cl)
                                    housekeeping.set_task_ref_photo(aid, tid, rel)
                                    render_cfg()

                                def ref_remove(tid=task["id"]):
                                    collect()
                                    housekeeping.save_checklist(aid, cl)
                                    housekeeping.set_task_ref_photo(aid, tid, None)
                                    render_cfg()
                                with ui.row().classes("w-full items-center gap-2 flex-wrap pl-1"):
                                    if task.get("ref_photo"):
                                        _photo_thumb(f"/media/{task['ref_photo']}", "w-16 h-16")
                                        ui.label("Beispielfoto").classes("text-xs text-gray-400")
                                        _photo_button("ändern", "ref", ref_saved, icon="photo_camera")
                                        ui.button("entfernen", icon="close", on_click=ref_remove) \
                                            .props("flat dense no-caps size=sm color=negative")
                                    else:
                                        _photo_button("Beispielfoto", "ref", ref_saved, icon="add_a_photo")
                                        ui.label("(Soll-Zustand fotografieren)").classes("text-xs text-gray-400")
                        ui.button("Aufgabe hinzufügen", icon="add",
                                  on_click=lambda rm=room: (collect(), rm["tasks"].append({"id": housekeeping._uid(), "text": "Neue Aufgabe", "ref_photo": None}), housekeeping.save_checklist(aid, cl), render_cfg())) \
                            .props("flat dense no-caps")
                ui.button("Raum hinzufügen", icon="add_home",
                          on_click=lambda: (collect(), cl["rooms"].append({"name": "Neuer Raum", "tasks": []}), housekeeping.save_checklist(aid, cl), render_cfg())) \
                    .props("outline no-caps")

            ui.separator()
            ui.label("Bestandsliste (Verbrauch/Wäsche)").classes("font-medium")
            for ii, it in enumerate(inv):
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    nm = ui.input("Artikel", value=it["name"]).props("dense outlined").classes("flex-grow min-w-[140px]")
                    ka = ui.select({"verbrauch": "Verbrauch", "waesche": "Wäsche"},
                                   value=it.get("kategorie", "verbrauch")).props("dense outlined").classes("w-32")
                    inv_inputs.append((it, nm, ka))
                    ui.button(icon="delete", on_click=lambda i=ii: (collect(), inv.pop(i), housekeeping.save_inventory(aid, inv), render_cfg())) \
                        .props("flat dense round color=negative")
            ui.button("Artikel hinzufügen", icon="add",
                      on_click=lambda: (collect(), inv.append({"id": housekeeping._uid(), "name": "Neuer Artikel", "kategorie": "verbrauch"}), housekeeping.save_inventory(aid, inv), render_cfg())) \
                .props("flat dense no-caps")

            ui.separator()
            with ui.row().classes("w-full justify-end"):
                ui.button("Konfiguration speichern", icon="save", on_click=lambda: persist()) \
                    .props("unelevated no-caps")

    sel.on_value_change(lambda e: render_cfg())
    render_cfg()
