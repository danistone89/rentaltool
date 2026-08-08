"""B4b: das Verrechnungskonto je Plattform.

Booking und Airbnb zahlen gesammelt und netto aus. Zwischen der Rechnung an den
Gast und dem Geld auf dem Konto liegen Wochen und eine einbehaltene Provision.
Ohne laufende Rechnung darüber sieht niemand, ob ein Monat aufgeht – genau
dafür führt das Steuerbüro ein Verrechnungskonto.

Hier ist es **abgeleitet**, nicht doppelt gebucht: derselbe Saldo, eine Quelle.
"""
from app import konto, verrechnung as v, zuordnung as z


def _bewegung(betrag, gegenpartei, bid, datum="2026-06-12", text=""):
    from app import db
    satz = {"id": bid, "datum": datum, "betrag": betrag, "gegenpartei": gegenpartei,
            "text": text, "konto": "giro", "umbuchung": False}
    db.anlegen(konto.TABELLE, satz)
    return satz


def _rechnung(nr, gast, brutto):
    from app import db, rechnung
    satz = {"id": f"r{nr}", "nummer": f"2026-{nr:04d}", "gast": gast,
            "datum": "2026-06-01", "status": rechnung.FESTGESCHRIEBEN,
            "summen": {"brutto": brutto, "netto": 0, "ust": 0, "durchlaufend": 0}}
    db.anlegen("rechnungen", satz)
    return satz


# ------------------------------------------------------------- Die Plattform
def test_die_plattform_wird_am_zahlungseingang_erkannt():
    assert v.plattform_von(_bewegung(500.0, "Booking.com BV", "b1")) == "booking"
    assert v.plattform_von(_bewegung(500.0, "Airbnb", "b2",
                                     text="AWV-MELDEPFLICHT")) == "airbnb"
    assert v.plattform_von(_bewegung(500.0, "Gockel, Katarina", "b3")) == ""


# --------------------------------------------------------- Das Kontoblatt
def test_ein_aufgehender_monat_hat_saldo_null():
    """Rechnungen rein, Provision und Auszahlung raus – in Summe null.
    Genau die Kontrolle, die das Verrechnungskonto leistet."""
    r1, r2 = _rechnung(31, "Meier", 620.00), _rechnung(32, "Schulz", 540.00)
    b = _bewegung(1014.13, "Booking.com BV", "bk1")
    z.hinzufuegen(b["id"], z.RECHNUNG, 620.00, ziel_id=r1["id"])
    z.hinzufuegen(b["id"], z.RECHNUNG, 540.00, ziel_id=r2["id"])
    z.hinzufuegen(b["id"], z.KATEGORIE, -145.87, "Portalprovision")
    assert v.saldo("booking") == 0.0


def test_eine_unzugeordnete_auszahlung_steht_im_saldo():
    """Der Gewinn gegenueber dem reinen Restbetrag einer einzelnen Bewegung:
    Geld ist gekommen, das durch keine Rechnung gedeckt ist. Wer nur auf die
    Bewegung sieht, haelt sie fuer „noch nicht bearbeitet"; das Konto sagt, wie
    viel insgesamt unerklaert ist."""
    _bewegung(1014.13, "Booking.com BV", "bk2")
    assert v.saldo("booking") == -1014.13


def test_ein_erloes_ohne_rechnung_zaehlt_wie_eine_rechnung():
    """Wer eine Auszahlung direkt einer Einnahmen-Kategorie zuordnet, bucht
    Erloes ohne Rechnung. Das gehoert aufs Konto - aber nicht unter
    „Provision", sonst stuende ein Erloes in der falschen Zeile."""
    b = _bewegung(500.0, "Booking.com BV", "bk2b")
    z.hinzufuegen(b["id"], z.KATEGORIE, 500.0, "Einnahmen Booking")
    arten = [x["art"] for x in v.zeilen("booking")]
    assert arten == ["erloes", "auszahlung"]
    assert v.saldo("booking") == 0.0


def test_das_kontoblatt_zeigt_alle_drei_arten():
    r = _rechnung(31, "Meier", 620.00)
    b = _bewegung(500.0, "Booking.com BV", "bk3")
    z.hinzufuegen(b["id"], z.RECHNUNG, 620.00, ziel_id=r["id"])
    z.hinzufuegen(b["id"], z.KATEGORIE, -120.0, "Portalprovision")
    arten = [x["art"] for x in v.zeilen("booking")]
    assert arten == ["rechnung", "provision", "auszahlung"]
    texte = [x["text"] for x in v.zeilen("booking")]
    assert "Nr. 2026-0031" in texte[0] and "Meier" in texte[0]


def test_die_plattformen_stoeren_sich_nicht():
    r = _rechnung(31, "Meier", 100.0)
    b = _bewegung(100.0, "Booking.com BV", "bk4")
    z.hinzufuegen(b["id"], z.RECHNUNG, 100.0, ziel_id=r["id"])
    _bewegung(200.0, "Airbnb", "ab1")
    assert v.saldo("booking") == 0.0
    assert v.saldo("airbnb") == -200.0


def test_ausgaben_zaehlen_nicht_auf_das_verrechnungskonto():
    """Eine Abbuchung an Booking waere etwas anderes als eine Auszahlung."""
    _bewegung(-50.0, "Booking.com BV", "bk5")
    assert v.zeilen("booking") == []


# ------------------------------------------------------------- Die Übersicht
def test_die_uebersicht_fasst_je_plattform_zusammen():
    r = _rechnung(31, "Meier", 620.00)
    b = _bewegung(500.0, "Booking.com BV", "bk6")
    z.hinzufuegen(b["id"], z.RECHNUNG, 620.00, ziel_id=r["id"])
    z.hinzufuegen(b["id"], z.KATEGORIE, -120.0, "Portalprovision")
    u = v.uebersicht()
    assert len(u) == 1 and u[0]["name"] == "Booking.com"
    assert u[0]["rechnungen"] == 620.0
    assert u[0]["provision"] == -120.0
    assert u[0]["auszahlung"] == -500.0
    assert u[0]["saldo"] == 0.0


def test_ohne_bewegungen_bleibt_die_uebersicht_leer():
    assert v.uebersicht() == []


# ----------------------------------------------------------- Die Monatsprobe
def test_die_monatsprobe_trifft_den_monatsbeleg():
    """Die Prüfung, die vorher fälschlich gegen Smoobu lief – jetzt gegen den
    Beleg, den die Plattform monatlich schickt."""
    r = _rechnung(31, "Meier", 620.00)
    b = _bewegung(500.0, "Booking.com BV", "bk7", datum="2026-06-12")
    z.hinzufuegen(b["id"], z.RECHNUNG, 620.00, ziel_id=r["id"])
    z.hinzufuegen(b["id"], z.KATEGORIE, -120.0, "Portalprovision")
    summe, beleg, stimmt = v.monatsprobe("booking", "2026-06", 120.0)
    assert (summe, beleg, stimmt) == (-120.0, -120.0, True)


def test_eine_abweichung_zum_monatsbeleg_faellt_auf():
    r = _rechnung(31, "Meier", 620.00)
    b = _bewegung(500.0, "Booking.com BV", "bk8", datum="2026-06-12")
    z.hinzufuegen(b["id"], z.RECHNUNG, 620.00, ziel_id=r["id"])
    z.hinzufuegen(b["id"], z.KATEGORIE, -120.0, "Portalprovision")
    summe, beleg, stimmt = v.monatsprobe("booking", "2026-06", 180.0)
    assert not stimmt and summe == -120.0 and beleg == -180.0


def test_ein_anderer_monat_zaehlt_nicht_mit():
    r = _rechnung(31, "Meier", 620.00)
    b = _bewegung(500.0, "Booking.com BV", "bk9", datum="2026-05-12")
    z.hinzufuegen(b["id"], z.RECHNUNG, 620.00, ziel_id=r["id"])
    z.hinzufuegen(b["id"], z.KATEGORIE, -120.0, "Portalprovision")
    assert v.monatsprobe("booking", "2026-06", 0.0)[0] == 0.0


# ------------------------------------------------------------- Die Anzeige
def test_die_karte_laesst_sich_zeichnen():
    """Rauchprobe für die Oberfläche: die Karte wird gebaut, ohne zu brechen.

    Die Fachlogik darüber ist geprüft; was hier schiefgeht, sind Tippfehler in
    der Anzeige – ein falscher Schlüssel im Zeilen-Satz oder eine Klasse, die es
    nicht gibt. Das fällt sonst erst im Browser auf.
    """
    from nicegui import ui
    from nicegui.client import Client
    from app.ui import kontoblatt
    r = _rechnung(31, "Meier", 620.00)
    b = _bewegung(500.0, "Booking.com BV", "bk10")
    z.hinzufuegen(b["id"], z.RECHNUNG, 620.00, ziel_id=r["id"])
    z.hinzufuegen(b["id"], z.KATEGORIE, -120.0, "Portalprovision")
    # Ohne eigenen Client hat NiceGUI je nach Testreihenfolge keinen Slot, in
    # den die Elemente gehoeren – allein bestand der Test, in der vollen Suite
    # nicht. Der Client stellt ihn her, unabhaengig davon, was vorher lief.
    with Client(lambda: None):
        with ui.card():
            kontoblatt._verrechnungskonten()


def test_die_monatsprobe_laesst_sich_zeichnen():
    from nicegui import ui
    from nicegui.client import Client
    from app import db
    from app.ui import kontoblatt
    db.anlegen("belege", {"id": "prov", "uploader": "x", "ts": "2026-06-30T10:00:00",
                          "photo": "p.jpg", "merchant": "Booking.com",
                          "amount": "265,87", "datum": "2026-06-30"})
    a = _bewegung(1014.13, "Booking.com BV", "bk30", datum="2026-06-05")
    z.hinzufuegen(a["id"], z.BELEG, -145.87, "Portalprovision", ziel_id="prov")
    b = _bewegung(500.0, "Airbnb", "bk31", datum="2026-05-05")
    z.hinzufuegen(b["id"], z.KATEGORIE, -50.0, "Portalprovision")
    with Client(lambda: None):
        with ui.card():
            kontoblatt._monatsprobe("booking")
            kontoblatt._monatsprobe("airbnb")


# ------------------------------------- Die Monatsprobe, jetzt mit Beleg (B5b)
def test_die_monatsuebersicht_findet_den_beleg_am_posten():
    """Der Monatsbeleg haengt seit B5 an den Provisions-Posten. Damit laesst
    sich die Probe endlich anzeigen – vorher fehlte der Betrag dafuer."""
    from app import db
    db.anlegen("belege", {"id": "prov", "uploader": "x", "ts": "2026-06-30T10:00:00",
                          "photo": "p.jpg", "merchant": "Booking.com",
                          "amount": "265,87", "datum": "2026-06-30"})
    r1 = _rechnung(31, "Meier", 620.00)
    a = _bewegung(1014.13, "Booking.com BV", "bk20", datum="2026-06-05")
    b = _bewegung(820.00, "Booking.com BV", "bk21", datum="2026-06-19")
    z.hinzufuegen(a["id"], z.RECHNUNG, 620.00, ziel_id=r1["id"])
    z.hinzufuegen(a["id"], z.BELEG, -145.87, "Portalprovision", ziel_id="prov")
    z.hinzufuegen(b["id"], z.BELEG, -120.00, "Portalprovision", ziel_id="prov")
    m = v.monatsuebersicht("booking")
    juni = [x for x in m if x["monat"] == "2026-06"][0]
    assert juni["provision"] == -265.87
    assert juni["beleg"] == -265.87 and juni["stimmt"] is True


def test_ein_monat_ohne_beleg_behauptet_nichts():
    r1 = _rechnung(31, "Meier", 620.00)
    a = _bewegung(1014.13, "Booking.com BV", "bk20", datum="2026-06-05")
    z.hinzufuegen(a["id"], z.RECHNUNG, 620.00, ziel_id=r1["id"])
    z.hinzufuegen(a["id"], z.KATEGORIE, -145.87, "Portalprovision")
    juni = v.monatsuebersicht("booking")[0]
    assert juni["provision"] == -145.87
    assert juni["beleg"] is None and juni["stimmt"] is None


def test_eine_fehlende_auszahlung_faellt_gegen_den_monatsbeleg_auf():
    """Der eigentliche Zweck: der Beleg sagt 265,87, gebucht sind nur 145,87 –
    also fehlt eine Auszahlung des Monats."""
    from app import db
    db.anlegen("belege", {"id": "prov", "uploader": "x", "ts": "2026-06-30T10:00:00",
                          "photo": "p.jpg", "merchant": "Booking.com",
                          "amount": "265,87", "datum": "2026-06-30"})
    a = _bewegung(1014.13, "Booking.com BV", "bk20", datum="2026-06-05")
    z.hinzufuegen(a["id"], z.BELEG, -145.87, "Portalprovision", ziel_id="prov")
    juni = v.monatsuebersicht("booking")[0]
    assert juni["stimmt"] is False and juni["beleg"] == -265.87
