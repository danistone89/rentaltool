"""AP13: Produkte, Preise und Kreditoren.

Der Test, der hier am meisten trägt, ist `test_der_preis_haengt_am_buchungstag`.
Die Reinigungsgebühr der Cottaer Straße stieg von 65 € auf 75 € – aber welcher
Preis gilt, hängt am **Buchungsdatum**, nicht am Aufenthalt. Am Anreisedatum
sortiert sieht dieselbe Reihe aus wie Zufall: die Beträge springen neunzehnmal
hin und her. Wer die Frage falsch stellt, rechnet alte Rechnungen falsch nach –
und merkt es nie, weil beide Zahlen plausibel aussehen.
"""
import pytest

from app import stammdaten as st

COTTAER, WERNER = 2748963, 2960031


@pytest.fixture
def reinigung():
    """Die echten Preisstände aus den Smoobu-Daten (gemessen am 7.8.2026)."""
    p = st.produkt_anlegen("Endreinigung", st.FEST, 0.07)
    st.preis_setzen(p["id"], COTTAER, "2020-01-01", 65)
    st.preis_setzen(p["id"], COTTAER, "2026-01-04", 75)
    st.preis_setzen(p["id"], WERNER, "2020-01-01", 95)
    return p["id"]


# ------------------------------------------------------------------ Preise
@pytest.mark.parametrize("gebucht,erwartet", [
    ("2025-06-08", 65.0),    # ältester Fall in den Daten
    ("2026-01-03", 65.0),    # Tag davor
    ("2026-01-04", 75.0),    # der Umstellungstag selbst zählt schon neu
    ("2026-08-07", 75.0),
])
def test_der_preis_haengt_am_buchungstag(reinigung, gebucht, erwartet):
    assert st.preis_am(reinigung, COTTAER, gebucht) == erwartet


def test_zwei_gaeste_im_selben_monat_zahlen_verschieden(reinigung):
    """Genau der Fall, der am Anreisedatum wie Zufall aussieht: beide reisen im
    Februar an, aber einer hat im Dezember gebucht und der andere im Januar."""
    frueh = st.preis_am(reinigung, COTTAER, "2025-12-20")
    spaet = st.preis_am(reinigung, COTTAER, "2026-01-15")
    assert (frueh, spaet) == (65.0, 75.0)


def test_ohne_hinterlegten_preis_kommt_nichts(reinigung):
    """Lieber keine Zahl als eine erfundene – die Rechnung soll stocken,
    nicht raten."""
    assert st.preis_am(reinigung, 999999, "2026-08-07") is None


def test_vor_dem_ersten_preis_gilt_keiner(reinigung):
    assert st.preis_am(reinigung, COTTAER, "2019-12-31") is None


def test_ohne_datum_keine_antwort(reinigung):
    assert st.preis_am(reinigung, COTTAER, "") is None
    assert st.preis_am(reinigung, COTTAER, None) is None


def test_derselbe_stichtag_ersetzt_statt_zu_verdoppeln(reinigung):
    """Zwei Preise mit demselben „ab" wären ein Widerspruch, den später niemand
    auflöst."""
    st.preis_setzen(reinigung, COTTAER, "2026-01-04", 80)
    assert st.preis_am(reinigung, COTTAER, "2026-06-01") == 80.0
    assert len(st.preisverlauf(reinigung, COTTAER)) == 2


def test_preis_entfernen_faellt_auf_den_vorigen_zurueck(reinigung):
    st.preis_entfernen(reinigung, COTTAER, "2026-01-04")
    assert st.preis_am(reinigung, COTTAER, "2026-08-07") == 65.0


def test_preisverlauf_steht_chronologisch(reinigung):
    verlauf = st.preisverlauf(reinigung, COTTAER)
    assert [x["ab"] for x in verlauf] == ["2020-01-01", "2026-01-04"]
    assert [x["betrag"] for x in verlauf] == [65.0, 75.0]


def test_wohnungen_stoeren_sich_nicht(reinigung):
    assert st.preis_am(reinigung, WERNER, "2026-08-07") == 95.0


# ---------------------------------------------------------------- Produkte
def test_die_drei_arten_kommen_aus_der_erstbefuellung():
    st.erstbefuellung()
    arten = {p["art"] for p in st.produkte()}
    assert arten == {st.BEHERBERGUNG, st.FEST, st.DURCHLAUFEND}


def test_erstbefuellung_legt_nichts_doppelt_an():
    st.erstbefuellung()
    vorher = len(st.produkte()), len(st.kreditoren())
    neu = st.erstbefuellung()
    assert (len(st.produkte()), len(st.kreditoren())) == vorher
    assert neu == {"produkte": [], "kreditoren": []}


def test_die_beherbergungssteuer_traegt_keine_umsatzsteuer():
    """Sie ist ein durchlaufender Posten – Steuer auf Steuer gäbe es sonst."""
    st.erstbefuellung()
    p = st.produkt_der_art(st.DURCHLAUFEND)
    assert p["steuersatz"] == 0.0


def test_neunzehn_prozent_sind_vorgesehen():
    """Nicht in Gebrauch, aber möglich: ein künftiges Produkt braucht dann eine
    Zahl und keinen Umbau."""
    assert 0.19 in st.STEUERSAETZE
    p = st.produkt_anlegen("Stellplatz", st.FEST, 0.19)
    assert st.produkt(p["id"])["steuersatz"] == 0.19


def test_produkt_aendern_laesst_die_preise_stehen(reinigung):
    st.produkt_aendern(reinigung, name="Endreinigung (neu)")
    assert st.produkt(reinigung)["name"] == "Endreinigung (neu)"
    assert st.preis_am(reinigung, COTTAER, "2026-08-07") == 75.0


# -------------------------------------------------------------- Kreditoren
@pytest.fixture
def lieferanten():
    st.erstbefuellung()


@pytest.mark.parametrize("haendler,erwartet", [
    ("ROSSMANN 2540", "Drogerie/Verbrauch (Rossmann)"),
    ("Rossmann Filiale Dresden", "Drogerie/Verbrauch (Rossmann)"),
    ("dm-drogerie markt GmbH + Co. KG", "Reinigung/Verbrauch (dm)"),
    ("Rena Textilpflege GmbH", "Wäscherei (Rena)"),
    ("JYSK SE", "Ausstattung/GWG (JYSK)"),
    ("SachsenEnergie Versorgung GmbH", "Strom (SachsenEnergie)"),
    ("DREWAG-Stadtwerke DD GmbH", "Wasser/Nebenkosten (DREWAG)"),
])
def test_bekannte_lieferanten_bringen_ihre_kategorie_mit(lieferanten, haendler, erwartet):
    """Die eigentliche Zeitersparnis: wer einmal zugeordnet ist, wird wieder
    erkannt – auch mit Filialnummer und Rechtsform im Namen."""
    kategorie, _wohnung, _k = st.vorbelegung(haendler)
    assert kategorie == erwartet


def test_unbekannter_haendler_bekommt_keine_kategorie(lieferanten):
    """Raten wäre schlimmer als nichts – eine falsche Kategorie läuft still in
    die EÜR."""
    assert st.vorbelegung("ALDI SUED")[0] == ""
    assert st.kreditor_zu("Irgendein Laden") is None


def test_leerer_haendler_stuerzt_nicht_ab(lieferanten):
    assert st.kreditor_zu("") is None
    assert st.kreditor_zu(None) is None


def test_das_laengste_muster_gewinnt():
    """Sonst verdrängte ein kurzes „dm" den Kreditor „dm drogerie markt",
    sobald beide angelegt sind."""
    st.kreditor_anlegen("Kurz", "Kategorie kurz", ["dm"])
    st.kreditor_anlegen("Lang", "Kategorie lang", ["dm drogerie markt"])
    assert st.kreditor_zu("dm drogerie markt GmbH")["name"] == "Lang"


def test_kreditor_traegt_kostenstelle_und_dauerbeleg():
    """Beides braucht AP15: die Wohnung für die Kennzahlen, der Dauerbeleg,
    damit die Miete nicht jeden Monat nach einem Beleg fragt."""
    k = st.kreditor_anlegen("Beiden und Gareis", "Miete/Raumkosten Wernerstr. 34c (Weitervermietung)",
                            ["beiden und gareis"], wohnung=WERNER,
                            dauerbeleg="Mietvertrag vom 1.3.2024")
    kategorie, wohnung, treffer = st.vorbelegung("Beiden und Gareis Immobilien")
    assert wohnung == WERNER
    assert treffer["dauerbeleg"].startswith("Mietvertrag")
    assert kategorie.startswith("Miete/Raumkosten")


def test_kreditor_aendern_normalisiert_die_muster():
    k = st.kreditor_anlegen("Test", "Kategorie", ["ALT"])
    st.kreditor_aendern(k["id"], muster=["  NEU  ", "", "Zweites"])
    assert st.kreditor(k["id"])["muster"] == ["neu", "zweites"]


def test_geloeschter_kreditor_wird_nicht_mehr_erkannt(lieferanten):
    k = st.kreditor_zu("ROSSMANN 2540")
    st.kreditor_loeschen(k["id"])
    assert st.kreditor_zu("ROSSMANN 2540") is None


# --------------------------------------------------------------- Oberfläche
from nicegui.testing import User            # noqa: E402
from app import auth, data, mailer, receipts, web   # noqa: E402


@pytest.fixture
def app_bereit(monkeypatch):
    monkeypatch.setattr(data, "get_apartments", lambda: [
        {"id": COTTAER, "name": "Cottaer Straße"}, {"id": WERNER, "name": "Wernerstraße"}])
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


async def test_einstellungen_haben_einen_reiter_fuer_stammdaten(user: User, app_bereit):
    await _anmelden(user)
    user.find(marker="nav-einstellungen").click()
    await user.should_see(marker="panel-stammdaten")
    # Ohne angelegte Produkte steht dort der Weg dorthin, nicht eine leere Liste.
    await user.should_see(marker="stammdaten-vorgaben")


async def test_vorgaben_anlegen_fuellt_produkte_und_kreditoren(user: User, app_bereit):
    await _anmelden(user)
    user.find(marker="nav-einstellungen").click()
    user.find(marker="stammdaten-vorgaben").click()
    assert len(st.produkte()) == 3
    assert st.kreditor_zu("ROSSMANN 2540") is not None


def test_neuer_beleg_erbt_die_kategorie_seines_lieferanten(app_bereit):
    """Die eigentliche Zeitersparnis – und der Grund, warum die Stammdaten
    zuerst kommen."""
    st.erstbefuellung()
    kategorie, _wohnung, _k = st.vorbelegung("ROSSMANN 2540 DRESDEN")
    r = receipts.add_receipt("vale", photo=None, merchant="ROSSMANN 2540 DRESDEN",
                             kategorie=kategorie)
    assert receipts.list_receipts()[0]["kategorie"] == "Drogerie/Verbrauch (Rossmann)"
    assert r["kategorie"] == "Drogerie/Verbrauch (Rossmann)"


def test_kreditor_ohne_treffer_laesst_die_kategorie_leer(app_bereit):
    st.erstbefuellung()
    kategorie, _w, _k = st.vorbelegung("Irgendein Laden GmbH")
    assert kategorie == ""


async def test_preis_eintragen_speichert_ihn(user: User, app_bereit):
    """Der Fehler vom 7.8.2026: das Feld war ein `ui.number`, und der getippte
    Wert kam beim Klick auf „+" nicht am Server an – die Meldung blieb aus, der
    Preis auch. Im echten Browser nachgestellt: mit `ui.number` kein Eintrag,
    mit `ui.input` einer."""
    from nicegui import ui as _ui
    st.erstbefuellung()
    await _anmelden(user)
    user.find(marker="nav-einstellungen").click()
    await user.should_see(marker=f"preis-betrag-{COTTAER}")

    with user.client:
        feld = next(iter(user.find(marker=f"preis-betrag-{COTTAER}").elements))
        assert isinstance(feld, _ui.input), \
            "Zahlenfelder schlucken die Eingabe – hier gehoert ein Textfeld hin"
        feld.value = "65,00"          # deutsche Schreibweise
    user.find(marker=f"preis-setzen-{COTTAER}").click()

    p = st.produkt_der_art(st.FEST)
    assert st.preisverlauf(p["id"], COTTAER), "Preis wurde nicht gespeichert"
    assert st.preisverlauf(p["id"], COTTAER)[0]["betrag"] == 65.0


async def test_deutsche_und_englische_schreibweise_gehen_beide(user: User, app_bereit):
    from nicegui import ui as _ui
    st.erstbefuellung()
    await _anmelden(user)
    user.find(marker="nav-einstellungen").click()
    await user.should_see(marker=f"preis-betrag-{WERNER}")
    with user.client:
        next(iter(user.find(marker=f"preis-betrag-{WERNER}").elements)).value = "95.50"
    user.find(marker=f"preis-setzen-{WERNER}").click()
    p = st.produkt_der_art(st.FEST)
    assert st.preisverlauf(p["id"], WERNER)[0]["betrag"] == 95.5


async def test_ohne_betrag_sagt_es_die_oberflaeche(user: User, app_bereit):
    st.erstbefuellung()
    await _anmelden(user)
    user.find(marker="nav-einstellungen").click()
    await user.should_see(marker=f"preis-setzen-{COTTAER}")
    user.find(marker=f"preis-setzen-{COTTAER}").click()
    await user.should_see("Bitte einen Betrag eintragen")
    p = st.produkt_der_art(st.FEST)
    assert st.preisverlauf(p["id"], COTTAER) == []
