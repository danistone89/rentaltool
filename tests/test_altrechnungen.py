"""B10: die Rechnungen aus dem alten Weg übernehmen.

Bis einschließlich der Buchung *Alexander Josan* (Nr. 78) sind die Rechnungen
über Smoobu erzeugt und verschickt. Ohne Übernahme fehlten dem Werkzeug 78
Rechnungen – und damit die halbe Einnahmenseite, an der die Zahlungseingänge
hängen (B3).

**Die PDFs sind die Quelle, nicht das Workbook**: das Rechnungsausgangsbuch
deckt nur Nr. 1–59 ab, die PDFs alle 78.

**Nachgemessen am echten Bestand (8.8.2026):** alle 78 vollständig gelesen,
gegen die 59 Workbook-Zeilen geprüft. Die Abweichungen waren keine Lesefehler,
sondern **zwei verschiedene Begriffe von „Brutto"**: das Workbook führt ihn
*ohne* Übernachtungssteuer, die PDF *mit*. Unter dieser Annahme stimmen 58 von
59; die Reste sind Cent-Differenzen zwischen Dokument und Workbook, bei denen
das Dokument gilt – der Gast hat es bekommen.
"""
import os

from app import altrechnungen as alt, rechnung

# Nachgebaut nach dem echten Dokument Nr. 78 (Alexander Josan). Der Text steht
# in dieser Reihenfolge in der PDF – Werte in eigenen Zeilen nach ihrer
# Beschriftung.
TEXT = """Rechnung
78
Ausstellungsdatum
31.07.2026
Vermieter/in
DS Apartments & Suites - Daniel
Rechnungsempfänger
Alexander Josan
1
Cottaer Straße, 28.07.26 - 31.07.26, 2 Erwachsene
1
358,66 €
7%
358,66 €
2
Reinigungsgebühr
1
75,00 €
7%
75,00 €
3
Übernachtungssteuer
1
26,02 €
0%
26,02 €
Steuer
Basis
Satz
Betrag
USt
405,29 €
7%
28,37 €
Summe
459,68 €
Inklusive USt
28,37 €
Gesamt
431,31 €
Gesamt zu zahlen
459,68 €
"""


def _pdf(tmp_path, nummer=78, gast="Alexander_Josan", text=TEXT):
    """Eine Datei mit dem Namensschema des alten Werkzeugs."""
    p = tmp_path / f"DS_Apartments_-_Rechnungen_{nummer}_{gast}.pdf"
    p.write_bytes(b"%PDF-1.4")
    return str(p)


def _lesen(pfad, text, monkeypatch):
    from app import receipts
    monkeypatch.setattr(receipts, "text_aus_pdf", lambda *a, **k: text)
    return alt.lesen(pfad)


# ------------------------------------------------------------- Das Lesen
def test_die_eckdaten_kommen_aus_der_pdf(tmp_path, monkeypatch):
    s = _lesen(_pdf(tmp_path), TEXT, monkeypatch)
    assert s["nummer"] == "78" and s["gast"] == "Alexander Josan"
    assert s["datum"] == "2026-07-31"
    assert s["wohnung_name"] == "Cottaer Straße"
    assert s["anreise"] == "2026-07-28" and s["abreise"] == "2026-07-31"


def test_die_summen_stimmen_mit_dem_dokument():
    """Genau die Zahlen, die auf Nr. 78 stehen."""
    s = alt._summen([z.strip() for z in TEXT.splitlines()])
    assert s["brutto"] == 459.68          # „Gesamt zu zahlen"
    assert s["ust"] == 28.37
    assert s["durchlaufend"] == 26.02     # Übernachtungssteuer
    assert s["netto"] == 405.29


def test_gesamt_zu_zahlen_schlaegt_summe_und_gesamt():
    """Auf diesen Dokumenten stehen alle drei – „Summe" 459,68, „Gesamt"
    431,31 und „Gesamt zu zahlen" 459,68. Nur die letzte ist das, was der Gast
    gezahlt hat."""
    s = alt._summen([z.strip() for z in TEXT.splitlines()])
    assert s["brutto"] != 431.31


def test_brutto_enthaelt_die_uebernachtungssteuer():
    """Die Konvention dieses Werkzeugs (`rechnung.summen`) – anders als im
    Workbook, das sie herausrechnet. Beide Zahlen sind richtig, sie meinen
    Verschiedenes."""
    s = alt._summen([z.strip() for z in TEXT.splitlines()])
    assert round(s["netto"] + s["ust"] + s["durchlaufend"], 2) == s["brutto"]


def test_eine_rechnung_ohne_uebernachtungssteuer():
    text = TEXT.replace("3\nÜbernachtungssteuer\n1\n26,02 €\n0%\n26,02 €\n", "")
    text = text.replace("459,68 €", "433,66 €")
    s = alt._summen([z.strip() for z in text.splitlines()])
    assert s["durchlaufend"] == 0.0 and s["brutto"] == 433.66


def test_eine_fremde_datei_wird_uebergangen(tmp_path, monkeypatch):
    p = tmp_path / "Irgendwas.pdf"
    p.write_bytes(b"%PDF")
    assert _lesen(str(p), TEXT, monkeypatch) is None


def test_eine_leere_pdf_wird_uebergangen(tmp_path, monkeypatch):
    """Lieber überspringen als einen Satz mit Nullen anlegen – der sähe später
    aus wie eine Rechnung über 0,00 €."""
    assert _lesen(_pdf(tmp_path), "", monkeypatch) is None


# ------------------------------------------------------------- Das Einlesen
def test_der_ordner_wird_nach_nummer_sortiert(tmp_path, monkeypatch):
    from app import receipts
    _pdf(tmp_path, 9, "Anna_Neun")
    _pdf(tmp_path, 10, "Bert_Zehn")
    monkeypatch.setattr(receipts, "text_aus_pdf", lambda *a, **k: TEXT)
    assert [s["nummer"] for s in alt.einlesen(str(tmp_path))] == ["9", "10"]


def test_der_schnitt_bei_josan_haelt(tmp_path, monkeypatch):
    """Ab Nr. 79 gehört alles dem neuen Weg – es darf nicht mit übernommen
    werden, sonst stünde dieselbe Rechnung zweimal im Werkzeug."""
    from app import receipts
    _pdf(tmp_path, 78, "Alexander_Josan")
    _pdf(tmp_path, 79, "Neue_Buchung")
    monkeypatch.setattr(receipts, "text_aus_pdf", lambda *a, **k: TEXT)
    assert [s["nummer"] for s in alt.einlesen(str(tmp_path), 78)] == ["78"]


# ----------------------------------------------------------- Die Übernahme
def _satz(nummer="78", gast="Alexander Josan", pfad=""):
    return {"nummer": nummer, "gast": gast, "datum": "2026-07-31",
            "wohnung_name": "Cottaer Straße", "anreise": "2026-07-28",
            "abreise": "2026-07-31",
            "summen": {"brutto": 459.68, "ust": 28.37, "netto": 405.29,
                       "durchlaufend": 26.02},
            "datei": pfad}


def test_die_uebernahme_legt_eine_gesendete_rechnung_an(tmp_path):
    neu, _u = alt.uebernehmen([_satz(pfad=_pdf(tmp_path))])
    assert neu == 1
    r = [x for x in rechnung.rechnungen() if x["nummer"] == "78"][0]
    # „gesendet", nicht „festgeschrieben": Festschreiben ist ein Vorgang DIESES
    # Werkzeugs, und ihn nachträglich zu behaupten wäre eine Aussage über
    # etwas, das hier nie stattgefunden hat.
    assert r["status"] == rechnung.GESENDET
    assert r["quelle"] == "smoobu" and r["gast"] == "Alexander Josan"


def test_ein_zweiter_lauf_legt_nichts_doppelt_an(tmp_path):
    saetze = [_satz(pfad=_pdf(tmp_path))]
    alt.uebernehmen(saetze)
    neu, uebersprungen = alt.uebernehmen(saetze)
    assert (neu, uebersprungen) == (0, 1)


def test_die_original_pdf_wird_mitgenommen(tmp_path):
    """Der Gast hat ein bestimmtes Dokument bekommen. Eines neu zu bauen wäre
    ein zweiter Beleg zum selben Vorgang."""
    alt.uebernehmen([_satz(pfad=_pdf(tmp_path))])
    r = [x for x in rechnung.rechnungen() if x["nummer"] == "78"][0]
    assert alt.ist_uebernommen(r)
    assert os.path.exists(alt.original_pfad(r))


def test_die_wohnung_wird_ueber_den_namen_zugeordnet(tmp_path):
    alt.uebernehmen([_satz(pfad=_pdf(tmp_path))],
                    wohnungen={"a1": "Cottaer Straße 1", "a2": "Wernerstraße 34c"})
    r = [x for x in rechnung.rechnungen() if x["nummer"] == "78"][0]
    assert r["wohnung"] == "a1"


def test_ohne_passende_wohnung_bleibt_das_feld_leer(tmp_path):
    alt.uebernehmen([_satz(pfad=_pdf(tmp_path))], wohnungen={"a2": "Wernerstraße"})
    r = [x for x in rechnung.rechnungen() if x["nummer"] == "78"][0]
    assert r["wohnung"] == ""


# ------------------------------------------------------- Der Nummernkreis
def test_die_alten_nummern_stoeren_den_neuen_kreis_nicht(tmp_path):
    """Sie tragen „78", der neue Kreis „2026-0079" – zwei Formate, kein
    Zusammenstoß."""
    alt.uebernehmen([_satz(pfad=_pdf(tmp_path))])
    cfg = {"rechnung_startjahr": "2026", "rechnung_startnummer": 79}
    assert rechnung.naechste_nummer(2026, cfg) == "2026-0079"


def test_ohne_startnummer_begaenne_das_werkzeug_bei_eins(tmp_path):
    """Deshalb MUSS die Startnummer gesetzt werden – sonst gäbe es Nr. 1
    zweimal, einmal von Smoobu und einmal von hier."""
    alt.uebernehmen([_satz(nummer="1", gast="Darius Drevinskas",
                           pfad=_pdf(tmp_path, 1, "Darius_Drevinskas"))])
    assert rechnung.naechste_nummer(2026, {}) == "2026-0001"


# ------------------------------------------------------- Für die Zuordnung
def test_uebernommene_rechnungen_stehen_zur_zuordnung_bereit(tmp_path):
    """Der eigentliche Zweck: die Zahlungseingänge hängen an ihnen (B3)."""
    from app import zahlungsvorschlag as vs
    alt.uebernehmen([_satz(pfad=_pdf(tmp_path))])
    assert [r["nummer"] for r in vs.offene()] == ["78"]


def test_die_beschriftung_wird_genau_genommen():
    """Schärfer als der Test oben: hier steht „Gesamt" NACH „Gesamt zu
    zahlen". Ein Vergleich, der nur mit „gesamt" beginnt, nähme den falschen
    Wert – im echten Dokument rettet ihn nur die Reihenfolge."""
    text = ("Gesamt zu zahlen\n459,68 €\nInklusive USt\n28,37 €\n"
            "Übernachtungssteuer\n1\n26,02 €\nGesamt\n431,31 €\n")
    s = alt._summen([z.strip() for z in text.splitlines()])
    assert s["brutto"] == 459.68


def test_ohne_gesamt_zu_zahlen_gilt_die_summe():
    """Ältere Dokumente führen nur „Summe"."""
    text = "Summe\n433,66 €\nInklusive USt\n28,37 €\n"
    assert alt._summen([z.strip() for z in text.splitlines()])["brutto"] == 433.66


def test_fuer_eine_uebernommene_rechnung_wird_kein_pdf_gebaut(tmp_path, monkeypatch):
    """Sonst bekaeme derselbe Vorgang zwei verschiedene Dokumente unter einer
    Nummer. Gebaut wird nur, was hier entstanden ist."""
    from app import rechnung_pdf
    from app.ui import rechnungen as ui_r
    gebaut = []
    monkeypatch.setattr(rechnung_pdf, "bauen",
                        lambda *a, **k: gebaut.append(1) or b"%PDF")
    geladen = []
    from nicegui import ui
    monkeypatch.setattr(ui.download, "content",
                        lambda daten, name, **k: geladen.append(name))
    alt.uebernehmen([_satz(pfad=_pdf(tmp_path))])
    r = [x for x in rechnung.rechnungen() if x["nummer"] == "78"][0]
    ui_r._pdf_laden(r)
    assert gebaut == [] and geladen == ["Rechnung_78.pdf"]


def test_umlaute_aus_dem_dateinamen_werden_zusammengesetzt(tmp_path, monkeypatch):
    """macOS legt Dateinamen in ZERLEGTER Unicode-Form ab („Ju"+"¨"). So
    gelesen sieht der Name richtig aus, vergleicht sich aber mit keinem
    anderen – beim Abgleich gegen die vorhandenen Rechnungen fielen dadurch
    ALLE Umlaut-Namen durch."""
    import unicodedata
    zerlegt = unicodedata.normalize("NFD", "Jürgen_Ollmann")
    s = _lesen(_pdf(tmp_path, 35, zerlegt), TEXT, monkeypatch)
    assert s["gast"] == "Jürgen Ollmann"
    assert s["gast"] == unicodedata.normalize("NFC", s["gast"])


# ------------------------------------- Die Verbindung zur Smoobu-Buchung
def test_ohne_verbindung_bietet_das_werkzeug_dubletten_an(tmp_path):
    """Der Befund vor dem Ausrollen: nach der Uebernahme haette das Werkzeug
    122 Entwuerfe vorgeschlagen, darunter 78 zu gerade eingelesenen
    Rechnungen."""
    alt.uebernehmen([_satz(pfad=_pdf(tmp_path))])
    buchung = {"id": 999, "guest-name": "Alexander Josan", "arrival": "2026-07-28",
               "departure": "2026-07-31"}
    assert rechnung.faellige_buchungen([buchung], heute=__import__("datetime").date(2026, 8, 8)) == [buchung]


def test_mit_verbindung_verschwindet_die_dublette(tmp_path):
    alt.uebernehmen([_satz(pfad=_pdf(tmp_path))])
    buchung = {"id": 999, "guest-name": "Alexander Josan", "arrival": "2026-07-28",
               "departure": "2026-07-31"}
    v, ohne = alt.buchungen_verknuepfen([buchung])
    assert (v, ohne) == (1, 0)
    assert rechnung.faellige_buchungen([buchung], heute=__import__("datetime").date(2026, 8, 8)) == []


def test_umlaute_stoeren_die_verbindung_nicht(tmp_path):
    import unicodedata
    alt.uebernehmen([_satz(gast="Jürgen Ollmann", pfad=_pdf(tmp_path, 35, "x"))])
    buchung = {"id": 5, "guest-name": unicodedata.normalize("NFD", "Jürgen Ollmann"),
               "arrival": "2026-07-28", "departure": "2026-07-31"}
    assert alt.buchungen_verknuepfen([buchung])[0] == 1


def test_ohne_treffer_bleibt_die_rechnung_unverbunden(tmp_path):
    """Ein geratener Treffer waere schlimmer – er verdeckte eine fehlende
    Rechnung."""
    alt.uebernehmen([_satz(pfad=_pdf(tmp_path))])
    v, ohne = alt.buchungen_verknuepfen([{"id": 1, "guest-name": "Wer Anders",
                                          "arrival": "2026-01-01"}])
    assert (v, ohne) == (0, 1)


def test_ein_zweiter_lauf_verbindet_nicht_neu(tmp_path):
    alt.uebernehmen([_satz(pfad=_pdf(tmp_path))])
    buchung = {"id": 999, "guest-name": "Alexander Josan", "arrival": "2026-07-28"}
    alt.buchungen_verknuepfen([buchung])
    assert alt.buchungen_verknuepfen([buchung]) == (0, 0)


# --------------------------- Rechnungen erst ab einem Stichtag (8.8.2026)
# Ansage: "2025 brauchen wir nicht. Es geht nur ab 2026." Ohne Grenze bot das
# Werkzeug 39 Entwuerfe fuer Aufenthalte aus Oktober bis Dezember 2025 an –
# fuer die es nie Rechnungen geben soll.
def _job(bid, ab, gast="Wer"):
    return {"id": bid, "guest-name": gast, "arrival": ab, "departure": ab}


def test_ohne_grenze_kommt_alles():
    from datetime import date
    jobs = [_job(1, "2025-11-02"), _job(2, "2026-01-02")]
    assert len(rechnung.faellige_buchungen(jobs, date(2026, 8, 8))) == 2


def test_die_grenze_laesst_aeltere_aus():
    from datetime import date
    jobs = [_job(1, "2025-11-02"), _job(2, "2026-01-02")]
    f = rechnung.faellige_buchungen(jobs, date(2026, 8, 8), ab="2026-01-01")
    assert [b["id"] for b in f] == [2]


def test_der_stichtag_selbst_zaehlt_mit():
    """Silvia Erdmann reiste am 01.01.2026 ab – die gehoert dazu."""
    from datetime import date
    jobs = [_job(1, "2026-01-01", "Silvia Erdmann")]
    assert rechnung.faellige_buchungen(jobs, date(2026, 8, 8), ab="2026-01-01") == jobs


def test_die_grenze_kommt_aus_der_konfiguration():
    from datetime import date
    jobs = [_job(1, "2025-11-02"), _job(2, "2026-01-02")]
    f = rechnung.faellige_buchungen(jobs, date(2026, 8, 8),
                                    cfg={"rechnung_ab": "2026-01-01"})
    assert [b["id"] for b in f] == [2]
