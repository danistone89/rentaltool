#!/usr/bin/env python3
"""Kalender-Datei (.ics) für einen Reinigungsauftrag.

Damit trägt sich die Putzkraft den Einsatz in ihren eigenen Kalender ein.
Reine Standardbibliothek – iCalendar ist Text (RFC 5545).

Zeitfenster: von der Abreise (Check-out) bis zur nächsten Anreise (Check-in).
Gibt es keine Folgebuchung oder liegt die Anreise nicht danach, werden zwei
Stunden angesetzt.

Zeitzone: Die Termine tragen `TZID=Europe/Berlin` samt VTIMEZONE-Block, damit
Google/Apple/Outlook die Sommerzeit korrekt umrechnen. Ohne den Block würden
Kalender die Zeit als "schwebend" ansehen und bei Reisenden verschieben.
"""
from datetime import date, datetime, timedelta

PRODID = "-//LIVARO Suites//Reinigungsplan//DE"
TZID = "Europe/Berlin"

# Minimaler, aber vollständiger VTIMEZONE-Block für Mitteleuropa.
_VTIMEZONE = f"""BEGIN:VTIMEZONE
TZID:{TZID}
X-LIC-LOCATION:{TZID}
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""


def _esc(text):
    """Text für ein iCal-Feld entschärfen (RFC 5545 §3.3.11)."""
    return (str(text or "")
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n"))


def _fold(zeile):
    """Zeilen auf 75 Oktette umbrechen, Folgezeilen mit einem Leerzeichen."""
    roh = zeile.encode("utf-8")
    if len(roh) <= 75:
        return zeile
    teile, rest = [], roh
    teile.append(rest[:75])
    rest = rest[75:]
    while rest:
        teile.append(rest[:74])
        rest = rest[74:]
    # An UTF-8-Grenzen ausrichten: notfalls ein Byte zurücknehmen
    out, puffer = [], b""
    for i, teil in enumerate(teile):
        puffer += teil
        while True:
            try:
                puffer.decode("utf-8")
                break
            except UnicodeDecodeError:
                teile[i + 1] = puffer[-1:] + teile[i + 1]
                puffer = puffer[:-1]
        out.append(puffer.decode("utf-8"))
        puffer = b""
    return out[0] + "".join("\r\n " + s for s in out[1:])


def _zeit(d, hhmm):
    """('2026-08-05', '10:00') -> datetime. Ungültige Zeit -> None."""
    try:
        h, m = (int(x) for x in str(hhmm).split(":")[:2])
        return datetime.combine(date.fromisoformat(d), datetime.min.time()).replace(
            hour=h, minute=m)
    except Exception:
        return None


def zeitfenster(job, standard_dauer_min=120):
    """(start, ende) des Reinigungsfensters als datetime."""
    start = _zeit(job.get("departure"), job.get("checkout_time")) \
        or _zeit(job.get("departure"), "10:00")
    nxt = job.get("next") or {}
    ende = None
    if nxt.get("arrival") == job.get("departure"):
        ende = _zeit(nxt.get("arrival"), nxt.get("checkin_time"))
    if ende is None or ende <= start:
        ende = start + timedelta(minutes=standard_dauer_min)
    return start, ende


def _stamp(dt):
    return dt.strftime("%Y%m%dT%H%M%S")


def _personen(nb):
    if not nb:
        return 0
    return (nb.get("adults") or 0) + (nb.get("children") or 0) or (nb.get("persons") or 0)


def cleaning_event(job, erinnerung_min=60, jetzt=None):
    """Eine .ics-Datei (bytes) für einen Reinigungsauftrag.

    `jetzt` nur für Tests – sonst der aktuelle Zeitpunkt für DTSTAMP.
    """
    start, ende = zeitfenster(job)
    nxt = job.get("next") or None
    wohnung = job.get("apartment_name") or "Reinigung"

    beschreibung = [f"Check-out {job.get('checkout_time') or '—'}"]
    if nxt:
        n = _personen(nxt)
        beschreibung.append(
            f"Vorbereiten für {n} " + ("Person" if n == 1 else "Personen"))
        beschreibung.append(f"Anreise {nxt.get('arrival')} um "
                            f"{nxt.get('checkin_time') or '—'}")
        if nxt.get("guest"):
            beschreibung.append(f"Gast: {nxt['guest']}")
    else:
        beschreibung.append("Keine Folgebuchung – nur reinigen.")

    wechseltag = bool(nxt and nxt.get("arrival") == job.get("departure"))
    titel = f"Reinigung {wohnung}" + (" (Wechseltag)" if wechseltag else "")

    zeilen = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        *_VTIMEZONE.split("\n"),
        "BEGIN:VEVENT",
        f"UID:reinigung-{job.get('id')}@livaro-suites",
        f"DTSTAMP:{_stamp(jetzt or datetime.now())}",
        f"DTSTART;TZID={TZID}:{_stamp(start)}",
        f"DTEND;TZID={TZID}:{_stamp(ende)}",
        f"SUMMARY:{_esc(titel)}",
        f"LOCATION:{_esc(wohnung)}",
        f"DESCRIPTION:{_esc(chr(10).join(beschreibung))}",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
    ]
    if erinnerung_min:
        zeilen += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_esc(titel)}",
            f"TRIGGER:-PT{int(erinnerung_min)}M",
            "END:VALARM",
        ]
    zeilen += ["END:VEVENT", "END:VCALENDAR"]
    return ("\r\n".join(_fold(z) for z in zeilen) + "\r\n").encode("utf-8")


def dateiname(job):
    """Sprechender Dateiname, ohne Sonderzeichen."""
    wohnung = "".join(c if c.isalnum() else "_"
                      for c in (job.get("apartment_name") or "Reinigung"))
    return f"Reinigung_{wohnung}_{job.get('departure', '')}.ics"
