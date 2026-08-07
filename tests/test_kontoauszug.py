"""Kontoauszüge einlesen (AP16).

Die Ausschnitte stammen **wörtlich** aus den echten Exporten vom 24.7.2026
(DKB-Business und DKB-VISA-Business-Card) – gekürzt, aber nicht geglättet.
Erfundene Testdaten hätten die beiden Fallen nicht gezeigt, um die es hier
geht: die zweistellige Jahreszahl und der Kreditkarten-Ausgleich, der in
**beiden** Auszügen steht.
"""
from datetime import date

import pytest

from app import konto, kontoauszug as ka

HEUTE = date(2026, 8, 7)

GIRO = """\
"DKB-Business";"DE62120300001310062102"
"Zeitraum:";"01.01.2026 - 24.07.2026"
"Kontostand vom 24.07.2026:";"5.765,34 €"
""
"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"
"24.07.26";"24.07.26";"Gebucht";"Booking.com BV";"DANIEL STEINHAUSS";"NO.bbqETYstLU6QDo85/ID.14005823";"Eingang";"NL15CITI2032301393";"314,93";"";"";"2196804724"
"24.07.26";"24.07.26";"Gebucht";"DANIEL STEINHAUß";"Deutsche Kreditbank Berlin";"KREDITKARTENABRECHNUNG VISA -ABR. 499898XXXXXX8136";"Ausgang";"DE79120300009003290294";"-3,41";"DE45ZZZ01518301218";"";""
"23.07.26";"23.07.26";"Gebucht";"Gockel, Katarina";"Daniel Steinhauß";"Buchung Katarina Gockel Cottaer Straße";"Eingang";"DE75100500001584049444";"379,48";"";"";""
"20.07.26";"20.07.26";"Gebucht";"Daniel Steinhauss";"DREWAG-Stadtwerke DD GmbH";"VK 211001172353 Abschlag 20.07.";"Ausgang";"DE72850800000410605231";"-111";"";"";""
"""

KARTE = """\
"Karte";"DKB-VISA-Business-Card";"4998 •••• •••• 8136"
""
"Saldo vom 24.07.2026:";"-0 EUR"
""
"Belegdatum";"Wertstellung";"Status";"Beschreibung";"Umsatztyp";"Betrag (€)";"Fremdwährungsbetrag"
"22.07.26";"23.07.26";"Gebucht";"Ausgleich Kreditkarte gem";"Lastschrift";"3,41";""
"29.06.26";"30.06.26";"Gebucht";"Rossmann 2424";"Im Geschäft";"-3,41";""
"08.06.26";"09.06.26";"Gebucht";"Wok art GmbH";"Im Geschäft";"-80";""
"""


def _giro():
    return ka.lesen(GIRO.encode("utf-8-sig"), heute=HEUTE)


def _karte():
    return ka.lesen(KARTE.encode("utf-8-sig"), heute=HEUTE)


# ------------------------------------------------------------------ Erkennung
def test_beide_formate_werden_am_inhalt_erkannt():
    """Am Spaltenkopf, nicht am Dateinamen – der ist frei wählbar."""
    assert _giro()[1] == ka.GESCHAEFT
    assert _karte()[1] == ka.KARTE


def test_der_vorspann_wird_uebersprungen():
    """Vor der Spaltenzeile stehen Kontoname, Zeitraum und Saldo. Würden sie
    mitgelesen, entstünden vier Bewegungen ohne Betrag."""
    assert len(_giro()[2]) == 4
    assert len(_karte()[2]) == 3


def test_das_konto_steht_am_satz():
    assert _giro()[0] == "DE62120300001310062102"
    assert _karte()[0] == "VISA 8136"


def test_eine_fremde_datei_sagt_es_deutlich():
    """Eine stumm leere Liste wäre schlimmer – sie sähe aus wie ein Monat ohne
    Umsätze."""
    with pytest.raises(ValueError, match="DKB-Auszug"):
        ka.lesen(b"Datum,Betrag\n01.01.2026,5\n")


# --------------------------------------------------------------------- Werte
@pytest.mark.parametrize("roh,erwartet", [
    ("1.234,56", 1234.56), ("83,46", 83.46), ("-3,41", -3.41),
    ("-111", -111.0), ("5.765,34 €", 5765.34), ("", None), ("keine Zahl", None),
])
def test_betraege_deutscher_schreibweise(roh, erwartet):
    assert ka.betrag(roh) == erwartet


def test_zweistellige_jahre_landen_im_richtigen_jahrhundert():
    """Die DKB schreibt „24.07.26". Ohne Auslegung wäre das das Jahr 26."""
    assert ka.datum("24.07.26", heute=HEUTE) == "2026-07-24"
    assert ka.datum("30.12.25", heute=HEUTE) == "2025-12-30"


def test_ein_datum_in_ferner_zukunft_wird_zurueckgesetzt():
    """„01.01.99" ist kein Auszug von 2099, sondern einer von 1999."""
    assert ka.datum("01.01.99", heute=HEUTE) == "1999-01-01"


def test_unsinnige_daten_liefern_leer_statt_absturz():
    assert ka.datum("31.02.26", heute=HEUTE) == ""
    assert ka.datum("keine Angabe", heute=HEUTE) == ""


def test_die_gegenpartei_haengt_an_der_richtung():
    """Bei einem Eingang zahlt der andere, bei einem Ausgang bekommt er –
    die Bank führt beide in verschiedenen Spalten."""
    bew = _giro()[2]
    eingang = next(b for b in bew if b["text"].startswith("NO."))
    ausgang = next(b for b in bew if b["text"].startswith("VK 21"))
    assert eingang["betrag"] > 0 and eingang["gegenpartei"] == "Booking.com BV"
    assert ausgang["betrag"] < 0 and ausgang["gegenpartei"] == "DREWAG-Stadtwerke DD GmbH"


def test_die_karte_kennt_nur_eine_beschreibung():
    """Dort ist die Beschreibung zugleich der Händler."""
    b = _karte()[2][1]
    assert b["gegenpartei"] == b["text"] == "Rossmann 2424"


# ------------------------------------------------- Der Kreditkarten-Ausgleich
def test_der_ausgleich_wird_auf_beiden_seiten_erkannt():
    """Er steht im Girokonto als Abbuchung und auf der Karte als Gutschrift.
    Zählt man beides, stehen die Kartenkäufe doppelt im Ergebnis."""
    giro = next(b for b in _giro()[2] if "KREDITKARTEN" in b["text"])
    karte = next(b for b in _karte()[2] if "Ausgleich" in b["text"])
    assert giro["umbuchung"] and karte["umbuchung"]


def test_ein_normaler_umsatz_ist_keine_umbuchung():
    """Sonst fiele er still aus dem Ergebnis."""
    assert not any(b["umbuchung"] for b in _karte()[2] if "Rossmann" in b["text"])
    assert not any(b["umbuchung"] for b in _giro()[2] if "Booking" in b["gegenpartei"])


def test_die_zusammenfassung_laesst_umbuchungen_draussen():
    z = ka.zusammenfassung(_karte()[2])
    assert z["umbuchungen"] == 1
    assert z["eingang"] == 0.0, "Der Ausgleich ist kein Eingang"
    assert z["ausgang"] == -83.41
    assert (z["von"], z["bis"]) == ("2026-06-08", "2026-07-22")


# ------------------------------------------------------------------- Ablage
def test_derselbe_auszug_zweimal_erzeugt_keine_dubletten():
    """Auszüge überschneiden sich – wer im Juli und im August exportiert, hat
    den Juli zweimal."""
    erst = konto.importieren(GIRO.encode("utf-8-sig"), heute=HEUTE)
    zweit = konto.importieren(GIRO.encode("utf-8-sig"), heute=HEUTE)
    assert (erst["neu"], erst["doppelt"]) == (4, 0)
    assert (zweit["neu"], zweit["doppelt"]) == (0, 4)
    assert len(konto.alle()) == 4


def test_eine_zuordnung_ueberlebt_den_zweiten_import():
    """Sonst wäre jeder erneute Import ein Rückschritt."""
    konto.importieren(GIRO.encode("utf-8-sig"), heute=HEUTE)
    b = konto.alle()[0]
    from app import db
    db.speichern(konto.TABELLE, b["id"], dict(b, beleg_id="xyz", kategorie="Strom"))
    konto.importieren(GIRO.encode("utf-8-sig"), heute=HEUTE)
    wieder = db.holen(konto.TABELLE, b["id"])
    assert wieder["beleg_id"] == "xyz" and wieder["kategorie"] == "Strom"


def test_zwei_konten_bleiben_getrennt():
    konto.importieren(GIRO.encode("utf-8-sig"), heute=HEUTE)
    konto.importieren(KARTE.encode("utf-8-sig"), heute=HEUTE)
    assert konto.konten() == ["DE62120300001310062102", "VISA 8136"]
    assert len(konto.alle(konto="VISA 8136")) == 3


def test_monatssummen_zaehlen_den_ausgleich_nicht_mit():
    """Die Probe auf die Umbuchung: 3,41 € Kartenkauf dürfen einmal im
    Ergebnis stehen, nicht zweimal."""
    konto.importieren(GIRO.encode("utf-8-sig"), heute=HEUTE)
    konto.importieren(KARTE.encode("utf-8-sig"), heute=HEUTE)
    juli = konto.monatssummen()["2026-07"]
    assert juli["eingang"] == 694.41           # 314,93 + 379,48
    assert juli["ausgang"] == -111.0           # nur DREWAG, nicht die Abrechnung


def test_zeitraum_ueber_den_bestand():
    konto.importieren(KARTE.encode("utf-8-sig"), heute=HEUTE)
    assert konto.zeitraum() == ("2026-06-08", "2026-07-22")


# ------------------------------------------------------- Der Bereich „Konto"
# Die Fachlogik oben ist ohne Oberfläche geprüft. Hier geht es darum, dass der
# Bereich wirklich erreichbar ist und die eingelesenen Bewegungen auch auf dem
# Bildschirm landen – eine Zahl, die stimmt, aber nirgends steht, nützt nichts.
from nicegui.testing import User            # noqa: E402

from app import auth, data, mailer, web     # noqa: E402


@pytest.fixture
def app_bereit(monkeypatch):
    monkeypatch.setattr(data, "get_apartments", lambda: [])
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [])
    monkeypatch.setattr(mailer, "send_notify", lambda *a, **k: None)
    monkeypatch.setitem(web.USERS, "nutzer", {
        "password_hash": auth.hash_password("geheim"), "role": "admin",
        "totp_secret": "", "name": "nutzer"})
    web._APARTMENTS.clear()


async def _anmelden(user):
    await user.open("/login")
    user.find(marker="login-user").type("nutzer")
    user.find(marker="login-pw").type("geheim")
    user.find("Anmelden").click()
    await user.open("/")


async def test_der_bereich_konto_ist_erreichbar(user: User, app_bereit):
    await _anmelden(user)
    user.find(marker="nav-konto").click()
    await user.should_see("Kontoauszüge einlesen")
    await user.should_see("Noch kein Auszug eingelesen")


async def test_eingelesene_bewegungen_stehen_auf_dem_bildschirm(user: User, app_bereit):
    konto.importieren(GIRO.encode("utf-8-sig"), heute=HEUTE)
    await _anmelden(user)
    user.find(marker="nav-konto").click()
    await user.should_see(marker="konto-monate")
    await user.should_see("Booking.com BV")
    await user.should_see("694,41")        # Eingang Juli, ohne die Umbuchung


# ------------------------------------------------------- Erkennung (AP24)
# Kein Name steht im Programm. Die Zuordnung macht ein Mensch einmal, danach
# erkennt das Werkzeug denselben Empfänger von allein – dieselbe Mechanik, die
# schon bei den Belegen lernt (`stammdaten.kategorie_lernen`).
DAUER = """\
"DKB-Business";"DE62120300001310062102"
"Zeitraum:";"01.01.2026 - 24.07.2026"
"Kontostand vom 24.07.2026:";"5.765,34 €"
""
"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"
"05.07.26";"05.07.26";"Gebucht";"Daniel Steinhauss";"Muster Privatkonto";"Entnahme";"Ausgang";"DE00";"-800";"";"";""
"03.07.26";"03.07.26";"Gebucht";"Daniel Steinhauss";"Stadtkasse Musterstadt";"Beherbergungssteuer Juni";"Ausgang";"DE00";"-341,90";"";"";""
"01.07.26";"01.07.26";"Gebucht";"Daniel Steinhauss";"Rena Textilpflege GmbH";"Wäsche";"Ausgang";"DE00";"-254,00";"";"";""
"01.07.26";"01.07.26";"Gebucht";"Daniel Steinhauss";"Irgendwer Neu GmbH";"Unbekannt";"Ausgang";"DE00";"-42,00";"";"";""
"""


def _bewegungen():
    from app import stammdaten
    stammdaten.erstbefuellung()          # bringt u. a. den Kreditor „Rena"
    konto.importieren(DAUER.encode("utf-8-sig"), heute=HEUTE)
    return {b["gegenpartei"]: b for b in konto.alle()}


def _zuordnen(empfaenger, kategorie):
    """Was in der Oberfläche ein Klick auf die Kategorie ist."""
    from app import buchhaltung, db, stammdaten
    b = _bewegungen()[empfaenger]
    db.speichern(konto.TABELLE, b["id"], dict(
        b, kategorie=kategorie, klasse=buchhaltung.klasse_fuer(kategorie),
        herkunft="hand"))
    stammdaten.kategorie_lernen(empfaenger, kategorie)
    return db.holen(konto.TABELLE, b["id"])


def test_ein_gepflegter_kreditor_wird_auch_auf_dem_konto_erkannt():
    """Dieselbe Erkennung wie bei den Belegen – nur auf dem Empfänger einer
    Kontobewegung. Ohne sie müsste dieselbe Zuordnung zweimal gepflegt werden."""
    b = _bewegungen()["Rena Textilpflege GmbH"]
    assert b["kategorie"] == "Wäscherei (Rena)"
    assert b["klasse"] == "Ausgabe"


def test_unbekanntes_bleibt_leer_statt_geraten():
    """Raten wäre schlimmer als schweigen: eine falsche Kategorie läuft still
    ins Ergebnis."""
    b = _bewegungen()["Irgendwer Neu GmbH"]
    assert not b.get("kategorie")
    assert any(x["gegenpartei"] == "Irgendwer Neu GmbH"
               for x in konto.ohne_zuordnung())


def test_eine_zuordnung_von_hand_wird_gemerkt():
    """Der Kern der Bedienung: einmal zuordnen, danach erkennt es das Werkzeug.
    Ohne das Lernen wäre jeder Monat dieselbe Handarbeit."""
    from app import stammdaten
    _zuordnen("Muster Privatkonto", "Eigenübertrag / Entnahme")
    kategorie, klasse, _h = konto.erkennen(
        {"gegenpartei": "Muster Privatkonto GmbH", "betrag": -50.0})
    assert kategorie == "Eigenübertrag / Entnahme"
    assert klasse == "Privat/prüfen", "Die Klasse muss mitgelernt werden"
    assert stammdaten.kreditor_zu("Muster Privatkonto")["quelle"] == "gelernt"


def test_privatentnahme_faellt_aus_dem_ergebnis():
    """Der größte Einzelposten der echten Daten. Als Ausgabe gezählt, rechnet
    man sich um genau diesen Betrag arm."""
    b = _zuordnen("Muster Privatkonto", "Eigenübertrag / Entnahme")
    assert b["klasse"] == "Privat/prüfen"
    m = konto.monatssummen()["2026-07"]
    assert round(m["eingang"] + m["ausgang"], 2) == -1437.90     # Geldfluss
    assert m["ergebnis"] == -637.90                              # ohne die 800

def test_abgefuehrte_steuer_ist_durchlaufend():
    """Sie war nie ein Erlös und ist auch keine Ausgabe – die Stadt bekommt
    Geld, das der Gast geschuldet hat."""
    assert _zuordnen("Stadtkasse Musterstadt",
                     "Beherbergungssteuer an Stadt (durchlaufender Posten)")["klasse"] == "Durchlaufend"


def test_das_darlehen_wird_zum_pruefen_markiert():
    """Zins und Tilgung stecken in einer Rate. Bis AP22 sie trennt, ist der
    Posten benannt, aber ausdrücklich unfertig."""
    from app import buchhaltung
    assert buchhaltung.klasse_fuer("Darlehensrate Targobank (Zins/Tilgung – aufteilen)") == "Ausgabe/prüfen"


def test_eingaenge_bekommen_keine_kategorie():
    """Was ein Erlös ist, entscheidet erst die Zuordnung zur Rechnung (AP20)
    und die Portalabrechnung (AP23)."""
    konto.importieren(GIRO.encode("utf-8-sig"), heute=HEUTE)
    eingang = next(b for b in konto.alle() if b["betrag"] > 0)
    assert eingang["klasse"] == "Einnahme" and not eingang["kategorie"]


def test_eine_zuordnung_von_hand_wird_nicht_ueberschrieben():
    """Sonst nähme der nächste Lauf jede Korrektur zurück."""
    from app import db
    b = _zuordnen("Irgendwer Neu GmbH", "Strom (SachsenEnergie)")
    konto.zuordnen()
    assert db.holen(konto.TABELLE, b["id"])["kategorie"] == "Strom (SachsenEnergie)"


# ------------------------------------------- Beleg zur Buchung (AP20, Schritt 1)
# Die Frage aus dem Alltag: welche Belege fehlen noch? Sie ist nur brauchbar,
# wenn sie NICHT jede Bewegung ohne Beleg meldet - sonst staenden dort auch
# Privatentnahmen, Loehne und Darlehensraten, also 93 der 122 echten Ausgaenge.
def test_ein_normaler_lieferant_braucht_einen_beleg():
    b = _bewegungen()["Rena Textilpflege GmbH"]
    assert konto.beleg_erwartet(b)
    assert any(x["gegenpartei"] == "Rena Textilpflege GmbH"
               for x in konto.ohne_beleg())


def test_eine_privatentnahme_braucht_keinen():
    """Dafuer stellt niemand eine Rechnung."""
    b = _zuordnen("Muster Privatkonto", "Eigenübertrag / Entnahme")
    assert not konto.beleg_erwartet(b)
    assert not any(x["id"] == b["id"] for x in konto.ohne_beleg())


def test_eine_umbuchung_und_ein_eingang_brauchen_keinen():
    konto.importieren(GIRO.encode("utf-8-sig"), heute=HEUTE)
    for b in konto.alle():
        if b.get("umbuchung") or b["betrag"] > 0:
            assert not konto.beleg_erwartet(b), b["gegenpartei"]


def test_ein_dauerbeleg_am_kreditor_befreit_von_der_belegpflicht():
    """Miete, Darlehen, Software: der Vertrag liegt einmal vor, die monatliche
    Abbuchung braucht kein eigenes Blatt. Genau dafuer gibt es das Feld."""
    from app import stammdaten
    stammdaten.kreditor_anlegen("Beiden und Gareis", "Miete/Raumkosten Wernerstr. 34c (Weitervermietung)",
                                ["beiden und gareis"], dauerbeleg="Mietvertrag vom 1.3.2024")
    b = {"gegenpartei": "Beiden und Gareis Immobilien", "betrag": -1213.0,
         "klasse": "Ausgabe"}
    assert not konto.beleg_erwartet(b)


def test_von_hand_abgehakt_verschwindet_aus_der_liste():
    """Ohne diesen Weg bliebe jede Ausnahme fuer immer stehen - und eine Liste,
    die man nicht leer bekommt, hoert man auf zu lesen."""
    b = _bewegungen()["Rena Textilpflege GmbH"]
    assert konto.beleg_erwartet(b)
    nachher = konto.beleg_nicht_noetig(b["id"])
    assert not konto.beleg_erwartet(nachher)
    assert not any(x["id"] == b["id"] for x in konto.ohne_beleg())


def test_ein_zugeordneter_beleg_verschwindet_aus_der_liste():
    b = _bewegungen()["Rena Textilpflege GmbH"]
    konto.beleg_setzen(b["id"], "beleg-1")
    assert not any(x["id"] == b["id"] for x in konto.ohne_beleg())
    # und laesst sich wieder loesen
    konto.beleg_setzen(b["id"], "")
    assert any(x["id"] == b["id"] for x in konto.ohne_beleg())


def test_unzugeordnetes_steht_noch_nicht_in_der_belegliste():
    """Erst zuordnen, dann Beleg. Solange nicht feststeht, WAS die Buchung ist,
    laesst sich nicht sagen, ob es dazu einen Beleg gibt – eine Privatentnahme
    sieht auf dem Auszug aus wie jede andere Abbuchung.

    An den echten Daten waeren es sonst 121 von 122 Ausgaengen: wieder eine
    Liste, die immer rot ist. Die unzugeordneten stehen ohnehin in ihrer
    eigenen Liste (`ohne_zuordnung`)."""
    b = _bewegungen()["Irgendwer Neu GmbH"]
    assert not b.get("kategorie")
    assert not konto.beleg_erwartet(b)
    assert any(x["id"] == b["id"] for x in konto.ohne_zuordnung()), \
        "sie darf nicht ganz verschwinden, nur in der anderen Liste stehen"


def test_die_liste_meldet_nicht_alles():
    """Die Probe: von den zugeordneten Ausgaengen brauchen nicht alle einen
    Beleg. Meldete die Liste jeden, waere sie unbrauchbar."""
    _zuordnen("Muster Privatkonto", "Eigenübertrag / Entnahme")
    _zuordnen("Stadtkasse Musterstadt", "Beherbergungssteuer an Stadt (durchlaufender Posten)")
    fehlen = {x["gegenpartei"] for x in konto.ohne_beleg()}
    assert "Rena Textilpflege GmbH" in fehlen, "ein Lieferant braucht einen Beleg"
    assert "Muster Privatkonto" not in fehlen
    assert "Stadtkasse Musterstadt" not in fehlen
