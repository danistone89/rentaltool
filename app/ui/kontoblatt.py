"""Bereich „Konto": Auszüge einlesen und Bewegungen ansehen (AP16).

Der erste Schritt der Buchhaltungskette. Zugeordnet wird hier noch nichts – das
kommt mit AP20; hier geht es darum, die Bewegungen überhaupt im Werkzeug zu
haben und zu sehen, was Monat für Monat rein- und rausgeht.

**Die Rückmeldung nach dem Einlesen nennt bewusst auch die Dubletten.** Bei
überlappenden Auszügen ist es der Normalfall, dass aus 169 Zeilen 12 neue Sätze
werden. Ohne die Zahl daneben sieht das nach einem Fehler aus.
"""
from nicegui import ui

from app import konto, kontoauszug, zuordnung
from app.ui.basis import _read_upload, _d
from app.ui import ton


def _eur(wert):
    s = f"{abs(wert):,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return ("−" if wert < 0 else "") + s + " €"


def _kategorie_wahl(bewegung):
    """Die Kategorie einer Ausgabe wählen – und die Wahl merken.

    Das ist der Kern der Bedienung: einmal zuordnen, und derselbe Empfänger
    wird beim nächsten Auszug von allein erkannt. Ohne das Lernen wäre jeder
    Monat dieselbe Handarbeit – und genau davor soll das Werkzeug bewahren.
    """
    from app import buchhaltung, db, stammdaten
    from app.ui.basis import CFG

    def gesetzt(e):
        kategorie = e.value or ""
        klasse = buchhaltung.klasse_fuer(kategorie) if kategorie else ""
        db.speichern(konto.TABELLE, bewegung["id"],
                     dict(bewegung, kategorie=kategorie, klasse=klasse,
                          herkunft="hand"))
        k = stammdaten.kategorie_lernen(bewegung.get("gegenpartei"), kategorie)
        hinweis = (f"Gemerkt: „{k['name']}“ ist ab jetzt {kategorie}." if k
                   else "Kategorie gesetzt.")
        ui.notify(hinweis, type="positive", timeout=2500)

    ui.select({"": "— zuordnen —",
               **{x: x for x in buchhaltung.kategorien(CFG)}},
              value=bewegung.get("kategorie") or "", on_change=gesetzt) \
        .props("dense borderless options-dense").classes(
            "text-xs shrink-0 w-[190px] " +
            (ton.AUF_HINWEIS if bewegung.get("klasse") in ("Privat/prüfen",
                                                           "Ausgabe/prüfen") else "")) \
        .mark(f"kat-{bewegung['id']}")


def _beleg_knopf(bewegung, neu_zeichnen):
    """Beleg zu dieser Buchung: hochladen, ansehen oder als nicht nötig abhaken.

    **Der Weg geht von der Buchung aus, nicht vom Beleg.** Im Alltag sieht man
    eine Abbuchung und hat das Papier in der Hand – nicht umgekehrt. Wer erst
    in die Belege wechseln, hochladen und dann die passende Buchung suchen
    müsste, tut es nicht.
    """
    from app import housekeeping, receipts
    from app.ui.basis import _read_upload

    beleg_id = (konto.belege_von(bewegung) or [""])[0]
    if beleg_id:
        ui.button(icon="description",
                  on_click=lambda: konto.beleg_setzen(bewegung["id"], "") or neu_zeichnen()) \
            .props("flat dense round color=positive") \
            .tooltip("Beleg hängt dran – klicken löst ihn wieder").classes("shrink-0")
        return
    # Hochladen geht IMMER, solange es eine Ausgabe ist. `beleg_erwartet`
    # beantwortet eine andere Frage – ob die Buchung in der Liste „fehlt noch"
    # steht –, und die setzt eine Kategorie voraus. Hier wäre das falsch: wer
    # den Kassenbon in der Hand hat, soll ihn anhängen können, ohne vorher zu
    # kategorisieren. (Erst gemeldet an einer Netto-Buchung ohne Kategorie:
    # dort fehlte der Knopf ganz.)
    if bewegung.get("umbuchung") or bewegung.get("betrag", 0) >= 0:
        return

    async def hochladen(e):
        try:
            rohdaten, name = await _read_upload(e)
            endung = (name.rsplit(".", 1)[-1] if "." in name else "jpg").lower()[:4]
            doc = receipts.save_document(rohdaten, endung,
                                         crop=not receipts.ist_pdf(rohdaten))
            # Was die Bank schon weiß, muss niemand abtippen: Betrag, Datum und
            # Händler stehen in der Bewegung.
            beleg = receipts.add_receipt(
                "konto", doc["photo"], pdf=doc.get("pdf"),
                amount=f"{abs(bewegung['betrag']):.2f}".replace(".", ","),
                merchant=bewegung.get("gegenpartei", ""),
                kategorie=bewegung.get("kategorie", ""))
            receipts.update_receipt(beleg["id"], datum=bewegung.get("datum", ""))
            konto.beleg_setzen(bewegung["id"], beleg["id"])
        except Exception as fehler:
            ui.notify(f"Beleg konnte nicht gespeichert werden: {fehler}", type="negative")
            return
        ui.notify("Beleg gespeichert und zugeordnet ✓", type="positive")
        neu_zeichnen()

    def dauerbeleg():
        """Einmal sagen, dass hier ein Vertrag statt monatlicher Belege gilt.

        Ohne diesen Weg müsste man jede Mietzahlung einzeln abhaken – sieben im
        Halbjahr, und im nächsten wieder. Gemerkt wird es am **Empfänger**,
        nicht an der einzelnen Buchung.
        """
        from app import stammdaten
        k = stammdaten.dauerbeleg_lernen(bewegung.get("gegenpartei"),
                                         "Dauerbeleg (Vertrag liegt vor)",
                                         bewegung.get("kategorie", ""))
        ui.notify(f"„{k['name']}“ braucht künftig keinen Monatsbeleg mehr."
                  if k else "Kein Empfänger erkennbar.",
                  type="positive" if k else "warning")
        neu_zeichnen()

    with ui.row().classes("items-center gap-0 shrink-0 no-wrap"):
        ui.upload(auto_upload=True, on_upload=hochladen, label="") \
            .props('accept="image/*,application/pdf" flat dense') \
            .classes("hk-upload w-[34px]").tooltip("Beleg hochladen") \
            .mark(f"beleg-up-{bewegung['id']}")
        ui.button(icon="event_repeat", on_click=dauerbeleg) \
            .props("flat dense round").classes(ton.ZART) \
            .tooltip("Dauerbeleg: Vertrag liegt vor, keine Monatsbelege nötig – "
                     "gilt ab jetzt für alle Zahlungen an diesen Empfänger") \
            .mark(f"dauer-{bewegung['id']}")
        ui.button(icon="block",
                  on_click=lambda: (konto.beleg_nicht_noetig(bewegung["id"]),
                                    neu_zeichnen())) \
            .props("flat dense round").classes(ton.ZART) \
            .tooltip("Nur für diese eine Buchung: es gibt keinen Beleg")


_ARTNAME = {zuordnung.RECHNUNG: "Ausgangsrechnung", zuordnung.BELEG: "Beleg",
            zuordnung.KATEGORIE: "nur Kategorie"}


def _zuordnungsmaske(bewegung, neu_zeichnen):
    """Eine Bewegung aufteilen – der Bildschirm, an dem die Arbeit stattfindet.

    **Der Restbetrag ist die Anleitung.** Er steht groß daneben und zählt mit
    jedem Posten herunter. Ist er null, ist die Bewegung fertig; bleibt etwas
    übrig, fehlt noch ein Posten – bei einer Portal-Auszahlung genau die
    Provision. Niemand muss wissen, wie viele Posten „richtig" sind: die Zahl
    sagt es.

    Der Betrag eines neuen Postens ist mit dem **Rest** vorbelegt. Im häufigen
    Fall – eine Zahlung, eine Kategorie – ist die Maske damit ein Klick.
    """
    from app import buchhaltung
    from app.ui.basis import CFG

    p = zuordnung.posten(bewegung["id"])
    rest = zuordnung.rest(bewegung)

    with ui.column().classes("w-full gap-1 pl-2 border-l-2 border-slate-100"):
        # Ohne diesen Satz ist „+" nicht zu erraten – so gemeldet.
        ui.label("Wofür war diese Zahlung? Eine Zahlung kann auf mehrere "
                 "Kategorien aufgeteilt werden – bei einer Portal-Auszahlung "
                 "auf mehrere Rechnungen plus die Provision. Der Rest unten "
                 "zeigt, was davon noch offen ist.") \
            .classes(f"text-xs {ton.STILL} mb-1")
        for satz in p:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(_ARTNAME.get(satz["art"], satz["art"])) \
                    .classes("text-xs text-slate-400 w-32 shrink-0")
                ui.label(satz.get("kategorie") or satz.get("ziel_id") or "—") \
                    .classes("text-sm truncate flex-grow min-w-0")
                ui.label(_eur(satz["betrag"])).classes("text-sm w-28 text-right shrink-0")
                ui.button(icon="close",
                          on_click=lambda s=satz: (zuordnung.entfernen(s["id"]),
                                                   neu_zeichnen())) \
                    .props("flat dense round").classes(f"{ton.ZART} shrink-0") \
                    .tooltip("Posten lösen")

        # ---- Neuer Posten: Kategorie und Betrag ------------------------------
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            kat = ui.select({"": "— Kategorie —",
                             **{x: x for x in buchhaltung.kategorien(CFG)}},
                            value=bewegung.get("kategorie") or "") \
                .props("dense borderless options-dense").classes("flex-grow min-w-0") \
                .mark(f"zu-kat-{bewegung['id']}")
            betrag = ui.number(value=abs(rest) if abs(rest) > 0.005 else None,
                               format="%.2f", step=0.01) \
                .props("dense borderless").classes("w-24 shrink-0") \
                .mark(f"zu-betrag-{bewegung['id']}")

            def anlegen():
                try:
                    wert = float(betrag.value or 0)
                except (TypeError, ValueError):
                    wert = 0.0
                # Das Vorzeichen kommt von der Bewegung, nicht vom Tippen: bei
                # einer Ausgabe ist der Posten negativ. Wer es umdrehen will –
                # die Provision einer Auszahlung –, gibt eine negative Zahl ein.
                if wert > 0 and bewegung.get("betrag", 0) < 0:
                    wert = -wert
                satz, meldung = zuordnung.hinzufuegen(
                    bewegung["id"], zuordnung.KATEGORIE, wert, kat.value or "")
                ui.notify(meldung, type="positive" if satz else "warning")
                if satz:
                    neu_zeichnen()

            # Beschriftung nach Lage: der erste Posten ist eine Zuordnung,
            # jeder weitere teilt die Zahlung auf.
            ui.button("Zuordnen" if not p else "Aufteilen", icon="add",
                      on_click=anlegen) \
                .props("dense unelevated no-caps size=sm") \
                .tooltip("Diesen Betrag der gewählten Kategorie zuordnen") \
                .mark(f"zu-plus-{bewegung['id']}")

        # ---- Der Restbetrag --------------------------------------------------
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            fertig = zuordnung.ist_fertig(bewegung)
            ui.label("Rest").classes("text-xs text-slate-400 flex-grow")
            ui.label(_eur(0 if fertig else rest)).classes(
                "text-sm font-medium w-28 text-right "
                + (ton.STILL if fertig else ton.AUF_HINWEIS)) \
                .mark(f"zu-rest-{bewegung['id']}")
            if bewegung.get("betrag", 0) < 0:
                _beleg_knopf(bewegung, neu_zeichnen)


def render_konto():
    ui.label("Konto").classes("text-xl font-bold")
    ui.label("Kontoauszüge einlesen – Geschäftskonto und Kreditkarte. "
             "Grundlage für den Überblick und für die Übergabe ans Steuerbüro.") \
        .classes("text-sm text-slate-500 mb-2")

    inhalt = ui.column().classes("w-full gap-3")
    # Welche Sicht auf die Bewegungen gerade gilt. Ueberlebt das Neuzeichnen –
    # sonst springt die Liste nach jedem Posten auf „Alle" zurueck.
    zustand = {"sicht": "alle"}

    async def hochladen(e):
        try:
            rohdaten, name = await _read_upload(e)
            bericht = konto.importieren(rohdaten)
        except ValueError as fehler:                # unbekanntes Format
            ui.notify(str(fehler), type="warning", timeout=8000)
            return
        except Exception as fehler:
            ui.notify(f"Auszug konnte nicht gelesen werden: {fehler}", type="negative")
            return
        teile = [f"{bericht['neu']} neu"]
        if bericht["doppelt"]:
            teile.append(f"{bericht['doppelt']} schon vorhanden")
        if bericht["umbuchungen"]:
            teile.append(f"{bericht['umbuchungen']} Umbuchungen")
        ui.notify(f"{bericht['konto']}: " + " · ".join(teile), type="positive",
                  timeout=6000)
        zeichnen()

    with ui.row().classes("w-full items-center gap-3"):
        ui.upload(auto_upload=True, on_upload=hochladen, label="Auszug (CSV) wählen") \
            .props('accept=".csv,text/csv"').classes("hk-upload w-[240px]") \
            .mark("konto-upload")
        ui.label("DKB-Business oder DKB-VISA, als CSV exportiert.") \
            .classes("text-xs text-slate-400")

    def zeichnen():
        inhalt.clear()
        with inhalt:
            bewegungen = konto.alle()
            if not bewegungen:
                ui.label("Noch kein Auszug eingelesen.").classes("text-sm text-slate-400")
                return

            von, bis = konto.zeitraum()
            ui.label(f"{len(bewegungen)} Bewegungen · {_d(von)} bis {_d(bis)} · "
                     f"{', '.join(konto.konten())}").classes("text-sm text-slate-500")

            # ---- Monatssummen: die gröbste Form des Überblicks --------------
            summen = konto.monatssummen()
            offen = konto.ohne_zuordnung()
            if summen:
                with ui.card().classes("w-full").mark("konto-monate"):
                    ui.label("Je Monat").classes("font-medium")
                    # Die beiden Spalten heißen bewusst verschieden. „Geldfluss"
                    # ist, was auf dem Konto passiert ist; „Ergebnis" lässt
                    # Privatentnahmen und durchlaufende Posten weg. Über das
                    # erste Halbjahr liegen dazwischen mehr als 6.000 €.
                    ui.label("Geldfluss = was auf dem Konto passiert ist. "
                             "Ergebnis = ohne Privatentnahmen und durchlaufende "
                             "Posten.").classes("text-xs text-slate-400")
                    with ui.element("div").classes(
                            "w-full grid grid-cols-[1fr_auto_auto_auto_auto] gap-x-4 mt-1"):
                        for kopf in ("Monat", "Eingang", "Ausgang", "Geldfluss", "Ergebnis"):
                            ui.label(kopf).classes("text-xs text-slate-400 "
                                                   + ("" if kopf == "Monat" else "text-right"))
                        for monat, w in sorted(summen.items(), reverse=True):
                            fluss = round(w["eingang"] + w["ausgang"], 2)
                            ui.label(monat + ("  •" if w["unklar"] else "")) \
                                .tooltip(f"{w['unklar']} Ausgänge noch ohne Zuordnung"
                                         if w["unklar"] else "")
                            ui.label(_eur(w["eingang"])).classes("text-right")
                            ui.label(_eur(w["ausgang"])).classes("text-right")
                            ui.label(_eur(fluss)).classes("text-right text-slate-500")
                            ui.label(_eur(w["ergebnis"])).classes(
                                "text-right font-medium "
                                + (ton.AUF_HINWEIS if w["ergebnis"] < 0 else ""))
                    if offen:
                        # Ohne diesen Satz liest jemand das Ergebnis als fertig.
                        ui.label(f"{len(offen)} Ausgänge sind noch keiner Kategorie "
                                 "zugeordnet – das Ergebnis ist so lange eine "
                                 "Näherung.").classes("text-xs mt-2 " + ton.AUF_HINWEIS) \
                            .mark("konto-unklar")

            # ---- Die Bewegungen -------------------------------------------
            # EINE Liste, drei Sichten. Vorher stand daneben eine zweite Karte
            # „Fehlende Belege" mit denselben Zeilen – zwei Listen, die dasselbe
            # zeigen, verwirren mehr als sie helfen (so gemeldet am 8.8.2026).
            fehlen_ids = {x["id"] for x in konto.ohne_beleg()}
            offen_ids = {x["id"] for x in offen}
            with ui.card().classes("w-full").mark("konto-liste"):
                with ui.row().classes("w-full items-center gap-2"):
                    ui.label("Bewegungen").classes("font-medium")
                    ui.space()
                    ui.toggle({"alle": f"Alle ({len(bewegungen)})",
                               "offen": f"Nicht zugeordnet ({len(offen_ids)})",
                               "beleg": f"Beleg fehlt ({len(fehlen_ids)})"},
                              value=zustand["sicht"],
                              on_change=lambda e: (zustand.update(sicht=e.value),
                                                   zeichnen())) \
                        .props("dense no-caps unelevated size=sm").mark("konto-sicht")
                if zustand["sicht"] == "offen":
                    bewegungen = [b for b in bewegungen if b["id"] in offen_ids]
                    ui.label("Ausgänge ohne Kategorie. Erst zuordnen – vorher "
                             "steht nicht fest, ob es dazu überhaupt einen Beleg "
                             "gibt.").classes(f"text-xs {ton.STILL}")
                elif zustand["sicht"] == "beleg":
                    bewegungen = [b for b in bewegungen if b["id"] in fehlen_ids]
                    ui.label("Zugeordnet, aber der Beleg fehlt. Privatentnahmen, "
                             "Löhne, Darlehen und Dauerbelege stehen hier bewusst "
                             "nicht.").classes(f"text-xs {ton.STILL}")
                # Jede Zeile lässt sich aufklappen. Zugeklappt sagt sie, ob die
                # Bewegung fertig ist; aufgeklappt steht die Zuordnungsmaske
                # darin. So bleibt die Liste lesbar und die Arbeit ist einen
                # Klick entfernt – ohne Wechsel auf eine andere Seite.
                for b in bewegungen[:200]:
                    fertig = zuordnung.ist_fertig(b)
                    zeile = ui.expansion().classes("w-full").props("dense") \
                        .mark(f"bew-{b['id']}")
                    with zeile.add_slot("header"):
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            ui.label(_d(b["datum"])) \
                                .classes("text-xs text-slate-400 w-20 shrink-0")
                            with ui.column().classes("gap-0 min-w-0 flex-grow"):
                                ui.label(b.get("gegenpartei") or "—") \
                                    .classes("text-sm truncate")
                                if b.get("text") and b["text"] != b.get("gegenpartei"):
                                    ui.label(b["text"]) \
                                        .classes("text-xs text-slate-400 truncate")
                            if b.get("umbuchung"):
                                ui.label("Umbuchung") \
                                    .classes("text-xs text-slate-400 shrink-0")
                            elif fertig:
                                ui.icon("check_circle") \
                                    .classes(f"text-base {ton.ERFOLG} shrink-0") \
                                    .tooltip("vollständig zugeordnet")
                            elif zuordnung.hat_posten(b["id"]):
                                ui.label(f"Rest {_eur(zuordnung.rest(b))}") \
                                    .classes("text-xs shrink-0 " + ton.AUF_HINWEIS)
                            ui.label(_eur(b["betrag"])).classes(
                                "text-sm text-right w-28 shrink-0 "
                                + ("" if b["betrag"] > 0 else "text-slate-600"))
                    with zeile:
                        if b.get("umbuchung"):
                            ui.label("Umbuchung zwischen eigenen Konten – hier "
                                     "gibt es nichts zuzuordnen.") \
                                .classes("text-xs text-slate-400")
                        else:
                            _zuordnungsmaske(b, zeichnen)
                if len(bewegungen) > 200:
                    ui.label(f"… und {len(bewegungen) - 200} weitere") \
                        .classes("text-xs text-slate-400 mt-1")

    zeichnen()
