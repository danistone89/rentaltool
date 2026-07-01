#!/usr/bin/env python3
"""E-Mail-Versand der Steueranmeldung über Gmail (SMTP).

Nur Standardbibliothek. Versendet das erzeugte PDF als Anhang an einen fest
konfigurierten Empfänger. Betreff und Text kommen aus konfigurierbaren Vorlagen
(config.email.betreff_vorlage / text_vorlage) mit Platzhaltern wie {monat},
{jahr}, {steuer}, {kassenzeichen}, {name}, {periode}.

Gmail: SMTP über smtp.gmail.com:587 (STARTTLS) mit einem **App-Passwort**
(nicht dem normalen Passwort; erfordert 2FA im Google-Konto). Das App-Passwort
wird in config.json gespeichert (gitignored) und nur vom Nutzer eingetragen.
"""
import smtplib
import ssl
from email.message import EmailMessage


class MailError(RuntimeError):
    pass


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"   # unbekannte Platzhalter sichtbar lassen


def render(template, context):
    return (template or "").format_map(_SafeDict(context))


def build_message(email_cfg, pdf_bytes, filename, context, *, subject=None, body=None):
    """EmailMessage mit gerendertem Betreff/Text und PDF-Anhang bauen."""
    to = (email_cfg.get("empfaenger") or "").strip()
    if not to:
        raise MailError("Kein Empfänger konfiguriert (Einstellungen → E-Mail).")
    absender = (email_cfg.get("absender") or "").strip()
    if not absender:
        raise MailError("Kein Absender (Gmail-Adresse) konfiguriert.")

    msg = EmailMessage()
    msg["From"] = absender
    msg["To"] = to
    if (email_cfg.get("cc") or "").strip():
        msg["Cc"] = email_cfg["cc"].strip()
    msg["Subject"] = subject if subject is not None else render(email_cfg.get("betreff_vorlage", ""), context)
    msg.set_content(body if body is not None else render(email_cfg.get("text_vorlage", ""), context))
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)
    return msg


def send(email_cfg, msg):
    """Nachricht über Gmail-SMTP versenden."""
    host = email_cfg.get("smtp_host") or "smtp.gmail.com"
    port = int(email_cfg.get("smtp_port") or 587)
    user = (email_cfg.get("absender") or "").strip()
    # Gmail zeigt App-Passwörter mit Leerzeichen ("abcd efgh ..."); beim Login
    # müssen die weg.
    pw = (email_cfg.get("app_password") or "").replace(" ", "")
    if not (user and pw):
        raise MailError("Gmail-Adresse oder App-Passwort fehlt (Einstellungen → E-Mail).")
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise MailError("Anmeldung bei Gmail fehlgeschlagen – App-Passwort prüfen "
                        "(nicht das normale Passwort; 2FA nötig).")
    except (smtplib.SMTPException, OSError) as ex:
        raise MailError(f"Versand fehlgeschlagen: {ex}")


def send_form(cfg, pdf_bytes, filename, context, *, subject=None, body=None):
    email_cfg = cfg.get("email", {})
    msg = build_message(email_cfg, pdf_bytes, filename, context, subject=subject, body=body)
    send(email_cfg, msg)
    return msg["To"]


def build_test_message(email_cfg):
    """Einfache Test-Nachricht ohne Anhang."""
    to = (email_cfg.get("empfaenger") or "").strip()
    absender = (email_cfg.get("absender") or "").strip()
    if not to:
        raise MailError("Kein Empfänger konfiguriert (Einstellungen → E-Mail).")
    if not absender:
        raise MailError("Kein Absender (Gmail-Adresse) konfiguriert.")
    msg = EmailMessage()
    msg["From"] = absender
    msg["To"] = to
    if (email_cfg.get("cc") or "").strip():
        msg["Cc"] = email_cfg["cc"].strip()
    msg["Subject"] = "Test – Beherbergungssteuer-App"
    msg.set_content("Dies ist eine Test-E-Mail der Beherbergungssteuer-App.\n"
                    "Wenn Sie diese Nachricht erhalten, funktioniert der Gmail-Versand.")
    return msg


def send_test(email_cfg):
    """Test-E-Mail an den konfigurierten Empfänger senden."""
    send(email_cfg, build_test_message(email_cfg))
    return (email_cfg.get("empfaenger") or "").strip()
