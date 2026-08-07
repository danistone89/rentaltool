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

**Kein Eurozeichen, kein Halbgeviertstrich.** Die eingebauten PDF-Schriften
kennen nur Latin-1; „€" und „–" fehlen dort und werden still zu einem Punkt.
Umlaute gehen, diese beiden nicht. Deshalb steht auf der Rechnung „EUR" und ein
schlichter Bindestrich – sichtbar richtig ist besser als typografisch gemeint.

**Die Beherbergungssteuer steht getrennt und ohne Umsatzsteuer.** Sie ist ein
durchlaufender Posten: die Stadt bekommt sie, nicht der Vermieter. Sie in die
Bemessungsgrundlage zu ziehen hieße, Steuer auf Steuer zu erheben.
"""
from datetime import date

MM = 72 / 25.4          # Millimeter in PDF-Punkte
RAND = 22 * MM
OBEN = 20 * MM

PURPLE = (0.369, 0.165, 0.518)      # #5E2A84
GRAU = (0.42, 0.40, 0.45)
HELLGRAU = (0.75, 0.74, 0.77)
SCHWARZ = (0.14, 0.11, 0.18)


def _eur(betrag):
    s = f"{abs(betrag):,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return ("-" if betrag < 0 else "") + s


def _d(iso):
    try:
        j, m, t = str(iso)[:10].split("-")
        return f"{t}.{m}.{j}"
    except ValueError:
        return str(iso or "")


# Was die eingebauten Schriften nicht kennen. Still ersetzt statt still
# verstuemmelt – ein "·" statt eines Betrags faellt sonst erst dem Gast auf.
_ERSATZ = {"\u20ac": " EUR", "\u2013": "-", "\u2014": "-",
           "\u201e": '"', "\u201c": '"', "\u2019": "'"}


def _darstellbar(text):
    for zeichen, ersatz in _ERSATZ.items():
        text = text.replace(zeichen, ersatz)
    return text.encode("latin-1", "replace").decode("latin-1")


def _zeile(seite, x, y, text, groesse=9, fett=False, farbe=SCHWARZ, rechts=None):
    """Eine Textzeile. `rechts` setzt sie rechtsbündig auf diese x-Position."""
    import fitz
    text = _darstellbar(text)
    schrift = "hebo" if fett else "helv"
    if rechts is not None:
        x = rechts - fitz.get_text_length(text, schrift, groesse)
    seite.insert_text((x, y), text, fontname=schrift, fontsize=groesse, color=farbe)


def _absenderzeile(betr):
    teile = [betr.get("name", ""), betr.get("zusatz", ""),
             f"{betr.get('strasse', '')} {betr.get('hausnummer', '')}".strip(),
             f"{betr.get('plz', '')} {betr.get('ort', '')}".strip()]
    return " · ".join(t for t in teile if t)


def bauen(r, betreiber, hinweis=""):
    """Eine Rechnung als PDF-Bytes.

    `r` ist der Datensatz aus `app/rechnung.py`, `betreiber` die Betreiberdaten
    aus der Konfiguration.
    """
    import fitz
    doc = fitz.open()
    seite = doc.new_page()                      # A4
    breite = seite.rect.width
    rechts = breite - RAND
    y = OBEN

    storniert = r.get("status") == "storniert"

    # ---- Kopf: Absender rechts, klein ------------------------------------
    for i, zeile in enumerate([betreiber.get("name", ""),
                               betreiber.get("zusatz", ""),
                               f"{betreiber.get('strasse', '')} "
                               f"{betreiber.get('hausnummer', '')}".strip(),
                               f"{betreiber.get('plz', '')} "
                               f"{betreiber.get('ort', '')}".strip(),
                               betreiber.get("telefon", ""),
                               betreiber.get("email", "")]):
        if zeile:
            _zeile(seite, 0, y + i * 11, zeile, 8.5,
                   fett=(i == 0), farbe=SCHWARZ if i == 0 else GRAU, rechts=rechts)

    # ---- Empfänger im Fensterbereich -------------------------------------
    y = OBEN + 24 * MM
    _zeile(seite, RAND, y, _absenderzeile(betreiber), 6.5, farbe=GRAU)
    seite.draw_line(fitz.Point(RAND, y + 3), fitz.Point(RAND + 85 * MM, y + 3),
                    color=HELLGRAU, width=0.4)
    e = r.get("empfaenger") or {}
    y += 16
    for zeile in [e.get("name", ""), e.get("strasse", ""),
                  f"{e.get('plz', '')} {e.get('ort', '')}".strip(),
                  e.get("land", "") if (e.get("land") or "").upper() not in ("", "DE") else ""]:
        if zeile:
            _zeile(seite, RAND, y, zeile, 10)
            y += 13

    # ---- Titel und Eckdaten ----------------------------------------------
    y = OBEN + 58 * MM
    titel = "Stornorechnung" if storniert else "Rechnung"
    _zeile(seite, RAND, y, titel, 17, fett=True, farbe=PURPLE)
    nummer = r.get("nummer") or "(Entwurf – noch keine Nummer)"
    _zeile(seite, 0, y, f"Nr. {nummer}", 10, fett=True, rechts=rechts)
    y += 18
    _zeile(seite, 0, y, f"Datum {_d(r.get('datum'))}", 9, farbe=GRAU, rechts=rechts)

    y += 22
    zeitraum = f"{_d(r.get('anreise'))} bis {_d(r.get('abreise'))}"
    for beschriftung, wert in [("Leistung", f"Beherbergung {r.get('wohnung_name', '')}"),
                               ("Leistungszeitraum", zeitraum),
                               ("Gast", r.get("gast", ""))]:
        if wert.strip():
            _zeile(seite, RAND, y, beschriftung, 8.5, farbe=GRAU)
            _zeile(seite, RAND + 32 * MM, y, wert, 9.5)
            y += 13

    # ---- Positionen -------------------------------------------------------
    y += 14
    sp_netto, sp_ust, sp_brutto = rechts - 115, rechts - 62, rechts
    seite.draw_line(fitz.Point(RAND, y - 9), fitz.Point(rechts, y - 9),
                    color=SCHWARZ, width=0.8)
    _zeile(seite, RAND, y, "Position", 8, fett=True, farbe=GRAU)
    _zeile(seite, 0, y, "Netto EUR", 8, fett=True, farbe=GRAU, rechts=sp_netto)
    _zeile(seite, 0, y, "USt", 8, fett=True, farbe=GRAU, rechts=sp_ust)
    _zeile(seite, 0, y, "Brutto EUR", 8, fett=True, farbe=GRAU, rechts=sp_brutto)
    y += 6
    seite.draw_line(fitz.Point(RAND, y), fitz.Point(rechts, y), color=HELLGRAU, width=0.4)
    y += 15

    for p in r.get("positionen", []):
        satz = p.get("ustsatz", 0)
        _zeile(seite, RAND, y, p.get("bezeichnung", ""), 9.5)
        if satz:
            _zeile(seite, 0, y, _eur(p["netto"]), 9.5, rechts=sp_netto)
            _zeile(seite, 0, y, f"{satz * 100:.0f} % · {_eur(p['ust'])}", 9.5, rechts=sp_ust)
        else:
            _zeile(seite, 0, y, "—", 9.5, farbe=GRAU, rechts=sp_netto)
            _zeile(seite, 0, y, "steuerfrei", 8.5, farbe=GRAU, rechts=sp_ust)
        _zeile(seite, 0, y, _eur(p["brutto"]), 9.5, rechts=sp_brutto)
        y += 15

    # ---- Summen -----------------------------------------------------------
    s = r.get("summen") or {}
    y += 4
    seite.draw_line(fitz.Point(rechts - 190, y), fitz.Point(rechts, y),
                    color=HELLGRAU, width=0.4)
    y += 15
    for beschriftung, wert, fett in [
            ("Nettobetrag (7 % USt)", s.get("netto", 0), False),
            ("zzgl. 7 % Umsatzsteuer", s.get("ust", 0), False),
            ("Beherbergungssteuer (durchlaufend)", s.get("durchlaufend", 0), False)]:
        if wert:
            _zeile(seite, 0, y, beschriftung, 9, farbe=GRAU, rechts=rechts - 78)
            _zeile(seite, 0, y, _eur(wert) + " EUR", 9, rechts=rechts)
            y += 14
    seite.draw_line(fitz.Point(rechts - 190, y), fitz.Point(rechts, y),
                    color=SCHWARZ, width=0.8)
    y += 16
    _zeile(seite, 0, y, "Gesamtbetrag", 11, fett=True, rechts=rechts - 78)
    _zeile(seite, 0, y, _eur(s.get("brutto", 0)) + " EUR", 12, fett=True,
           farbe=PURPLE, rechts=rechts)

    # ---- Hinweise ---------------------------------------------------------
    y += 30
    if s.get("durchlaufend"):
        _zeile(seite, RAND, y,
               "Die Beherbergungssteuer ist ein durchlaufender Posten der "
               "Landeshauptstadt Dresden und", 8.5, farbe=GRAU)
        y += 11
        _zeile(seite, RAND, y, "unterliegt nicht der Umsatzsteuer.", 8.5, farbe=GRAU)
        y += 16
    if storniert:
        _zeile(seite, RAND, y, f"Storniert: {r.get('storno_grund') or 'ohne Angabe'}",
               9, fett=True, farbe=(0.63, 0.23, 0.18))
        y += 16
    if hinweis:
        for zeile in hinweis.splitlines():
            _zeile(seite, RAND, y, zeile, 9)
            y += 12

    # ---- Fußzeile ---------------------------------------------------------
    fuss = seite.rect.height - 20 * MM
    seite.draw_line(fitz.Point(RAND, fuss - 12), fitz.Point(rechts, fuss - 12),
                    color=HELLGRAU, width=0.4)
    links = [betreiber.get("name", ""),
             f"{betreiber.get('strasse', '')} {betreiber.get('hausnummer', '')}".strip(),
             f"{betreiber.get('plz', '')} {betreiber.get('ort', '')}".strip()]
    mitte = [x for x in [
        f"Steuernummer {betreiber['steuernummer']}" if betreiber.get("steuernummer") else "",
        f"USt-IdNr. {betreiber['ust_id']}" if betreiber.get("ust_id") else "",
        betreiber.get("telefon", ""), betreiber.get("email", "")] if x]
    rechte_spalte = [x for x in [betreiber.get("bank", ""),
                                 f"IBAN {betreiber['iban']}" if betreiber.get("iban") else "",
                                 f"BIC {betreiber['bic']}" if betreiber.get("bic") else ""] if x]
    for i in range(max(len(links), len(mitte), len(rechte_spalte))):
        yy = fuss + i * 9.5
        if i < len(links):
            _zeile(seite, RAND, yy, links[i], 7, farbe=GRAU)
        if i < len(mitte):
            _zeile(seite, RAND + 62 * MM, yy, mitte[i], 7, farbe=GRAU)
        if i < len(rechte_spalte):
            _zeile(seite, 0, yy, rechte_spalte[i], 7, farbe=GRAU, rechts=rechts)

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
