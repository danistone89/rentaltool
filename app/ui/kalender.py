"""Buchungskalender: Zeitleiste ueber alle Wohnungen und Monatsblatt einer Wohnung."""

from nicegui import ui
from datetime import date
from app import bookings, data, smoobu
from app.ui.basis import (_apts, t)
from app.ui import buchungen, dialog  # noqa: F401  (Ringschluss, siehe Kopf)

_MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
           "August", "September", "Oktober", "November", "Dezember"]
_APT_HEX = ["#5E2A84", "#0F766E", "#B45309", "#BE185D", "#1D4ED8",
            "#4338CA", "#047857", "#9333EA"]


def _apt_hex(apt_id):
    """Stabile Farbe je Wohnung (nach Reihenfolge der Apartments)."""
    ids = list(_apts().keys())
    try:
        idx = ids.index(apt_id)
    except ValueError:
        idx = int(apt_id) if isinstance(apt_id, int) else 0
    return _APT_HEX[idx % len(_APT_HEX)]


def _render_calendar(user, admin, staff, activate):
    today = date.today()
    apts = _apts()
    state = {"mode": "multi", "start": today.isoformat(),
             "y": today.year, "m": today.month, "apt": next(iter(apts), None)}
    box = ui.column().classes("w-full gap-2")

    def render():
        box.clear()
        with box:
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                mode = ui.toggle({"multi": t("Alle Wohnungen"), "single": t("Einzeln")},
                                 value=state["mode"]).props("no-caps")
                mode.on_value_change(lambda e: (state.update(mode=e.value), render()))
                if state["mode"] == "single" and apts:
                    sel = ui.select(apts, value=state["apt"], label=t("Wohnung")) \
                        .props("dense outlined").classes("min-w-[200px]")
                    sel.on_value_change(lambda e: (state.update(apt=e.value), render()))
            if state["mode"] == "single":
                _single_month(state, user, admin, staff, activate, render)
            else:
                _timeline(state, user, admin, staff, activate, render)
    render()


def _shift_days(state, delta, rerender):
    from datetime import timedelta
    state["start"] = (date.fromisoformat(state["start"]) + timedelta(days=delta)).isoformat()
    rerender()


def _shift_month(state, delta, rerender):
    m, y = state["m"] + delta, state["y"]
    while m < 1:
        m += 12; y -= 1
    while m > 12:
        m -= 12; y += 1
    state["y"], state["m"] = y, m
    rerender()


def _timeline(state, user, admin, staff, activate, rerender):
    """Reservierungs-Timeline: Wohnungen als Zeilen, Tage als Spalten, Buchungen als
    Balken (skaliert mit weiteren Wohnungen). Klick auf einen Balken öffnet Details."""
    from datetime import timedelta
    CELL, LABELW, NDAYS = 58, 130, 21
    start = date.fromisoformat(state["start"])
    days = [start + timedelta(days=i) for i in range(NDAYS)]
    gs, ge = days[0].isoformat(), days[-1].isoformat()
    today = date.today()
    apts = _apts()
    try:
        raw = data._reservations(gs, ge)
    except smoobu.SmoobuError as ex:
        ui.notify(t("Smoobu: {fehler}", fehler=ex), type="negative", timeout=8000)
        raw = []
    by_apt = {}
    for b in raw:
        if not bookings.is_real(b):
            continue
        nb = bookings.normalize(b)
        if nb["arrival"] and nb["departure"] and nb["apartment_id"]:
            by_apt.setdefault(nb["apartment_id"], []).append(nb)
    for lst in by_apt.values():
        lst.sort(key=lambda x: x["arrival"])

    # Navigation
    with ui.row().classes("w-full items-center gap-1"):
        ui.button(icon="chevron_left", on_click=lambda: _shift_days(state, -7, rerender)) \
            .props("flat round dense")
        ui.label(f"{start.strftime('%d.%m.')} – {days[-1].strftime('%d.%m.%Y')}") \
            .classes("text-sm font-semibold min-w-[150px] text-center")
        ui.button(icon="chevron_right", on_click=lambda: _shift_days(state, 7, rerender)) \
            .props("flat round dense")
        ui.space()
        ui.button(t("Heute"), icon="today",
                  on_click=lambda: (state.update(start=date.today().isoformat()), rerender())) \
            .props("flat dense no-caps")

    lbl = f"width:{LABELW}px; flex:0 0 {LABELW}px"
    with ui.element("div").classes("w-full overflow-x-auto rounded-xl border border-slate-100"):
        with ui.column().classes("gap-0").style(f"min-width:{LABELW + NDAYS * CELL}px"):
            # Kopfzeile: Tage
            with ui.row().classes("no-wrap items-stretch gap-0 bg-slate-50 border-b border-slate-100"):
                ui.element("div").style(lbl)
                for d in days:
                    is_today = (d == today)
                    weekend = d.weekday() >= 5
                    with ui.column().classes("items-center justify-center gap-0 py-1") \
                            .style(f"width:{CELL}px; flex:0 0 {CELL}px"):
                        ui.label(buchungen._WD[d.weekday()]).classes(
                            "text-[10px] leading-none " + ("text-primary font-bold" if is_today
                            else ("text-blue-500" if weekend else "text-gray-400")))
                        ui.label(str(d.day)).classes(
                            "text-xs leading-tight " + ("text-primary font-bold" if is_today else "text-gray-600"))
            # Zeile je Wohnung
            grid_bg = ("background-image:repeating-linear-gradient(to right,"
                       "#eef2f7 0 1px,transparent 1px %dpx)" % CELL)
            for aid, name in apts.items():
                hexc = _apt_hex(aid)
                with ui.row().classes("no-wrap items-center gap-0 border-b border-slate-100").style("height:44px"):
                    with ui.row().classes("no-wrap items-center gap-1 px-2").style(lbl):
                        ui.element("div").classes("rounded-full shrink-0") \
                            .style(f"width:10px;height:10px;background:{hexc}")
                        ui.label(name).classes("text-sm font-medium truncate text-slate-700")
                    with ui.element("div").style(
                            f"position:relative; height:44px; width:{NDAYS * CELL}px; "
                            f"flex:0 0 {NDAYS * CELL}px; {grid_bg}"):
                        if gs <= today.isoformat() <= ge:
                            ti = (today - start).days
                            ui.element("div").style(
                                f"position:absolute; left:{ti * CELL}px; top:0; width:{CELL}px; "
                                "height:100%; background:rgba(94,42,132,0.07)")
                        for b in by_apt.get(aid, []):
                            a_idx = max((date.fromisoformat(b["arrival"]) - start).days, 0)
                            d_idx = min((date.fromisoformat(b["departure"]) - start).days, NDAYS)
                            if d_idx <= 0 or a_idx >= NDAYS or d_idx <= a_idx:
                                continue
                            w = (d_idx - a_idx) * CELL - 6
                            taken = "👤 " if bookings.assignee_of(b["id"]) else ""
                            bar = ui.label(taken + (b["guest"] or b["apartment_name"])).classes(
                                "absolute text-white text-xs truncate cursor-pointer rounded-full px-3 "
                                "shadow-sm hover:brightness-110").style(
                                f"left:{a_idx * CELL + 3}px; width:{w}px; top:8px; height:28px; "
                                f"line-height:28px; background:{hexc}") \
                                .tooltip(t("Reinigung übernommen") if taken else "")
                            bar.on("click", lambda _e, bk=b: dialog.open_booking_dialog(bk, user, admin, staff, activate))
            if not apts:
                ui.label(t("Keine Wohnungen geladen.")).classes("text-gray-500 p-4")


def _single_month(state, user, admin, staff, activate, rerender):
    """Monatskalender EINER Wohnung; Buchungen als durchgehende Balken pro Woche."""
    import calendar as _cal
    from datetime import timedelta
    aid = state["apt"]
    if not aid:
        ui.label(t("Keine Wohnung gewählt.")).classes("text-gray-500 mt-2")
        return
    name = _apts().get(aid, "")
    hexc = _apt_hex(aid)
    y, m = state["y"], state["m"]
    first = date(y, m, 1)
    start = first - timedelta(days=first.weekday())
    last = date(y, m, _cal.monthrange(y, m)[1])
    weeks = ((last - start).days) // 7 + 1
    gs = start.isoformat()
    ge = (start + timedelta(days=weeks * 7 - 1)).isoformat()
    try:
        raw = data._reservations(gs, ge)
    except smoobu.SmoobuError as ex:
        ui.notify(t("Smoobu: {fehler}", fehler=ex), type="negative", timeout=8000)
        raw = []
    bks = [bookings.normalize(b) for b in raw if bookings.is_real(b)]
    bks = [b for b in bks if b["apartment_id"] == aid and b["arrival"] and b["departure"]]
    bks.sort(key=lambda b: b["arrival"])

    # Kopf: Navigation
    with ui.row().classes("w-full items-center gap-1"):
        ui.button(icon="chevron_left", on_click=lambda: _shift_month(state, -1, rerender)) \
            .props("flat round dense")
        ui.label(f"{_MONTHS[m - 1]} {y}").classes("text-lg font-semibold min-w-[150px] text-center")
        ui.button(icon="chevron_right", on_click=lambda: _shift_month(state, 1, rerender)) \
            .props("flat round dense")
        ui.space()
        ui.chip(name).style(f"background:{hexc};color:white")
        ui.button(t("Heute"), icon="today",
                  on_click=lambda: (state.update(y=date.today().year, m=date.today().month), rerender())) \
            .props("flat dense no-caps")
    # Wochentags-Kopf
    with ui.row().classes("no-wrap w-full gap-0"):
        for wd in buchungen._WD:
            ui.label(wd).classes("text-xs font-medium text-gray-400 text-center").style("width:14.2857%")

    today = date.today()
    colpct = 100 / 7
    for w in range(weeks):
        ws = start + timedelta(days=w * 7)
        we = ws + timedelta(days=6)
        with ui.element("div").classes("relative w-full").style("min-height:78px"):
            # Hintergrund: 7 Tageszellen
            with ui.row().classes("no-wrap w-full gap-0"):
                for i in range(7):
                    d = ws + timedelta(days=i)
                    other = d.month != m
                    is_today = (d == today)
                    cc = "border border-slate-100 " + ("bg-violet-50 " if is_today else "")
                    with ui.element("div").classes(cc).style("width:14.2857%; min-height:78px"):
                        ui.label(str(d.day)).classes(
                            "text-xs px-1 pt-1 " + ("font-bold text-primary" if is_today
                            else ("text-gray-300" if other else "text-gray-500")))
            # Balken (durchgehend über die Woche)
            for b in bks:
                a = date.fromisoformat(b["arrival"])
                dep = date.fromisoformat(b["departure"])
                sc = max((a - ws).days, 0)
                ec = min((dep - ws).days, 7)        # exklusiv (deckt Nächte ab)
                if ec <= 0 or sc >= 7 or ec <= sc:
                    continue
                round_l = a >= ws                    # echter Anreisetag in dieser Woche
                round_r = dep <= we                  # echter Abreisetag in dieser Woche
                il = 3 if round_l else 0
                ir = 3 if round_r else 0
                style = (f"position:absolute; top:26px; height:22px; line-height:22px; "
                         f"left:calc({sc * colpct}% + {il}px); "
                         f"width:calc({(ec - sc) * colpct}% - {il + ir}px); "
                         f"background:{hexc};")
                if round_l:
                    style += "border-top-left-radius:9999px;border-bottom-left-radius:9999px;"
                if round_r:
                    style += "border-top-right-radius:9999px;border-bottom-right-radius:9999px;"
                taken = "👤 " if bookings.assignee_of(b["id"]) else ""
                label = (taken + (b["guest"] or name)) if (a >= ws) else ""
                bar = ui.label(label).classes(
                    "text-white text-xs truncate cursor-pointer px-2 shadow-sm hover:brightness-110") \
                    .style(style)
                bar.on("click", lambda _e, bk=b: dialog.open_booking_dialog(bk, user, admin, staff, activate))
