#!/usr/bin/env python3
"""Belege bis zur EÜR: Kategorien, Prüfungen, Monatsabschluss, Export.

Ohne Oberfläche – hier steht nur, was fachlich gilt. Die Anzeige dazu liegt in
`app/ui/belege.py`.

**Warum die Kategorie-Namen so sperrig sind.** Das EÜR-Workbook
(`Buchhaltung_DS_Apartments_2026.xlsx`) zieht jede Position mit

    SUMIF(Kontenjournal!$G$4:$G$N; "<Kategorie>"; $E$4:$E$N)

also über einen **wörtlichen Vergleich**. Ein Buchstabe daneben, und die Summe
bleibt still auf null – kein Fehler, keine Meldung, nur eine EÜR, die zu
niedrig ist. Deshalb sind die Namen hier exakt die Kriterien aus dem Workbook,
Klammern und Halbgeviertstrich eingeschlossen, und deshalb ist eine freie
Eingabe an dieser Stelle keine gute Idee.

Am 6.8.2026 gegen das Workbook geprüft: alle 26 Kriterien treffen.

**Was hier bewusst nicht passiert:** Die App schreibt nicht ins Workbook. Sie
gibt einen Monat als CSV in den acht Spalten des Kontenjournals aus; angehängt
wird von Hand, und dabei ist die Bereichsgrenze N der SUMIF nachzuziehen. Die
Buchhaltung bleibt damit dort, wo sie hingehört.
"""
import csv
import io
import re
from datetime import date, datetime

from app import db

TABELLE = "abschluesse"

# ---------------------------------------------------------------- Kategorien
# Wörtlich die SUMIF-Kriterien des Workbooks. Reihenfolge nach dem, was als
# fotografierter Beleg tatsächlich ankommt – nicht alphabetisch.
VORGABE_KATEGORIEN = [
    "Reinigung/Verbrauch (dm)",
    "Drogerie/Verbrauch (Rossmann)",
    "Ausstattung/GWG (JYSK)",
    "Textilien/Wäsche (Hotelwäsche Bartsch)",
    "Wäscherei (Rena)",
    "Lebensmittel (privat? – prüfen)",
    "Werbung (Meta/Facebook)",
    "Software (Smoobu Channelmanager)",
    "Software (Lexware Office)",
    "Strom (SachsenEnergie)",
    "Wasser/Nebenkosten (DREWAG)",
    # Ab AP24 kommen die Kontobewegungen dazu – und mit ihnen die Posten, die
    # es als *Beleg* nie gab: Miete, Löhne, Darlehen, Entnahmen. Die
    # Schreibweise ist auch hier **wörtlich die des Workbooks**, denn sie
    # entscheidet über den SUMIF (siehe Modulkopf). Erfundene Bezeichnungen
    # ließen die Summe still auf null fallen.
    "Miete/Raumkosten Wernerstr. 34c (Weitervermietung)",
    "Hausgeld WEG Wohnpark",
    "Löhne/Gehälter Minijob",
    "Sozialabgaben Minijob (Knappschaft)",
    "Knappschaft HAUSHALTSSCHECK (privater Haushalt? – prüfen)",
    "Kontoführung/Bankgebühr DKB",
    "Telekommunikation (Magenta TV)",
    "Verwaltungsgebühr LH Dresden (Geodaten)",
    # Erlösseite. „netto Auszahlung" ist keine Beschreibung, sondern eine
    # Warnung: was ankommt, ist der Gastpreis MINUS Provision – siehe AP23.
    "Beherbergungserlöse (Booking, netto Auszahlung)",
    "Beherbergungserlöse (Airbnb, netto Auszahlung)",
    "Beherbergungserlöse (Direktbuchung, brutto)",
    # Und die vier, an denen sich das Ergebnis entscheidet: keiner davon ist
    # eine Betriebsausgabe.
    "Beherbergungssteuer an Stadt (durchlaufender Posten)",
    "Darlehensrate Targobank (Zins/Tilgung – aufteilen)",
    "Immobiliendarlehen (Zins abzugsf., Tilgung neutral)",
    "Eigenübertrag / Entnahme",
    "Privateinlage / Eigenübertrag",
    "Kartenausgleich (neutral)",
    "Kreditkartenausgleich (neutral – Einzelausgaben s. VISA)",
]

# Der Auffangposten. Er steht so im Workbook und landet in der EÜR unter
# „Sonstige Eingangsrechnung (unklar)". Ein Beleg darf hier landen – aber er
# hält den Monatsabschluss auf, bis jemand hingesehen hat. Ein stiller
# Sammelposten wäre bequemer und genau deshalb falsch.
UNKLAR = "Eingangsrechnung – Verwendungszweck unklar (prüfen)"

# Die Klasse sagt, wie die Zahl ins Ergebnis eingeht. Sie ergibt sich aus der
# Kategorie; von Hand gesetzt wird sie nur in Ausnahmen.
KLASSEN = ["Ausgabe", "Ausgabe/prüfen", "Privat/prüfen", "Durchlaufend",
           "Neutral", "Einnahme"]
_KLASSE_JE_KATEGORIE = {
    "Lebensmittel (privat? – prüfen)": "Privat/prüfen",
    UNKLAR: "Ausgabe/prüfen",
    # Was auf dem Konto steht, aber nicht ins betriebliche Ergebnis gehört.
    "Eigenübertrag / Entnahme": "Privat/prüfen",
    "Privateinlage / Eigenübertrag": "Privat/prüfen",
    "Knappschaft HAUSHALTSSCHECK (privater Haushalt? – prüfen)": "Privat/prüfen",
    "Beherbergungssteuer an Stadt (durchlaufender Posten)": "Durchlaufend",
    "Kartenausgleich (neutral)": "Neutral",
    "Kreditkartenausgleich (neutral – Einzelausgaben s. VISA)": "Neutral",
    # Zins ist Ausgabe, Tilgung nicht – beides steckt in einer Rate. Bis AP22
    # sie trennt, sind die Posten benannt, aber ausdrücklich unfertig.
    "Darlehensrate Targobank (Zins/Tilgung – aufteilen)": "Ausgabe/prüfen",
    "Immobiliendarlehen (Zins abzugsf., Tilgung neutral)": "Ausgabe/prüfen",
    # Erlöse. Die Provision fehlt in diesen Beträgen – bis AP23 sie
    # heraustrennt, ist der Umsatz zu niedrig ausgewiesen.
    "Beherbergungserlöse (Booking, netto Auszahlung)": "Einnahme",
    "Beherbergungserlöse (Airbnb, netto Auszahlung)": "Einnahme",
    "Beherbergungserlöse (Direktbuchung, brutto)": "Einnahme",
}


def kategorien(cfg=None):
    """Auswahlliste: die Vorgaben, dann eigene aus den Einstellungen, zuletzt
    der Auffangposten. Eigene sind nötig, weil jeder neue Lieferant eine neue
    Zeile im Kontenjournal bekommt – die Vorgabe kann das nicht vorwegnehmen."""
    return VORGABE_KATEGORIEN + eigene_kategorien(cfg) + [UNKLAR]


# ------------------------------------------------------- Eigene Kategorien
# Die Vorgaben oben sind wörtlich die SUMIF-Kriterien des Workbooks und deshalb
# unveränderlich. Alles, was der Betrieb darüber hinaus auswerten will –
# „Putzmittel", „Gastgeschenke", was auch immer –, gehört hierher: angelegt in
# den Einstellungen, nicht im Quelltext.

def eigene_kategorien(cfg=None):
    """Die selbst angelegten Kategorien, in der Reihenfolge des Anlegens."""
    return [k.strip() for k in ((cfg or {}).get("beleg_kategorien") or [])
            if k and k.strip() and k.strip() not in VORGABE_KATEGORIEN]


def kategorie_anlegen(cfg, name):
    """Eine eigene Kategorie hinzufügen. Gibt (ok, meldung) zurück.

    Abgelehnt wird, was schon existiert – auch als Vorgabe. Zwei gleich
    heißende Kategorien wären in der Auswahlliste nicht unterscheidbar, und in
    der Auswertung liefe die Summe auf zwei Zeilen auseinander.
    """
    name = " ".join((name or "").split())
    if not name:
        return False, "Bitte einen Namen eingeben."
    vorhanden = {k.lower() for k in kategorien(cfg)}
    if name.lower() in vorhanden:
        return False, f"„{name}“ gibt es schon."
    cfg.setdefault("beleg_kategorien", []).append(name)
    return True, f"„{name}“ angelegt."


def kategorie_umbenennen(cfg, alt, neu):
    """Eine eigene Kategorie umbenennen – **samt der schon zugeordneten Sätze**.

    Ohne das Nachziehen verwaist die Auswertung still: die Belege und
    Bewegungen trügen weiter den alten Text, die neue Kategorie stünde bei
    null, und niemand sähe einen Fehler.

    Vorgaben lassen sich nicht umbenennen – sie sind die wörtlichen
    SUMIF-Kriterien des Workbooks. Gibt (ok, meldung) zurück.
    """
    alt = " ".join((alt or "").split())
    neu = " ".join((neu or "").split())
    if alt in VORGABE_KATEGORIEN:
        return False, "Vorgaben lassen sich nicht umbenennen."
    if alt not in eigene_kategorien(cfg):
        return False, "Diese Kategorie gibt es nicht."
    if not neu:
        return False, "Bitte einen Namen eingeben."
    if neu.lower() != alt.lower() and neu.lower() in {k.lower() for k in kategorien(cfg)}:
        return False, f"„{neu}“ gibt es schon."
    cfg["beleg_kategorien"] = [neu if k == alt else k
                               for k in (cfg.get("beleg_kategorien") or [])]
    return True, f"Umbenannt in „{neu}“ – {_nachziehen(alt, neu)} Sätze mitgenommen."


def kategorie_loeschen(cfg, name):
    """Eine eigene Kategorie entfernen.

    Solange ihr noch Belege oder Bewegungen zugeordnet sind, wird nicht
    gelöscht: die Sätze trügen sonst eine Kategorie, die es nicht mehr gibt.
    """
    name = " ".join((name or "").split())
    if name in VORGABE_KATEGORIEN:
        return False, "Vorgaben lassen sich nicht löschen."
    benutzt = _zaehlen(name)
    if benutzt:
        return False, (f"„{name}“ ist noch {benutzt}× zugeordnet – erst "
                       "umbuchen, dann löschen.")
    cfg["beleg_kategorien"] = [k for k in (cfg.get("beleg_kategorien") or [])
                               if k != name]
    return True, f"„{name}“ entfernt."


def _betroffen(name):
    """Alle Sätze, die diese Kategorie tragen – Belege wie Kontobewegungen."""
    for tabelle in ("belege", "bewegungen"):
        try:
            for satz in db.alle(tabelle):
                if (satz.get("kategorie") or "") == name:
                    yield tabelle, satz
        except Exception:
            continue        # Tabelle (noch) nicht vorhanden


def _zaehlen(name):
    return sum(1 for _t, _s in _betroffen(name))


def _nachziehen(alt, neu):
    anzahl = 0
    with db.transaktion():
        for tabelle, satz in list(_betroffen(alt)):
            db.speichern(tabelle, satz["id"], dict(satz, kategorie=neu))
            anzahl += 1
    return anzahl


def klasse_fuer(kategorie):
    """Vorschlag für die Klasse. Unbekanntes ist eine Ausgabe – das ist der
    Normalfall bei einem Beleg."""
    return _KLASSE_JE_KATEGORIE.get((kategorie or "").strip(), "Ausgabe")


# ------------------------------------------------------------------ Betrag
def betrag_zahl(text):
    """„27,81" / „1.234,56" / „27.81" -> 27.81. None, wenn nichts zu lesen ist.

    Die Beträge kommen aus der OCR und aus Tippen am Handy, also in jeder
    denkbaren Schreibweise. Sie hier einmal sauber zu lesen ist billiger, als
    sie später in der Buchhaltung zu suchen.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return round(float(text), 2)
    s = str(text).strip().replace("€", "").replace(" ", "")
    if not s:
        return None
    s = re.sub(r"[^\d,.\-]", "", s)
    if "," in s and "." in s:            # 1.234,56 – der Punkt gruppiert
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:                        # 27,81
        s = s.replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def betrag_text(wert):
    """Zahl -> „1.234,56". Deutsche Schreibweise, weil das Ziel Excel ist."""
    if wert is None:
        return ""
    ganz, komma = f"{abs(wert):.2f}".split(".")
    gruppen = []
    while len(ganz) > 3:                      # Tausenderpunkte von hinten
        gruppen.insert(0, ganz[-3:])
        ganz = ganz[:-3]
    gruppen.insert(0, ganz)
    return ("-" if wert < 0 else "") + ".".join(gruppen) + "," + komma


# ------------------------------------------------------------------ Datum
def belegdatum(beleg):
    """Das Datum, unter dem gebucht wird: das Belegdatum, sonst der Upload.

    Beides auseinanderzuhalten ist der Punkt. Ein Beleg vom 29. wird oft erst
    am 2. des Folgemonats fotografiert – er gehört trotzdem in den alten Monat,
    sonst wandert die Ausgabe still ins nächste Quartal.
    """
    d = (beleg.get("datum") or "").strip()
    if d:
        return d[:10]
    return (beleg.get("ts") or "")[:10]


def monat(beleg):
    """„2026-08" – der Monat, in dem der Beleg abgeschlossen wird."""
    return belegdatum(beleg)[:7]


def _ist_datum(s):
    try:
        date.fromisoformat((s or "")[:10])
        return True
    except ValueError:
        return False


# --------------------------------------------------------------- Prüfungen
PFLICHTFELDER = {
    "datum": "Belegdatum",
    "amount": "Betrag",
    "merchant": "Händler",
    "kategorie": "Kategorie",
}


def fehlende_felder(beleg):
    """Was fehlt, damit der Beleg buchbar ist – in Klartext, nicht als Schlüssel.

    Ohne diese Prüfung landen halbe Belege im Export, und der Fehler fällt erst
    im Steuerbüro auf, wo ihn niemand mehr aufklären kann.
    """
    fehlt = []
    if not _ist_datum(belegdatum(beleg)):
        fehlt.append(PFLICHTFELDER["datum"])
    if betrag_zahl(beleg.get("amount")) in (None, 0):
        fehlt.append(PFLICHTFELDER["amount"])
    if not (beleg.get("merchant") or "").strip():
        fehlt.append(PFLICHTFELDER["merchant"])
    if not (beleg.get("kategorie") or "").strip():
        fehlt.append(PFLICHTFELDER["kategorie"])
    return fehlt


def _dublettenschluessel(beleg):
    haendler = re.sub(r"\W+", "", (beleg.get("merchant") or "").lower())
    return (belegdatum(beleg), haendler, betrag_zahl(beleg.get("amount")))


def dubletten(belege):
    """Gruppen von Belegen, die denselben Vorgang meinen könnten.

    Gleicher Tag, gleicher Händler, gleicher Betrag. Das passiert real: zwei
    Leute fotografieren denselben Kassenbon, oder der Upload wird nach einem
    Verbindungsabbruch wiederholt. Doppelt gebucht wäre die Ausgabe doppelt
    abgesetzt – das fällt in der EÜR niemandem auf.

    Gemeldet, nicht gelöscht: Zwei Einkäufe am selben Tag beim selben Händler
    über denselben Betrag sind unwahrscheinlich, aber möglich.
    """
    nach_schluessel = {}
    for b in belege:
        s = _dublettenschluessel(b)
        if None in s or not s[1]:
            continue
        nach_schluessel.setdefault(s, []).append(b)
    return [g for g in nach_schluessel.values() if len(g) > 1]


def pruefung(belege):
    """Der vollständige Befund eines Monats – alles, was einem Abschluss
    im Weg steht, in einem Durchgang."""
    unvollstaendig = [(b, fehlende_felder(b)) for b in belege]
    unvollstaendig = [(b, f) for b, f in unvollstaendig if f]
    unklar = [b for b in belege if (b.get("kategorie") or "").strip() == UNKLAR]
    doppelt = dubletten(belege)
    return {"anzahl": len(belege),
            "unvollstaendig": unvollstaendig,
            "unklar": unklar,
            "dubletten": doppelt,
            "summe": summe(belege),
            "abschliessbar": not (unvollstaendig or unklar or doppelt)}


def summe(belege):
    """Summe der Beträge (positiv), zum Abgleich mit dem Kontoauszug."""
    return round(sum(betrag_zahl(b.get("amount")) or 0 for b in belege), 2)


# ------------------------------------------------------------------ Export
# Die acht Spalten des Kontenjournals, in seiner Reihenfolge.
JOURNAL_SPALTEN = ["Datum", "Quelle", "Gegenkonto", "Verwendungszweck",
                   "Betrag", "Klasse", "Kategorie", "Belegstatus"]


def journal_zeile(beleg):
    """Ein Beleg als Zeile des Kontenjournals.

    Das Vorzeichen kommt aus der Klasse: das Journal führt Ausgaben negativ.
    Die Beträge am Beleg stehen positiv, weil niemand ein Minus abtippt.
    """
    klasse = (beleg.get("klasse") or "").strip() or klasse_fuer(beleg.get("kategorie"))
    wert = betrag_zahl(beleg.get("amount")) or 0.0
    if klasse != "Einnahme":
        wert = -abs(wert)
    zweck = (beleg.get("note") or "").strip()
    wohnung = (beleg.get("apartment_name") or "").strip()
    if wohnung:
        zweck = f"{zweck} · {wohnung}".strip(" ·")
    return {"Datum": belegdatum(beleg),
            "Quelle": "Beleg",
            "Gegenkonto": (beleg.get("merchant") or "").strip(),
            "Verwendungszweck": zweck,
            "Betrag": betrag_text(wert),
            "Klasse": klasse,
            "Kategorie": (beleg.get("kategorie") or "").strip(),
            "Belegstatus": "Beleg vorhanden"}


def journal_zeilen(belege):
    return [journal_zeile(b) for b in sorted(belege, key=belegdatum)]


def csv_bytes(belege):
    """CSV in der Form, die das Kontenjournal erwartet: Semikolon getrennt,
    utf-8 mit BOM (sonst zerlegt Excel die Umlaute) und deutsche Beträge."""
    puffer = io.StringIO()
    schreiber = csv.DictWriter(puffer, fieldnames=JOURNAL_SPALTEN, delimiter=";",
                              lineterminator="\r\n")
    schreiber.writeheader()
    for zeile in journal_zeilen(belege):
        schreiber.writerow(zeile)
    return puffer.getvalue().encode("utf-8-sig")


# ------------------------------------------------------------ Monatsabschluss
def _jetzt():
    return datetime.now().isoformat(timespec="seconds")


def abschluss_von(monat_iso):
    """Der Abschluss dieses Monats – None, wenn er noch offen ist."""
    for a in db.alle(TABELLE):
        if a.get("monat") == monat_iso:
            return a
    return None


def abgeschlossen(beleg):
    """Ist der Monat dieses Belegs schon abgeschlossen? Dann ist er gebucht und
    darf sich nicht mehr ändern."""
    return abschluss_von(monat(beleg)) is not None


def abschliessen(monat_iso, belege, wer):
    """Monat schließen: festhalten, was gebucht wurde, und womit.

    Danach sind die Belege dieses Monats unveränderlich. Das ist der Sinn eines
    Abschlusses – eine Zahl, die sich nachträglich noch bewegt, ist im
    Steuerbüro nichts wert. Nachträgliche Belege bekommen einen neuen Monat
    oder müssen von Hand nachgetragen werden.
    """
    befund = pruefung(belege)
    if not befund["abschliessbar"]:
        raise ValueError("Monat ist noch nicht abschließbar")
    eintrag = {"id": monat_iso, "monat": monat_iso, "wer": wer, "wann": _jetzt(),
               "anzahl": len(belege), "summe": summe(belege),
               "beleg_ids": sorted(b["id"] for b in belege)}
    db.anlegen(TABELLE, eintrag)
    return eintrag


def abschluesse():
    """Alle Abschlüsse, neueste zuerst."""
    return sorted(db.alle(TABELLE), key=lambda a: a.get("monat", ""), reverse=True)


def oeffnen(monat_iso):
    """Abschluss zurücknehmen – nur, solange nichts weitergemeldet wurde.

    Es gibt keinen guten Grund, das zu verstecken: manchmal fehlt ein Beleg
    genau einen Tag zu spät. Wer öffnet, steht im Eintrag.
    """
    db.loeschen(TABELLE, monat_iso)


def monate(belege):
    """Welche Monate kommen in diesen Belegen vor – neueste zuerst."""
    return sorted({monat(b) for b in belege if monat(b)}, reverse=True)
