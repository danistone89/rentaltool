"""Tests für die Mehrsprachigkeit."""
import pytest

from app import i18n


@pytest.fixture(autouse=True)
def reset_resolver():
    """Den vorher gesetzten Resolver wiederherstellen – web.py registriert beim
    Import seinen eigenen, den die UI-Tests danach noch brauchen."""
    vorher = i18n._resolver
    yield
    i18n.set_resolver(vorher)


def _use(code):
    i18n.set_resolver(lambda: code)


def test_deutsch_liefert_den_ausgangstext_unveraendert():
    _use("de")
    assert i18n.t("Anmelden") == "Anmelden"
    assert i18n.t("Beliebiger nie übersetzter Satz") == "Beliebiger nie übersetzter Satz"


def test_englisch_uebersetzt():
    _use("en")
    assert i18n.t("Anmelden") == "Sign in"
    assert i18n.t("Zeiterfassung") == "Time tracking"
    assert i18n.t("Wochenende/Feiertag") == "Weekend/holiday"


def test_fehlende_uebersetzung_faellt_auf_deutsch_zurueck():
    _use("en")
    assert i18n.t("Ein Text ohne Eintrag im Wörterbuch") == "Ein Text ohne Eintrag im Wörterbuch"


def test_platzhalter():
    _use("en")
    assert i18n.t("{n} Erwachsene", n=3) == "3 adults"
    assert i18n.t("{n} Kinder", n=2) == "2 children"
    _use("de")
    assert i18n.t("{n} Erwachsene", n=3) == "3 Erwachsene"


def test_kaputter_platzhalter_wirft_nicht():
    _use("en")
    # falscher Schlüsselname -> unformatierter Text statt KeyError
    assert i18n.t("{n} Erwachsene", falsch=1) == "{n} adults"


def test_unbekannte_sprache_faellt_auf_default():
    _use("kl")
    assert i18n.lang() == "de"
    assert i18n.t("Anmelden") == "Anmelden"


def test_resolver_der_wirft_bricht_nicht():
    def boom():
        raise RuntimeError("keine Session")
    i18n.set_resolver(boom)
    assert i18n.lang() == "de"
    assert i18n.t("Anmelden") == "Anmelden"


def test_keine_leeren_uebersetzungen():
    assert i18n.missing("en") == []


def test_alle_sprachen_haben_einen_namen():
    assert set(i18n.LANGUAGES) == {"de", "en"}
    assert all(v for v in i18n.LANGUAGES.values())
