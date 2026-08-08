#!/usr/bin/env python3
"""Der Überblick: Ergebnis je Monat, je Kategorie, je Wohnung (B7).

**Wozu er da ist.** Nicht als EÜR fürs Finanzamt – die macht das Steuerbüro.
Der Zweck ist der Blick auf die eigenen Zahlen, weil das Steuerbüro acht bis
zehn Monate hinterherhinkt und es bis dahin ein Blindflug wäre (Ansage vom
8.8.2026). Daraus folgt eine Regel, die überall gilt: **es muss dabeistehen,
wie belastbar eine Zahl gerade ist.** Eine Auswertung, die aussieht wie das
Ergebnis, aber die halbe Buchhaltung nicht kennt, ist schlimmer als keine.

**Gerechnet wird über die Posten, nicht über die Bewegung.** Seit B1 kann eine
Zahlung auf mehrere Kategorien mit verschiedenen Klassen aufgeteilt sein: 400 €
Wäscherei und 600 € Privatentnahme in einer Abbuchung. Nach der Bewegung
gerechnet zählte die ganze Zahlung mit *einer* Klasse – die Aufteilung war
unsichtbar.
"""
from app import buchhaltung, db, konto, zuordnung

# Wohin das gehört, was noch keiner Kategorie zugeordnet ist. Bewusst eine
# eigene Gruppe: unter „Ausgabe" geführt wäre es eine Behauptung.
UNGEKLAERT = "Noch nicht zugeordnet"

# Klassen, die nicht ins betriebliche Ergebnis gehören.
_NICHT_INS_ERGEBNIS = {"Privat/prüfen", "Durchlaufend", "Neutral"}


def _posten_mit_klasse(von="", bis=""):
    """Alle Beträge des Zeitraums als (datum, betrag, kategorie, klasse).

    Wo Posten hängen, zählen sie; wo keine hängen, die Bewegung selbst. Was an
    einer teilweise aufgeteilten Bewegung offen ist, kommt als eigener Eintrag
    ohne Kategorie – sonst wäre die Summe zu niedrig und niemand sähe es.
    """
    raus = []
    for b in konto.alle(von, bis):
        if b.get("umbuchung") or not b.get("datum"):
            continue
        p = zuordnung.posten(b["id"])
        if not p:
            kat = (b.get("kategorie") or "").strip()
            raus.append((b["datum"], round(b.get("betrag", 0.0), 2), kat,
                         _klasse(kat, b)))
            continue
        for z in p:
            kat = (z.get("kategorie") or "").strip()
            raus.append((b["datum"], z["betrag"], kat, _klasse(kat, b)))
        rest = zuordnung.rest(b)
        if abs(rest) >= zuordnung.GENAU:
            raus.append((b["datum"], rest, "", ""))
    return raus


def _klasse(kategorie, bewegung):
    """Die Klasse eines Betrags: aus seiner Kategorie, sonst aus der Bewegung.

    Ohne Kategorie bleibt sie leer – und ein Betrag ohne Klasse zählt **nicht**
    ins Ergebnis. Ihn als Ausgabe zu führen wäre geraten.
    """
    if kategorie:
        return buchhaltung.klasse_fuer(kategorie)
    return ""


def monate(von="", bis=""):
    """Je Monat: Geldfluss und – davon getrennt – das betriebliche Ergebnis.

    * `eingang`/`ausgang`/`geldfluss` – was auf dem Konto passiert ist.
      Umbuchungen bleiben draußen (der Kreditkarten-Ausgleich ist keine
      Ausgabe, sonst stünden die Kartenkäufe doppelt).
    * `ergebnis` – ohne Privatentnahmen, durchlaufende Posten und Neutrales,
      und **ohne alles, was noch keine Kategorie hat**.
    * `offen` – wie viele Ausgänge noch niemand zugeordnet hat.
    * `offen_betrag` / `belastbar` – **wie viel Geld dem Ergebnis noch fehlt.**
      An den echten Zahlen der entscheidende Wert: im Juni 2026 stand ein
      Verlust von 1.489 €, weil die Einnahmen noch nicht zugeordnet waren.
      Ohne diese Zahl daneben liest man den Verlust als Ergebnis.
    """
    summen = {}
    for datum, betrag, _kat, klasse in _posten_mit_klasse(von, bis):
        e = summen.setdefault(datum[:7], {"eingang": 0.0, "ausgang": 0.0,
                                          "ergebnis": 0.0, "offen": 0,
                                          "offen_betrag": 0.0})
        e["eingang" if betrag > 0 else "ausgang"] += betrag
        if klasse and klasse not in _NICHT_INS_ERGEBNIS:
            e["ergebnis"] += betrag
        elif not klasse:
            # Wie viel Geld im Ergebnis noch FEHLT. An den echten Zahlen war
            # das der entscheidende Wert: im Juni standen 1.489 EUR Verlust,
            # weil die Einnahmen noch nicht zugeordnet waren. Ohne diese Zahl
            # daneben liest man den Verlust als Ergebnis.
            e["offen_betrag"] += betrag
    for b in konto.ohne_zuordnung():
        if not b.get("datum"):
            continue
        m = b["datum"][:7]
        if m in summen:
            summen[m]["offen"] += 1
    return {m: {"eingang": round(w["eingang"], 2),
                "ausgang": round(w["ausgang"], 2),
                "geldfluss": round(w["eingang"] + w["ausgang"], 2),
                "ergebnis": round(w["ergebnis"], 2),
                "offen": w["offen"],
                "offen_betrag": round(w["offen_betrag"], 2),
                # Ein Ergebnis, dem noch Geld fehlt, ist keins. Die Anzeige
                # soll es deshalb nicht als Ergebnis ausgeben duerfen.
                "belastbar": abs(w["offen_betrag"]) < 0.005}
            for m, w in sorted(summen.items())}


def kategorien(von="", bis=""):
    """Je Klasse die Kategorien mit ihrer Summe, größte zuerst.

    Die eigentliche Frage aus dem Alltag: *wie viel ging für Putzmittel drauf?*
    Deshalb steht innerhalb einer Klasse das Größte oben.
    """
    je_klasse = {}
    for _datum, betrag, kat, klasse in _posten_mit_klasse(von, bis):
        gruppe = klasse if kat else UNGEKLAERT
        name = kat or konto.OHNE_KATEGORIE
        je_klasse.setdefault(gruppe or UNGEKLAERT, {})
        ziel = je_klasse[gruppe or UNGEKLAERT]
        ziel[name] = round(ziel.get(name, 0.0) + betrag, 2)
    return {klasse: sorted(((k, s) for k, s in werte.items() if abs(s) >= 0.005),
                           key=lambda kv: -abs(kv[1]))
            for klasse, werte in je_klasse.items()
            if any(abs(s) >= 0.005 for s in werte.values())}


def _wohnung_von(posten):
    """Zu welcher Wohnung gehört dieser Posten? '' wenn es sich nicht ergibt.

    Sie steht **nicht** an der Bewegung – die Bank weiß nichts von Wohnungen.
    Ableitbar ist sie nur über das Gegenstück: die Rechnung kennt ihre Wohnung,
    ein Beleg kann eine tragen.
    """
    if posten["art"] == zuordnung.RECHNUNG and posten.get("ziel_id"):
        return (db.holen("rechnungen", posten["ziel_id"]) or {}).get("wohnung") or ""
    if posten["art"] == zuordnung.BELEG and posten.get("ziel_id"):
        return (db.holen("belege", posten["ziel_id"]) or {}).get("apartment_id") or ""
    return ""


def wohnungen(von="", bis=""):
    """Je Wohnung: Einnahmen und Ausgaben – **so weit die Daten es hergeben**.

    Was keiner Wohnung zugeordnet werden kann, taucht hier **nicht** auf. Es
    einer zuzuschlagen wäre erfunden. Wie viel dadurch fehlt, sagt `abdeckung`
    – ohne diese Zahl liest man eine kurze Tabelle als „keine Kosten".
    """
    raus = {}
    for b in konto.alle(von, bis):
        if b.get("umbuchung"):
            continue
        for z in zuordnung.posten(b["id"]):
            w = _wohnung_von(z)
            if not w:
                continue
            e = raus.setdefault(w, {"einnahmen": 0.0, "ausgaben": 0.0})
            e["einnahmen" if z["betrag"] > 0 else "ausgaben"] += z["betrag"]
    return {w: {k: round(v, 2) for k, v in e.items()} for w, e in raus.items()}


def abdeckung(von="", bis=""):
    """Wie viele Posten tragen überhaupt eine Wohnung?

    **Der wichtigste Teil von B7c.** Am Bestand vom 8.8.2026 trug **kein
    einziger** der 30 Belege eine Wohnung; die Tabelle wäre leer gewesen und
    hätte ausgesehen wie „diese Wohnung kostet nichts".
    """
    gesamt = mit = 0
    for b in konto.alle(von, bis):
        if b.get("umbuchung"):
            continue
        for z in zuordnung.posten(b["id"]):
            gesamt += 1
            mit += 1 if _wohnung_von(z) else 0
    return {"posten": gesamt, "mit_wohnung": mit,
            "anteil": round(mit / gesamt, 3) if gesamt else 0.0}
