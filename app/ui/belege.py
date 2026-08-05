"""Belege: Scanner (Kamera + Ecken ziehen), Ablage, OCR, Liste.

Bewusst ohne automatische Kantenerkennung im Browser – der Versuch mit
OpenCV.js traf Belege zu unzuverlaessig und lud 10 MB WebAssembly (siehe README).
"""

import os
import base64
from nicegui import ui
from app import housekeeping, mode, receipts
from app.ui.basis import (CFG, _MONATE, _apts, _cur_user, _d, _esc_attr, _is_admin, _photo_thumb, _read_upload, t)

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
    admin = _is_admin()
    with ui.row().classes("w-full items-center gap-3"):
        ui.icon("receipt").classes("text-3xl text-primary")
        with ui.column().classes("gap-0"):
            ui.label(t("Belege")).classes("text-2xl font-bold text-slate-800 leading-tight")
            ui.label(t("Rechnungen scannen, ablegen & per OCR auslesen")) \
                .classes("text-sm text-gray-500")

    apts = _apts()
    sc = {"apt": None, "dlg": None}

    def _process_and_add(data, ext, crop, corners=None):
        """Beleg-Bytes -> Dokument/PDF + OCR + Datensatz (blockierender Teil).

        corners: die im Scanner gesetzten Ecken (Anteile 0..1); sie haben
        Vorrang vor der automatischen Erkennung."""
        doc = receipts.save_document(data, ext, _beleg_mirror(), crop, corners)
        try:
            text = receipts.ocr_image(os.path.join(housekeeping.MEDIA_DIR, doc["photo"]))
        except Exception:
            text = ""
        aid = sc["apt"]
        receipts.add_receipt(user, doc["photo"], ocr_text=text,
                             amount=receipts.guess_amount(text),
                             merchant=receipts.guess_merchant(text), pdf=doc.get("pdf"),
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
                    render()
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
                    .classes("text-[11px] text-gray-500 text-center")
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

    box = ui.column().classes("w-full gap-3")

    def render():
        box.clear()
        with box:
            # Upload-Karte
            with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-2 p-4"):
                ui.label(t("Neuen Beleg hinzufügen")).classes("font-medium")
                ui.label(t("Live scannen (Rand wird erkannt) oder Foto/Datei wählen. "
                   "Das Dokument wird als PDF abgelegt und per OCR ausgelesen.")) \
                    .classes("text-xs text-gray-500")
                apt_sel = ui.select({None: t("— keine Wohnung —"), **apts}, value=sc["apt"],
                                    label=t("Für welche Wohnung?")).props("outlined dense") \
                    .classes("min-w-[220px]")
                apt_sel.on_value_change(lambda e: sc.update(apt=e.value))

                async def handle(e):
                    try:
                        content, name = await _read_upload(e)
                    except Exception as ex:
                        ui.notify(t("Upload fehlgeschlagen: {fehler}", fehler=ex), type="negative"); return
                    ext = (name.rsplit(".", 1)[-1] if "." in name else "jpg").lower()[:4] or "jpg"
                    ui.notify(t("Beleg wird verarbeitet (Zuschnitt, PDF, OCR) …"), type="info", timeout=4000)
                    from nicegui import run
                    doc = await run.io_bound(_process_and_add, content, ext, True)
                    ui.notify(t("Beleg erfasst ✓") + (t(" (als PDF)") if doc.get("pdf") else ""),
                              type="positive")
                    render()

                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    ui.button(t("Beleg scannen"), icon="document_scanner", on_click=_open_scanner) \
                        .props("unelevated no-caps").mark("scan-open")
                    ui.upload(auto_upload=True, on_upload=handle, label=t("Foto / Datei")) \
                        .props('accept="image/*"').classes("hk-upload max-w-[220px]")
                if not receipts.ocr_available():
                    ui.label(t("Hinweis: OCR (Tesseract) ist auf dem Server nicht installiert – "
                       "Belege werden gespeichert, aber nicht automatisch ausgelesen.")) \
                        .classes("text-xs text-amber-700")

            items = receipts.list_receipts()
            if not items:
                ui.label(t("Noch keine Belege abgelegt.")).classes("text-gray-500 mt-2")
                return
            cur_month = None
            for r in items:
                month = r["ts"][:7]
                if month != cur_month:
                    cur_month = month
                    ym = f"{_MONATE[int(month[5:7]) - 1]} {month[:4]}"
                    ui.label(ym).classes("text-sm font-semibold text-primary mt-3")
                _beleg_card(r, apts, user, admin, render)
    render()


def _beleg_card(r, apts, user, admin, rerender):
    with ui.card().classes("w-full rounded-xl shadow-sm border border-slate-100 gap-2 p-3"):
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
                    ui.label("€").classes("text-sm text-gray-400")
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.icon("home").classes("text-gray-400 text-sm shrink-0")
                    apt_sel = ui.select({None: "— keine Wohnung —", **apts},
                                        value=r.get("apartment_id")).props("dense borderless") \
                        .classes("min-w-0")
                    apt_sel.on_value_change(lambda e, i=r["id"]:
                                            receipts.update_receipt(i, apartment_id=e.value,
                                                                    apartment_name=apts.get(e.value, "")))
                ui.label(f"{_d(r['ts'])} · {r.get('uploader', '')}").classes("text-xs text-gray-400")
                note = ui.input(placeholder=t("Notiz (z. B. wofür)"),
                                value=r.get("note", "")).props("dense borderless").classes("w-full")
                note.on("blur", lambda e, i=r["id"], f=note:
                        receipts.update_receipt(i, note=f.value or ""))
            with ui.column().classes("items-center gap-1 shrink-0"):
                if r.get("pdf"):
                    ui.button(icon="picture_as_pdf",
                              on_click=lambda p=r["pdf"]: ui.navigate.to(f"/media/{p}", new_tab=True)) \
                        .props("flat round dense color=primary").tooltip(t("PDF öffnen"))
                if admin:
                    ui.button(icon="delete", on_click=lambda i=r["id"]: _del_beleg(i, rerender)) \
                        .props("flat round dense color=negative").tooltip(t("Beleg löschen"))
        if r.get("ocr_text"):
            with ui.expansion(t("Erkannter Text (OCR)"), icon="document_scanner").classes("w-full"):
                ui.label(r["ocr_text"]).classes("text-xs whitespace-pre-wrap text-gray-600")


def _del_beleg(receipt_id, rerender):
    with ui.dialog() as dlg, ui.card().classes("gap-2"):
        ui.label(t("Beleg wirklich löschen?")).classes("font-medium")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(t("Abbrechen"), on_click=dlg.close).props("flat")
            ui.button(t("Löschen"), on_click=lambda: (receipts.delete_receipt(receipt_id),
                                                   dlg.close(),
                                                   ui.notify(t("Beleg gelöscht."), type="warning"),
                                                   rerender())) \
                .props("unelevated color=negative")
    dlg.open()
