#!/usr/bin/env python3
"""Belege und Bankbewegungen zusammenbringen (B5).

**Warum es das braucht.** Belege und Konto liefen bisher nebeneinander: was
jemand mit dem Handy fotografiert, bleibt für die Buchhaltung unsichtbar, und
derselbe Beleg kann über beide Wege zweimal im Werkzeug landen.

**Am Bestand nachgemessen (8.8.2026), bevor gebaut wurde:** 4 Belege, davon
einer mit Betrag und keiner mit gepflegtem Belegdatum. Dieser eine Betrag
(9,44 €) trifft **null** der 128 Ausgaben-Bewegungen. Ein Abgleich über den
Betrag trägt hier also nicht – derselbe Befund wie bei den Zahlungseingängen
in B3.

Deshalb: **Vorschläge, keine Automatik.** Sortiert wird nach

1. **Händlername** – „ALDI" im Beleg, „ALDI SAGT DANKE 1234" auf dem Auszug,
2. **gleicher Betrag** – wenn einer da ist; ein Zusatzhinweis, kein Schlüssel,
3. **Datumsnähe** – der Beleg vom 12. gehört eher zur Abbuchung vom 13.

Ein fehlender Betrag schließt **nichts** aus. Drei von vier echten Belegen
tragen keinen; eine Regel, die sie aussortiert, schlägt nichts mehr vor – der
Fehler, der in B3 schon einmal null Kandidaten erzeugt hat.

**Ein Beleg darf an mehreren Bewegungen hängen** (B5b). Der Provisionsbeleg von
Booking kommt monatlich, die Auszahlungen kommen einzeln – 44 im Halbjahr. Ohne
diese Richtung ließe sich der Monatsbeleg gar nicht verbuchen.
"""
from app import buchhaltung, db, konto, receipts, zuordnung

# Wie nah zwei Daten liegen müssen, damit von einer Dublette die Rede ist.
# Ein Beleg wird oft erst Tage später fotografiert; drei Tage sind großzügig
# genug für den Alltag und eng genug, dass nicht der halbe Monat verdächtig ist.
DUBLETTE_TAGE = 3

# Bis hierhin gilt ein Beleg als „nah genug" an einer Bewegung, um überhaupt
# vorgeschlagen zu werden. Danach steht er weiter unten, verschwindet aber
# nicht – Ausschluss über das Datum war in B3 schon einmal falsch.
NAH_TAGE = 14


def _tag(text):
    from datetime import date
    try:
        j, m, t = str(text)[:10].split("-")
        return date(int(j), int(m), int(t))
    except (ValueError, AttributeError):
        return None


def _abstand(a, b):
    ta, tb = _tag(a), _tag(b)
    return abs((ta - tb).days) if (ta and tb) else 10 ** 5


def _wortstuecke(text):
    """Wortstücke, die einen Händler benennen könnten – klein, ohne Zahlen."""
    import re
    return {w.lower() for w in re.split(r"[^A-Za-zÄÖÜäöüß]+", text or "")
            if len(w) > 3}


def _haendler_passt(beleg, bewegung):
    """Steht der Händler des Belegs im Text der Bewegung – oder umgekehrt?

    Auf dem Auszug steht „ALDI SAGT DANKE 1234", am Beleg „ALDI". Verglichen
    werden deshalb Wortstücke, nicht ganze Zeichenketten.
    """
    beleg_worte = _wortstuecke(beleg.get("merchant"))
    if not beleg_worte:
        return False
    bew_worte = _wortstuecke((bewegung.get("gegenpartei") or "") + " "
                             + (bewegung.get("text") or ""))
    return bool(beleg_worte & bew_worte)


def _betrag_passt(beleg, bewegung):
    b = buchhaltung.betrag_zahl(beleg.get("amount"))
    if b is None:
        return False
    return abs(abs(bewegung.get("betrag", 0.0)) - abs(b)) < 0.005


def ist_zugeordnet(beleg_id):
    return bool(zuordnung.bewegungen_zu(zuordnung.BELEG, beleg_id))


def ohne_bewegung(limit=500):
    """Belege, die an keiner Bewegung hängen – die Arbeitsliste von der
    Beleg-Seite aus. Das Gegenstück zu `konto.ohne_beleg`."""
    return [r for r in receipts.list_receipts(limit) if not ist_zugeordnet(r["id"])]


def _bewertung(beleg, bewegung):
    """(Sortierschlüssel, Grund) für ein Paar aus Beleg und Bewegung.

    Der Grund gehört zum Vorschlag: einer, den man nicht nachvollziehen kann,
    wird entweder blind übernommen oder ignoriert.
    """
    haendler = _haendler_passt(beleg, bewegung)
    betrag = _betrag_passt(beleg, bewegung)
    tage = _abstand(buchhaltung.belegdatum(beleg), bewegung.get("datum"))
    grund = ("Händler passt" if haendler else
             "Betrag stimmt" if betrag else
             "gleiche Woche" if tage <= 7 else "offen")
    return (not haendler, not betrag, tage), grund


def belege_zu(bewegung, limit=500):
    """Belege, die zu dieser Bewegung gehören könnten – bester zuerst.

    Nur für **Ausgaben**: zu einer Auszahlung von Booking gibt es keinen
    Lieferantenbeleg, und ein Vorschlag an dieser Stelle wäre nur Rauschen.
    """
    # Eine Umbuchung braucht keine Zuordnung, darf aber ein Dokument tragen –
    # die Kreditkartenabrechnung gehoert an ihre Sammelbuchung.
    if bewegung.get("betrag", 0.0) >= 0:
        return []
    raus = []
    for r in ohne_bewegung(limit):
        schluessel, grund = _bewertung(r, bewegung)
        raus.append({"beleg": r, "grund": grund, "_s": schluessel})
    raus.sort(key=lambda x: x["_s"])
    return [{k: v for k, v in x.items() if k != "_s"} for x in raus]


def bewegungen_zu(beleg, von="", bis=""):
    """Der umgekehrte Weg: welche Bewegung passt zu diesem Beleg?

    Die Richtung aus dem Alltag – jemand fotografiert eine Quittung, die
    Abbuchung steht längst im Auszug.
    """
    raus = []
    for b in konto.alle(von, bis):
        if b.get("betrag", 0.0) >= 0 or b.get("umbuchung"):
            continue
        schluessel, grund = _bewertung(beleg, b)
        raus.append({"bewegung": b, "grund": grund, "_s": schluessel})
    raus.sort(key=lambda x: x["_s"])
    return [{k: v for k, v in x.items() if k != "_s"} for x in raus]


def posten_von(beleg_id):
    """Alle Posten, die auf diesen Beleg zeigen – über alle Bewegungen hinweg."""
    return [z for z in db.finden(zuordnung.TABELLE, zart=zuordnung.BELEG,
                                 ziel=str(beleg_id))]


def belegprobe(beleg):
    """Deckt sich, was verteilt wurde, mit dem Betrag auf dem Beleg? (B5b)

    Für den Monatsbeleg einer Plattform die eigentliche Kontrolle: der Beleg
    über 265,87 € muss sich lückenlos auf die Auszahlungen des Monats
    verteilen. Fehlt eine, bleibt ein Rest stehen.

    Gibt (verteilt, beleg, stimmt) zurück. Ohne Betrag am Beleg gibt es nichts
    zu prüfen – dann sind `beleg` und `stimmt` None, statt eine Abweichung zu
    behaupten, die nur eine fehlende Angabe ist.
    """
    verteilt = round(sum(z.get("betrag", 0.0) for z in posten_von(beleg["id"])), 2)
    wert = buchhaltung.betrag_zahl(beleg.get("amount"))
    if wert is None:
        return verteilt, None, None
    # Ein Lieferantenbeleg mindert – das Vorzeichen des Belegs ist beliebig
    # getippt, das der Posten ist es nicht.
    soll = -abs(round(wert, 2))
    return verteilt, soll, abs(verteilt - soll) < 0.02


def dubletten(beleg, limit=500):
    """Andere Belege, die derselbe sein könnten – **Warnung, kein Verbot**.

    **Baut auf `buchhaltung.dubletten` auf**, das den Monatsabschluss schon
    prüft: gleicher Tag, gleicher Händler, gleicher Betrag. Zwei Mechanismen
    für dieselbe Frage würden mit der Zeit auseinanderlaufen und
    Widersprüchliches melden.

    Der Unterschied zum Abschluss ist nur der **Zeitpunkt**: hier wird ein
    einzelner, gerade entstandener Beleg gegen den Bestand gehalten – im
    Moment des Hochladens, wo die Rückfrage noch etwas nützt. Und das
    Datumsfenster ist etwas weiter: dieselbe Quittung wird über beide Wege
    selten am selben Tag erfasst.

    **Ohne Betrag wird nichts behauptet.** Zwei Belege ohne Betrag sehen immer
    gleich aus; eine Warnung, die ständig kommt, wird weggeklickt – und fehlt
    dann im echten Fall. Beim Händler ist es umgekehrt als im Abschluss: er
    wird oft gar nicht getippt, deshalb genügen Betrag und Tag für eine
    Rückfrage.

    Zwei Tankquittungen desselben Tages über denselben Betrag gibt es wirklich
    – deshalb gemeldet, nicht verhindert.
    """
    wert = buchhaltung.betrag_zahl(beleg.get("amount"))
    if wert is None:
        return []
    tag = buchhaltung.belegdatum(beleg)
    return [r for r in receipts.list_receipts(limit)
            if r["id"] != beleg["id"]
            and buchhaltung.betrag_zahl(r.get("amount")) == wert
            and _abstand(buchhaltung.belegdatum(r), tag) <= DUBLETTE_TAGE]



def teilweise_verteilt(limit=500):
    """Belege, die schon irgendwo hängen, aber noch nicht ganz verteilt sind (B5b).

    Der Monatsbeleg von Booking über 265,87 € hängt nach der ersten Auszahlung
    mit 145,87 € fest – die restlichen 120,00 € gehören an die zweite. Ohne
    diese Liste wäre er nach dem ersten Klick nicht mehr auswählbar und ein
    Monatsbeleg ließe sich gar nicht verteilen.

    **Ohne Betrag gilt ein Beleg als erledigt.** Sonst stünde jeder zugeordnete
    Beleg ohne Betragsangabe für immer in dieser Liste.
    """
    raus = []
    for r in receipts.list_receipts(limit):
        verteilt, soll, stimmt = belegprobe(r)
        if soll is None or stimmt or abs(verteilt) < 0.005:
            continue
        raus.append(r)
    return raus


def filtern(kandidaten, suche, feld="bewegung"):
    """Vorschläge auf einen Suchbegriff einengen.

    **Warum Suche statt Deckel.** Die Kandidatenliste umfasst alle Ausgaben –
    an den echten Daten 122. Die ersten acht zu zeigen war bequem, aber falsch:
    wer weiß, zu welcher Abbuchung sein Beleg gehört, fand sie nicht, weil sie
    auf Platz 40 stand. Sortierung ist eine Hilfe, kein Ersatz für Suchen.

    Gesucht wird in allem, was auf dem Auszug steht: Empfänger,
    Verwendungszweck, Datum und Betrag. Mehrere Wörter müssen **alle**
    vorkommen – so lässt sich „drewag juli" eingeben.
    """
    worte = [w for w in str(suche or "").lower().split() if w]
    if not worte:
        return list(kandidaten)
    raus = []
    for k in kandidaten:
        satz = k[feld] if isinstance(k, dict) and feld in k else k
        heu = " ".join([
            str(satz.get("gegenpartei") or ""), str(satz.get("text") or ""),
            str(satz.get("merchant") or ""), str(satz.get("datum") or ""),
            # Beträge in beiden Schreibweisen, damit „27,81" und „27.81" gehen.
            f"{satz.get('betrag', satz.get('amount', ''))}".replace(".", ","),
            f"{satz.get('betrag', satz.get('amount', ''))}",
        ]).lower()
        if all(w in heu for w in worte):
            raus.append(k)
    return raus
