#!/usr/bin/env python3
"""Benutzerverwaltung von der Kommandozeile – für den Betreiber/Entwickler.

Für alles, was ohne laufende Oberfläche gehen muss: ausgesperrt, neues Konto
auf dem Server anlegen, 2FA eines Mitarbeiters entfernen, Zugangslink erzeugen,
wenn der Mailversand hakt. Arbeitet direkt auf `config.json`.

    python3 tools/useradmin.py liste
    python3 tools/useradmin.py passwort admin --email ich@example.com
    python3 tools/useradmin.py link admin
    python3 tools/useradmin.py rolle anna manager
    python3 tools/useradmin.py 2fa-aus admin
    python3 tools/useradmin.py loeschen anna

Auf dem Server (Dienst hält die Konfiguration im Speicher und würde sie beim
nächsten Speichern überschreiben) mit `--neustart` aufrufen:

    cd /opt/rentaltool
    .venv/bin/python tools/useradmin.py passwort admin --neustart

Ohne `--passwort` wird das Passwort verdeckt abgefragt – so landet es nicht in
der Shell-History.
"""
import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import auth  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(HERE, "config.json")
DEFAULT_URL = "https://app.ds-apartments.de"
ROLLEN = ("admin", "manager", "putzkraft")
DIENST = "rentaltool"


class Fehler(RuntimeError):
    pass


# ------------------------------------------------------------------ Konfig
def laden(pfad):
    if not os.path.exists(pfad):
        raise Fehler(f"{pfad} gibt es nicht.")
    with open(pfad, encoding="utf-8") as fh:
        return json.load(fh)


def speichern(cfg, pfad):
    """Erst sichern, dann atomar ersetzen – ein Abbruch darf die Konten nicht
    zerreißen."""
    if os.path.exists(pfad):
        shutil.copy2(pfad, f"{pfad}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, pfad)


def users_of(cfg):
    return cfg.setdefault("auth", {}).setdefault("users", {})


def hole(cfg, name):
    u = users_of(cfg).get(name)
    if u is None:
        raise Fehler(f"Benutzer '{name}' gibt es nicht. "
                     f"Vorhanden: {', '.join(sorted(users_of(cfg))) or '(keine)'}")
    return u


# ------------------------------------------------------------------ Befehle
def cmd_liste(cfg, args):
    users = users_of(cfg)
    if not users:
        return ["Keine Benutzer angelegt – beim ersten Aufruf der App wird ein "
                "Administrator eingerichtet."]
    zeilen = [f"{'Benutzer':<16} {'Rolle':<10} {'2FA':<5} {'Zugang':<12} E-Mail",
              "-" * 72]
    for name in sorted(users):
        u = users[name]
        zustand = auth.invite_state(u)
        if not u.get("password_hash"):
            zustand = "eingeladen" if zustand == "offen" else "kein Passwort"
        zeilen.append(f"{name:<16} {u.get('role', '?'):<10} "
                      f"{'ja' if u.get('totp_secret') else 'nein':<5} "
                      f"{zustand:<12} {u.get('email') or '-'}")
    return zeilen


def cmd_passwort(cfg, args):
    """Passwort setzen; legt das Konto an, wenn es es noch nicht gibt."""
    users = users_of(cfg)
    neu = args.benutzer not in users
    if neu and not args.rolle:
        raise Fehler(f"'{args.benutzer}' ist neu – bitte --rolle angeben "
                     f"({'/'.join(ROLLEN)}).")
    pw = args.passwort or getpass.getpass(f"Neues Passwort für {args.benutzer}: ")
    if len(pw) < 6:
        raise Fehler("Passwort zu kurz (mindestens 6 Zeichen).")
    u = users.setdefault(args.benutzer, {"name": args.benutzer, "totp_secret": ""})
    u["password_hash"] = auth.hash_password(pw)
    u.pop("invite", None)          # offener Einmal-Link wird ungültig
    if args.rolle:
        u["role"] = args.rolle
    u.setdefault("role", "putzkraft")
    if args.email:
        u["email"] = args.email
    u.setdefault("totp_secret", "")
    return [f"{'Angelegt' if neu else 'Passwort gesetzt'}: {args.benutzer} "
            f"(Rolle {u['role']}, E-Mail {u.get('email') or '-'})"]


def cmd_link(cfg, args):
    """Einmal-Link erzeugen und ausgeben – ohne E-Mail, für den Notfall."""
    u = hole(cfg, args.benutzer)
    token, rec = auth.new_invite("reset" if u.get("password_hash") else "einladung")
    u["invite"] = rec
    basis = (args.url or cfg.get("app_url") or DEFAULT_URL).rstrip("/")
    bis = time.strftime("%d.%m.%Y %H:%M", time.localtime(rec["expires"]))
    return [f"Zugangslink für {args.benutzer} (einmalig, gültig bis {bis}):",
            f"{basis}/invite?token={token}",
            "",
            "Der Link ersetzt einen zuvor erzeugten. Das bisherige Passwort bleibt "
            "gültig, bis der Link benutzt wird."]


def cmd_rolle(cfg, args):
    u = hole(cfg, args.benutzer)
    vorher = u.get("role", "?")
    u["role"] = args.rolle
    return [f"Rolle von {args.benutzer}: {vorher} -> {args.rolle}"]


def cmd_2fa_aus(cfg, args):
    u = hole(cfg, args.benutzer)
    if not u.get("totp_secret"):
        return [f"{args.benutzer} hat kein 2FA aktiv – nichts zu tun."]
    u["totp_secret"] = ""
    return [f"2FA für {args.benutzer} entfernt."]


def cmd_loeschen(cfg, args):
    hole(cfg, args.benutzer)
    users = users_of(cfg)
    if users[args.benutzer].get("role") == "admin" and \
            sum(1 for u in users.values() if u.get("role") == "admin") == 1:
        raise Fehler(f"'{args.benutzer}' ist der einzige Administrator – "
                     "erst einen zweiten anlegen.")
    users.pop(args.benutzer)
    return [f"{args.benutzer} gelöscht."]


BEFEHLE = {
    "liste": (cmd_liste, False),
    "passwort": (cmd_passwort, True),
    "link": (cmd_link, True),
    "rolle": (cmd_rolle, True),
    "2fa-aus": (cmd_2fa_aus, True),
    "loeschen": (cmd_loeschen, True),
}


# ------------------------------------------------------------------ CLI
def parser():
    p = argparse.ArgumentParser(
        description="Benutzer der Beherbergungssteuer-App verwalten "
                    "(arbeitet direkt auf config.json).")
    p.add_argument("--config", default=CONFIG, help="Pfad zur config.json")
    p.add_argument("--neustart", action="store_true",
                   help=f"danach 'systemctl restart {DIENST}' ausführen (Server)")
    sub = p.add_subparsers(dest="befehl", required=True)

    sub.add_parser("liste", help="Konten mit Rolle, 2FA, Zustand und E-Mail zeigen")

    sp = sub.add_parser("passwort", help="Passwort setzen (legt das Konto bei Bedarf an)")
    sp.add_argument("benutzer")
    sp.add_argument("--passwort", help="ohne Angabe: verdeckte Eingabe")
    sp.add_argument("--rolle", choices=ROLLEN, help="Pflicht bei neuen Konten")
    sp.add_argument("--email", help="für Benachrichtigungen und 'Passwort vergessen'")

    sp = sub.add_parser("link", help="Einmal-Link zum Passwortsetzen ausgeben (ohne Mail)")
    sp.add_argument("benutzer")
    sp.add_argument("--url", help=f"Basis-Adresse (sonst app_url, sonst {DEFAULT_URL})")

    sp = sub.add_parser("rolle", help="Rolle ändern")
    sp.add_argument("benutzer")
    sp.add_argument("rolle", choices=ROLLEN)

    sp = sub.add_parser("2fa-aus", help="2FA eines Kontos entfernen")
    sp.add_argument("benutzer")

    sp = sub.add_parser("loeschen", help="Konto löschen")
    sp.add_argument("benutzer")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    fn, schreibt = BEFEHLE[args.befehl]
    try:
        cfg = laden(args.config)
        ausgabe = fn(cfg, args)
        if schreibt:
            speichern(cfg, args.config)
    except Fehler as ex:
        print(f"Fehler: {ex}", file=sys.stderr)
        return 1
    print("\n".join(ausgabe))
    if schreibt and args.neustart:
        rc = subprocess.call(["systemctl", "restart", DIENST])
        print(f"Dienst {DIENST} neu gestartet." if rc == 0
              else f"Neustart von {DIENST} fehlgeschlagen (Code {rc}).")
    elif schreibt:
        print(f"\nHinweis: Läuft die App gerade, hat sie die alte Konfiguration im "
              f"Speicher. Erst nach 'systemctl restart {DIENST}' gilt die Änderung "
              f"– sonst überschreibt sie diese beim nächsten Speichern.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
