"""Tests für den E-Mail-Aufbau (ohne echten Versand)."""
import pytest

from app import mailer

EMAIL_CFG = {
    "absender": "betrieb@gmail.com",
    "app_password": "geheim",
    "empfaenger": "steueramt@dresden.de",
    "cc": "buchhaltung@example.com",
    "betreff_vorlage": "Beherbergungssteuer {monat} {jahr}",
    "text_vorlage": "Steuer {steuer} € für {monat} {jahr}, Kassenzeichen {kassenzeichen}.",
}
CTX = {"monat": "Dezember", "jahr": 2025, "periode": "2025-12",
       "steuer": "341,90", "kassenzeichen": "6419.64.002729", "name": "Muster"}


def test_render_platzhalter():
    assert mailer.render("Steuer {steuer} €", CTX) == "Steuer 341,90 €"
    # unbekannter Platzhalter bleibt sichtbar
    assert mailer.render("{foo}", CTX) == "{foo}"


def test_build_message():
    msg = mailer.build_message(EMAIL_CFG, b"%PDF-1.4 test", "anmeldung.pdf", CTX)
    assert msg["To"] == "steueramt@dresden.de"
    assert msg["From"] == "betrieb@gmail.com"
    assert msg["Cc"] == "buchhaltung@example.com"
    assert msg["Subject"] == "Beherbergungssteuer Dezember 2025"
    assert "341,90" in msg.get_body(preferencelist=("plain",)).get_content()
    atts = list(msg.iter_attachments())
    assert len(atts) == 1
    assert atts[0].get_filename() == "anmeldung.pdf"
    assert atts[0].get_content_type() == "application/pdf"


def test_build_message_ohne_empfaenger_fehler():
    cfg = dict(EMAIL_CFG, empfaenger="")
    with pytest.raises(mailer.MailError):
        mailer.build_message(cfg, b"x", "a.pdf", CTX)


def test_eigener_betreff_ueberschreibt_vorlage():
    msg = mailer.build_message(EMAIL_CFG, b"x", "a.pdf", CTX,
                               subject="Individuell", body="Kurztext")
    assert msg["Subject"] == "Individuell"
    assert msg.get_body(preferencelist=("plain",)).get_content().strip() == "Kurztext"
