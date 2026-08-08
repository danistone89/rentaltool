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


def test_eine_spaeter_ausgestellte_rechnung_bleibt_kandidat():
    """**Der Denkfehler, den die Praxis aufgedeckt hat.** Eine fruehere Fassung
    schloss Rechnungen aus, die nach dem Zahltag ausgestellt wurden. Das schien
    plausibel und war falsch: Gaeste zahlen VOR dem Aufenthalt, die Rechnung
    folgt danach.

    An den echten Daten trugen alle 48 Rechnungen den Tag ihrer Erstellung
    (7.8.2026), waehrend die Zahlungen von Januar bis Juli reichten - die Regel
    verwarf damit JEDEN Kandidaten. Fuer die Zahlung der Familie Ernst vom
    11.6. wurden null Rechnungen vorgeschlagen, obwohl die passende vorlag."""
    _rechnung(60, "Anja Ernst", 400.07, datum="2026-08-07")
    b = _bewegung(400.07, "Buchung Cottaer Strase Fam. Ernst",
                  datum="2026-06-11", gegenpartei="ERNST SASCHA U ANJA")
    liste = vs.kandidaten(b)
    assert liste, "die Rechnung muss vorgeschlagen werden"
    assert liste[0]["rechnung"]["gast"] == "Anja Ernst"
    assert liste[0]["namenstreffer"]


def test_der_aufenthalt_sortiert_naeher_als_das_rechnungsdatum():
    """Sortiert wird ueber den Aufenthalt - der haengt mit der Zahlung
    zusammen, das Ausstellungsdatum nicht."""
    from app import db
    for r, an, ab in ((97, "2026-06-08", "2026-06-12"), (98, "2026-11-01", "2026-11-05")):
        satz = _rechnung(r, f"Gast{r}", 100.0, datum="2026-08-07")
        db.speichern("rechnungen", satz["id"], dict(satz, anreise=an, abreise=ab))
    liste = vs.kandidaten(_bewegung(100.0, datum="2026-06-11"))
    assert liste[0]["rechnung"]["gast"] == "Gast97"


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


# ------------------------------------------------- Die Provisionsprobe (B4)
def test_der_rest_ist_die_provision():
    """Sobald alle Rechnungen zugeordnet sind, IST der Rest die einbehaltene
    Provision – und Smoobu kennt sie, also laesst sie sich nachrechnen."""
    r1 = _rechnung(41, "Meier", 620.00)
    r2 = _rechnung(42, "Schulz", 540.00)
    b = _bewegung(1080.70, bid="ab1")
    buchungen = {941: {"commission-included": 45.30},
                 942: {"commission-included": 34.00}}
    # Gebucht wird der RECHNUNGSBETRAG, nicht die Auszahlung - sonst waere der
    # Umsatz um die Provision zu niedrig und die Provision taeuchte nie auf.
    for r in (r1, r2):
        z.hinzufuegen(b["id"], z.RECHNUNG,
                      r["summen"]["brutto"], ziel_id=r["id"])
    rest, erwartet, stimmt = vs.provisionsprobe(b, buchungen)
    assert rest == -79.30 and erwartet == -79.30 and stimmt


def test_eine_fehlende_rechnung_faellt_bei_der_probe_auf():
    """Der eigentliche Wert: ein Knopf, der den Rest stillschweigend glattzieht,
    versteckt genau die Faelle, die man pruefen muesste."""
    r1 = _rechnung(41, "Meier", 620.00)
    _rechnung(42, "Schulz", 540.00)          # nicht zugeordnet
    b = _bewegung(1080.70, bid="ab2")
    buchungen = {941: {"commission-included": 45.30},
                 942: {"commission-included": 34.00}}
    z.hinzufuegen(b["id"], z.RECHNUNG, r1["summen"]["brutto"], ziel_id=r1["id"])
    rest, erwartet, stimmt = vs.provisionsprobe(b, buchungen)
    assert not stimmt, "der Rest ist groesser als die Provision der einen Rechnung"
    assert erwartet == -45.30 and rest == 460.70


def test_ohne_provisionsangabe_bleibt_die_probe_still():
    """Direktzahler: keine Provision, kein Befund."""
    r = _rechnung(74, "Gockel", 379.48)
    b = _bewegung(379.48, bid="ab3")
    z.hinzufuegen(b["id"], z.RECHNUNG, 379.48, ziel_id=r["id"])
    rest, erwartet, stimmt = vs.provisionsprobe(b, {})
    assert (rest, erwartet, stimmt) == (0.0, 0.0, True)
