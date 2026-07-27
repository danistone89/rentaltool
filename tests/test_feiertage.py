"""Tests für die sächsischen Feiertage und die Tagesart-Einstufung."""
from datetime import date

from app import feiertage


def test_ostersonntag():
    # Referenzwerte aus dem Kirchenkalender
    assert feiertage.ostersonntag(2024) == date(2024, 3, 31)
    assert feiertage.ostersonntag(2025) == date(2025, 4, 20)
    assert feiertage.ostersonntag(2026) == date(2026, 4, 5)
    assert feiertage.ostersonntag(2027) == date(2027, 3, 28)


def test_buss_und_bettag_ist_mittwoch_vor_dem_23_november():
    for jahr, tag in ((2025, date(2025, 11, 19)), (2026, date(2026, 11, 18)),
                      (2027, date(2027, 11, 17))):
        assert feiertage.buss_und_bettag(jahr) == tag
        assert feiertage.buss_und_bettag(jahr).weekday() == 2


def test_sachsen_hat_elf_feiertage():
    for jahr in range(2024, 2031):
        assert len(feiertage.feiertage(jahr)) == 11


def test_feiertagsnamen_2026():
    f = feiertage.feiertage(2026)
    assert f[date(2026, 1, 1)] == "Neujahr"
    assert f[date(2026, 4, 3)] == "Karfreitag"
    assert f[date(2026, 4, 6)] == "Ostermontag"
    assert f[date(2026, 5, 14)] == "Christi Himmelfahrt"
    assert f[date(2026, 5, 25)] == "Pfingstmontag"
    assert f[date(2026, 10, 31)] == "Reformationstag"
    assert f[date(2026, 11, 18)] == "Buß- und Bettag"


def test_fronleichnam_ist_kein_feiertag_in_dresden():
    # Fronleichnam = Ostern + 60 Tage, in Sachsen nur in sorbischen Gemeinden
    assert not feiertage.is_feiertag(date(2026, 6, 4))


def test_kind_of_werktag_und_wochenende():
    assert feiertage.kind_of(date(2026, 7, 1)) == feiertage.WERKTAG    # Mittwoch
    assert feiertage.kind_of(date(2026, 7, 4)) == feiertage.WOCHENENDE  # Samstag
    assert feiertage.kind_of(date(2026, 7, 5)) == feiertage.WOCHENENDE  # Sonntag
    assert feiertage.kind_of(date(2026, 5, 1)) == feiertage.WOCHENENDE  # Feiertag (Fr)


def test_label_of():
    assert feiertage.label_of(date(2026, 5, 1)) == "Tag der Arbeit"
    assert feiertage.label_of(date(2026, 7, 4)) == "Samstag"
    assert feiertage.label_of(date(2026, 7, 5)) == "Sonntag"
    assert feiertage.label_of(date(2026, 7, 1)) == "Werktag"
