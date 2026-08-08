"""Belege: Scanner (Kamera + Ecken ziehen), Ablage, OCR, Liste.

Bewusst ohne automatische Kantenerkennung im Browser – der Versuch mit
OpenCV.js traf Belege zu unzuverlaessig und lud 10 MB WebAssembly (siehe README).
"""

import os
import base64
from nicegui import ui
from app import (belegzuordnung, buchhaltung, housekeeping, mode, protokoll,
                 receipts, rechte, stammdaten)
from app.ui.basis import (CFG, _MONATE, _apts, _cur_user, _d, _darf, _esc_attr,
                          _photo_thumb, _read_upload, bereichskopf,
                          leer, stoerung, t)
from app.ui import ton

def _beleg_mirror():
    if mode.STAGING:
        return None
    return CFG.get("belege_ordner") or None


# Client-Scanner: Foto aufnehmen, dann Ecken von Hand ziehen.
#
# Die automatische Kantenerkennung (OpenCV.js + jscanify) traf Belege zu
# unzuverlässig – Kassenbons auf hellem Untergrund liefern kaum Kanten. Der
# Ablauf ist deshalb zweistufig und kommt ohne Fremdbibliothek aus:
#
#   1. Kamera -> "Foto aufnehmen" friert das Bild ein
#   2. Vier Eckpunkte liegen als Rechteck auf dem Bild und lassen sich per
#      Finger/Maus ziehen; eine Lupe zeigt den Bereich unter dem Finger
#   3. Beim Speichern gehen Bild + Ecken (als Anteile 0..1) an Python, das
#      serverseitig perspektivisch entzerrt und die A4-PDF baut
#
# Kein OpenCV.js (10 MB) und kein jscanify mehr – reines Canvas.
_SCAN_JS = r"""
(function(){
  let tries=0;
  function start(){
    const wrap=document.getElementById('beleg-scan');
    if(!wrap){ if(tries++<30){setTimeout(start,100);} return; }
    if(wrap.dataset.init) return; wrap.dataset.init='1';

    const video=wrap.querySelector('video');
    const cv2=wrap.querySelector('canvas.edit');      // Bearbeitungsflaeche
    const status=wrap.querySelector('.scan-status');
    const ctx=cv2.getContext('2d');
    const M=k=>wrap.dataset[k]||'';

    const shot=document.createElement('canvas');      // Originalaufloesung
    let stream=null, img=null, pts=null, drag=-1, dpr=window.devicePixelRatio||1;

    function setStatus(t){ if(status) status.textContent=t; }
    function phase(p){
      wrap.dataset.phase=p;
      video.style.display   = p==='cam'  ? 'block':'none';
      cv2.style.display     = p==='edit' ? 'block':'none';
      document.querySelectorAll('.beleg-cam').forEach(e=>e.style.display = p==='cam' ?'':'none');
      document.querySelectorAll('.beleg-edit').forEach(e=>e.style.display = p==='edit'?'':'none');
    }

    async function init(){
      try{
        setStatus(M('msgCam'));
        stream=await navigator.mediaDevices.getUserMedia(
          {video:{facingMode:{ideal:'environment'},
                  width:{ideal:2560},height:{ideal:1440}},audio:false});
        video.srcObject=stream; await video.play();
        phase('cam'); setStatus(M('msgAim'));
      }catch(err){
        phase('cam');
        setStatus(M('msgNoCam')+' ('+((err&&err.message)||err)+')');
      }
    }

    function stopCam(){
      if(stream){ try{stream.getTracks().forEach(t=>t.stop());}catch(e){} stream=null; }
    }

    // ---- Schritt 1: Foto einfrieren -------------------------------------
    function capture(){
      const w=video.videoWidth,h=video.videoHeight;
      if(!w||!h){ setStatus(M('msgNoFrame')); return; }
      shot.width=w; shot.height=h;
      shot.getContext('2d').drawImage(video,0,0,w,h);
      stopCam();
      img=new Image();
      img.onload=()=>{ resetPts(); layout(); phase('edit'); setStatus(M('msgDrag')); };
      img.src=shot.toDataURL('image/jpeg',0.95);
    }

    // Startrechteck mit 8 % Rand – bewusst grosszuegig, damit alle vier
    // Griffe sichtbar im Bild liegen und nicht am Rand kleben.
    function resetPts(){ const a=0.08,b=1-a; pts=[[a,a],[b,a],[b,b],[a,b]]; }

    function layout(){
      const maxW=wrap.clientWidth||360, maxH=Math.round(window.innerHeight*0.52);
      const s=Math.min(maxW/img.width, maxH/img.height);
      const w=Math.round(img.width*s), h=Math.round(img.height*s);
      cv2.style.width=w+'px'; cv2.style.height=h+'px';
      cv2.width=Math.round(w*dpr); cv2.height=Math.round(h*dpr);
      draw();
    }

    function P(i){ return [pts[i][0]*cv2.width, pts[i][1]*cv2.height]; }

    function draw(){
      if(!img) return;
      ctx.clearRect(0,0,cv2.width,cv2.height);
      ctx.drawImage(img,0,0,cv2.width,cv2.height);
      // Bereich ausserhalb der Auswahl abdunkeln
      ctx.save();
      ctx.beginPath(); ctx.rect(0,0,cv2.width,cv2.height);
      ctx.moveTo(...P(0)); for(let i=3;i>=1;i--) ctx.lineTo(...P(i));
      ctx.closePath();
      ctx.fillStyle='rgba(0,0,0,.45)'; ctx.fill('evenodd');
      ctx.restore();
      // Auswahlkanten
      ctx.beginPath(); ctx.moveTo(...P(0));
      for(let i=1;i<4;i++) ctx.lineTo(...P(i));
      ctx.closePath();
      ctx.lineWidth=Math.max(2,cv2.width/300); ctx.strokeStyle='#16a34a'; ctx.stroke();
      // Griffe
      const r=Math.max(10,cv2.width/45);
      for(let i=0;i<4;i++){
        const [x,y]=P(i);
        ctx.beginPath(); ctx.arc(x,y,r,0,6.2832);
        ctx.fillStyle= drag===i ? 'rgba(22,163,74,.95)' : 'rgba(255,255,255,.9)';
        ctx.fill(); ctx.lineWidth=Math.max(2,r/5); ctx.strokeStyle='#16a34a'; ctx.stroke();
      }
      if(drag>=0) magnifier(P(drag));
    }

    // Lupe: der Finger verdeckt die Ecke, deshalb den Ausschnitt daneben zeigen
    function magnifier(p){
      const R=Math.min(cv2.width,cv2.height)*0.16, Z=2.5;
      const cx = p[0] < cv2.width/2 ? cv2.width-R-8 : R+8;
      const cy = R+8;
      ctx.save();
      ctx.beginPath(); ctx.arc(cx,cy,R,0,6.2832); ctx.clip();
      ctx.fillStyle='#000'; ctx.fillRect(cx-R,cy-R,2*R,2*R);
      ctx.drawImage(img, 0,0, img.width,img.height,
                    cx-p[0]*Z, cy-p[1]*Z, cv2.width*Z, cv2.height*Z);
      ctx.beginPath(); ctx.moveTo(cx-R,cy); ctx.lineTo(cx+R,cy);
      ctx.moveTo(cx,cy-R); ctx.lineTo(cx,cy+R);
      ctx.strokeStyle='rgba(22,163,74,.9)'; ctx.lineWidth=1.5; ctx.stroke();
      ctx.restore();
      ctx.beginPath(); ctx.arc(cx,cy,R,0,6.2832);
      ctx.strokeStyle='#16a34a'; ctx.lineWidth=2; ctx.stroke();
    }

    function pos(ev){
      const r=cv2.getBoundingClientRect();
      const t=(ev.touches&&ev.touches[0])||ev;
      return [(t.clientX-r.left)/r.width, (t.clientY-r.top)/r.height];
    }
    function nearest(q){
      let best=-1,bd=1e9;
      for(let i=0;i<4;i++){
        const d=Math.hypot(pts[i][0]-q[0], pts[i][1]-q[1]);
        if(d<bd){ bd=d; best=i; }
      }
      return bd<0.12 ? best : -1;          // nur greifen, wenn nah genug
    }
    function down(ev){ if(!img) return; drag=nearest(pos(ev)); if(drag>=0){ ev.preventDefault(); draw(); } }
    function move(ev){
      if(drag<0) return;
      ev.preventDefault();
      const q=pos(ev);
      pts[drag]=[Math.min(1,Math.max(0,q[0])), Math.min(1,Math.max(0,q[1]))];
      draw();
    }
    function up(){ if(drag>=0){ drag=-1; draw(); } }

    cv2.addEventListener('mousedown',down);   cv2.addEventListener('touchstart',down,{passive:false});
    window.addEventListener('mousemove',move); cv2.addEventListener('touchmove',move,{passive:false});
    window.addEventListener('mouseup',up);     cv2.addEventListener('touchend',up);
    window.addEventListener('resize',()=>{ if(img) layout(); });

    // ---- Schritt 2: Datei waehlen statt Kamera --------------------------
    function fromFile(file){
      if(!file) return;
      const fr=new FileReader();
      fr.onload=()=>{
        stopCam();
        img=new Image();
        img.onload=()=>{
          shot.width=img.width; shot.height=img.height;
          shot.getContext('2d').drawImage(img,0,0);
          resetPts(); layout(); phase('edit'); setStatus(M('msgDrag'));
        };
        img.src=fr.result;
      };
      fr.readAsDataURL(file);
    }

    window.__belegCapture=capture;
    window.__belegRetake=function(){ img=null; phase('cam'); init(); };
    window.__belegReset=function(){ if(img){ resetPts(); draw(); } };
    window.__belegFile=function(){
      const inp=document.createElement('input');
      inp.type='file'; inp.accept='image/*';
      inp.onchange=()=>fromFile(inp.files&&inp.files[0]);
      inp.click();
    };
    window.__belegStop=stopCam;
    window.__belegSave=function(){
      if(!img||!pts) return;
      setStatus(M('msgWork'));
      emitEvent('beleg_scan', {image: shot.toDataURL('image/jpeg',0.92), corners: pts});
    };
    init();
  }
  start();
})();
"""


def render_belege():
    user = _cur_user()
    darf_loeschen = _darf(rechte.BELEGE_LOESCHEN)
    bereichskopf("receipt", t("Belege"),
                 t("Rechnungen scannen, ablegen & per OCR auslesen"))

    apts = _apts()
    sc = {"apt": None, "dlg": None}
    # Ueberlebt das Neuzeichnen – sonst springt die Liste nach jedem
    # Handgriff auf „Alle" zurueck.
    zustand = {"beleg_sicht": "alle"}

    def _process_and_add(data, ext, crop, corners=None):
        """Beleg-Bytes -> Dokument/PDF + OCR + Datensatz (blockierender Teil).

        corners: die im Scanner gesetzten Ecken (Anteile 0..1); sie haben
        Vorrang vor der automatischen Erkennung."""
        doc = receipts.save_document(data, ext, _beleg_mirror(), crop, corners)
        # Bei einer echten PDF steht der Text drin und muss nicht geraten
        # werden – Lieferantenrechnungen liefern so exakte Betraege statt
        # OCR-Naeherungen. Nur eingescanntes Papier braucht die Erkennung.
        text = ""
        try:
            if doc.get("pdf") and receipts.ist_pdf(data):
                text = receipts.text_aus_pdf(
                    os.path.join(housekeeping.MEDIA_DIR, doc["pdf"]))
            if not text and doc.get("photo"):
                text = receipts.ocr_image(
                    os.path.join(housekeeping.MEDIA_DIR, doc["photo"]))
        except Exception:
            text = ""
        aid = sc["apt"]
        haendler = receipts.guess_merchant(text)
        # Ein bekannter Lieferant bringt seine Kategorie mit (AP13). Die vom
        # Benutzer gewaehlte Wohnung schlaegt die Vorgabe des Kreditors – wer
        # sie ausdruecklich gesetzt hat, weiss es besser.
        kategorie, kreditor_wohnung, _k = stammdaten.vorbelegung(haendler)
        if aid is None and kreditor_wohnung:
            aid = kreditor_wohnung
        receipts.add_receipt(user, doc["photo"], ocr_text=text,
                             amount=receipts.guess_amount(text),
                             merchant=haendler, pdf=doc.get("pdf"),
                             kategorie=kategorie,
                             apartment_id=aid, apartment_name=apts.get(aid, ""))
        return doc

    def _open_scanner():
        """Zweistufig: erst Foto aufnehmen, dann die vier Ecken von Hand ziehen.
        Die automatische Kantenerkennung war auf Belegen zu unzuverlaessig."""
        state = {"busy": False}

        def js(code):
            ui.run_javascript(code)

        with ui.dialog().props("persistent") as dlg, \
                ui.card().classes("w-[560px] max-w-full gap-2").mark("scan-dialog"):
            with ui.row().classes("w-full items-center"):
                ui.label(t("Beleg scannen")).classes("font-bold")
                ui.space()
                ui.button(icon="close",
                          on_click=lambda: (js("window.__belegStop&&window.__belegStop()"),
                                            dlg.close())).props("flat round dense")

            msgs = {
                "msg-cam": t("Kamera wird gestartet …"),
                "msg-no-cam": t("Kamera nicht verfügbar – wähle ein Foto aus."),
                "msg-aim": t("Beleg fotografieren – Ränder müssen mit aufs Bild."),
                "msg-drag": t("Ecken auf die Belegkanten ziehen."),
                "msg-no-frame": t("Kamerabild noch nicht bereit – kurz warten."),
                "msg-work": t("Beleg wird verarbeitet (PDF, OCR) …"),
            }
            attrs = " ".join(f'data-{k}="{_esc_attr(v)}"' for k, v in msgs.items())
            ui.html(
                f'<div id="beleg-scan" style="width:100%" {attrs}>'
                '<video autoplay playsinline muted '
                'style="width:100%;border-radius:12px;background:#000;display:block"></video>'
                '<canvas class="edit" style="display:none;border-radius:12px;'
                'background:#000;margin:0 auto;touch-action:none"></canvas>'
                '<div class="scan-status" style="font-size:12px;color:#6b7280;'
                'margin-top:6px;text-align:center;min-height:18px"></div></div>',
                # Selbst erzeugtes Markup; die Texte sind per _esc_attr entschaerft.
                # Ohne sanitize=False entfernt NiceGUI <video>/<canvas>.
                sanitize=False)

            async def _on_scan(e):
                """Bild + Ecken aus dem Browser entgegennehmen."""
                if state["busy"]:
                    return
                state["busy"] = True
                try:
                    from nicegui import run
                    payload = e.args or {}
                    url = payload.get("image") or ""
                    corners = payload.get("corners") or None
                    try:
                        raw = base64.b64decode(url.split(",", 1)[1])
                    except Exception:
                        ui.notify(t("Scan konnte nicht verarbeitet werden."), type="negative")
                        return
                    dlg.close()
                    ui.notify(t("Beleg wird verarbeitet (PDF, OCR) …"), type="info", timeout=3000)
                    await run.io_bound(_process_and_add, raw, "jpg", False, corners)
                    ui.notify(t("Beleg gescannt ✓"), type="positive")
                    render_alles()
                finally:
                    state["busy"] = False
            ui.on("beleg_scan", _on_scan)

            # --- Schritt 1: Kamera ---
            with ui.row().classes("w-full items-center gap-2 beleg-cam"):
                ui.button(t("Foto aufnehmen"), icon="photo_camera",
                          on_click=lambda: js("window.__belegCapture&&window.__belegCapture()")) \
                    .props("unelevated no-caps size=lg").classes("flex-grow")
                ui.button(icon="folder_open",
                          on_click=lambda: js("window.__belegFile&&window.__belegFile()")) \
                    .props("outline").tooltip(t("Vorhandenes Foto wählen"))

            # --- Schritt 2: Ecken ziehen ---
            with ui.column().classes("w-full gap-2 beleg-edit").style("display:none"):
                ui.label(t("Ziehe die vier Punkte auf die Ecken des Belegs. Der Bereich "
                           "wird geradegezogen und als PDF gespeichert.")) \
                    .classes("text-[11px] text-slate-500 text-center")
                with ui.row().classes("w-full items-center gap-2"):
                    ui.button(t("Neu aufnehmen"), icon="replay",
                              on_click=lambda: js("window.__belegRetake&&window.__belegRetake()")) \
                        .props("outline no-caps")
                    ui.button(t("Ecken zurücksetzen"), icon="crop_free",
                              on_click=lambda: js("window.__belegReset&&window.__belegReset()")) \
                        .props("flat no-caps")
                ui.button(t("Zuschneiden & speichern"), icon="check",
                          on_click=lambda: js("window.__belegSave&&window.__belegSave()")) \
                    .props("unelevated no-caps size=lg").classes("w-full")
        sc["dlg"] = dlg
        dlg.open()
        ui.run_javascript(_SCAN_JS)

    # Kategorisieren ist ein Buchungsakt: eine falsche Kategorie laeuft still in
    # die EÜR. Die Putzkraft fotografiert und schreibt Haendler, Betrag und
    # wofuer – gebucht wird von der Verwaltung.
    bucht = _darf(rechte.BELEGE_BUCHEN)

    if bucht:
        with ui.tabs().props("dense no-caps align=left").classes("w-full") as reiter:
            r_liste = ui.tab(t("Belege"), icon="receipt")
            r_abschluss = ui.tab(t("Monatsabschluss"), icon="event_available")
        with ui.tab_panels(reiter, value=r_liste).classes("w-full"):
            with ui.tab_panel(r_liste).classes("p-0"):
                box = ui.column().classes("w-full gap-3")
            with ui.tab_panel(r_abschluss).classes("p-0").mark("panel-abschluss"):
                abschluss_box = ui.column().classes("w-full gap-3")
    else:
        box = ui.column().classes("w-full gap-3")
        abschluss_box = None

    def render():
        box.clear()
        with box:
            # Upload-Karte
            with ui.card().classes(ton.KARTE_WEIT):
                ui.label(t("Neuen Beleg hinzufügen")).classes("font-medium")
                ui.label(t("Live scannen (Rand wird erkannt), Foto wählen – oder eine "
                   "fertige PDF hochladen, wie sie Lieferanten per Mail schicken.")) \
                    .classes("text-xs text-slate-500")
                apt_sel = ui.select({None: t("— keine Wohnung —"), **apts}, value=sc["apt"],
                                    label=t("Für welche Wohnung?")).props("outlined dense") \
                    .classes("min-w-[220px]")
                apt_sel.on_value_change(lambda e: sc.update(apt=e.value))

                async def _einen(datei, nr, gesamt):
                    """Eine Datei verarbeiten. Gibt (doc, fehler) zurueck.

                    Zuschnitt, PDF und OCR dauern je Beleg mehrere Sekunden.
                    Bei einem Stapel ist deshalb wichtig, dass der Zaehler
                    mitlaeuft – sonst sieht es aus, als haenge die Seite.
                    """
                    from nicegui import run
                    try:
                        content = await datei.read()
                        name = getattr(datei, "name", None) or "foto.jpg"
                    except Exception as ex:
                        return None, str(ex)
                    ext = (name.rsplit(".", 1)[-1] if "." in name else "jpg").lower()[:4] or "jpg"
                    if gesamt > 1:
                        ui.notify(t("Beleg {nr} von {gesamt} wird verarbeitet …",
                                    nr=nr, gesamt=gesamt), type="info", timeout=2500)
                    else:
                        ui.notify(t("Beleg wird verarbeitet (Zuschnitt, PDF, OCR) …"),
                                  type="info", timeout=4000)
                    try:
                        return await run.io_bound(_process_and_add, content, ext, True), None
                    except Exception as ex:
                        return None, str(ex)

                async def _stapel(dateien):
                    fertig, fehler = await _stapel_verarbeiten(dateien, _einen)
                    if fertig:
                        ui.notify(t("{n} Belege erfasst ✓", n=fertig) if fertig > 1
                                  else t("Beleg erfasst ✓"), type="positive")
                    for problem in fehler[:3]:
                        ui.notify(t("Upload fehlgeschlagen: {fehler}", fehler=problem),
                                  type="negative", timeout=8000)
                    render_alles()

                async def handle_viele(e):
                    await _stapel(list(e.files))

                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    ui.button(t("Beleg scannen"), icon="document_scanner", on_click=_open_scanner) \
                        .props("unelevated no-caps").mark("scan-open")
                    ui.upload(auto_upload=True, multiple=True, max_files=30,
                              on_upload=None, on_multi_upload=handle_viele,
                              label=t("Fotos oder PDFs")) \
                        .props('accept="image/*,application/pdf"') \
                        .classes("hk-upload max-w-[220px]").mark("beleg-upload")
                ui.label(t("Mehrere Dateien auf einmal sind möglich – Zuschnitt, "
                           "PDF und Texterkennung laufen dann nacheinander.")) \
                    .classes(f"text-xs {ton.STILL}")
                if not receipts.ocr_available():
                    ui.label(t("Hinweis: OCR (Tesseract) ist auf dem Server nicht installiert – "
                       "Belege werden gespeichert, aber nicht automatisch ausgelesen.")) \
                        .classes("text-xs text-amber-700")

            items = receipts.list_receipts()
            if not items:
                leer("receipt_long", t("Noch keine Belege abgelegt."),
                     t("Oben fotografieren oder eine Datei hochladen."))
                return
            # ---- B5d: die beiden Wege sehen einander ---------------------
            # Ein Beleg, der an keiner Bankbewegung haengt, ist fuer die
            # Buchhaltung nicht vorhanden. Vorher liess sich das hier gar
            # nicht sehen. Kein Zusammenlegen der Bereiche: Fotografieren
            # unterwegs und Buchen am Schreibtisch sind zwei Situationen.
            if bucht:
                offene = belegzuordnung.ohne_bewegung()
                if offene:
                    with ui.row().classes("w-full items-center gap-2"):
                        ui.label(t("{n} Belege hängen an keiner Bankbewegung.",
                                   n=len(offene))).classes(f"text-xs {ton.AUF_HINWEIS}")
                        ui.space()
                        ui.toggle({"alle": t("Alle ({n})", n=len(items)),
                                   "offen": t("Ohne Bewegung ({n})", n=len(offene))},
                                  value=zustand["beleg_sicht"],
                                  on_change=lambda e: (zustand.update(beleg_sicht=e.value),
                                                       render_alles())) \
                            .props("dense no-caps unelevated size=sm").mark("beleg-sicht")
                    if zustand["beleg_sicht"] == "offen":
                        items = offene
            # Gruppiert nach dem BELEGDATUM, nicht nach dem Upload: ein Beleg vom
            # 29. gehoert in den alten Monat, auch wenn er am 2. ankommt.
            items = sorted(items, key=buchhaltung.belegdatum, reverse=True)
            cur_month = None
            for r in items:
                month = buchhaltung.monat(r)
                if month != cur_month:
                    cur_month = month
                    ym = f"{_MONATE[int(month[5:7]) - 1]} {month[:4]}"
                    with ui.row().classes("w-full items-center gap-2 mt-3"):
                        ui.label(ym).classes("text-sm font-semibold text-primary")
                        if buchhaltung.abschluss_von(month):
                            ui.chip(t("abgeschlossen"), icon="lock") \
                                .props("color=green-7 text-color=white dense square") \
                                .classes("text-xs")
                _beleg_card(r, apts, user, darf_loeschen, bucht, render_alles)

    def render_abschluss():
        if abschluss_box is None:
            return
        abschluss_box.clear()
        with abschluss_box:
            _abschluss_ansicht(user, render_alles)

    def render_alles():
        render()
        render_abschluss()

    render_alles()


def _beleg_card(r, apts, user, darf_loeschen, bucht, rerender):
    zu = buchhaltung.abschluss_von(buchhaltung.monat(r)) is not None
    with ui.card().classes(ton.KARTE_ENG):
        with ui.row().classes("w-full items-start gap-3 no-wrap"):
            if r.get("photo"):
                _photo_thumb(f"/media/{r['photo']}", "w-20 h-20")
            with ui.column().classes("gap-1 min-w-0 flex-grow"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    merch = ui.input(placeholder=t("Händler"), value=r.get("merchant", "")) \
                        .props("dense borderless").classes("font-semibold flex-grow min-w-0")
                    merch.on("blur", lambda e, i=r["id"], f=merch:
                             receipts.update_receipt(i, merchant=f.value or ""))
                    amount = ui.input(placeholder="€", value=r.get("amount", "")) \
                        .props("dense borderless").classes("w-20 text-right")
                    amount.on("blur", lambda e, i=r["id"], f=amount:
                              receipts.update_receipt(i, amount=f.value or ""))
                    ui.label("€").classes("text-sm text-slate-400")
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.icon("home").classes("text-slate-400 text-sm shrink-0")
                    apt_sel = ui.select({None: "— keine Wohnung —", **apts},
                                        value=r.get("apartment_id")).props("dense borderless") \
                        .classes("min-w-0")
                    apt_sel.on_value_change(lambda e, i=r["id"]:
                                            receipts.update_receipt(i, apartment_id=e.value,
                                                                    apartment_name=apts.get(e.value, "")))
                if bucht:
                    # Das Belegdatum ist NICHT der Upload: ein Beleg vom 29.,
                    # der am 2. ankommt, gehört in den alten Monat.
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.icon("event").classes("text-slate-400 text-sm shrink-0")
                        datum = ui.input(value=buchhaltung.belegdatum(r)) \
                            .props("type=date dense borderless").classes("min-w-0") \
                            .mark(f"beleg-datum-{r['id']}")
                        datum.on("blur", lambda e, i=r["id"], f=datum:
                                 receipts.update_receipt(i, datum=f.value or ""))
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.icon("sell").classes("text-slate-400 text-sm shrink-0")
                        kat = ui.select({"": t("— Kategorie wählen —"),
                                         **{k: k for k in buchhaltung.kategorien(CFG)}},
                                        value=r.get("kategorie") or "") \
                            .props("dense borderless options-dense").classes("min-w-0 flex-grow") \
                            .mark(f"beleg-kategorie-{r['id']}")
                        def _kategorie_gesetzt(e, beleg=r):
                            # Die Zuordnung von Hand ist der Lernmoment: beim
                            # nächsten Beleg desselben Händlers steht die
                            # Kategorie schon da (AP15).
                            receipts.update_receipt(
                                beleg["id"], kategorie=e.value or "",
                                klasse=buchhaltung.klasse_fuer(e.value))
                            k = stammdaten.kategorie_lernen(
                                beleg.get("merchant"), e.value or "",
                                beleg.get("apartment_id"))
                            if k:
                                receipts.update_receipt(beleg["id"], kreditor_id=k["id"])
                            hinweis = (t("Kategorie gesetzt ✓ – für {name} gemerkt",
                                         name=k["name"]) if k
                                       else t("Kategorie gesetzt ✓"))
                            ui.notify(hinweis, type="positive", timeout=1500)

                        kat.on_value_change(_kategorie_gesetzt)
                else:
                    ui.label(_d(buchhaltung.belegdatum(r))).classes("text-xs text-slate-400")
                ui.label(f"{t('erfasst')} {_d(r['ts'])} · {r.get('uploader', '')}") \
                    .classes("text-xs text-slate-400")
                if bucht:
                    _bewegungszeile(r, rerender)
                note = ui.input(placeholder=t("Notiz (z. B. wofür)"),
                                value=r.get("note", "")).props("dense borderless").classes("w-full")
                note.on("blur", lambda e, i=r["id"], f=note:
                        receipts.update_receipt(i, note=f.value or ""))
                if zu:
                    with ui.row().classes("w-full items-center gap-1 no-wrap text-slate-400"):
                        ui.icon("lock").classes("text-sm shrink-0")
                        ui.label(t("Monat ist abgeschlossen – Änderungen wirken nicht "
                                   "mehr im Export.")).classes("text-xs")
            with ui.column().classes("items-center gap-1 shrink-0"):
                if r.get("pdf"):
                    ui.button(icon="picture_as_pdf",
                              on_click=lambda p=r["pdf"]: ui.navigate.to(f"/media/{p}", new_tab=True)) \
                        .props("flat round dense color=primary").tooltip(t("PDF öffnen"))
                if darf_loeschen:
                    ui.button(icon="delete", on_click=lambda i=r["id"]: _del_beleg(i, rerender)) \
                        .props("flat round dense color=negative").tooltip(t("Beleg löschen"))
        if r.get("ocr_text"):
            with ui.expansion(t("Erkannter Text (OCR)"), icon="document_scanner").classes("w-full"):
                ui.label(r["ocr_text"]).classes("text-xs whitespace-pre-wrap text-slate-600")


async def _stapel_verarbeiten(dateien, einzeln):
    """Mehrere Belege nacheinander verarbeiten. Gibt (fertig, fehler) zurück.

    **Nacheinander, nicht gleichzeitig:** Zuschnitt, PDF und OCR laufen im
    Thread-Pool; zehn davon parallel bringen den Server eher zum Stocken, als
    dass sie Zeit sparten.

    **Ein Fehler stoppt den Stapel nicht.** Sonst verhinderte eine unlesbare
    Datei in der Mitte alles Nachfolgende – und man wüsste hinterher nicht,
    welche Belege angekommen sind.

    `einzeln(datei, nr, gesamt)` gibt (ergebnis, fehlertext) zurück.
    """
    fertig, fehler = 0, []
    for i, datei in enumerate(dateien, 1):
        try:
            _doc, problem = await einzeln(datei, i, len(dateien))
        except Exception as ex:                # noqa: BLE001 – ein Beleg darf
            problem = str(ex)                  # den Stapel nicht abbrechen
        if problem:
            fehler.append(problem)
        else:
            fertig += 1
    return fertig, fehler


def _bewegungszeile(r, rerender):
    """Zu welcher Bankbewegung gehört dieser Beleg – und wenn zu keiner: welche
    käme in Frage? (B5a/B5d)

    **Die Richtung aus dem Alltag.** Jemand fotografiert eine Quittung; die
    Abbuchung steht längst im Auszug. Ohne diese Zeile blieb der Beleg für die
    Buchhaltung unsichtbar und wanderte womöglich ein zweites Mal ins System.

    Ein Beleg darf an **mehreren** Bewegungen hängen – der Monatsbeleg eines
    Portals gehört an jede Auszahlung des Monats.
    """
    from app import konto, zuordnung
    ids = zuordnung.bewegungen_zu(zuordnung.BELEG, r["id"])
    if ids:
        verteilt, soll, stimmt = belegzuordnung.belegprobe(r)
        for bid in dict.fromkeys(ids):
            b = konto.holen(bid)
            if not b:
                continue
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                ui.icon("account_balance").classes(f"text-sm shrink-0 {ton.ERFOLG}")
                ui.label(f"{_d(b.get('datum'))} · {b.get('gegenpartei') or '—'} · "
                         f"{buchhaltung.betrag_text(b.get('betrag', 0))} €") \
                    .classes("text-xs truncate")
                ui.button(icon="link_off",
                          on_click=lambda i=bid: (konto.beleg_loesen(i, r["id"]),
                                                  rerender())) \
                    .props("flat dense round").classes(f"{ton.ZART} shrink-0") \
                    .tooltip(t("Von dieser Bewegung lösen"))
        if soll is not None and not stimmt:
            # Nur beim verteilten Beleg eine Aussage: sonst wäre jede
            # Rundungsdifferenz eine Warnung.
            ui.label(t("Verteilt: {v} von {s} – der Rest fehlt noch.",
                       v=f"{buchhaltung.betrag_text(verteilt)} €",
                       s=f"{buchhaltung.betrag_text(soll)} €")) \
                .classes(f"text-xs {ton.AUF_HINWEIS}")
        return

    alle_k = belegzuordnung.bewegungen_zu(r)
    if not alle_k:
        ui.label(t("Noch keiner Bankbewegung zugeordnet.")) \
            .classes(f"text-xs {ton.AUF_HINWEIS}")
        return

    def zuordnen(bid, dlg):
        erfolg = konto.beleg_anhaengen(bid, r["id"])
        dlg.close()
        if erfolg is None:
            ui.notify(t("Dazu fehlt an der Bewegung noch die gegengebuchte "
                        "Provision – erst im Konto gegenbuchen."),
                      type="warning", timeout=8000)
        else:
            ui.notify(t("Beleg der Bewegung zugeordnet ✓"), type="positive")
        rerender()

    def oeffnen():
        with ui.dialog() as dlg, ui.card().classes("w-[560px] max-w-full gap-2"):
            ui.label(t("Passende Bankbewegung wählen")).classes("font-medium")
            ui.label(t("Wahrscheinlichste zuerst – sortiert nach Empfänger und "
                       "Datum. Der Betrag ist nur ein Hinweis: von den "
                       "vorhandenen Belegen trägt kaum einer einen.")) \
                .classes(f"text-xs {ton.STILL}")
            # ALLE Ausgaben stehen zur Wahl, nicht die ersten acht. Eine
            # Vorauswahl half nur, solange die richtige Bewegung zufaellig
            # oben stand – wer weiss, wohin sein Beleg gehoert, muss sie
            # finden koennen. Statt eines Deckels: suchen und scrollen.
            liste = ui.column().classes("w-full gap-1")

            def zeichnen(suche=""):
                treffer = belegzuordnung.filtern(alle_k, suche)
                liste.clear()
                with liste:
                    ui.label(t("{n} von {g} Bewegungen", n=len(treffer),
                               g=len(alle_k))).classes(f"text-xs {ton.STILL}")
                    if not treffer:
                        ui.label(t("Nichts gefunden – Suchbegriff ändern.")) \
                            .classes(f"text-xs {ton.AUF_HINWEIS}")
                    with ui.scroll_area().classes("w-full h-[320px]"):
                        for k in treffer:
                            b = k["bewegung"]
                            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                                with ui.column().classes("gap-0 min-w-0 flex-grow"):
                                    ui.label(b.get("gegenpartei") or "—") \
                                        .classes("text-sm truncate")
                                    ui.label(f"{_d(b.get('datum'))} · {k['grund']}") \
                                        .classes(f"text-xs {ton.STILL} truncate")
                                ui.label(f"{buchhaltung.betrag_text(b.get('betrag', 0))} €") \
                                    .classes("text-sm w-24 text-right shrink-0")
                                ui.button(icon="add",
                                          on_click=lambda i=b["id"]: zuordnen(i, dlg)) \
                                    .props("flat dense round").mark(f"bz-add-{b['id']}")

            ui.input(placeholder=t("Suchen: Empfänger, Verwendungszweck, Datum, Betrag"),
                     on_change=lambda e: zeichnen(e.value)) \
                .props("dense outlined clearable").classes("w-full") \
                .mark(f"bz-suche-{r['id']}")
            zeichnen()
            ui.button(t("Schließen"), on_click=dlg.close).props("flat no-caps dense")
        dlg.open()

    with ui.row().classes("w-full items-center gap-1 no-wrap"):
        ui.label(t("Noch keiner Bankbewegung zugeordnet.")) \
            .classes(f"text-xs {ton.AUF_HINWEIS}")
        ui.button(t("Bewegung wählen"), icon="account_balance", on_click=oeffnen) \
            .props("flat dense no-caps size=sm").mark(f"bz-waehl-{r['id']}")


def _del_beleg(receipt_id, rerender):
    with ui.dialog() as dlg, ui.card().classes("gap-2"):
        ui.label(t("Beleg wirklich löschen?")).classes("font-medium")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Löschen"), on_click=lambda: (_beleg_weg(receipt_id),
                                                   dlg.close(),
                                                   ui.notify(t("Beleg gelöscht."), type="warning"),
                                                   rerender())) \
                .props("unelevated color=negative")
    dlg.open()


# ------------------------------------------------------ Monatsabschluss (AP10)
def _abschluss_ansicht(user, rerender):
    """Je Monat: was drin ist, was noch fehlt, und die beiden Ausgaben.

    Der Abschluss ist keine Formsache. Danach sind die Zahlen des Monats fest –
    eine Summe, die sich nachträglich noch bewegt, ist im Steuerbüro nichts
    wert. Deshalb geht er erst, wenn nichts mehr offen ist.
    """
    alle = receipts.list_receipts()
    monate = buchhaltung.monate(alle)
    if not monate:
        leer("event_available", t("Noch nichts abzuschließen."),
             t("Sobald Belege da sind, steht hier jeder Monat einzeln."))
        return
    for m in monate:
        belege = [b for b in alle if buchhaltung.monat(b) == m]
        _monatskarte(m, belege, user, rerender)


def _monatskarte(m, belege, user, rerender):
    befund = buchhaltung.pruefung(belege)
    abschluss = buchhaltung.abschluss_von(m)
    name = f"{_MONATE[int(m[5:7]) - 1]} {m[:4]}"
    with ui.card().classes(ton.KARTE_ENG).mark(f"monat-{m}"):
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.label(name).classes("text-lg font-bold text-slate-800")
            ui.space()
            if abschluss:
                ui.chip(t("abgeschlossen"), icon="lock") \
                    .props("color=green-7 text-color=white dense square").classes("text-xs")
            elif befund["abschliessbar"]:
                ui.chip(t("bereit"), icon="check_circle") \
                    .props("color=green-7 text-color=white dense square").classes("text-xs")
            else:
                ui.chip(t("offen"), icon="pending") \
                    .props("color=amber-7 text-color=white dense square").classes("text-xs")
        ui.label(t("{n} Belege · {summe} €", n=befund["anzahl"],
                   summe=buchhaltung.betrag_text(befund["summe"]))) \
            .classes("text-sm text-slate-600")

        if abschluss:
            ui.label(t("Abgeschlossen am {wann} von {wer}",
                       wann=_d(abschluss.get("wann", "")), wer=abschluss.get("wer", ""))) \
                .classes("text-xs text-slate-400")
        else:
            _befund_zeigen(befund)

        with ui.row().classes("w-full items-center gap-2 flex-wrap mt-1"):
            ui.button(t("CSV fürs Kontenjournal"), icon="table_view",
                      on_click=lambda: ui.download.content(
                          buchhaltung.csv_bytes(belege), f"belege_{m}.csv",
                          media_type="text/csv")) \
                .props("outline no-caps").mark(f"csv-{m}")
            ui.button(t("Sammelmappe (PDF)"), icon="picture_as_pdf",
                      on_click=lambda: _sammelmappe_laden(m, belege, name)) \
                .props("outline no-caps").mark(f"pdf-{m}")
            ui.space()
            if abschluss:
                ui.button(t("Wieder öffnen"), icon="lock_open",
                          on_click=lambda: (buchhaltung.oeffnen(m),
                                            protokoll.notieren(
                                                _cur_user(), protokoll.MONAT_GEOEFFNET, m,
                                                f"{befund['anzahl']} Belege, "
                                                f"{buchhaltung.betrag_text(befund['summe'])} €"),
                                            ui.navigate.reload())) \
                    .props("flat no-caps color=negative").mark(f"oeffnen-{m}")
            else:
                knopf = ui.button(
                    t("Monat abschließen"), icon="lock",
                    on_click=lambda: _abschliessen(m, belege, user, name, rerender)) \
                    .props("unelevated no-caps").mark(f"abschliessen-{m}")
                if not befund["abschliessbar"]:
                    knopf.disable()
                    knopf.tooltip(t("Erst klären, was oben offen steht."))


def _befund_zeigen(befund):
    """Was den Abschluss aufhält – benannt, nicht gezählt. „3 Probleme" schickt
    einen suchen; „Rossmann 27,81 € zweimal" nicht."""
    if befund["abschliessbar"]:
        return
    with ui.column().classes(f"w-full gap-1 rounded-lg p-2 {ton.FLAECHE_HINWEIS}"):
        for beleg, felder in befund["unvollstaendig"]:
            _befundzeile("edit_note",
                         t("{haendler}: es fehlt {felder}",
                           haendler=(beleg.get("merchant") or t("ohne Händler")),
                           felder=", ".join(felder)))
        for beleg in befund["unklar"]:
            _befundzeile("help_outline",
                         t("{haendler}: Kategorie noch ungeklärt",
                           haendler=(beleg.get("merchant") or t("ohne Händler"))))
        for gruppe in befund["dubletten"]:
            b = gruppe[0]
            _befundzeile("content_copy",
                         t("{haendler} {betrag} € steht {n}× am selben Tag – doppelt erfasst?",
                           haendler=(b.get("merchant") or t("ohne Händler")),
                           betrag=b.get("amount", ""), n=len(gruppe)))


def _befundzeile(icon, text):
    with ui.row().classes(f"w-full items-start gap-2 no-wrap {ton.AUF_HINWEIS}"):
        ui.icon(icon).classes("text-sm shrink-0 mt-0.5")
        ui.label(text).classes("text-xs")


def _sammelmappe_laden(m, belege, name):
    try:
        zeilen = buchhaltung.journal_zeilen(belege)
        sortiert = sorted(belege, key=buchhaltung.belegdatum)
        roh = receipts.sammelmappe(sortiert, t("Belege {monat}", monat=name), zeilen)
    except Exception as ex:
        ui.notify(t("Sammelmappe fehlgeschlagen: {fehler}", fehler=ex),
                  type="negative", timeout=9000)
        return
    ui.download.content(roh, f"belege_{m}.pdf", media_type="application/pdf")


def _abschliessen(m, belege, user, name, rerender):
    try:
        buchhaltung.abschliessen(m, belege, user)
    except ValueError:
        ui.notify(t("Es steht noch etwas offen – siehe oben."), type="warning")
        return
    ui.navigate.reload()


def _beleg_weg(receipt_id):
    """Löschen und festhalten, wer es war – ein Beleg ist ein Beweismittel."""
    weg = receipts.list_receipts()
    weg = next((r for r in weg if r["id"] == receipt_id), {})
    receipts.delete_receipt(receipt_id)
    protokoll.notieren(
        _cur_user(), protokoll.BELEG_GELOESCHT, receipt_id,
        f"{weg.get('merchant') or '?'} · {weg.get('amount') or '?'} € · "
        f"{buchhaltung.belegdatum(weg) if weg else '?'}")
