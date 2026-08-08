"""B7: der Überblick – Ergebnis je Monat, je Kategorie, je Wohnung.

Zweck laut Betrieb (8.8.2026): **keine EÜR fürs Finanzamt** – die macht das
Steuerbüro. Hier geht es um den Blick auf die eigenen Zahlen, weil das
Steuerbüro 8–10 Monate hinterherhinkt. Deshalb muss überall dabeistehen, wie
belastbar eine Zahl gerade ist.

Am Bestand nachgemessen, bevor gebaut wurde: von 27 Posten trägt **einer** eine
ableitbare Wohnung, von 30 Belegen **keiner**. „Je Wohnung" kann auf der
Ausgabenseite deshalb heute nichts liefern – und muss das sagen.
"""
from app import konto, ueberblick as ub, zuordnung as z


def _bewegung(betrag, gegenpartei, bid, datum="2026-06-12", kategorie="", klasse=""):
    from app import db
    satz = {"id": bid, "datum": datum, "betrag": betrag, "gegenpartei": gegenpartei,
            "text": "", "konto": "giro", "umbuchung": False,
            "kategorie": kategorie, "klasse": klasse}
    db.anlegen(konto.TABELLE, satz)
    return satz


# ------------------------------------------------- B7a: Ergebnis je Monat
def test_der_geldfluss_und_das_ergebnis_sind_zwei_zahlen():
    """Die Verwechslung ist teuer: über das erste Halbjahr liegen mehr als
    8.000 € dazwischen."""
    _bewegung(1000.0, "Gast", "w1", kategorie="Beherbergungserlöse (Direktbuchung, brutto)")
    _bewegung(-300.0, "Rena", "w2", kategorie="Wäscherei (Rena)")
    _bewegung(-500.0, "Privat", "w3", kategorie="Eigenübertrag / Entnahme")
    m = ub.monate()["2026-06"]
    assert m["eingang"] == 1000.0 and m["ausgang"] == -800.0
    assert m["geldfluss"] == 200.0
    # Die Privatentnahme gehört nicht ins Ergebnis.
    assert m["ergebnis"] == 700.0


def test_eine_privatentnahme_in_einer_sammelzahlung_belastet_nicht():
    """Der Grund für B7a: nach der Bewegung gerechnet zählte die ganze Zahlung
    mit der Klasse der Bewegung – die Aufteilung war unsichtbar."""
    b = _bewegung(-1000.0, "Sammelabbuchung", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -400.0, "Wäscherei (Rena)")
    z.hinzufuegen(b["id"], z.KATEGORIE, -600.0, "Eigenübertrag / Entnahme")
    m = ub.monate()["2026-06"]
    assert m["ausgang"] == -1000.0          # Geldfluss: alles
    assert m["ergebnis"] == -400.0          # Ergebnis: nur die Wäscherei


def test_durchlaufende_posten_bleiben_draussen():
    _bewegung(-259.74, "Stadt Dresden", "w1",
              kategorie="Beherbergungssteuer an Stadt (durchlaufender Posten)")
    assert ub.monate()["2026-06"]["ergebnis"] == 0.0


def test_umbuchungen_zaehlen_nirgends_mit():
    from app import db
    db.anlegen(konto.TABELLE, {"id": "u1", "datum": "2026-06-12", "betrag": -500.0,
                               "gegenpartei": "Kreditkarte", "text": "", "konto": "giro",
                               "umbuchung": True, "kategorie": "", "klasse": ""})
    assert ub.monate() == {}


def test_offene_ausgaben_werden_gezaehlt():
    """Solange die Zahl größer als null ist, ist das Ergebnis eine Näherung –
    und die Anzeige soll das sagen dürfen."""
    _bewegung(-300.0, "Unbekannt", "w1")
    _bewegung(-300.0, "Rena", "w2", kategorie="Wäscherei (Rena)")
    assert ub.monate()["2026-06"]["offen"] == 1


def test_eine_ueber_die_maske_zugeordnete_zahlung_gilt_nicht_als_offen():
    """Dieselbe Naht wie in `ohne_zuordnung`: `unklar` zählte nur das Feld."""
    b = _bewegung(-300.0, "Unbekannt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -300.0, "Wäscherei (Rena)")
    assert ub.monate()["2026-06"]["offen"] == 0


def test_die_monate_kommen_sortiert():
    _bewegung(-100.0, "Rena", "w1", datum="2026-07-01", kategorie="Wäscherei (Rena)")
    _bewegung(-100.0, "Rena", "w2", datum="2026-05-01", kategorie="Wäscherei (Rena)")
    assert list(ub.monate()) == ["2026-05", "2026-07"]


def test_ein_zeitraum_grenzt_ein():
    _bewegung(-100.0, "Rena", "w1", datum="2026-07-01", kategorie="Wäscherei (Rena)")
    _bewegung(-100.0, "Rena", "w2", datum="2026-05-01", kategorie="Wäscherei (Rena)")
    assert list(ub.monate("2026-07-01", "2026-07-31")) == ["2026-07"]


# ------------------------------------------------- B7b: je Kategorie
def test_die_kategorien_stehen_nach_klasse_gruppiert():
    _bewegung(1000.0, "Gast", "w1", kategorie="Beherbergungserlöse (Direktbuchung, brutto)")
    _bewegung(-300.0, "Rena", "w2", kategorie="Wäscherei (Rena)")
    _bewegung(-500.0, "Privat", "w3", kategorie="Eigenübertrag / Entnahme")
    g = ub.kategorien()
    assert g["Einnahme"] == [("Beherbergungserlöse (Direktbuchung, brutto)", 1000.0)]
    assert g["Ausgabe"] == [("Wäscherei (Rena)", -300.0)]
    assert g["Privat/prüfen"] == [("Eigenübertrag / Entnahme", -500.0)]


def test_innerhalb_einer_klasse_steht_das_groesste_oben():
    """„Wie viel ging für Putzmittel drauf" – die Antwort soll oben stehen."""
    _bewegung(-50.0, "dm", "w1", kategorie="Reinigung/Verbrauch (dm)")
    _bewegung(-300.0, "Rena", "w2", kategorie="Wäscherei (Rena)")
    assert [k for k, _s in ub.kategorien()["Ausgabe"]] \
        == ["Wäscherei (Rena)", "Reinigung/Verbrauch (dm)"]


def test_das_noch_nicht_zugeordnete_steht_fuer_sich():
    """Es unter „Ausgabe" zu führen wäre eine Behauptung – es ist noch nichts."""
    _bewegung(-300.0, "Unbekannt", "w1")
    g = ub.kategorien()
    assert g.get("Ausgabe") is None
    assert g[ub.UNGEKLAERT] == [(konto.OHNE_KATEGORIE, -300.0)]


# ------------------------------------------------- B7c: je Wohnung
def test_erloese_je_wohnung_kommen_aus_den_rechnungen():
    from app import db, rechnung
    db.anlegen("rechnungen", {"id": "r1", "nummer": "2026-0001", "gast": "Meier",
                              "datum": "2026-06-01", "wohnung": "a1",
                              "status": rechnung.FESTGESCHRIEBEN,
                              "summen": {"brutto": 620.0}})
    b = _bewegung(620.0, "Meier", "w1")
    z.hinzufuegen(b["id"], z.RECHNUNG, 620.0, ziel_id="r1")
    w = ub.wohnungen()
    assert w["a1"]["einnahmen"] == 620.0


def test_ausgaben_je_wohnung_kommen_aus_den_belegen():
    from app import db
    db.anlegen("belege", {"id": "q1", "uploader": "x", "ts": "2026-06-12T10:00:00",
                          "photo": "p.jpg", "merchant": "dm", "amount": "24,52",
                          "apartment_id": "a1", "datum": "2026-06-12"})
    b = _bewegung(-24.52, "dm", "w1")
    z.hinzufuegen(b["id"], z.BELEG, -24.52, "Reinigung/Verbrauch (dm)", ziel_id="q1")
    assert ub.wohnungen()["a1"]["ausgaben"] == -24.52


def test_die_abdeckung_wird_ausgewiesen():
    """Der wichtigste Teil von B7c: eine Auswertung, die verschweigt, worauf
    sie sich stützt, ist schlimmer als keine. Am Bestand trug KEIN Beleg eine
    Wohnung – eine leere Tabelle sähe aus wie „keine Kosten"."""
    b = _bewegung(-300.0, "Rena", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -300.0, "Wäscherei (Rena)")
    a = ub.abdeckung()
    assert a["posten"] == 1 and a["mit_wohnung"] == 0


def test_bei_voller_abdeckung_meldet_sie_das_auch():
    from app import db
    db.anlegen("belege", {"id": "q1", "uploader": "x", "ts": "2026-06-12T10:00:00",
                          "photo": "p.jpg", "merchant": "dm", "amount": "24,52",
                          "apartment_id": "a1", "datum": "2026-06-12"})
    b = _bewegung(-24.52, "dm", "w1")
    z.hinzufuegen(b["id"], z.BELEG, -24.52, "Reinigung/Verbrauch (dm)", ziel_id="q1")
    a = ub.abdeckung()
    assert a["posten"] == 1 and a["mit_wohnung"] == 1


def test_ohne_wohnung_taucht_der_posten_nicht_in_der_tabelle_auf():
    """Ihn einer Wohnung zuzuschlagen wäre erfunden."""
    b = _bewegung(-300.0, "Rena", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -300.0, "Wäscherei (Rena)")
    assert ub.wohnungen() == {}


def test_der_offene_rest_einer_halben_aufteilung_geht_nicht_verloren():
    """Sonst zeigt der Geldfluss weniger, als vom Konto abging – und der
    fehlende Teil verschwände lautlos statt als offener Posten dazustehen."""
    b = _bewegung(-1000.0, "Sammelabbuchung", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -400.0, "Wäscherei (Rena)")
    m = ub.monate()["2026-06"]
    assert m["ausgang"] == -1000.0
    assert m["ergebnis"] == -400.0
    g = ub.kategorien()
    assert g["Ausgabe"] == [("Wäscherei (Rena)", -400.0)]
    assert g[ub.UNGEKLAERT] == [(konto.OHNE_KATEGORIE, -600.0)]


def test_ein_ergebnis_ohne_zugeordnete_einnahmen_ist_nicht_belastbar():
    """Der wichtigste Befund aus den echten Zahlen: im Juni stand ein Verlust
    von 1.489 €, weil die Einnahmen noch nicht zugeordnet waren. Ohne den
    Hinweis daneben liest man den Verlust als Ergebnis."""
    _bewegung(-300.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    _bewegung(1200.0, "Booking.com BV", "w2")           # noch nicht zugeordnet
    m = ub.monate()["2026-06"]
    assert m["ergebnis"] == -300.0
    assert m["offen_betrag"] == 1200.0
    assert m["belastbar"] is False


def test_ist_alles_zugeordnet_traegt_das_ergebnis():
    _bewegung(-300.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    _bewegung(1200.0, "Gast", "w2",
              kategorie="Beherbergungserlöse (Direktbuchung, brutto)")
    m = ub.monate()["2026-06"]
    assert m["ergebnis"] == 900.0 and m["belastbar"] is True


# ------------------------------------------------------------- Die Anzeige
def _in_client(bauen):
    from nicegui import ui
    from nicegui.client import Client
    with Client(lambda: None):
        with ui.card():
            bauen()


def test_die_seite_laesst_sich_zeichnen():
    from app.ui import ueberblick as ui_ub
    _bewegung(-300.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    _bewegung(1200.0, "Booking.com BV", "w2")
    _in_client(ui_ub.render_ueberblick)


def test_die_seite_haelt_auch_einen_leeren_bestand_aus():
    from app.ui import ueberblick as ui_ub
    _in_client(ui_ub.render_ueberblick)


def test_die_wohnungstabelle_laesst_sich_zeichnen():
    from app.ui import ueberblick as ui_ub
    from app import db, rechnung
    db.anlegen("rechnungen", {"id": "r1", "nummer": "2026-0001", "gast": "Meier",
                              "datum": "2026-06-01", "wohnung": "a1",
                              "status": rechnung.FESTGESCHRIEBEN,
                              "summen": {"brutto": 620.0}})
    b = _bewegung(620.0, "Meier", "w1")
    z.hinzufuegen(b["id"], z.RECHNUNG, 620.0, ziel_id="r1")
    _in_client(lambda: ui_ub._wohnungstabelle({"von": "", "bis": ""}))


def test_der_ueberblick_ist_ein_eigener_bereich():
    """Sonst ist die Seite gebaut, aber nicht erreichbar."""
    from app.ui import basis
    schluessel = [a["key"] for a in basis.AREAS]
    assert "ueberblick" in schluessel
    assert "ueberblick" in basis.ROLE_AREAS["admin"]
    # Putzkraefte und Manager haben dort nichts zu suchen.
    assert "ueberblick" not in basis.ROLE_AREAS["putzkraft"]
    assert "ueberblick" not in basis.ROLE_AREAS["manager"]
