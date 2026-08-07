"""AP10: Belege bis zur EÜR – Kategorien, Prüfungen, Abschluss, Export.

Die Fachlogik ohne Oberfläche. Zwei Tests tragen hier mehr als alle anderen:

* `test_kategorien_sind_woertlich_die_kriterien_des_workbooks` – das Workbook
  vergleicht wörtlich. Ein „verbessertes" Kategoriewort lässt die Summe still
  auf null fallen, ohne Fehlermeldung.
* `test_beleg_gehoert_in_den_monat_seines_datums` – ein Beleg vom 29., der am
  2. fotografiert wird, gehört in den alten Monat. Sonst wandert die Ausgabe
  ins nächste Quartal, und die Voranmeldung stimmt nicht mehr.
"""
import os

import pytest

from app import buchhaltung as bh

WORKBOOK = os.path.expanduser(
    "~/Claude/Projects/Buchhaltung DS Apartments & Suites/"
    "Buchhaltung_DS_Apartments_2026.xlsx")


def _beleg(**felder):
    grund = {"id": "b1", "ts": "2026-08-06T10:00:00", "datum": "2026-08-03",
             "amount": "27,81", "merchant": "Rossmann 2540",
             "kategorie": "Drogerie/Verbrauch (Rossmann)", "note": "Reinigungsmittel",
             "apartment_name": ""}
    grund.update(felder)
    return grund


# ------------------------------------------------------------------ Betrag
@pytest.mark.parametrize("text,erwartet", [
    ("27,81", 27.81), ("1.234,56", 1234.56), ("27.81", 27.81),
    ("€ 9,90", 9.9), ("  12,00  ", 12.0), ("-5,00", -5.0),
    ("", None), (None, None), ("keine Zahl", None), (27.81, 27.81),
])
def test_betrag_lesen(text, erwartet):
    """Die Beträge kommen aus OCR und vom Handy – in jeder Schreibweise."""
    assert bh.betrag_zahl(text) == erwartet


@pytest.mark.parametrize("wert,erwartet", [
    (-27.81, "-27,81"), (1234.56, "1.234,56"), (0.0, "0,00"),
    (1234567.8, "1.234.567,80"), (None, ""),
])
def test_betrag_schreiben(wert, erwartet):
    """Ziel ist Excel mit deutscher Ländereinstellung."""
    assert bh.betrag_text(wert) == erwartet


def test_betrag_ueberlebt_den_hin_und_rueckweg():
    for wert in [0.01, 27.81, 999.99, 1234.56, 1234567.8]:
        assert bh.betrag_zahl(bh.betrag_text(wert)) == wert


# ------------------------------------------------------------------ Datum
def test_beleg_gehoert_in_den_monat_seines_datums():
    """Ein Beleg vom 29. Juli, fotografiert am 2. August, ist ein Juli-Beleg."""
    spaet = _beleg(datum="2026-07-29", ts="2026-08-02T08:15:00")
    assert bh.belegdatum(spaet) == "2026-07-29"
    assert bh.monat(spaet) == "2026-07"


def test_ohne_belegdatum_zaehlt_der_upload():
    """Besser ein plausibles Datum als gar keins – die Prüfung meckert nicht,
    weil `ts` immer gesetzt ist."""
    ohne = _beleg(datum="")
    assert bh.belegdatum(ohne) == "2026-08-06"


# --------------------------------------------------------------- Prüfungen
def test_vollstaendiger_beleg_hat_nichts_offen():
    assert bh.fehlende_felder(_beleg()) == []


@pytest.mark.parametrize("feld,erwartet", [
    ("amount", "Betrag"), ("merchant", "Händler"), ("kategorie", "Kategorie"),
])
def test_fehlendes_pflichtfeld_wird_im_klartext_gemeldet(feld, erwartet):
    """„fehlt: kategorie" hilft niemandem, der den Beleg nachtragen soll."""
    assert bh.fehlende_felder(_beleg(**{feld: ""})) == [erwartet]


def test_betrag_null_gilt_als_fehlend():
    """Ein Beleg über 0,00 € ist kein Beleg, sondern ein Tippfehler."""
    assert "Betrag" in bh.fehlende_felder(_beleg(amount="0,00"))


def test_unlesbares_datum_faellt_auf():
    assert "Belegdatum" in bh.fehlende_felder(_beleg(datum="irgendwann", ts=""))


def test_derselbe_kassenbon_zweimal_faellt_auf():
    """Zwei Leute fotografieren denselben Bon, oder der Upload wird nach einem
    Verbindungsabbruch wiederholt. Doppelt gebucht merkt die EÜR nicht."""
    a, b = _beleg(id="a"), _beleg(id="b")
    gruppen = bh.dubletten([a, b])
    assert len(gruppen) == 1 and len(gruppen[0]) == 2


def test_gleicher_haendler_anderer_tag_ist_keine_dublette():
    assert bh.dubletten([_beleg(id="a"), _beleg(id="b", datum="2026-08-04")]) == []


def test_schreibweise_des_haendlers_taeuscht_die_pruefung_nicht():
    """„Rossmann 2540" und „rossmann2540" sind derselbe Laden."""
    assert len(bh.dubletten([_beleg(id="a"),
                             _beleg(id="b", merchant="rossmann2540")])) == 1


def test_halbe_belege_zaehlen_nicht_als_dublette():
    """Ohne Betrag oder Händler ist die Frage nicht zu beantworten – dann meldet
    die Pflichtfeldprüfung, nicht die Dublettenprüfung."""
    assert bh.dubletten([_beleg(id="a", amount=""), _beleg(id="b", amount="")]) == []


def test_pruefung_fasst_alles_zusammen():
    belege = [_beleg(id="a"), _beleg(id="b"),                    # Dublette
              _beleg(id="c", datum="2026-08-05", kategorie=""),  # unvollständig
              _beleg(id="d", datum="2026-08-07", amount="5,00",
                     merchant="dm", kategorie=bh.UNKLAR)]        # unklar
    befund = bh.pruefung(belege)
    assert befund["anzahl"] == 4
    assert len(befund["dubletten"]) == 1
    assert len(befund["unvollstaendig"]) == 1
    assert len(befund["unklar"]) == 1
    assert not befund["abschliessbar"]


def test_sauberer_monat_ist_abschliessbar():
    belege = [_beleg(id="a"), _beleg(id="b", datum="2026-08-04", amount="5,00",
                                     merchant="dm",
                                     kategorie="Reinigung/Verbrauch (dm)")]
    befund = bh.pruefung(belege)
    assert befund["abschliessbar"]
    assert befund["summe"] == 32.81


# ------------------------------------------------------------------ Export
def test_ausgabe_geht_negativ_ins_journal():
    """Das Kontenjournal führt Ausgaben negativ; am Beleg steht die Zahl
    positiv, weil niemand ein Minus abtippt."""
    assert bh.journal_zeile(_beleg())["Betrag"] == "-27,81"


def test_privates_bleibt_als_privat_gekennzeichnet():
    zeile = bh.journal_zeile(_beleg(kategorie="Lebensmittel (privat? – prüfen)"))
    assert zeile["Klasse"] == "Privat/prüfen"


def test_die_wohnung_steht_im_verwendungszweck():
    """In der Buchhaltung ist später sonst nicht mehr zu sehen, wofür es war."""
    zeile = bh.journal_zeile(_beleg(apartment_name="Cottaer Straße"))
    assert zeile["Verwendungszweck"] == "Reinigungsmittel · Cottaer Straße"


def test_journal_hat_genau_die_acht_spalten_des_kontenjournals():
    assert list(bh.journal_zeile(_beleg())) == bh.JOURNAL_SPALTEN
    assert bh.JOURNAL_SPALTEN == ["Datum", "Quelle", "Gegenkonto",
                                  "Verwendungszweck", "Betrag", "Klasse",
                                  "Kategorie", "Belegstatus"]


def test_zeilen_stehen_chronologisch():
    belege = [_beleg(id="b", datum="2026-08-09"), _beleg(id="a", datum="2026-08-01")]
    assert [z["Datum"] for z in bh.journal_zeilen(belege)] == ["2026-08-01", "2026-08-09"]


def test_csv_ist_fuer_excel_lesbar():
    """Semikolon, BOM und deutsche Beträge – ohne BOM zerlegt Excel die Umlaute."""
    roh = bh.csv_bytes([_beleg(merchant="Bäckerei Müller")])
    assert roh.startswith(b"\xef\xbb\xbf")
    text = roh.decode("utf-8-sig")
    kopf, zeile = text.splitlines()[:2]
    assert kopf == ";".join(bh.JOURNAL_SPALTEN)
    assert "Bäckerei Müller" in zeile
    assert "-27,81" in zeile


# -------------------------------------------------------------- Kategorien
def test_kategorien_enthalten_den_auffangposten_zuletzt():
    liste = bh.kategorien()
    assert liste[-1] == bh.UNKLAR
    assert liste[:-1] == bh.VORGABE_KATEGORIEN


def test_eigene_kategorien_kommen_aus_den_einstellungen():
    """Jeder neue Lieferant braucht eine neue Zeile im Kontenjournal – das kann
    die Vorgabe nicht vorwegnehmen."""
    liste = bh.kategorien({"beleg_kategorien": ["Gartenpflege (Grün & Co)"]})
    assert "Gartenpflege (Grün & Co)" in liste
    assert liste[-1] == bh.UNKLAR


def test_eigene_kategorie_verdoppelt_keine_vorgabe():
    liste = bh.kategorien({"beleg_kategorien": ["Wäscherei (Rena)", "  ", ""]})
    assert liste.count("Wäscherei (Rena)") == 1


def test_klasse_folgt_aus_der_kategorie():
    assert bh.klasse_fuer("Reinigung/Verbrauch (dm)") == "Ausgabe"
    assert bh.klasse_fuer("Lebensmittel (privat? – prüfen)") == "Privat/prüfen"
    assert bh.klasse_fuer(bh.UNKLAR) == "Ausgabe/prüfen"
    assert bh.klasse_fuer("") == "Ausgabe"


@pytest.mark.skipif(not os.path.exists(WORKBOOK),
                    reason="EÜR-Workbook liegt nur auf dem Rechner des Betreibers")
def test_kategorien_sind_woertlich_die_kriterien_des_workbooks():
    """Der wichtigste Test dieses Pakets.

    Die EÜR zieht jede Position per SUMIF über einen **wörtlichen** Vergleich.
    Ein Buchstabe daneben – „Bertsch" statt „Bartsch", ein Bindestrich statt
    des Halbgeviertstrichs – und die Summe bleibt still auf null. Kein Fehler,
    keine Meldung, nur eine zu niedrige EÜR.
    """
    # openpyxl steht bewusst nicht in requirements.txt: die App braucht es nie,
    # nur diese Gegenprobe. Zum Ausführen: .venv/bin/pip install openpyxl
    openpyxl = pytest.importorskip(
        "openpyxl", reason="für die Gegenprobe gegen das Workbook: pip install openpyxl")
    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)
    kj = wb["Kontenjournal"]
    im_workbook = {str(kj.cell(r, 7).value).strip()
                   for r in range(4, kj.max_row + 1) if kj.cell(r, 7).value}
    unbekannt = [k for k in bh.VORGABE_KATEGORIEN + [bh.UNKLAR]
                 if k not in im_workbook]
    assert not unbekannt, (
        "Diese Kategorien kennt das Kontenjournal nicht – ihre Summe bliebe in "
        f"der EÜR auf null: {unbekannt}")


# ----------------------------------------------------------- Die Oberfläche
from nicegui.testing import User            # noqa: E402
from app import auth, data, mailer, receipts, web   # noqa: E402


@pytest.fixture
def app_bereit(monkeypatch):
    monkeypatch.setattr(data, "get_apartments", lambda: [
        {"id": 2748963, "name": "Cottaer Straße"}])
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [])
    monkeypatch.setattr(mailer, "send_notify", lambda *a, **k: None)
    web._APARTMENTS.clear()


async def _anmelden(user, monkeypatch, rolle="admin"):
    monkeypatch.setitem(web.USERS, "nutzer", {
        "password_hash": auth.hash_password("geheim"), "role": rolle,
        "totp_secret": "", "name": "nutzer"})
    await user.open("/login")
    user.find(marker="login-user").type("nutzer")
    user.find(marker="login-pw").type("geheim")
    user.find("Anmelden").click()
    await user.open("/")


def _lege_beleg_an(**felder):
    r = receipts.add_receipt("vale", photo=None, **{
        k: v for k, v in felder.items() if k != "datum"})
    if felder.get("datum"):
        receipts.update_receipt(r["id"], datum=felder["datum"])
    return receipts.list_receipts()[0]


async def test_putzkraft_bucht_nicht(user: User, app_bereit, monkeypatch):
    """Kategorisieren ist ein Buchungsakt – eine falsche Kategorie läuft still
    in die EÜR. Die Putzkraft fotografiert und beschreibt, mehr nicht."""
    beleg = _lege_beleg_an(amount="27,81", merchant="Rossmann", datum="2026-08-03")
    await _anmelden(user, monkeypatch, "putzkraft")
    user.find(marker="nav-belege").click()
    await user.should_see("Neuen Beleg hinzufügen")
    await user.should_not_see(marker=f"beleg-kategorie-{beleg['id']}")
    await user.should_not_see(marker="panel-abschluss")


async def test_verwaltung_bucht(user: User, app_bereit, monkeypatch):
    beleg = _lege_beleg_an(amount="27,81", merchant="Rossmann", datum="2026-08-03")
    await _anmelden(user, monkeypatch, "admin")
    user.find(marker="nav-belege").click()
    await user.should_see(marker=f"beleg-kategorie-{beleg['id']}")
    await user.should_see(marker=f"beleg-datum-{beleg['id']}")
    await user.should_see(marker="panel-abschluss")


async def test_offener_monat_nennt_den_grund_und_sperrt_den_abschluss(
        user: User, app_bereit, monkeypatch):
    """„3 Probleme" schickt einen suchen. Der Befund nennt Händler und Feld."""
    _lege_beleg_an(amount="27,81", merchant="Rossmann", datum="2026-08-03")
    await _anmelden(user, monkeypatch, "admin")
    user.find(marker="nav-belege").click()
    await user.should_see(marker="monat-2026-08")
    await user.should_see("Rossmann: es fehlt Kategorie")
    with user.client:
        knopf = next(iter(user.find(marker="abschliessen-2026-08").elements))
        assert not knopf.enabled, "Abschluss trotz offener Punkte möglich"


async def test_dublette_haelt_den_abschluss_auf(user: User, app_bereit, monkeypatch):
    for _ in range(2):
        _lege_beleg_an(amount="27,81", merchant="Rossmann", datum="2026-08-03",
                       kategorie="Drogerie/Verbrauch (Rossmann)")
    await _anmelden(user, monkeypatch, "admin")
    user.find(marker="nav-belege").click()
    await user.should_see("doppelt erfasst?")


async def test_sauberer_monat_laesst_sich_abschliessen(user: User, app_bereit, monkeypatch):
    _lege_beleg_an(amount="27,81", merchant="Rossmann", datum="2026-08-03",
                   kategorie="Drogerie/Verbrauch (Rossmann)")
    await _anmelden(user, monkeypatch, "admin")
    user.find(marker="nav-belege").click()
    await user.should_see(marker="abschliessen-2026-08")
    user.find(marker="abschliessen-2026-08").click()
    assert bh.abschluss_von("2026-08") is not None
    await user.open("/")
    user.find(marker="nav-belege").click()
    assert user.find(marker="oeffnen-2026-08").elements, "Monat nicht als geschlossen gezeigt"
    with user.client:
        assert bh.abschluss_von("2026-08")["wer"] == "nutzer"


async def test_abgeschlossener_monat_laesst_sich_wieder_oeffnen(
        user: User, app_bereit, monkeypatch):
    """Manchmal fehlt ein Beleg genau einen Tag zu spät. Das zu verstecken
    hilft niemandem – wer öffnet, steht im Eintrag."""
    _lege_beleg_an(amount="27,81", merchant="Rossmann", datum="2026-08-03",
                   kategorie="Drogerie/Verbrauch (Rossmann)")
    await _anmelden(user, monkeypatch, "admin")
    user.find(marker="nav-belege").click()
    # Der Abschluss lädt die Seite neu (wie jede andere Statusänderung in
    # dieser App auch), deshalb hier neu öffnen statt auf einen Neuaufbau warten.
    user.find(marker="abschliessen-2026-08").click()
    assert bh.abschluss_von("2026-08") is not None
    await user.open("/")
    user.find(marker="nav-belege").click()
    assert user.find(marker="oeffnen-2026-08").elements, "Abschluss nicht sichtbar"
    user.find(marker="oeffnen-2026-08").click()
    assert bh.abschluss_von("2026-08") is None
    await user.open("/")
    user.find(marker="nav-belege").click()
    assert user.find(marker="abschliessen-2026-08").elements


def test_abschluss_verweigert_sich_bei_offenen_punkten():
    """Auch am Modul vorbei – die Regel steht in der Fachlogik, nicht in der
    Oberfläche."""
    with pytest.raises(ValueError):
        bh.abschliessen("2026-08", [_beleg(kategorie="")], "nutzer")


# ------------------------------------------------------------ Sammelmappe
def test_sammelmappe_ist_eine_lesbare_pdf(tmp_path, monkeypatch):
    """Die Mappe ist das, was das Steuerbüro sonst einzeln anfordert. Sie muss
    auch dann entstehen, wenn zu einem Beleg das Bild fehlt – sonst bricht der
    Monatsabschluss an einem einzigen kaputten Anhang ab."""
    import fitz
    from app import housekeeping as hk
    monkeypatch.setattr(hk, "MEDIA_DIR", str(tmp_path))

    bild = tmp_path / "beleg.png"
    fitz.open().new_page(width=200, height=300).parent.save(str(tmp_path / "leer.pdf"))
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 200))
    pix.clear_with(220)
    pix.save(str(bild))

    belege = [_beleg(id="a", photo="beleg.png"),
              _beleg(id="b", datum="2026-08-04", photo="fehlt.png")]
    zeilen = bh.journal_zeilen(belege)
    roh = receipts.sammelmappe(belege, "Belege August 2026", zeilen)

    doc = fitz.open(stream=roh, filetype="pdf")
    assert doc.page_count >= 3          # Aufstellung + je Beleg eine Seite
    text = doc[0].get_text()
    assert "Belege August 2026" in text
    assert "Rossmann" in text
    # Die Kopfzeile ordnet den Bon zu – ohne sie ist er in einem Stapel von
    # vierzig nicht mehr aufzulösen.
    assert "Rossmann" in doc[1].get_text()


# --------------------------------------------------- Eigene Kategorien (AP27)
# Die Vorgaben sind woertlich die SUMIF-Kriterien des Workbooks. Alles, was der
# Betrieb darueber hinaus auswerten will, legt er selbst an – nicht der
# Entwickler im Quelltext.
def test_eine_eigene_kategorie_laesst_sich_anlegen():
    cfg = {}
    ok, _m = bh.kategorie_anlegen(cfg, "  Putzmittel ")
    assert ok
    assert bh.eigene_kategorien(cfg) == ["Putzmittel"]
    assert "Putzmittel" in bh.kategorien(cfg)


def test_doppelte_namen_werden_abgelehnt():
    """Zwei gleich heissende Kategorien waeren in der Auswahl nicht
    unterscheidbar, und die Auswertung liefe auf zwei Zeilen auseinander."""
    cfg = {}
    bh.kategorie_anlegen(cfg, "Putzmittel")
    ok, meldung = bh.kategorie_anlegen(cfg, "putzmittel")
    assert not ok and "gibt es schon" in meldung
    ok, _m = bh.kategorie_anlegen(cfg, bh.VORGABE_KATEGORIEN[0])
    assert not ok, "auch eine Vorgabe darf nicht doppelt entstehen"


def test_ein_leerer_name_legt_nichts_an():
    cfg = {}
    assert bh.kategorie_anlegen(cfg, "   ")[0] is False
    assert bh.eigene_kategorien(cfg) == []


def test_umbenennen_nimmt_die_zugeordneten_saetze_mit():
    """Der eigentliche Fund: ohne das Nachziehen truegen die Belege weiter den
    alten Text, die neue Kategorie staende bei null – und niemand saehe einen
    Fehler."""
    from app import db
    cfg = {}
    bh.kategorie_anlegen(cfg, "Putzmittel")
    db.anlegen("belege", {"id": "b1", "kategorie": "Putzmittel", "amount": "9,99"})
    db.anlegen("bewegungen", {"id": "k1", "kategorie": "Putzmittel", "betrag": -9.99})
    ok, meldung = bh.kategorie_umbenennen(cfg, "Putzmittel", "Reinigungsbedarf")
    assert ok and "2 Sätze" in meldung
    assert db.holen("belege", "b1")["kategorie"] == "Reinigungsbedarf"
    assert db.holen("bewegungen", "k1")["kategorie"] == "Reinigungsbedarf"
    assert bh.eigene_kategorien(cfg) == ["Reinigungsbedarf"]


def test_vorgaben_lassen_sich_nicht_umbenennen():
    """Sie muessen woertlich zum Workbook passen – ein Buchstabe daneben laesst
    die SUMIF-Summe still auf null fallen."""
    cfg = {}
    ok, meldung = bh.kategorie_umbenennen(cfg, bh.VORGABE_KATEGORIEN[0], "Neuer Name")
    assert not ok and "Vorgaben" in meldung


def test_eine_benutzte_kategorie_wird_nicht_geloescht():
    """Sonst truegen die Saetze eine Kategorie, die es nicht mehr gibt."""
    from app import db
    cfg = {}
    bh.kategorie_anlegen(cfg, "Gastgeschenke")
    db.anlegen("belege", {"id": "b2", "kategorie": "Gastgeschenke"})
    ok, meldung = bh.kategorie_loeschen(cfg, "Gastgeschenke")
    assert not ok and "1× zugeordnet" in meldung
    assert bh.eigene_kategorien(cfg) == ["Gastgeschenke"]


def test_eine_unbenutzte_kategorie_laesst_sich_loeschen():
    cfg = {}
    bh.kategorie_anlegen(cfg, "Versehen")
    assert bh.kategorie_loeschen(cfg, "Versehen")[0]
    assert bh.eigene_kategorien(cfg) == []
