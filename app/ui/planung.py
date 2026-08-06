#!/usr/bin/env python3
"""Zuweisen mit Vorschlag: Wochenplanung, Stammzuständigkeit, Abwesenheiten.

Drei Oberflächen zu `app/planung.py`:

* **„Offene zuweisen"** – alle unverteilten Reinigungen der nächsten zwei Wochen
  auf einem Blatt, je Zeile ein Vorschlag, den man ändern kann. Ein Knopf am
  Ende. Das ersetzt das Öffnen jeder einzelnen Buchung.
* **Abwesenheiten** (Mein Konto) – jeder trägt selbst ein, wann er weg ist.
* **Stammzuständigkeit** (Übersicht → Konfiguration) – wer macht welche Wohnung
  normalerweise.

Der Vorschlag wird **nie automatisch gespeichert**. Man sieht ihn, ändert ihn
und bestätigt. Automatisches Zuweisen würde genau die Fehler machen, die
niemand sucht – weil ja „das System" zugewiesen hat.
"""
from datetime import date, timedelta

from nicegui import ui

from app import bookings, planung, push
from app.ui.basis import USERS, _apts, _cur_user, t


def _staff():
    """{benutzername: anzeigename} aller, die Reinigungen übernehmen."""
    return planung.reinigungskraefte(USERS)


def _dfmt(iso):
    return f"{iso[8:10]}.{iso[5:7]}." if iso and len(iso) >= 10 else (iso or "")


# ------------------------------------------------------------ Wochenplanung
def offene_zuweisen_dialog(jobs, staff, on_saved=None, tage=14):
    """Alle offenen Reinigungen der nächsten Tage mit Vorschlag zeigen."""
    offen = [j for j in planung.naechste_tage(jobs, tage)
             if not bookings.assignee_of(j["id"])]
    last = planung.last_je_mitarbeiter(jobs, bookings.assignee_of)
    paare = planung.vorschlaege(offen, staff, last)
    auswahl = {}

    with ui.dialog() as dlg, ui.card().classes("w-[560px] max-w-full gap-2 "
                                               "max-h-[90vh] overflow-auto"):
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.icon("assignment_ind").classes("text-primary text-2xl")
            with ui.column().classes("gap-0"):
                ui.label(t("Offene Reinigungen zuweisen")).classes("text-lg font-bold")
                ui.label(t("Nächste {n} Tage · Vorschlag ist änderbar", n=tage)) \
                    .classes("text-xs text-slate-500")
        if not offen:
            ui.label(t("Nichts offen – alles ist zugewiesen. 🎉")) \
                .classes("text-slate-500 py-4")
            with ui.row().classes("w-full justify-end"):
                ui.button(t("Schließen"), on_click=dlg.close).props("flat")
            dlg.open()
            return dlg

        abw = planung.abwesenheiten()
        for job, wer in paare:
            with ui.row().classes("w-full items-center gap-2 no-wrap border-b "
                                  "border-slate-100 py-1"):
                with ui.column().classes("gap-0 min-w-0 flex-grow"):
                    ui.label(job["apartment_name"]).classes("text-sm font-medium truncate")
                    ui.label(_dfmt(job["departure"])).classes("text-xs text-slate-500")
                weg = planung.abwesend_am(job["departure"], abw)
                # Wer an dem Tag weg ist, steht mit Hinweis in der Liste – aber
                # er steht drin: manchmal weiß der Mensch mehr als der Kalender.
                moeglich = {u: (n + (" · " + t("abwesend") if u in weg else ""))
                            for u, n in staff.items()}
                sel = ui.select(moeglich, value=wer).props("dense outlined") \
                    .classes("w-[190px] shrink-0")
                auswahl[job["id"]] = (job, sel)
        if not any(w for _j, w in paare):
            ui.label(t("Für diese Tage ist niemand verfügbar – Abwesenheiten prüfen.")) \
                .classes("text-sm text-amber-800")

        def zuweisen():
            von = _cur_user()
            je_person = {}
            for job, sel in auswahl.values():
                if not sel.value:
                    continue
                bookings.set_assignment(job["id"], sel.value, von)
                je_person.setdefault(sel.value, []).append(job)
            dlg.close()
            if not je_person:
                ui.notify(t("Nichts ausgewählt."), type="warning")
                return
            for benutzer, eigene in je_person.items():
                if benutzer == von or not push.will(USERS.get(benutzer), "zuweisung"):
                    continue
                # EINE Nachricht je Person statt einer je Buchung – zehn
                # Meldungen hintereinander liest niemand, die wischt man weg.
                anzahl = len(eigene)
                push.senden_im_hintergrund(
                    benutzer,
                    t("1 neue Reinigung für dich") if anzahl == 1
                    else t("{n} neue Reinigungen für dich", n=anzahl),
                    " · ".join(f"{_dfmt(j['departure'])} {j['apartment_name']}"
                               for j in eigene[:4]),
                    "/", "zuweisung")
            ui.notify(t("{n} Reinigung(en) zugewiesen ✓",
                        n=sum(len(v) for v in je_person.values())), type="positive")
            if on_saved:
                # Erst wenn dieser Klick fertig ist. Der Dialog hängt in der
                # Liste, die `on_saved` neu aufbaut – ein direkter Aufruf löscht
                # ihn mitten in seinem eigenen Klick-Handler (dieselbe Falle wie
                # beim Abrechnungs-Dialog, siehe README).
                ui.timer(0.05, on_saved, once=True)

        with ui.row().classes("w-full justify-end gap-2 mt-1"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Zuweisen"), icon="check", on_click=zuweisen).props("unelevated")
    dlg.open()
    return dlg


# ------------------------------------------------------------ Abwesenheiten
def abwesenheiten_block(benutzer=None, titel=True):
    """„Wann bist du weg?" – Selbstbedienung in „Mein Konto“."""
    benutzer = benutzer or _cur_user()
    rumpf = ui.column().classes("w-full gap-1")

    def neu():
        rumpf.clear()
        with rumpf:
            _abwesenheiten_inhalt(benutzer, neu, titel)
    neu()
    return rumpf


def _abwesenheiten_inhalt(benutzer, neu, titel):
    if titel:
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.icon("beach_access").classes("text-primary text-xl")
            ui.label(t("Abwesenheiten")).classes("font-medium text-slate-700")
            ui.space()
            ui.label(t("Urlaub, krank, frei")).classes("text-xs text-slate-400")

    heute = date.today().isoformat()
    eintraege = planung.abwesenheiten(benutzer, ab=heute)
    if not eintraege:
        ui.label(t("Kein Eintrag – du giltst als verfügbar.")) \
            .classes("text-sm text-slate-500")
    for a in eintraege:
        with ui.row().classes("w-full items-center gap-2 no-wrap text-sm"):
            ui.icon("event_busy").classes("text-slate-400 text-base")
            ui.label(f"{_dfmt(a['von'])} – {_dfmt(a['bis'])}").classes("shrink-0")
            ui.label(a.get("grund") or "").classes("text-slate-500 truncate flex-grow")
            ui.button(icon="delete", on_click=lambda _e=None, sid=a["id"]: (
                planung.abwesenheit_loeschen(sid), neu())) \
                .props("flat round dense size=sm color=negative")

    with ui.row().classes("w-full items-end gap-2 flex-wrap mt-1"):
        von = ui.input(t("Von"), value=heute).props("type=date outlined dense") \
            .classes("w-[150px]")
        bis = ui.input(t("Bis"), value=heute).props("type=date outlined dense") \
            .classes("w-[150px]")
        grund = ui.input(t("Grund (optional)")).props("outlined dense") \
            .classes("flex-grow min-w-[120px]")

        def anlegen():
            try:
                planung.abwesenheit_anlegen(benutzer, von.value, bis.value,
                                            (grund.value or "").strip())
            except ValueError as ex:
                ui.notify(str(ex), type="warning")
                return
            ui.notify(t("Eingetragen ✓"), type="positive")
            neu()
        ui.button(t("Eintragen"), icon="add", on_click=anlegen) \
            .props("outline no-caps dense")


# ------------------------------------------------------------ Stammzuständigkeit
def stammkraefte_block():
    """Wer macht welche Wohnung normalerweise (Übersicht → Konfiguration)."""
    staff = _staff()
    with ui.column().classes("w-full gap-1"):
        ui.label("Stammzuständigkeit").classes("text-sm font-semibold text-slate-500")
        ui.label("Grundlage für den Vorschlag beim Zuweisen. Wer im Urlaub ist, "
                 "wird übersprungen.").classes("text-xs text-slate-400")
        for aid, name in _apts().items():
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.icon("home").classes("text-primary text-base")
                ui.label(name).classes("text-sm flex-grow truncate")
                sel = ui.select({"": "— keine —", **staff},
                                value=planung.stammkraft(aid) or "") \
                    .props("dense outlined").classes("w-[200px]")
                sel.on_value_change(lambda e, a=aid: (
                    planung.stammkraft_setzen(a, e.value or None),
                    ui.notify(t("Gespeichert ✓"), type="positive")))


def wer_ist_weg(tag=None):
    """Kurzform für Kopfzeilen: wer ist heute/an dem Tag nicht da."""
    tag = tag or date.today().isoformat()
    return sorted(planung.abwesend_am(tag))


def naechste_abwesenheiten(tage=14):
    """[(anzeigename, von, bis, grund)] der nächsten Tage – für die Übersicht."""
    bis = (date.today() + timedelta(days=tage)).isoformat()
    staff = _staff()
    return [(staff.get(a["user"], a["user"]), a["von"], a["bis"], a.get("grund", ""))
            for a in planung.abwesenheiten(ab=date.today().isoformat())
            if a["von"] <= bis]
