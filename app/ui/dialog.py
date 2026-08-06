"""Buchungs-Dialog: Details, Protokoll, Gast, Notizen, Nachrichten, Aktionen.

Der Einstieg in fast alles, was an einer Buchung zu tun ist – uebernehmen,
tauschen, Zeit nachtragen, Schaden melden, Gast anschreiben.
"""

from nicegui import ui
from app import bookings, housekeeping, mailer, planung, push, smoobu, timetrack
from app.ui.basis import (CFG, USERS, _app_url, _checklisten_an, _cur_area, _cur_role, _cur_user, _d, _photo_thumb, _t, t)
from app.ui import buchungen, reinigung  # noqa: F401  (Ringschluss, siehe Kopf)

def _dfmt_kurz(iso):
    """„05.08." – in einer Benachrichtigung ist kein Platz für mehr."""
    return f"{iso[8:10]}.{iso[5:7]}." if iso and len(iso) >= 10 else (iso or "")


def _assign(bk, assignee, by, staff, after, note=""):
    bookings.set_assignment(bk["id"], assignee, by, note)
    if assignee != by:   # jemandem anderen zugewiesen → benachrichtigen
        _notify_assignee(bk, assignee, by, staff)
    ui.notify(t("{wohnung} → {name} zugewiesen ✓", wohnung=bk["apartment_name"],
                name=staff.get(assignee, assignee)),
              type="positive")
    if after:
        after()


def _notify_assignee(bk, assignee, by, staff):
    # Push zuerst: das kommt auf dem Sperrbildschirm an, die Mail liegt im
    # Postfach. Beides, weil nicht jeder die App eingerichtet hat.
    if push.will(USERS.get(assignee), "zuweisung"):
        push.senden_im_hintergrund(
            assignee, t("Neue Reinigung für dich"),
            t("{wohnung} · {datum}", wohnung=bk["apartment_name"],
              datum=_dfmt_kurz(bk["departure"])), "/", "zuweisung")
    to = buchungen._user_email(assignee)
    if not to:
        ui.notify(t("Hinweis: {name} hat keine E-Mail hinterlegt – "
                    "keine Benachrichtigung verschickt.",
                    name=staff.get(assignee, assignee)),
                  type="warning", timeout=8000)
        return
    body = (f"Hallo {staff.get(assignee, assignee)},\n\n"
            f"dir wurde eine Reinigung zugewiesen:\n\n"
            f"Wohnung: {bk['apartment_name']}\n"
            f"Abreise (Reinigung): {bk['departure']}, Check-out {bk['checkout_time'] or '—'}\n"
            f"Anreise nächster Gast: {bk['arrival']}\n"
            f"Personen: {bk['persons']}\n\n"
            f"Zugewiesen von: {staff.get(by, by)}\n\n"
            f"Bitte in der LIVARO-App bestätigen: {_app_url()}\n")
    try:
        mailer.send_notify(CFG, to, f"Neue Reinigung: {bk['apartment_name']} ({bk['departure']})", body)
        ui.notify(f"{staff.get(assignee, assignee)} per E-Mail benachrichtigt ✓", type="positive")
    except mailer.MailError as ex:
        ui.notify(f"E-Mail nicht gesendet: {ex}", type="warning", timeout=9000)


def _notify_nachtragen(job, staff):
    """Einmalige Erinnerung, wenn nach Check-out nicht abgeschlossen (Checkliste +
    Arbeitszeit fehlen). Empfänger: zugewiesener Mitarbeiter, sonst Admin."""
    rec = bookings.get_record(job["id"])
    if rec.get("nachtragen_notified"):
        return
    who = bookings.assignee_of(job["id"])
    to = buchungen._user_email(who) if who else (CFG.get("notify_email", {}).get("absender")
                                       or CFG.get("email", {}).get("absender"))
    if not to:
        return
    anrede = staff.get(who, who) if who else "Team"
    body = (f"Hallo {anrede},\n\n"
            f"die folgende Reinigung wurde nach dem Check-out noch nicht abgeschlossen. "
            f"Bitte trage die Checkliste und die Arbeitszeit in der LIVARO-App nach:\n\n"
            f"Wohnung: {job['apartment_name']}\n"
            f"Abreise: {job['departure']}, Check-out {job.get('checkout_time') or '—'}\n"
            f"Gast: {job.get('guest') or '—'}\n\n"
            f"App: {_app_url()}  →  Buchungen → Reinigungen\n")
    if who and push.will(USERS.get(who), "nachtragen"):
        push.senden_im_hintergrund(
            who, t("Arbeitszeit fehlt noch"),
            t("{wohnung} · {datum}", wohnung=job["apartment_name"],
              datum=_dfmt_kurz(job["departure"])), "/", "nachtragen")
    try:
        mailer.send_notify(CFG, to,
                           f"Bitte nachtragen: {job['apartment_name']} ({job['departure']})", body)
        bookings.set_field(job["id"], nachtragen_notified=bookings.now_iso())
    except mailer.MailError:
        pass   # später erneut versuchen (Flag nicht gesetzt)


def _open_swap(bk, user, staff, on_saved):
    who = bookings.assignee_of(bk["id"])
    others = {u: n for u, n in staff.items() if u != who}
    # Wer an dem Tag weg ist, steht mit Hinweis in der Liste – aber er steht
    # drin: manchmal weiß der Mensch mehr als der Kalender.
    weg = planung.abwesend_am(bk["departure"])
    beschriftet = {u: (n + (" · " + t("abwesend") if u in weg else ""))
                   for u, n in others.items()}
    vorgeschlagen = planung.vorschlag(bk, others)
    with ui.dialog() as dlg, ui.card().classes("w-[360px] max-w-full gap-2"):
        ui.label(t("Zuweisen / Tauschen – {wohnung}", wohnung=bk["apartment_name"])).classes("font-bold")
        if not others:
            ui.label(t("Keine weiteren Mitarbeiter.")).classes("text-sm text-gray-500")
        sel = ui.select(beschriftet, label=t("Mitarbeiter"), value=vorgeschlagen) \
            .props("dense outlined").classes("w-full")
        if vorgeschlagen:
            grund = (t("Stammzuständig für diese Wohnung")
                     if planung.stammkraft(bk.get("apartment_id")) == vorgeschlagen
                     else t("Hat an dem Tag am wenigsten zu tun"))
            ui.label(t("Vorschlag: {name} – {grund}",
                       name=staff.get(vorgeschlagen, vorgeschlagen), grund=grund)) \
                .classes("text-xs text-gray-500")

        def go():
            if not sel.value:
                ui.notify(t("Bitte Mitarbeiter wählen."), type="warning"); return
            dlg.close()
            _assign(bk, sel.value, user, staff, on_saved)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Zuweisen"), icon="check", on_click=go).props("unelevated")
    dlg.open()


def _reset_dialog(bk, user, admin, staff, activate):
    """Admin: Auftrag zurücksetzen (Zuweisung, Checkliste, erfasste Zeiten)."""
    with ui.dialog() as dlg, ui.card().classes("w-[400px] max-w-full gap-2"):
        ui.label(t("Auftrag zurücksetzen – {wohnung}", wohnung=bk["apartment_name"])).classes("font-bold")
        ui.label(t("Setzt Zuweisung und Checklisten-Abschluss zurück und entfernt die für "
                   "diese Buchung erfassten Arbeitszeiten. Status wird wieder Nicht "
                   "zugewiesen. Die interne Notiz bleibt erhalten.")) \
            .classes("text-sm text-gray-500")

        def do():
            bookings.reset(bk["id"])
            n = timetrack.delete_for_booking(bk["id"])
            dlg.close()
            ui.notify(t("Auftrag zurückgesetzt (entfernte Zeiteinträge: {n}).", n=n), type="warning")
            open_booking_dialog(bk, user, admin, staff, activate)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Zurücksetzen"), icon="restart_alt", on_click=do).props("unelevated color=negative")
    dlg.open()


def _run_photo_count(apt_id):
    """Anzahl aufgenommener Ist-Fotos im letzten Durchgang dieser Wohnung."""
    run = next((r for r in housekeeping.list_runs()
                if str(r["apartment_id"]) == str(apt_id)), None)
    if not run:
        return 0
    return sum(1 for v in run["tasks"].values() if v.get("ist_photo"))


def _booking_log(bk):
    """Protokoll: was für diese Buchung schon erledigt/gemeldet wurde."""
    bid = bk["id"]
    entries = [e for e in timetrack.entries_for_booking(bid) if e.get("checkout")]
    total_min = sum(timetrack.duration_minutes(e) or 0 for e in entries)
    dprog, tprog = buchungen._checklist_progress(bk, _cur_user())
    photos = _run_photo_count(bk["apartment_id"])
    dmgs = housekeeping.damages_for_booking(bid)
    rst = housekeeping.restock_for_booking(bid)
    something = entries or dprog or photos or dmgs or rst

    # Arbeitszeit
    with ui.row().classes("w-full items-center gap-2"):
        ui.icon("schedule").classes("text-primary")
        ui.label(t("Arbeitszeit: {dauer}",
                   dauer=timetrack.fmt_dur(total_min) if total_min else "0:00 h")
                 + (t(" ({n} Einträge)", n=len(entries)) if entries else "")).classes("text-sm font-medium")
    for e in entries:
        ui.label(f"· {_d(e['checkin'])} {_t(e['checkin'])}–{_t(e['checkout'])}"
                 + (t(" (nachgetragen)") if e.get("manual") else "")).classes("text-xs text-gray-500 pl-6")
    # Checkliste
    with ui.row().classes("w-full items-center gap-2 mt-1"):
        ui.icon("checklist").classes("text-primary")
        ui.label(t("Checkliste: {done}/{total} erledigt · {fotos} Foto(s)",
                   done=dprog, total=tprog, fotos=photos)).classes("text-sm font-medium")
    # Schäden
    with ui.row().classes("w-full items-center gap-2 mt-1"):
        ui.icon("report_problem").classes("text-red-600")
        ui.label(t("Schäden gemeldet: {n}", n=len(dmgs))).classes("text-sm font-medium")
    for d in dmgs:
        with ui.row().classes("w-full items-start gap-2 pl-6 no-wrap"):
            if d.get("photo"):
                _photo_thumb(f"/media/{d['photo']}", "w-12 h-12")
            ui.label(f"{d.get('room') or '—'} · {d['desc']} ({d['urgency']})"
                     + ("" if d["status"] == "offen" else " ✓")).classes("text-xs text-gray-600")
    # Verbrauch / Wäsche
    with ui.row().classes("w-full items-center gap-2 mt-1"):
        ui.icon("inventory_2").classes("text-primary")
        ui.label(t("Nachbestellt: {n}", n=len(rst))).classes("text-sm font-medium")
    for r in rst:
        ui.label(f"· {r['menge']}× {r['item']}" + ("" if r["status"] == "offen" else " ✓")) \
            .classes("text-xs text-gray-600 pl-6")

    if not something:
        ui.label(t("Für diese Buchung wurde noch nichts erfasst.")).classes("text-sm text-gray-400 mt-2")


def _msg_time(s):
    """Smoobu-Zeitstempel '2026-04-07 19:09:46' -> '07.04. 19:09'."""
    from datetime import datetime
    s = (s or "").strip()
    try:
        return datetime.strptime(s[:16], "%Y-%m-%d %H:%M").strftime("%d.%m. %H:%M")
    except Exception:
        return s


def _confirm_send_guest(bk, textarea, reload_cb):
    """Bestätigungsdialog vor dem Live-Versand einer Gast-Antwort über Smoobu."""
    text = (textarea.value or "").strip()
    if not text:
        ui.notify(t("Bitte zuerst eine Antwort eingeben."), type="warning")
        return
    with ui.dialog() as cd, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(t("Nachricht an den Gast senden?")).classes("text-lg font-bold")
        ui.label(t("Gast: {name}", name=bk.get("guest") or "—")).classes("text-sm text-gray-500")
        with ui.column().classes("w-full bg-gray-50 rounded p-2 max-h-[30vh] overflow-auto"):
            ui.label(text).classes("text-sm whitespace-pre-wrap")
        ui.label(t("Die Nachricht wird sofort über Smoobu an den Gast zugestellt.")) \
            .classes("text-xs text-amber-700")

        async def _do():
            from nicegui import run
            api_key = (CFG.get("smoobu_api_key") or "").strip()
            if not api_key:
                ui.notify(t("Kein Smoobu-API-Key konfiguriert."), type="negative")
                return
            try:
                await run.io_bound(smoobu.send_message, api_key, bk["id"], text)
            except Exception as ex:
                ui.notify(t("Senden fehlgeschlagen: {fehler}", fehler=ex), type="negative")
                return
            cd.close()
            textarea.value = ""
            ui.notify(t("Nachricht an den Gast gesendet."), type="positive")
            await reload_cb(True)

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=cd.close).props("flat no-caps")
            ui.button(t("Senden"), icon="send", on_click=_do).props("unelevated no-caps color=primary")
    cd.open()


def _render_guest_thread(box, msgs, err, reload_cb, bk):
    """Nachrichtenverlauf (type 1 = Gast, type 2 = wir) als Chat + Antwortfeld.

    box ist eine Spalte mit fester Höhe: Kopf + Antwortfeld bleiben fix, nur der
    Verlauf in der Mitte scrollt (WhatsApp-/Smoobu-Stil)."""
    box.clear()
    with box:
        # --- Kopf (fix) -----------------------------------------------------
        with ui.row().classes("w-full items-center shrink-0 pb-1"):
            ui.label(t("Gästekommunikation")).classes("text-xs font-semibold text-gray-400")
            ui.space()
            ui.button(icon="refresh", on_click=lambda: reload_cb(True)) \
                .props("flat round dense size=sm").tooltip(t("Aktualisieren"))
        # --- Verlauf (scrollt) ---------------------------------------------
        thread = ui.column().classes(
            "w-full gap-2 flex-grow overflow-auto min-h-0 py-1 pr-1")
        with thread:
            if err:
                with ui.row().classes("w-full items-center gap-2 bg-red-50 rounded p-2"):
                    ui.icon("error_outline").classes("text-red-500")
                    ui.label(t("Nachrichten konnten nicht geladen werden: {fehler}", fehler=err)) \
                        .classes("text-xs text-red-700")
            elif not msgs:
                ui.label(t("Noch keine Nachrichten zu dieser Buchung.")) \
                    .classes("text-sm text-gray-400 m-auto")
            for m in msgs:
                mine = m.get("type") == 2
                with ui.row().classes("w-full no-wrap "
                                      + ("justify-end" if mine else "justify-start")):
                    with ui.column().classes(
                            "gap-0 rounded-2xl px-3 py-2 max-w-[82%] "
                            + ("bg-primary text-white rounded-br-sm" if mine
                               else "bg-gray-100 rounded-bl-sm")):
                        subj = (m.get("subject") or "").strip()
                        if subj:
                            ui.label(subj).classes(
                                "text-xs font-semibold "
                                + ("text-white/90" if mine else "text-gray-600"))
                        ui.label((m.get("message") or "").strip() or "—") \
                            .classes("text-sm whitespace-pre-wrap break-words")
                        ui.label(_msg_time(m.get("createdAt"))).classes(
                            "text-[10px] self-end "
                            + ("text-white/70" if mine else "text-gray-400"))
        # neueste Nachricht sichtbar: Verlauf ans Ende scrollen
        if msgs:
            thread_id = thread.id
            ui.timer(0.05, lambda: ui.run_javascript(
                f"const e=document.getElementById('c{thread_id}');"
                f" if(e) e.scrollTop=e.scrollHeight;"), once=True)
        # --- Antwortfeld (fix, unten) --------------------------------------
        if not err:
            with ui.column().classes("w-full gap-1 shrink-0 pt-2 border-t border-gray-100"):
                ta = ui.textarea(placeholder=t("Antwort an den Gast …")) \
                    .props("outlined autogrow dense").classes("w-full") \
                    .style("max-height:96px;overflow-y:auto")
                with ui.row().classes("w-full items-center gap-2"):
                    ui.label(t("Wird direkt über Smoobu an den Gast gesendet.")) \
                        .classes("text-[11px] text-gray-400 flex-grow")
                    ui.button(t("Senden"), icon="send",
                              on_click=lambda: _confirm_send_guest(bk, ta, reload_cb)) \
                        .props("unelevated no-caps")


def open_booking_dialog(bk, user, admin, staff, activate):
    who = bookings.assignee_of(bk["id"])
    nxt = bk.get("next")
    same_day = bool(nxt and nxt["arrival"] == bk["departure"])
    # Nach einer Aktion wieder in dieser Detailübersicht landen:
    reopen = lambda: open_booking_dialog(bk, user, admin, staff, activate)
    with ui.dialog() as dlg, ui.card().classes("w-[460px] max-w-full gap-0 p-0 max-h-[92vh] overflow-auto"):
        with ui.row().classes("w-full items-center gap-2 p-3 pb-1"):
            ui.icon("home").classes("text-primary text-2xl")
            ui.label(bk["apartment_name"]).classes("text-xl font-bold")
            ui.space()
            # Schließen aktualisiert die dahinterliegende Liste
            ui.button(icon="close", on_click=lambda: (dlg.close(), activate(_cur_area()))) \
                .props("flat round dense")
        mgr = _cur_role() in ("admin", "manager")   # Nachrichten nur Admin/Manager
        _hooks = {}
        with ui.tabs().props("dense no-caps align=left inline-label").classes("w-full px-2") as tabs:
            t_b = ui.tab(t("Buchung"))
            t_log = ui.tab(t("Protokoll"))
            t_g = ui.tab(t("Gast"))
            t_n = ui.tab(t("Notizen"))
            if mgr:
                t_msg = ui.tab(t("Nachrichten"))
        with ui.tab_panels(tabs, value=t_b).classes("w-full"):
            with ui.tab_panel(t_b):
                with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-1 text-sm"):
                    ui.label(t("Anreise")).classes("text-gray-500")
                    ui.label(f"{buchungen._dfmt(bk['arrival'])} · {bk['checkin_time'] or '—'}")
                    ui.label(t("Abreise")).classes("text-gray-500")
                    ui.label(f"{buchungen._dfmt(bk['departure'])} · {bk['checkout_time'] or '—'}")
                    ui.label(t("Personen")).classes("text-gray-500")
                    ui.label(buchungen._persons_text(bk, True))
                    ui.label(t("Gast")).classes("text-gray-500")
                    ui.label(bk["guest"] or "—")
                    ui.label(t("Buchungskanal")).classes("text-gray-500")
                    ui.label(bk["channel"] or "—")
                if nxt:
                    with ui.column().classes("w-full gap-0 rounded-lg p-2 mt-2 "
                                             + ("bg-red-50" if same_day else "bg-green-50")):
                        ui.label(t("Anreise vorbereiten für")).classes(
                            "text-xs " + ("text-red-500" if same_day else "text-gray-500"))
                        ui.label(buchungen._guest_persons(nxt, True)).classes(
                            "text-sm font-semibold " + ("text-red-700" if same_day else "text-green-700"))
                        ui.label(t("Nächste Anreise: {datum} · {zeit}",
                                    datum=buchungen._dfmt(nxt["arrival"]), zeit=nxt["checkin_time"] or "")
                                 + (f" ({t('Wechseltag')})" if same_day else "")).classes("text-xs text-gray-500")
            with ui.tab_panel(t_log):
                _booking_log(bk)
            with ui.tab_panel(t_g):
                with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-1 text-sm"):
                    ui.label(t("Name")).classes("text-gray-500")
                    ui.label(bk["guest"] or "—")
                    ui.label(t("E-Mail")).classes("text-gray-500")
                    ui.label(bk.get("email") or "—")
                    ui.label(t("Telefon")).classes("text-gray-500")
                    ui.label(bk.get("phone") or "—")
            with ui.tab_panel(t_n):
                intern = bookings.get_record(bk["id"]).get("note", "")
                if intern:
                    ui.label(t("Interne Notiz")).classes("text-xs text-gray-500")
                    ui.label(intern).classes("text-sm whitespace-pre-wrap")
                    ui.separator().classes("my-1")
                ui.label(t("Buchungsdetails (Smoobu)")).classes("text-xs text-gray-500")
                ui.label(bk["notice"] or "—").classes("text-sm whitespace-pre-wrap")
            if mgr:
                with ui.tab_panel(t_msg).classes("p-2"):
                    # feste Höhe: Verlauf scrollt intern, Antwortfeld bleibt unten sichtbar
                    _mbox = ui.column().classes("w-full gap-0 h-[68vh] no-wrap")
                    _mstate = {"loaded": False, "busy": False}

                    async def load_msgs(force=False):
                        if _mstate["busy"] or (_mstate["loaded"] and not force):
                            return
                        _mstate["busy"] = True
                        _mbox.clear()
                        with _mbox:
                            ui.spinner(size="lg").classes("m-auto")
                        from nicegui import run
                        api_key = (CFG.get("smoobu_api_key") or "").strip()
                        err, msgs = None, []
                        if not api_key:
                            err = "Kein Smoobu-API-Key konfiguriert."
                        else:
                            try:
                                msgs = await run.io_bound(smoobu.get_messages, api_key, bk["id"])
                            except Exception as ex:
                                err = str(ex)
                        _mstate["loaded"], _mstate["busy"] = True, False
                        _render_guest_thread(_mbox, msgs, err, load_msgs, bk)

                    _hooks["load"] = load_msgs

        footer_box = ui.column().classes("w-full gap-0 p-0")
        with footer_box:
            ui.separator()
            ui.label(t("Aktionen")).classes("text-xs font-semibold text-gray-400 px-3 pt-1")

            def action(label, icon, cb, color="primary"):
                b = ui.button(on_click=cb).props("flat no-caps align=left").classes("w-full")
                with b:
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        ui.icon(icon).classes(f"text-{color}")
                        ui.label(label).classes("flex-grow text-left normal-case text-slate-700")
                        ui.icon("chevron_right").classes("text-gray-300")
            if who != user:
                action(t("Ich übernehme diesen Auftrag"), "how_to_reg",
                       lambda: (dlg.close(), _assign(bk, user, user, staff, reopen)))
            action(t("Tauschen / Zuweisen"), "swap_horiz",
                   lambda: (dlg.close(), _open_swap(bk, user, staff, reopen)))
            action(t("Zeit nachtragen"), "more_time",
                   lambda: (dlg.close(), buchungen._add_time_dialog(bk, user, on_saved=reopen)))
            action(t("Notiz hinzufügen"), "sticky_note_2",
                   lambda: (dlg.close(), buchungen._note_dialog(bk, on_saved=reopen)))
            action(t("Verbrauch / Wäsche"), "inventory_2",
                   lambda: (dlg.close(), buchungen._restock_dialog(bk, user, on_close=reopen)))
            action(t("Schaden melden"), "report_problem",
                   lambda: (dlg.close(), reinigung.open_damage_dialog(bk["apartment_id"], bk["apartment_name"], user, on_saved=reopen, booking_id=bk["id"])),
                   color="negative")
            if _checklisten_an():
                action(t("Checkliste & Fotos"), "checklist",
                       lambda: (dlg.close(), buchungen._open_checkliste(bk, activate)))
            action(t("In meinen Kalender (.ics)"), "event_available",
                   lambda: buchungen._kalender_download(bk))
            if admin:
                action(t("Zurücksetzen (Admin)"), "restart_alt",
                       lambda: (dlg.close(), _reset_dialog(bk, user, admin, staff, activate)), color="negative")

        if mgr:
            async def _on_tab(e):
                # Im Nachrichten-Tab die Aktionsliste ausblenden (mehr Platz für den Chat)
                footer_box.set_visibility(e.value != "Nachrichten")
                if e.value == "Nachrichten":
                    await _hooks["load"]()
            tabs.on_value_change(_on_tab)
    dlg.open()
