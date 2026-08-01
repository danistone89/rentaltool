#!/usr/bin/env python3
"""Mehrsprachige Oberfläche (Deutsch / Englisch).

Übersetzt sind die **Mitarbeiterbereiche** – Login, Mein Konto, Buchungen,
Reinigungs-Checklisten, Belege und Zeiterfassung. Der Verwaltungsteil
(Beherbergungssteuer, Auswertung, Einstellungen, Benutzerverwaltung) bleibt
bewusst deutsch: Steuerbegriffe wie „Beherbergungssteuer" oder „Buß- und
Bettag" haben keine belastbare englische Entsprechung, und diese Bereiche
bedient nur der Betreiber.

Der **deutsche Text ist zugleich der Schlüssel**. Fehlt eine Übersetzung,
kommt unverändert das Deutsche zurück – eine Lücke kann die Oberfläche also
nie leeren oder zerstören.

    t("Anmelden")                 -> "Sign in"   (en)  /  "Anmelden" (de)
    t("{n} von {m}", n=1, m=3)    -> "1 of 3"    (en)

Inhalte aus den Datendateien (Checklisten-Punkte, Wohnungsnamen, Notizen,
Inventar) werden NICHT übersetzt – sie erscheinen so, wie sie angelegt wurden.
"""

DEFAULT = "de"
LANGUAGES = {"de": "Deutsch", "en": "English"}

# de -> en. Schlüssel ist exakt der deutsche Quelltext.
_EN = {
    # ---------------------------------------------------------------- Login
    "Anmelden": "Sign in",
    "Benutzername": "Username",
    "Passwort": "Password",
    "Passwort wiederholen": "Repeat password",
    "Neues Passwort": "New password",
    "6-stelliger Code (falls 2FA aktiv)": "6-digit code (if 2FA is enabled)",
    "Benutzername oder Passwort falsch.": "Incorrect username or password.",
    "Code fehlt oder ist falsch.": "Code missing or incorrect.",
    "Benutzername fehlt.": "Username is missing.",
    "Passwort mindestens 6 Zeichen.": "Password must be at least 6 characters.",
    "Passwörter stimmen nicht überein.": "Passwords do not match.",
    "Erst-Einrichtung – Administrator anlegen": "Initial setup – create administrator",
    "Anlegen & anmelden": "Create & sign in",
    "Sprache": "Language",
    "Dein Zugang ist noch nicht aktiviert – bitte den Link aus der Einladungs-E-Mail benutzen.":
        "Your account is not activated yet – please use the link from the invitation email.",

    "Passwort vergessen?": "Forgot your password?",
    "Passwort zurücksetzen": "Reset password",
    "Wir schicken dir einen Link, mit dem du dir ein neues Passwort setzt.":
        "We will send you a link to choose a new password.",
    "Benutzername oder E-Mail": "Username or email",
    "Link anfordern": "Request link",
    "Wenn es dazu ein Konto mit E-Mail-Adresse gibt, ist gleich eine E-Mail mit "
    "einem Link unterwegs.":
        "If there is an account with an email address for this, a message with a "
        "link is on its way.",

    # ------------------------------------------------- Einladung / Zugang
    "Zugang einrichten": "Set up your access",
    "Neues Passwort vergeben": "Choose a new password",
    "Vergib hier dein Passwort – danach bist du direkt angemeldet.":
        "Choose your password here – you will be signed in right away.",
    "Konto: {benutzer}": "Account: {benutzer}",
    "Passwort speichern & anmelden": "Save password & sign in",
    "Link ungültig oder abgelaufen.": "Link invalid or expired.",
    "Bitte fordere bei deinem Administrator eine neue Einladung an.":
        "Please ask your administrator for a new invitation.",
    "Zur Anmeldung": "Go to sign-in",
    "Passwort gesetzt – willkommen!": "Password set – welcome!",
    # … Text der Einladungs-E-Mail
    "Dein Zugang zur LIVARO-App": "Your access to the LIVARO app",
    "Neues Passwort für die LIVARO-App": "New password for the LIVARO app",
    "Hallo {name},": "Hello {name},",
    "für dich wurde ein Zugang zur LIVARO-App angelegt.":
        "an account has been created for you in the LIVARO app.",
    "für deinen Zugang zur LIVARO-App wurde ein neues Passwort angefordert.":
        "a new password has been requested for your LIVARO app account.",
    "Dein Benutzername: {benutzer}": "Your username: {benutzer}",
    "Über diesen Link vergibst du dein Passwort (nur einmal verwendbar):":
        "Use this link to choose your password (can only be used once):",
    "Der Link ist bis zum {datum} gültig.": "The link is valid until {datum}.",
    "Danach meldest du dich jederzeit unter {url} mit deinem Benutzernamen und "
    "deinem Passwort an.":
        "After that you can sign in any time at {url} with your username and "
        "your password.",
    "Viele Grüße": "Best regards",
    "Diese E-Mail wurde automatisch von der LIVARO-App verschickt.":
        "This email was sent automatically by the LIVARO app.",

    # ------------------------------------------------------------ Mein Konto
    "Mein Konto": "My account",
    "Angemeldet als {user} · {rolle}": "Signed in as {user} · {rolle}",
    "E-Mail (für Benachrichtigungen)": "Email (for notifications)",
    "Neues Passwort (leer = unverändert)": "New password (blank = unchanged)",
    "Passwort zu kurz (min. 6).": "Password too short (min. 6).",
    "Gespeichert.": "Saved.",
    "Gespeichert ✓": "Saved ✓",
    "Abmelden": "Sign out",
    "2FA aktiv": "2FA enabled",
    "2FA aktivieren": "Enable 2FA",
    "2FA deaktivieren": "Disable 2FA",
    "2FA aktiviert.": "2FA enabled.",
    "2FA deaktiviert.": "2FA disabled.",
    "🔐 Google Authenticator einrichten": "🔐 Set up Google Authenticator",
    "1. QR-Code in der Authenticator-App scannen:":
        "1. Scan the QR code in your authenticator app:",
    "oder Secret manuell eintippen:": "or enter the secret manually:",
    "2. Zur Bestätigung den aktuellen 6-stelligen Code eingeben:":
        "2. Enter the current 6-digit code to confirm:",
    "Code": "Code",
    "Code stimmt nicht – bitte erneut versuchen.": "Incorrect code – please try again.",
    "Kein angemeldeter Benutzer.": "No user signed in.",
    "Aktivieren": "Enable",

    # ------------------------------------------------------------- Allgemein
    "Bereiche": "Sections",
    "Speichern": "Save",
    "Abbrechen": "Cancel",
    "Schließen": "Close",
    "Löschen": "Delete",
    "Bearbeiten": "Edit",
    "Öffnen": "Open",
    "Zurück": "Back",
    "Weiter": "Next",
    "Ja": "Yes",
    "Nein": "No",
    "Administrator": "Administrator",
    "Manager": "Manager",
    "Putzkraft": "Cleaner",
    "Gast": "Guest",
    "keine": "none",
    "Noch keine Einträge.": "No entries yet.",

    # ------------------------------------------------------------- Buchungen
    "Buchungen": "Bookings",
    "An- und Abreisen, Wechseltage und Reinigungen": "Arrivals, departures, turnovers and cleanings",
    "Anreise": "Arrival",
    "Abreise": "Departure",
    "Anreise vorbereiten für": "Prepare arrival for",
    "Vorbereiten": "Prepare",
    "Vorbereiten für": "Prepare for",
    "Vorbereiten für {n}": "Prepare for {n}",
    "Es reist ab": "Departing",
    "Nur zur Info – nicht die Zahl für die Vorbereitung.":
        "For information only – not the number to prepare for.",
    "keine Folgebuchung": "no follow-up booking",
    "Nichts vorzubereiten – nur reinigen.": "Nothing to prepare – cleaning only.",
    "Wechseltag": "Turnover day",
    "Wechseltag – Anreise noch heute": "Turnover day – arrival still today",
    "Nächste Anreise: {datum} · {zeit}": "Next arrival: {datum} · {zeit}",
    "Person": "Guest",

    # ------------------------------------------- Übersicht Zeiterfassung
    "Meine Übersicht": "My overview",
    "Stunden dieser Monat": "Hours this month",
    "Ø je Einsatz": "Avg. per job",
    "davon Wo.-ende/Feiertag": "of which weekend/holiday",
    "Werktags {h}": "Weekdays {h}",
    "Vormonat": "Previous month",
    "Gesamt erfasst": "Total recorded",
    "Betrag dieser Monat": "Amount this month",
    "nach hinterlegtem Stundensatz": "at your hourly rate",
    "{n} Einsätze": "{n} jobs",
    "{n} Wohnungen": "{n} apartments",
    "Abrechnungsstand": "Billing status",
    "noch offen": "still open",
    "abgerechnet": "billed",
    "Std": "hrs",
    "Ans Steuerbüro gemeldet – nicht mehr änderbar.":
        "Reported to the tax office – no longer editable.",
    "„Abgerechnet“ heißt: ans Steuerbüro gemeldet. Diese Einträge "
    "lassen sich nicht mehr ändern.":
        "“Billed” means reported to the tax office. These entries can no longer be changed.",
    "Personen": "Guests",
    "Buchungskanal": "Booking channel",
    "Name": "Name",
    "E-Mail": "Email",
    "Telefon": "Phone",
    "Notizen": "Notes",
    "Protokoll": "Log",
    "Buchung": "Booking",
    "Nachrichten": "Messages",
    "Interne Notiz": "Internal note",
    "Buchungsdetails (Smoobu)": "Booking details (Smoobu)",
    "Ich übernehme": "I'll take it",
    "nicht zugewiesen": "unassigned",
    "Nicht zugewiesen": "Unassigned",
    "Zugewiesen": "Assigned",
    "In Arbeit": "In progress",
    "Fertig": "Done",
    "Überfällig": "Overdue",
    "Nächte": "Nights",
    "1 Erwachsener": "1 adult",
    "{n} Erwachsene": "{n} adults",
    "1 Kind": "1 child",
    "{n} Kinder": "{n} children",
    "keine Kinder": "no children",
    "{n} Pers.": "{n} people",

    # ------------------------------------------------------------- Reinigung
    "Checkliste": "Checklist",
    "Weiter zur Checkliste": "Continue to checklist",
    "{done}/{total} erledigt": "{done}/{total} done",
    "Alle Aufgaben abgeschlossen": "All tasks completed",
    "Nächste Schritte": "Next steps",
    "Reinigung": "Cleaning",
    "Soll": "Target",
    "Ist": "Actual",
    "Heute fällig (nach Abreise):": "Due today (after departure):",
    "Apartment wählen:": "Choose apartment:",
    "Apartment": "Apartment",
    "Reinigung starten": "Start cleaning",
    "Bitte Apartment wählen.": "Please choose an apartment.",
    "Fortschritt": "Progress",
    "Räume & Aufgaben": "Rooms & tasks",
    "Nach Raum gruppieren": "Group by room",
    "Alle Aufgaben anzeigen": "Show all tasks",
    "Alle einklappen": "Collapse all",
    "Checkliste abgeschlossen ✓": "Checklist completed ✓",
    "Checkliste abschließen": "Complete checklist",

    # --------------------------------------------------------- Zeiterfassung
    "Zeiterfassung": "Time tracking",
    "Start/Stop, manuell erfassen & bearbeiten": "Start/stop, add and edit entries",
    "Arbeitszeit läuft": "Work timer running",
    "Arbeitszeit starten": "Start work timer",
    "Arbeitszeit beenden": "Stop work timer",
    "Arbeitszeit gestartet ✓": "Work timer started ✓",
    "Arbeitszeit beendet ✓": "Work timer stopped ✓",
    "Beenden": "Stop",
    "Erfasst {dauer}": "Logged {dauer}",
    "Du bist bereits an einem anderen Ort eingecheckt.":
        "You are already checked in at another location.",
    "Standort wird geprüft …": "Checking location …",
    "Zeit manuell erfassen": "Add time manually",
    "Zeit bearbeiten": "Edit time entry",
    "Datum": "Date",
    "Von": "From",
    "Bis": "To",
    "Wohnung": "Apartment",
    "— keine Wohnung —": "— no apartment —",
    "Mitarbeiter": "Employee",
    "Ende muss nach Beginn liegen.": "End must be after start.",
    "Eintrag gelöscht.": "Entry deleted.",
    "Meine Zeiten": "My hours",
    "läuft…": "running…",
    "Werktag": "Weekday",
    "Wochenende/Feiertag": "Weekend/holiday",
    "Samstag": "Saturday",
    "Sonntag": "Sunday",
    "manuell": "manual",

    # ----------------------------------------------------------- Feiertage
    "Neujahr": "New Year's Day",
    "Karfreitag": "Good Friday",
    "Ostermontag": "Easter Monday",
    "Tag der Arbeit": "Labour Day",
    "Christi Himmelfahrt": "Ascension Day",
    "Pfingstmontag": "Whit Monday",
    "Tag der Deutschen Einheit": "German Unity Day",
    "Reformationstag": "Reformation Day",
    "Buß- und Bettag": "Day of Repentance and Prayer",
    "1. Weihnachtsfeiertag": "Christmas Day",
    "2. Weihnachtsfeiertag": "Boxing Day",

    # ---------------------------------------------------------------- Belege
    "Belege": "Receipts",
    "Rechnungen scannen, ablegen & per OCR auslesen":
        "Scan, file and read invoices via OCR",
    "Neuen Beleg hinzufügen": "Add new receipt",
    "Beleg scannen": "Scan receipt",
    "Scannen": "Scan",
    "Foto / Datei": "Photo / file",
    "Für welche Wohnung?": "For which apartment?",
    "Händler": "Merchant",
    "Notiz (z. B. wofür)": "Note (e.g. what for)",
    "Betrag": "Amount",
    "Beschreibung": "Description",
    "Kategorie": "Category",
    "Foto": "Photo",
    "Hochladen": "Upload",
    "Live scannen (Rand wird erkannt) oder Foto/Datei wählen. "
    "Das Dokument wird als PDF abgelegt und per OCR ausgelesen.":
        "Scan live (edges are detected) or pick a photo/file. The document is "
        "filed as a PDF and read via OCR.",
    "Hinweis: OCR (Tesseract) ist auf dem Server nicht installiert – "
    "Belege werden gespeichert, aber nicht automatisch ausgelesen.":
        "Note: OCR (Tesseract) is not installed on the server – receipts are "
        "stored but not read automatically.",
    "Kein Beleg erkannt – bitte neu ausrichten.":
        "No receipt detected – please reposition.",
    "Kamera wird gestartet …": "Starting camera …",
    "Kamera nicht verfügbar – wähle ein Foto aus.":
        "Camera unavailable – pick a photo instead.",
    "Beleg fotografieren – Ränder müssen mit aufs Bild.":
        "Photograph the receipt – include its edges.",
    "Ecken auf die Belegkanten ziehen.": "Drag the corners onto the receipt edges.",
    "Kamerabild noch nicht bereit – kurz warten.":
        "Camera image not ready yet – please wait.",
    "Foto aufnehmen": "Take photo",
    "Vorhandenes Foto wählen": "Choose an existing photo",
    "Neu aufnehmen": "Retake",
    "Ecken zurücksetzen": "Reset corners",
    "Zuschneiden & speichern": "Crop & save",
    "Ziehe die vier Punkte auf die Ecken des Belegs. Der Bereich "
    "wird geradegezogen und als PDF gespeichert.":
        "Drag the four points onto the corners of the receipt. The area is "
        "de-skewed and saved as a PDF.",
    "Scan konnte nicht verarbeitet werden.": "Scan could not be processed.",
    "Beleg wird verarbeitet (PDF, OCR) …": "Processing receipt (PDF, OCR) …",
    "Beleg wird verarbeitet (Zuschnitt, PDF, OCR) …":
        "Processing receipt (crop, PDF, OCR) …",
    "Beleg gescannt ✓": "Receipt scanned ✓",
    "Beleg erfasst ✓": "Receipt saved ✓",
    " (als PDF)": " (as PDF)",
    "Beleg wirklich löschen?": "Really delete this receipt?",
    "Beleg gelöscht.": "Receipt deleted.",
    "Noch keine Belege abgelegt.": "No receipts filed yet.",
    "Upload fehlgeschlagen: {fehler}": "Upload failed: {fehler}",

    # --------------------------------------------------- Buchungen, Kalender
    "Reinigungs-Übersicht & Buchungskalender": "Cleaning overview & booking calendar",
    "Reinigungen": "Cleanings",
    "Kalender": "Calendar",
    "Aktualisieren": "Refresh",
    "Alle Wohnungen": "All apartments",
    "Einzeln": "Single",
    "Heute": "Today",
    "Keine Wohnung gewählt.": "No apartment selected.",
    "Keine Wohnungen geladen.": "No apartments loaded.",
    "Keine anstehenden Reinigungen.": "No upcoming cleanings.",
    "Heute keine Reinigungen. 🎉": "No cleanings today. 🎉",
    "Check-in": "Check-in",
    "Check-out": "Check-out",
    "Ab": "Out",
    "An": "In",
    "Aktionen": "Actions",
    "Für diese Buchung wurde noch nichts erfasst.":
        "Nothing has been recorded for this booking yet.",

    # ------------------------------------------------- Schäden & Nachschub
    "Was ist beschädigt?": "What is damaged?",
    "Bitte Beschreibung angeben.": "Please enter a description.",
    "Schaden gemeldet – Danke!": "Damage reported – thank you!",
    "Melden": "Report",
    "melden": "report",
    "Was muss nachgekauft werden?": "What needs restocking?",
    "Menge": "Quantity",
    "{name} gemeldet ✓": "{name} reported ✓",
    "Foto gespeichert ✓": "Photo saved ✓",
    "Bitte Datum und Uhrzeiten prüfen.": "Please check the date and times.",

    # ------------------------------------------- Aktionen in einer Buchung
    "Ich übernehme diesen Auftrag": "I'll take this job",
    "Tauschen / Zuweisen": "Swap / assign",
    "Zeit nachtragen": "Add time entry",
    "Notiz hinzufügen": "Add note",
    "Verbrauch / Wäsche": "Supplies / laundry",
    "Schaden melden": "Report damage",
    "Checkliste & Fotos": "Checklist & photos",
    "Zurücksetzen (Admin)": "Reset (admin)",
    "Zuweisen": "Assign",
    "Zurücksetzen": "Reset",
    "Senden": "Send",
    "Notiz": "Note",

    "Arbeitszeit nachtragen – {wohnung}": "Add work time – {wohnung}",
    "Arbeitszeit nachgetragen: {dauer}": "Work time added: {dauer}",
    "Notiz – {wohnung}": "Note – {wohnung}",
    "Notiz gespeichert ✓": "Note saved ✓",
    "Verbrauch / Wäsche – {wohnung}": "Supplies / laundry – {wohnung}",
    "Schaden melden – {wohnung}": "Report damage – {wohnung}",
    "Zuweisen / Tauschen – {wohnung}": "Assign / swap – {wohnung}",
    "Keine weiteren Mitarbeiter.": "No other employees.",
    "Bitte Mitarbeiter wählen.": "Please select an employee.",
    "{wohnung} → {name} zugewiesen ✓": "{wohnung} → assigned to {name} ✓",
    "Auftrag zurücksetzen – {wohnung}": "Reset job – {wohnung}",
    "Setzt Zuweisung und Checklisten-Abschluss zurück und entfernt die für "
    "diese Buchung erfassten Arbeitszeiten. Status wird wieder Nicht "
    "zugewiesen. Die interne Notiz bleibt erhalten.":
        "Resets the assignment and checklist completion and removes the work "
        "time logged for this booking. The status returns to Unassigned. The "
        "internal note is kept.",
    "Auftrag zurückgesetzt (entfernte Zeiteinträge: {n}).":
        "Job reset (time entries removed: {n}).",

    # ------------------------------------------------- Protokoll (Buchung)
    "Arbeitszeit: {dauer}": "Work time: {dauer}",
    " ({n} Einträge)": " ({n} entries)",
    " (nachgetragen)": " (added manually)",
    "Checkliste: {done}/{total} erledigt · {fotos} Foto(s)":
        "Checklist: {done}/{total} done · {fotos} photo(s)",
    "Schäden gemeldet: {n}": "Damage reports: {n}",
    "Nachbestellt: {n}": "Restock requests: {n}",

    # ------------------------------------------------ Nachricht an den Gast
    "Bitte zuerst eine Antwort eingeben.": "Please enter a reply first.",
    "Nachricht an den Gast senden?": "Send message to the guest?",
    "Gast: {name}": "Guest: {name}",
    "Die Nachricht wird sofort über Smoobu an den Gast zugestellt.":
        "The message is delivered to the guest immediately via Smoobu.",
    "Kein Smoobu-API-Key konfiguriert.": "No Smoobu API key configured.",
    "Senden fehlgeschlagen: {fehler}": "Sending failed: {fehler}",
    "Nachricht an den Gast gesendet.": "Message sent to the guest.",

    # ------------------------------------------ Zeiterfassung: Check-in/out
    "Du bist bereits eingecheckt.": "You are already checked in.",
    "Eingecheckt ✓ · {ort} ({dist} m)": "Checked in ✓ · {ort} ({dist} m)",
    "Eingecheckt ✓ · ⚠️ nicht am Objekt (nächstes {dist} m)":
        "Checked in ✓ · ⚠️ not at the property (nearest {dist} m)",
    "Eingecheckt ✓ · ⚠️ kein Standort – bitte Ortung aktivieren.":
        "Checked in ✓ · ⚠️ no location – please enable location services.",
    "Kein offener Check-in.": "No open check-in.",
    "Ausgecheckt ✓ · {ort} ({dist} m)": "Checked out ✓ · {ort} ({dist} m)",
    "Eingecheckt ✓": "Checked in ✓",
    "Ausgecheckt ✓": "Checked out ✓",
    "Eingecheckt seit {zeit} Uhr": "Checked in since {zeit}",
    "Nachweis: ": "Evidence: ",
    "Nicht eingecheckt": "Not checked in",
    "Fertig · {dauer} · {done}/{total} erledigt": "Done · {dauer} · {done}/{total} completed",

    # ------------------------------------------------------ Reinigungsliste
    "Überfällig ({n})": "Overdue ({n})",
    "Heute ({n})": "Today ({n})",
    "Reinigung übernommen": "Cleaning taken on",
    "Foto konnte nicht gespeichert werden: {fehler}": "Photo could not be saved: {fehler}",
    "Hinweis: {name} hat keine E-Mail hinterlegt – "
    "keine Benachrichtigung verschickt.":
        "Note: {name} has no email address – no notification sent.",
    "Smoobu: {fehler}": "Smoobu: {fehler}",

    # ------------------------------------------------------- Beleg-Karte
    "PDF öffnen": "Open PDF",
    "Beleg löschen": "Delete receipt",
    "Erkannter Text (OCR)": "Recognised text (OCR)",

    # ------------------------------------------------- Gästekommunikation
    "Gästekommunikation": "Guest communication",
    "Nachrichten konnten nicht geladen werden: {fehler}":
        "Messages could not be loaded: {fehler}",
    "Noch keine Nachrichten zu dieser Buchung.": "No messages for this booking yet.",
    "Antwort an den Gast …": "Reply to the guest …",
    "Wird direkt über Smoobu an den Gast gesendet.":
        "Sent to the guest directly via Smoobu.",

    # ------------------------------------------------------------ Sonstiges
    "Willkommen, {name}!": "Welcome, {name}!",
    "Für deinen Zugang sind noch keine Bereiche freigeschaltet.":
        "No sections have been enabled for your account yet.",
}

TRANSLATIONS = {"en": _EN}


def _default_resolver():
    return DEFAULT


_resolver = _default_resolver


def set_resolver(fn):
    """Callable registrieren, das die Sprache des aktuellen Benutzers liefert.

    Wird von web.py auf die NiceGUI-Session gesetzt; als Modul bleibt i18n
    dadurch frei von UI-Abhängigkeiten und in Tests direkt steuerbar.
    """
    global _resolver
    _resolver = fn or _default_resolver


def lang():
    try:
        code = _resolver()
    except Exception:
        code = DEFAULT
    return code if code in LANGUAGES else DEFAULT


def tl(code, text, **kwargs):
    """Wie t(), aber mit ausdrücklich angegebener Sprache.

    Für Texte, die NICHT für den gerade angemeldeten Benutzer bestimmt sind –
    etwa die Einladungs-E-Mail an einen Mitarbeiter (dessen Profilsprache).
    """
    code = code if code in LANGUAGES else DEFAULT
    out = TRANSLATIONS.get(code, {}).get(text, text)
    if kwargs:
        try:
            return out.format(**kwargs)
        except (KeyError, IndexError):
            return out
    return out


def t(text, **kwargs):
    """Übersetzten Text liefern; ohne Treffer den deutschen Ausgangstext."""
    return tl(lang(), text, **kwargs)


def missing(code="en"):
    """Schlüssel ohne Übersetzung – für Tests und Pflege."""
    return sorted(k for k in _EN if not TRANSLATIONS.get(code, {}).get(k))
