"""Bereich „Konto": Auszüge einlesen und Bewegungen ansehen (AP16).

Der erste Schritt der Buchhaltungskette. Zugeordnet wird hier noch nichts – das
kommt mit AP20; hier geht es darum, die Bewegungen überhaupt im Werkzeug zu
haben und zu sehen, was Monat für Monat rein- und rausgeht.

**Die Rückmeldung nach dem Einlesen nennt bewusst auch die Dubletten.** Bei
überlappenden Auszügen ist es der Normalfall, dass aus 169 Zeilen 12 neue Sätze
werden. Ohne die Zahl daneben sieht das nach einem Fehler aus.
"""
from nicegui import ui

from app import konto, kontoauszug
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


def render_konto():
    ui.label("Konto").classes("text-xl font-bold")
    ui.label("Kontoauszüge einlesen – Geschäftskonto und Kreditkarte. "
             "Grundlage für den Überblick und für die Übergabe ans Steuerbüro.") \
        .classes("text-sm text-slate-500 mb-2")

    inhalt = ui.column().classes("w-full gap-3")

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

            # ---- Die Bewegungen selbst --------------------------------------
            with ui.card().classes("w-full").mark("konto-liste"):
                ui.label("Bewegungen").classes("font-medium")
                for b in bewegungen[:200]:
                    with ui.row().classes("w-full items-start gap-2 no-wrap py-1 "
                                          "border-b border-slate-100"):
                        ui.label(_d(b["datum"])).classes("text-xs text-slate-400 w-20 shrink-0")
                        with ui.column().classes("gap-0 min-w-0 flex-grow"):
                            ui.label(b.get("gegenpartei") or "—") \
                                .classes("text-sm truncate")
                            if b.get("text") and b["text"] != b.get("gegenpartei"):
                                ui.label(b["text"]).classes("text-xs text-slate-400 truncate")
                        if b.get("umbuchung"):
                            ui.label("Umbuchung").classes("text-xs text-slate-400 shrink-0")
                        elif b["betrag"] < 0:
                            _kategorie_wahl(b)
                        ui.label(_eur(b["betrag"])).classes(
                            "text-sm text-right w-28 shrink-0 "
                            + ("" if b["betrag"] > 0 else "text-slate-600"))
                if len(bewegungen) > 200:
                    ui.label(f"… und {len(bewegungen) - 200} weitere") \
                        .classes("text-xs text-slate-400 mt-1")

    zeichnen()
