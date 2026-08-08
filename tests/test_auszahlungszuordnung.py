"""B11d: eine Portal-Auszahlung in einem Zug zuordnen.

Die Kette, die B11b/c gelegt haben, wird hier abgelaufen:

    Bankbewegung → Auszahlung → Reservierungsnummer → Smoobu-Buchung → Rechnung

Gebucht wird der **Rechnungsbetrag**, nicht der Auszahlungsanteil – sonst wäre
der Umsatz um die Provision zu niedrig. Was bis zum Aufgehen der Bewegung
fehlt, ist die einbehaltene Provision; der Bericht sagt, wie hoch sie sein
müsste, und eine Abweichung wird gezeigt statt geglättet.
"""
import io

import pytest

from app import auszahlungszuordnung as az
from app import db, portalbericht as pb, rechnung, zuordnung


# ---------------------------------------------------------------- Aufbau
def _bericht(zeilen):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    kopf = [""] * 32
    for i, name in ((0, "Type/Transaction type"), (1, "Statement Descriptor"),
                    (2, "Reference number"), (9, "Property ID"),
                    (15, "Gross amount"), (16, "Commission"),
                    (18, "Payments Service Fee"), (25, "Payable amount"),
                    (26, "Payout amount"), (28, "Payout date")):
        kopf[i] = name
    ws.append(kopf)
    for z in zeilen:
        reihe = [""] * 32
        for i, wert in z.items():
            reihe[i] = wert
        ws.append(reihe)
    puffer = io.BytesIO()
    wb.save(puffer)
    return puffer.getvalue()


KUERZEL = "vQmQNcef5aDAINyZ"
AUSZAHLUNG = {0: "(Payout)", 1: KUERZEL, 26: 859.89, 28: "2026-01-01 00:00:00"}
# 431,57 - 49,50 - 6,04 = 376,03 und 554,38 - 62,76 - 7,76 = 483,86.
RES_A = {0: "Reservation", 1: KUERZEL, 2: "6180071938", 15: 431.57, 16: -49.5,
         18: -6.04, 25: 376.03}
RES_B = {0: "Reservation", 1: KUERZEL, 2: "6419216970", 15: 554.38, 16: -62.76,
         18: -7.76, 25: 483.86}

BEWEGUNG = {"id": "w1", "datum": "2026-01-05", "betrag": 859.89,
            "konto": "Giro", "gegenpartei": "Booking.com BV",
            "text": f"NO.{KUERZEL}/ID.15049295"}


def _buchungen(*paare):
    """Smoobu-Buchungen als {id: Satz}, wie die Oberfläche sie hält."""
    return {b["id"]: b for b in
            [{"id": bid, "reference-id": ref, "guest-name": "Gast"}
             for bid, ref in paare]}


def _rechnung(rid, buchung, brutto, nummer="1", status=None):
    satz = {"id": rid, "buchung": buchung, "nummer": nummer, "gast": "Gast",
            "status": status or rechnung.GESENDET,
            "summen": {"brutto": brutto}}
    db.anlegen(rechnung.TABELLE, satz, rid)
    return satz


def _stelle_auf(**abweichend):
    """Der Normalfall: Bericht eingelesen, beide Rechnungen vorhanden."""
    pb.merken(pb.lesen(_bericht([AUSZAHLUNG, RES_A, RES_B])))
    db.anlegen("bewegungen", BEWEGUNG, BEWEGUNG["id"])
    buchungen = _buchungen((111, "6180071938"), (222, "6419216970"))
    _rechnung("r1", 111, abweichend.get("brutto_a", 431.57), nummer="41")
    _rechnung("r2", 222, abweichend.get("brutto_b", 554.38), nummer="42")
    return buchungen


# ---------------------------------------------------------------- Vorschau
def test_ohne_bericht_gibt_es_nichts_vorzuschlagen():
    db.anlegen("bewegungen", BEWEGUNG, BEWEGUNG["id"])
    assert az.vorschau(BEWEGUNG, {}) is None


def test_die_vorschau_findet_beide_rechnungen():
    buchungen = _stelle_auf()
    v = az.vorschau(BEWEGUNG, buchungen)
    assert [z["rechnung"]["nummer"] for z in v["zeilen"]] == ["41", "42"]
    assert v["rechnungssumme"] == 985.95
    assert v["vollstaendig"] is True


def test_der_rest_ist_die_einbehaltene_provision():
    """859,89 − 985,95 = −126,06. Und laut Bericht: 49,50 + 6,04 + 62,76 +
    7,76 = 126,06. Beide Wege müssen zur selben Zahl führen."""
    v = az.vorschau(BEWEGUNG, _stelle_auf())
    assert v["rest"] == -126.06
    assert v["laut_bericht"] == -126.06
    assert v["weicht_ab"] is False


def test_eine_abweichung_wird_gezeigt_statt_geglaettet():
    """Stimmt der Rechnungsbetrag nicht mit dem überein, was das Portal
    abgerechnet hat, ist das ein Befund – kein Rundungsfehler."""
    v = az.vorschau(BEWEGUNG, _stelle_auf(brutto_a=400.0))
    assert v["weicht_ab"] is True
    assert v["rest"] == -94.49 and v["laut_bericht"] == -126.06


def test_eine_reservierung_ohne_rechnung_faellt_auf():
    pb.merken(pb.lesen(_bericht([AUSZAHLUNG, RES_A, RES_B])))
    db.anlegen("bewegungen", BEWEGUNG, BEWEGUNG["id"])
    buchungen = _buchungen((111, "6180071938"), (222, "6419216970"))
    _rechnung("r1", 111, 431.57, nummer="41")
    v = az.vorschau(BEWEGUNG, buchungen)
    assert v["vollstaendig"] is False
    assert v["zeilen"][1]["problem"] == "zu dieser Buchung gibt es noch keine Rechnung"


def test_eine_reservierung_ohne_smoobu_buchung_faellt_auf():
    pb.merken(pb.lesen(_bericht([AUSZAHLUNG, RES_A, RES_B])))
    db.anlegen("bewegungen", BEWEGUNG, BEWEGUNG["id"])
    v = az.vorschau(BEWEGUNG, _buchungen((111, "6180071938")))
    assert v["zeilen"][1]["problem"] == "Reservierung nicht in Smoobu gefunden"


def test_ein_entwurf_gilt_nicht_als_rechnung():
    """Ein Entwurf trägt keine Nummer und ist nie hinausgegangen – eine
    Auszahlung bezahlt ihn nicht."""
    pb.merken(pb.lesen(_bericht([AUSZAHLUNG, RES_A, RES_B])))
    db.anlegen("bewegungen", BEWEGUNG, BEWEGUNG["id"])
    buchungen = _buchungen((111, "6180071938"), (222, "6419216970"))
    _rechnung("r1", 111, 431.57, nummer="41")
    _rechnung("r2", 222, 554.38, nummer="", status=rechnung.ENTWURF)
    v = az.vorschau(BEWEGUNG, buchungen)
    assert v["zeilen"][1]["rechnung"] is None and v["vollstaendig"] is False


def test_eine_schon_vergebene_rechnung_wird_nicht_zweimal_gebucht():
    buchungen = _stelle_auf()
    zuordnung.hinzufuegen("w9", zuordnung.RECHNUNG, 431.57, ziel_id="r1",
                          kategorie="Beherbergungserlöse (Booking, netto Auszahlung)")
    v = az.vorschau(BEWEGUNG, buchungen)
    assert v["zeilen"][0]["problem"] == "Rechnung hängt schon an einer anderen Bewegung"
    assert v["rechnungssumme"] == 554.38


# ---------------------------------------------------------------- Übernehmen
def test_uebernehmen_legt_die_rechnungsposten_an():
    buchungen = _stelle_auf()
    anzahl, _ = az.uebernehmen(BEWEGUNG, "Provision Booking", buchungen)
    posten = zuordnung.posten("w1")
    assert anzahl == 3                       # zwei Rechnungen und die Provision
    assert sorted(round(p["betrag"], 2) for p in posten) == [-126.06, 431.57, 554.38]


def test_danach_geht_die_bewegung_auf():
    """Der Punkt der ganzen Übung: Restbetrag null, ohne Handarbeit."""
    buchungen = _stelle_auf()
    az.uebernehmen(BEWEGUNG, "Provision Booking", buchungen)
    assert zuordnung.ist_fertig(BEWEGUNG)


def test_die_rechnungsposten_tragen_den_erloes():
    buchungen = _stelle_auf()
    az.uebernehmen(BEWEGUNG, "Provision Booking", buchungen)
    erloese = [p for p in zuordnung.posten("w1") if p["art"] == zuordnung.RECHNUNG]
    assert all(p["kategorie"] == "Beherbergungserlöse (Booking, netto Auszahlung)"
               for p in erloese)


def test_ohne_kategorie_entsteht_kein_provisionsposten():
    """Ein Posten ohne Kategorie steht in keiner Auswertung. Lieber bleibt die
    Bewegung offen – dann sieht man sie wenigstens."""
    buchungen = _stelle_auf()
    anzahl, meldung = az.uebernehmen(BEWEGUNG, "", buchungen)
    assert anzahl == 2 and not zuordnung.ist_fertig(BEWEGUNG)
    assert "Kategorie" in meldung


def test_ohne_vollstaendigkeit_entsteht_kein_provisionsposten():
    """Fehlt eine Rechnung, ist der Rest nicht nur Provision – er enthält auch
    die fehlende Rechnung. Unter „Provision" verschwände sie spurlos."""
    pb.merken(pb.lesen(_bericht([AUSZAHLUNG, RES_A, RES_B])))
    db.anlegen("bewegungen", BEWEGUNG, BEWEGUNG["id"])
    buchungen = _buchungen((111, "6180071938"), (222, "6419216970"))
    _rechnung("r1", 111, 431.57, nummer="41")
    anzahl, meldung = az.uebernehmen(BEWEGUNG, "Provision Booking", buchungen)
    assert anzahl == 1
    assert not any(p["art"] == zuordnung.KATEGORIE for p in zuordnung.posten("w1"))
    assert "ohne Rechnung" in meldung


def test_zweimal_uebernehmen_bucht_nicht_doppelt():
    buchungen = _stelle_auf()
    az.uebernehmen(BEWEGUNG, "Provision Booking", buchungen)
    anzahl, _ = az.uebernehmen(BEWEGUNG, "Provision Booking", buchungen)
    assert anzahl == 0
    assert len(zuordnung.posten("w1")) == 3


def test_die_abweichung_steht_in_der_meldung():
    buchungen = _stelle_auf(brutto_a=400.0)
    _, meldung = az.uebernehmen(BEWEGUNG, "Provision Booking", buchungen)
    assert "Achtung" in meldung and "126,06".replace(",", ".") in meldung


# ------------------------------------------------- Die Kategorie wird gelernt
def test_die_provisionskategorie_wird_gemerkt():
    """Es gibt keine Vorgabe dafür – die Vorgabekategorien sind wörtlich die
    SUMIF-Kriterien des Workbooks. Statt eine zu erfinden, merkt sich das
    Werkzeug die, die schon einmal an einem Provisionsposten stand."""
    buchungen = _stelle_auf()
    assert az.vorschau(BEWEGUNG, buchungen)["kategorie"] == ""
    az.uebernehmen(BEWEGUNG, "Provision Booking", buchungen)
    assert az.provisionskategorie() == "Provision Booking"


def test_eine_gewoehnliche_ausgabe_gilt_nicht_als_provision():
    """Sonst schlüge das Werkzeug beim nächsten Mal „Bankgebühr" als
    Provisionskategorie vor."""
    zuordnung.hinzufuegen("w7", zuordnung.KATEGORIE, -4.9,
                          kategorie="Kontoführung/Bankgebühr DKB",
                          notiz="Kontoführung")
    assert az.provisionskategorie() == ""


def test_die_vorschau_laesst_sich_zeichnen():
    """Rauchprobe: die Maske im Kontoblatt baut sich mit echten Daten auf."""
    from nicegui import ui
    from nicegui.client import Client
    from app.ui import kontoblatt
    buchungen = _stelle_auf()
    with Client(lambda: None):
        with ui.card():
            kontoblatt._auszahlungsvorschau(BEWEGUNG, buchungen, lambda: None)


def test_ohne_auszahlung_zeichnet_sie_nichts():
    """Bei einer gewöhnlichen Bewegung darf der Bereich gar nicht erscheinen."""
    from nicegui import ui
    from nicegui.client import Client
    from app.ui import kontoblatt
    with Client(lambda: None):
        with ui.card() as karte:
            kontoblatt._auszahlungsvorschau(
                {"id": "w5", "datum": "2026-01-05", "betrag": 20.0,
                 "gegenpartei": "Rewe", "text": "Einkauf"}, {}, lambda: None)
    assert not karte.default_slot.children


# --------------------------------------- Wenn die Auszahlung gar nicht passt
def test_eine_ratenzahlung_wird_nicht_zugeordnet():
    """Airbnb zahlt einen langen Aufenthalt in Monatsraten aus – 86 Nächte,
    6.102,99 € in drei Raten. Die Rechnung gehört dann nicht an eine einzelne
    Rate. Ohne diese Sperre hätten 4.540 € unter „Provision" gestanden."""
    buchungen = _stelle_auf(brutto_a=6102.99)
    v = az.vorschau(BEWEGUNG, buchungen)
    assert v["deckt_nicht"] is True and v["weicht_ab"] is False
    anzahl, meldung = az.uebernehmen(BEWEGUNG, "Provision Booking", buchungen)
    assert anzahl == 0 and zuordnung.posten("w1") == []
    assert "Raten" in meldung


def test_bei_einer_abweichung_entsteht_kein_provisionsposten():
    """Ist die Rechnung niedriger als das, was das Portal dem Gast berechnet
    hat, ist der Rest nicht bloß Provision – bei den übernommenen
    Smoobu-Rechnungen steckt die Beherbergungssteuer darin. Die Rechnungen
    gehören trotzdem an diese Auszahlung."""
    buchungen = _stelle_auf(brutto_a=400.0)
    anzahl, meldung = az.uebernehmen(BEWEGUNG, "Provision Booking", buchungen)
    assert anzahl == 2
    assert not any(p["art"] == zuordnung.KATEGORIE for p in zuordnung.posten("w1"))
    assert "nicht nur Provision" in meldung


def test_bei_einer_ratenzahlung_gibt_es_keinen_uebernehmen_knopf():
    """Was nicht gebucht werden darf, soll auch nicht anklickbar sein."""
    from nicegui import ui
    from nicegui.client import Client
    from app.ui import kontoblatt
    buchungen = _stelle_auf(brutto_a=6102.99)
    with Client(lambda: None) as client:
        with ui.card():
            kontoblatt._auszahlungsvorschau(BEWEGUNG, buchungen, lambda: None)
        marker = [m for e in client.elements.values()
                  for m in (getattr(e, "_markers", None) or [])]
    assert "az-w1" in marker          # die Vorschau steht da
    assert "az-add-w1" not in marker  # der Knopf nicht
