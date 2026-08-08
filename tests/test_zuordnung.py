"""B1: die Zuordnung als eigener Satz.

Der Grund für den Umbau steht in `docs/konzept-bankbuchhaltung.md`: Vorher hing
an einer Bewegung je EIN Feld (`beleg_id`, `rechnung_id`). Eine Airbnb-
Auszahlung über 1.794,13 € für drei Buchungen plus Provisionsbeleg liess sich
damit nicht ausdrücken – und das ist nicht die Ausnahme, sondern der Normalfall:
51 von 65 Zahlungseingängen der echten Daten sind Sammelauszahlungen.

Der Restbetrag ist die ganze Mechanik. Ist er null, ist die Bewegung fertig.
"""
import pytest

from app import konto, zuordnung as z


def _bewegung(betrag, bid="b1", **felder):
    from app import db
    satz = {"id": bid, "datum": "2026-01-12", "betrag": betrag,
            "gegenpartei": "Airbnb", "text": "", "konto": "giro",
            "umbuchung": False}
    satz.update(felder)
    db.anlegen(konto.TABELLE, satz)
    return satz


# ------------------------------------------------------------- Der Kernfall
def test_eine_auszahlung_traegt_mehrere_rechnungen_und_die_provision():
    """Der Fall, für den das ganze Paket gebaut wird.

    1.794,13 € kommen an. Die Rechnungen summieren sich auf 1.940,00 € – mehr
    als angekommen ist, weil Airbnb die Provision einbehält. Erst der
    Provisionsposten über −145,87 € bringt den Rest auf null.
    """
    b = _bewegung(1794.13)
    for nr, betrag in (("41", 620.00), ("42", 540.00), ("43", 780.00)):
        z.hinzufuegen(b["id"], z.RECHNUNG, betrag, "Einnahmen Airbnb", ziel_id=nr)
    assert z.rest(b) == -145.87, "so viel hat Airbnb einbehalten"
    assert not z.ist_fertig(b)

    z.hinzufuegen(b["id"], z.BELEG, -145.87, "Portalprovision", ziel_id="prov-01")
    assert z.rest(b) == 0.0
    assert z.ist_fertig(b)
    assert len(z.posten(b["id"])) == 4


def test_der_einfache_fall_ist_kein_sonderfall():
    """Ein Gast überweist genau den Rechnungsbetrag – eine Bewegung mit genau
    einem Posten. Dafür braucht es keine eigene Mechanik."""
    b = _bewegung(379.48)
    z.hinzufuegen(b["id"], z.RECHNUNG, 379.48, "Einnahmen Direktbuchung", ziel_id="74")
    assert z.ist_fertig(b) and z.rest(b) == 0.0


def test_eine_ausgabe_mit_zwei_belegen():
    """Eine Sammelabbuchung, zu der zwei Rechnungen gehören."""
    b = _bewegung(-254.00)
    z.hinzufuegen(b["id"], z.BELEG, -200.00, "Wäscherei (Rena)", ziel_id="r1")
    assert z.rest(b) == -54.0
    z.hinzufuegen(b["id"], z.BELEG, -54.00, "Wäscherei (Rena)", ziel_id="r2")
    assert z.ist_fertig(b)


def test_ein_posten_ohne_gegenstueck_ist_erlaubt():
    """Eine Bankgebühr braucht keinen Beleg, soll aber eine Kategorie tragen."""
    b = _bewegung(-4.90)
    satz, _m = z.hinzufuegen(b["id"], z.KATEGORIE, -4.90, "Kontoführung/Bankgebühr DKB")
    assert satz is not None
    assert z.ist_fertig(b)


# ------------------------------------------------------------------ Prüfungen
def test_ohne_gegenstueck_geht_rechnung_und_beleg_nicht():
    b = _bewegung(-10.0)
    for art in (z.RECHNUNG, z.BELEG):
        satz, meldung = z.hinzufuegen(b["id"], art, -10.0, "X", ziel_id="")
        assert satz is None and "Gegenstück" in meldung


@pytest.mark.parametrize("betrag", [0, 0.0, "0,00", "keine Zahl", None])
def test_ein_posten_ueber_null_wird_abgelehnt(betrag):
    """Er sagt nichts und macht den Restbetrag nur unübersichtlich."""
    b = _bewegung(-10.0)
    assert z.hinzufuegen(b["id"], z.KATEGORIE, betrag, "X")[0] is None


def test_eine_unbekannte_art_wird_abgelehnt():
    b = _bewegung(-10.0)
    assert z.hinzufuegen(b["id"], "irgendwas", -5.0)[0] is None


def test_die_summe_darf_den_betrag_uebersteigen():
    """**Kein Fehler, sondern der Grund für den Provisionsposten.** Wer hier
    begrenzt, macht die Portalabrechnung unmöglich."""
    b = _bewegung(1000.0)
    satz, _m = z.hinzufuegen(b["id"], z.RECHNUNG, 1200.0, "Einnahmen", ziel_id="1")
    assert satz is not None
    assert z.rest(b) == -200.0


def test_cent_reste_gelten_als_fertig():
    """Beim Runden der Einzelpositionen bleibt gelegentlich ein Cent übrig. Wer
    auf 0,00 besteht, macht die Maske unbenutzbar."""
    b = _bewegung(100.00)
    z.hinzufuegen(b["id"], z.RECHNUNG, 99.996, "X", ziel_id="1")
    assert z.ist_fertig(b)


# ------------------------------------------------------------------- Wege
def test_posten_lassen_sich_einzeln_und_gesammelt_loesen():
    b = _bewegung(-100.0)
    a, _m = z.hinzufuegen(b["id"], z.BELEG, -60.0, "X", ziel_id="r1")
    z.hinzufuegen(b["id"], z.BELEG, -40.0, "X", ziel_id="r2")
    z.entfernen(a["id"])          # -60 faellt weg, -40 bleibt zugeordnet
    assert z.rest(b) == -60.0
    z.entfernen_zu(b["id"])
    assert z.posten(b["id"]) == [] and z.rest(b) == -100.0


def test_der_umgekehrte_weg_findet_die_bewegung():
    """Für die Frage „ist diese Rechnung bezahlt?" – vom Beleg zur Zahlung."""
    b = _bewegung(500.0, bid="bx")
    z.hinzufuegen(b["id"], z.RECHNUNG, 500.0, "X", ziel_id="rg-7")
    assert z.bewegung_zu(z.RECHNUNG, "rg-7") == "bx"
    assert z.bewegung_zu(z.RECHNUNG, "gibtsnicht") == ""


def test_zwei_bewegungen_stoeren_sich_nicht():
    a = _bewegung(-10.0, bid="a")
    c = _bewegung(-20.0, bid="c")
    z.hinzufuegen(a["id"], z.KATEGORIE, -10.0, "X")
    assert z.ist_fertig(a) and not z.ist_fertig(c)


# --------------------------------------------------------------- Übernahme
def test_alte_zuordnungen_gehen_nicht_verloren():
    """Beim Modellwechsel darf keine bereits geleistete Arbeit wegfallen."""
    b = _bewegung(-254.0, beleg_id="alt-1", kategorie="Wäscherei (Rena)")
    assert z.uebernehmen_aus_feldern([b]) == 1
    p = z.posten(b["id"])
    assert len(p) == 1 and p[0]["ziel_id"] == "alt-1"
    assert p[0]["betrag"] == -254.0 and p[0]["kategorie"] == "Wäscherei (Rena)"
    assert z.ist_fertig(b)


def test_die_uebernahme_laeuft_zweimal_ohne_schaden():
    b = _bewegung(-254.0, beleg_id="alt-1")
    z.uebernehmen_aus_feldern([b])
    assert z.uebernehmen_aus_feldern([b]) == 0
    assert len(z.posten(b["id"])) == 1


def test_konto_beleg_setzen_erzeugt_einen_posten():
    """Der bequeme Weg für den einfachen Fall bleibt – er legt jetzt aber einen
    Posten an statt ein Feld zu setzen."""
    b = _bewegung(-95.0, bid="bk")
    konto.beleg_setzen("bk", "beleg-9")
    assert konto.belege_von(b) == ["beleg-9"]
    assert z.ist_fertig(b), "der volle Betrag ist zugeordnet"
    konto.beleg_setzen("bk", "")
    assert konto.belege_von(b) == [] and not z.ist_fertig(b)
