#!/usr/bin/env python3
"""Bereich „Überblick": was reinkam, was rausging, was übrig bleibt (B7).

Die Rechnung steht in `app/ueberblick.py` – hier wird sie gezeigt.

**Die wichtigste Gestaltungsentscheidung:** ein Ergebnis, dem noch Geld fehlt,
wird **nicht als Ergebnis dargestellt**. An den echten Zahlen stand für Juni
2026 ein Verlust von 1.489 € – allein deshalb, weil die Einnahmen noch nicht
zugeordnet waren. Wer diese Zahl für das Ergebnis hält, trifft Entscheidungen
auf einer Rechnung, der die halbe Einnahmenseite fehlt. Deshalb steht neben
jedem Monat, wie viel noch offen ist, und nicht belastbare Ergebnisse stehen
blass mit Hinweis statt in Ergebnisfarbe.

Bewusst nüchtern: keine Diagramme. Bei acht Monaten ist eine Tabelle schneller
zu lesen als jedes Bild, und eine Zahl, die man abschreiben kann, ist mehr wert
als eine, die man aus einem Balken schätzt.
"""
from nicegui import ui

from app import konto, uebergabe, ueberblick, vollstaendigkeit
from app.ui.basis import _d
from app.ui import ton

_MONATSNAME = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
               "August", "September", "Oktober", "November", "Dezember"]


def _eur(wert):
    s = f"{abs(wert):,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return ("−" if wert < 0 else "") + s + " €"


def _monatsname(m):
    try:
        jahr, nr = m.split("-")
        return f"{_MONATSNAME[int(nr) - 1]} {jahr}"
    except (ValueError, IndexError):
        return m


def render_ueberblick():
    ui.label("Überblick").classes("text-xl font-bold")
    ui.label("Was reinkam, was rausging, was übrig bleibt – aus den "
             "Kontobewegungen und ihren Zuordnungen. Kein Ersatz für die EÜR "
             "des Steuerbüros, sondern der Blick dazwischen.") \
        .classes("text-sm text-slate-500 mb-2")

    inhalt = ui.column().classes("w-full gap-3")
    zustand = {"von": "", "bis": ""}

    def zeichnen():
        inhalt.clear()
        with inhalt:
            monate = ueberblick.monate(zustand["von"], zustand["bis"])
            if not monate:
                ui.label("Noch keine Bewegungen – erst im Bereich Konto einen "
                         "Auszug einlesen.").classes("text-sm text-slate-400")
                return
            _vollstaendigkeit()
            _uebergabe(zustand)
            _monatstabelle(monate)
            _kategorietabelle(zustand)
            _wohnungstabelle(zustand)

    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
        von = ui.input(label="von").props("type=date dense outlined") \
            .classes("w-[150px]").mark("ub-von")
        bis = ui.input(label="bis").props("type=date dense outlined") \
            .classes("w-[150px]").mark("ub-bis")
        von.on("change", lambda e: (zustand.update(von=von.value or ""), zeichnen()))
        bis.on("change", lambda e: (zustand.update(bis=bis.value or ""), zeichnen()))
        ui.label("Leer lassen = alles.").classes(f"text-xs {ton.STILL}")
    zeichnen()


def _vollstaendigkeit():
    """Steht der Überblick überhaupt auf vollständigen Daten? (B8)

    **Ganz oben, vor den Zahlen.** Ein fehlender Auszugsmonat macht keinen
    Fehler, er macht ein falsches, plausibel aussehendes Ergebnis. Wer die
    Zahlen erst liest und die Einschränkung danach, hat sie schon geglaubt.

    **Kein Ampel-Urteil.** „Alles in Ordnung" wäre eine Behauptung über Daten,
    die das Werkzeug nicht kennen kann – etwa ein Konto, von dem noch nie ein
    Auszug kam.
    """
    b = vollstaendigkeit.befund()
    with ui.card().classes("w-full").mark("ub-vollstaendigkeit"):
        ui.label("Steht das auf vollständigen Daten?").classes("font-medium")
        if not b["auszuege"]:
            ui.label("Zu den eingelesenen Bewegungen liegen keine Kopfdaten vor "
                     "(Zeitraum und Kontostand). Sie entstehen ab dem nächsten "
                     "Import – bis dahin lässt sich Vollständigkeit nicht "
                     "prüfen.").classes(f"text-xs {ton.AUF_HINWEIS}")
        else:
            ui.label(f"{b['auszuege']} Auszüge erfasst · "
                     + ", ".join(b["konten"])).classes(f"text-xs {ton.STILL}")
            if not b["saldo_pruefbar"]:
                ui.label("Der Saldo lässt sich erst ab dem zweiten Auszug eines "
                         "Kontos prüfen – vorher fehlt der Anfangswert.") \
                    .classes(f"text-xs {ton.AUF_HINWEIS}")
            elif not b["saldospruenge"]:
                ui.label("Kontostände und Bewegungen gehen auf.") \
                    .classes(f"text-xs {ton.ERFOLG}")
        for s in b["saldospruenge"]:
            ui.label(f"{s['konto']}: zwischen {_d(s['von'])} und {_d(s['bis'])} "
                     f"fehlen {_eur(abs(s['differenz']))}. Erwartet "
                     f"{_eur(s['erwartet'])}, im Auszug steht "
                     f"{_eur(s['gemeldet'])}.") \
                .classes(f"text-xs {ton.AUF_HINWEIS}").mark("ub-saldosprung")
        for l in b["luecken"]:
            ui.label(f"{l['konto']}: für {_d(l['von'])} bis {_d(l['bis'])} liegt "
                     "kein Auszug vor.").classes(f"text-xs {ton.AUF_HINWEIS}") \
                .mark("ub-luecke")

        # Die Kreditkarte: EINE Sammelbuchung auf dem Girokonto, dieselben
        # Betraege einzeln im Kartenauszug. Fehlt der Kartenauszug, fehlen alle
        # Einzelausgaben – und nichts faellt auf, weil die Sammelbuchung
        # neutral gestellt ist.
        for s in b["karte_ohne_auszug"]:
            ui.label(f"Kreditkartenabrechnung vom {_d(s.get('datum'))} über "
                     f"{_eur(abs(s.get('betrag', 0)))}: dazu liegt kein "
                     "Kartenauszug vor. Solange er fehlt, stehen die "
                     "Einzelausgaben dieses Monats nirgends.") \
                .classes(f"text-xs {ton.AUF_HINWEIS}").mark("ub-karte-fehlt")
        for s in b["giro_fehlt"]:
            # Die gefaehrlichere Richtung: fehlt der BANKauszug, fehlen alle
            # Einnahmen und Ausgaben des Zeitraums, nicht nur Kartenkaeufe.
            ui.label(f"Die Kreditkarte wurde am {_d(s.get('datum'))} mit "
                     f"{_eur(abs(s.get('betrag', 0)))} ausgeglichen – auf dem "
                     "Girokonto steht dazu keine Abrechnung. Für diesen "
                     "Zeitraum fehlt vermutlich der Kontoauszug des "
                     "Girokontos.").classes(f"text-xs {ton.AUF_HINWEIS}") \
                .mark("ub-giro-fehlt")
        for p in b["kartenproben"]:
            ui.label(f"Kartenabrechnung {_d(p['datum'])}: ausgeglichen wurden "
                     f"{_eur(p['ausgleich'])}, erfasst sind aber nur "
                     f"{_eur(abs(p['kaeufe']))} an Käufen "
                     f"({_eur(abs(p['differenz']))} fehlen).") \
                .classes(f"text-xs {ton.AUF_HINWEIS}").mark("ub-kartenprobe")

        o = b["offene_arbeiten"]
        posten = [("Kategorien automatisch erkannt, noch nicht bestätigt",
                   o["automatisch"]),
                  ("Bewegungen mit offenem Rest", o["rest"]),
                  ("Ausgaben ohne Kategorie", o["ohne_kategorie"]),
                  ("Buchungen ohne Beleg", o["ohne_beleg"]),
                  ("Posten ohne Kategorie", o["posten_ohne_kategorie"])]
        if any(n for _name, n in posten):
            ui.label("Noch zu tun – im Bereich Konto:") \
                .classes(f"text-xs mt-1 {ton.STILL}")
            with ui.element("div").classes("w-full grid grid-cols-[auto_1fr] gap-x-3"):
                for name, n in posten:
                    if not n:
                        continue
                    ui.label(str(n)).classes("text-sm font-medium text-right")
                    ui.label(name).classes("text-sm")
        else:
            ui.label("Alle Bewegungen sind zugeordnet.") \
                .classes(f"text-xs {ton.ERFOLG}")


def _uebergabe(zustand):
    """Alles fürs Steuerbüro in einer Datei (B9).

    **Mit Deckblatt, das das Fehlende nennt.** Ein Stapel Belege plus Journal
    sieht nach Abschluss aus; ohne den Hinweis, dass 45 Ausgaben noch keine
    Kategorie tragen, arbeitet das Steuerbüro auf einem Zwischenstand weiter
    und merkt es nicht.

    Kein automatisches Hochladen in die Nextcloud: der Beleg-Ordner wird
    ohnehin gespiegelt, ein zweiter Weg dorthin wäre ein zweiter Mechanismus
    für dieselbe Frage.
    """
    with ui.card().classes("w-full").mark("ub-uebergabe"):
        ui.label("Übergabe ans Steuerbüro").classes("font-medium")
        ui.label("Alle Belege nach Jahr und Monat, das Kontenjournal als CSV "
                 "und ein Deckblatt, das auch nennt, was noch offen ist – "
                 "entweder als Datei zum Herunterladen oder direkt in den "
                 "Übergabe-Ordner (Einstellungen → Ablage), etwa den "
                 "Nextcloud-Ordner.").classes(f"text-xs {ton.STILL}")
        zeilen = len(uebergabe.journal(zustand["von"], zustand["bis"]))
        ohne_nummer = sum(1 for r in uebergabe.receipts.list_receipts(100000)
                          if not (r.get("nummer") or "").strip())
        ui.label(f"{zeilen} Journalzeilen"
                 + (f" · {ohne_nummer} Belege bekommen dabei ihre Belegnummer"
                    if ohne_nummer else "")).classes(f"text-xs {ton.STILL}")

        def laden():
            daten = uebergabe.paket(zustand["von"], zustand["bis"])
            teil = f"_{zustand['von']}_{zustand['bis']}" if zustand["von"] else ""
            ui.download(daten, f"Uebergabe{teil}.zip")
            ui.notify("Paket erstellt ✓ – die Belegnummern sind vergeben.",
                      type="positive")

        def ablegen():
            from app.ui.basis import CFG
            try:
                bericht = uebergabe.ablegen(CFG.get("uebergabe_ordner", ""),
                                            zustand["von"], zustand["bis"])
            except ValueError as fehler:
                ui.notify(str(fehler), type="warning", timeout=9000)
                return
            ui.notify(f"{bericht['dateien']} Dateien abgelegt unter "
                      f"„{bericht['ordner']}“ ✓", type="positive", timeout=8000)

        with ui.row().classes("w-full items-center gap-2"):
            ui.button("Paket herunterladen", icon="download", on_click=laden) \
                .props("unelevated no-caps").mark("uebergabe-laden")
            ui.button("In den Übergabe-Ordner legen", icon="drive_file_move",
                      on_click=ablegen) \
                .props("outline no-caps").mark("uebergabe-ablegen")
            ui.button("Nur das Journal (CSV)", icon="table_view",
                      on_click=lambda: ui.download(
                          uebergabe.journal_csv(zustand["von"], zustand["bis"]),
                          "Kontenjournal.csv")) \
                .props("flat no-caps").mark("uebergabe-csv")


def _monatstabelle(monate):
    """Je Monat: Geldfluss und Ergebnis – nebeneinander, aber nie verwechselbar."""
    gesamt = {k: round(sum(w[k] for w in monate.values()), 2)
              for k in ("eingang", "ausgang", "geldfluss", "ergebnis", "offen_betrag")}
    with ui.card().classes("w-full").mark("ub-monate"):
        ui.label("Je Monat").classes("font-medium")
        ui.label("Geldfluss = was auf dem Konto passiert ist. Ergebnis = ohne "
                 "Privatentnahmen und durchlaufende Posten, und nur aus dem, "
                 "was zugeordnet ist.").classes(f"text-xs {ton.STILL}")
        with ui.element("div").classes(
                "w-full grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-x-4 mt-1"):
            for kopf in ("Monat", "Eingang", "Ausgang", "Geldfluss", "Ergebnis",
                         "davon offen"):
                ui.label(kopf).classes(f"text-xs {ton.ZART} "
                                       + ("" if kopf == "Monat" else "text-right"))
            for m, w in sorted(monate.items(), reverse=True):
                ui.label(_monatsname(m)).classes("text-sm")
                ui.label(_eur(w["eingang"])).classes("text-sm text-right")
                ui.label(_eur(w["ausgang"])).classes("text-sm text-right")
                ui.label(_eur(w["geldfluss"])).classes(f"text-sm text-right {ton.STILL}")
                # Ein Ergebnis, dem Geld fehlt, steht blass da – es ist keins.
                ui.label(_eur(w["ergebnis"])).classes(
                    "text-sm text-right font-medium "
                    + (ton.STILL if not w["belastbar"]
                       else ton.AUF_HINWEIS if w["ergebnis"] < 0 else ""))
                ui.label("—" if w["belastbar"] else _eur(w["offen_betrag"])) \
                    .classes("text-sm text-right "
                             + (ton.STILL if w["belastbar"] else ton.AUF_HINWEIS))
            for kopf, wert in (("Gesamt", None), ("", gesamt["eingang"]),
                               ("", gesamt["ausgang"]), ("", gesamt["geldfluss"]),
                               ("", gesamt["ergebnis"]), ("", gesamt["offen_betrag"])):
                ui.label(kopf if wert is None else _eur(wert)) \
                    .classes("text-sm font-medium border-t pt-1 "
                             + ("" if wert is None else "text-right"))
        if abs(gesamt["offen_betrag"]) >= 0.005:
            # Ohne diesen Satz liest man ein Minus als Verlust. An den echten
            # Zahlen fehlten fast 12.000 EUR – ueberwiegend Einnahmen.
            ui.label(f"{_eur(abs(gesamt['offen_betrag']))} sind noch keiner "
                     "Kategorie zugeordnet und fehlen im Ergebnis. Solange das "
                     "so ist, ist die Ergebnisspalte kein Ergebnis, sondern ein "
                     "Zwischenstand.").classes(f"text-xs mt-2 {ton.AUF_HINWEIS}") \
                .mark("ub-warnung")


def _kategorietabelle(zustand):
    """Je Kategorie – die Frage aus dem Alltag: wo ist das Geld hin?"""
    gruppen = ueberblick.kategorien(zustand["von"], zustand["bis"])
    if not gruppen:
        return
    # Reihenfolge nach Aussagekraft, nicht alphabetisch.
    ordnung = ["Einnahme", "Ausgabe", "Ausgabe/prüfen", "Privat/prüfen",
               "Durchlaufend", "Neutral", ueberblick.UNGEKLAERT]
    with ui.card().classes("w-full").mark("ub-kategorien"):
        ui.label("Je Kategorie").classes("font-medium")
        ui.label("Innerhalb einer Gruppe steht das Größte oben.") \
            .classes(f"text-xs {ton.STILL}")
        for klasse in ordnung + [k for k in gruppen if k not in ordnung]:
            zeilen = gruppen.get(klasse)
            if not zeilen:
                continue
            summe = round(sum(s for _k, s in zeilen), 2)
            with ui.row().classes("w-full items-center gap-2 mt-2 no-wrap"):
                ui.label(klasse).classes("text-sm font-medium")
                ui.space()
                ui.label(_eur(summe)).classes("text-sm font-medium")
            if klasse == ueberblick.UNGEKLAERT:
                ui.label("Diese Beträge stehen in keiner Auswertung – sie "
                         "warten im Konto auf eine Kategorie.") \
                    .classes(f"text-xs {ton.AUF_HINWEIS}")
            with ui.element("div").classes(
                    "w-full grid grid-cols-[1fr_auto] gap-x-4"):
                for name, wert in zeilen:
                    ui.label(name).classes("text-sm truncate")
                    ui.label(_eur(wert)).classes("text-sm text-right")


def _wohnungstabelle(zustand):
    """Je Wohnung – und ehrlich dazu, worauf sich das stützt."""
    from app.ui.basis import _apts
    a = ueberblick.abdeckung(zustand["von"], zustand["bis"])
    if not a["posten"]:
        return
    werte = ueberblick.wohnungen(zustand["von"], zustand["bis"])
    namen = _apts()
    with ui.card().classes("w-full").mark("ub-wohnungen"):
        ui.label("Je Wohnung").classes("font-medium")
        # Die Abdeckung steht VOR der Tabelle. Eine kurze Tabelle liest sich
        # sonst wie „diese Wohnung kostet nichts" – am Bestand trug kein
        # einziger Beleg eine Wohnung.
        ui.label(f"{a['mit_wohnung']} von {a['posten']} Posten lassen sich einer "
                 f"Wohnung zuordnen ({a['anteil'] * 100:.0f} %). Eine Ausgabe "
                 "bekommt ihre Wohnung über den Beleg, eine Einnahme über die "
                 "Rechnung.").classes(
                     f"text-xs {ton.STILL if a['anteil'] > 0.8 else ton.AUF_HINWEIS}") \
            .mark("ub-abdeckung")
        if not werte:
            ui.label("Deshalb steht hier noch nichts.") \
                .classes(f"text-sm {ton.STILL}")
            return
        with ui.element("div").classes(
                "w-full grid grid-cols-[1fr_auto_auto_auto] gap-x-4 mt-1"):
            for kopf in ("Wohnung", "Einnahmen", "Ausgaben", "Saldo"):
                ui.label(kopf).classes(f"text-xs {ton.ZART} "
                                       + ("" if kopf == "Wohnung" else "text-right"))
            for wid, w in sorted(werte.items(),
                                 key=lambda kv: -kv[1]["einnahmen"]):
                ui.label(namen.get(wid) or str(wid)).classes("text-sm truncate")
                ui.label(_eur(w["einnahmen"])).classes("text-sm text-right")
                ui.label(_eur(w["ausgaben"])).classes("text-sm text-right")
                ui.label(_eur(round(w["einnahmen"] + w["ausgaben"], 2))) \
                    .classes("text-sm text-right font-medium")
