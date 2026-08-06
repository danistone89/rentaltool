"""AP11: der Weg einer Monatsmeldung – Frist, Status, Vollständigkeit.

Die Frist ist der 7. des Folgemonats, für Meldung *und* Überweisung. Fällt sie
auf ein Wochenende oder einen Feiertag, verschiebt sie sich auf den nächsten
Werktag (§ 108 Abs. 3 AO). Genau diese Verschiebung ist der Test, der hier am
meisten trägt: eine Frist, die einen Tag zu früh mahnt, nervt – eine, die einen
Tag zu spät mahnt, kostet Säumniszuschlag.
"""
from datetime import date

import pytest

from app import archive, data, meldung as m


@pytest.fixture(autouse=True)
def ab_wann(monkeypatch):
    """Startmonat festnageln.

    Ohne das hingen die Tests am echten Archiv des Rechners, auf dem sie
    laufen – auf dem Server wäre dasselbe Ergebnis ein anderes.
    """
    monkeypatch.setitem(data.CONFIG, "meldungen_ab", "2026-01")
    monkeypatch.setattr(archive, "list_entries", lambda: [])


# ------------------------------------------------------------------ Frist
@pytest.mark.parametrize("periode,erwartet", [
    ("2026-06", "2026-07-07"),      # Dienstag – bleibt
    ("2026-07", "2026-08-07"),      # Freitag – bleibt
    ("2025-12", "2026-01-07"),      # Jahreswechsel
])
def test_frist_ist_der_siebte_des_folgemonats(periode, erwartet):
    assert m.frist(periode).isoformat() == erwartet


def test_frist_am_wochenende_rutscht_auf_montag():
    """7.3.2026 ist ein Samstag."""
    assert date(2026, 3, 7).weekday() == 5
    assert m.frist("2026-02") == date(2026, 3, 9)


def test_frist_am_feiertag_rutscht_weiter():
    """Wäre der 7. ein sächsischer Feiertag, zählt der nächste Werktag."""
    jahr = 2026
    for monat in range(1, 13):
        f = m.frist(m.periode(jahr, monat - 1 if monat > 1 else 12))
        assert f.weekday() < 5, f"{f} faellt aufs Wochenende"
        from app import feiertage
        assert not feiertage.is_feiertag(f), f"{f} ist ein Feiertag"


def test_ueberfaellig_wird_negativ_gezaehlt():
    assert m.tage_bis_frist("2026-07", heute=date(2026, 8, 5)) == 2
    assert m.tage_bis_frist("2026-07", heute=date(2026, 8, 7)) == 0
    assert m.tage_bis_frist("2026-07", heute=date(2026, 8, 10)) == -3


# ------------------------------------------------------------------ Status
def test_neuer_monat_ist_offen():
    assert m.status("2026-07") == m.OFFEN


def test_stufen_bauen_aufeinander_auf():
    m.erzeugt("2026-07", "nutzer")
    assert m.status("2026-07") == m.ERZEUGT
    m.gesendet("2026-07", "nutzer", an="stadt@dresden.de")
    assert m.status("2026-07") == m.GESENDET
    m.bezahlt("2026-07", "nutzer")
    assert m.status("2026-07") == m.BEZAHLT


def test_senden_setzt_erzeugt_mit(monkeypatch):
    """Wer sendet, hat erzeugt – der Versand legt das PDF selbst ab."""
    m.gesendet("2026-07", "nutzer")
    e = m.eintrag("2026-07")
    assert e["erzeugt"] and e["gesendet"]


def test_ein_dokument_im_archiv_zaehlt_als_erzeugt(monkeypatch):
    """Das Archiv ist die Wahrheit über „erzeugt": ein PDF entsteht nie, ohne
    abgelegt zu werden. Auch Anmeldungen von vor AP11 sollen richtig dastehen."""
    monkeypatch.setattr(archive, "list_entries",
                        lambda: [{"period": "2026-05", "revision": 1}])
    assert m.status("2026-05") == m.ERZEUGT
    assert m.status("2026-04") == m.OFFEN


def test_bezahlt_bestaetigt_ein_mensch():
    """Die App sieht das Bankkonto nicht – deshalb steht dran, wer es war."""
    m.bezahlt("2026-07", "daniel")
    assert m.eintrag("2026-07")["bezahlt_von"] == "daniel"


def test_zuruecknehmen_raeumt_auch_das_darauf_auf():
    """„Nicht gesendet, aber bezahlt" ist ein Zustand, den es nicht gibt."""
    m.gesendet("2026-07", "nutzer")
    m.bezahlt("2026-07", "nutzer")
    m.zuruecknehmen("2026-07", m.GESENDET)
    assert m.status("2026-07") == m.ERZEUGT


def test_nur_bezahlt_zuruecknehmen_laesst_gesendet_stehen():
    m.gesendet("2026-07", "nutzer")
    m.bezahlt("2026-07", "nutzer")
    m.zuruecknehmen("2026-07", m.BEZAHLT)
    assert m.status("2026-07") == m.GESENDET


# ------------------------------------------------------------------ Übersicht
def test_offene_zaehlen_den_laufenden_monat_nicht_mit():
    """Der laufende Monat ist noch gar nicht zu melden."""
    offen = m.offene(heute=date(2026, 8, 20), monate_zurueck=3)
    perioden = [e["periode"] for e in offen]
    assert "2026-08" not in perioden
    assert perioden == ["2026-05", "2026-06", "2026-07"]


def test_bezahlte_monate_verschwinden_aus_der_liste():
    m.bezahlt("2026-07", "nutzer")
    perioden = [e["periode"] for e in m.offene(heute=date(2026, 8, 20), monate_zurueck=3)]
    assert "2026-07" not in perioden


def test_ueberfaellig_ist_was_die_frist_gerissen_hat():
    """Am 8.8. ist der Juli überfällig, der Juni sowieso."""
    faellig = [e["periode"] for e in m.ueberfaellig(heute=date(2026, 8, 8))]
    assert "2026-07" in faellig
    # Am 6.8. war der Juli noch nicht so weit.
    assert "2026-07" not in [e["periode"] for e in m.ueberfaellig(heute=date(2026, 8, 6))]


# -------------------------------------------------- Vollständigkeitsprüfung
def _ergebnis(**felder):
    grund = {"year": 2026, "month": 7, "rows": [{"id": 1}],
             "uebernachtungen_airbnb": 0, "umsatz_steuerpflichtig": 400.0}
    grund.update(felder)
    return grund


def _buchung(**felder):
    grund = {"id": 1, "type": "reservation", "is-blocked-booking": False,
             "arrival": "2026-07-01", "departure": "2026-07-05"}
    grund.update(felder)
    return grund


def test_abgeschlossener_sauberer_monat_hat_keinen_befund():
    assert m.vollstaendigkeit(_ergebnis(), [_buchung()], heute=date(2026, 8, 3)) == []


def test_laufender_monat_faellt_auf():
    """Wer am 3. Juli den Juli meldet, meldet zwei Drittel davon."""
    befund = m.vollstaendigkeit(_ergebnis(), [_buchung()], heute=date(2026, 7, 3))
    assert any("läuft noch" in z for z in befund)


def test_kuenftige_abreisen_werden_gezaehlt():
    """`steuer.classify` wirft sie still weg – hier bekommen sie eine Stimme."""
    buchungen = [_buchung(id=1, departure="2026-07-05"),
                 _buchung(id=2, departure="2026-07-28")]
    befund = m.vollstaendigkeit(_ergebnis(), buchungen, heute=date(2026, 7, 10))
    assert any("reisen erst nach heute ab" in z for z in befund)


def test_buchung_ohne_abreisedatum_faellt_auf():
    """Sie fällt aus der Rechnung, ohne aufzufallen – das ist der gefährliche
    Teil: die Summe sieht plausibel aus, ist aber zu niedrig."""
    befund = m.vollstaendigkeit(_ergebnis(), [_buchung(departure=None)],
                                heute=date(2026, 8, 3))
    assert any("kein Abreisedatum" in z for z in befund)


def test_leerer_monat_faellt_auf():
    befund = m.vollstaendigkeit(_ergebnis(rows=[]), [], heute=date(2026, 8, 3))
    assert any("keine einzige Buchung" in z for z in befund)


def test_stornos_und_blockaden_zaehlen_nicht_als_luecke():
    buchungen = [_buchung(id=1),
                 _buchung(id=2, departure=None, type="cancellation"),
                 _buchung(id=3, departure=None, **{"is-blocked-booking": True})]
    assert m.vollstaendigkeit(_ergebnis(), buchungen, heute=date(2026, 8, 3)) == []


def test_zweites_pdf_nach_dem_versand_ist_eine_korrekturmeldung():
    """Das darf man – aber man soll wissen, dass man es tut."""
    m.gesendet("2026-07", "nutzer")
    befund = m.vollstaendigkeit(_ergebnis(), [_buchung()], heute=date(2026, 8, 3))
    assert any("Korrekturmeldung" in z for z in befund)


# ----------------------------------------------------------- Die Oberfläche
from nicegui.testing import User            # noqa: E402
from app import auth, data, mailer, web     # noqa: E402


@pytest.fixture
def app_bereit(monkeypatch):
    monkeypatch.setattr(data, "get_apartments", lambda: [
        {"id": 2748963, "name": "Cottaer Straße"}])
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [])
    monkeypatch.setattr(mailer, "send_notify", lambda *a, **k: None)
    monkeypatch.setitem(web.USERS, "nutzer", {
        "password_hash": auth.hash_password("geheim"), "role": "admin",
        "totp_secret": "", "name": "nutzer"})
    web._APARTMENTS.clear()


async def _anmelden(user):
    await user.open("/login")
    user.find(marker="login-user").type("nutzer")
    user.find(marker="login-pw").type("geheim")
    user.find("Anmelden").click()
    await user.open("/")
    user.find(marker="nav-beherbergungssteuer").click()


async def test_steuerbereich_zeigt_zuerst_was_ansteht(user: User, app_bereit):
    """Wer den Bereich öffnet, will meistens wissen, ob noch etwas offen ist –
    nicht sofort rechnen."""
    await _anmelden(user)
    await user.should_see(marker="meldungen")
    await user.should_see("Offene Meldungen")


async def test_offener_monat_steht_mit_frist_da(user: User, app_bereit):
    await _anmelden(user)
    vormonat = m.offene()[-1]["periode"]
    await user.should_see(marker=f"meldung-{vormonat}")


async def test_bezahlt_erst_nach_dem_senden(user: User, app_bereit):
    """Vorher gibt es nichts zu bestätigen – die Reihenfolge steht fest."""
    vormonat = m.offene()[-1]["periode"]
    await _anmelden(user)
    await user.should_not_see(marker=f"bezahlt-{vormonat}")

    m.gesendet(vormonat, "nutzer")
    await user.open("/")
    user.find(marker="nav-beherbergungssteuer").click()
    await user.should_see(marker=f"bezahlt-{vormonat}")


async def test_bezahlt_bestaetigen_traegt_den_namen_ein(user: User, app_bereit):
    vormonat = m.offene()[-1]["periode"]
    m.gesendet(vormonat, "nutzer")
    await _anmelden(user)
    user.find(marker=f"bezahlt-{vormonat}").click()
    assert m.status(vormonat) == m.BEZAHLT
    assert m.eintrag(vormonat)["bezahlt_von"] == "nutzer"
    # Die Bestätigung lädt die Seite neu – danach steht der Monat nicht mehr
    # in den offenen.
    await user.open("/")
    user.find(marker="nav-beherbergungssteuer").click()
    await user.should_not_see(marker=f"meldung-{vormonat}")


async def test_alles_erledigt_sagt_das_auch(user: User, app_bereit):
    for e in m.offene():
        m.bezahlt(e["periode"], "nutzer")
    await _anmelden(user)
    await user.should_see("Alles gemeldet und bezahlt.")


# ---------------------------------------------------------------- Startmonat
def test_frische_instanz_meldet_keine_alten_monate(monkeypatch):
    """Ohne Grenze stünden hier zwölf überfällige Monate für Zeiträume, die
    längst außerhalb der App erledigt wurden. Eine Liste, die beim ersten Blick
    komplett rot ist, liest danach niemand mehr."""
    monkeypatch.setitem(data.CONFIG, "meldungen_ab", "")
    monkeypatch.setattr(archive, "list_entries", lambda: [])
    assert m.startmonat(heute=date(2026, 8, 20)) == "2026-08"
    assert m.offene(heute=date(2026, 8, 20)) == []


def test_das_aelteste_archivdokument_setzt_die_grenze(monkeypatch):
    """Was im Archiv liegt, hat diese App erzeugt – ab dort ist sie zuständig."""
    monkeypatch.setitem(data.CONFIG, "meldungen_ab", "")
    monkeypatch.setattr(archive, "list_entries",
                        lambda: [{"period": "2026-06"}, {"period": "2026-05"}])
    assert m.startmonat() == "2026-05"
    perioden = [e["periode"] for e in m.offene(heute=date(2026, 8, 20))]
    assert perioden == ["2026-05", "2026-06", "2026-07"]


def test_die_einstellung_schlaegt_das_archiv(monkeypatch):
    monkeypatch.setitem(data.CONFIG, "meldungen_ab", "2026-07")
    monkeypatch.setattr(archive, "list_entries", lambda: [{"period": "2026-01"}])
    assert m.startmonat() == "2026-07"
    assert [e["periode"] for e in m.offene(heute=date(2026, 8, 20))] == ["2026-07"]


async def test_pruefung_steht_vor_den_knoepfen(user: User, app_bereit, monkeypatch):
    """Der Befund gehört zwischen Ergebnis und „Erzeugen": wer erst hinterher
    merkt, dass der Monat noch lief, muss eine Korrekturmeldung schicken."""
    heute = date.today()
    ergebnis = {"year": heute.year, "month": heute.month, "steuersatz": 0.06,
                "uebernachtungen_insgesamt": 4, "uebernachtungen_airbnb": 0,
                "uebernachtungen_airbnb_smoobu": 0, "uebernachtungen_verbleibend": 4,
                "umsatz_verbleibend": 400.0, "umsatz_steuerbefreit": 0.0,
                "umsatz_steuerpflichtig": 400.0, "beherbergungssteuer": 24.0,
                "rows": [], "remaining_rows": [], "airbnb_rows": []}
    monkeypatch.setattr(data, "compute", lambda *a, **k: ergebnis)
    monkeypatch.setattr(data, "LAST_BOOKINGS", [])

    await _anmelden(user)
    user.find("Berechnen").click()
    await user.should_see(marker="vollstaendigkeit")
    await user.should_see("Vor dem Erzeugen prüfen")
    # Der laufende Monat ist der Normalfall dieses Hinweises.
    await user.should_see("Der Monat läuft noch")
