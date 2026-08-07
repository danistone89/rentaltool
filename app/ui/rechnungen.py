#!/usr/bin/env python3
"""Ausgangsrechnungen: Entwürfe prüfen, festschreiben, verschicken.

Der Ablauf ist bewusst zweistufig. Ein **Entwurf** entsteht von allein nach dem
Check-out und trägt noch keine Nummer – er lässt sich ändern und auch wieder
wegwerfen. Erst das **Festschreiben** vergibt die Nummer und macht ihn
unveränderlich; ab da wird korrigiert, indem man storniert und neu schreibt.

Der Versand geht nie von allein. Aus der Liste lassen sich mehrere anwählen und
in einem Zug verschicken; was noch Entwurf ist oder keine Anschrift hat, lässt
sich gar nicht erst anwählen – so kann der Stapelversand nichts Halbes
hinausschicken.
"""
from datetime import date

from nicegui import ui

from app import archive, data, mailer, protokoll, rechnung, rechnung_pdf
from app.ui.basis import (CFG, _cur_user, _d, _eur, bereichskopf, leer, spaeter,
                          stoerung, t)
from app.ui import ton

STATUS_ANZEIGE = {
    rechnung.ENTWURF: ("Entwurf", "grey-6", "edit_note"),
    rechnung.FESTGESCHRIEBEN: ("festgeschrieben", "blue-7", "lock"),
    rechnung.GESENDET: ("gesendet", "green-7", "outgoing_mail"),
    rechnung.STORNIERT: ("storniert", "red-7", "block"),
}

BETREFF = "Ihre Rechnung {nummer} – {wohnung}"
TEXT = ("Guten Tag {name},\n\n"
        "anbei erhalten Sie die Rechnung zu Ihrem Aufenthalt vom {von} bis {bis} "
        "in unserem Apartment {wohnung}.\n\n"
        "Vielen Dank für Ihren Besuch – wir freuen uns, wenn Sie wiederkommen.\n\n"
        "Freundliche Grüße\n{absender}")


def render_rechnungen(activate=None):
    bereichskopf("request_quote", "Rechnungen",
                 "Ausgangsrechnungen aus den Buchungen",
                 lambda: ui.button("Entwürfe suchen", icon="auto_awesome",
                                   on_click=lambda: _entwuerfe_erzeugen(neu_laden))
                 .props("outline no-caps").mark("entwuerfe-suchen"))

    fehlt = rechnung_pdf.fehlende_pflichtangaben(CFG.get("betreiber", {}))
    if fehlt:
        with ui.column().classes(f"w-full gap-1 rounded-lg p-3 {ton.FLAECHE_HINWEIS}") \
                .mark("betreiber-unvollstaendig"):
            with ui.row().classes(f"items-center gap-2 no-wrap {ton.AUF_HINWEIS}"):
                ui.icon("gpp_maybe").classes("text-base shrink-0")
                ui.label("Der Rechnungskopf ist unvollständig").classes(
                    "text-sm font-semibold")
            ui.label("Es fehlt: " + ", ".join(fehlt) + ". Ohne diese Angaben ist die "
                     "Rechnung nach § 14 UStG unvollständig – nachzutragen in den "
                     "Einstellungen unter Betreiber.").classes(f"text-xs {ton.LEISE}")

    box = ui.column().classes("w-full gap-3")

    def neu_laden():
        box.clear()
        with box:
            _liste()
    neu_laden()


def _liste():
    alle = rechnung.rechnungen()
    if not alle:
        leer("request_quote", "Noch keine Rechnungen.",
             "Der Knopf oben legt für jede abgereiste Buchung einen Entwurf an.")
        return

    entwuerfe = [r for r in alle if r["status"] == rechnung.ENTWURF]
    offen = [r for r in alle if r["status"] == rechnung.FESTGESCHRIEBEN]
    rest = [r for r in alle if r["status"] in (rechnung.GESENDET, rechnung.STORNIERT)]

    if offen:
        _stapel(offen)
    for titel, gruppe in [("Entwürfe", entwuerfe), ("Bereit zum Versand", offen),
                          ("Erledigt", rest)]:
        if not gruppe:
            continue
        ui.label(f"{titel} ({len(gruppe)})").classes(
            f"text-sm font-semibold {ton.GEDECKT} mt-2")
        for r in gruppe:
            _karte(r)


def _stapel(offene):
    """Mehrere auf einmal verschicken – was nicht darf, ist nicht anwählbar."""
    versandbar = [r for r in offene if rechnung.versandbereit(r)[0]]
    if not versandbar:
        return
    with ui.card().classes(ton.KARTE_ENG).mark("stapelversand"):
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.icon("mark_email_read").classes("text-primary text-xl shrink-0")
            ui.label(f"{len(versandbar)} Rechnung(en) bereit zum Versand") \
                .classes("font-semibold")
            ui.space()
            ui.button("Alle senden", icon="send",
                      on_click=lambda: _senden_viele(versandbar)) \
                .props("unelevated no-caps").mark("stapel-senden")
        ui.label("Nur vollständige Rechnungen mit E-Mail-Adresse sind dabei.") \
            .classes(f"text-xs {ton.STILL}")


def _karte(r):
    label, farbe, icon = STATUS_ANZEIGE[r["status"]]
    s = r.get("summen") or {}
    with ui.card().classes(ton.KARTE_ENG).mark(f"rechnung-{r['id']}"):
        with ui.row().classes("w-full items-center gap-2 no-wrap flex-wrap"):
            ui.chip(label, icon=icon).props(f"color={farbe} text-color=white dense square") \
                .classes("text-xs shrink-0")
            ui.label(r.get("nummer") or "ohne Nummer").classes("font-mono text-sm")
            ui.label(r.get("gast") or "Gast").classes("text-sm font-medium")
            ui.space()
            ui.label(_eur(s.get("brutto", 0))).classes("text-sm font-semibold")
        ui.label(f"{r.get('wohnung_name', '')} · {_d(r.get('anreise'))} bis "
                 f"{_d(r.get('abreise'))}").classes(f"text-xs {ton.LEISE}")

        for zeile in r.get("befunde", []):
            with ui.row().classes(f"w-full items-start gap-2 no-wrap {ton.AUF_HINWEIS} "
                                  f"rounded-lg p-2 {ton.FLAECHE_HINWEIS}"):
                ui.icon("error_outline").classes("text-sm shrink-0 mt-0.5")
                ui.label(zeile).classes("text-xs")

        _empfaenger(r)
        _aktionen(r)


def _empfaenger(r):
    e = r.get("empfaenger") or {}
    vollstaendig = rechnung.anschrift_vollstaendig(e)
    noetig = rechnung.braucht_anschrift((r.get("summen") or {}).get("brutto", 0))
    with ui.row().classes("w-full items-center gap-2 no-wrap"):
        ui.icon("person").classes(f"{ton.STILL} text-sm shrink-0")
        if vollstaendig:
            ui.label(f"{e.get('name', '')}, {e.get('strasse', '')}, "
                     f"{e.get('plz', '')} {e.get('ort', '')}") \
                .classes(f"text-xs {ton.LEISE} truncate")
        elif noetig:
            ui.label("Anschrift fehlt – über 250 € verlangt § 14 UStG Name und Anschrift.") \
                .classes(f"text-xs font-medium {ton.HINWEIS}")
        else:
            ui.label("Kleinbetragsrechnung – Anschrift nicht nötig.") \
                .classes(f"text-xs {ton.STILL}")
        ui.space()
        if r["status"] == rechnung.ENTWURF:
            ui.button(icon="edit", on_click=lambda rr=r: _empfaenger_dialog(rr)) \
                .props("flat dense round").tooltip("Empfänger bearbeiten") \
                .mark(f"empfaenger-{r['id']}")


def _aktionen(r):
    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
        ui.button("PDF", icon="picture_as_pdf", on_click=lambda rr=r: _pdf_laden(rr)) \
            .props("outline dense no-caps").mark(f"pdf-{r['id']}")
        if r["status"] == rechnung.ENTWURF:
            knopf = ui.button("Festschreiben", icon="lock",
                              on_click=lambda rr=r: _festschreiben(rr)) \
                .props("unelevated dense no-caps").mark(f"festschreiben-{r['id']}")
            if r.get("befunde"):
                knopf.disable()
                knopf.tooltip("Erst klären, was oben steht.")
            ui.button(icon="delete", on_click=lambda rr=r: (
                rechnung.loeschen(rr["id"]),
                ui.notify("Entwurf verworfen.", type="warning"),
                spaeter(lambda: ui.navigate.reload()))) \
                .props("flat dense round color=negative").tooltip("Entwurf verwerfen")
        elif r["status"] in (rechnung.FESTGESCHRIEBEN, rechnung.GESENDET):
            ja, grund = rechnung.versandbereit(r)
            knopf = ui.button("Senden" if r["status"] == rechnung.FESTGESCHRIEBEN
                              else "Erneut senden", icon="send",
                              on_click=lambda rr=r: _senden_viele([rr])) \
                .props("outline dense no-caps").mark(f"senden-{r['id']}")
            if not ja:
                knopf.disable()
                knopf.tooltip(grund)
            ui.button(icon="block", on_click=lambda rr=r: _storno_dialog(rr)) \
                .props("flat dense round color=negative").tooltip("Stornieren")
        ui.space()
        if r.get("gesendet"):
            ui.label(f"gesendet {_d(r['gesendet'])}").classes(f"text-xs {ton.STILL}")


# ------------------------------------------------------------------ Aktionen
def _entwuerfe_erzeugen(neu_laden):
    from app.ui import buchungen as ui_buchungen
    jobs = ui_buchungen._cleaning_jobs(quiet=True)
    faellig = rechnung.faellige_buchungen(jobs)
    if not faellig:
        ui.notify("Keine abgereiste Buchung ohne Rechnung.", type="info")
        return
    gaeste = data.gastdaten()
    neu, mit_befund = 0, 0
    for j in faellig:
        e, befunde = rechnung.entwurf_fuer(j, gaeste.get(j.get("id")), CFG, _cur_user())
        if e:
            neu += 1
            mit_befund += 1 if befunde else 0
    ui.notify(f"{neu} Entwurf/Entwürfe angelegt"
              + (f", davon {mit_befund} mit offenen Punkten." if mit_befund else "."),
              type="positive", timeout=6000)
    spaeter(neu_laden)


def _festschreiben(r):
    try:
        fest = rechnung.festschreiben(r["id"], _cur_user(), CFG)
    except ValueError:
        ui.notify("Es steht noch etwas offen.", type="warning")
        return
    if not fest:
        return
    # Wie die Steueranmeldung: der Beleg geht revisionssicher ins Archiv.
    try:
        pdf = rechnung_pdf.bauen(fest, CFG.get("betreiber", {}))
        archive.archive_pdf(pdf, f"RE-{fest['nummer']}",
                            {"brutto": (fest.get("summen") or {}).get("brutto", 0),
                             "gast": fest.get("gast", "")})
    except Exception as ex:
        ui.notify(f"Festgeschrieben, aber nicht archiviert: {ex}",
                  type="warning", timeout=9000)
    ui.notify(f"Rechnung {fest['nummer']} festgeschrieben.", type="positive")
    ui.navigate.reload()


def _pdf_laden(r):
    try:
        pdf = rechnung_pdf.bauen(r, CFG.get("betreiber", {}))
    except Exception as ex:
        ui.notify(f"PDF fehlgeschlagen: {ex}", type="negative", timeout=9000)
        return
    ui.download.content(pdf, rechnung_pdf.dateiname(r), media_type="application/pdf")


def _senden_viele(liste):
    betr = CFG.get("betreiber", {})
    gesendet, fehler = 0, []
    for r in liste:
        ja, grund = rechnung.versandbereit(r)
        if not ja:
            fehler.append(f"{r.get('nummer') or 'Entwurf'}: {grund}")
            continue
        e = r.get("empfaenger") or {}
        ctx = {"nummer": r.get("nummer", ""), "wohnung": r.get("wohnung_name", ""),
               "name": e.get("name", ""), "von": _d(r.get("anreise")),
               "bis": _d(r.get("abreise")),
               "absender": (betr.get("name", "") + " " + betr.get("zusatz", "")).strip()}
        try:
            pdf = rechnung_pdf.bauen(r, betr)
            mailer.send_form(CFG, pdf, rechnung_pdf.dateiname(r), ctx,
                             subject=mailer.render(BETREFF, ctx),
                             body=mailer.render(TEXT, ctx),
                             to=e.get("email"), cc=False)
        except Exception as ex:
            fehler.append(f"{r.get('nummer')}: {ex}")
            continue
        rechnung.gesendet(r["id"], e.get("email", ""), _cur_user())
        gesendet += 1
    if gesendet:
        ui.notify(f"{gesendet} Rechnung(en) verschickt.", type="positive")
    for f in fehler[:3]:
        ui.notify(f, type="negative", timeout=9000)
    if gesendet:
        ui.navigate.reload()


def _empfaenger_dialog(r):
    e = dict(r.get("empfaenger") or {})
    with ui.dialog() as dlg, ui.card().classes("w-[460px] max-w-full gap-2"):
        ui.label("Rechnungsempfänger").classes("font-bold")
        ui.label("Über 250 € verlangt § 14 UStG Name und Anschrift. Smoobu liefert "
                 "sie meistens mit – wo nicht, muss der Gast sie nachreichen.") \
            .classes(f"text-xs {ton.LEISE}")
        felder = {}
        for schluessel, beschriftung in [("name", "Name"), ("strasse", "Straße und Nr."),
                                         ("plz", "PLZ"), ("ort", "Ort"),
                                         ("land", "Land"), ("email", "E-Mail")]:
            felder[schluessel] = ui.input(beschriftung, value=e.get(schluessel, "")) \
                .props("outlined dense").classes("w-full").mark(f"feld-{schluessel}")

        def sichern():
            neu = {k: (f.value or "").strip() for k, f in felder.items()}
            befunde = [x for x in (r.get("befunde") or []) if "Anschrift" not in x]
            brutto = (r.get("summen") or {}).get("brutto", 0)
            if rechnung.braucht_anschrift(brutto) and not rechnung.anschrift_vollstaendig(neu):
                befunde.append("Über 250 € – Anschrift des Gastes fehlt noch.")
            rechnung.aendern(r["id"], empfaenger=neu, befunde=befunde)
            dlg.close()
            ui.notify("Gespeichert ✓", type="positive")
            ui.navigate.reload()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Speichern", on_click=sichern).props("unelevated") \
                .mark("empfaenger-speichern")
    dlg.open()


def _storno_dialog(r):
    with ui.dialog() as dlg, ui.card().classes("w-[420px] max-w-full gap-2"):
        ui.label(f"Rechnung {r.get('nummer')} stornieren").classes("font-bold")
        ui.label("Die Nummer bleibt vergeben – eine verschwundene Rechnungsnummer ist "
                 "ein Mangel, den jede Prüfung findet. Der Beleg bleibt stehen und "
                 "trägt seinen Grund.").classes(f"text-xs {ton.LEISE}")
        grund = ui.input("Grund").props("outlined dense").classes("w-full") \
            .mark("storno-grund")

        def go():
            rechnung.stornieren(r["id"], grund.value or "", _cur_user())
            protokoll.notieren(_cur_user(), "rechnung_storniert", r.get("nummer", ""),
                               grund.value or "ohne Angabe")
            dlg.close()
            ui.notify("Storniert.", type="warning")
            ui.navigate.reload()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat")
            ui.button("Stornieren", on_click=go).props("unelevated color=negative") \
                .mark("storno-bestaetigen")
    dlg.open()
