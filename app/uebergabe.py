#!/usr/bin/env python3
"""Die Übergabe ans Steuerbüro (B9).

Das Ziel aus dem Betrieb: *am Ende muss der Steuerberater alle Belege
bekommen. Sammeln will ich alles über das Tool, speichern dann in Nextcloud.*

**Das Journal kommt aus den Bewegungen, nicht aus den Belegen.** Bis B9 baute
`buchhaltung.journal_zeile` das Kontenjournal aus den hochgeladenen Belegen.
Das war richtig, solange Belege die einzige Quelle waren. Seit B1 ist die
Buchhaltung die **Bewegung mit ihren Posten**: ein Journal aus Belegen kennt
die Ausgaben ohne Beleg nicht (am Bestand 45 von 224) und keine Aufteilung. Es
gäbe dem Steuerbüro ein unvollständiges Bild, das vollständig aussieht.

**Was fehlt, steht drin – als Vermerk, nicht als Lücke.** Eine Zeile ohne
Kategorie oder ohne Beleg sagt das in der Spalte „Hinweis". Eine weggelassene
Zeile fiele niemandem auf; eine mit Vermerk führt zur Rückfrage, und genau die
soll sie auslösen.
"""
import csv
import io
import os
import re
import zipfile
from datetime import date

from app import buchhaltung, db, housekeeping, konto, receipts, zuordnung

SPALTEN = ["Datum", "Konto", "Gegenpartei", "Verwendungszweck", "Betrag",
           "Klasse", "Kategorie", "Beleg", "Hinweis"]


# ------------------------------------------------------------- Die Belegnummer
def _jahr(beleg):
    return (buchhaltung.belegdatum(beleg) or "")[:4] or str(date.today().year)


def nummer_vergeben(beleg_id):
    """Dem Beleg seine laufende Nummer geben – einmal und für immer.

    **Sie ist die Klammer zwischen Buchung und Papier.** Im Journal steht sie
    in der Spalte „Beleg", im Übergabepaket im Dateinamen. Wandert sie, findet
    das Steuerbüro nichts mehr wieder – deshalb wird eine vorhandene Nummer nie
    neu vergeben.
    """
    beleg = db.holen(receipts.TABELLE, beleg_id)
    if beleg is None:
        return ""
    if (beleg.get("nummer") or "").strip():
        return beleg["nummer"]
    jahr = _jahr(beleg)
    hoechste = 0
    for r in db.alle(receipts.TABELLE):
        m = re.match(rf"^{jahr}-(\d+)$", (r.get("nummer") or "").strip())
        if m:
            hoechste = max(hoechste, int(m.group(1)))
    nummer = f"{jahr}-{hoechste + 1:04d}"
    db.speichern(receipts.TABELLE, beleg_id, dict(beleg, nummer=nummer))
    return nummer


def nummern_nachtragen():
    """Allen Belegen ohne Nummer eine geben – **nach Belegdatum**.

    Damit die Reihenfolge der Nummern der Reihenfolge der Belege folgt und
    nicht der des Hochladens. Gibt die Anzahl der vergebenen Nummern zurück.
    """
    offen = [r for r in db.alle(receipts.TABELLE)
             if not (r.get("nummer") or "").strip()]
    for r in sorted(offen, key=buchhaltung.belegdatum):
        nummer_vergeben(r["id"])
    return len(offen)


def _beleg_nummer(beleg_id):
    return ((db.holen(receipts.TABELLE, beleg_id) or {}).get("nummer") or "").strip()


# ------------------------------------------------------------------ Das Journal
def _zeile(bewegung, betrag, kategorie, beleg_id="", zweck=""):
    klasse = (buchhaltung.klasse_fuer(kategorie) if kategorie
              else ("Neutral" if bewegung.get("umbuchung") else ""))
    nummer = _beleg_nummer(beleg_id) if beleg_id else ""
    hinweise = []
    if bewegung.get("umbuchung"):
        hinweise.append("Umbuchung zwischen eigenen Konten – neutral")
    else:
        if not kategorie:
            hinweise.append("ohne Kategorie")
        if not nummer and betrag < 0:
            hinweise.append("Beleg fehlt")
    return {"Datum": (bewegung.get("datum") or "")[:10],
            "Konto": bewegung.get("konto", ""),
            "Gegenpartei": bewegung.get("gegenpartei", ""),
            "Verwendungszweck": zweck or bewegung.get("text", ""),
            "Betrag": buchhaltung.betrag_text(round(betrag, 2)),
            "Klasse": klasse,
            "Kategorie": kategorie,
            "Beleg": nummer,
            "Hinweis": " · ".join(hinweise)}


def journal(von="", bis=""):
    """Das Kontenjournal: **eine Zeile je Posten**, nicht je Beleg.

    Eine Zahlung von 100 € auf Putzmittel (60) und Gastgeschenke (40) ergibt
    zwei Zeilen. Eine Bewegung ohne Posten kommt mit ihrer eigenen Kategorie –
    sonst fehlten alle Zahlungen, die nur erkannt wurden. Und eine Bewegung
    ohne alles steht mit Vermerk drin, statt zu fehlen.
    """
    raus = []
    for b in konto.alle(von, bis):
        p = zuordnung.posten(b["id"])
        if not p:
            raus.append(_zeile(b, b.get("betrag", 0.0),
                               (b.get("kategorie") or "").strip()))
            continue
        for z in p:
            raus.append(_zeile(b, z["betrag"], (z.get("kategorie") or "").strip(),
                               beleg_id=z.get("ziel_id") if z["art"] == zuordnung.BELEG
                               else "", zweck=z.get("notiz", "")))
        rest = zuordnung.rest(b)
        if abs(rest) >= zuordnung.GENAU:
            raus.append(dict(_zeile(b, rest, ""),
                             Hinweis="Restbetrag – noch nicht zugeordnet"))
    return sorted(raus, key=lambda x: (x["Datum"], x["Konto"]))


def journal_csv(von="", bis=""):
    """Das Journal als CSV – Semikolon, utf-8 mit BOM, deutsche Beträge.

    Genau die Form, die Excel und die Kanzleisoftware ohne Nachfrage lesen;
    ohne BOM zerlegt Excel die Umlaute.
    """
    puffer = io.StringIO()
    schreiber = csv.DictWriter(puffer, fieldnames=SPALTEN, delimiter=";",
                               lineterminator="\r\n")
    schreiber.writeheader()
    for zeile in journal(von, bis):
        schreiber.writerow(zeile)
    return puffer.getvalue().encode("utf-8-sig")


# --------------------------------------------------------------- Das Deckblatt
def deckblatt(von="", bis=""):
    """Was das Steuerbüro über diesen Stapel wissen muss – **auch das Fehlende**.

    Ohne dieses Blatt liest man einen Zwischenstand als Abschluss. Es nennt
    Zeitraum und Konten, die Zahl der Bewegungen und Belege, und was offen ist.
    """
    from app import vollstaendigkeit
    bewegungen = konto.alle(von, bis)
    tage = sorted(b.get("datum", "") for b in bewegungen if b.get("datum"))
    konten = sorted({b.get("konto", "") for b in bewegungen if b.get("konto")})
    offen = vollstaendigkeit.offene_arbeiten()
    belege = receipts.list_receipts(100000)
    # Ohne Belegdatum liegt ein Beleg im Monat seines Uploads – die Ablage nach
    # Jahr und Monat waere dann irrefuehrend. Also sagen, wie viele das sind.
    ohne_datum = sum(1 for r in belege if not (r.get("datum") or "").strip())
    zeilen = [
        "Übergabe an das Steuerbüro",
        "",
        f"Erstellt am {date.today().isoformat()}",
        f"Zeitraum {tage[0] if tage else '—'} bis {tage[-1] if tage else '—'}",
        f"Konten: {', '.join(konten) or '—'}",
        "",
        f"{len(bewegungen)} Bankbewegungen",
        f"{len(belege)} Belege"
        + (f", davon {ohne_datum} ohne gepflegtes Belegdatum"
           if ohne_datum else ""),
        f"{len(journal(von, bis))} Journalzeilen",
        "",
        "Was noch offen ist:",
        f"  {offen['ohne_kategorie']} Ausgaben ohne Kategorie",
        f"  {offen['ohne_beleg']} Buchungen ohne Beleg",
        f"  {offen['rest']} Bewegungen mit offenem Restbetrag",
        f"  {offen['automatisch']} Kategorien automatisch erkannt, nicht bestätigt",
        "",
        "Die Zeilen des Journals tragen diese Angaben in der Spalte „Hinweis“.",
        "Umbuchungen zwischen eigenen Konten stehen als neutral darin – sie",
        "sind keine Ausgabe, werden aber gebraucht, damit der Kontostand aufgeht.",
    ]
    for s in vollstaendigkeit.saldospruenge():
        zeilen.append(f"  Saldosprung {s['konto']} {s['von']}–{s['bis']}: "
                      f"{s['differenz']:+.2f} €")
    for l in vollstaendigkeit.luecken():
        zeilen.append(f"  Kein Auszug für {l['konto']} {l['von']}–{l['bis']}")
    return "\n".join(zeilen)


# ------------------------------------------------------------ Das Übergabepaket
def _dateiname(beleg, endung):
    """`0007_2026-03-14_Rossmann_27,81.pdf` – sprechend und sortierbar."""
    nummer = (beleg.get("nummer") or "").split("-")[-1] or "0000"
    haendler = re.sub(r"[^\wäöüÄÖÜß -]", "", (beleg.get("merchant") or "")).strip()
    betrag = (beleg.get("amount") or "").strip().replace(".", "")
    teile = [nummer, buchhaltung.belegdatum(beleg), haendler or "ohne Händler"]
    if betrag:
        teile.append(betrag)
    return "_".join(teile).replace("/", "-") + "." + endung


def paket(von="", bis=""):
    """Alles in einer ZIP: Belege nach Jahr und Monat, Journal, Deckblatt.

    **Belege ohne Bewegung kommen mit.** Sie gehören dem Steuerbüro, auch wenn
    hier noch niemand sie zugeordnet hat – sie wegzulassen hieße, sie zu
    unterschlagen.

    Kein automatisches Hochladen in die Nextcloud: der Beleg-Ordner wird
    ohnehin gespiegelt, und ein zweiter Weg dorthin wäre ein zweiter
    Mechanismus für dieselbe Frage.
    """
    nummern_nachtragen()
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Deckblatt.txt", deckblatt(von, bis))
        zf.writestr("Kontenjournal.csv", journal_csv(von, bis))
        for r in receipts.list_receipts(100000):
            tag = buchhaltung.belegdatum(r)
            if von and tag < von or bis and tag > bis:
                continue
            rel = r.get("pdf") or r.get("photo")
            if not rel:
                continue
            quelle = os.path.join(housekeeping.MEDIA_DIR, rel)
            if not os.path.exists(quelle):
                continue
            endung = rel.rsplit(".", 1)[-1] if "." in rel else "jpg"
            # Ein Beleg ohne gepflegtes Datum gehoert NICHT in den Monat seines
            # Uploads – dort saehe er aus, als sei er dort entstanden. Er kommt
            # in einen eigenen Ordner, wo er auffaellt.
            ordner = (f"{tag[:4]}/{tag[5:7]}" if (r.get("datum") or "").strip()
                      else "_ohne Belegdatum")
            with open(quelle, "rb") as f:
                zf.writestr(f"{ordner}/{_dateiname(r, endung)}", f.read())
    return puffer.getvalue()
