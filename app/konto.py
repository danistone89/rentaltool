#!/usr/bin/env python3
"""Kontobewegungen ablegen und abfragen.

Das Lesen der Auszüge steht in `app/kontoauszug.py`; hier geht es nur um die
Ablage. Getrennt, weil das Lesen die heikle Fachlogik ist und ohne Datenbank
prüfbar bleiben soll.

**Ein zweiter Import darf nichts kaputtmachen.** Auszüge überschneiden sich:
wer im Juli und im August exportiert, hat den Juli zweimal. Der Satzschlüssel
ist deshalb der Fingerabdruck der Bewegung (`kontoauszug.schluessel`) und nicht
eine laufende Nummer – dieselbe Bewegung landet auf demselben Satz, egal wie
oft sie eingelesen wird.

**Was einmal zugeordnet ist, bleibt zugeordnet.** Beim erneuten Import werden
die Felder der Bank aufgefrischt, die eigenen Zuordnungen (Beleg, Rechnung,
Kategorie) aber nicht angerührt. Sonst wäre jede Wiederholung ein Rückschritt.
"""
from datetime import datetime

from app import buchhaltung, db, kontoauszug, stammdaten, zuordnung

TABELLE = "bewegungen"

# **Hier stehen keine Namen.** Wer die eigene Privatentnahme bekommt, welche
# Stadtkasse die Beherbergungssteuer einzieht und wie die Bank des Darlehens
# heißt, ist von Betrieb zu Betrieb verschieden – das sind **Stammdaten**, keine
# Fachlogik. Sie werden als Kreditoren gepflegt (Einstellungen → Produkte &
# Kreditoren) und tragen dort eine Klasse aus `buchhaltung.KLASSEN`.
#
# Eine erste Fassung war anders: die Empfänger standen in dieser Datei. Das war
# nicht Software, sondern eine Buchhaltung in Python – für genau einen Betrieb,
# nicht änderbar, ohne den Quelltext anzufassen.

# Felder, die dem Werkzeug gehören und nicht der Bank. Ein erneuter Import
# lässt sie in Ruhe.
_EIGENE = ("beleg_id", "rechnung_id", "kategorie", "klasse", "herkunft",
           "beleg_noetig", "notiz", "geprueft")

def _jetzt():
    return datetime.now().isoformat(timespec="seconds")


def erkennen(bewegung):
    """Was ist das für eine Bewegung? (kategorie, klasse, herkunft).

    Drei Stufen:

    1. **Umbuchung** zwischen eigenen Konten – neutral, kein Geldfluss nach
       außen (siehe `kontoauszug`).
    2. **Kreditor** – dieselbe Erkennung wie bei den Belegen
       (`stammdaten.kreditor_zu`), nur auf dem Empfänger der Bewegung. Er
       bringt Kategorie **und Klasse** mit. Die Klasse entscheidet, ob die
       Zahlung ins Ergebnis eingeht: eine Privatentnahme ist keine Ausgabe.
       Steht am Kreditor keine Klasse, wird sie aus der Kategorie abgeleitet.
    3. **Nichts** – dann bleibt es leer und die Bewegung wartet auf einen
       Menschen. Raten wäre hier schlimmer als schweigen: eine falsche
       Kategorie läuft still ins Ergebnis.

    Eingänge bekommen keine Kategorie: was ein Erlös ist, entscheidet erst die
    Zuordnung zu einer Rechnung (AP20) und die Portalabrechnung (AP23).
    """
    if bewegung.get("umbuchung"):
        return "", "Neutral", "umbuchung"
    k = stammdaten.kreditor_zu(bewegung.get("gegenpartei") or "")
    if k and (k.get("kategorie") or k.get("klasse")):
        klasse = k.get("klasse") or buchhaltung.klasse_fuer(k.get("kategorie", ""))
        return k.get("kategorie", ""), klasse, "kreditor"
    if bewegung.get("betrag", 0) > 0:
        return "", "Einnahme", ""
    return "", "", ""


def zuordnen(bewegungen=None):
    """Erkennung auf alle Bewegungen anwenden, die noch keine Kategorie tragen.

    Was ein Mensch von Hand gesetzt hat, bleibt unangetastet – sonst nähme ein
    späterer Lauf die Korrektur wieder zurück.
    """
    getroffen = 0
    with db.transaktion():
        for b in (bewegungen if bewegungen is not None else db.alle(TABELLE)):
            if b.get("kategorie") or b.get("klasse"):
                continue
            kategorie, klasse, art = erkennen(b)
            if not (kategorie or klasse):
                continue
            db.speichern(TABELLE, b["id"],
                         dict(b, kategorie=kategorie, klasse=klasse, herkunft=art))
            getroffen += 1
    return getroffen


def ohne_zuordnung():
    """Ausgänge, die weder erkannt noch von Hand zugeordnet sind.

    Das ist die Arbeitsliste – und später das Maß dafür, ob die Übergabe ans
    Steuerbüro vollständig ist (AP25).
    """
    raus = []
    for b in alle():
        if b.get("betrag", 0) >= 0 or b.get("umbuchung"):
            continue
        if (b.get("kategorie") or "").strip():
            continue
        # Wer die Maske benutzt, legt Posten an und setzt das Feld nicht. Ohne
        # diese Zeile wurde die Liste nie leer – an den echten Daten stand eine
        # vollstaendig aufgeteilte Bewegung weiter darin (8.8.2026). Halb
        # aufgeteilt zaehlt weiter mit: der Rest gehoert noch nirgends hin.
        if zuordnung.hat_posten(b["id"]) and zuordnung.ist_fertig(b):
            continue
        raus.append(b)
    return raus


def schnell_zuordnen(bewegung_id, kategorie):
    """Eine ganze Ausgabe mit einem Klick zuordnen – der einfache Fall.

    **Warum es das wieder gibt.** Bis Paket B2 stand die Kategorieauswahl in
    der Zeile; seither muss man jede Bewegung erst aufklappen. Bei 17
    Lohnzahlungen ist das der Unterschied zwischen einem Nachmittag und einer
    Minute (so gemeldet am 8.8.2026).

    Angelegt wird ein **Posten** ueber den ganzen Betrag – nicht nur das Feld.
    Sonst gaebe es zwei Vorstellungen davon, was „zugeordnet" heisst, und die
    Auswertung liefe je nach Weg anders.

    **Nur, solange nichts anderes dran haengt.** Wo schon Posten sind, gilt die
    Maske: ein Klick kann eine Aufteilung nicht kennen.
    """
    from app import buchhaltung, stammdaten
    kategorie = (kategorie or "").strip()
    b = db.holen(TABELLE, bewegung_id)
    if not kategorie or b is None or b.get("umbuchung"):
        return None
    if b.get("betrag", 0.0) >= 0 or zuordnung.hat_posten(bewegung_id):
        return None
    satz, _meldung = zuordnung.hinzufuegen(bewegung_id, zuordnung.KATEGORIE,
                                           b.get("betrag", 0.0), kategorie)
    if satz is None:
        return None
    db.speichern(TABELLE, bewegung_id,
                 dict(b, kategorie=kategorie, klasse=buchhaltung.klasse_fuer(kategorie),
                      herkunft="hand"))
    # Der Kern der Bedienung: einmal zuordnen, danach von allein erkannt.
    stammdaten.kategorie_lernen(b.get("gegenpartei"), kategorie)
    return db.holen(TABELLE, bewegung_id)


def vorschau_gelernt():
    """Welche vorhandenen Bewegungen wuerde die Erkennung jetzt treffen?

    **Das Gelernte wirkte bisher nicht rueckwirkend.** `zuordnen` laeuft nur
    beim Einlesen; wer danach einen Empfaenger zuordnet, hilft damit erst dem
    naechsten Auszug. An den echten Daten blieben so nach der Zuordnung von
    „Valeriya Remez" fuenf weitere Zahlungen an dieselbe Person offen.

    Gibt Vorschlaege zurueck, **ohne zu schreiben** – ein Lauf, der
    stillschweigend Dutzende Bewegungen umschreibt, waere nicht
    nachvollziehbar.
    """
    raus = []
    for b in ohne_zuordnung():
        kategorie, klasse, art = erkennen(b)
        if not kategorie:
            continue
        raus.append({"bewegung": b, "kategorie": kategorie, "klasse": klasse,
                     "herkunft": art})
    return raus


def gelerntes_anwenden(vorschau):
    """Die Vorschlaege aus `vorschau_gelernt` schreiben. Gibt die Anzahl zurueck."""
    n = 0
    for v in vorschau:
        if schnell_zuordnen(v["bewegung"]["id"], v["kategorie"]):
            n += 1
    return n


# ----------------------------------------------------------- Beleg zur Buchung
# Klassen, zu denen es keinen Lieferantenbeleg gibt. Eine Privatentnahme, eine
# abgefuehrte Steuer, eine Umbuchung – dafuer stellt niemand eine Rechnung.
_OHNE_BELEG = {"Privat/prüfen", "Durchlaufend", "Neutral", "Einnahme"}


def beleg_erwartet(bewegung):
    """Braucht diese Bewegung einen Beleg?

    **Die Frage entscheidet, ob die Liste „fehlt noch" brauchbar ist.** Meldete
    sie jede Bewegung ohne Beleg, stuenden dort auch Privatentnahmen, Loehne,
    Darlehensraten und die an die Stadt abgefuehrte Steuer – 93 der 122
    Ausgaenge. Eine Liste, die immer rot ist, liest niemand; genau daran waere
    sie gescheitert.

    Vier Gruende, warum kein Beleg erwartet wird:

    1. **Von Hand entschieden** (`beleg_noetig=False`) – gewinnt immer.
    2. **Eingang oder Umbuchung** – die Erloesseite haengt an Rechnungen
       (AP20 spaeter), eine Umbuchung ist gar kein Geschaeftsvorfall.
    3. **Die Klasse** – privat, durchlaufend, neutral.
    4. **Ein Dauerbeleg am Kreditor** – Miete, Darlehen, Software: der Vertrag
       liegt einmal vor, die monatliche Abbuchung braucht kein eigenes Blatt.
       Genau dafuer gibt es das Feld seit AP13.
    """
    if bewegung.get("beleg_noetig") is not None:
        return bool(bewegung["beleg_noetig"])
    if bewegung.get("umbuchung") or bewegung.get("betrag", 0) >= 0:
        return False
    # **Erst zuordnen, dann Beleg.** Solange nicht feststeht, WAS die Buchung
    # ist, laesst sich nicht sagen, ob es dazu einen Beleg gibt – eine
    # Privatentnahme sieht auf dem Auszug aus wie jede andere Abbuchung. Ohne
    # diese Zeile stuenden alle noch nicht zugeordneten Bewegungen in der
    # Liste: an den echten Daten 121 von 122, also wieder eine Liste, die immer
    # rot ist. Die unzugeordneten stehen ohnehin schon in ihrer eigenen Liste.
    if not (bewegung.get("kategorie") or "").strip():
        return False
    if (bewegung.get("klasse") or "") in _OHNE_BELEG:
        return False
    k = stammdaten.kreditor_zu(bewegung.get("gegenpartei") or "")
    if k and (k.get("dauerbeleg") or "").strip():
        return False
    return True


def holen(bewegung_id):
    return db.holen(TABELLE, bewegung_id)


def beleg_anhaengen(bewegung_id, beleg_id):
    """Einen Beleg an eine Bewegung haengen, **ohne vorhandene Arbeit zu loeschen** (B5).

    Der alte Weg (`beleg_setzen`) loeste zuerst alle Posten. Wer eine Zahlung
    von 100 EUR auf Putzmittel (60) und Gastgeschenke (40) aufgeteilt hatte und
    danach den Kassenbon anhaengte, verlor die Aufteilung – stillschweigend.

    Drei Lagen, drei Antworten:

    1. **Keine Posten** – der Beleg deckt die ganze Bewegung.
    2. **Ein Rest ist offen** – der Beleg deckt genau diesen Rest.
    3. **Nichts mehr offen** – ein zusaetzlicher Posten wuerde die Zahlung
       doppelt buchen. Stattdessen bekommen die Posten ohne Gegenstueck ihr
       Papier: aus „nur Kategorie" wird „Beleg", Betrag und Kategorie bleiben.
       Genau der Fall des Provisionsbelegs, der monatlich zu einer bereits
       gegengebuchten Auszahlung nachgereicht wird.

       **Welche Posten?** Trifft der Betrag des Belegs genau einen von ihnen,
       nur diesen – dann gibt es zu einer Zahlung zwei Belege, und jeder deckt
       seinen Teil. Sonst alle: eine Quittung ueber 100 EUR gehoert zur ganzen
       Zahlung, auch wenn die auf Putzmittel und Gastgeschenke aufgeteilt ist.
       Haengte sie nur an einem Posten, meldete die Belegprobe spaeter eine
       Luecke, die keine ist.

    **Bei einem Zahlungseingang gilt nur Lage 3.** Ein Lieferantenbeleg kann
    niemals den offenen Rest einer Auszahlung decken – der ist Umsatz. An den
    echten Daten hat genau das zugeschlagen: der Provisionsbeleg ueber 265,87
    EUR erzeugte an einer Booking-Auszahlung einen Posten ueber +1.348,42 EUR.
    Er gehoert an die gegengebuchte **Provision**, also an einen negativen
    Posten. Gibt es den noch nicht, passiert nichts – erst gegenbuchen.
    """
    from app import buchhaltung, receipts
    b = db.holen(TABELLE, bewegung_id)
    if b is None or not beleg_id:
        return None
    p = zuordnung.posten(bewegung_id)
    offen = zuordnung.rest(b)
    if b.get("betrag", 0.0) > 0:
        ziel = [z for z in p if not z.get("ziel_id") and z["betrag"] < 0]
        for z in ziel:
            zuordnung.ziel_setzen(z["id"], zuordnung.BELEG, beleg_id)
        return db.holen(TABELLE, bewegung_id) if ziel else None
    if not p:
        zuordnung.hinzufuegen(bewegung_id, zuordnung.BELEG, b.get("betrag", 0.0),
                              kategorie=b.get("kategorie", ""), ziel_id=beleg_id)
    elif abs(offen) >= zuordnung.GENAU:
        zuordnung.hinzufuegen(bewegung_id, zuordnung.BELEG, offen,
                              kategorie=b.get("kategorie", ""), ziel_id=beleg_id)
    else:
        ohne_ziel = [z for z in p if not z.get("ziel_id")]
        if not ohne_ziel:
            return None                       # jeder Posten hat schon sein Papier
        wert = buchhaltung.betrag_zahl((db.holen(receipts.TABELLE, beleg_id)
                                        or {}).get("amount"))
        genau = ([z for z in ohne_ziel
                  if wert is not None and abs(abs(z["betrag"]) - abs(wert)) < 0.005]
                 if len(ohne_ziel) > 1 else [])
        for z in (genau[:1] or ohne_ziel):
            zuordnung.ziel_setzen(z["id"], zuordnung.BELEG, beleg_id)
    return db.holen(TABELLE, bewegung_id)


def beleg_loesen(bewegung_id, beleg_id):
    """Nur diesen einen Beleg wieder loesen – die uebrigen Posten bleiben."""
    for z in zuordnung.posten(bewegung_id):
        if z["art"] == zuordnung.BELEG and z.get("ziel_id") == beleg_id:
            zuordnung.entfernen(z["id"])
    return db.holen(TABELLE, bewegung_id)


def beleg_setzen(bewegung_id, beleg_id):
    """Einen Beleg an eine Bewegung haengen (oder mit '' alle wieder loesen).

    ⚠ **Loest zuerst alle Posten.** Fuer den Alltag ist `beleg_anhaengen` das
    richtige Werkzeug; diese Funktion bleibt fuer den bewussten Neuanfang an
    einer Zeile und fuer den Aufruf mit '' (alles loesen).

    Seit B1 entsteht dabei ein **Posten** (`app/zuordnung.py`), kein Feld mehr.
    """
    b = db.holen(TABELLE, bewegung_id)
    if b is None:
        return None
    zuordnung.entfernen_zu(bewegung_id)
    if beleg_id:
        zuordnung.hinzufuegen(bewegung_id, zuordnung.BELEG, b.get("betrag", 0.0),
                              kategorie=b.get("kategorie", ""), ziel_id=beleg_id)
    return db.holen(TABELLE, bewegung_id)


def belege_von(bewegung):
    """Die Belege, die an dieser Bewegung haengen (kann mehr als einer sein)."""
    return zuordnung.ziele(bewegung["id"], zuordnung.BELEG)


def hat_beleg(bewegung):
    return bool(belege_von(bewegung))


def beleg_nicht_noetig(bewegung_id, noetig=False):
    """Von Hand festhalten, dass es zu dieser Buchung keinen Beleg gibt.

    Ohne diesen Weg bliebe jede Ausnahme fuer immer in der Liste stehen – und
    eine Liste, die man nicht leer bekommt, hoert man auf zu lesen.
    """
    b = db.holen(TABELLE, bewegung_id)
    if b is None:
        return None
    db.speichern(TABELLE, bewegung_id, dict(b, beleg_noetig=bool(noetig)))
    return db.holen(TABELLE, bewegung_id)


def ohne_beleg(von="", bis=""):
    """Bewegungen, die einen Beleg brauchen und keinen haben – die Arbeitsliste.

    Das ist die Frage aus dem Alltag: *welche Belege fehlen noch?* Und spaeter
    das Mass dafuer, ob die Uebergabe ans Steuerbuero vollstaendig ist (AP25).
    """
    return [b for b in alle(von, bis)
            if beleg_erwartet(b) and not hat_beleg(b)]


def importieren(rohdaten, heute=None):
    """Einen Auszug einlesen und ablegen.

    Gibt einen Bericht zurück: was gelesen wurde, was neu ist und was schon da
    war. Die Zahl der Dubletten ist keine Panne, sondern der Normalfall bei
    überlappenden Auszügen – sie gehört trotzdem in die Rückmeldung, damit
    niemand rätselt, warum aus 169 Zeilen 12 neue Sätze wurden.
    """
    konto, art, gelesen = kontoauszug.lesen(rohdaten, heute=heute)
    neu = doppelt = 0
    with db.transaktion():
        for b in gelesen:
            vorhanden = db.holen(TABELLE, b["id"])
            if vorhanden is None:
                db.anlegen(TABELLE, dict(b, erfasst=_jetzt()), sid=b["id"])
                neu += 1
            else:
                # Die Bankfelder auffrischen, die eigenen behalten.
                satz = dict(vorhanden)
                satz.update(b)
                for feld in _EIGENE:
                    if feld in vorhanden:
                        satz[feld] = vorhanden[feld]
                db.speichern(TABELLE, b["id"], satz)
                doppelt += 1
    bericht = kontoauszug.zusammenfassung(gelesen)
    bericht.update({"konto": konto, "art": art, "neu": neu, "doppelt": doppelt,
                    "erkannt": zuordnen()})
    return bericht


def alle(von="", bis="", konto=""):
    """Bewegungen im Zeitraum, neueste zuerst. Leere Grenzen = alles."""
    treffer = [b for b in db.alle(TABELLE)
               if (not von or b.get("datum", "") >= von)
               and (not bis or b.get("datum", "") <= bis)
               and (not konto or b.get("konto") == konto)]
    return sorted(treffer, key=lambda b: (b.get("datum", ""), b.get("erfasst", "")),
                  reverse=True)


def konten():
    """Welche Konten liegen im Bestand – für Filter und Anzeige."""
    return sorted({b.get("konto", "") for b in db.alle(TABELLE) if b.get("konto")})


def zeitraum(konto=""):
    """(erster, letzter) Tag im Bestand – oder ('', '')."""
    tage = sorted(b.get("datum", "") for b in db.alle(TABELLE)
                  if b.get("datum") and (not konto or b.get("konto") == konto))
    return (tage[0], tage[-1]) if tage else ("", "")


def monatssummen(konto=""):
    """Je Monat: Geldfluss und – davon getrennt – das betriebliche Ergebnis.

    **Zwei verschiedene Zahlen, und die Verwechslung ist teuer.**

    * `eingang`/`ausgang` sind der reine **Geldfluss**: was auf dem Konto
      passiert ist. Umbuchungen bleiben draußen (der Kreditkarten-Ausgleich ist
      keine Ausgabe, sonst stünden die Kartenkäufe doppelt).
    * `ergebnis` lässt zusätzlich alles weg, was **keine Betriebsausgabe** ist:
      Privatentnahmen, durchlaufende Posten wie die abgeführte
      Beherbergungssteuer, und Bewegungen der Klasse `Neutral`.

    Über das erste Halbjahr 2026 liegen dazwischen mehr als 8.000 € – wer den
    Geldfluss für das Ergebnis hält, rechnet sich arm.

    `unklar` zählt die Ausgänge, die noch niemand zugeordnet hat. Solange die
    Zahl größer als null ist, ist das Ergebnis eine Näherung, und die Anzeige
    soll das sagen dürfen.
    """
    # Klassen, die nicht ins betriebliche Ergebnis gehören.
    raus = {"Privat/prüfen", "Durchlaufend", "Neutral"}
    summen = {}
    for b in db.alle(TABELLE):
        if b.get("umbuchung") or not b.get("datum"):
            continue
        if konto and b.get("konto") != konto:
            continue
        monat = b["datum"][:7]
        e = summen.setdefault(monat, {"eingang": 0.0, "ausgang": 0.0,
                                      "ergebnis": 0.0, "unklar": 0})
        wert = b.get("betrag", 0.0)
        e["eingang" if wert > 0 else "ausgang"] += wert
        if (b.get("klasse") or "") not in raus:
            e["ergebnis"] += wert
        if wert < 0 and not (b.get("kategorie") or "").strip():
            e["unklar"] += 1
    return {m: {k: (v if k == "unklar" else round(v, 2)) for k, v in w.items()}
            for m, w in sorted(summen.items())}


# Wohin der noch nicht zugeordnete Teil einer Bewegung zaehlt. Er als „ohne
# Kategorie" auszuweisen ist ehrlicher, als ihn wegzulassen: sonst sieht eine
# halb bearbeitete Auswertung vollstaendig aus.
OHNE_KATEGORIE = "— noch ohne Kategorie —"


def je_kategorie(von="", bis="", konto=""):
    """Summe je Kategorie – **ueber die Posten**, nicht ueber die Bewegung (B6).

    Der Unterschied ist der ganze Sinn von B1: eine Zahlung von 100 EUR kann zu
    60 EUR Waescherei und 40 EUR Ausstattung gehoeren. Nach der Bewegung
    gerechnet stuende alles unter einer Kategorie.

    Drei Regeln:

    * Wo **Posten** da sind, zaehlen sie.
    * Wo **keine** da sind, zaehlt die Kategorie der Bewegung – sonst
      verschwaende jede noch nicht aufgeteilte Zahlung aus der Auswertung.
    * Was an einer teilweise aufgeteilten Bewegung **offen** ist, steht unter
      `OHNE_KATEGORIE`. Es der Bewegungskategorie zuzuschlagen waere zu hoch
      gerechnet, es wegzulassen liesse die Auswertung fertig aussehen.
    """
    summen = {}

    def dazu(name, betrag):
        if abs(betrag) < zuordnung.GENAU:
            return
        summen[name] = round(summen.get(name, 0.0) + betrag, 2)

    for b in alle(von, bis, konto):
        if b.get("umbuchung"):
            continue
        p = zuordnung.posten(b["id"])
        if not p:
            dazu((b.get("kategorie") or "").strip() or OHNE_KATEGORIE,
                 round(b.get("betrag", 0.0), 2))
            continue
        for z in p:
            dazu((z.get("kategorie") or "").strip() or OHNE_KATEGORIE, z["betrag"])
        dazu(OHNE_KATEGORIE, zuordnung.rest(b))
    return summen
