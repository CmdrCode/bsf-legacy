#!/usr/bin/env python3
"""Live preview: watch a ship file, serve its scene, draw it in a browser.

The page is a **blitter over the same scene the PIL renderer consumes**, so the
two views cannot disagree about geometry, ordering or colour -- only about how a
rotated bitmap is resampled. Everything else was decided once, in `scene.py`.

The file is the bus. This server neither owns nor locks the ship: it polls for a
content change and pushes a new scene, so an edit from the CLI and a save from
ShipMaker look identical to it.

    GET /              the page
    GET /scene.json    the draw list, sprites inlined as data URIs
    GET /version       cheap poll: content hash + mtime
"""
from __future__ import annotations

import hashlib
import http.server
import json
import pathlib
import socketserver
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import model   # noqa: E402
import scene   # noqa: E402

#: Canvas draws with GM's conventions: y down, image_angle counterclockwise.
#: ctx.rotate is clockwise in a y-down frame, hence the negation below -- the one
#: place the two blitters differ in expression rather than in result.
PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__NAME__ — ship preview</title>
<style>
  :root{--bg:#05070a;--fg:#cfe6cf;--dim:#7d8f7d;--line:#26331f;--warn:#ff6b60}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
       display:flex;flex-direction:column;height:100vh;overflow:hidden}
  header{padding:9px 14px;border-bottom:1px solid var(--line);
         display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
  h1{margin:0;font-size:14px;letter-spacing:.14em;text-transform:uppercase}
  .stat{color:var(--dim)} .stat b{color:var(--fg);font-weight:600}
  main{flex:1;position:relative;min-height:0}
  canvas{position:absolute;inset:0;width:100%;height:100%;display:block;cursor:crosshair}
  #hud{position:absolute;left:12px;bottom:12px;pointer-events:none;
       background:rgba(5,7,10,.85);border:1px solid var(--line);border-radius:5px;
       padding:7px 10px;min-width:230px}
  #hud.empty{display:none}
  #hud b{color:#62e07d}
  footer{border-top:1px solid var(--line);padding:8px 14px;
         display:flex;gap:16px;align-items:center;flex-wrap:wrap}
  label{display:flex;gap:6px;align-items:center;cursor:pointer;white-space:nowrap}
  input[type=range]{width:120px;accent-color:#62e07d}
  kbd{border:1px solid var(--line);border-radius:3px;padding:0 4px;color:var(--dim)}
  #live{color:var(--dim)} #live.on{color:#62e07d}
  .warn{color:var(--warn)}
</style></head><body>
<header>
  <h1 id="nm">—</h1>
  <span class="stat">sections <b id="ns">0</b></span>
  <span class="stat">weapons <b id="nw">0</b></span>
  <span class="stat">modules <b id="nm2">0</b></span>
  <span class="stat">doodads <b id="nd">0</b></span>
  <span class="stat">size <b id="sz">—</b></span>
  <span class="stat" id="notes"></span>
  <span class="stat" style="margin-left:auto">rev <b id="rev">—</b></span>
  <span id="live">●</span>
</header>
<main><canvas id="c"></canvas><div id="hud" class="empty"></div></main>
<footer>
  <label>zoom <input type="range" id="zoom" min="1" max="16" step="0.5" value="4"></label>
  <label><input type="checkbox" id="bridge" checked> bridge</label>
  <label><input type="checkbox" id="mounts"> mounts</label>
  <label><input type="checkbox" id="ids"> ids</label>
  <label><input type="checkbox" id="axes"> centreline</label>
  <span class="stat"><kbd>drag</kbd> pan · <kbd>wheel</kbd> zoom · <kbd>hover</kbd> inspect</span>
</footer>
<script>
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
const ui=id=>document.getElementById(id);
let SC=null,IMGS={},pan={x:0,y:0},drag=null,hover=null,rev='';

function fit(){const r=cv.getBoundingClientRect(),d=devicePixelRatio||1;
  cv.width=r.width*d;cv.height=r.height*d;draw();}
addEventListener('resize',fit);

async function loadScene(){
  const sc=await (await fetch('scene.json',{cache:'no-store'})).json();
  const need=Object.entries(sc.sprites).filter(([k])=>!IMGS[k]);
  await Promise.all(need.map(([k,src])=>new Promise(res=>{
    const im=new Image();im.onload=()=>{IMGS[k]=im;res()};im.onerror=res;im.src=src;})));
  SC=sc;
  ui('nm').textContent=sc.name;ui('ns').textContent=sc.counts.section;
  ui('nw').textContent=sc.counts.weapon;ui('nm2').textContent=sc.counts.module;
  ui('nd').textContent=sc.counts.doodad||0;
  const b=sc.bbox;ui('sz').textContent=Math.round(b[2]-b[0])+'×'+Math.round(b[3]-b[1]);
  const msgs=[...sc.notes,...(sc.missing.length?['unresolved: '+sc.missing.join(', ')]:[])];
  ui('notes').innerHTML=msgs.length?'<span class="warn">'+msgs.join(' · ')+'</span>':'';
  draw();
}

function visible(){const b=ui('bridge').checked;
  return SC.ops.filter(o=>b||o.kind!=='bridge');}

// A section is a two-tone mask multiplied by its colour. That multiply has to
// happen OFF-SCREEN: 'destination-in' composites against the whole canvas, not
// against the sprite being drawn, so tinting in place erases everything painted
// earlier and only the last masked op survives. Cached per sprite+colour, so
// each combination is built once.
const TINT={};
function tinted(o){
  const key=o.spr+'|'+o.blend;
  if(TINT[key])return TINT[key];
  const im=IMGS[o.spr];
  const c=document.createElement('canvas');c.width=o.w;c.height=o.h;
  const x=c.getContext('2d');
  x.drawImage(im,0,0,o.w,o.h,0,0,o.w,o.h);
  x.globalCompositeOperation='multiply';
  x.fillStyle=o.blend;x.fillRect(0,0,o.w,o.h);
  x.globalCompositeOperation='destination-in';
  x.drawImage(im,0,0,o.w,o.h,0,0,o.w,o.h);
  TINT[key]=c;return c;
}

function place(o,z,cx,cy){
  ctx.save();
  ctx.translate(cx+o.x*z+pan.x, cy+o.y*z+pan.y);
  ctx.rotate(-o.ang*Math.PI/180);          // GM angle is CCW; canvas is CW
  ctx.scale(o.xs*z, o.ys*z);
  return ()=>ctx.restore();
}

function draw(){
  const z=parseFloat(ui('zoom').value);
  ctx.setTransform(1,0,0,1,0,0);
  ctx.fillStyle='#05070a';ctx.fillRect(0,0,cv.width,cv.height);
  if(!SC)return;
  const d=devicePixelRatio||1;ctx.scale(d,d);
  const cx=cv.width/d/2, cy=cv.height/d/2;

  if(ui('axes').checked){
    ctx.strokeStyle='#26331f';ctx.lineWidth=1;ctx.beginPath();
    ctx.moveTo(0,cy+pan.y);ctx.lineTo(cv.width,cy+pan.y);
    ctx.moveTo(cx+pan.x,0);ctx.lineTo(cx+pan.x,cv.height);ctx.stroke();
  }
  ctx.imageSmoothingEnabled=z<3;
  for(const o of visible()){
    const im=IMGS[o.spr];if(!im)continue;
    const done=place(o,z,cx,cy);
    ctx.globalAlpha=(o.alpha??1)*(hover!==null&&hover!==o.id?0.35:1);
    const src=(o.mask&&o.blend!=='#FFFFFF')?tinted(o):im;
    ctx.drawImage(src,0,0,o.w,o.h,-o.ox,-o.oy,o.w,o.h);
    done();
  }
  ctx.globalAlpha=1;

  if(ui('mounts').checked)for(const o of SC.ops){
    if(o.kind!=='weapon'&&o.kind!=='module')continue;
    ctx.strokeStyle='#ff6b60';ctx.beginPath();
    ctx.arc(cx+o.x*z+pan.x,cy+o.y*z+pan.y,3,0,7);ctx.stroke();
  }
  if(ui('ids').checked){ctx.fillStyle='#7d8f7d';ctx.font='9px ui-monospace,monospace';
    for(const o of SC.ops)if(o.kind==='section')
      ctx.fillText(o.id,cx+o.x*z+pan.x+2,cy+o.y*z+pan.y-2);}
}

// Hover picks the topmost op whose rotated local box contains the cursor --
// the same transform the blitter uses, inverted.
function pick(mx,my){
  const z=parseFloat(ui('zoom').value),d=devicePixelRatio||1;
  const cx=cv.width/d/2, cy=cv.height/d/2;
  const ops=visible();
  for(let i=ops.length-1;i>=0;i--){
    const o=ops[i];
    const dx=(mx-cx-pan.x)/z-o.x, dy=(my-cy-pan.y)/z-o.y;
    const a=-o.ang*Math.PI/180;
    let lx=dx*Math.cos(a)+dy*Math.sin(a), ly=-dx*Math.sin(a)+dy*Math.cos(a);
    lx/=o.xs; ly/=o.ys;
    if(Math.abs(lx)<=o.w/2&&Math.abs(ly)<=o.h/2)return o;
  }
  return null;
}

cv.addEventListener('mousemove',e=>{
  const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  if(drag){pan.x=drag.px+mx-drag.mx;pan.y=drag.py+my-drag.my;draw();return;}
  const o=pick(mx,my),h=ui('hud');
  hover=o?o.id:null;
  if(!o){h.className='empty';draw();return;}
  h.className='';
  h.innerHTML=`<b>${o.kind} ${o.id}</b> ${o.name}<br>`+
    `pos ${o.x.toFixed(2)}, ${o.y.toFixed(2)}${o.y<0?' (up)':''}<br>`+
    `ang ${o.ang}°  flip ${o.xs<0?'X':'-'}${o.ys<0?'Y':'-'}  depth ${o.z}<br>`+
    (o.parent!==undefined?`parent ${o.parent||'core'}  mirror ${o.mirror??'—'}<br>`:'')+
    `<span style="color:${o.blend}">■</span> ${o.blend}`;
  draw();
});
cv.addEventListener('mouseleave',()=>{hover=null;ui('hud').className='empty';draw()});
cv.addEventListener('mousedown',e=>{const r=cv.getBoundingClientRect();
  drag={mx:e.clientX-r.left,my:e.clientY-r.top,px:pan.x,py:pan.y}});
addEventListener('mouseup',()=>drag=null);
cv.addEventListener('wheel',e=>{e.preventDefault();
  const zi=ui('zoom');zi.value=Math.max(1,Math.min(16,+zi.value-Math.sign(e.deltaY)*0.5));
  draw();},{passive:false});
for(const id of ['zoom','bridge','mounts','ids','axes'])ui(id).addEventListener('input',draw);

async function poll(){
  try{
    const v=await (await fetch('version',{cache:'no-store'})).json();
    ui('live').className='on';
    if(v.rev!==rev){rev=v.rev;ui('rev').textContent=v.rev.slice(0,7);await loadScene();}
  }catch(e){ui('live').className='';}
  setTimeout(poll,600);
}
fit();poll();
</script></body></html>'''


class Handler(http.server.BaseHTTPRequestHandler):
    path_ref: pathlib.Path
    lock = threading.Lock()

    def log_message(self, *a):                                  # quiet
        pass

    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                           # noqa: N802
        route = self.path.split('?')[0].lstrip('/')
        try:
            if route in ('', 'index.html'):
                name = self.path_ref.stem
                self._send(PAGE.replace('__NAME__', name).encode(), 'text/html; charset=utf-8')
            elif route == 'version':
                raw = self.path_ref.read_bytes()
                self._send(json.dumps({
                    'rev': hashlib.sha256(raw).hexdigest()[:12],
                    'mtime': self.path_ref.stat().st_mtime,
                }).encode(), 'application/json')
            elif route == 'scene.json':
                with self.lock:
                    sc = scene.for_web(scene.build(model.load(self.path_ref)))
                self._send(json.dumps(sc).encode(), 'application/json')
            else:
                self.send_error(404)
        except FileNotFoundError:
            self.send_error(404, 'ship file is gone')
        except Exception as e:                                  # noqa: BLE001
            self.send_error(500, f'{type(e).__name__}: {e}')


def run(path: pathlib.Path, bind: str = '127.0.0.1', port: int = 8771) -> int:
    Handler.path_ref = path.resolve()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((bind, port), Handler) as srv:
        print(f'watching {path.name}  ->  http://{bind}:{port}/')
        print('the page follows the file, whoever writes it — Ctrl-C to stop')
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print('\nstopped')
    return 0


if __name__ == '__main__':
    raise SystemExit(run(pathlib.Path(sys.argv[1]),
                         sys.argv[2] if len(sys.argv) > 2 else '127.0.0.1',
                         int(sys.argv[3]) if len(sys.argv) > 3 else 8771))
