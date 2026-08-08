"""B11: die Auszahlungsberichte der Portale einlesen.

Aus den Bankdaten allein ist nicht zu erkennen, welche Rechnung zu welcher
Auszahlung gehört – die Reservierungsnummer steht nicht im Verwendungszweck.
Die Berichte der Portale schließen die Lücke:

* **Booking** nennt in der Spalte „Statement Descriptor" genau das Kürzel, das
  auf dem Kontoauszug als `NO.vQmQNcef5aDAINyZ` steht. Darunter stehen die
  Reservierungen mit Nummer, Brutto und Provision. An den echten Daten: 46 von
  48 Auszahlungen wiedergefunden, 75 von 75 Reservierungen in Smoobu.
* **Airbnb** liefert keinen Bezug im Verwendungszweck; dort trägt die
  Verknüpfung über Betrag und Datum (7 von 7 eindeutig).
"""
import io

import pytest

from app import portalbericht as pb


def _booking_xlsx(zeilen):
    """Eine Datei im Aufbau des echten Berichts – Kopfzeile plus Datenzeilen."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Booking.com"
    kopf = [""] * 32
    for i, name in ((0, "Type/Transaction type"), (1, "Statement Descriptor"),
                    (2, "Reference number"), (3, "Check-in date"),
                    (4, "Check-out date"), (9, "Property ID"),
                    (15, "Gross amount"), (16, "Commission"),
                    (18, "Payments Service Fee"),
                    (25, "Payable amount"), (26, "Payout amount"),
                    (28, "Payout date")):
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


AUSZAHLUNG = {0: "(Payout)", 1: "vQmQNcef5aDAINyZ", 9: "15049295",
              26: 859.89, 28: "2026-01-01 00:00:00"}
RES_A = {0: "Reservation", 1: "vQmQNcef5aDAINyZ", 2: "6180071938",
         3: "2025-12-25 00:00:00", 4: "2025-12-28 00:00:00", 9: "15049295",
         15: 431.57, 16: -49.5, 18: -6.04, 25: 376.03}
RES_B = {0: "Reservation", 1: "vQmQNcef5aDAINyZ", 2: "6419216970",
         3: "2025-12-22 00:00:00", 4: "2025-12-25 00:00:00", 9: "15049295",
         15: 554.38, 16: -62.76, 18: -7.76, 25: 483.86}


# ------------------------------------------------------------- Das Erkennen
def test_der_booking_bericht_wird_erkannt():
    assert pb.art(_booking_xlsx([AUSZAHLUNG])) == pb.BOOKING


def test_eine_fremde_datei_wird_nicht_erkannt():
    assert pb.art(b"Datum;Betrag\n01.01.2026;5,00\n") == ""


# ------------------------------------------------------------- Das Lesen
def test_die_auszahlung_kommt_mit_ihren_reservierungen():
    a = pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A, RES_B]))
    assert len(a) == 1
    z = a[0]
    assert z["schluessel"] == "vQmQNcef5aDAINyZ"
    assert z["betrag"] == 859.89 and z["datum"] == "2026-01-01"
    assert [r["nummer"] for r in z["reservierungen"]] == ["6180071938", "6419216970"]


def test_brutto_und_provision_stehen_an_der_reservierung():
    """Die Provision kommt damit aus Bookings eigener Quelle – nicht aus
    Smoobu, dessen Zahl der Betrieb als unzuverlässig bezeichnet hat."""
    z = pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A, RES_B]))[0]
    r = z["reservierungen"][0]
    assert r["brutto"] == 431.57 and r["provision"] == -49.5
    assert r["gebuehr"] == -6.04
    assert r["auszahlbar"] == 376.03
    # 431,57 - 49,50 - 6,04 = 376,03. Die Zahlungsgebuehr steht in einer
    # eigenen Spalte und ist nicht Teil der Provision - wer nur die Provision
    # abzieht, kommt auf 382,07 und sucht dann 6,04 Euro.
    assert round(r["brutto"] + r["provision"] + r["gebuehr"], 2) == r["auszahlbar"]


def test_die_summe_der_reservierungen_ergibt_die_auszahlung():
    """376,03 + 483,86 = 859,89 – auf den Cent. Geht es nicht auf, fehlt eine
    Zeile, und das muss auffallen."""
    z = pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A, RES_B]))[0]
    assert z["stimmt"] is True
    assert round(sum(r["auszahlbar"] for r in z["reservierungen"]), 2) == z["betrag"]


def test_eine_fehlende_reservierung_faellt_auf():
    z = pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A]))[0]
    assert z["stimmt"] is False


def test_eine_auszahlung_ohne_reservierungen_wird_uebergangen():
    """Sie sagt nichts – und ohne Reservierungen gibt es nichts zuzuordnen."""
    assert pb.lesen(_booking_xlsx([AUSZAHLUNG])) == []


def test_mehrere_auszahlungen_bleiben_getrennt():
    zweite = {**AUSZAHLUNG, 1: "QzRE0yt4NLvH3zMi", 26: 657.63}
    res_c = {**RES_A, 1: "QzRE0yt4NLvH3zMi", 2: "5901334367", 25: 657.63}
    a = pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A, RES_B, zweite, res_c]))
    assert [x["schluessel"] for x in a] == ["vQmQNcef5aDAINyZ", "QzRE0yt4NLvH3zMi"]
    assert [len(x["reservierungen"]) for x in a] == [2, 1]


# ------------------------------------------------------------- Das Ablegen
def test_der_bericht_wird_gemerkt():
    neu, doppelt = pb.merken(pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A, RES_B])))
    assert (neu, doppelt) == (1, 0)
    assert [a["schluessel"] for a in pb.auszahlungen()] == ["vQmQNcef5aDAINyZ"]


def test_derselbe_bericht_zweimal_aendert_nichts():
    """Der Betrieb laedt immer „01.01. bis heute" – Ueberschneidungen sind der
    Normalfall, nicht die Ausnahme."""
    daten = pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A, RES_B]))
    pb.merken(daten)
    neu, doppelt = pb.merken(daten)
    assert (neu, doppelt) == (0, 1)
    assert len(pb.auszahlungen()) == 1


def test_ein_spaeterer_bericht_ergaenzt_die_reservierungen():
    """Wird eine Auszahlung im ersten Export unvollstaendig geliefert, soll der
    zweite sie vervollstaendigen – nicht danebenlegen."""
    pb.merken(pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A])))
    pb.merken(pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A, RES_B])))
    a = pb.auszahlungen()[0]
    assert len(a["reservierungen"]) == 2 and a["stimmt"] is True


# ------------------------------------------------- Die Bank findet ihre Auszahlung
def test_die_bankbewegung_findet_ihre_auszahlung_ueber_das_kuerzel():
    bewegung = {"id": "w1", "datum": "2026-01-05", "betrag": 859.89,
                "gegenpartei": "Booking.com BV",
                "text": "NO.vQmQNcef5aDAINyZ/ID.15049295 AWV-MELDEPFLICHT"}
    pb.merken(pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A, RES_B])))
    a = pb.zu_bewegung(bewegung)
    assert a and a["schluessel"] == "vQmQNcef5aDAINyZ"


def test_ohne_kuerzel_findet_sie_nichts():
    bewegung = {"id": "w1", "datum": "2026-01-05", "betrag": 859.89,
                "gegenpartei": "Booking.com BV", "text": "AWV-MELDEPFLICHT"}
    pb.merken(pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A, RES_B])))
    assert pb.zu_bewegung(bewegung) is None


def test_ein_fremdes_kuerzel_findet_nichts():
    bewegung = {"id": "w1", "datum": "2026-01-05", "betrag": 859.89,
                "gegenpartei": "Booking.com BV", "text": "NO.GIBTSNICHT/ID.1"}
    pb.merken(pb.lesen(_booking_xlsx([AUSZAHLUNG, RES_A, RES_B])))
    assert pb.zu_bewegung(bewegung) is None


# ------------------------------------------------- Dieselbe Auswahl wie Auszüge
def test_ein_kontoauszug_wird_durchgelassen():
    """`einlesen` gibt None zurück – dann übernimmt der Auszugs-Import."""
    assert pb.einlesen(b"Buchungsdatum;Betrag\n01.01.26;5,00\n") is None


def test_der_bericht_meldet_was_angekommen_ist():
    b = pb.einlesen(_booking_xlsx([AUSZAHLUNG, RES_A, RES_B]))
    assert b["konto"] == "Booking.com" and b["neu"] == 1 and b["doppelt"] == 0
    assert b["auszahlungen"] == 1 and b["reservierungen"] == 2
    assert b["zeitraum"] == ("2026-01-01", "2026-01-01")
    assert b["schief"] == []


def test_eine_unstimmige_auszahlung_wird_gemeldet():
    """Sonst hielte der Betrieb den Bericht für vollständig, obwohl eine
    Reservierung fehlt – und der Rest der Auszahlung bliebe unerklärt."""
    b = pb.einlesen(_booking_xlsx([AUSZAHLUNG, RES_A]))
    assert b["schief"] == ["vQmQNcef5aDAINyZ"]
