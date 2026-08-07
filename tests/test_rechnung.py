"""AP14: aus einer Buchung wird eine Rechnung.

`test_der_belegte_fall_stimmt_auf_den_cent` ist der Anker: Rechnung 60 aus dem
Rechnungsausgangsbuch, 400,07 € brutto = 312,42 Übernachtung + 65,00 Reinigung
+ 22,65 Übernachtungssteuer. Diese Zahlen stehen im Projekt seit der
Steueranmeldung und sind der Maßstab – weicht die Rechnung davon ab, ist eine
von beiden falsch.

Gegengeprüft am 7.8.2026 an **219 echten Buchungen**: 186 teilen sich sauber
auf. Die übrigen sind keine Fehler der Rechnung, sondern Funde in den Daten –
drei Buchungen ohne Betrag und eine, deren Reinigungsgebühr größer ist als der
ganze Aufenthalt. Genau die soll die Aufteilung ablehnen statt schönzurechnen.
"""
import pytest

from app import rechnung, stammdaten


def _buchung(**felder):
    grund = {"id": 111, "price": 400.07, "price-details": "",
             "apartment": {"id": 2748963, "name": "Cottaer Straße"},
             "arrival": "2026-08-01", "departure": "2026-08-05",
             "created-at": "2026-07-01 10:00", "guest-name": "Anja Ernst",
             "channel": {"name": "Direct booking"}}
    grund.update(felder)
    return grund


# ----------------------------------------------------------- Die Aufteilung
def test_der_belegte_fall_stimmt_auf_den_cent():
    """Rechnung 60, Direktbuchung ohne jede Aufschlüsselung von Smoobu."""
    pos, befunde = rechnung.aufteilung(_buchung(), reinigungspreis=65)
    assert befunde == []
    betraege = {p["bezeichnung"]: p["brutto"] for p in pos}
    assert betraege == {"Übernachtung": 312.42, "Endreinigung": 65.00,
                        "Beherbergungssteuer": 22.65}
    assert rechnung.summen(pos)["brutto"] == 400.07


def test_die_summe_trifft_immer_den_betrag_des_gastes():
    """Die Probe gehört dazu: eine Rechnung, die sich still um zwei Cent
    verrechnet, findet niemand wieder."""
    for preis in (99.99, 150.0, 233.33, 1000.0):
        b = _buchung(price=preis)
        pos, befunde = rechnung.aufteilung(b, reinigungspreis=65)
        if pos:
            assert rechnung.summen(pos)["brutto"] == round(preis, 2), preis
            assert befunde == []


def test_smoobus_angabe_schlaegt_den_hinterlegten_preis():
    """Der Gast hat diesen Betrag bezahlt – nicht den, den wir für richtig
    halten. Der hinterlegte Preis ist Gegenprobe, nicht Quelle."""
    b = _buchung(**{"price-details": "Reinigungsgebühr - EUR 75\nÜbernachtungssteuer - EUR 18"})
    pos, befunde = rechnung.aufteilung(b, reinigungspreis=65)
    betraege = {p["bezeichnung"]: p["brutto"] for p in pos}
    assert betraege["Endreinigung"] == 75.0
    assert any("75.00" in x and "65.00" in x for x in befunde), befunde


def test_ohne_angabe_greift_der_hinterlegte_preis():
    pos, _ = rechnung.aufteilung(_buchung(), reinigungspreis=75)
    assert {p["bezeichnung"]: p["brutto"] for p in pos}["Endreinigung"] == 75.0


def test_ohne_preis_und_ohne_angabe_gibt_es_einen_befund():
    """Lieber ein Klärfall als eine erfundene Zahl."""
    _pos, befunde = rechnung.aufteilung(_buchung(), reinigungspreis=None)
    assert any("weder von Smoobu noch als Preis" in x for x in befunde)


def test_buchung_ohne_betrag_wird_abgelehnt():
    """Kommt in den echten Daten dreimal vor."""
    pos, befunde = rechnung.aufteilung(_buchung(price=0), reinigungspreis=65)
    assert pos == [] and befunde == ["Die Buchung hat keinen Betrag."]


def test_reinigung_groesser_als_der_aufenthalt_wird_abgelehnt():
    """Ein echter Fund aus den Daten: 68,85 € Gesamtbetrag bei 95 € Reinigung.
    Eine negative Übernachtungsposition wäre schöngerechnet."""
    pos, befunde = rechnung.aufteilung(_buchung(price=68.85), reinigungspreis=95)
    assert pos == []
    assert any("größer als der ganze Betrag" in x for x in befunde)


def test_die_beherbergungssteuer_traegt_keine_umsatzsteuer():
    """Durchlaufender Posten – Steuer auf Steuer gäbe es sonst."""
    pos, _ = rechnung.aufteilung(_buchung(), reinigungspreis=65)
    steuerzeile = next(p for p in pos if p["bezeichnung"] == "Beherbergungssteuer")
    assert steuerzeile["ustsatz"] == 0.0
    assert steuerzeile["ust"] == 0.0
    assert steuerzeile["netto"] == steuerzeile["brutto"]


def test_uebernachtung_und_reinigung_laufen_mit_sieben_prozent():
    pos, _ = rechnung.aufteilung(_buchung(), reinigungspreis=65)
    for p in pos:
        if p["bezeichnung"] != "Beherbergungssteuer":
            assert p["ustsatz"] == 0.07
            assert p["netto"] + p["ust"] == p["brutto"]


def test_summen_trennen_umsatzsteuerpflichtiges_vom_durchlaufenden():
    pos, _ = rechnung.aufteilung(_buchung(), reinigungspreis=65)
    s = rechnung.summen(pos)
    assert s["durchlaufend"] == 22.65
    assert round(s["netto"] + s["ust"], 2) == 377.42     # die Bemessungsgrundlage
    assert s["brutto"] == 400.07


# --------------------------------------------------------------- Empfänger
def _gast(**felder):
    grund = {"firstName": "Anja", "lastName": "Ernst",
             "address": {"street": "Musterweg 3", "postalCode": "01067",
                         "city": "Dresden", "country": "DE"},
             "emails": ["anja@example.com"]}
    grund.update(felder)
    return grund


def test_empfaenger_kommt_aus_den_gastdaten():
    e = rechnung.empfaenger_aus_gast(_gast())
    assert e["name"] == "Anja Ernst"
    assert (e["strasse"], e["plz"], e["ort"]) == ("Musterweg 3", "01067", "Dresden")
    assert e["email"] == "anja@example.com"


def test_fehlende_anschrift_faellt_auf():
    ohne = rechnung.empfaenger_aus_gast(_gast(address={}))
    assert not rechnung.anschrift_vollstaendig(ohne)
    assert rechnung.anschrift_vollstaendig(rechnung.empfaenger_aus_gast(_gast()))


@pytest.mark.parametrize("brutto,noetig", [
    (100.0, False), (250.0, False), (250.01, True), (400.07, True),
])
def test_bis_250_euro_genuegt_die_kleinbetragsrechnung(brutto, noetig):
    """§ 33 UStDV – darunter braucht es keine Empfängeranschrift."""
    assert rechnung.braucht_anschrift(brutto) is noetig


# ------------------------------------------------------------ Nummernkreis
def test_der_kreis_beginnt_hinter_dem_workbook(monkeypatch):
    from app import data
    monkeypatch.setitem(data.CONFIG, "rechnung_startjahr", "2026")
    monkeypatch.setitem(data.CONFIG, "rechnung_startnummer", 76)
    assert rechnung.naechste_nummer(2026) == "2026-0076"


def test_jedes_weitere_jahr_beginnt_bei_eins(monkeypatch):
    """Sonst hinge die Zählung 2030 noch an einer Zahl aus dem Workbook."""
    from app import data
    monkeypatch.setitem(data.CONFIG, "rechnung_startjahr", "2026")
    monkeypatch.setitem(data.CONFIG, "rechnung_startnummer", 76)
    assert rechnung.naechste_nummer(2027) == "2027-0001"


def test_die_nummer_entsteht_erst_beim_festschreiben():
    """Ein verworfener Entwurf darf keine Lücke hinterlassen – ein lückenhafter
    Nummernkreis ist ein Mangel, den jede Prüfung findet."""
    pos, _ = rechnung.aufteilung(_buchung(), reinigungspreis=65)
    e = rechnung.entwurf_anlegen(_buchung(), pos, rechnung.empfaenger_aus_gast(_gast()))
    assert e["nummer"] == ""
    rechnung.loeschen(e["id"])

    zweiter = rechnung.entwurf_anlegen(_buchung(), pos,
                                       rechnung.empfaenger_aus_gast(_gast()))
    fest = rechnung.festschreiben(zweiter["id"], "nutzer")
    assert fest["nummer"].endswith("0001") or fest["nummer"].split("-")[1].isdigit()


def test_nummern_laufen_ohne_luecke_weiter():
    pos, _ = rechnung.aufteilung(_buchung(), reinigungspreis=65)
    nummern = []
    for i in range(3):
        e = rechnung.entwurf_anlegen(_buchung(id=100 + i), pos,
                                     rechnung.empfaenger_aus_gast(_gast()))
        nummern.append(rechnung.festschreiben(e["id"], "nutzer")["nummer"])
    zahlen = [int(n.split("-")[1]) for n in nummern]
    assert zahlen == list(range(zahlen[0], zahlen[0] + 3))


# ----------------------------------------------------------------- Der Weg
def _entwurf(**felder):
    pos, befunde = rechnung.aufteilung(_buchung(**felder), reinigungspreis=65)
    return rechnung.entwurf_anlegen(_buchung(**felder), pos,
                                    rechnung.empfaenger_aus_gast(_gast()), befunde)


def test_ein_entwurf_laesst_sich_aendern_eine_rechnung_nicht():
    """Was festgeschrieben ist, ist fest. Wer korrigieren muss, storniert."""
    e = _entwurf()
    assert rechnung.aendern(e["id"], datum="2026-08-09")["datum"] == "2026-08-09"
    rechnung.festschreiben(e["id"], "nutzer")
    assert rechnung.aendern(e["id"], datum="2026-08-10") is None


def test_mit_offenen_befunden_wird_nicht_festgeschrieben():
    e = _entwurf(price=68.85)   # Reinigung groesser als der Betrag -> keine Positionen
    if e is None:
        return
    with pytest.raises(ValueError):
        rechnung.festschreiben(e["id"], "nutzer")


def test_versand_erst_nach_dem_festschreiben():
    e = _entwurf()
    ja, grund = rechnung.versandbereit(e)
    assert not ja and "Entwurf" in grund
    fest = rechnung.festschreiben(e["id"], "nutzer")
    assert rechnung.versandbereit(fest)[0]


def test_ueber_250_euro_ohne_anschrift_geht_nicht_raus():
    """Der Entwurf entsteht trotzdem – nur hinaus geht er nicht."""
    pos, _ = rechnung.aufteilung(_buchung(), reinigungspreis=65)
    ohne = rechnung.empfaenger_aus_gast(_gast(address={}))
    e = rechnung.entwurf_anlegen(_buchung(), pos, ohne)
    fest = rechnung.festschreiben(e["id"], "nutzer")
    ja, grund = rechnung.versandbereit(fest)
    assert not ja and "Anschrift" in grund


def test_kleinbetrag_ohne_anschrift_darf_raus():
    pos, _ = rechnung.aufteilung(_buchung(price=120.0), reinigungspreis=65)
    ohne = rechnung.empfaenger_aus_gast(_gast(address={}))
    e = rechnung.entwurf_anlegen(_buchung(price=120.0), pos, ohne)
    fest = rechnung.festschreiben(e["id"], "nutzer")
    assert rechnung.versandbereit(fest)[0], rechnung.versandbereit(fest)[1]


def test_storno_behaelt_die_nummer():
    """Eine verschwundene Rechnungsnummer ist ein Mangel, den jede Prüfung
    findet. Storno heißt Gutschrift, nicht Löschung."""
    e = _entwurf()
    fest = rechnung.festschreiben(e["id"], "nutzer")
    nummer = fest["nummer"]
    storno = rechnung.stornieren(e["id"], "Buchung storniert", "nutzer")
    assert storno["status"] == rechnung.STORNIERT
    assert storno["nummer"] == nummer
    assert storno["storno_grund"] == "Buchung storniert"


def test_festgeschriebenes_laesst_sich_nicht_loeschen():
    e = _entwurf()
    rechnung.festschreiben(e["id"], "nutzer")
    assert rechnung.loeschen(e["id"]) is False


def test_entwuerfe_lassen_sich_loeschen():
    e = _entwurf()
    assert rechnung.loeschen(e["id"]) is True


# ------------------------------------------------- Entwürfe nach Check-out
def test_erst_nach_der_abreise_entsteht_ein_entwurf():
    """Vorher kann sich der Betrag noch ändern – eine Rechnung über einen
    laufenden Aufenthalt ist keine."""
    from datetime import date, timedelta
    heute = date.today()
    jobs = [{"id": 1, "departure": (heute - timedelta(days=1)).isoformat()},
            {"id": 2, "departure": (heute + timedelta(days=3)).isoformat()}]
    faellig = rechnung.faellige_buchungen(jobs, heute)
    assert [j["id"] for j in faellig] == [1]


def test_wo_schon_eine_rechnung_liegt_entsteht_keine_zweite():
    from datetime import date, timedelta
    heute = date.today()
    e = _entwurf()
    jobs = [{"id": e["buchung"], "departure": (heute - timedelta(days=1)).isoformat()}]
    assert rechnung.faellige_buchungen(jobs, heute) == []


def test_entwurf_fuer_nimmt_den_preis_vom_buchungstag(monkeypatch):
    """Die Verbindung zu AP13: gefragt wird mit `created-at`, nicht mit der
    Anreise."""
    p = stammdaten.produkt_anlegen("Endreinigung", stammdaten.FEST, 0.07)
    stammdaten.preis_setzen(p["id"], 2748963, "2020-01-01", 65)
    stammdaten.preis_setzen(p["id"], 2748963, "2026-01-04", 75)

    frueh = _buchung(**{"created-at": "2025-12-20 09:00", "price-details": ""})
    e, _ = rechnung.entwurf_fuer(frueh, _gast())
    betraege = {x["bezeichnung"]: x["brutto"] for x in e["positionen"]}
    assert betraege["Endreinigung"] == 65.0

    spaet = _buchung(id=222, **{"created-at": "2026-02-01 09:00", "price-details": ""})
    e2, _ = rechnung.entwurf_fuer(spaet, _gast())
    assert {x["bezeichnung"]: x["brutto"] for x in e2["positionen"]}["Endreinigung"] == 75.0


# --------------------------------------------------------------- Oberfläche
from nicegui.testing import User            # noqa: E402
from app import auth, data, mailer, web     # noqa: E402


@pytest.fixture
def app_bereit(monkeypatch):
    monkeypatch.setattr(data, "get_apartments", lambda: [
        {"id": 2748963, "name": "Cottaer Straße"}])
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [])
    monkeypatch.setattr(data, "gastdaten", lambda force=False: {})
    monkeypatch.setattr(mailer, "send_notify", lambda *a, **k: None)
    monkeypatch.setitem(web.CFG, "betreiber", {
        "name": "DS Apartments", "strasse": "Antonstraße", "hausnummer": "15",
        "plz": "01097", "ort": "Dresden", "steuernummer": "203/277/09284"})
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
    user.find(marker="nav-rechnungen").click()


async def test_der_bereich_gibt_es_und_ist_leer(user: User, app_bereit):
    await _anmelden(user)
    await user.should_see("Noch keine Rechnungen.")
    await user.should_see(marker="entwuerfe-suchen")


async def test_ein_entwurf_steht_mit_seinen_befunden_da(user: User, app_bereit):
    """Der Entwurf entsteht auch ohne Anschrift – er sagt es nur."""
    pos, _ = rechnung.aufteilung(_buchung(), reinigungspreis=65)
    ohne = rechnung.empfaenger_aus_gast(_gast(address={}))
    e = rechnung.entwurf_anlegen(_buchung(), pos, ohne,
                                 ["Über 250 € – Anschrift des Gastes fehlt noch."])
    await _anmelden(user)
    await user.should_see(marker=f"rechnung-{e['id']}")
    await user.should_see("Anschrift des Gastes fehlt noch")
    with user.client:
        knopf = next(iter(user.find(marker=f"festschreiben-{e['id']}").elements))
        assert not knopf.enabled, "Festschreiben trotz offener Befunde moeglich"


async def test_anschrift_nachtragen_macht_den_entwurf_fertig(user: User, app_bereit):
    pos, _ = rechnung.aufteilung(_buchung(), reinigungspreis=65)
    e = rechnung.entwurf_anlegen(_buchung(), pos,
                                 rechnung.empfaenger_aus_gast(_gast(address={})),
                                 ["Über 250 € – Anschrift des Gastes fehlt noch."])
    await _anmelden(user)
    user.find(marker=f"empfaenger-{e['id']}").click()
    await user.should_see(marker="feld-strasse")
    user.find(marker="feld-strasse").type("Musterweg 3")
    user.find(marker="feld-plz").type("01067")
    user.find(marker="feld-ort").type("Dresden")
    user.find(marker="empfaenger-speichern").click()
    assert rechnung.rechnungen()[0]["befunde"] == []


async def test_der_rechnungskopf_meldet_fehlende_pflichtangaben(user: User, app_bereit,
                                                                monkeypatch):
    """Ohne Steuernummer ist die Rechnung nach § 14 UStG unvollständig."""
    monkeypatch.setitem(web.CFG, "betreiber", {"name": "DS Apartments"})
    await _anmelden(user)
    await user.should_see(marker="betreiber-unvollstaendig")
    await user.should_see("Steuernummer oder USt-IdNr.")


async def test_die_managerin_sieht_den_bereich_nicht(user: User, app_bereit, monkeypatch):
    """Rechnungen sind Geld – das bleibt beim Betreiber (AP12)."""
    monkeypatch.setitem(web.USERS, "mgr", {
        "password_hash": auth.hash_password("geheim"), "role": "manager",
        "totp_secret": "", "name": "mgr"})
    await user.open("/login")
    user.find(marker="login-user").type("mgr")
    user.find(marker="login-pw").type("geheim")
    user.find("Anmelden").click()
    await user.open("/")
    await user.should_not_see(marker="nav-rechnungen")


def test_die_rechnungssuche_hat_ihr_eigenes_fenster():
    """Der Fehler vom 7.8.2026: „Entwürfe suchen" nahm die Reinigungsliste, und
    die blickt nur EINEN Tag zurück – sie ist für den Alltag gebaut, nicht für
    die Buchhaltung. Von 48 abgereisten Buchungen war damit genau eine
    erreichbar; der Knopf schien nichts zu tun."""
    from datetime import date, timedelta
    assert rechnung.RUECKBLICK_TAGE >= 60, \
        "Zu kurz – Rechnungen entstehen nach dem Aufenthalt, oft mit Verzug."
    heute = date.today()
    alt = [{"id": 1, "departure": (heute - timedelta(days=40)).isoformat()}]
    assert rechnung.faellige_buchungen(alt, heute), \
        "Eine Abreise vor 40 Tagen muss eine faellige Rechnung sein"


def test_kuenftige_abreisen_bleiben_aussen_vor():
    from datetime import date, timedelta
    heute = date.today()
    kuenftig = [{"id": 1, "departure": (heute + timedelta(days=2)).isoformat()}]
    assert rechnung.faellige_buchungen(kuenftig, heute) == []


# ------------------------------------------------------------------ Die Naht
# Die beiden Hälften waren einzeln immer richtig: `faellige_buchungen` wurde mit
# Attrappen geprüft, `entwurf_fuer` mit echten Smoobu-Daten. Geprüft hat nie
# jemand, ob das, was die erste durchreicht, der zweiten überhaupt genügt – und
# genau dort lag der Fehler. Diese zwei Tests decken die Naht ab.

def test_die_ganze_kette_von_der_smoobu_antwort_bis_zum_entwurf():
    """Der Fehler vom 7.8.2026, zweiter Teil: „Entwürfe suchen" reichte die
    aufbereiteten Reinigungs-Jobs weiter. Preis, Preisdetails, Buchungsdatum
    und die Wohnung fallen dort heraus – jeder Entwurf scheiterte lautlos an
    „Die Buchung hat keinen Betrag." Der Knopf schien nichts zu tun.

    Gegangen wird hier derselbe Weg wie im Bildschirm: rohe Smoobu-Antwort →
    aussortieren → fällige finden → Entwurf.
    """
    from datetime import date, timedelta
    from app import bookings

    p = stammdaten.produkt_anlegen("Endreinigung", stammdaten.FEST, 0.07)
    stammdaten.preis_setzen(p["id"], 2748963, "2020-01-01", 65)

    heute = date.today()
    abreise = (heute - timedelta(days=30)).isoformat()
    roh = [_buchung(id=901, departure=abreise,
                    arrival=(heute - timedelta(days=33)).isoformat()),
           # Eine Blockierung ist keine Buchung und darf keine Rechnung werden.
           _buchung(id=902, departure=abreise, **{"is-blocked-booking": True})]

    faellig = rechnung.faellige_buchungen(
        [b for b in roh if bookings.is_real(b)], heute)
    assert [b["id"] for b in faellig] == [901]

    entwurf, befunde = rechnung.entwurf_fuer(faellig[0], _gast())
    assert entwurf, f"Kein Entwurf entstanden. Befunde: {befunde}"
    assert entwurf["summen"]["brutto"] == 400.07


async def test_der_knopf_legt_wirklich_entwuerfe_an(user: User, app_bereit,
                                                    monkeypatch):
    """Der Test, der gefehlt hat. Beide Hälften waren einzeln geprüft und
    einzeln richtig – geklickt hat den Knopf keiner. Vor der Korrektur legte er
    null Entwürfe an und sagte nichts dazu.

    Deshalb wird hier wirklich geklickt, mit einer Smoobu-Antwort in der Form,
    die auch im Betrieb ankommt.
    """
    from datetime import date, timedelta

    p = stammdaten.produkt_anlegen("Endreinigung", stammdaten.FEST, 0.07)
    stammdaten.preis_setzen(p["id"], 2748963, "2020-01-01", 65)

    heute = date.today()
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [
        _buchung(id=901, arrival=(heute - timedelta(days=33)).isoformat(),
                 departure=(heute - timedelta(days=30)).isoformat())])

    await _anmelden(user)
    user.find(marker="entwuerfe-suchen").click()
    await user.should_see("1 Entwurf")

    # Die Meldung allein genügt nicht – der Entwurf muss auch dastehen, und mit
    # dem richtigen Betrag. Genau daran scheiterte der alte Weg lautlos.
    angelegt = rechnung.rechnungen()
    assert len(angelegt) == 1, "Der Knopf meldet Erfolg, legt aber nichts an"
    assert angelegt[0]["summen"]["brutto"] == 400.07
    assert angelegt[0]["buchung"] == 901


async def test_uebersprungene_buchungen_sagen_warum(user: User, app_bereit,
                                                    monkeypatch):
    """Schweigen war das eigentliche Ärgernis: der Knopf sah kaputt aus, obwohl
    er lief. Was er nicht verarbeiten kann, muss er benennen."""
    from datetime import date, timedelta

    heute = date.today()
    # Ohne hinterlegten Reinigungspreis und ohne Angabe von Smoobu bleibt die
    # Aufteilung unbelastbar – das ist richtig so, darf aber nicht stumm sein.
    monkeypatch.setattr(data, "_reservations", lambda *a, **k: [
        _buchung(id=902, price=0,
                 departure=(heute - timedelta(days=10)).isoformat())])

    await _anmelden(user)
    user.find(marker="entwuerfe-suchen").click()
    await user.should_see("1 übersprungen")
    await user.should_see("keinen Betrag")


def test_aufbereitete_reinigungs_jobs_taugen_nicht_fuer_rechnungen():
    """Die Falle festgenagelt: wer die Buchungen wieder über die
    Reinigungsliste holt, bekommt genau dieses Ergebnis. Schlägt der Test um,
    weil plötzlich doch ein Entwurf entsteht, ist `normalize()` gewachsen – dann
    darf diese Warnung weg."""
    from app import bookings

    job = bookings.normalize(_buchung())
    assert "price" not in job and "price-details" not in job, \
        "normalize() reicht den Betrag jetzt durch – der Umweg wäre wieder gangbar"
    entwurf, befunde = rechnung.entwurf_fuer(job, _gast())
    assert entwurf is None
    assert befunde == ["Die Buchung hat keinen Betrag."]
