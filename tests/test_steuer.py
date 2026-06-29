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


if __name__ == "__main__":
    unittest.main(verbosity=2)
