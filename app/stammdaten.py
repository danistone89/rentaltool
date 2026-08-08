#!/usr/bin/env python3
"""Stammdaten der Buchhaltung: Produkte mit Preisen, Kreditoren.

Die Grundlage für alles, was in Phase 6 folgt – die Rechnung (AP14) rechnet mit
diesen Produkten, die Eingangsrechnung (AP15) ordnet Kreditoren zu.

**Warum Preise ein „gültig ab" brauchen, und zwar am Buchungsdatum.**
Die Reinigungsgebühr der Cottaer Straße stieg von 65 € auf 75 €. Welcher Preis
gilt, hängt nicht am Aufenthalt, sondern daran, **wann gebucht wurde**: Wer vor
dem 4.1.2026 gebucht hat, zahlt 65 (72 Buchungen), wer danach buchte, 75 (27
Buchungen, ausnahmslos) – auch wenn beide im selben Monat anreisen. Am
Anreisedatum sortiert sieht dieselbe Reihe aus wie Zufall: die Beträge springen
neunzehnmal hin und her. Wer die Frage falsch stellt, rechnet alte Rechnungen
falsch nach.

**Was der Preis hier ist – und was nicht.** Er ist nicht die Quelle für die
Rechnung: Smoobu liefert die tatsächlich berechnete Gebühr in
`price-details`, und die gilt. Der hinterlegte Preis ist die **Gegenprobe** und
der Rückfall, wenn Smoobu nichts mitschickt (7 von 85 Buchungen). Weichen beide
voneinander ab, ist das ein Klärfall und keine stille Korrektur.
"""
import re
import uuid
from datetime import date

from app import db

PRODUKTE = "produkte"
KREDITOREN = "kreditoren"

# ---- Arten von Produkten ---------------------------------------------------
# Die Art sagt, **wie** der Betrag zustande kommt – nicht, wie er heißt.
BEHERBERGUNG = "beherbergung"    # der Rest nach Abzug von allem anderen
FEST = "fest"                    # fester Preis je Wohnung (Reinigung)
DURCHLAUFEND = "durchlaufend"    # Beherbergungssteuer: 1:1 weitergereicht
ARTEN = [BEHERBERGUNG, FEST, DURCHLAUFEND]

# 7 % trägt heute alles. 19 % ist vorgesehen, damit ein künftiges Produkt (etwa
# ein verkaufter Artikel) nur eine Zahl braucht und keinen Umbau.
STEUERSAETZE = [0.07, 0.19, 0.00]


def _jetzt():
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- Produkte
def produkte():
    """Alle Produkte, in fester Reihenfolge: erst was die Rechnung trägt."""
    reihenfolge = {BEHERBERGUNG: 0, FEST: 1, DURCHLAUFEND: 2}
    return sorted(db.alle(PRODUKTE),
                  key=lambda p: (reihenfolge.get(p.get("art"), 9), p.get("name", "")))


def produkt(produkt_id):
    return db.holen(PRODUKTE, produkt_id)


def produkt_der_art(art):
    """Das eine Produkt dieser Art – None, wenn keins angelegt ist."""
    for p in produkte():
        if p.get("art") == art:
            return p
    return None


def produkt_anlegen(name, art, steuersatz=0.07, produkt_id=None):
    eintrag = {"id": produkt_id or uuid.uuid4().hex[:10], "name": name, "art": art,
               "steuersatz": float(steuersatz), "preise": [], "angelegt": _jetzt()}
    db.anlegen(PRODUKTE, eintrag)
    return eintrag


def produkt_aendern(produkt_id, **felder):
    with db.transaktion():
        p = db.holen(PRODUKTE, produkt_id)
        if p is None:
            return None
        for k, v in felder.items():
            if k in ("name", "art", "steuersatz"):
                p[k] = v
        db.speichern(PRODUKTE, produkt_id, p)
    return p


def produkt_loeschen(produkt_id):
    db.loeschen(PRODUKTE, produkt_id)


# ---------------------------------------------------------------- Preise
def preis_setzen(produkt_id, wohnung_id, ab, betrag):
    """Einen Preis ab einem Datum hinterlegen.

    Ein zweiter Preis mit demselben „ab" für dieselbe Wohnung ersetzt den
    ersten – alles andere wäre ein Widerspruch, den später niemand auflöst.
    """
    ab = str(ab)[:10]
    with db.transaktion():
        p = db.holen(PRODUKTE, produkt_id)
        if p is None:
            return None
        preise = [x for x in p.get("preise", [])
                  if not (x.get("wohnung") == wohnung_id and x.get("ab") == ab)]
        preise.append({"wohnung": wohnung_id, "ab": ab, "betrag": round(float(betrag), 2)})
        p["preise"] = sorted(preise, key=lambda x: (str(x.get("wohnung")), x.get("ab", "")))
        db.speichern(PRODUKTE, produkt_id, p)
    return p


def preis_entfernen(produkt_id, wohnung_id, ab):
    with db.transaktion():
        p = db.holen(PRODUKTE, produkt_id)
        if p is None:
            return None
        p["preise"] = [x for x in p.get("preise", [])
                       if not (x.get("wohnung") == wohnung_id and x.get("ab") == str(ab)[:10])]
        db.speichern(PRODUKTE, produkt_id, p)
    return p


def preis_am(produkt_id_oder_produkt, wohnung_id, buchungsdatum):
    """Der Preis, der an diesem **Buchungstag** galt. None, wenn keiner gilt.

    Gefragt wird mit dem Tag, an dem der Gast gebucht hat – nicht mit der
    Anreise. Genau daran hängt die Cottaer Straße (siehe Modulkopf).
    """
    p = (produkt_id_oder_produkt if isinstance(produkt_id_oder_produkt, dict)
         else produkt(produkt_id_oder_produkt))
    if not p:
        return None
    tag = str(buchungsdatum or "")[:10]
    if not tag:
        return None
    gueltig = [x for x in p.get("preise", [])
               if x.get("wohnung") == wohnung_id and str(x.get("ab", "")) <= tag]
    if not gueltig:
        return None
    return max(gueltig, key=lambda x: x["ab"])["betrag"]


def preisverlauf(produkt_id, wohnung_id):
    """Alle Preisstände dieser Wohnung, ältester zuerst – für die Anzeige."""
    p = produkt(produkt_id) or {}
    return sorted((x for x in p.get("preise", []) if x.get("wohnung") == wohnung_id),
                  key=lambda x: x.get("ab", ""))


# ---------------------------------------------------------------- Kreditoren
def kreditoren():
    return sorted(db.alle(KREDITOREN), key=lambda k: (k.get("name") or "").lower())


def kreditor(kreditor_id):
    return db.holen(KREDITOREN, kreditor_id)


def kreditor_anlegen(name, kategorie="", muster=None, wohnung=None,
                     dauerbeleg="", kreditor_id=None, quelle="", klasse=""):
    """Einen Lieferanten anlegen.

    `muster` sind Textstücke, an denen er im Händlernamen eines Belegs erkannt
    wird – „rossmann" trifft auch „ROSSMANN 2540". Ohne Muster gilt der Name.
    `quelle="gelernt"` markiert einen, der aus einer Beleg-Zuordnung entstanden
    ist – gepflegte Stammdaten sollen von selbst entstandenen unterscheidbar
    bleiben.

    `klasse` sagt, **wie** die Zahlung ins Ergebnis eingeht (siehe
    `buchhaltung.KLASSEN`). Sie steht hier und nicht im Programm, weil das je
    Betrieb verschieden ist: die eigene Privatentnahme, die Stadtkasse, die
    Bank des Darlehens, die Angestellten – das sind gepflegte Daten, keine
    Fachlogik. Leer heißt: aus der Kategorie ableiten, also im Regelfall
    „Ausgabe".
    """
    eintrag = {"id": kreditor_id or uuid.uuid4().hex[:10], "name": name,
               "kategorie": kategorie or "", "muster": [m.lower() for m in (muster or [])],
               "wohnung": wohnung, "dauerbeleg": dauerbeleg or "",
               "quelle": quelle or "", "klasse": klasse or "", "angelegt": _jetzt()}
    db.anlegen(KREDITOREN, eintrag)
    return eintrag


def kreditor_aendern(kreditor_id, **felder):
    with db.transaktion():
        k = db.holen(KREDITOREN, kreditor_id)
        if k is None:
            return None
        for feld, wert in felder.items():
            if feld == "muster":
                k[feld] = [m.lower().strip() for m in (wert or []) if m and m.strip()]
            elif feld in ("name", "kategorie", "wohnung", "dauerbeleg", "klasse"):
                k[feld] = wert
        db.speichern(KREDITOREN, kreditor_id, k)
    return k


def kreditor_loeschen(kreditor_id):
    db.loeschen(KREDITOREN, kreditor_id)


def _normal(text):
    """Klein, ohne Ziffern und Sonderzeichen – „ROSSMANN 2540" wird „rossmann"."""
    return re.sub(r"[^a-zäöüß]+", " ", (text or "").lower()).strip()


def kreditor_zu(haendler):
    """Welcher Kreditor gehört zu diesem Händlernamen? None, wenn keiner passt.

    Das ist die eigentliche Zeitersparnis bei den Belegen: Wer einmal zugeordnet
    ist, wird beim nächsten Mal erkannt und bringt Kategorie und Kostenstelle
    gleich mit.

    Es gewinnt das **längste** passende Muster. Sonst würde ein kurzes „dm"
    einen Kreditor „dm drogerie markt" verdrängen, sobald beide angelegt sind.
    """
    text = f" {_normal(haendler)} "
    if not text.strip():
        return None
    treffer = []
    for k in kreditoren():
        for m in (k.get("muster") or [_normal(k.get("name"))]):
            m = _normal(m)
            if m and (f" {m} " in text or text.strip().startswith(m)
                      or m in text.replace(" ", "")):
                treffer.append((len(m), k))
                break
    if not treffer:
        return None
    return max(treffer, key=lambda x: x[0])[1]


def kategorie_lernen(haendler, kategorie, wohnung=None):
    """Eine von Hand gesetzte Kategorie für diesen Händler merken.

    Ohne das rät die App beim nächsten Beleg desselben Händlers wieder – die
    Zeitersparnis, die die Kreditoren versprechen, entsteht erst hier.

    Trifft ein vorhandener Kreditor, bekommt er die Kategorie. Trifft keiner,
    wird einer angelegt; er trägt `quelle="gelernt"`, damit die selbst
    entstandenen von den gepflegten unterscheidbar bleiben. Das Muster ist der
    normalisierte Händlername – dieselbe Form, in der `kreditor_zu()` sucht.

    **Eine gepflegte Kategorie wird nicht überschrieben.** Sonst kippte ein
    einzelner falsch zugeordneter Beleg die Stammdaten. Geändert wird nur, was
    leer ist oder selbst gelernt wurde.

    Gibt den Kreditor zurück oder None, wenn nichts zu lernen war.
    """
    name = (haendler or "").strip()
    kategorie = (kategorie or "").strip()
    if not name or not kategorie:
        return None
    muster = _normal(name)
    if not muster:
        return None
    # Die Klasse ergibt sich aus der Kategorie – sie mitzulernen ist der Kern:
    # ordnet jemand eine Abbuchung „Privatentnahme" zu, ist der Empfänger ab
    # dann als privat bekannt und fällt aus dem Ergebnis heraus.
    from app import buchhaltung
    klasse = buchhaltung.klasse_fuer(kategorie)
    vorhanden = kreditor_zu(name)
    if vorhanden is None:
        return kreditor_anlegen(name, kategorie, [muster], wohnung,
                                quelle="gelernt", klasse=klasse)
    if vorhanden.get("kategorie") and vorhanden.get("quelle") != "gelernt":
        return vorhanden
    if (vorhanden.get("kategorie"), vorhanden.get("klasse")) != (kategorie, klasse):
        return kreditor_aendern(vorhanden["id"], kategorie=kategorie, klasse=klasse)
    return vorhanden


def dauerbeleg_lernen(haendler, text, kategorie=""):
    """Für diesen Empfänger festhalten, dass ein Dauerbeleg vorliegt.

    Miete, Darlehen, Software: der Vertrag liegt einmal vor, die monatliche
    Abbuchung braucht kein eigenes Blatt. Ohne diesen Weg müsste man jede
    einzelne Buchung von Hand abhaken – sieben Mietzahlungen im Halbjahr, und
    im nächsten wieder.

    Legt den Kreditor an, wenn es ihn noch nicht gibt. Gibt ihn zurück.
    """
    name = " ".join((haendler or "").split())
    text = " ".join((text or "").split()) or "Dauerbeleg"
    if not name:
        return None
    muster = _normal(name)
    if not muster:
        return None
    k = kreditor_zu(name)
    if k is None:
        return kreditor_anlegen(name, kategorie, [muster], quelle="gelernt",
                                dauerbeleg=text)
    return kreditor_aendern(k["id"], dauerbeleg=text)


def vorbelegung(haendler):
    """Was ein Beleg dieses Händlers vermutlich ist: (kategorie, wohnung, kreditor)."""
    k = kreditor_zu(haendler)
    if not k:
        return "", None, None
    return k.get("kategorie", ""), k.get("wohnung"), k


# ------------------------------------------------------------ Erstbefüllung
# Ausdrücklich **nicht** automatisch beim Start: Stammdaten sind gepflegte
# Daten, und etwas, das sich von selbst anlegt, traut sich niemand zu ändern.
# Aufgerufen wird das einmal aus den Einstellungen.
VORGABE_PRODUKTE = [
    ("Übernachtung", BEHERBERGUNG, 0.07),
    ("Endreinigung", FEST, 0.07),
    ("Beherbergungssteuer", DURCHLAUFEND, 0.00),
]

# Aus dem Kontenjournal des EÜR-Workbooks: Lieferant → Kategorie. Die
# Kategorien sind wörtlich die SUMIF-Kriterien (siehe app/buchhaltung.py).
VORGABE_KREDITOREN = [
    ("Rena Textilpflege", "Wäscherei (Rena)", ["rena"]),
    ("Hotelwäsche Bartsch", "Textilien/Wäsche (Hotelwäsche Bartsch)", ["bartsch", "hotelwäsche"]),
    ("Rossmann", "Drogerie/Verbrauch (Rossmann)", ["rossmann"]),
    ("dm-drogerie markt", "Reinigung/Verbrauch (dm)", ["dm drogerie", "dm filiale"]),
    ("JYSK", "Ausstattung/GWG (JYSK)", ["jysk"]),
    ("SachsenEnergie", "Strom (SachsenEnergie)", ["sachsenenergie"]),
    ("DREWAG", "Wasser/Nebenkosten (DREWAG)", ["drewag"]),
    ("Smoobu", "Software (Smoobu Channelmanager)", ["smoobu"]),
    ("Lexware Office", "Software (Lexware Office)", ["lexware", "mollie"]),
    ("Meta Platforms", "Werbung (Meta/Facebook)", ["meta platforms", "facebook"]),
]


def erstbefuellung(vorhandene_wohnungen=None):
    """Produkte und bekannte Lieferanten anlegen, was noch fehlt.

    Legt nichts doppelt an: schon vorhandene Namen bleiben unangetastet.
    Gibt zurück, was neu entstanden ist.
    """
    neu = {"produkte": [], "kreditoren": []}
    vorhanden = {(p.get("name") or "").lower() for p in produkte()}
    for name, art, satz in VORGABE_PRODUKTE:
        if name.lower() not in vorhanden and not produkt_der_art(art):
            produkt_anlegen(name, art, satz)
            neu["produkte"].append(name)
    bekannt = {(k.get("name") or "").lower() for k in kreditoren()}
    for name, kategorie, muster in VORGABE_KREDITOREN:
        if name.lower() not in bekannt:
            kreditor_anlegen(name, kategorie, muster)
            neu["kreditoren"].append(name)
    return neu
