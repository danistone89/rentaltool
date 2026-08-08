"""Bereich „Konto": Auszüge einlesen und Bewegungen ansehen (AP16).

Der erste Schritt der Buchhaltungskette. Zugeordnet wird hier noch nichts – das
kommt mit AP20; hier geht es darum, die Bewegungen überhaupt im Werkzeug zu
haben und zu sehen, was Monat für Monat rein- und rausgeht.

**Die Rückmeldung nach dem Einlesen nennt bewusst auch die Dubletten.** Bei
überlappenden Auszügen ist es der Normalfall, dass aus 169 Zeilen 12 neue Sätze
werden. Ohne die Zahl daneben sieht das nach einem Fehler aus.
"""
from nicegui import ui

from app import konto, kontoauszug, verrechnung, zuordnung
from app.ui.basis import _read_upload, _d
from app.ui import ton


def _eur(wert):
    s = f"{abs(wert):,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return ("−" if wert < 0 else "") + s + " €"


def _kategorie_wahl(bewegung, neu_zeichnen):
    """Die Kategorie direkt in der Zeile – ein Klick für den einfachen Fall.

    **Warum sie zurückkommt.** Bis Paket B2 stand sie hier; seither musste man
    jede Bewegung erst aufklappen. Bei 17 Lohnzahlungen ist das der Unterschied
    zwischen einem Nachmittag und einer Minute (so gemeldet am 8.8.2026).

    Sie erscheint **nur bei Ausgaben ohne Posten**. Wo schon etwas hängt, gilt
    die Maske: ein Klick kann eine Aufteilung nicht kennen. Und bei einem
    Eingang entscheidet die zugeordnete Rechnung, was ein Erlös ist – nicht der
    Name des Absenders.
    """
    from app import buchhaltung
    from app.ui.basis import CFG

    if (bewegung.get("umbuchung") or bewegung.get("betrag", 0) >= 0
            or zuordnung.hat_posten(bewegung["id"])):
        return

    def gesetzt(e):
        if not e.value:
            return
        # Auch wenn dieselbe Kategorie gewaehlt wird: die Bewegung bekommt
        # dadurch ihren Posten und der Empfaenger wird gemerkt.
        satz, weitere = konto.schnell_zuordnen(bewegung["id"], e.value)
        if not satz:
            return
        name = bewegung.get("gegenpartei") or ""
        if weitere:
            # Es wurden Bewegungen berührt, die niemand einzeln gesehen hat –
            # das muss man sagen und zurücknehmen können. Gemeldet am
            # 8.8.2026: „bei allen anderen hat sich nichts geändert."
            _mitgezogen_zeigen(name, e.value, weitere, neu_zeichnen)
        else:
            ui.notify(f"Zugeordnet ✓ – „{name}“ ist ab jetzt gemerkt.",
                      type="positive", timeout=2500)
        neu_zeichnen()

    # Die gesetzte Kategorie steht als Wert drin, nicht „— zuordnen —". Sonst
    # sieht eine erkannte Bewegung aus wie unbearbeitet, und ein Klick auf
    # dieselbe Kategorie scheint wirkungslos (so gemeldet am 8.8.2026 an
    # Smoobu).
    jetzige = (bewegung.get("kategorie") or "").strip()
    auswahl = {"": "— zuordnen —", **{x: x for x in buchhaltung.kategorien(CFG)}}
    if jetzige and jetzige not in auswahl:
        auswahl[jetzige] = f"{jetzige} (nicht mehr in der Liste)"
    ui.select(auswahl, value=jetzige, on_change=gesetzt) \
        .props("dense borderless options-dense").classes(
            f"text-xs shrink-0 w-[190px] "
            + (ton.STILL if not jetzige else "")) \
        .mark(f"kat-{bewegung['id']}")
    if bewegung.get("herkunft") == "kreditor" and jetzige:
        # Was die Maschine entschieden hat, muss man sehen. Die Erkennung ueber
        # den Empfaenger hat am 8.8.2026 68 Kategorien gesetzt, ohne zu fragen –
        # und nichts wies darauf hin. Ein Klick auf dieselbe Kategorie ist die
        # Bestaetigung, danach verschwindet die Markierung.
        ui.icon("auto_awesome").classes(f"text-xs shrink-0 {ton.AUF_HINWEIS}") \
            .tooltip("Automatisch über den Empfänger erkannt – noch nicht "
                     "bestätigt. Kategorie auswählen bestätigt sie.") \
            .mark(f"auto-{bewegung['id']}")


def _mitgezogen_zeigen(name, kategorie, ids, neu_zeichnen):
    """Sagen, was außer der angeklickten Zeile noch zugeordnet wurde.

    Wer entschieden hat, wofür eine Zahlung an diese Person ist, hat es für
    alle entschieden – aber gesehen hat er nur die eine. Deshalb: Zahl nennen,
    Rückweg anbieten.
    """
    with ui.dialog() as dlg, ui.card().classes("w-[480px] max-w-full gap-2"):
        ui.label(f"{len(ids) + 1} Zahlungen zugeordnet").classes("font-medium")
        ui.label(f"Alle offenen Zahlungen an „{name}“ stehen jetzt unter "
                 f"„{kategorie}“ – die angeklickte und {len(ids)} weitere. "
                 "Künftige Zahlungen an diesen Empfänger werden von allein "
                 "erkannt.").classes(f"text-xs {ton.STILL}")
        with ui.column().classes("w-full gap-1"):
            for bid in ids[:12]:
                b = konto.holen(bid)
                if not b:
                    continue
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.label(_d(b.get("datum"))).classes(f"text-xs w-20 {ton.STILL}")
                    ui.label(b.get("gegenpartei") or "—") \
                        .classes("text-xs flex-grow min-w-0 truncate")
                    ui.label(_eur(b.get("betrag", 0))) \
                        .classes("text-xs w-24 text-right")
            if len(ids) > 12:
                ui.label(f"… und {len(ids) - 12} weitere") \
                    .classes(f"text-xs {ton.STILL}")

        def zurueck():
            n = konto.zuruecknehmen(ids)
            dlg.close()
            ui.notify(f"{n} zurückgenommen – nur die angeklickte Zahlung bleibt "
                      "zugeordnet.", type="warning")
            neu_zeichnen()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Nur diese eine", on_click=zurueck) \
                .props("flat no-caps dense").mark("mitgezogen-zurueck")
            ui.button("Gut so", on_click=dlg.close) \
                .props("unelevated no-caps dense").mark("mitgezogen-ok")
    dlg.open()


def _beleg_waehlen(bewegung, neu_zeichnen):
    """Einen **vorhandenen** Beleg an diese Bewegung hängen (B5).

    Der zweite Weg neben dem Hochladen: was jemand unterwegs fotografiert hat,
    liegt schon im Werkzeug und war für die Buchhaltung bisher unsichtbar.

    **Zwei Gruppen, und die zweite ist der eigentliche Punkt:** unten stehen
    Belege, die schon woanders hängen, aber noch nicht ganz verteilt sind. Der
    Provisionsbeleg von Booking kommt monatlich, die Auszahlungen kommen
    einzeln – ohne diese Gruppe ließe er sich nach der ersten Auszahlung nicht
    mehr auswählen.
    """
    from app import belegzuordnung as bz, buchhaltung

    frei = bz.belege_zu(bewegung) if bewegung.get("betrag", 0) < 0 else []
    offen = bz.teilweise_verteilt()
    if not frei and not offen:
        return

    def anhaengen(beleg_id, dlg):
        erfolg = konto.beleg_anhaengen(bewegung["id"], beleg_id)
        dlg.close()
        if erfolg is None:
            # An einer Auszahlung braucht der Beleg einen negativen Posten, an
            # den er gehoert. Lieber nichts tun und es sagen, als den Umsatz
            # der Auszahlung als Ausgabe zu buchen.
            ui.notify("Dazu fehlt noch die gegengebuchte Provision. Erst "
                      "„Provision …“ drücken, dann den Beleg zuordnen.",
                      type="warning", timeout=8000)
        else:
            ui.notify("Beleg zugeordnet ✓", type="positive")
        neu_zeichnen()

    def zeile(r, grund, dlg):
        wert = buchhaltung.betrag_zahl(r.get("amount"))
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            with ui.column().classes("gap-0 min-w-0 flex-grow"):
                ui.label(r.get("merchant") or "(ohne Händler)").classes("text-sm truncate")
                ui.label(f"{_d(buchhaltung.belegdatum(r))} · {grund}") \
                    .classes(f"text-xs {ton.STILL} truncate")
            ui.label("—" if wert is None else _eur(-abs(wert))) \
                .classes("text-sm w-24 text-right shrink-0")
            ui.button(icon="add", on_click=lambda i=r["id"]: anhaengen(i, dlg)) \
                .props("flat dense round").tooltip("Dieser Bewegung zuordnen") \
                .mark(f"bw-add-{r['id']}")

    def oeffnen():
        with ui.dialog() as dlg, ui.card().classes("w-[560px] max-w-full gap-2"):
            ui.label("Vorhandenen Beleg zuordnen").classes("font-medium")
            # Kein Deckel bei 20: wer weiss, welchen Beleg er sucht, muss ihn
            # finden koennen, auch wenn er nicht zufaellig oben steht.
            liste = ui.column().classes("w-full gap-1")

            def zeichnen(suche=""):
                f_frei = bz.filtern(frei, suche, "beleg")
                f_offen = bz.filtern(offen, suche, "beleg")
                liste.clear()
                with liste:
                    if not f_frei and not f_offen:
                        ui.label("Nichts gefunden – Suchbegriff ändern.") \
                            .classes(f"text-xs {ton.AUF_HINWEIS}")
                    with ui.scroll_area().classes("w-full h-[320px]"):
                        if f_frei:
                            ui.label(f"Noch keiner Bewegung zugeordnet "
                                     f"({len(f_frei)} von {len(frei)}) – "
                                     "wahrscheinlichster zuerst") \
                                .classes(f"text-xs {ton.STILL}")
                            for k in f_frei:
                                zeile(k["beleg"], k["grund"], dlg)
                        if f_offen:
                            ui.separator()
                            ui.label("Noch nicht ganz verteilt – etwa der "
                                     "Monatsbeleg eines Portals") \
                                .classes(f"text-xs {ton.STILL}")
                            for r in f_offen:
                                verteilt, soll, _ = bz.belegprobe(r)
                                zeile(r, f"davon {_eur(verteilt)} verteilt, "
                                         f"{_eur(round((soll or 0) - verteilt, 2))} offen",
                                      dlg)

            if len(frei) + len(offen) > 8:
                ui.input(placeholder="Suchen: Händler, Datum, Betrag",
                         on_change=lambda e: zeichnen(e.value)) \
                    .props("dense outlined clearable").classes("w-full") \
                    .mark(f"bw-suche-{bewegung['id']}")
            zeichnen()
            ui.button("Schließen", on_click=dlg.close).props("flat no-caps dense")
        dlg.open()

    ui.button(icon="attach_file", on_click=oeffnen) \
        .props("flat dense round").classes(f"{ton.ZART} shrink-0") \
        .tooltip("Vorhandenen Beleg zuordnen") \
        .mark(f"beleg-waehl-{bewegung['id']}")


def _beleg_knopf(bewegung, neu_zeichnen):
    """Beleg zu dieser Buchung: hochladen, ansehen oder als nicht nötig abhaken.

    **Der Weg geht von der Buchung aus, nicht vom Beleg.** Im Alltag sieht man
    eine Abbuchung und hat das Papier in der Hand – nicht umgekehrt. Wer erst
    in die Belege wechseln, hochladen und dann die passende Buchung suchen
    müsste, tut es nicht.
    """
    from app import housekeeping, receipts
    from app.ui.basis import _read_upload

    # Alle anhängenden Belege, jeder einzeln lösbar. Vorher stand hier nur der
    # erste – und ein Klick darauf löste über `beleg_setzen` ALLE Posten der
    # Bewegung, auch die Aufteilung auf Kategorien.
    for bid in konto.belege_von(bewegung):
        ui.button(icon="description",
                  on_click=lambda i=bid: (konto.beleg_loesen(bewegung["id"], i),
                                          neu_zeichnen())) \
            .props("flat dense round color=positive") \
            .tooltip("Beleg hängt dran – klicken löst ihn wieder").classes("shrink-0")

    _beleg_waehlen(bewegung, neu_zeichnen)

    # Hochladen geht IMMER, solange es eine Ausgabe ist. `beleg_erwartet`
    # beantwortet eine andere Frage – ob die Buchung in der Liste „fehlt noch"
    # steht –, und die setzt eine Kategorie voraus. Hier wäre das falsch: wer
    # den Kassenbon in der Hand hat, soll ihn anhängen können, ohne vorher zu
    # kategorisieren. (Erst gemeldet an einer Netto-Buchung ohne Kategorie:
    # dort fehlte der Knopf ganz.)
    if bewegung.get("betrag", 0) >= 0:
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
            # `beleg_anhaengen` statt `beleg_setzen`: der alte Weg loeste erst
            # ALLE Posten – wer eine Zahlung auf zwei Kategorien aufgeteilt
            # hatte und dann den Bon anhaengte, verlor die Aufteilung.
            konto.beleg_anhaengen(bewegung["id"], beleg["id"])
        except Exception as fehler:
            ui.notify(f"Beleg konnte nicht gespeichert werden: {fehler}", type="negative")
            return
        from app import belegzuordnung as bz
        doppelt = bz.dubletten(dict(beleg, datum=bewegung.get("datum", "")))
        if doppelt:
            # Gewarnt, nicht verhindert: zwei Quittungen desselben Tages ueber
            # denselben Betrag gibt es wirklich.
            ui.notify(f"Zugeordnet ✓ – aber es gibt schon {len(doppelt)} Beleg(e) "
                      "mit gleichem Betrag um dasselbe Datum. Bitte pruefen, ob "
                      "es derselbe ist.", type="warning", timeout=9000)
        else:
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
        if bewegung.get("umbuchung"):
            return              # Dokument ja, Dauerbeleg/„kein Beleg" nein
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


def _posten_text(satz):
    """Was am Posten steht – die Rechnungsnummer, nicht die interne Kennung.

    Vorher stand dort „ffed1df3f8c3". Eine Kennung, die nur die Datenbank
    kennt, sagt dem Menschen nichts; er sucht die Rechnung dann von Hand.
    """
    from app import db
    if satz["art"] == zuordnung.RECHNUNG and satz.get("ziel_id"):
        r = db.holen("rechnungen", satz["ziel_id"]) or {}
        teile = [f"Nr. {r['nummer']}" if r.get("nummer") else "", r.get("gast", "")]
        klar = " · ".join(x for x in teile if x)
        if klar:
            return klar
    if satz["art"] == zuordnung.BELEG and satz.get("ziel_id"):
        b = db.holen("belege", satz["ziel_id"]) or {}
        teile = [b.get("merchant", ""), b.get("datum", "")]
        klar = " · ".join(x for x in teile if x)
        if klar:
            return klar
    return (satz.get("kategorie") or satz.get("notiz")
            or satz.get("ziel_id") or "—")


def _provision_buchen(bewegung, rest, kategorie, neu_zeichnen):
    satz, meldung = zuordnung.hinzufuegen(
        bewegung["id"], zuordnung.KATEGORIE, rest, kategorie,
        notiz="Provision des Portals")
    ui.notify(meldung, type="positive" if satz else "warning")
    if satz:
        neu_zeichnen()


def _kategorie_anlegen_dialog(vorschlag, danach):
    """Eine Kategorie anlegen und danach weiterarbeiten.

    Der Bedarf entsteht mitten in der Zuordnung – etwa bei der Portalprovision,
    für die es keine Vorgabe gibt. Wer dafür die Bewegung verlassen muss,
    ordnet sie „irgendwie" zu oder gar nicht.
    """
    from app import buchhaltung, data
    from app.ui.basis import CFG
    with ui.dialog() as dlg, ui.card().classes("w-[440px] max-w-full gap-2"):
        ui.label("Neue Kategorie").classes("font-medium")
        ui.label("Dafür gibt es noch keine Kategorie. Sie erscheint danach "
                 "überall zur Auswahl und in der Auswertung als eigene Zeile.") \
            .classes(f"text-xs {ton.STILL}")
        feld = ui.input(value=vorschlag).props("dense outlined autofocus") \
            .classes("w-full").mark("neue-kategorie-feld")

        def anlegen():
            name = " ".join((feld.value or "").split())
            ok, meldung = buchhaltung.kategorie_anlegen(CFG, name)
            if not ok and meldung.endswith("gibt es schon."):
                ok = True                      # dann nehmen wir eben die da
            ui.notify(meldung, type="positive" if ok else "warning")
            if ok:
                data.save_config()
                dlg.close()
                danach(name)

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Abbrechen", on_click=dlg.close).props("flat no-caps dense")
            ui.button("Anlegen und zuordnen", on_click=anlegen) \
                .props("unelevated no-caps dense").mark("neue-kategorie-ok")
    dlg.open()


def _posten_kategorie(satz, neu_zeichnen):
    """Die Kategorie eines einzelnen Postens – änderbar (B6a).

    Bei einer Sammelzahlung trägt jeder Posten eine andere: 60 € Wäscherei,
    40 € Ausstattung. Vorher stand die Kategorie an der **Bewegung** und ließ
    sich nach dem Anlegen nicht mehr ändern – wer sich vertat, musste den
    Posten löschen und neu anlegen.
    """
    from app import buchhaltung
    from app.ui.basis import CFG

    def gesetzt(e):
        if zuordnung.kategorie_setzen(satz["id"], e.value or ""):
            ui.notify("Kategorie geändert.", type="positive", timeout=1500)
            neu_zeichnen()

    jetzige = (satz.get("kategorie") or "").strip()
    fehlt = not jetzige
    auswahl = {"": "— Kategorie —", **{x: x for x in buchhaltung.kategorien(CFG)}}
    if jetzige and jetzige not in auswahl:
        # Eine geloeschte oder umbenannte Kategorie steht noch am Posten. Ohne
        # diesen Eintrag lehnt die Auswahl den Wert ab und die ganze Maske
        # bricht ab – der Posten waere nicht mehr erreichbar.
        auswahl[jetzige] = f"{jetzige} (nicht mehr in der Liste)"
    ui.select(auswahl, value=jetzige, on_change=gesetzt) \
        .props("dense borderless options-dense") \
        .classes("text-xs w-full min-w-0 " + (ton.AUF_HINWEIS if fehlt else ton.STILL)) \
        .mark(f"pk-{satz['id']}")


def _neue_kategorie_knopf(auswahl, neu_zeichnen):
    """Das „+" neben der Kategorieauswahl (B6b).

    **Warum hier und nicht nur in den Einstellungen.** Der Bedarf entsteht in
    dem Moment, in dem eine Zahlung zugeordnet wird und nichts passt. Angelegt
    wird nur, was der Betrieb selbst benennt – die Vorgaben sind wörtlich die
    Kriterien des Workbooks, die Vorkontierung macht der Betrieb.
    """
    ui.button(icon="add",
              on_click=lambda: _kategorie_anlegen_dialog(
                  "", lambda name: (auswahl.set_value(name), neu_zeichnen()))) \
        .props("flat dense round").classes(f"{ton.ZART} shrink-0") \
        .tooltip("Neue Kategorie anlegen").mark("kategorie-neu")


def _provisionszeile(bewegung, rest, neu_zeichnen):
    """Den Rest einer Portal-Auszahlung als Provision gegenbuchen (B4).

    **Der Rest IST die Provision** – sobald alle zugehörigen Rechnungen
    zugeordnet sind. Statt ihn von Hand einzutippen, steht hier ein Knopf.

    **Maßgeblich ist der Beleg des Portals, nicht Smoobu.** Eine frühere Fassung
    rechnete den Rest gegen `commission-included` aus den Smoobu-Buchungen und
    meldete Abweichungen als Befund. Der Betreiber hat am 8.8.2026
    widersprochen: die Smoobu-Zahl stimmt nicht verlässlich, und das Steuerbüro
    bucht die **monatlichen Booking- und Airbnb-Belege** gegen die
    Auszahlungen. Eine Nachrechnung gegen eine unzuverlässige Zahl hätte
    Fehlalarme erzeugt – „es fehlt eine Rechnung", wo nur die Schätzung daneben
    lag. Geprüft wird deshalb gegen den Monatsbeleg (B5), nicht hier.
    """
    if not zuordnung.ziele(bewegung["id"], zuordnung.RECHNUNG) or rest >= 0:
        return
    from app import buchhaltung
    from app.ui.basis import CFG
    kategorien = [k for k in buchhaltung.kategorien(CFG) if "provision" in k.lower()]

    with ui.row().classes("w-full items-center gap-2 no-wrap mt-1"):
        ui.label("Was nicht ausgezahlt wurde, ist die Provision des Portals. "
                 "Der Monatsbeleg von Booking bzw. Airbnb wird später dagegen "
                 "gebucht.").classes(f"text-xs {ton.STILL} flex-grow min-w-0")

        def buchen():
            if not kategorien:
                # Fuer die Portalprovision gibt es keine Vorgabe – die
                # Kategorien sind woertlich die des Workbooks, und dort kommt
                # sie nicht vor. Statt sie zu erfinden oder mit leerer
                # Kategorie zu buchen (so entstand ein Posten ueber 790,27 EUR,
                # der in keiner Auswertung auftaucht): hier anlegen lassen.
                _kategorie_anlegen_dialog(
                    "Portalprovision (Booking/Airbnb)",
                    lambda name: _provision_buchen(bewegung, rest, name,
                                                   neu_zeichnen))
                return
            _provision_buchen(bewegung, rest, kategorien[0], neu_zeichnen)

        ui.button(f"Provision {_eur(rest)}", icon="percent", on_click=buchen) \
            .props("dense unelevated no-caps size=sm").classes("shrink-0") \
            .mark(f"prov-{bewegung['id']}")


def _rechnungsvorschlaege(bewegung, rest, neu_zeichnen):
    """Offene Rechnungen zum Abhaken – die wahrscheinlichste zuerst.

    **Kein automatisches Buchen.** Von 65 Zahlungseingängen entspricht genau
    einer exakt einem Rechnungsbetrag; die Portale zahlen netto nach Provision.
    Das Werkzeug sortiert vor und nennt den Grund, entschieden wird hier.

    Neben jeder Rechnung steht, was von ihr **ankommen müsste** – Betrag minus
    Provision aus Smoobu. Damit zählt der Rest beim Abhaken sauber herunter,
    und was am Ende übrig bleibt, ist die Provision.
    """
    from app import data, zahlungsvorschlag as vs
    from app.ui.basis import CFG

    # Die Smoobu-Buchungen liefern die Provision je Rechnung. Fehlt der Zugang,
    # geht es ohne – dann steht der volle Rechnungsbetrag daneben.
    # Eng gefasstes Fenster um den Zahltag: drei Jahre bei jedem Zeichnen waren
    # ein Abruf, den niemand braucht. Ein Aufenthalt liegt selten mehr als ein
    # halbes Jahr von seiner Zahlung entfernt.
    tag = (bewegung.get("datum") or "")[:10]
    buchungen = {}
    if tag:
        try:
            von = f"{int(tag[:4]) - 1}-07-01"
            bis = f"{int(tag[:4]) + 1}-06-30"
            for b in data._reservations(von, bis):
                buchungen[b.get("id")] = b
        except Exception:
            pass

    liste = vs.kandidaten(bewegung, CFG, buchungen)
    if not liste:
        return
    # KEIN zweites Aufklapp-Element. Vorher lagen die Vorschlaege in einer
    # verschachtelten Expansion – zugeklappt sah man nur eine Zeile, und wer die
    # Bewegung aufklappte, fand sie nicht (so gemeldet). Sie stehen jetzt
    # sichtbar da, sobald es welche gibt.
    with ui.column().classes("w-full gap-1 mt-1").mark(f"vs-{bewegung['id']}"):
        ui.label(f"Offene Rechnungen ({len(liste)}) – die wahrscheinlichste zuerst") \
            .classes(f"text-xs {ton.STILL}")
        for k in liste[:15]:
            r = k["rechnung"]
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(f"Nr. {r.get('nummer') or '—'}") \
                    .classes(f"text-xs {ton.STILL} w-16 shrink-0")
                with ui.column().classes("gap-0 min-w-0 flex-grow"):
                    ui.label(r.get("gast") or "—").classes("text-sm truncate")
                    # Der Kanal gehoert dazu: bei einer Booking-Auszahlung
                    # sind Airbnb-Rechnungen keine Kandidaten, und das sieht
                    # man der Zeile sonst nicht an.
                    b_ = buchungen.get(r.get("buchung")) or {}
                    kanal = (b_.get("channel") or {}).get("name", "")
                    ui.label(" · ".join(x for x in
                                        [_d(r.get('datum')), r.get('wohnung_name', ''),
                                         kanal, k['grund']] if x)) \
                        .classes(f"text-xs {ton.STILL} truncate")
                # Gebucht wird der RECHNUNGSBETRAG, nicht der Auszahlungsbetrag.
                # Sonst waere der Umsatz um die Provision zu niedrig und die
                # Provision taeuchte als Ausgabe nie auf – genau der Fehler, den
                # das Konzept benennt. Der Auszahlungsbetrag steht daneben,
                # damit man sieht, was davon ankommt.
                brutto = round((k["rechnung"].get("summen") or {}).get("brutto", 0), 2)
                ui.label(_eur(brutto)).classes("text-sm w-24 text-right shrink-0")

                def zuordnen(kk=k):
                    r_ = kk["rechnung"]
                    voll = round((r_.get("summen") or {}).get("brutto", 0), 2)
                    satz, meldung = zuordnung.hinzufuegen(
                        bewegung["id"], zuordnung.RECHNUNG, voll,
                        kategorie=bewegung.get("kategorie", ""), ziel_id=r_["id"],
                        notiz=f"Rechnung {r_.get('nummer') or ''}".strip())
                    if satz:
                        # Die Wohnung hinter der Portal-Kennung lernen – beim
                        # nächsten Auszug steht die richtige Liste schon oben.
                        gelernt = vs.kennung_lernen(CFG, vs.kennung(bewegung),
                                                    r_.get("wohnung"))
                        if gelernt:
                            data.save_config()
                    ui.notify(meldung, type="positive" if satz else "warning")
                    if satz:
                        neu_zeichnen()

                ui.button(icon="add", on_click=zuordnen) \
                    .props("flat dense round").tooltip("Dieser Zahlung zuordnen") \
                    .mark(f"vs-add-{r['id']}")
        if len(liste) > 15:
            ui.label(f"… und {len(liste) - 15} weitere offene Rechnungen") \
                .classes(f"text-xs {ton.STILL}")


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
                with ui.column().classes("gap-0 min-w-0 flex-grow"):
                    ui.label(_posten_text(satz)).classes("text-sm truncate")
                    # Die Kategorie gehoert an den POSTEN (B6): bei einer
                    # Sammelzahlung traegt jeder eine andere. Vorher liess sie
                    # sich nach dem Anlegen nicht mehr aendern.
                    _posten_kategorie(satz, neu_zeichnen)
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
                # Deckt der Posten die ganze Bewegung und haengt sonst nichts
                # dran, ist das dieselbe Entscheidung wie in der Zeile: merken
                # und die uebrigen Zahlungen desselben Empfaengers mitnehmen.
                # Vorher taten die beiden Wege Verschiedenes – wer die Maske
                # benutzte, tippte jede Wiederholung einzeln (so gemeldet am
                # 8.8.2026 an acht gleichen Targobank-Abbuchungen).
                if (not p and kat.value
                        and abs(wert - bewegung.get("betrag", 0.0)) < zuordnung.GENAU):
                    satz, weitere = konto.ganz_zuordnen(bewegung["id"], kat.value)
                    if satz and weitere:
                        _mitgezogen_zeigen(bewegung.get("gegenpartei") or "",
                                           kat.value, weitere, neu_zeichnen)
                    elif satz:
                        ui.notify(f"Zugeordnet ✓ – „{bewegung.get('gegenpartei') or ''}“ "
                                  "ist ab jetzt gemerkt.", type="positive", timeout=2500)
                    if satz:
                        neu_zeichnen()
                        return
                satz, meldung = zuordnung.hinzufuegen(
                    bewegung["id"], zuordnung.KATEGORIE, wert, kat.value or "")
                ui.notify(meldung, type="positive" if satz else "warning")
                if satz:
                    neu_zeichnen()

            _neue_kategorie_knopf(kat, neu_zeichnen)

            # Beschriftung nach Lage: der erste Posten ist eine Zuordnung,
            # jeder weitere teilt die Zahlung auf.
            ui.button("Zuordnen" if not p else "Aufteilen", icon="add",
                      on_click=anlegen) \
                .props("dense unelevated no-caps size=sm") \
                .tooltip("Diesen Betrag der gewählten Kategorie zuordnen") \
                .mark(f"zu-plus-{bewegung['id']}")

        # ---- Ausgangsrechnungen (B3) ----------------------------------------
        # Nur bei Eingängen, und nur solange etwas offen ist.
        if bewegung.get("betrag", 0) > 0 and abs(rest) > 0.005:
            _provisionszeile(bewegung, rest, neu_zeichnen)
            _rechnungsvorschlaege(bewegung, rest, neu_zeichnen)

        # ---- Der Restbetrag --------------------------------------------------
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            fertig = zuordnung.ist_fertig(bewegung)
            ui.label("Rest").classes("text-xs text-slate-400 flex-grow")
            ui.label(_eur(0 if fertig else rest)).classes(
                "text-sm font-medium w-28 text-right "
                + (ton.STILL if fertig else ton.AUF_HINWEIS)) \
                .mark(f"zu-rest-{bewegung['id']}")
            # Auch an Eingaengen: der Provisionsbeleg einer Plattform gehoert
            # an die Auszahlung, nicht an eine Ausgabe.
            _beleg_knopf(bewegung, neu_zeichnen)


def _offen_merken(bisher, bewegung_id, aufgeklappt):
    """Welche Zeile gilt nach diesem Klick als offen?

    Klingt trivial, ist es nicht: NiceGUI meldet beim Aufklappen einer Zeile
    **auch** das Zuklappen der vorigen – und zwar in beliebiger Reihenfolge.
    Wer beim Zuklappen bedingungslos leert, löscht damit die gerade geöffnete
    Zeile wieder, und alles klappt zu.
    """
    if aufgeklappt:
        return bewegung_id
    return "" if bisher == bewegung_id else bisher


def _filterzeile(zustand, neu_zeichnen):
    """Suchen, nach Kategorie und Zeitraum einengen (8.8.2026).

    **Bei 238 Bewegungen ist Suchen die halbe Arbeit.** Gesucht wird in allem,
    was auf dem Auszug steht – Empfänger, Verwendungszweck, Datum, Betrag;
    mehrere Wörter müssen alle vorkommen („weg 2026-07").

    Die Kategorienliste zeigt nur, was im Bestand **vorkommt**. Alle 31
    Vorgaben plus eigene wären länger als die Liste selbst, und die meisten
    Einträge führten ins Leere.
    """
    def setzen(**felder):
        zustand.update(**felder)
        neu_zeichnen()

    vergeben = konto.vergebene_kategorien()
    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
        ui.input(placeholder="Suchen: Empfänger, Zweck, Datum, Betrag",
                 value=zustand["suche"],
                 on_change=lambda e: setzen(suche=e.value or "")) \
            .props("dense outlined clearable").classes("w-[280px]") \
            .mark("konto-suche")
        ui.select({"": "Alle Kategorien", konto.OHNE_KATEGORIE: "— ohne Kategorie —",
                   **{k: k for k in vergeben}},
                  value=zustand["kategorie"],
                  on_change=lambda e: setzen(kategorie=e.value or "")) \
            .props("dense outlined options-dense").classes("w-[240px]") \
            .mark("konto-kategoriefilter")
        ui.input(label="von", value=zustand["von"],
                 on_change=lambda e: setzen(von=e.value or "")) \
            .props("type=date dense outlined").classes("w-[150px]").mark("konto-von")
        ui.input(label="bis", value=zustand["bis"],
                 on_change=lambda e: setzen(bis=e.value or "")) \
            .props("type=date dense outlined").classes("w-[150px]").mark("konto-bis")
        if any((zustand["suche"], zustand["kategorie"], zustand["von"], zustand["bis"])):
            ui.button("Filter zurücksetzen", icon="close",
                      on_click=lambda: setzen(suche="", kategorie="", von="", bis="")) \
                .props("flat dense no-caps size=sm").mark("konto-filter-weg")


def _gelerntes_knopf(neu_zeichnen):
    """„Gelerntes anwenden" – die Erkennung auf vorhandene Bewegungen (8.8.2026).

    **Warum es das braucht.** Die Erkennung lief nur beim Einlesen. Wer danach
    einen Empfänger zuordnet, half damit erst dem nächsten Auszug – an den
    echten Daten blieben nach der Zuordnung von „Valeriya Remez" fünf weitere
    Zahlungen an dieselbe Person offen.

    **Mit Vorschau.** Ein Knopf, der stillschweigend Dutzende Bewegungen
    umschreibt, ist nicht nachvollziehbar.
    """
    vorschau = konto.vorschau_gelernt()
    if not vorschau:
        return

    def anwenden(dlg):
        n = konto.gelerntes_anwenden(vorschau)
        dlg.close()
        ui.notify(f"{n} Bewegungen zugeordnet ✓", type="positive")
        neu_zeichnen()

    def oeffnen():
        with ui.dialog() as dlg, ui.card().classes("w-[640px] max-w-full gap-2"):
            ui.label("Gelerntes anwenden").classes("font-medium")
            ui.label("Diese Bewegungen gehören zu Empfängern, die schon einmal "
                     "zugeordnet wurden. Was bereits eine Kategorie trägt, "
                     "bleibt unangetastet.").classes(f"text-xs {ton.STILL}")
            with ui.scroll_area().classes("w-full h-[340px]"):
                for v in vorschau:
                    b = v["bewegung"]
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.label(_d(b.get("datum"))) \
                            .classes(f"text-xs w-20 shrink-0 {ton.STILL}")
                        ui.label(b.get("gegenpartei") or "—") \
                            .classes("text-xs flex-grow min-w-0 truncate")
                        ui.label(_eur(b.get("betrag", 0))) \
                            .classes("text-xs w-24 text-right shrink-0")
                        ui.label(v["kategorie"]).classes("text-xs w-1/3 truncate")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Abbrechen", on_click=dlg.close).props("flat no-caps")
                ui.button(f"{len(vorschau)} Bewegungen zuordnen",
                          on_click=lambda: anwenden(dlg)) \
                    .props("unelevated no-caps").mark("gelernt-ok")
        dlg.open()

    with ui.row().classes("w-full items-center gap-2"):
        ui.icon("auto_awesome").classes(f"text-sm {ton.AUF_HINWEIS}")
        ui.label(f"{len(vorschau)} Bewegungen gehören zu Empfängern, die Sie "
                 "schon zugeordnet haben.").classes(f"text-xs {ton.AUF_HINWEIS}")
        ui.button("Ansehen und übernehmen", on_click=oeffnen) \
            .props("flat dense no-caps size=sm").mark("gelernt-open")


def _monatsprobe(schluessel):
    """Je Monat: gebuchte Provision gegen den Monatsbeleg des Portals (B4b/B5b).

    **Die Prüfung, die vorher fälschlich gegen Smoobu lief.** Booking und
    Airbnb schicken monatlich einen Provisionsbeleg; seit B5 hängt er an den
    Provisions-Posten. Deckt seine Summe die gebuchten Posten nicht, fehlt eine
    Auszahlung des Monats – oder an einer davon die Rechnung.

    Ohne Beleg steht hier nur die gebuchte Summe. Ein Monat, dessen Beleg noch
    nicht da ist, ist kein Fehler, sondern unfertig.
    """
    monate = verrechnung.monatsuebersicht(schluessel)
    if not monate:
        return
    with ui.element("div").classes(
            "w-full grid grid-cols-[auto_auto_auto_1fr] gap-x-4 mb-2"):
        for kopf in ("Monat", "gebucht", "Monatsbeleg", ""):
            ui.label(kopf).classes(f"text-xs {ton.ZART} "
                                   + ("" if kopf == "Monat" else "text-right"))
        for m in monate:
            ui.label(m["monat"]).classes("text-xs")
            ui.label(_eur(m["provision"])).classes("text-xs text-right")
            ui.label("—" if m["beleg"] is None else _eur(m["beleg"])) \
                .classes(f"text-xs text-right {ton.STILL if m['beleg'] is None else ''}")
            if m["stimmt"] is None:
                ui.label("Beleg des Portals noch nicht zugeordnet") \
                    .classes(f"text-xs {ton.STILL} pl-2")
            elif m["stimmt"]:
                ui.label("stimmt überein").classes(f"text-xs {ton.ERFOLG} pl-2")
            else:
                ui.label(f"{_eur(round(m['beleg'] - m['provision'], 2))} nicht "
                         "gebucht – eine Auszahlung des Monats fehlt") \
                    .classes(f"text-xs {ton.AUF_HINWEIS} pl-2")


def _verrechnungskonten():
    """Je Plattform ein Kontoblatt – Rechnungen rein, Provision und Auszahlung raus.

    Das führt das Steuerbüro genauso. Der Sinn steht in der einen Zahl rechts:
    solange der Saldo nicht null ist, fehlt zwischen Rechnung und Geldeingang
    noch etwas. Die Zeilen darunter zeigen, wo.
    """
    konten = verrechnung.uebersicht()
    if not konten:
        return
    with ui.card().classes("w-full").mark("verrechnungskonten"):
        ui.label("Verrechnungskonten").classes("font-medium")
        ui.label("Booking und Airbnb ziehen beim Gast ein und zahlen gesammelt "
                 "netto aus. Geht ein Konto auf, ist der Saldo null.") \
            .classes(f"text-xs {ton.STILL}")
        for k in konten:
            stimmt = abs(k["saldo"]) < 0.005
            with ui.expansion().classes("w-full").props("dense") \
                    .mark(f"vk-{k['schluessel']}") as auf:
                with auf.add_slot("header"):
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.label(k["name"]).classes("text-sm font-medium")
                        ui.space()
                        for kopf, wert in (("Rechnungen", k["rechnungen"]),
                                           ("Provision", k["provision"]),
                                           ("Auszahlung", k["auszahlung"])):
                            with ui.column().classes("gap-0 items-end shrink-0"):
                                ui.label(kopf).classes(f"text-xs {ton.ZART}")
                                ui.label(_eur(wert)).classes("text-xs")
                        with ui.column().classes("gap-0 items-end w-28 shrink-0"):
                            ui.label("Saldo").classes(f"text-xs {ton.ZART}")
                            ui.label(_eur(k["saldo"])).classes(
                                "text-sm font-medium "
                                + (ton.ERFOLG if stimmt else ton.AUF_HINWEIS))
                if not stimmt:
                    # Ohne diesen Satz liest man die Zahl als Forderung. Sie ist
                    # aber meist eine Lücke in der Erfassung – und das ist eine
                    # andere Aufgabe als eine Mahnung.
                    ui.label("Der Saldo ist nicht null: entweder ist eine "
                             "Auszahlung noch keiner Rechnung zugeordnet, oder "
                             "der Provisionsbeleg der Plattform fehlt noch.") \
                        .classes(f"text-xs mb-1 {ton.AUF_HINWEIS}")
                _monatsprobe(k["schluessel"])
                lauf = 0.0
                with ui.element("div").classes(
                        "w-full grid grid-cols-[auto_1fr_auto_auto] gap-x-4"):
                    for kopf in ("Datum", "Vorgang", "Betrag", "Saldo"):
                        ui.label(kopf).classes(f"text-xs {ton.ZART} "
                                               + ("" if kopf in ("Datum", "Vorgang")
                                                  else "text-right"))
                    for z in k["zeilen"]:
                        lauf = round(lauf + z["betrag"], 2)
                        ui.label(_d(z["datum"])).classes(f"text-xs {ton.ZART}")
                        ui.label(z["text"]).classes("text-xs truncate")
                        ui.label(_eur(z["betrag"])).classes("text-xs text-right")
                        ui.label(_eur(lauf)).classes(f"text-xs text-right {ton.STILL}")


def render_konto():
    ui.label("Konto").classes("text-xl font-bold")
    ui.label("Kontoauszüge einlesen – Geschäftskonto und Kreditkarte. "
             "Grundlage für den Überblick und für die Übergabe ans Steuerbüro.") \
        .classes("text-sm text-slate-500 mb-2")

    inhalt = ui.column().classes("w-full gap-3")
    # Welche Sicht auf die Bewegungen gerade gilt. Ueberlebt das Neuzeichnen –
    # sonst springt die Liste nach jedem Posten auf „Alle" zurueck.
    # Ueberlebt das Neuzeichnen. `offen_id` ist die Zeile, an der gerade
    # gearbeitet wird: sie bleibt aufgeklappt und im Filter stehen, damit man
    # das Ergebnis der Zuordnung sieht (so gemeldet am 8.8.2026).
    zustand = {"sicht": "alle", "suche": "", "kategorie": "", "von": "", "bis": "",
               "offen_id": ""}

    async def _ein_auszug(datei):
        """Einen Auszug einlesen. Gibt (bericht, fehlertext) zurück."""
        try:
            rohdaten = await datei.read()
        except Exception as fehler:
            return None, f"Datei nicht lesbar: {fehler}"
        try:
            return konto.importieren(rohdaten), None
        except ValueError as fehler:                # unbekanntes Format
            return None, str(fehler)
        except Exception as fehler:
            return None, f"Auszug konnte nicht gelesen werden: {fehler}"

    async def auszuege_laden(e):
        """Mehrere Auszüge auf einmal – Girokonto und Karte gehören zusammen.

        Die Kreditkartenabrechnung steht auf dem Girokonto als **eine**
        Sammelbuchung; die Einzelkäufe stehen im Kartenauszug. Beide in einem
        Zug einzulesen ist der Normalfall, nicht die Ausnahme – vorher ging nur
        eine Datei je Auswahl.

        **Ein Fehler stoppt den Stapel nicht.** Sonst verhinderte eine falsche
        Datei alles Nachfolgende, und man wüsste nicht, was angekommen ist.
        """
        berichte, fehler = [], []
        for datei in list(getattr(e, "files", None) or [e.file]):
            bericht, problem = await _ein_auszug(datei)
            (fehler if problem else berichte).append(problem or bericht)
        for b in berichte:
            teile = [f"{b['neu']} neu"]
            if b["doppelt"]:
                teile.append(f"{b['doppelt']} schon vorhanden")
            if b["umbuchungen"]:
                teile.append(f"{b['umbuchungen']} Umbuchungen")
            von, bis = b.get("zeitraum") or ("", "")
            if von and bis:
                teile.append(f"{_d(von)}–{_d(bis)}")
            ui.notify(f"{b['konto']}: " + " · ".join(teile), type="positive",
                      timeout=6000)
        for problem in fehler[:3]:
            ui.notify(problem, type="warning", timeout=9000)
        zeichnen()

    with ui.row().classes("w-full items-center gap-3"):
        ui.upload(auto_upload=True, multiple=True, max_files=12,
                  on_upload=None, on_multi_upload=auszuege_laden,
                  label="Auszüge (CSV) wählen") \
            .props('accept=".csv,text/csv"').classes("hk-upload w-[240px]") \
            .mark("konto-upload")
        ui.label("DKB-Business und DKB-VISA, als CSV exportiert – beide "
                 "zusammen auswählbar. Das Format wird an der Spaltenzeile "
                 "erkannt.").classes("text-xs text-slate-400")

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

            _verrechnungskonten()

            # ---- Die Bewegungen -------------------------------------------
            # EINE Liste, drei Sichten. Vorher stand daneben eine zweite Karte
            # „Fehlende Belege" mit denselben Zeilen – zwei Listen, die dasselbe
            # zeigen, verwirren mehr als sie helfen (so gemeldet am 8.8.2026).
            fehlen_ids = {x["id"] for x in konto.ohne_beleg()}
            offen_ids = {x["id"] for x in offen}
            auto_ids = {x["id"] for x in konto.automatisch()}
            with ui.card().classes("w-full").mark("konto-liste"):
                _gelerntes_knopf(zeichnen)
                _filterzeile(zustand, zeichnen)
                with ui.row().classes("w-full items-center gap-2"):
                    ui.label("Bewegungen").classes("font-medium")
                    ui.space()
                    ui.toggle({"alle": f"Alle ({len(bewegungen)})",
                               "offen": f"Nicht zugeordnet ({len(offen_ids)})",
                               "auto": f"Automatisch erkannt ({len(auto_ids)})",
                               "beleg": f"Beleg fehlt ({len(fehlen_ids)})"},
                              value=zustand["sicht"],
                              on_change=lambda e: (zustand.update(sicht=e.value),
                                                   zeichnen())) \
                        .props("dense no-caps unelevated size=sm").mark("konto-sicht")
                bewegungen = konto.filtern(
                    bewegungen, zustand["suche"], zustand["kategorie"],
                    zustand["von"], zustand["bis"], behalten=zustand["offen_id"])
                if zustand["sicht"] == "offen":
                    bewegungen = [b for b in bewegungen if b["id"] in offen_ids]
                    ui.label("Ausgänge ohne Kategorie. Erst zuordnen – vorher "
                             "steht nicht fest, ob es dazu überhaupt einen Beleg "
                             "gibt.").classes(f"text-xs {ton.STILL}")
                elif zustand["sicht"] == "auto":
                    bewegungen = [b for b in bewegungen if b["id"] in auto_ids]
                    ui.label("Diese Kategorien hat das Werkzeug selbst gesetzt – "
                             "über den Empfänger, ohne zu fragen. Meistens "
                             "stimmen sie; durchsehen sollte man sie trotzdem "
                             "einmal. Eine Kategorie auswählen bestätigt sie, "
                             "auch dieselbe.").classes(f"text-xs {ton.STILL}")
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
                    fertig = konto.ist_erledigt(b)
                    zeile = ui.expansion(value=b["id"] == zustand["offen_id"]) \
                        .classes("w-full").props("dense") \
                        .mark(f"bew-{b['id']}")
                    # Merken, welche Zeile offen ist – sonst klappt sie beim
                    # naechsten Neuzeichnen zu und der Vorgang verschwindet.
                    zeile.on_value_change(
                        lambda e, i=b["id"]: zustand.update(
                            offen_id=_offen_merken(zustand["offen_id"], i, e.value)))
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
                            # Ein Klick statt Aufklappen – nur beim einfachen
                            # Fall, siehe `_kategorie_wahl`.
                            _kategorie_wahl(b, zeichnen)
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
                            with ui.row().classes("w-full items-center gap-2"):
                                # Zuzuordnen gibt es nichts – zu dokumentieren
                                # schon: die Kreditkartenabrechnung gehoert an
                                # ihre Sammelbuchung, damit das Steuerbuero sie
                                # dort findet. An den Zahlen aendert das nichts.
                                ui.label("Umbuchung zwischen eigenen Konten – "
                                         "zählt in keiner Auswertung mit. Ein "
                                         "Dokument dazu (z. B. die "
                                         "Kreditkartenabrechnung) kann trotzdem "
                                         "hier hängen.") \
                                    .classes("text-xs text-slate-400 flex-grow")
                                _beleg_knopf(b, zeichnen)
                        else:
                            _zuordnungsmaske(b, zeichnen)
                if len(bewegungen) > 200:
                    ui.label(f"… und {len(bewegungen) - 200} weitere") \
                        .classes("text-xs text-slate-400 mt-1")

    zeichnen()
