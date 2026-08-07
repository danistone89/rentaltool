#!/usr/bin/env python3
"""Kontoauszüge einlesen: DKB-Geschäftskonto und DKB-VISA-Karte.

Ohne Oberfläche, ohne Datenbank – hier steht nur, wie aus einer CSV-Datei
Bewegungen werden. Die Ablage liegt in `app/konto.py`.

**Warum das der Anfang der Buchhaltung ist.** Der Überblick rechnet auf
Zahlungsbasis: es zählt der Tag, an dem das Geld geflossen ist. Ohne die
Kontobewegungen gibt es keinen Zufluss, also kein Ergebnis – und ohne sie fehlt
dem Steuerbüro später einer der vier Belegströme.

**Zwei Formate, ein Ergebnis.** Beide Dateien kommen als CSV mit `;`, in
UTF-8 **mit BOM**, mit vier Kopfzeilen vor der eigentlichen Spaltenzeile und
mit zweistelliger Jahreszahl (`24.07.26`). Sie unterscheiden sich sonst
deutlich: das Geschäftskonto nennt beide Parteien, IBAN und Verwendungszweck,
die Karte nur eine Beschreibung. Herausgelesen wird beides in dieselbe Form.

**Der Kreditkarten-Ausgleich steht in BEIDEN Dateien** – im Geschäftskonto als
Abbuchung („KREDITKARTENABRECHNUNG VISA"), auf der Karte als Gutschrift
(„Ausgleich Kreditkarte"). Wer beide Auszüge einliest und alles zusammenzählt,
zählt die Kartenkäufe doppelt: einmal als Kauf, einmal als Abrechnung. Es ist
aber keine Ausgabe, sondern eine **Umbuchung zwischen eigenen Konten**. Solche
Bewegungen werden deshalb erkannt und gekennzeichnet (`umbuchung`), damit sie
aus dem Ergebnis herausfallen können, ohne aus dem Auszug zu verschwinden.
"""
import csv
import hashlib
import io
import re
from datetime import date

GESCHAEFT = "giro"
KARTE = "karte"

# Spaltenzeilen, an denen die beiden Formate erkannt werden. Der Vergleich läuft
# über die ersten Spalten, nicht über den Dateinamen – der ist frei wählbar.
_KOPF_GIRO = ("buchungsdatum", "wertstellung", "status")
_KOPF_KARTE = ("belegdatum", "wertstellung", "status")

# Woran eine Umbuchung zwischen eigenen Konten zu erkennen ist. Bewusst eng
# gehalten: was hier hineinrutscht, fehlt später im Ergebnis.
_UMBUCHUNG = (
    "kreditkartenabrechnung",
    "ausgleich kreditkarte",
)


def _text(wert):
    return " ".join(str(wert or "").split())


def betrag(wert):
    """Deutscher Betrag als Zahl: „1.234,56" → 1234.56, „-3,41" → -3.41.

    Die DKB schreibt glatte Beträge ohne Nachkommastellen („-111"), mit
    Tausenderpunkt und mit Komma – alle drei müssen durch dieselbe Stelle.
    """
    s = _text(wert).replace("€", "").replace(" ", "")
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def datum(wert, heute=None):
    """„24.07.26" → „2026-07-24". Auch vierstellige Jahre werden angenommen.

    Zweistellige Jahre sind eine Falle: ein Auszug aus 1999 gibt es nicht, ein
    Datum in der fernen Zukunft auch nicht. Ausgelegt wird deshalb ins
    Jahrhundert von heute, und was mehr als ein Jahr in der Zukunft läge, gilt
    als Vorjahrhundert-Tippfehler und wird zurückgesetzt.
    """
    s = _text(wert)
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})", s)
    if not m:
        return ""
    tag, monat, jahr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    heute = heute or date.today()
    if jahr < 100:
        jahr += (heute.year // 100) * 100
        if jahr > heute.year + 1:
            jahr -= 100
    try:
        return date(jahr, monat, tag).isoformat()
    except ValueError:
        return ""


def ist_umbuchung(text):
    """Bewegung zwischen eigenen Konten? Siehe Modulkopf – sie darf nicht als
    Ausgabe zählen, sonst stehen die Kartenkäufe doppelt im Ergebnis."""
    t = _text(text).lower()
    return any(marke in t for marke in _UMBUCHUNG)


def schluessel(bewegung):
    """Fingerabdruck einer Bewegung – für die Dublettenerkennung.

    Auszüge überschneiden sich: wer im Juli und im August exportiert, hat den
    Juli zweimal. Der Schlüssel nimmt das, was die Bank nicht mehr ändert –
    Konto, Datum, Betrag und den Text. Die laufende Nummer der Datei taugt
    nicht, sie beginnt in jedem Export neu.
    """
    teile = [bewegung.get("konto", ""), bewegung.get("datum", ""),
             f"{bewegung.get('betrag', 0):.2f}", _text(bewegung.get("text")),
             _text(bewegung.get("gegenpartei"))]
    return hashlib.sha256("|".join(teile).encode("utf-8")).hexdigest()[:16]


def _zeilen(rohdaten):
    """CSV-Zeilen aus den Rohbytes – UTF-8 mit BOM, notfalls Latin-1."""
    if isinstance(rohdaten, bytes):
        try:
            text = rohdaten.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = rohdaten.decode("latin-1")
    else:
        text = rohdaten
    return list(csv.reader(io.StringIO(text), delimiter=";"))


def _kopfzeile(zeilen):
    """(Index der Spaltenzeile, Format) – oder (None, None).

    Vor der Spaltenzeile stehen Kontoname, Zeitraum und Saldo. Gesucht wird
    deshalb nach der Zeile, die wie ein Spaltenkopf aussieht, statt eine feste
    Zeilennummer anzunehmen: die DKB hat den Vorspann schon geändert.
    """
    for i, zeile in enumerate(zeilen[:15]):
        klein = tuple(_text(z).lower() for z in zeile[:3])
        if klein == _KOPF_GIRO:
            return i, GESCHAEFT
        if klein == _KOPF_KARTE:
            return i, KARTE
    return None, None


def kontoname(zeilen, art):
    """Woher der Auszug stammt – für die Anzeige und den Dublettenschlüssel."""
    if not zeilen:
        return art
    erste = [_text(z) for z in zeilen[0] if _text(z)]
    if art == GESCHAEFT:
        return erste[-1] if len(erste) > 1 else (erste[0] if erste else art)
    # Karte: „Karte";"DKB-VISA-Business-Card";"4998 •••• •••• 8136"
    ziffern = re.findall(r"\d{4}", erste[-1]) if erste else []
    return f"VISA {ziffern[-1]}" if ziffern else (erste[1] if len(erste) > 1 else art)


def lesen(rohdaten, heute=None):
    """Einen Auszug einlesen: (konto, art, [bewegungen]).

    Wirft `ValueError` mit einem Satz Klartext, wenn die Datei keine ist – eine
    stumm leere Liste wäre schlimmer, sie sähe aus wie ein Monat ohne Umsätze.
    """
    zeilen = _zeilen(rohdaten)
    kopf, art = _kopfzeile(zeilen)
    if kopf is None:
        raise ValueError("Das sieht nicht nach einem DKB-Auszug aus – erwartet "
                         "wird eine CSV mit Semikolon und einer Spaltenzeile "
                         "„Buchungsdatum“ (Konto) oder „Belegdatum“ (Karte).")
    spalten = [_text(z).lower() for z in zeilen[kopf]]
    konto = kontoname(zeilen, art)
    bewegungen = []
    for zeile in zeilen[kopf + 1:]:
        if not any(_text(z) for z in zeile):
            continue
        satz = dict(zip(spalten, [_text(z) for z in zeile]))
        b = (_giro(satz, heute) if art == GESCHAEFT else _karte(satz, heute))
        if b is None:
            continue
        b["konto"] = konto
        b["art"] = art
        b["id"] = schluessel(b)
        bewegungen.append(b)
    return konto, art, bewegungen


def _gemeinsam(satz, heute):
    """Was beide Formate teilen. None, wenn Datum oder Betrag fehlen – eine
    Bewegung ohne beides ist keine."""
    wert = betrag(satz.get("betrag (€)") or satz.get("betrag"))
    tag = datum(satz.get("buchungsdatum") or satz.get("belegdatum"), heute)
    if wert is None or not tag:
        return None
    return {"datum": tag,
            "wertstellung": datum(satz.get("wertstellung"), heute) or tag,
            "betrag": wert,
            # „Vorgemerkt" ist noch nicht gebucht und kann sich ändern. Sie
            # wird mitgenommen, aber gekennzeichnet – wer sie zählt, rechnet
            # mit einer Zahl, die die Bank noch zurücknehmen kann.
            "vorgemerkt": _text(satz.get("status")).lower().startswith("vorgemerkt"),
            "typ": satz.get("umsatztyp", "")}


def _giro(satz, heute):
    b = _gemeinsam(satz, heute)
    if b is None:
        return None
    zweck = satz.get("verwendungszweck", "")
    # Die Gegenpartei ist je nach Richtung die eine oder die andere Spalte.
    gegen = (satz.get("zahlungspflichtige*r", "") if b["betrag"] > 0
             else satz.get("zahlungsempfänger*in", ""))
    b.update({"gegenpartei": gegen, "text": zweck,
              "iban": satz.get("iban", ""),
              "referenz": satz.get("kundenreferenz", ""),
              "umbuchung": ist_umbuchung(zweck)})
    return b


def _karte(satz, heute):
    b = _gemeinsam(satz, heute)
    if b is None:
        return None
    # Die Karte kennt keine zwei Parteien: die Beschreibung IST der Händler.
    beschreibung = satz.get("beschreibung", "")
    b.update({"gegenpartei": beschreibung, "text": beschreibung,
              "iban": "", "referenz": "",
              "umbuchung": ist_umbuchung(beschreibung)})
    return b


def zusammenfassung(bewegungen):
    """Was der Auszug ergibt – für die Rückmeldung nach dem Einlesen.

    Umbuchungen zählen NICHT in Ein- und Ausgang: sie sind kein Geldfluss nach
    außen, sondern eine Verschiebung zwischen eigenen Konten.
    """
    echte = [b for b in bewegungen if not b.get("umbuchung")]
    tage = sorted(b["datum"] for b in bewegungen if b.get("datum"))
    return {"anzahl": len(bewegungen),
            "umbuchungen": len(bewegungen) - len(echte),
            "vorgemerkt": sum(1 for b in bewegungen if b.get("vorgemerkt")),
            "eingang": round(sum(b["betrag"] for b in echte if b["betrag"] > 0), 2),
            "ausgang": round(sum(b["betrag"] for b in echte if b["betrag"] < 0), 2),
            "von": tage[0] if tage else "", "bis": tage[-1] if tage else ""}
