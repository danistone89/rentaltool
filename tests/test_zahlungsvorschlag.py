"""B3: welche Rechnungen könnten zu dieser Zahlung gehören?

Der Befund, der dieses Paket bestimmt (siehe `docs/konzept-bankbuchhaltung.md`):
**Von 65 Zahlungseingängen entspricht genau EINER exakt einem
Rechnungsbetrag.** Booking und Airbnb zahlen netto nach Provision aus, und die
Reservierungsnummer steht nicht im Verwendungszweck – dort steht nur die
Wohnung. Deshalb sortiert das Werkzeug vor, statt zu buchen.
"""
import pytest

from app import konto, rechnung, zahlungsvorschlag as vs, zuordnung as z


def _rechnung(nr, gast, brutto, datum="2026-01-05", wohnung=1, status=None):
    from app import db
    satz = {"id": f"r{nr}", "nummer": str(nr), "gast": gast, "datum": datum,
            "wohnung": wohnung, "wohnung_name": "Cottaer Straße",
            "buchung": 900 + nr, "status": status or rechnung.FESTGESCHRIEBEN,
            "summen": {"brutto": brutto, "netto": 0, "ust": 0, "durchlaufend": 0}}
    db.anlegen("rechnungen", satz)
    return satz


def _bewegung(betrag, text="", bid="b1", datum="2026-01-12", gegenpartei="Booking.com BV"):
    from app import db
    satz = {"id": bid, "datum": datum, "betrag": betrag, "gegenpartei": gegenpartei,
            "text": text, "konto": "giro", "umbuchung": False}
    db.anlegen(konto.TABELLE, satz)
    return satz


# ------------------------------------------------------------- Die Kennung
def test_die_portal_kennung_wird_gelesen():
    b = _bewegung(314.93, "NO.bbqETYstLU6QDo85/ID.14005823")
    assert vs.kennung(b) == "14005823"


def test_ohne_kennung_kein_absturz():
    assert vs.kennung(_bewegung(100.0, "Buchung Katarina Gockel")) == ""
    assert vs.kennung({}) == ""


def test_die_wohnung_hinter_der_kennung_wird_gelernt():
    """Booking nennt seine eigene Objektnummer. Welche Wohnung das ist, weiß
    nur der Betrieb – und sagt es, indem er einmal zuordnet."""
    cfg = {}
    vs.kennung_lernen(cfg, "14005823", 2748963)
    assert vs.wohnung_zu_kennung("14005823", cfg) == 2748963
    assert vs.wohnung_zu_kennung("99999999", cfg) == ""


# ------------------------------------------------- Der erwartete Betrag
def test_der_erwartete_betrag_zieht_die_provision_ab():
    """Smoobu liefert sie je Buchung. Ohne den Abzug zählte der Rest beim
    Abhaken nicht sauber herunter."""
    r = _rechnung(41, "Meier", 620.00)
    betrag, provision = vs.erwartet(r, {941: {"commission-included": 89.30}})
    assert (betrag, provision) == (530.70, 89.30)


def test_ohne_provision_gilt_der_rechnungsbetrag():
    """Der Direktzahler-Fall: der Gast überweist, kein Portal dazwischen."""
    r = _rechnung(74, "Gockel", 379.48)
    assert vs.erwartet(r, {}) == (379.48, 0.0)


# ----------------------------------------------------------- Die Kandidaten
def test_der_name_im_verwendungszweck_steht_oben():
    """Bei Direktzahlern das einzige verlässliche Merkmal."""
    _rechnung(70, "Schulz", 500.0)
    _rechnung(74, "Gockel", 379.48)
    b = _bewegung(379.48, "Buchung Katarina Gockel Cottaer Straße",
                 gegenpartei="Gockel, Katarina")
    liste = vs.kandidaten(b)
    assert liste[0]["rechnung"]["gast"] == "Gockel"
    assert liste[0]["namenstreffer"] and liste[0]["grund"] == "Name im Verwendungszweck"


def test_die_gelernte_wohnung_sortiert_vor():
    """Die Kennung sagt nicht, welche Buchung gemeint ist – aber sie halbiert
    die Liste."""
    _rechnung(70, "Schulz", 500.0, wohnung=2)
    _rechnung(71, "Meier", 400.0, wohnung=1)
    cfg = {}
    vs.kennung_lernen(cfg, "14005823", 1)
    b = _bewegung(300.0, "NO.abc/ID.14005823")
    liste = vs.kandidaten(b, cfg)
    assert liste[0]["rechnung"]["gast"] == "Meier" and liste[0]["wohnung"]


def test_der_grund_steht_dabei():
    """Ein Vorschlag, den man nicht nachvollziehen kann, wird entweder blind
    übernommen oder ignoriert."""
    _rechnung(70, "Schulz", 500.0)
    assert vs.kandidaten(_bewegung(500.0))[0]["grund"] == "offen"


def test_entwuerfe_und_stornos_warten_auf_kein_geld():
    _rechnung(80, "Entwurf", 100.0, status=rechnung.ENTWURF)
    _rechnung(81, "Storno", 100.0, status=rechnung.STORNIERT)
    _rechnung(82, "Offen", 100.0)
    assert [r["gast"] for r in vs.offene()] == ["Offen"]


def test_eine_zugeordnete_rechnung_ist_bezahlt_und_verschwindet():
    """Sonst böte das Werkzeug dieselbe Rechnung zweimal an."""
    r = _rechnung(90, "Bezahlt", 200.0)
    b = _bewegung(200.0, bid="bz")
    assert not vs.ist_bezahlt(r)
    z.hinzufuegen(b["id"], z.RECHNUNG, 200.0, ziel_id=r["id"])
    assert vs.ist_bezahlt(r)
    assert r["id"] not in [x["id"] for x in vs.offene()]


def test_eine_spaetere_rechnung_kann_nicht_gemeint_sein():
    """Wer am 12. zahlt, kann keine Rechnung vom 20. begleichen."""
    _rechnung(95, "Spaeter", 100.0, datum="2026-01-20")
    _rechnung(96, "Frueher", 100.0, datum="2026-01-02")
    liste = vs.kandidaten(_bewegung(100.0, datum="2026-01-12"))
    assert [k["rechnung"]["gast"] for k in liste] == ["Frueher"]


def test_ohne_offene_rechnungen_bleibt_die_liste_leer():
    assert vs.kandidaten(_bewegung(100.0)) == []


@pytest.mark.parametrize("text,erwartet", [
    ("Buchung Katarina Gockel Cottaer Straße", True),
    ("NO.abc/ID.14005823", False),
    ("", False),
])
def test_namenserkennung_greift_nur_bei_echten_namen(text, erwartet):
    """Kurze Wortstücke und Zahlen dürfen nicht als Name durchgehen – sonst
    stünde jede Rechnung ganz oben."""
    _rechnung(74, "Gockel", 379.48)
    assert vs.kandidaten(_bewegung(379.48, text))[0]["namenstreffer"] is erwartet
