#!/usr/bin/env python3
"""Golden-Test Dezember 2025 (korrekte Rechenregeln).

Fixture = echte Smoobu-Rohdaten (Nov 2025 – Jan 2026).

Basis = Preis − durchlaufende Übernachtungssteuer (Reinigung inkl.).
Das eingereichte Formular 2025-12 hatte korrekten Umsatz/Steuer, aber die
Airbnb-Zahl war falsch (7 statt 15). Airbnb beeinflusst die Steuer nicht.
Korrekt: 137 verbl. ÜN, 15 Airbnb, 152 insgesamt, 5.698,29 €, 341,90 €.
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
        self.assertAlmostEqual(self.r["umsatz_verbleibend"], 5698.28, places=2)

    def test_beherbergungssteuer(self):
        self.assertEqual(self.r["beherbergungssteuer"], 341.90)

    def test_nur_stattgefundene_buchungen(self):
        # Stichtag vor Monatsende -> keine noch nicht abgereisten Buchungen
        r = steuer.compute(self.bookings, 2025, 12, today=date(2025, 12, 10))
        for row in r["rows"]:
            self.assertLessEqual(row["departure"], "2025-12-10")

    def test_stornos_und_blocks_ausgeschlossen(self):
        for row in self.r["rows"]:
            self.assertTrue(row["nights"] > 0)


class TestMai2026(unittest.TestCase):
    """Zweiter Golden-Test: verbleibende Umsätze Mai 2026 = 7.155,86 €."""

    def setUp(self):
        fx = os.path.join(os.path.dirname(__file__), "fixture_2026-05.json")
        with open(fx, encoding="utf-8") as f:
            self.bookings = json.load(f)
        self.r = steuer.compute(self.bookings, 2026, 5, today=STICHTAG)

    def test_verbleibende_umsaetze(self):
        self.assertAlmostEqual(self.r["umsatz_verbleibend"], 7155.85, places=2)

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

    def test_basis_entspricht_der_rechnung(self):
        for nr, gast, kanal, details, price, basis, bst in self.RECHNUNGEN:
            with self.subTest(rechnung=nr, gast=gast):
                row = self._row(kanal, details, price)
                self.assertEqual(row["base"], basis)
                self.assertEqual(row["citytax"], bst)
                # Probe: Basis + Steuer = Rechnungsbetrag
                self.assertAlmostEqual(row["base"] + row["citytax"], price, places=2)

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

    def test_ausgewiesener_betrag_schlaegt_die_umrechnung(self):
        """Wernerstraße: Booking.com kassiert 7 %. Dann gilt der ausgewiesene
        Betrag – nicht price/1,06 –, sonst bliebe Steuer in der Basis."""
        row = self._row("Booking.com",
                        "Reinigungsgebühr - EUR 95\r\nÜbernachtungssteuer - EUR 47.56",
                        726.95)
        self.assertEqual(row["citytax"], 47.56)
        self.assertEqual(row["base"], 679.39)
        self.assertNotEqual(row["base"], round(726.95 / 1.06, 2))

    def test_airbnb_bleibt_unberuehrt(self):
        """Airbnb meldet selbst – dort wird nichts herausgerechnet."""
        row = self._row("Airbnb", "Airbnb Collected Tax - EUR 39.36", 656.0)
        self.assertEqual(row["citytax"], 0.0)
        self.assertEqual(row["base"], 656.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
