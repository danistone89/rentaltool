#!/usr/bin/env python3
"""Die Rechnung als PDF – ein Standardlayout, das man vorzeigen kann.

Gebaut mit PyMuPDF, ohne Vorlage: eine Rechnung ist kein amtliches Formular mit
festen Feldpositionen (das ist die Steueranmeldung, siehe `app/pdf_form.py`),
sondern eine Seite, die man setzt.

**Was drauf muss, steht im Gesetz** (§ 14 Abs. 4 UStG): vollständiger Name und
Anschrift beider Seiten, Steuernummer oder USt-IdNr., Ausstellungsdatum, eine
fortlaufende Nummer, Art und Umfang der Leistung, der Zeitpunkt der Leistung,
das Entgelt nach Steuersätzen aufgeschlüsselt sowie Steuersatz und Steuerbetrag.
Fehlt davon etwas, ist der Beleg unvollständig – und der Gast, der ihn
einreichen will, steht damit schlechter da als ohne.

**Der Aufbau folgt der abgestimmten Vorlage** (Beispielrechnung B2B): Titel und
Eckdaten, Empfänger, ein Block „Aufenthalt / Gast / Zeitraum", die Aufstellung
mit Netto/USt./Brutto, die Zwischensumme der Beherbergungsleistungen, die
Beherbergungssteuer, der Gesamtbetrag, die Steuerinformation, der Hinweis und
eine Fußzeile aus drei Spalten. Übernommen ist die **Reihenfolge**, nicht die
Gestaltung – gesetzt wird zurückhaltend wie im Rest des Werkzeugs: Haarlinien
statt farbiger Flächen, die Hausfarbe nur für Titel und Gesamtbetrag.

**Geschrieben wird mit `fitz.TextWriter`, nicht mit `insert_text`.** Letzteres
kodiert nach Latin-1; „€" und „–" wurden dort still zu einem Punkt, weshalb auf
der Rechnung früher „EUR" stand. Der TextWriter bettet die Schrift ein und
schreibt beide Zeichen richtig. Was Helvetica gar nicht kennt, fängt
`_darstellbar()` ab – ein fehlendes Glyph würde sonst den Aufbau abbrechen.

**Die Beherbergungssteuer steht getrennt und ohne Umsatzsteuer.** Sie ist ein
durchlaufender Posten: die Stadt bekommt sie, nicht der Vermieter. Sie in die
Bemessungsgrundlage zu ziehen hieße, Steuer auf Steuer zu erheben. In der
USt-Spalte steht deshalb „nicht steuerbar" – und NICHT „steuerfrei": das wäre
ein Umsatz nach § 4 UStG und gehörte in die Voranmeldung.
"""
MM = 72 / 25.4          # Millimeter in PDF-Punkte

# ---- Maße nach DIN 5008 Form A ---------------------------------------------
# DIN 5008 ist die Norm für Geschäftsbriefe; ISO 269 regelt nur die Fenster-
# formate der Umschläge. Maßgeblich für uns ist das **Anschriftfeld**: es
# beginnt 27 mm unter der Blattkante und teilt sich in die Zusatz- und
# Vermerkzone (27,0–44,7 mm, dort steht die kleine Rücksendeangabe) und die
# **Anschriftzone ab 44,7 mm**, in der die Empfängeranschrift stehen MUSS –
# sonst sitzt sie im Fenster eines DIN-Umschlags nicht richtig.
#
# Nachgemessen an der Vorlage (Rechnung_Entwurf_Peter_Queißer-2): dort stand
# die Rücksendeangabe auf 44,7 mm und die erste Anschriftzeile auf 50,7 mm –
# beides sechs Millimeter zu tief. Korrigiert.
RAND = 24.1 * MM        # linker Schreibbereich (DIN 5008)
RAND_RECHTS = 20.0 * MM
ANSCHRIFT_ZONE = 44.7 * MM      # ab hier gehört das Feld dem Empfänger
RUECKSENDUNG = 42.5 * MM        # kleine Absenderzeile, noch in der Zusatzzone
ANSCHRIFT_ZEILE = 4.23 * MM     # Zeilenabstand im Anschriftfeld
BETREFF = 80.4 * MM             # zwei Leerzeilen unter dem Anschriftfeld
OBEN = 20 * MM

# Logo oben links: die Zusatzzone darüber gehört dem Briefkopf.
LOGO_MAX_B = 46 * MM
LOGO_MAX_H = 20 * MM

PURPLE = (0.369, 0.165, 0.518)      # #5E2A84
GRAU = (0.42, 0.40, 0.45)
HELLGRAU = (0.75, 0.74, 0.77)
SCHWARZ = (0.14, 0.11, 0.18)
ROT = (0.63, 0.23, 0.18)
WEISS = (1, 1, 1)
KASTEN = (247 / 255, 245 / 255, 248 / 255)      # Hinterlegung der Zwischensumme

_FONTS = {}


def _font(fett=False):
    import fitz
    name = "hebo" if fett else "helv"
    if name not in _FONTS:
        _FONTS[name] = fitz.Font(name)
    return _FONTS[name]


def _eur(betrag, zeichen=True):
    s = f"{abs(betrag):,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return ("-" if betrag < 0 else "") + s + (" €" if zeichen else "")


def _d(iso):
    try:
        j, m, t = str(iso)[:10].split("-")
        return f"{t}.{m}.{j}"
    except ValueError:
        return str(iso or "")


def _darstellbar(text, fett=False):
    """Zeichen entfernen, die Helvetica nicht kennt. Ein fehlendes Glyph würde
    den TextWriter abbrechen lassen – ein Gastname in kyrillischer Schrift darf
    aber keine Rechnung verhindern."""
    f = _font(fett)
    return "".join(c for c in str(text) if c in "\n\t " or f.has_glyph(ord(c)))


def _in_lesereihenfolge(posten, zeilentoleranz=3.0):
    """Zeile für Zeile, darin von links nach rechts.

    Nicht einfach nach y sortieren: „nicht steuerbar" steht 0,4 pt höher als
    der Betrag daneben, damit die kleinere Schrift optisch auf der Zeile sitzt.
    Nach reinem y sortiert stünde es im Textstrom vor seiner eigenen Zeile.
    Alles, was weniger als `zeilentoleranz` auseinanderliegt, gilt als eine
    Zeile.
    """
    reihen = []
    for eintrag in sorted(posten, key=lambda p: p[1]):
        if reihen and abs(eintrag[1] - reihen[-1][0]) < zeilentoleranz:
            reihen[-1][1].append(eintrag)
        else:
            reihen.append((eintrag[1], [eintrag]))
    for _y, zeile in reihen:
        for eintrag in sorted(zeile, key=lambda p: p[0]):
            yield eintrag


class _Setzer:
    """Sammelt Text und Linien und schreibt sie am Ende aufs Blatt.

    Gesammelt wird, weil ein `TextWriter` nur EINE Farbe je Durchgang kann –
    am Ende wird je Farbe und Schnitt einmal geschrieben statt je Zeile.
    """

    def __init__(self, seite):
        self.seite = seite
        self.posten = []

    def text(self, x, y, text, groesse=9.5, fett=False, farbe=SCHWARZ, rechts=None):
        """Eine Textzeile. `rechts` setzt sie rechtsbündig auf diese x-Position."""
        text = _darstellbar(text, fett)
        if not text.strip():
            return
        if rechts is not None:
            x = rechts - _font(fett).text_length(text, groesse)
        self.posten.append((x, y, text, groesse, fett, farbe))

    def breite(self, text, groesse, fett=False):
        return _font(fett).text_length(_darstellbar(text, fett), groesse)

    def linie(self, y, x0, x1, farbe=HELLGRAU, staerke=0.4):
        import fitz
        self.seite.draw_line(fitz.Point(x0, y), fitz.Point(x1, y),
                             color=farbe, width=staerke)

    def kasten(self, x0, y0, x1, y1, farbe, radius=0.12):
        """Eine gefüllte Fläche. Wird sofort gezeichnet, der Text kommt am Ende
        obenauf – sonst läge die Fläche über der Schrift."""
        import fitz
        self.seite.draw_rect(fitz.Rect(x0, y0, x1, y1), color=farbe, fill=farbe,
                             radius=radius)

    def fertig(self):
        """Alles ausgeben – in Lesereihenfolge.

        Sortiert wird nach Zeile und Spalte, bevor geschrieben wird: die
        Reihenfolge im PDF ist die, in der ein Auslesen den Text bekommt
        (Kopieren, Vorlesen, Prüfsoftware). Würde nur nach Farbe gruppiert,
        stünde der Gesamtbetrag im Textstrom vor der Aufstellung.

        Innerhalb der Sortierung werden gleichfarbige Nachbarn zusammengefasst,
        weil ein `TextWriter` nur EINE Farbe je Durchgang kann.
        """
        import fitz
        lauf, farbe_aktuell, fett_aktuell = [], None, None

        def schreiben():
            if not lauf:
                return
            tw = fitz.TextWriter(self.seite.rect)
            f = _font(fett_aktuell)
            for x, y, text, groesse in lauf:
                tw.append((x, y), text, font=f, fontsize=groesse)
            tw.write_text(self.seite, color=farbe_aktuell)

        for x, y, text, groesse, fett, farbe in _in_lesereihenfolge(self.posten):
            if (fett, farbe) != (fett_aktuell, farbe_aktuell):
                schreiben()
                lauf, fett_aktuell, farbe_aktuell = [], fett, farbe
            lauf.append((x, y, text, groesse))
        schreiben()


def _je_steuersatz(leistungen):
    """Die eigenen Leistungen nach Steuersätzen zusammengefasst.

    Heute steht auf jeder Rechnung nur ein Satz (7 %). Frühstück, Parkplatz oder
    Haustier wären 19 % – deshalb wird über die tatsächlich vorkommenden Sätze
    gruppiert und nicht einer angenommen.
    """
    je_satz = {}
    for p in leistungen:
        satz = p.get("ustsatz", 0)
        eintrag = je_satz.setdefault(satz, {"netto": 0.0, "ust": 0.0, "brutto": 0.0})
        for feld in ("netto", "ust", "brutto"):
            eintrag[feld] += p.get(feld, 0)
    return {satz: {k: round(v, 2) for k, v in w.items()} for satz, w in je_satz.items()}


# Auf dem Blatt ausführlicher als in den Daten: „Übernachtung" allein sagt dem
# Gast nicht, wofür er zahlt, und die Beherbergungssteuer gibt es nur, weil
# Dresden sie erhebt. Die gespeicherten Bezeichnungen bleiben unangetastet – an
# ihnen hängen Produktpreise, Auswertungen und die festgeschriebenen Rechnungen.
_ANZEIGENAME = {"Übernachtung": "Übernachtung / Beherbergung",
                "Beherbergungssteuer": "Beherbergungssteuer Dresden"}


def _absenderzeile(betr):
    teile = [betr.get("name", ""), betr.get("zusatz", ""),
             f"{betr.get('strasse', '')} {betr.get('hausnummer', '')}".strip(),
             f"{betr.get('plz', '')} {betr.get('ort', '')}".strip()]
    return " · ".join(t for t in teile if t)


def _logo(seite, betreiber):
    """Das Logo oben links, eingepasst und seitenrichtig.

    Ein fehlendes oder kaputtes Bild darf keine Rechnung verhindern – dann
    bleibt die Ecke eben leer.
    """
    import fitz
    pfad = _logo_pfad(betreiber)
    if not pfad:
        return
    try:
        seite.insert_image(fitz.Rect(RAND, 54.0, RAND + LOGO_MAX_B, 54.0 + LOGO_MAX_H),
                           filename=pfad, keep_proportion=True)
    except Exception:
        pass


def _logo_pfad(betreiber):
    """Absoluter Pfad zum Logo oder ''.

    Gespeichert wird der Name relativ zum Medienordner (wie bei den Fotos) –
    so nimmt ein Umzug des Datenordners das Logo mit, und dieselbe Angabe
    zeigt es in der Oberfläche unter `/media/<name>`.
    """
    rel = (betreiber.get("logo") or "").strip()
    if not rel:
        return ""
    import os
    if os.path.isabs(rel):
        return rel if os.path.isfile(rel) else ""
    try:
        from app import paths
        voll = paths.p("media", rel)
    except Exception:
        return ""
    return voll if os.path.isfile(voll) else ""


def _briefkopf(s, seite, betreiber, rechts):
    """Logo links, Anbieterdaten rechts – beides über dem Anschriftfeld."""
    _logo(seite, betreiber)
    zeilen = [betreiber.get("name", ""), betreiber.get("zusatz", ""),
              f"{betreiber.get('strasse', '')} {betreiber.get('hausnummer', '')}".strip(),
              f"{betreiber.get('plz', '')} {betreiber.get('ort', '')}".strip(),
              betreiber.get("telefon", ""), betreiber.get("email", "")]
    y = 59.3
    for i, zeile in enumerate([z for z in zeilen if z.strip()]):
        s.text(0, y, zeile, 8.5, fett=(i == 0), farbe=SCHWARZ if i == 0 else GRAU,
               rechts=rechts)
        y += 11


def _anschriftfeld(s, r, betreiber):
    """Rücksendeangabe und Empfänger – im Anschriftfeld nach DIN 5008 Form A."""
    s.text(RAND, RUECKSENDUNG, _absenderzeile(betreiber), 6.5, farbe=GRAU)
    s.linie(RUECKSENDUNG + 3, RAND, RAND + 85 * MM)
    e = r.get("empfaenger") or {}
    # Erste Grundlinie so tief, dass die OBERKANTE der Schrift in der Zone
    # liegt – nicht die Grundlinie. Sonst ragt die erste Zeile über 44,7 mm
    # hinaus und sitzt im Umschlagfenster zu hoch.
    y = ANSCHRIFT_ZONE + _font().ascender * 10 + 0.5
    for zeile in [e.get("name", ""), e.get("strasse", ""),
                  f"{e.get('plz', '')} {e.get('ort', '')}".strip(),
                  e.get("land", "") if (e.get("land") or "").upper() not in ("", "DE") else ""]:
        if zeile.strip():
            s.text(RAND, y, zeile, 10)
            y += ANSCHRIFT_ZEILE


def _titel(s, r, rechts, storniert):
    """Überschrift auf der Betreffzeile, Nummer und Datum daneben.
    Gibt die Höhe zurück, auf der es weitergeht."""
    s.text(RAND, BETREFF, "Stornorechnung" if storniert else "Rechnung", 17,
           fett=True, farbe=PURPLE)
    untertitel = " · ".join(x for x in ["Beherbergung", r.get("wohnung_name", "")] if x)
    s.text(RAND, BETREFF + 15, untertitel, 9, farbe=GRAU)
    nummer = r.get("nummer") or "Entwurf – noch keine Nummer"
    s.text(0, BETREFF - 2, f"Nr. {nummer}", 10, fett=True, rechts=rechts)
    s.text(0, BETREFF + 15.5, f"Datum {_d(r.get('datum'))}", 9, farbe=GRAU, rechts=rechts)
    return BETREFF + 40


def _aufenthalt(s, r, y, rechts):
    """Worum es geht, für wen, wann – drei Spalten zwischen zwei Haarlinien."""
    s.linie(y, RAND, rechts)
    y += 14
    zeitraum = f"{_d(r.get('anreise'))} – {_d(r.get('abreise'))}"
    spalten = [(RAND, None, "Aufenthalt", r.get("wohnung_name", ""), True),
               (RAND + 88 * MM, None, "Gast", r.get("gast", ""), False),
               (None, rechts, "Zeitraum", zeitraum, False)]
    for x, rx, bez, wert, fett in spalten:
        if not (wert or "").strip():
            continue
        s.text(x or 0, y, bez, 8, farbe=GRAU, rechts=rx)
        s.text(x or 0, y + 14, wert, 9.5, fett=fett, rechts=rx)
    y += 24
    s.linie(y, RAND, rechts)
    return y + 22


def _fusszeile(s, betreiber, rechts, hoehe):
    """Drei Spalten unten: wer, Steuerdaten, Bankverbindung."""
    fuss = hoehe - 20 * MM
    s.linie(fuss - 12, RAND, rechts)
    spalten = [
        (RAND, None, betreiber.get("name", ""), [
            f"{betreiber.get('strasse', '')} {betreiber.get('hausnummer', '')}".strip(),
            f"{betreiber.get('plz', '')} {betreiber.get('ort', '')}".strip(),
            " · ".join(x for x in [betreiber.get("telefon", ""),
                                   betreiber.get("email", "")] if x)]),
        (RAND + 62 * MM, None, "Steuerdaten", [
            f"Steuernummer {betreiber['steuernummer']}" if betreiber.get("steuernummer") else "",
            f"USt-IdNr. {betreiber['ust_id']}" if betreiber.get("ust_id") else ""]),
        (None, rechts, "Bankverbindung", [
            betreiber.get("bank", ""),
            f"IBAN {betreiber['iban']}" if betreiber.get("iban") else "",
            f"BIC {betreiber['bic']}" if betreiber.get("bic") else ""]),
    ]
    for x, rx, kopf, zeilen in spalten:
        s.text(x or 0, fuss, kopf, 7, fett=True, farbe=GRAU, rechts=rx)
        yy = fuss + 9.5
        for zeile in [z for z in zeilen if z.strip()]:
            s.text(x or 0, yy, zeile, 7, farbe=GRAU, rechts=rx)
            yy += 9.5


def bauen(r, betreiber, hinweis=""):
    """Eine Rechnung als PDF-Bytes.

    `r` ist der Datensatz aus `app/rechnung.py`, `betreiber` die Betreiberdaten
    aus der Konfiguration.
    """
    import fitz
    doc = fitz.open()
    seite = doc.new_page()                      # A4
    rechts = seite.rect.width - RAND_RECHTS
    s = _Setzer(seite)
    storniert = r.get("status") == "storniert"

    _briefkopf(s, seite, betreiber, rechts)
    _anschriftfeld(s, r, betreiber)
    y = _titel(s, r, rechts, storniert)
    y = _aufenthalt(s, r, y, rechts)

    # ---- Aufstellung ------------------------------------------------------
    # Netto, Steuersatz und Brutto je Zeile: § 14 Abs. 4 Nr. 8 UStG verlangt das
    # Entgelt nach Steuersätzen aufgeschlüsselt, und die Buchhaltung liest die
    # Netto-Spalte zuerst. Der Gast findet seinen Betrag rechts, fett gesetzt.
    sp_netto, sp_ust, sp_brutto = rechts - 185, rechts - 105, rechts
    s.linie(y - 9, RAND, rechts, farbe=SCHWARZ, staerke=0.8)
    s.text(RAND, y, "Leistung", 8, fett=True, farbe=GRAU)
    s.text(0, y, "Netto", 8, fett=True, farbe=GRAU, rechts=sp_netto)
    s.text(0, y, "USt.", 8, fett=True, farbe=GRAU, rechts=sp_ust)
    s.text(0, y, "Brutto", 8, fett=True, farbe=GRAU, rechts=sp_brutto)
    s.linie(y + 6, RAND, rechts)
    y += 22

    positionen = r.get("positionen", [])
    leistungen = [p for p in positionen if p.get("ustsatz")]
    durchlaufende = [p for p in positionen if not p.get("ustsatz")]
    summen = r.get("summen") or {}
    # Aus Netto und USt gebildet, nicht aus einem eigenen Feld: so stimmt die
    # Zeile auch für Rechnungen, die vor dieser Änderung entstanden sind.
    steuerpflichtig = round(summen.get("netto", 0) + summen.get("ust", 0), 2)

    for p in leistungen:
        s.text(RAND, y, _ANZEIGENAME.get(p.get("bezeichnung", ""), p.get("bezeichnung", "")), 9.5)
        s.text(0, y, _eur(p["netto"]), 9.5, rechts=sp_netto)
        s.text(0, y, f"{p.get('ustsatz', 0) * 100:.0f} %", 9.5, rechts=sp_ust)
        s.text(0, y, _eur(p["brutto"]), 9.5, fett=True, rechts=sp_brutto)
        y += 16

    if durchlaufende:
        # Zwischensumme der eigenen Leistungen. Ohne sie muss die Buchhaltung
        # den eigentlichen Rechnungsbetrag selbst bilden, weil zwischen ihr und
        # dem Gesamtbetrag die Beherbergungssteuer steht, die nicht dazugehört.
        # Hell hinterlegt, damit sie sich von den Einzelposten abhebt.
        y += 5
        s.kasten(RAND, y - 12.5, rechts, y + 6.5, KASTEN)
        s.text(RAND + 6, y, "Beherbergungsleistungen", 9.2, fett=True)
        s.text(0, y, _eur(summen.get("netto", 0)), 9.2, fett=True, rechts=sp_netto)
        s.text(0, y, _eur(summen.get("ust", 0)), 9.2, fett=True, rechts=sp_ust)
        s.text(0, y, _eur(steuerpflichtig), 9.2, fett=True, rechts=sp_brutto)
        y += 20
        for p in durchlaufende:
            # Bewusst KEIN Steuersatz: was die Portale als Übernachtungssteuer
            # abrechnen, folgt drei verschiedenen Formeln (siehe
            # `steuer.ohne_citytax`). Lieber keine Angabe als eine, die sich
            # nachrechnen lässt und dann nicht aufgeht.
            s.text(RAND, y, _ANZEIGENAME.get(p.get("bezeichnung", ""), p.get("bezeichnung", "")), 9.5)
            s.text(0, y - 0.4, "nicht steuerbar", 8, farbe=GRAU, rechts=sp_ust)
            s.text(0, y, _eur(p["brutto"]), 9.5, fett=True, rechts=sp_brutto)
            y += 16

    # ---- Gesamtbetrag ------------------------------------------------------
    # Der einzige Betrag, den der Gast wirklich sucht – deshalb als farbige
    # Fläche wie in der Vorlage. Sie steht rechts, damit die Beträge darüber
    # in derselben Flucht bleiben.
    kasten_oben = y + 4
    s.kasten(rechts - 238, kasten_oben, rechts, kasten_oben + 44, PURPLE)
    s.text(rechts - 238 + 14, kasten_oben + 21, "GESAMTBETRAG", 8.5, fett=True, farbe=WEISS)
    s.text(0, kasten_oben + 36, _eur(summen.get("brutto", 0)), 16, fett=True,
           farbe=WEISS, rechts=rechts - 14)
    y = kasten_oben + 44

    # ---- Steuerinformation -------------------------------------------------
    y += 30
    s.text(RAND, y, "Steuerinformation", 8, fett=True, farbe=GRAU)
    y += 14
    for satz, w in sorted(_je_steuersatz(leistungen).items()):
        s.text(RAND, y, f"{satz * 100:.0f} % Umsatzsteuer auf Beherbergungsleistungen:", 8.5)
        s.text(0, y, f"Netto {_eur(w['netto'])}  ·  USt. {_eur(w['ust'])}  ·  "
                     f"Brutto {_eur(w['brutto'])}", 8.5, fett=True, rechts=rechts)
        y += 13

    # ---- Hinweise ----------------------------------------------------------
    y += 12
    if storniert:
        s.text(RAND, y, f"Storniert: {r.get('storno_grund') or 'ohne Angabe'}",
               9, fett=True, farbe=ROT)
        y += 18
    if durchlaufende:
        s.text(RAND, y, "Hinweis zur Beherbergungssteuer", 8, fett=True, farbe=GRAU)
        y += 13
        for zeile in ["Die Beherbergungssteuer schuldet nach der Satzung der "
                      "Landeshauptstadt Dresden der Gast; sie wird lediglich",
                      "einbehalten und abgeführt. Sie ist damit ein nicht steuerbarer "
                      "durchlaufender Posten nach § 10 Abs. 1 UStG",
                      "und gehört nicht zum Entgelt."]:
            s.text(RAND, y, zeile, 8, farbe=GRAU)
            y += 11
    if hinweis:
        y += 6
        for zeile in hinweis.splitlines():
            s.text(RAND, y, zeile, 8.5, farbe=GRAU)
            y += 12

    _fusszeile(s, betreiber, rechts, seite.rect.height)
    s.fertig()
    roh = doc.tobytes()
    doc.close()
    return roh


def dateiname(r):
    nummer = (r.get("nummer") or "Entwurf").replace("/", "-")
    gast = (r.get("gast") or "").replace(" ", "_")[:30] or "Gast"
    return f"Rechnung_{nummer}_{gast}.pdf"


def fehlende_pflichtangaben(betreiber):
    """Was der Rechnung noch fehlt, um vollständig zu sein (§ 14 Abs. 4 UStG)."""
    fehlt = []
    for feld, name in [("name", "Name/Firma"), ("strasse", "Straße"),
                       ("plz", "PLZ"), ("ort", "Ort")]:
        if not (betreiber.get(feld) or "").strip():
            fehlt.append(name)
    if not ((betreiber.get("steuernummer") or "").strip()
            or (betreiber.get("ust_id") or "").strip()):
        fehlt.append("Steuernummer oder USt-IdNr.")
    return fehlt
