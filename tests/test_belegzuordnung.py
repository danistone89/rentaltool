"""B5: Belege und Bankbewegungen zusammenbringen.

Gemessen am Bestand (8.8.2026): 4 Belege, davon 1 mit Betrag, 0 mit gepflegtem
Belegdatum – und dieser eine Betrag trifft null Bewegungen. Ein Abgleich über
den Betrag trägt hier also nicht. Sortiert wird nach Händlername und
Datumsnähe; der Betrag ist ein Zusatzhinweis, nie ein Ausschluss.
"""
from app import belegzuordnung as bz, konto, zuordnung as z


def _bewegung(betrag, gegenpartei, bid, datum="2026-06-12", text=""):
    from app import db
    satz = {"id": bid, "datum": datum, "betrag": betrag, "gegenpartei": gegenpartei,
            "text": text, "konto": "giro", "umbuchung": False}
    db.anlegen(konto.TABELLE, satz)
    return satz


def _rechnung_satz(rid, brutto):
    from app import db, rechnung
    satz = {"id": rid, "nummer": "2026-0031", "gast": "Meier", "datum": "2026-06-01",
            "status": rechnung.FESTGESCHRIEBEN,
            "summen": {"brutto": brutto, "netto": 0, "ust": 0, "durchlaufend": 0}}
    db.anlegen("rechnungen", satz)
    return satz


def _hole_beleg(bid):
    from app import db
    return db.holen("belege", bid)


def _beleg(bid, merchant="", amount="", datum="", ts="2026-06-12T10:00:00"):
    from app import db
    satz = {"id": bid, "uploader": "Gabriel", "ts": ts, "photo": "x.jpg",
            "merchant": merchant, "amount": amount, "datum": datum,
            "note": "", "kategorie": ""}
    db.anlegen("belege", satz)
    return satz


# ------------------------------------------------------ Belege ohne Bewegung
def test_ein_frisch_hochgeladener_beleg_haengt_nirgends():
    _beleg("q1", "ALDI", "27,81")
    assert [x["id"] for x in bz.ohne_bewegung()] == ["q1"]


def test_ein_zugeordneter_beleg_faellt_aus_der_liste():
    b = _bewegung(-27.81, "ALDI SAGT DANKE", "w1")
    _beleg("q1", "ALDI", "27,81")
    z.hinzufuegen(b["id"], z.BELEG, -27.81, ziel_id="q1")
    assert bz.ohne_bewegung() == []


# ---------------------------------------------- Von der Bewegung zum Beleg
def test_der_haendlername_traegt_den_vorschlag():
    b = _bewegung(-27.81, "ALDI SAGT DANKE 1234", "w1")
    _beleg("q1", "ALDI", "27,81")
    _beleg("q2", "Baumarkt", "99,00")
    k = bz.belege_zu(b)
    assert [x["beleg"]["id"] for x in k][0] == "q1"
    assert k[0]["grund"] == "Händler passt"


def test_ein_beleg_ohne_betrag_wird_trotzdem_vorgeschlagen():
    """3 von 4 echten Belegen tragen keinen Betrag. Wer sie ausschliesst,
    schlaegt nichts mehr vor."""
    b = _bewegung(-27.81, "ALDI SAGT DANKE", "w1")
    _beleg("q1", "ALDI", "")
    assert [x["beleg"]["id"] for x in bz.belege_zu(b)] == ["q1"]


def test_der_gleiche_betrag_hebt_einen_vorschlag_nach_oben():
    """Der Beleg ohne Betrag wird zuletzt angelegt und stuende ohne die Regel
    oben – die Liste kommt neueste zuerst. Genau deshalb steht er hier so."""
    b = _bewegung(-27.81, "Unbekannt GmbH", "w1", datum="2026-06-12")
    _beleg("mit", "", "27,81", ts="2026-06-12T10:00:00")
    _beleg("ohne", "", "", ts="2026-06-12T10:00:00")
    k = bz.belege_zu(b)
    assert [x["beleg"]["id"] for x in k] == ["mit", "ohne"]
    assert k[0]["grund"] == "Betrag stimmt"
    # Ein fehlender Betrag ist kein stiller Treffer.
    assert k[1]["grund"] != "Betrag stimmt"


def test_naehere_belege_stehen_oben():
    b = _bewegung(-27.81, "Unbekannt GmbH", "w1", datum="2026-06-12")
    _beleg("weit", "", "", ts="2026-01-02T10:00:00")
    _beleg("nah", "", "", ts="2026-06-13T10:00:00")
    assert [x["beleg"]["id"] for x in bz.belege_zu(b)] == ["nah", "weit"]


def test_zu_einer_einnahme_gibt_es_keinen_lieferantenbeleg():
    _bewegung(1014.13, "Booking.com BV", "w1")
    _beleg("q1", "ALDI", "27,81")
    assert bz.belege_zu(konto.alle()[0]) == []


def test_schon_zugeordnete_belege_werden_nicht_nochmal_vorgeschlagen():
    b1 = _bewegung(-27.81, "ALDI SAGT DANKE", "w1")
    b2 = _bewegung(-31.50, "ALDI SAGT DANKE", "w2")
    _beleg("q1", "ALDI", "27,81")
    z.hinzufuegen(b1["id"], z.BELEG, -27.81, ziel_id="q1")
    assert bz.belege_zu(b2) == []


# ---------------------------------------------- Vom Beleg zur Bewegung
def test_umgekehrt_wird_die_bewegung_vorgeschlagen():
    _bewegung(-27.81, "ALDI SAGT DANKE", "w1")
    _bewegung(-99.00, "Baumarkt Nord", "w2")
    r = _beleg("q1", "ALDI", "27,81")
    k = bz.bewegungen_zu(r)
    assert [x["bewegung"]["id"] for x in k][0] == "w1"


def test_einnahmen_sind_auch_umgekehrt_keine_kandidaten():
    _bewegung(1014.13, "ALDI", "w1")
    r = _beleg("q1", "ALDI", "")
    assert bz.bewegungen_zu(r) == []


# ------------------------------------- B5b: ein Beleg auf mehrere Bewegungen
def test_ein_beleg_kann_an_mehreren_bewegungen_haengen():
    """Der Provisionsbeleg kommt monatlich, die Auszahlungen einzeln."""
    a = _bewegung(1014.13, "Booking.com BV", "p1", datum="2026-06-05")
    b = _bewegung(820.00, "Booking.com BV", "p2", datum="2026-06-19")
    _beleg("prov", "Booking.com", "265,87")
    z.hinzufuegen(a["id"], z.BELEG, -145.87, ziel_id="prov")
    z.hinzufuegen(b["id"], z.BELEG, -120.00, ziel_id="prov")
    assert sorted(z.bewegungen_zu(z.BELEG, "prov")) == ["p1", "p2"]
    assert bz.ohne_bewegung() == []


def test_der_verteilte_beleg_wird_gegen_seine_posten_geprueft():
    a = _bewegung(1014.13, "Booking.com BV", "p1", datum="2026-06-05")
    b = _bewegung(820.00, "Booking.com BV", "p2", datum="2026-06-19")
    r = _beleg("prov", "Booking.com", "265,87")
    z.hinzufuegen(a["id"], z.BELEG, -145.87, ziel_id="prov")
    z.hinzufuegen(b["id"], z.BELEG, -120.00, ziel_id="prov")
    verteilt, beleg, stimmt = bz.belegprobe(r)
    assert (verteilt, beleg, stimmt) == (-265.87, -265.87, True)


def test_eine_luecke_im_verteilten_beleg_faellt_auf():
    a = _bewegung(1014.13, "Booking.com BV", "p1", datum="2026-06-05")
    r = _beleg("prov", "Booking.com", "265,87")
    z.hinzufuegen(a["id"], z.BELEG, -145.87, ziel_id="prov")
    verteilt, beleg, stimmt = bz.belegprobe(r)
    assert not stimmt and verteilt == -145.87 and beleg == -265.87


def test_ohne_betrag_am_beleg_gibt_es_nichts_zu_pruefen():
    a = _bewegung(1014.13, "Booking.com BV", "p1")
    r = _beleg("prov", "Booking.com", "")
    z.hinzufuegen(a["id"], z.BELEG, -145.87, ziel_id="prov")
    assert bz.belegprobe(r) == (-145.87, None, None)


# ------------------------------------------------------- B5c: Dubletten
def test_derselbe_beleg_zweimal_faellt_auf():
    _beleg("q1", "ALDI", "27,81", datum="2026-06-12")
    neu = _beleg("q2", "ALDI", "27,81", datum="2026-06-12")
    assert [x["id"] for x in bz.dubletten(neu)] == ["q1"]


def test_ein_anderer_betrag_ist_keine_dublette():
    _beleg("q1", "ALDI", "27,81", datum="2026-06-12")
    neu = _beleg("q2", "ALDI", "31,50", datum="2026-06-12")
    assert bz.dubletten(neu) == []


def test_ohne_betrag_wird_keine_dublette_behauptet():
    """Zwei Belege ohne Betrag sehen immer gleich aus. Eine Warnung, die
    staendig kommt, wird weggeklickt – dann fehlt sie im echten Fall."""
    _beleg("q1", "ALDI", "", datum="2026-06-12")
    neu = _beleg("q2", "ALDI", "", datum="2026-06-12")
    assert bz.dubletten(neu) == []


def test_weit_auseinander_liegende_belege_sind_keine_dublette():
    _beleg("q1", "ALDI", "27,81", datum="2026-01-12")
    neu = _beleg("q2", "ALDI", "27,81", datum="2026-06-12")
    assert bz.dubletten(neu) == []


def test_ein_beleg_ist_nie_seine_eigene_dublette():
    r = _beleg("q1", "ALDI", "27,81", datum="2026-06-12")
    assert bz.dubletten(r) == []


# ------------------------------------ Anhaengen, ohne vorhandene Arbeit zu loeschen
def test_ein_beleg_loescht_die_aufteilung_nicht():
    """Der Fehler im alten Weg: `beleg_setzen` loeste erst ALLE Posten.

    Wer eine Zahlung auf Putzmittel und Gastgeschenke aufgeteilt hatte und
    danach den Kassenbon anhaengte, verlor die Aufteilung – stillschweigend.
    """
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Putzmittel")
    z.hinzufuegen(b["id"], z.KATEGORIE, -40.0, "Gastgeschenke")
    _beleg("q1", "Baumarkt", "100,00")
    konto.beleg_anhaengen("w1", "q1")
    arten = [(p["kategorie"], p["betrag"]) for p in z.posten("w1")]
    assert arten == [("Putzmittel", -60.0), ("Gastgeschenke", -40.0)]
    # Die Quittung ueber 100 EUR gehoert zur ganzen Zahlung, nicht zu einem
    # Teil davon – sonst meldete die Belegprobe eine Luecke, die keine ist.
    assert z.bewegungen_zu(z.BELEG, "q1") == ["w1", "w1"]
    assert bz.belegprobe(konto.holen("w1") and _hole_beleg("q1"))[2] is True


def test_bei_voll_verteilter_bewegung_bekommt_ein_posten_den_beleg():
    """Ist der Rest null, waere ein zusaetzlicher Posten falsch – er wuerde die
    Zahlung doppelt buchen. Stattdessen bekommt der Posten sein Papier."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -100.0, "Putzmittel")
    _beleg("q1", "Baumarkt", "100,00")
    konto.beleg_anhaengen("w1", "q1")
    p = z.posten("w1")
    assert len(p) == 1
    assert p[0]["art"] == z.BELEG and p[0]["ziel_id"] == "q1"
    # Die Kategorie darf dabei nicht verlorengehen.
    assert p[0]["kategorie"] == "Putzmittel"
    assert z.ist_fertig(konto.holen("w1"))


def test_ohne_posten_deckt_der_beleg_die_ganze_bewegung():
    _bewegung(-27.81, "ALDI", "w1")
    _beleg("q1", "ALDI", "27,81")
    konto.beleg_anhaengen("w1", "q1")
    p = z.posten("w1")
    assert len(p) == 1 and p[0]["betrag"] == -27.81


def test_zwei_belege_teilen_sich_eine_aufgeteilte_zahlung():
    """Trifft der Betrag des Belegs genau einen Posten, haengt er nur dort.
    Sonst gaebe es keinen Weg, zu einer Zahlung zwei Quittungen zu fuehren."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Putzmittel")
    z.hinzufuegen(b["id"], z.KATEGORIE, -40.0, "Gastgeschenke")
    _beleg("q1", "Baumarkt", "40,00")
    konto.beleg_anhaengen("w1", "q1")
    treffer = [(p["kategorie"], p["art"]) for p in z.posten("w1")]
    assert treffer == [("Putzmittel", "kategorie"), ("Gastgeschenke", "beleg")]


def test_ein_offener_rest_wird_dem_beleg_zugeschlagen():
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Putzmittel")
    _beleg("q1", "Baumarkt", "40,00")
    konto.beleg_anhaengen("w1", "q1")
    p = [x for x in z.posten("w1") if x["art"] == z.BELEG]
    assert len(p) == 1 and p[0]["betrag"] == -40.0


def test_ein_beleg_loesen_laesst_die_anderen_posten_stehen():
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Putzmittel")
    _beleg("q1", "Baumarkt", "40,00")
    konto.beleg_anhaengen("w1", "q1")
    konto.beleg_loesen("w1", "q1")
    rest = [(p["art"], p["kategorie"]) for p in z.posten("w1")]
    assert rest == [("kategorie", "Putzmittel")]


# ------------------------ B5b: ein Beleg, der noch nicht ganz verteilt ist
def test_ein_teilweise_verteilter_beleg_bleibt_zur_auswahl():
    """Der Monatsbeleg ueber 265,87 EUR haengt schon an der ersten Auszahlung.
    Fuer die zweite muss er weiter waehlbar sein – sonst laesst sich ein
    Monatsbeleg gar nicht verteilen."""
    a = _bewegung(1014.13, "Booking.com BV", "p1", datum="2026-06-05")
    _beleg("prov", "Booking.com", "265,87")
    z.hinzufuegen(a["id"], z.BELEG, -145.87, ziel_id="prov")
    assert [x["id"] for x in bz.teilweise_verteilt()] == ["prov"]


def test_ein_ganz_verteilter_beleg_faellt_aus_der_auswahl():
    a = _bewegung(1014.13, "Booking.com BV", "p1", datum="2026-06-05")
    _beleg("prov", "Booking.com", "265,87")
    z.hinzufuegen(a["id"], z.BELEG, -265.87, ziel_id="prov")
    assert bz.teilweise_verteilt() == []


def test_ohne_betrag_gilt_ein_beleg_als_erledigt():
    """Ohne Betrag laesst sich nicht sagen, ob noch etwas fehlt – dann waere
    jeder zugeordnete Beleg fuer immer 'teilweise verteilt'."""
    a = _bewegung(-50.0, "ALDI", "w1")
    _beleg("q1", "ALDI", "")
    z.hinzufuegen(a["id"], z.BELEG, -50.0, ziel_id="q1")
    assert bz.teilweise_verteilt() == []


# ------------------------------------------------------------- Die Anzeige
def _in_client(bauen):
    """Rauchprobe: die Maske wird gebaut, ohne zu brechen.

    Ohne eigenen Client hat NiceGUI je nach Testreihenfolge keinen Slot – der
    Fehler, der in B4b erst in der vollen Suite auffiel.
    """
    from nicegui import ui
    from nicegui.client import Client
    with Client(lambda: None):
        with ui.card():
            bauen()


def test_die_belegauswahl_an_der_bewegung_laesst_sich_zeichnen():
    from app.ui import kontoblatt
    b = _bewegung(-27.81, "ALDI SAGT DANKE", "w1")
    _beleg("q1", "ALDI", "27,81")
    _in_client(lambda: kontoblatt._beleg_waehlen(b, lambda: None))


def test_die_bewegungszeile_am_beleg_laesst_sich_zeichnen():
    from app.ui import belege
    _bewegung(-27.81, "ALDI SAGT DANKE", "w1")
    r = _beleg("q1", "ALDI", "27,81")
    _in_client(lambda: belege._bewegungszeile(r, lambda: None))


def test_die_bewegungszeile_zeigt_auch_den_verteilten_beleg():
    """Der zweite Zweig: der Beleg haengt schon und wird gegen seine Posten
    geprueft. Ein Tippfehler dort faellt sonst erst im Browser auf."""
    from app.ui import belege
    a = _bewegung(1014.13, "Booking.com BV", "p1")
    r = _beleg("prov", "Booking.com", "265,87")
    z.hinzufuegen(a["id"], z.BELEG, -145.87, ziel_id="prov")
    _in_client(lambda: belege._bewegungszeile(r, lambda: None))


# --------------------------- Der Fehler, den erst die echten Daten zeigten
def test_ein_beleg_bucht_an_einer_auszahlung_nicht_den_umsatz():
    """An den echten Daten aufgefallen: der Provisionsbeleg ueber 265,87 EUR
    erzeugte an einer Booking-Auszahlung einen Posten ueber +1.348,42 EUR.

    Ein Lieferantenbeleg kann den offenen Rest einer Auszahlung nicht decken –
    der ist Umsatz. Er gehoert an die gegengebuchte Provision.
    """
    b = _bewegung(1202.55, "Booking.com BV", "p1", datum="2026-06-26")
    z.hinzufuegen(b["id"], z.KATEGORIE, -145.87, "Portalprovision")
    _beleg("prov", "Booking.com", "265,87")
    konto.beleg_anhaengen("p1", "prov")
    p = z.posten("p1")
    assert len(p) == 1
    assert p[0]["betrag"] == -145.87 and p[0]["ziel_id"] == "prov"


def test_ohne_gegengebuchte_provision_passiert_an_der_auszahlung_nichts():
    """Lieber nichts tun als etwas Falsches: erst die Provision gegenbuchen."""
    _bewegung(1202.55, "Booking.com BV", "p1", datum="2026-06-26")
    _beleg("prov", "Booking.com", "265,87")
    assert konto.beleg_anhaengen("p1", "prov") is None
    assert z.posten("p1") == []


def test_die_rechnungen_einer_auszahlung_bleiben_unberuehrt():
    r = _rechnung_satz("r1", 620.00)
    b = _bewegung(1202.55, "Booking.com BV", "p1", datum="2026-06-26")
    z.hinzufuegen(b["id"], z.RECHNUNG, 620.00, ziel_id=r["id"])
    z.hinzufuegen(b["id"], z.KATEGORIE, -145.87, "Portalprovision")
    _beleg("prov", "Booking.com", "265,87")
    konto.beleg_anhaengen("p1", "prov")
    arten = [(x["art"], x["betrag"]) for x in z.posten("p1")]
    assert arten == [("rechnung", 620.00), ("beleg", -145.87)]


# ------------------------------------------------- Suchen statt Deckel
def test_die_suche_findet_ueber_den_empfaenger():
    """122 Kandidaten sind kein Fehler – nur die ersten acht zu zeigen schon.
    Wer weiss, zu welcher Abbuchung sein Beleg gehoert, muss sie finden."""
    a = _bewegung(-27.81, "DREWAG-Stadtwerke DD GmbH", "w1", datum="2026-07-20")
    b = _bewegung(-99.00, "Baumarkt Nord", "w2", datum="2026-03-02")
    k = [{"bewegung": a, "grund": "offen"}, {"bewegung": b, "grund": "offen"}]
    assert [x["bewegung"]["id"] for x in bz.filtern(k, "drewag")] == ["w1"]


def test_mehrere_woerter_muessen_alle_vorkommen():
    a = _bewegung(-27.81, "DREWAG-Stadtwerke DD GmbH", "w1", datum="2026-07-20")
    b = _bewegung(-99.00, "DREWAG-Stadtwerke DD GmbH", "w2", datum="2026-03-02")
    k = [{"bewegung": a, "grund": "offen"}, {"bewegung": b, "grund": "offen"}]
    assert [x["bewegung"]["id"] for x in bz.filtern(k, "drewag 2026-07")] == ["w1"]


def test_die_suche_findet_ueber_den_betrag():
    a = _bewegung(-27.81, "Unbekannt", "w1")
    b = _bewegung(-99.00, "Unbekannt", "w2")
    k = [{"bewegung": a, "grund": "offen"}, {"bewegung": b, "grund": "offen"}]
    assert [x["bewegung"]["id"] for x in bz.filtern(k, "27,81")] == ["w1"]
    assert [x["bewegung"]["id"] for x in bz.filtern(k, "27.81")] == ["w1"]


def test_die_suche_findet_im_verwendungszweck():
    a = _bewegung(-27.81, "Unbekannt", "w1", text="Rechnung 4711 Juli")
    b = _bewegung(-99.00, "Unbekannt", "w2", text="Dauerauftrag")
    k = [{"bewegung": a, "grund": "offen"}, {"bewegung": b, "grund": "offen"}]
    assert [x["bewegung"]["id"] for x in bz.filtern(k, "4711")] == ["w1"]


def test_ohne_suchbegriff_bleibt_alles_stehen():
    a = _bewegung(-27.81, "Unbekannt", "w1")
    k = [{"bewegung": a, "grund": "offen"}]
    assert bz.filtern(k, "") == k and bz.filtern(k, "   ") == k


def test_die_suche_funktioniert_auch_ueber_belege():
    """Dieselbe Maske auf der anderen Seite: Belege an einer Bewegung."""
    r1 = _beleg("q1", "ALDI", "27,81")
    r2 = _beleg("q2", "Baumarkt", "99,00")
    k = [{"beleg": r1, "grund": "offen"}, {"beleg": r2, "grund": "offen"}]
    assert [x["beleg"]["id"] for x in bz.filtern(k, "aldi", "beleg")] == ["q1"]
