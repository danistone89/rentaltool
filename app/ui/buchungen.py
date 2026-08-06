"""Buchungen: Reinigungslisten (eigene/alle), Tagesgruppen, Reinigungskarten.

Herzstueck des Alltags. Die Regel "eine grosse Personenzahl gibt es nur einmal,
und die meint immer die Anreise" wird hier durchgehalten (siehe README).

Dieses Modul ist die Drehscheibe der Buchungs-Bereiche: `dialog`, `kalender` und
`reinigung` greifen darauf zu. Umgekehrt werden sie hier ueber das Modulobjekt
angesprochen, damit sich die Importe nicht im Kreis drehen.
"""

from nicegui import ui
from datetime import date
from app import bookings, data, housekeeping, i18n, ical, smoobu, timetrack
from app.ui.basis import (USERS, _checklisten_an, _cur_area, _cur_user, _is_admin,
                          bereichskopf, leer, stoerung, t)
from app.ui.standort import (_match_geofence, get_location)
from app.ui import dialog, kalender, reinigung
from app.ui import planung as ui_planung  # noqa: F401  (Ringschluss, siehe Kopf)
from app.ui import ton

# ---------------------------------------------------------------- Buchungen
_PENDING_REINIGUNG = {}   # {"apt": (id, name)} – Workflow-Sprung Buchung → Checkliste

# Kam der letzte Abruf bei Smoobu durch? Ohne diesen Merker sieht ein Ausfall
# aus wie Feierabend: es kommen null Buchungen zurück, und die Liste meldet
# „Keine anstehenden Reinigungen" – die gefährlichste Falschauskunft der App.
_ABRUF = {"fehler": None}


def abruf_fehler():
    """Fehlertext des letzten Smoobu-Abrufs; None, wenn er durchkam."""
    return _ABRUF["fehler"]


def _staff_users():
    """{username: Anzeigename} aller Mitarbeiter (Putzkräfte + Admins)."""
    return {u: (info.get("name") or u) for u, info in USERS.items()}


def _user_email(username):
    return (USERS.get(username, {}) or {}).get("email", "")


_WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_WD_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _dfmt(iso):
    try:
        d = date.fromisoformat(iso)
        wd = (_WD_EN if i18n.lang() == "en" else _WD)[d.weekday()]
        return f"{wd} {d.strftime('%d.%m.')}"
    except Exception:
        return iso or ""


def _persons_text(nb, explicit_children=False):
    """'2 Erwachsene · 1 Kind'. Mit explicit_children auch 'keine Kinder',
    damit im Wechsel klar ist, dass wirklich keine gebucht sind."""
    a, c = nb.get("adults") or 0, nb.get("children") or 0
    parts = []
    if a:
        parts.append(t("1 Erwachsener") if a == 1 else t("{n} Erwachsene", n=a))
    if c:
        parts.append(t("1 Kind") if c == 1 else t("{n} Kinder", n=c))
    elif explicit_children and a:
        parts.append(t("keine Kinder"))
    return " · ".join(parts) or t("{n} Pers.", n=nb.get("persons", 0))


def _guest_persons(nb, explicit_children=False):
    """'Max Mustermann · 2 Erwachsene · 1 Kind'"""
    return f"{nb.get('guest') or t('Gast')} · {_persons_text(nb, explicit_children)}"


def _pers_count(nb):
    """Personen einer Buchung (Erwachsene + Kinder)."""
    if not nb:
        return 0
    return (nb.get("adults") or 0) + (nb.get("children") or 0) or (nb.get("persons") or 0)


def _prep_panel(nxt, same_day):
    """Der 'Vorbereiten für N'-Block – die EINZIGE Stelle mit einer grossen
    Personenzahl. Die Abreise-Zahl steht bewusst nirgends so prominent, damit
    das Putzteam nicht für die abreisenden statt für die anreisenden Gäste
    eindeckt."""
    if not nxt:
        with ui.row().classes(f"w-full items-center gap-2 rounded-xl p-3 {ton.FLAECHE_RUHIG}"):
            ui.icon("event_busy").classes("text-slate-400")
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(t("keine Folgebuchung")).classes("font-medium text-slate-600")
                ui.label(t("Nichts vorzubereiten – nur reinigen.")).classes("text-xs text-slate-500")
        return
    n = _pers_count(nxt)
    # Wechseltag ist die einzige Lage, die heute noch eilt – dafuer gibt es
    # DRINGEND. Alles andere ist schlicht in Ordnung.
    tone, txt = ((ton.FLAECHE_DRINGEND, ton.AUF_DRINGEND) if same_day
                 else (ton.FLAECHE_ERFOLG, ton.AUF_ERFOLG))
    with ui.column().classes(f"w-full gap-0 rounded-xl p-3 {tone}").mark("prep-block"):
        with ui.row().classes("w-full items-center gap-1 no-wrap"):
            ui.icon("login").classes(f"{txt} text-base shrink-0")
            ui.label(t("Vorbereiten für")).classes(
                f"text-xs font-semibold uppercase tracking-wide {txt}")
        with ui.row().classes("items-baseline gap-2 no-wrap"):
            ui.label(str(n)).classes(f"text-4xl font-extrabold leading-none {txt}").mark("prep-count")
            ui.label(t("Person") if n == 1 else t("Personen")).classes(
                f"text-base font-semibold {txt}")
        ui.label(_persons_text(nxt, True)).classes(f"text-sm {txt} leading-tight")
        ui.label(nxt.get("guest") or t("Gast")).classes(
            "text-sm text-slate-600 truncate leading-tight mt-1")
        ui.label(f"{t('Anreise')} {_dfmt(nxt['arrival'])} · {nxt['checkin_time'] or '—'}") \
            .classes("text-xs text-slate-500 leading-tight")
        if same_day:
            with ui.row().classes("w-full items-center gap-1 no-wrap mt-1"):
                ui.icon("bolt").classes(f"{ton.DRINGEND} text-sm shrink-0")
                ui.label(t("Wechseltag – Anreise noch heute")).classes(
                    f"text-xs font-semibold {ton.DRINGEND}")


def _depart_panel(job):
    """Abreise-Angaben – bewusst neutral/klein gehalten (siehe _prep_panel)."""
    with ui.column().classes(f"w-full gap-0 rounded-xl p-3 {ton.FLAECHE_RUHIG}") \
            .mark("depart-block"):
        with ui.row().classes("w-full items-center gap-1 no-wrap"):
            ui.icon("logout").classes("text-slate-500 text-base shrink-0")
            ui.label(t("Es reist ab")).classes(
                "text-xs font-semibold uppercase tracking-wide text-slate-500")
        ui.label(job.get("guest") or t("Gast")).classes(
            "font-medium text-slate-700 truncate leading-tight")
        ui.label(_persons_text(job, True)).classes("text-sm text-slate-600 leading-tight")
        ui.label(f"{t('Check-out')} {_dfmt(job['departure'])} · {job.get('checkout_time') or '—'}") \
            .classes("text-xs text-slate-500 leading-tight")
        ui.label(t("Nur zur Info – nicht die Zahl für die Vorbereitung.")) \
            .classes("text-xs text-slate-400 italic mt-1")


def _ab_an_tabs(job, nxt, same_day):
    """Abreise und Anreise in getrennten Tabs statt untereinander – Standard ist
    'Vorbereiten', weil nur diese Zahl fürs Eindecken zählt."""
    with ui.tabs().props("dense no-caps align=left").classes("w-full") as tabs:
        tab_prep = ui.tab(t("Vorbereiten"), icon="login")
        tab_ab = ui.tab(t("Abreise"), icon="logout")
    with ui.tab_panels(tabs, value=tab_prep).classes("w-full"):
        with ui.tab_panel(tab_prep).classes("p-0 pt-2"):
            _prep_panel(nxt, same_day)
        with ui.tab_panel(tab_ab).classes("p-0 pt-2"):
            _depart_panel(job)


def _events_between(d_from, d_to):
    """An-/Abreise-Ereignisse mit Datum in [d_from, d_to] (unsortiert)."""
    try:
        raw = data._reservations(d_from, d_to)
    except smoobu.SmoobuError as ex:
        _ABRUF["fehler"] = str(ex)
        ui.notify(t("Smoobu: {fehler}", fehler=ex), type="negative", timeout=8000)
        return []
    _ABRUF["fehler"] = None
    evs = []
    for b in raw:
        if not bookings.is_real(b):
            continue
        nb = bookings.normalize(b)
        try:
            nb["nights"] = (date.fromisoformat(nb["departure"])
                            - date.fromisoformat(nb["arrival"])).days
        except Exception:
            nb["nights"] = None
        if nb["arrival"] and d_from <= nb["arrival"] <= d_to:
            evs.append({**nb, "kind": "in", "date": nb["arrival"], "time": nb["checkin_time"]})
        if nb["departure"] and d_from <= nb["departure"] <= d_to:
            evs.append({**nb, "kind": "out", "date": nb["departure"], "time": nb["checkout_time"]})
    return evs


def _fetch_events(days_ahead=21, days_back=1):
    """An- und Abreise-Ereignisse aus Smoobu im Zeitfenster, chronologisch sortiert."""
    from datetime import timedelta
    today = date.today()
    evs = _events_between((today - timedelta(days=days_back)).isoformat(),
                          (today + timedelta(days=days_ahead)).isoformat())
    evs.sort(key=lambda e: (e["date"], e["time"] or "99:99", e["apartment_name"]))
    return evs


def _cleaning_jobs(days_ahead=21, days_back=1, quiet=False):
    """Reinigungs-Jobs: jede Abreise im Fenster + die nächste Anreise (Folgebuchung)
    derselben Wohnung – damit die Putzkraft weiß, für wie viele Personen vorzubereiten.

    `quiet` unterdrückt die Fehlermeldung. Das braucht der Zähler in der Leiste:
    er läuft auf jeder Seite mit, und zwei gleiche Meldungen zu einer Störung
    sind eine zu viel – gemeldet wird sie von der Liste, die man ansieht.
    """
    from datetime import timedelta
    today = date.today()
    d_from = (today - timedelta(days=days_back)).isoformat()
    d_to = (today + timedelta(days=days_ahead)).isoformat()
    look_to = (today + timedelta(days=days_ahead + 120)).isoformat()  # weit für Folgebuchung
    try:
        raw = data._reservations(d_from, look_to)
    except smoobu.SmoobuError as ex:
        _ABRUF["fehler"] = str(ex)
        if not quiet:
            ui.notify(t("Smoobu: {fehler}", fehler=ex), type="negative", timeout=8000)
        return []
    _ABRUF["fehler"] = None
    norm = [bookings.normalize(b) for b in raw if bookings.is_real(b)]
    by_apt = {}
    for nb in norm:
        by_apt.setdefault(nb["apartment_id"], []).append(nb)
    jobs = []
    for nb in norm:
        if not (nb["departure"] and d_from <= nb["departure"] <= d_to):
            continue
        nxt = None
        for cand in by_apt.get(nb["apartment_id"], []):
            if cand["id"] == nb["id"] or not cand["arrival"]:
                continue
            if cand["arrival"] >= nb["departure"] and (nxt is None or cand["arrival"] < nxt["arrival"]):
                nxt = cand
        jobs.append({**nb, "next": nxt})
    jobs.sort(key=lambda j: (j["departure"], j["checkout_time"] or "99:99", j["apartment_name"]))
    return jobs


def nav_zaehler(user, verwaltung):
    """Die eine Zahl auf dem Platz „Reinigungen“ in der Leiste.

    Genau ein Zähler in der ganzen App – mehr Zähler heißt: keiner wird mehr
    gelesen. Was er zählt, hängt davon ab, wofür man die App öffnet:

    * **Putzkraft** – was heute ansteht: die eigenen Aufträge von heute, die
      noch nicht fertig sind.
    * **Verwaltung** – was in sieben Tagen noch niemandem gehört.

    Gibt 0 zurück, wenn nichts zu zeigen ist; 0 heißt „kein Zähler“. Eine Null
    anzuschreiben wäre eine Zahl, die nichts sagt, und entwertet die anderen.
    """
    from datetime import timedelta
    # Bewusst dasselbe Fenster wie die Reinigungsliste: so trifft der Abruf
    # denselben Zwischenspeicher und kostet Smoobu keinen zweiten Aufruf.
    jobs = _cleaning_jobs(quiet=True)
    heute = date.today()
    if verwaltung:
        grenze = (heute + timedelta(days=7)).isoformat()
        # Bewusst am Fehlen der Zuweisung gemessen, nicht am Status: eine
        # ueberfaellige Reinigung heisst "nachtragen" und gehoert trotzdem
        # niemandem – gerade die darf hier nicht durchrutschen.
        return sum(1 for j in jobs
                   if heute.isoformat() <= j["departure"] <= grenze
                   and not bookings.assignee_of(j["id"]))
    return sum(1 for j in jobs
               if j["departure"] == heute.isoformat()
               and bookings.assignee_of(j["id"]) == user
               and _booking_status(j) != "abgeschlossen")


def _open_checkliste(job, activate):
    """Sprung Buchung → Checkliste. Nimmt den ganzen Job mit, damit in der
    Checkliste steht, für wie viele Personen einzudecken ist."""
    nxt = job.get("next") or None
    _PENDING_REINIGUNG["apt"] = (job["apartment_id"], job["apartment_name"])
    _PENDING_REINIGUNG["return"] = _cur_area()   # dorthin zurück, wo man herkam
    _PENDING_REINIGUNG["booking"] = job.get("id")
    _PENDING_REINIGUNG["co"] = job.get("checkout_time")
    _PENDING_REINIGUNG["ci"] = (nxt or {}).get("checkin_time")
    _PENDING_REINIGUNG["next"] = nxt
    _PENDING_REINIGUNG["same_day"] = bool(nxt and nxt.get("arrival") == job.get("departure"))
    activate("reinigung")


# ------------------------------------------------------- Buchungs-/Reinigungs-Status
_STATUS = {
    "nicht_zugewiesen": ("Nicht zugewiesen", "grey-5", "person_off"),
    "zugewiesen":       ("Zugewiesen", "blue-6", "assignment_ind"),
    "in_progress":      ("In Arbeit", "green-6", "play_circle"),
    "abgeschlossen":    ("Fertig", "green-7", "check_circle"),
    "nachtragen":       ("Überfällig", "red-6", "warning"),
}


def _past_checkout(job):
    from datetime import datetime, time as _time_cls
    try:
        d = date.fromisoformat(job["departure"])
        hh, mm = (job.get("checkout_time") or "10:00").split(":")[:2]
        return datetime.now() > datetime.combine(d, _time_cls(int(hh), int(mm)))
    except Exception:
        return job.get("departure", "") < date.today().isoformat()


def _booking_status(job):
    """Status-Key. 'Fertig' heißt: Arbeitszeit erfasst – und, falls Checklisten
    eingeschaltet sind, zusätzlich die Checkliste vollständig abgehakt.

    Ohne diese Unterscheidung käme bei ausgeschalteten Checklisten NIE ein
    'Fertig' zustande, weil sich keine Checkliste mehr abhaken lässt.
    """
    bid = job["id"]
    who = bookings.assignee_of(bid)
    entries = timetrack.entries_for_booking(bid)
    has_time = any(e.get("checkout") for e in entries)
    open_now = any(not e.get("checkout") for e in entries)
    started = bool(entries)
    if _checklisten_an():
        dprog, tprog = _checklist_progress(job, None)
        fully_done = tprog > 0 and dprog >= tprog
    else:
        fully_done = True
    if fully_done and has_time:
        return "abgeschlossen"
    if open_now:
        return "in_progress"
    if _past_checkout(job):
        return "nachtragen"
    if started:
        return "in_progress"
    if who:
        return "zugewiesen"
    return "nicht_zugewiesen"


def _status_chip(job):
    label, color, icon = _STATUS[_booking_status(job)]
    ui.chip(t(label), icon=icon).props(f"color={color} text-color=white dense") \
        .classes("shrink-0 whitespace-nowrap")


def render_buchungen(activate):
    user = _cur_user()
    admin = _is_admin()
    bereichskopf("calendar_month", t("Buchungen"),
                 t("Reinigungs-Übersicht & Buchungskalender"),
                 lambda: ui.button(icon="refresh",
                                   on_click=lambda: (data.clear_cache(),
                                                     activate("buchungen")))
                 .props("flat round").tooltip(t("Aktualisieren")))
    staff = _staff_users()
    # „Meine Reinigungen“ ist die Startansicht: am Tagesanfang zählt, wofür man
    # selbst zuständig ist. Zuweisen passiert in „Alle Reinigungen“.
    with ui.tabs().props("dense no-caps align=left").classes("w-full") as tabs:
        t_meine = ui.tab(t("Meine Reinigungen"), icon="assignment_ind")
        t_alle = ui.tab(t("Alle Reinigungen"), icon="cleaning_services")
        t_cal = ui.tab(t("Kalender"), icon="calendar_month")
    with ui.tab_panels(tabs, value=t_meine).classes("w-full"):
        with ui.tab_panel(t_meine).mark("panel-meine"):
            _render_cleaning(user, admin, staff, activate, nur_eigene=True,
                             zu_allen=lambda: tabs.set_value(t_alle))
        with ui.tab_panel(t_alle).mark("panel-alle"):
            _render_cleaning(user, admin, staff, activate)
        with ui.tab_panel(t_cal):
            kalender._render_calendar(user, admin, staff, activate)


def _render_cleaning(user, admin, staff, activate, nur_eigene=False, zu_allen=None):
    """Reinigungsliste. `nur_eigene` blendet auf die eigenen Aufträge ein –
    das ist die Startansicht: am Tagesanfang zählt, wofür man zuständig ist.
    """
    jobs = _cleaning_jobs()

    def _stoerung():
        """Kein Abruf, keine Liste – das muss als Ausfall dastehen, nicht als
        leerer Tag."""
        stoerung(t("Die Buchungen konnten nicht geladen werden."),
                 abruf_fehler(),
                 nochmal=lambda: (data.clear_cache(), activate("buchungen")))

    if nur_eigene:
        jobs = [j for j in jobs if bookings.assignee_of(j["id"]) == user]
        if not jobs:
            if abruf_fehler():
                _stoerung()
            else:
                leer("assignment_turned_in",
                     t("Dir ist gerade keine Reinigung zugewiesen."),
                     t("Unter „Alle Reinigungen“ siehst du, was noch frei ist."),
                     (lambda: ui.button(t("Alle Reinigungen ansehen"),
                                        icon="cleaning_services", on_click=zu_allen)
                      .props("unelevated no-caps").classes("mt-2")) if zu_allen else None)
            return
    else:
        # Offene "Nachtragen"-Fälle einmalig per E-Mail anstoßen – nur hier,
        # damit die Erinnerung nicht zweimal je Seitenaufbau läuft.
        for j in jobs:
            if _booking_status(j) == "nachtragen":
                dialog._notify_nachtragen(j, staff)
    if not jobs:
        if abruf_fehler():
            _stoerung()
        else:
            leer("event_available", t("Keine anstehenden Reinigungen."),
                 t("In den nächsten drei Wochen steht keine Abreise an."))
        return
    today = date.today().isoformat()
    overdue = [j for j in jobs if _booking_status(j) == "nachtragen"]
    odids = {j["id"] for j in overdue}
    todayj = [j for j in jobs if j["departure"] == today and j["id"] not in odids]
    future = [j for j in jobs if j["departure"] > today and j["id"] not in odids]

    # Überfällig – volle Karten
    if overdue:
        ui.label(t("Überfällig ({n})", n=len(overdue))).classes("text-sm font-semibold text-red-700 mt-2")
        for j in overdue:
            _cleaning_card(j, user, admin, staff, activate)
    # Heute – volle Karten
    if todayj:
        ui.label(t("Heute ({n})", n=len(todayj))).classes("text-sm font-semibold text-primary mt-3")
        for j in todayj:
            _cleaning_card(j, user, admin, staff, activate)
    if not overdue and not todayj:
        ui.label(t("Für dich heute nichts zu tun. 🎉") if nur_eigene
                 else t("Heute keine Reinigungen. 🎉")).classes("text-slate-500 mt-2")

    # Kommende Tage – kompakt, ausklappbar
    if future:
        groups = {}
        for j in future:
            groups.setdefault(j["departure"], []).append(j)
        ui.label("KOMMENDE TAGE").classes("text-xs font-semibold tracking-wide text-slate-400 mt-4")
        offen_ges = 0
        for d in sorted(groups):
            offen_ges += sum(1 for j in groups[d] if not bookings.assignee_of(j["id"]))
        if offen_ges and not nur_eigene:
            with ui.row().classes(f"w-full items-center gap-2 no-wrap rounded-lg px-3 py-2 "
                                  f"{ton.AUF_HINWEIS} {ton.FLAECHE_HINWEIS}"):
                ui.icon("person_off").classes("text-amber-700 text-base shrink-0")
                ui.label(t("{n} Reinigung noch niemandem zugewiesen", n=offen_ges)
                         if offen_ges == 1 else
                         t("{n} Reinigungen noch niemandem zugewiesen", n=offen_ges)) \
                    .classes("text-sm font-medium")
                ui.space()
                # Alle auf einem Blatt statt Buchung für Buchung (app/ui/planung.py)
                ui.button(t("Offene zuweisen"), icon="assignment_ind",
                          on_click=lambda: ui_planung.offene_zuweisen_dialog(
                              jobs, ui_planung._staff(),
                              on_saved=lambda: activate(_cur_area()))) \
                    .props("unelevated dense no-caps size=sm").classes("shrink-0")
        for d in sorted(groups):
            _tagesgruppe(d, groups[d], user, admin, staff, activate, nur_eigene)


def _tagesgruppe(d, tagesjobs, user, admin, staff, activate, nur_eigene=False):
    """Ein ausklappbarer Tag. Der Kopf muss ohne Aufklappen zeigen, wie viele
    Reinigungen des Tages noch frei sind – bei zwei Buchungen an einem Tag ist
    oft nur eine davon zu vergeben.

    In der eigenen Liste (`nur_eigene`) ist das sinnlos – dort ist alles
    zugewiesen. Stattdessen stehen im Kopf die Wohnungen, damit man ohne
    Aufklappen sieht, wo man hin muss."""
    dd = date.fromisoformat(d)
    wd = (_WD_EN if i18n.lang() == "en" else _WD)[dd.weekday()]
    n = len(tagesjobs)
    offen, vergeben = [], []
    for j in tagesjobs:
        (vergeben if bookings.assignee_of(j["id"]) else offen).append(j)
    namen = sorted({staff.get(bookings.assignee_of(j["id"]),
                              bookings.assignee_of(j["id"])) for j in vergeben})

    # In der eigenen Liste gibt es nichts Freies – dann kein Warnrahmen.
    rahmen = "border-amber-300" if (offen and not nur_eigene) else "border-slate-100"
    exp = ui.expansion(value=False).classes(f"w-full border {rahmen} rounded-xl")
    with exp.add_slot("header"):
        # Die Chips stehen UNTER dem Datum, nicht daneben. Nebeneinander laufen
        # sie auf dem Handy über den rechten Rand (die Kopfzeile bricht nicht um,
        # und der Platz reicht neben Datum und Quasars Aufklapppfeil nicht).
        # Quasars Pfeil bleibt trotz eigenem Header-Slot erhalten – keinen
        # zweiten ergänzen.
        with ui.row().classes("w-full items-start gap-2 no-wrap"):
            ui.icon("event").classes(("text-amber-700" if (offen and not nur_eigene)
                                      else "text-slate-400")
                                     + " text-xl shrink-0 mt-0.5")
            with ui.column().classes("gap-1 min-w-0 flex-grow"):
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(f"{wd} {dd.strftime('%d.%m.')}") \
                        .classes("font-medium leading-tight whitespace-nowrap")
                    ui.label(t("{n} Reinigung", n=n) if n == 1 else t("{n} Reinigungen", n=n)) \
                        .classes("text-xs text-slate-500 leading-tight whitespace-nowrap")
                with ui.row().classes("items-center gap-1 flex-wrap"):
                    if nur_eigene:
                        for wohnung in sorted({j["apartment_name"] for j in tagesjobs}):
                            ui.chip(wohnung, icon="home") \
                                .props("color=primary text-color=white dense square") \
                                .classes("text-xs !ml-0")
                    else:
                        if offen:
                            ui.chip(t("{n} frei", n=len(offen)), icon="person_off") \
                                .props("color=amber-8 text-color=white dense square") \
                                .classes("text-xs !ml-0")
                        if vergeben:
                            # Namen statt Zahl, solange es wenige sind – das ist die
                            # Information, die man sonst durch Aufklappen sucht. Erst
                            # ab drei Namen wird die Kopfzeile davon zu voll.
                            if len(namen) <= 2:
                                for nm in namen:
                                    ui.chip(nm, icon="how_to_reg") \
                                        .props("color=green-7 text-color=white dense square") \
                                        .classes("text-xs !ml-0")
                            else:
                                ui.chip(t("{n} vergeben", n=len(vergeben)), icon="how_to_reg") \
                                    .props("color=green-7 text-color=white dense square") \
                                    .classes("text-xs !ml-0")
    with exp:
        for j in tagesjobs:
            _cleaning_compact(j, user, admin, staff, activate)


def _kalender_download(job):
    """Reinigungstermin als .ics herunterladen – für den eigenen Kalender."""
    try:
        ui.download.content(ical.cleaning_event(job), ical.dateiname(job),
                            media_type="text/calendar")
    except Exception as ex:                       # defekte Buchungsdaten
        ui.notify(t("Kalender-Datei konnte nicht erstellt werden: {fehler}", fehler=ex),
                  type="negative", timeout=8000)
        return
    start, ende = ical.zeitfenster(job)
    ui.notify(t("Termin {von}–{bis} Uhr heruntergeladen ✓",
                von=start.strftime("%H:%M"), bis=ende.strftime("%H:%M")),
              type="positive")


def _add_time_dialog(job, user, on_saved=None):
    """Arbeitszeit für diese Buchung manuell nachtragen."""
    from datetime import datetime
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(t("Arbeitszeit nachtragen – {wohnung}", wohnung=job["apartment_name"])).classes("text-lg font-bold")
        d = ui.input(t("Datum"), value=job["departure"]).props("type=date outlined dense").classes("w-full")
        with ui.row().classes("w-full gap-2"):
            t1 = ui.input(t("Von"), value=(job.get("checkout_time") or "10:00")) \
                .props("type=time outlined dense").classes("flex-grow")
            t2 = ui.input(t("Bis"), value="12:00").props("type=time outlined dense").classes("flex-grow")

        def save():
            try:
                ci = datetime.fromisoformat(f"{d.value}T{t1.value}")
                co = datetime.fromisoformat(f"{d.value}T{t2.value}")
            except Exception:
                ui.notify(t("Bitte Datum und Uhrzeiten prüfen."), type="warning"); return
            if co <= ci:
                ui.notify(t("Ende muss nach Beginn liegen."), type="warning"); return
            timetrack.add_manual(user, ci, co, booking_id=job["id"], apartment=job["apartment_name"])
            ui.notify(t("Arbeitszeit nachgetragen: {dauer}",
                        dauer=timetrack.fmt_dur(int((co - ci).total_seconds() // 60))),
                      type="positive")
            dlg.close()
            if on_saved:
                on_saved()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Speichern"), icon="save", on_click=save).props("unelevated")
    dlg.open()


def _checklist_progress(job, user):
    """(erledigt, gesamt) der Checkliste – zählt die TATSÄCHLICH abgehakten Aufgaben
    des relevanten Durchgangs (offen, sonst letzter für diese Wohnung)."""
    try:
        cl = housekeeping.get_checklist(job["apartment_id"])
        total = sum(len(r["tasks"]) for r in cl["rooms"])
    except Exception:
        total = 0
    run = housekeeping.get_open_run(job["apartment_id"], user)
    if not run:
        run = next((r for r in housekeeping.list_runs()
                    if str(r["apartment_id"]) == str(job["apartment_id"])), None)
    done = sum(1 for v in run["tasks"].values() if v.get("done")) if run else 0
    return min(done, total), total


def _step_button(label, icon, cb):
    """Listen-Zeile als Button (Icon · Label · Chevron)."""
    b = ui.button(on_click=cb).props("flat no-caps align=left").classes("w-full")
    with b:
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            ui.icon(icon).classes("text-primary")
            ui.label(label).classes("flex-grow text-left normal-case text-slate-700")
            ui.icon("chevron_right").classes("text-slate-300")


def _note_dialog(job, on_saved=None):
    rec = bookings.get_record(job["id"])
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(t("Notiz – {wohnung}", wohnung=job["apartment_name"])).classes("text-lg font-bold")
        ta = ui.textarea(t("Notiz"), value=rec.get("note", "")).props("outlined autogrow").classes("w-full")

        def save():
            bookings.set_field(job["id"], note=(ta.value or "").strip())
            ui.notify(t("Notiz gespeichert ✓"), type="positive"); dlg.close()
            if on_saved:
                on_saved()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Speichern"), icon="save", on_click=save).props("unelevated")
    dlg.open()


def _restock_dialog(job, user, on_close=None):
    with ui.dialog() as dlg, ui.card().classes("w-[440px] max-w-full gap-2"):
        ui.label(t("Verbrauch / Wäsche – {wohnung}", wohnung=job["apartment_name"])).classes("text-lg font-bold")
        ui.label(t("Was muss nachgekauft werden?")).classes("text-sm text-slate-500")
        for it in housekeeping.get_inventory(job["apartment_id"]):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(it["name"]).classes("flex-grow")
                qty = ui.input(t("Menge"), value="1").props("dense outlined").classes("w-20")

                def melden(name=it["name"], kat=it["kategorie"], q=qty):
                    housekeeping.add_restock(job["apartment_id"], job["apartment_name"],
                                             name, (q.value or "1").strip(), kat, user,
                                             booking_id=job.get("id"))
                    ui.notify(t("{name} gemeldet ✓", name=name), type="positive")
                ui.button(t("melden"), icon="add_shopping_cart", on_click=melden).props("flat dense no-caps")
        with ui.row().classes("w-full justify-end"):
            ui.button(t("Schließen"), on_click=lambda: (dlg.close(), on_close() if on_close else None)).props("flat")
    dlg.open()


def _cleaning_card(job, user, admin, staff, activate):
    """Voll-Karte gemäß Entwurf. Start/Stop zeichnet NUR diese Karte neu (kein
    Seiten-Sprung), daher lokales render() statt activate()."""
    from datetime import datetime
    nxt = job.get("next")
    same_day = bool(nxt and nxt["arrival"] == job["departure"])
    wrap = ui.column().classes("w-full")

    async def _do_in():
        gps = None
        try:
            loc = await get_location()
            gps = None if loc.get("error") else loc
        except Exception:
            pass
        ort, dist = _match_geofence(gps)
        if timetrack.check_in(user, gps, None, ort, dist,
                              booking_id=job["id"], apartment=job["apartment_name"]) is None:
            ui.notify(t("Du bist bereits an einem anderen Ort eingecheckt."), type="warning")
        else:
            ui.notify(t("Arbeitszeit gestartet ✓"), type="positive")
        render()

    async def _do_out():
        gps = None
        try:
            loc = await get_location()
            gps = None if loc.get("error") else loc
        except Exception:
            pass
        ort, dist = _match_geofence(gps)
        timetrack.check_out(user, gps, None, ort, dist)
        ui.notify(t("Arbeitszeit beendet ✓"), type="positive")
        render()

    def render():
        wrap.clear()
        with wrap:
            status = _booking_status(job)
            done_entries = [e for e in timetrack.entries_for_booking(job["id"]) if e.get("checkout")]
            total_min = sum(timetrack.duration_minutes(e) or 0 for e in done_entries)
            oe = timetrack.get_open(user)
            open_here = bool(oe and str(oe.get("booking_id")) == str(job["id"]))
            with ui.card().classes("w-full rounded-2xl shadow-sm border border-slate-100 gap-2 p-4 mt-1"):
                info = ui.column().classes("w-full gap-1 cursor-pointer").mark("booking-details")
                info.on("click", lambda: dialog.open_booking_dialog(job, user, admin, staff, activate))
                with info:
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.icon("cleaning_services").classes("text-primary text-xl shrink-0")
                        ui.label(job["apartment_name"]).classes("font-bold text-lg leading-tight")
                        ui.space()
                        _status_chip(job)
                    if same_day:
                        ui.chip(t("Wechseltag"), icon="bolt").props("color=deep-orange text-color=white dense")
                    with ui.row().classes("w-full items-center gap-1 text-sm text-slate-600 no-wrap"):
                        ui.icon("logout").classes("text-deep-orange text-base")
                        ui.label(f"{t('Check-out')} {job['checkout_time'] or '—'}")
                        ui.icon("arrow_forward").classes("text-slate-400 text-sm")
                        ui.icon("login").classes("text-green-700 text-base")
                        ui.label(f"{t('Check-in')} {nxt['checkin_time'] if nxt else '—'}")

                # Ausserhalb von `info`, sonst öffnet jeder Tab-Klick den Dialog.
                _ab_an_tabs(job, nxt, same_day)
                with ui.row().classes("w-full justify-end -mt-1"):
                    ui.button(t("In meinen Kalender"), icon="event_available",
                              on_click=lambda: _kalender_download(job)) \
                        .props("flat dense no-caps size=sm").mark("ical")

                if open_here:
                    checkin_dt = datetime.fromisoformat(oe["checkin"])
                    listen = _checklisten_an()
                    if listen:
                        dprog, tprog = _checklist_progress(job, user)
                        complete = bool(tprog) and dprog >= tprog
                    else:
                        dprog = tprog = 0
                        complete = True     # ohne Checkliste direkt zu den Schritten
                    with ui.card().classes("w-full bg-violet-50 rounded-xl p-3 gap-1 shadow-none"):
                        with ui.row().classes("w-full items-center"):
                            ui.label(t("Arbeitszeit läuft")).classes("text-xs text-slate-500")
                            ui.space()
                            if not complete:
                                ui.button(t("Beenden"), icon="stop_circle", on_click=_do_out) \
                                    .props("outline dense no-caps color=negative")
                        tl = ui.label("0:00:00").classes("text-3xl font-bold text-primary")

                        def tick(cd=checkin_dt, lbl=tl):
                            lbl.text = str(datetime.now().replace(microsecond=0) - cd.replace(microsecond=0))
                        tick()
                        ui.timer(1.0, tick)
                    if listen:
                        with ui.row().classes("w-full items-center"):
                            ui.label(t("Checkliste")).classes("font-medium text-sm")
                            ui.space()
                            ui.label(f"{dprog}/{tprog} erledigt").classes("text-xs text-slate-500")
                        ui.linear_progress(value=(dprog / tprog if tprog else 0), show_value=False) \
                            .props(f"color={'green' if complete else 'primary'} rounded track-color=grey-3").classes("w-full")
                    if not complete:
                        ui.button(t("Weiter zur Checkliste"), icon="checklist",
                                  on_click=lambda: _open_checkliste(job, activate)) \
                            .props("unelevated no-caps size=lg").classes("w-full")
                    else:
                        if listen:
                            with ui.row().classes("w-full items-center gap-1 text-sm text-green-700"):
                                ui.icon("check_circle").classes("text-base")
                                ui.label(t("Alle Aufgaben abgeschlossen"))
                        ui.label(t("Nächste Schritte")).classes("text-xs font-semibold text-slate-400 mt-1")
                        with ui.column().classes("w-full gap-1"):
                            _step_button("Schaden melden", "report_problem",
                                         lambda: reinigung.open_damage_dialog(job["apartment_id"], job["apartment_name"], user, booking_id=job["id"]))
                            _step_button("Notiz hinzufügen", "sticky_note_2",
                                         lambda: _note_dialog(job))
                            _step_button("Verbrauch / Wäsche", "inventory_2",
                                         lambda: _restock_dialog(job, user))
                        ui.button(t("Arbeitszeit beenden"), icon="stop_circle", on_click=_do_out) \
                            .props("unelevated no-caps size=lg color=negative").classes("w-full mt-1")
                elif status == "abgeschlossen":
                    with ui.row().classes("w-full items-center gap-2 text-sm text-green-700 bg-green-50 rounded-lg p-2"):
                        ui.icon("check_circle")
                        if _checklisten_an():
                            dprog, tprog = _checklist_progress(job, user)
                            ui.label(t("Fertig · {dauer} · {done}/{total} erledigt",
                                        dauer=timetrack.fmt_dur(total_min), done=dprog, total=tprog))
                        else:
                            ui.label(t("Fertig · {dauer}", dauer=timetrack.fmt_dur(total_min)))
                else:
                    if total_min:
                        ui.label(t("Erfasst {dauer}", dauer=timetrack.fmt_dur(total_min))).classes("text-xs text-slate-500")
                    ui.button(t("Arbeitszeit starten"), icon="play_arrow", on_click=_do_in) \
                        .props("unelevated no-caps size=lg").classes("w-full")
    render()


def _cleaning_compact(job, user, admin, staff, activate):
    nxt = job.get("next")
    card = ui.card().classes(ton.KARTE_ENG + " cursor-pointer")
    card.on("click", lambda: dialog.open_booking_dialog(job, user, admin, staff, activate))
    with card:
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.icon("home").classes("text-primary shrink-0")
            with ui.column().classes("gap-0 min-w-0 flex-grow"):
                ui.label(job["apartment_name"]).classes("font-medium truncate")
                ui.label(f"{t('Check-out')} {job['checkout_time'] or '—'} → "
                         f"{t('Check-in')} {nxt['checkin_time'] if nxt else '—'}") \
                    .classes("text-xs text-slate-500")
                # Nur die Anreise-Zahl – die Abreise-Personen stehen im Detail-Dialog,
                # nebeneinander werden sie zu leicht verwechselt.
                if nxt:
                    n = _pers_count(nxt)
                    ui.label(t("Vorbereiten für {n}", n=n) + " "
                             + (t("Person") if n == 1 else t("Personen"))) \
                        .classes("text-xs font-semibold text-green-700 truncate")
                else:
                    ui.label(t("keine Folgebuchung")).classes("text-xs text-slate-400 truncate")
                # Wer übernimmt DIESE Reinigung. Im Kopf der Tagesgruppe steht bei
                # mehreren Buchungen nur "{n} vergeben" – ohne den Namen an der
                # Karte lässt sich das Aufgeklappte keinem Mitarbeiter zuordnen.
                who = bookings.assignee_of(job["id"])
                with ui.row().classes("items-center gap-1 no-wrap min-w-0"):
                    if who:
                        ui.icon("how_to_reg").classes("text-green-700 text-sm shrink-0")
                        ui.label(t("Du") if who == user else staff.get(who, who)) \
                            .classes("text-xs font-medium text-green-700 truncate")
                    else:
                        ui.icon("person_off").classes("text-amber-700 text-sm shrink-0")
                        ui.label(t("noch frei")).classes(f"text-xs font-medium {ton.AUF_HINWEIS} truncate")
            _status_chip(job)
            ui.icon("chevron_right").classes("text-slate-300 shrink-0")


def _event_card(ev, user, admin, staff, activate):
    is_out = ev["kind"] == "out"
    who = bookings.assignee_of(ev["id"])
    who_name = staff.get(who, who) if who else None
    with ui.card().classes(ton.KARTE_ENG):
        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
            if is_out:
                ui.chip(t("Abreise"), icon="logout").props("color=deep-orange text-color=white dense")
            else:
                ui.chip(t("Anreise"), icon="login").props("color=green text-color=white dense")
            ui.label(ev["apartment_name"]).classes("font-semibold")
            with ui.row().classes("items-center gap-1 text-sm text-slate-500"):
                ui.icon("schedule").classes("text-base")
                ui.label(ev["time"] or "—")
            if ev.get("nights") is not None:
                with ui.row().classes("items-center gap-1 text-sm text-slate-500") \
                        .tooltip(t("Nächte")):
                    ui.icon("dark_mode").classes("text-base")
                    ui.label(f"{ev['nights']}")
            ui.space()
            if is_out:
                if who_name:
                    ui.chip(who_name, icon="person").props("color=primary text-color=white dense")
                else:
                    ui.chip(t("nicht zugewiesen"), icon="person_off").props("color=grey-4 dense")
        with ui.row().classes("w-full items-center gap-2 flex-wrap text-sm text-slate-500"):
            ui.label(f"{ev['guest'] or t('Gast')} · {ev['channel']}")
            ui.label(_persons_text(ev, True))
        with ui.row().classes("w-full items-center gap-2 flex-wrap mt-1"):
            ui.button(t("Öffnen"), icon="open_in_full",
                      on_click=lambda e=ev: dialog.open_booking_dialog(e, user, admin, staff, activate)) \
                .props("unelevated dense no-caps")
            if is_out and who != user:
                ui.button(t("Ich übernehme"), icon="how_to_reg",
                          on_click=lambda e=ev: dialog._assign(e, user, user, staff, activate)) \
                    .props("outline dense no-caps")
