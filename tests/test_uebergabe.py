"""B9: die Übergabe ans Steuerbüro.

Das Ziel aus dem Betrieb (8.8.2026): *am Ende muss der Steuerberater alle
Belege etc. bekommen. Sammeln will ich alles über das Tool, speichern dann in
Nextcloud.*

**Der entscheidende Befund beim Bauen:** das Kontenjournal kam aus den
**Belegen**. Das war richtig, solange Belege die einzige Quelle waren. Seit B1
ist die Buchhaltung die **Bewegung mit ihren Posten** — ein Journal aus Belegen
kennt die 45 Ausgaben ohne Beleg nicht und keine Aufteilung. Es gäbe dem
Steuerbüro ein unvollständiges Bild, das vollständig aussieht.
"""
from app import konto, uebergabe as ue, zuordnung as z


def _bewegung(betrag, gegenpartei, bid, datum="2026-03-14", text="", kategorie="",
              umbuchung=False, konto_name="DKB-Business"):
    from app import db
    satz = {"id": bid, "datum": datum, "betrag": betrag, "gegenpartei": gegenpartei,
            "text": text, "konto": konto_name, "umbuchung": umbuchung,
            "kategorie": kategorie}
    db.anlegen(konto.TABELLE, satz)
    return satz


def _beleg(bid, merchant="Rossmann", amount="27,81", datum="2026-03-14"):
    """Legt auch die Datei an – ohne sie käme der Beleg nicht ins Paket, und
    der Test prüfte nur die Datenbank statt der Übergabe."""
    import os
    from app import db, housekeeping
    os.makedirs(housekeeping.MEDIA_DIR, exist_ok=True)
    with open(os.path.join(housekeeping.MEDIA_DIR, f"{bid}.pdf"), "wb") as f:
        f.write(b"%PDF-1.4 Testbeleg")
    satz = {"id": bid, "uploader": "x", "ts": "2026-03-15T10:00:00",
            "photo": f"{bid}.jpg", "pdf": f"{bid}.pdf", "merchant": merchant,
            "amount": amount, "datum": datum, "kategorie": ""}
    db.anlegen("belege", satz)
    return satz


# ------------------------------------------------------- B9a: die Belegnummer
def test_ein_beleg_bekommt_eine_laufende_nummer():
    _beleg("q1", datum="2026-03-14")
    _beleg("q2", datum="2026-03-20")
    assert ue.nummer_vergeben("q1") == "2026-0001"
    assert ue.nummer_vergeben("q2") == "2026-0002"


def test_eine_vergebene_nummer_aendert_sich_nie():
    """Sie ist die Klammer zwischen Buchung und Papier – wandert sie, findet
    das Steuerbüro nichts mehr wieder."""
    _beleg("q1")
    erste = ue.nummer_vergeben("q1")
    assert ue.nummer_vergeben("q1") == erste


def test_die_nummer_zaehlt_je_jahr():
    _beleg("q1", datum="2025-12-30")
    _beleg("q2", datum="2026-01-02")
    assert ue.nummer_vergeben("q1") == "2025-0001"
    assert ue.nummer_vergeben("q2") == "2026-0001"


def test_ohne_beleg_keine_nummer():
    assert ue.nummer_vergeben("gibtsnicht") == ""


def test_alle_nachnummerieren_geht_nach_datum():
    """Damit die Reihenfolge der Nummern der Reihenfolge der Belege folgt."""
    _beleg("spaet", datum="2026-05-01")
    _beleg("frueh", datum="2026-02-01")
    ue.nummern_nachtragen()
    from app import db
    assert db.holen("belege", "frueh")["nummer"] == "2026-0001"
    assert db.holen("belege", "spaet")["nummer"] == "2026-0002"


# ------------------------------------------------- B9b: das Journal
def test_eine_zeile_je_posten_nicht_je_beleg():
    """Der Kern von B9b: eine Zahlung, zwei Verwendungen, zwei Zeilen."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    z.hinzufuegen(b["id"], z.KATEGORIE, -40.0, "Ausstattung/GWG (JYSK)")
    zeilen = ue.journal()
    assert len(zeilen) == 2
    assert [x["Kategorie"] for x in zeilen] \
        == ["Wäscherei (Rena)", "Ausstattung/GWG (JYSK)"]
    assert [x["Betrag"] for x in zeilen] == ["-60,00", "-40,00"]


def test_eine_bewegung_ohne_posten_kommt_mit_ihrer_kategorie():
    """Sonst fehlten dem Steuerbüro alle Zahlungen, die nur erkannt wurden."""
    _bewegung(-73.78, "Smoobu GmbH", "w1", kategorie="Software (Smoobu Channelmanager)")
    zeile = ue.journal()[0]
    assert zeile["Kategorie"] == "Software (Smoobu Channelmanager)"
    assert zeile["Betrag"] == "-73,78"


def test_eine_bewegung_ohne_alles_steht_trotzdem_drin():
    """Was fehlt, gehört als Fehlt-Vermerk hinein – nicht weggelassen."""
    _bewegung(-42.0, "Unbekannt GmbH", "w1")
    zeile = ue.journal()[0]
    assert zeile["Kategorie"] == ""
    assert "ohne Kategorie" in zeile["Hinweis"]


def test_eine_umbuchung_steht_als_neutral_drin():
    """Weglassen wäre falsch – der Kontostand ginge dann nicht auf."""
    _bewegung(-185.68, "DKB", "u1", text="KREDITKARTENABRECHNUNG", umbuchung=True)
    zeile = ue.journal()[0]
    assert zeile["Klasse"] == "Neutral" and "neutral" in zeile["Hinweis"].lower()


def test_die_belegnummer_steht_an_der_buchung():
    """Die Klammer zwischen Journal und Papier."""
    b = _bewegung(-27.81, "Rossmann", "w1")
    _beleg("q1")
    ue.nummer_vergeben("q1")
    z.hinzufuegen(b["id"], z.BELEG, -27.81, "Drogerie/Verbrauch (Rossmann)",
                  ziel_id="q1")
    assert ue.journal()[0]["Beleg"] == "2026-0001"


def test_ohne_beleg_sagt_die_zeile_das_auch():
    _bewegung(-42.0, "Baumarkt", "w1", kategorie="Wäscherei (Rena)")
    zeile = ue.journal()[0]
    assert zeile["Beleg"] == "" and "Beleg fehlt" in zeile["Hinweis"]


def test_das_journal_kommt_nach_datum_sortiert():
    _bewegung(-10.0, "B", "w2", datum="2026-05-01", kategorie="Wäscherei (Rena)")
    _bewegung(-10.0, "A", "w1", datum="2026-02-01", kategorie="Wäscherei (Rena)")
    assert [x["Datum"] for x in ue.journal()] == ["2026-02-01", "2026-05-01"]


def test_der_zeitraum_grenzt_das_journal_ein():
    _bewegung(-10.0, "A", "w1", datum="2026-02-01", kategorie="Wäscherei (Rena)")
    _bewegung(-10.0, "B", "w2", datum="2026-05-01", kategorie="Wäscherei (Rena)")
    assert len(ue.journal("2026-05-01", "2026-05-31")) == 1


def test_das_journal_als_csv_traegt_die_spalten():
    _bewegung(-42.0, "Baumarkt", "w1", kategorie="Wäscherei (Rena)")
    roh = ue.journal_csv().decode("utf-8-sig")
    kopf = roh.splitlines()[0]
    assert kopf.startswith("Datum;Konto;Gegenpartei")
    assert "Beleg" in kopf and "Hinweis" in kopf


# ------------------------------------------------- B9c: das Übergabepaket
def test_das_paket_legt_die_belege_nach_jahr_und_monat_ab():
    import zipfile, io
    _beleg("q1", merchant="Rossmann", amount="27,81", datum="2026-03-14")
    ue.nummer_vergeben("q1")
    b = _bewegung(-27.81, "Rossmann", "w1")
    z.hinzufuegen(b["id"], z.BELEG, -27.81, "Drogerie/Verbrauch (Rossmann)",
                  ziel_id="q1")
    with zipfile.ZipFile(io.BytesIO(ue.paket())) as zf:
        namen = zf.namelist()
    assert any(n.startswith("2026/03/") and "0001" in n and "Rossmann" in n
               for n in namen), namen


def test_das_paket_enthaelt_journal_und_deckblatt():
    import zipfile, io
    _bewegung(-42.0, "Baumarkt", "w1", kategorie="Wäscherei (Rena)")
    with zipfile.ZipFile(io.BytesIO(ue.paket())) as zf:
        namen = zf.namelist()
    assert "Kontenjournal.csv" in namen
    assert "Deckblatt.txt" in namen


def test_das_deckblatt_nennt_was_fehlt():
    """Ohne dieses Blatt liest das Steuerbüro einen Zwischenstand als
    Abschluss."""
    _bewegung(-42.0, "Unbekannt", "w1")
    _bewegung(-10.0, "Rena", "w2", kategorie="Wäscherei (Rena)")
    text = ue.deckblatt()
    assert "1 Ausgabe ohne Kategorie" in text or "1 Ausgaben ohne Kategorie" in text
    assert "ohne Beleg" in text


def test_das_deckblatt_nennt_zeitraum_und_konten():
    _bewegung(-42.0, "Rena", "w1", datum="2026-02-01", kategorie="Wäscherei (Rena)")
    _bewegung(-10.0, "Rena", "w2", datum="2026-05-01", kategorie="Wäscherei (Rena)",
              konto_name="VISA 8136")
    text = ue.deckblatt()
    assert "2026-02-01" in text and "2026-05-01" in text
    assert "DKB-Business" in text and "VISA 8136" in text


def test_ein_beleg_ohne_bewegung_kommt_trotzdem_mit():
    """Er gehört dem Steuerbüro – auch wenn ihn hier noch niemand zugeordnet
    hat. Weglassen hieße, ihn zu unterschlagen."""
    import zipfile, io
    _beleg("q1", merchant="Metro", amount="390,11", datum="2026-03-25")
    with zipfile.ZipFile(io.BytesIO(ue.paket())) as zf:
        namen = zf.namelist()
    assert any("Metro" in n for n in namen), namen


def test_ein_leerer_bestand_ergibt_ein_leeres_paket_mit_deckblatt():
    import zipfile, io
    with zipfile.ZipFile(io.BytesIO(ue.paket())) as zf:
        assert "Deckblatt.txt" in zf.namelist()


# ------------------------------------------------------------- Die Anzeige
def _in_client(bauen):
    from nicegui import ui
    from nicegui.client import Client
    with Client(lambda: None):
        with ui.card():
            bauen()


def test_die_uebergabekarte_laesst_sich_zeichnen():
    from app.ui import ueberblick as ui_ub
    _bewegung(-42.0, "Baumarkt", "w1", kategorie="Wäscherei (Rena)")
    _beleg("q1")
    _in_client(lambda: ui_ub._uebergabe({"von": "", "bis": ""}))


def test_die_karte_haelt_auch_einen_leeren_bestand_aus():
    from app.ui import ueberblick as ui_ub
    _in_client(lambda: ui_ub._uebergabe({"von": "", "bis": ""}))


def test_belege_ohne_datum_kommen_in_einen_eigenen_ordner():
    """Im Monat des Uploads saehen sie aus, als seien sie dort entstanden. Am
    Bestand lagen so alle 30 unter „2026/08"."""
    import zipfile, io
    from app import db
    _beleg("q1", merchant="Metro", datum="")
    db.speichern("belege", "q1", dict(db.holen("belege", "q1"), datum=""))
    with zipfile.ZipFile(io.BytesIO(ue.paket())) as zf:
        namen = [n for n in zf.namelist() if "Metro" in n]
    assert namen and namen[0].startswith("_ohne Belegdatum/"), namen


def test_das_deckblatt_nennt_die_belege_ohne_datum():
    from app import db
    _beleg("q1", datum="")
    db.speichern("belege", "q1", dict(db.holen("belege", "q1"), datum=""))
    assert "ohne gepflegtes Belegdatum" in ue.deckblatt()
