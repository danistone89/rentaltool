#!/usr/bin/env python3
"""Golden-Test Dezember 2025 (korrekte Rechenregeln).

Fixture = echte Smoobu-Rohdaten (Nov 2025 – Jan 2026).

Basis = Preis / 1,06 (Reinigung inkl.) – von Smoobu wird nur der Gesamtbetrag
genommen, der ausgewiesene Steuerbetrag nicht (siehe `steuer.ohne_citytax`).

**Die Umsatzzahl weicht seit dem 7.8.2026 vom eingereichten Formular ab.**
Eingereicht wurde 5.698,29 € / 341,90 €; damals galt der von Booking.com
ausgewiesene Steuerbetrag. Nach der jetzigen Regel sind es 5.652,71 € /
339,16 € – 2,74 € weniger. Grund: Booking.com wies die Steuer teils zu niedrig
aus (6 % ohne die Reinigungsgebühr), wodurch die Basis zu hoch wurde. Ob die
Dezember-Anmeldung berichtigt wird, ist eine Entscheidung des Betreibers; der
eingereichte Stand bleibt hier dokumentiert.

Übernachtungen sind unberührt: 137 verbl. ÜN, 15 Airbnb, 152 insgesamt. Das
eingereichte Formular hatte dort 7 statt 15 Airbnb – Airbnb beeinflusst die
Steuer nicht.
"""
import json
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import steuer  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixture_2025-12.json")
STICHTAG = date(2026, 6, 29)  # alle Dez-Abreisen liegen davor


class TestDezember2025(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE, encoding="utf-8") as f:
            self.bookings = json.load(f)
        self.r = steuer.compute(self.bookings, 2025, 12, today=STICHTAG)

    def test_verbleibende_uebernachtungen(self):
        self.assertEqual(self.r["uebernachtungen_verbleibend"], 137)

    def test_airbnb_uebernachtungen(self):
        self.assertEqual(self.r["uebernachtungen_airbnb"], 15)

    def test_insgesamt(self):
        self.assertEqual(self.r["uebernachtungen_insgesamt"], 152)

    def test_verbleibende_umsaetze(self):
        # Eingereicht waren 5.698,29 € (Steuerbetrag von Booking.com übernommen).
        self.assertAlmostEqual(self.r["umsatz_verbleibend"], 5652.71, places=2)

    def test_beherbergungssteuer(self):
        self.assertEqual(self.r["beherbergungssteuer"], 339.16)   # eingereicht: 341,90

    def test_jede_buchung_geht_auf(self):
        """Basis + Steuer = Rechnungsbetrag, für jede einzelne Buchung. Genau
        das ging vorher nicht auf: über beide Fixture-Monate klafften 263,31 €
        zwischen dem, was der Gast als Steuer zahlte, und dem, was angemeldet
        wurde."""
        for row in self.r["rows"]:
            self.assertAlmostEqual(row["base"] + row["citytax"], row["price"], places=2)
            if row["citytax"]:
                self.assertAlmostEqual(round(row["base"] * 0.06, 2), row["citytax"],
                                       delta=0.01)

    def test_nur_stattgefundene_buchungen(self):
        # Stichtag vor Monatsende -> keine noch nicht abgereisten Buchungen
        r = steuer.compute(self.bookings, 2025, 12, today=date(2025, 12, 10))
        for row in r["rows"]:
            self.assertLessEqual(row["departure"], "2025-12-10")

    def test_stornos_und_blocks_ausgeschlossen(self):
        for row in self.r["rows"]:
            self.assertTrue(row["nights"] > 0)


class TestMai2026(unittest.TestCase):
    """Zweiter Golden-Test Mai 2026. Vorher 7.155,86 €, jetzt 7.177,01 € –
    hier geht es in die andere Richtung: in diesem Monat wies Booking.com für
    die Wernerstraße 7 % aus, wodurch die Basis zu niedrig wurde."""

    def setUp(self):
        fx = os.path.join(os.path.dirname(__file__), "fixture_2026-05.json")
        with open(fx, encoding="utf-8") as f:
            self.bookings = json.load(f)
        self.r = steuer.compute(self.bookings, 2026, 5, today=STICHTAG)

    def test_verbleibende_umsaetze(self):
        self.assertAlmostEqual(self.r["umsatz_verbleibend"], 7177.01, places=2)

    def test_anzahl_buchungen(self):
        self.assertEqual(len(self.r["remaining_rows"]), 14)


class TestGastrechnungen(unittest.TestCase):
    """Gegen echte Gastrechnungen validiert (Juli 2026, Rechnungen 60–78).

    Jede Rechnung weist die Übernachtungssteuer als eigene Position mit 0 % USt
    aus; der Rechnungsbetrag ist brutto INKLUSIVE dieser Steuer. Die Basis der
    App muss der Summe aus Übernachtung + Reinigungsgebühr entsprechen.

    Rechnung 60 (Anja Ernst) ist der wichtige Fall: Direktbuchung, Smoobu
    liefert dazu KEINE Steuerzeile (`price-details` ist leer) – die 22,65 €
    stecken trotzdem im Preis und müssen herausgerechnet werden.
    """

    # (Rechnung, Gast, Kanal, price-details, price, Basis lt. Rg., BSt lt. Rg.)
    RECHNUNGEN = [
        (60, "Anja Ernst", "Direct booking",
         "", 400.07, 377.42, 22.65),
        (74, "Katarina Gockel", "Direct booking",
         "", 379.48, 358.00, 21.48),
        (61, "Kusala Sami", "Booking.com",
         "Reinigungsgebühr - EUR 95\r\nÜbernachtungssteuer - EUR 14.22",
         217.30, 203.08, 14.22),
        (71, "Christian Michael", "Booking.com",
         "Reinigungsgebühr - EUR 95\r\nMehrwertsteuer - EUR 38.23\r\n"
         "Übernachtungssteuer - EUR 47.56",
         726.95, 679.39, 47.56),
        (77, "Jan Peters", "Booking.com",
         "Reinigungsgebühr - EUR 75\r\nÜbernachtungssteuer - EUR 18.09",
         319.59, 301.50, 18.09),
        (78, "Alexander Josan", "Booking.com",
         "Reinigungsgebühr - EUR 75\r\nÜbernachtungssteuer - EUR 26.02",
         459.68, 433.66, 26.02),
    ]

    def _row(self, kanal, details, price):
        b = {"id": 1, "type": "reservation", "is-blocked-booking": False,
             "apartment": {"id": 1, "name": "Test"},
             "arrival": "2026-07-01", "departure": "2026-07-03",
             "adults": 2, "children": 0, "guest-name": "X",
             "channel": {"name": kanal},
             "price": price, "price-details": details}
        return steuer.classify(b, 2026, 7, today=date(2026, 8, 1))

    # Rechnungen, deren ausgewiesene Steuer schon 6 % der Basis inkl. Reinigung
    # war – dort ändert die neue Regel nichts, sie trifft dieselbe Zahl.
    STIMMIG = {60, 74, 77, 78}

    def test_basis_entspricht_der_rechnung(self):
        """Wo das Portal richtig gerechnet hat, trifft die Umrechnung die
        Rechnung auf den Cent – das ist der Beleg, dass price/1,06 nicht
        geraten ist, sondern die Umkehrung dessen, was auf dem Beleg steht."""
        for nr, gast, kanal, details, price, basis, bst in self.RECHNUNGEN:
            if nr not in self.STIMMIG:
                continue
            with self.subTest(rechnung=nr, gast=gast):
                row = self._row(kanal, details, price)
                self.assertEqual(row["base"], basis)
                self.assertEqual(row["citytax"], bst)
                self.assertAlmostEqual(row["base"] + row["citytax"], price, places=2)

    def test_bei_falsch_gerechneten_rechnungen_weicht_die_app_bewusst_ab(self):
        """Rechnungen 61 und 71 (Wernerstraße, 7 %): dort wies Booking.com mehr
        Steuer aus, als die Satzung vorsieht. Der Gast hat den Gesamtbetrag
        gezahlt – der Überhang ist keine Steuer, die wir schulden, sondern
        Entgelt. Die App teilt deshalb anders auf als der damalige Beleg."""
        for nr, gast, kanal, details, price, basis_rg, bst_rg in self.RECHNUNGEN:
            if nr in self.STIMMIG:
                continue
            with self.subTest(rechnung=nr, gast=gast):
                row = self._row(kanal, details, price)
                self.assertNotEqual(row["citytax"], bst_rg, "Portalwert übernommen")
                self.assertLess(row["citytax"], bst_rg, "7 % müssen auf 6 % sinken")
                self.assertGreater(row["base"], basis_rg, "Der Überhang gehört ins Entgelt")
                self.assertAlmostEqual(row["base"] + row["citytax"], price, places=2)

    def test_jede_rechnung_geht_auf_und_traegt_glatte_sechs_prozent(self):
        """Die Eigenschaft, die vorher fehlte: für JEDE Buchung gilt
        Basis + Steuer = Rechnungsbetrag UND Steuer = 6 % der Basis. Solange der
        Portalwert galt, war beides zusammen nicht zu haben."""
        for nr, gast, kanal, details, price, _b, _s in self.RECHNUNGEN:
            with self.subTest(rechnung=nr, gast=gast):
                row = self._row(kanal, details, price)
                self.assertAlmostEqual(row["base"] + row["citytax"], price, places=2)
                self.assertAlmostEqual(row["citytax"] / row["base"], 0.06, places=4)

    def test_direktbuchung_wird_herausgerechnet(self):
        """Rechnung 60: ohne Steuerzeile trotzdem 377,42 € Basis, nicht 400,07 €."""
        row = self._row("Direct booking", "", 400.07)
        self.assertEqual(row["base"], 377.42)
        self.assertEqual(row["citytax"], 22.65)

    def test_beide_direktrechnungen_ergeben_glatte_sechs_prozent(self):
        """Gegenprobe zur Regel: bei beiden Direktbuchungs-Rechnungen ist die
        ausgewiesene Steuer exakt 6 % der Basis – price/1,06 ist also nicht
        geraten, sondern die Umkehrung dessen, was auf der Rechnung steht."""
        for price, basis, bst in ((400.07, 377.42, 22.65), (379.48, 358.00, 21.48)):
            with self.subTest(price=price):
                self.assertAlmostEqual(bst / basis, 0.06, places=4)
                row = self._row("Direct booking", "", price)
                self.assertEqual(row["base"], basis)

    def test_der_ausgewiesene_betrag_wird_ignoriert(self):
        """Die Umkehrung der früheren Regel, und der Grund dafür.

        Vorher galt der ausgewiesene Betrag. Dann wies die Gastrechnung 47,56 €
        Steuer aus, angemeldet wurden aber 6 % von 679,39 € = 40,76 €: 6,80 €
        kamen in keiner der beiden Zahlen vor. Aus dem Gesamtbetrag gerechnet
        nennen Rechnung und Anmeldung dieselben 41,15 €."""
        row = self._row("Booking.com",
                        "Reinigungsgebühr - EUR 95\r\nÜbernachtungssteuer - EUR 47.56",
                        726.95)
        self.assertEqual(row["citytax"], 41.15)
        self.assertEqual(row["base"], 685.80)
        self.assertEqual(row["base"], round(726.95 / 1.06, 2))
        self.assertAlmostEqual(round(row["base"] * 0.06, 2), row["citytax"], delta=0.01)

    def test_auch_zu_niedrig_ausgewiesene_steuer_wird_ignoriert(self):
        """Der häufigere Fall: 6 % nur auf die Übernachtung, die Reinigung fehlt
        in der Basis. 76 von 135 Buchungen der Fixture-Monate sehen so aus."""
        row = self._row("Booking.com",
                        "Reinigungsgebühr - EUR 95\r\nÜbernachtungssteuer - EUR 13.28",
                        329.68)
        self.assertNotEqual(row["citytax"], 13.28)
        self.assertEqual(row["citytax"], 18.66)
        self.assertEqual(row["base"], 311.02)

    def test_airbnb_bleibt_unberuehrt(self):
        """Airbnb meldet selbst – dort wird nichts herausgerechnet."""
        row = self._row("Airbnb", "Airbnb Collected Tax - EUR 39.36", 656.0)
        self.assertEqual(row["citytax"], 0.0)
        self.assertEqual(row["base"], 656.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
