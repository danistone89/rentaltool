#!/usr/bin/env python3
"""HTML-Rendering: Dashboard mit Ergebnis, Buchungsliste und PDF-Download.

Nur Standardbibliothek. Das amtliche Formular wird als echte PDF erzeugt
(app/pdf_form.py) und über /pdf heruntergeladen.
"""
import html
import urllib.parse

MONATE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]


def euro(v):
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _esc(s):
    return html.escape(str(s if s is not None else ""))


PAGE_CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#1a1d24;--muted:#6b7280;--line:#e3e6ea;
--accent:#1f6feb;--accent-bg:#eaf2ff;--good:#0a7d33;}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
color:var(--ink);background:var(--bg)}
header{background:var(--card);border-bottom:1px solid var(--line);padding:14px 24px;
display:flex;align-items:baseline;gap:14px}
header h1{font-size:17px;margin:0}
header .sub{color:var(--muted);font-size:13px}
main{max-width:1080px;margin:0 auto;padding:24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:18px 20px;margin-bottom:20px}
.controls{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end}
.controls label{display:flex;flex-direction:column;font-size:12px;color:var(--muted);gap:4px}
.controls select,.controls input{font:14px inherit;padding:7px 9px;border:1px solid var(--line);
border-radius:7px;background:#fff;min-width:90px}
.controls button{font:14px inherit;padding:8px 16px;border:0;border-radius:7px;
background:var(--accent);color:#fff;cursor:pointer}
.controls button:hover{filter:brightness(1.06)}
.apts{display:flex;flex-direction:column;gap:3px}
.apts .opt{display:flex;gap:6px;align-items:center;color:var(--ink);font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.kpi{background:var(--accent-bg);border-radius:10px;padding:14px 16px}
.kpi .lbl{font-size:12px;color:var(--muted)}
.kpi .val{font-size:24px;font-weight:600;margin-top:2px}
.kpi.tax .val{color:var(--good)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr.airbnb td{color:var(--muted);background:#fafbfc}
tfoot .sum td{font-weight:600;border-top:2px solid #c9ced6;background:#f4f7fb}
tfoot .sum.air td{color:var(--muted);font-weight:500;background:#fafbfc}
.flag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:99px;background:#eee}
.flag.air{background:#ffeef0;color:#b3204a}
.note{color:var(--muted);font-size:12px;margin-top:8px}
.err{background:#fff0f0;border:1px solid #f3b4b4;color:#9a1c1c;padding:12px 14px;border-radius:8px}
.toolbar{display:flex;gap:10px;margin-bottom:14px}
.btn{font:14px inherit;padding:8px 16px;border:1px solid var(--line);border-radius:7px;
background:#fff;color:var(--ink);cursor:pointer;text-decoration:none}
.btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
h2{font-size:15px;margin:0 0 12px}
"""


def dashboard(cfg, apartments, sel, result, error=None):
    """sel: dict mit year, month, apt_ids(set/list), airbnb, befreit."""
    opts_month = "".join(
        f'<option value="{m}"{" selected" if m == sel["month"] else ""}>{MONATE[m]}</option>'
        for m in range(1, 13))
    years = range(2023, sel["year"] + 2)
    opts_year = "".join(
        f'<option value="{y}"{" selected" if y == sel["year"] else ""}>{y}</option>'
        for y in years)
    apt_ids = set(sel.get("apt_ids") or [])
    apt_opts = "".join(
        f'<label class="opt"><input type="checkbox" name="apt" value="{a["id"]}"'
        f'{" checked" if (not apt_ids or a["id"] in apt_ids) else ""}> {_esc(a["name"])}</label>'
        for a in apartments)

    body = [f"""<!doctype html><html lang="de"><meta charset="utf-8">
<title>Beherbergungssteuer Dresden</title><style>{PAGE_CSS}</style>
<header><h1>Beherbergungssteuer Dresden</h1>
<span class="sub">{_esc(cfg['betreiber']['name'])} · Kassenzeichen {_esc(cfg['betreiber']['kassenzeichen'])}</span></header>
<main>
<form class="card noprint" method="get" action="/">
  <div class="controls">
    <label>Jahr<select name="year">{opts_year}</select></label>
    <label>Monat<select name="month">{opts_month}</select></label>
    <label>Apartments<div class="apts">{apt_opts}</div></label>
    <label>Airbnb-ÜN (Override)<input type="number" name="airbnb" min="0" step="1"
      value="{_esc(sel.get('airbnb',''))}" placeholder="leer = berechnet"></label>
    <label>Steuerbefr. Umsatz €<input type="number" name="befreit" min="0" step="0.01"
      value="{sel.get('befreit',0) or 0}"></label>
    <button type="submit">Berechnen</button>
  </div>
  <div class="note">Zuordnung nach Abreisedatum (§6) · Steuerbasis = Buchungspreis ohne
    durchlaufende Übernachtungssteuer (Reinigung inkl.) · nur bereits stattgefundene
    Buchungen (Abreise ≤ heute). Airbnb wird aus Smoobu berechnet; Override nur ausnahmsweise.</div>
</form>"""]

    if error:
        body.append(f'<div class="card err">{_esc(error)}</div></main></html>')
        return "".join(body)

    if result is None:
        body.append("</main></html>")
        return "".join(body)

    r = result
    body.append(f"""
<div class="card noprint">
  <h2>Ergebnis {MONATE[r['month']]} {r['year']}</h2>
  <div class="kpis">
    <div class="kpi"><div class="lbl">ÜN insgesamt</div><div class="val">{r['uebernachtungen_insgesamt']}</div></div>
    <div class="kpi"><div class="lbl">verbleibende ÜN</div><div class="val">{r['uebernachtungen_verbleibend']}</div></div>
    <div class="kpi"><div class="lbl">steuerpfl. Umsatz</div><div class="val">{euro(r['umsatz_steuerpflichtig'])} €</div></div>
    <div class="kpi tax"><div class="lbl">Beherbergungssteuer</div><div class="val">{euro(r['beherbergungssteuer'])} €</div></div>
  </div>
  <p class="note">Airbnb-ÜN (berechnet): {r['uebernachtungen_airbnb']} – fließen nicht in die
    Steuer ein (Airbnb meldet selbst). Basis = Preis ohne durchlaufende Übernachtungssteuer,
    Steuersatz {int(r['steuersatz']*100)} %.</p>
</div>""")

    body.append(_booking_table(r))
    params = [("year", sel["year"]), ("month", sel["month"]),
              ("airbnb", sel.get("airbnb", "")), ("befreit", sel.get("befreit", 0))]
    params += [("apt", a) for a in (sel.get("apt_ids") or [])]
    pdf_url = "/pdf?" + urllib.parse.urlencode(params)
    body.append(f'''<div class="toolbar noprint">
      <a class="btn primary" href="{pdf_url}" target="_blank">📄 Amtliches Formular (PDF) herunterladen</a>
      <span class="note">Pixelgenau wie das Original (Vdr 22.040/5), Monat angekreuzt, Werte eingesetzt.</span>
    </div>''')
    body.append("</main></html>")
    return "".join(body)


def _booking_table(r):
    rows = []
    for x in r["rows"]:
        cls = ' class="airbnb"' if x["is_airbnb"] else ""
        flag = '<span class="flag air">Airbnb</span>' if x["is_airbnb"] else f'<span class="flag">{_esc(x["channel"])}</span>'
        steuer = '<span style="color:#9aa0aa">—</span>' if x["is_airbnb"] \
            else euro(round(x["base"] * r["steuersatz"], 2))
        rows.append(f"""<tr{cls}>
<td>{_esc(x['departure'])}</td><td>{_esc(x['guest'])}</td><td>{_esc(x['apartment'])}</td>
<td>{flag}</td><td>{_esc(x['arrival'])}</td><td class="num">{x['nights']}</td>
<td class="num">{x['persons']}</td><td class="num">{x['overnights']}</td>
<td class="num">{euro(x['price'])}</td><td class="num">{steuer}</td></tr>""")
    foot = f"""<tfoot>
<tr class="sum"><td colspan="7">Steuerpflichtig (alle Kanäle außer Airbnb – Booking.com, Website, Direkt …)</td>
<td class="num">{r['uebernachtungen_verbleibend']} ÜN</td>
<td class="num">{euro(r['umsatz_verbleibend'])}</td>
<td class="num">{euro(r['beherbergungssteuer'])}</td></tr>
<tr class="sum air"><td colspan="7">Airbnb (Airbnb meldet selbst – keine Steuer)</td>
<td class="num">{r['uebernachtungen_airbnb']} ÜN</td><td class="num">—</td><td class="num">—</td></tr>
</tfoot>"""
    return f"""<div class="card noprint">
<h2>Buchungen ({len(r['rows'])}) – Abreise im Monat, bereits stattgefunden</h2>
<table><thead><tr><th>Abreise</th><th>Gast</th><th>Apartment</th><th>Kanal</th>
<th>Anreise</th><th class="num">Nächte</th><th class="num">Pers.</th>
<th class="num">ÜN</th><th class="num">Gesamtpreis €</th><th class="num">Steuer €</th></tr></thead>
<tbody>{''.join(rows)}</tbody>{foot}</table></div>"""


