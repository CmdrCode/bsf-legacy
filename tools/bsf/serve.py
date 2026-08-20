#!/usr/bin/env python3
"""Live preview: watch a set of ship files, serve their scenes, draw them in a
browser.

The page is a **blitter over the same scene the PIL renderer consumes**, so the
two views cannot disagree about geometry, ordering or colour -- only about how a
rotated bitmap is resampled. Everything else was decided once, in `scene.py`.

The files are the bus. This server neither owns nor locks a ship: it rescans its
roots and polls for content changes, so an edit from the CLI and a save from
ShipMaker look identical to it. It also owns no *selection* -- the hull on show
is named in the URL, so two browsers can watch two hulls on the one port and a
URL handed to someone means the same hull tomorrow.

    GET /                      the page
    GET /index[?ship=KEY]      the ship list, plus the selected hull's hash
    GET /scene.json?ship=KEY   the draw list, sprites inlined as data URIs

A KEY is `<root-index>/<filename>` and is resolved **only** by lookup in the
current scan, never by joining it onto a directory: an unknown key is a 404
rather than something traversal has to be defended against. That matters
because the page is meant to be handed to someone watching: by default it
listens on loopback *and*, when Tailscale is up, on the tailnet address, so the
URL it prints works from a phone or a second machine without opening anything
to the local network.
"""
from __future__ import annotations

import hashlib
import http.server
import ipaddress
import json
import pathlib
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import model   # noqa: E402
import paths   # noqa: E402
import scene   # noqa: E402

#: What the dropdown lists. `.sb4` is the editable source and `.shp` is what the
#: game actually loads, so both belong on the page -- a `.shp` that has fallen
#: behind its `.sb4` is a real bug, and it is only visible if both are shown.
#: ShipMaker's `.txt` description sidecars are not ships and never appear.
SUFFIXES = ('.sb4', '.shp')


# --------------------------------------------------------------------------
# the index
# --------------------------------------------------------------------------

#: Display names, keyed by path and invalidated by (mtime, size). Reading the
#: `nShp` name of all 17 hulls in the default roots measures 0.9 ms warm, so
#: this cache is about not doing it 1.7 times a second, not about affordability.
_NAMES: dict[str, tuple[tuple, str]] = {}


def _display_name(p: pathlib.Path, stamp: tuple) -> str:
    hit = _NAMES.get(str(p))
    if hit is not None and hit[0] == stamp:
        return hit[1]
    try:
        name = model.load(p).name
    except Exception:                                # noqa: BLE001
        name = p.stem                                # unparseable: still listable
    _NAMES[str(p)] = (stamp, name)
    return name


def default_roots() -> list[pathlib.Path]:
    """The two places hulls are worked on: this repo's, and ShipMaker's."""
    return [r for r in (paths.SHIPS, paths.GAME / 'Custom Ships') if r.is_dir()]


def resolve_roots(targets: list[str],
                  extra: list[str] | None = None
                  ) -> tuple[list[pathlib.Path], pathlib.Path | None]:
    """(roots, the file to select first) from the command line.

    A named directory is a root; a named file contributes its parent as a root
    and, if it is the first one named, becomes the initial selection. Naming
    anything at all replaces the defaults, so `ship serve mods/ships/` shows
    those hulls and nothing leaks in from the game folder.
    """
    roots: list[pathlib.Path] = []
    first: pathlib.Path | None = None
    for t in targets:
        p = pathlib.Path(t).expanduser()
        if p.is_dir():
            roots.append(p.resolve())
        else:
            if not p.exists():
                raise FileNotFoundError(t)
            if first is None:
                first = p.resolve()
            roots.append(p.resolve().parent)
    for e in extra or []:
        roots.append(pathlib.Path(e).expanduser().resolve())
    if not roots:
        roots = default_roots()
    seen, out = set(), []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out, first


def _labels(roots: list[pathlib.Path]) -> list[str]:
    """A short name per root -- repo-relative inside the checkout, else the
    directory's own name. Never absolute: the page is served over `--bind`, and
    a full path names the account it sits under."""
    out = []
    for r in roots:
        try:
            out.append(str(r.relative_to(paths.REPO)))
        except ValueError:
            out.append(r.name)
    for i, lab in enumerate(out):                    # disambiguate collisions
        if out.count(lab) > 1:
            out[i] = f'{roots[i].parent.name}/{lab}'
    return out


class Index:
    """The set of hulls on offer, rebuilt from disk on demand.

    Absolute paths live here and *only* here -- `entries` is what goes over the
    wire, so it cannot carry one by construction.
    """

    def __init__(self, roots: list[pathlib.Path],
                 first: pathlib.Path | None = None):
        self.roots = roots
        self.labels = _labels(roots)
        self.first = first
        self.entries: list[dict] = []
        self.paths: dict[str, pathlib.Path] = {}
        self.rescan()

    def rescan(self) -> None:
        entries: list[dict] = []
        paths_: dict[str, pathlib.Path] = {}
        for ri, root in enumerate(self.roots):
            try:                                     # one level: both roots are flat
                files = [p for p in root.iterdir()
                         if p.is_file() and p.suffix.lower() in SUFFIXES]
            except OSError:
                continue
            fams: dict[str, dict[str, pathlib.Path]] = {}
            for p in files:
                fams.setdefault(p.stem, {})[p.suffix.lower()] = p
            for stem in sorted(fams, key=str.lower):
                sb4, shp = fams[stem].get('.sb4'), fams[stem].get('.shp')
                src = None
                if sb4 is not None:
                    src = self._entry(ri, sb4)
                    entries.append(src)
                    paths_[src['key']] = sb4
                if shp is not None:
                    e = self._entry(ri, shp, pair=src['key'] if src else None)
                    if src is not None:
                        # The export is behind its source: rule 20 made visible.
                        e['stale'] = e['stamp'][0] < src['stamp'][0]
                    entries.append(e)
                    paths_[e['key']] = shp
        self.entries, self.paths = entries, paths_
        self.by_key = {e['key']: e for e in entries}

    @staticmethod
    def _entry(ri: int, p: pathlib.Path, pair: str | None = None) -> dict:
        st = p.stat()
        stamp = [round(st.st_mtime, 3), st.st_size]
        return {
            'key': f'{ri}/{p.name}',
            'file': p.name,
            'kind': p.suffix.lower().lstrip('.'),
            'group': ri,
            'name': _display_name(p, tuple(stamp)),
            'pair': pair,
            'stale': False,
            'stamp': stamp,
        }

    def default(self) -> str | None:
        """The hull a bare `/` shows: the file named on the command line, else
        the most recently saved one -- the honest reading of "being worked on"."""
        if self.first is not None:
            for key, p in self.paths.items():
                if p == self.first:
                    return key
        pool = [e for e in self.entries if e['kind'] == 'sb4'] or self.entries
        if not pool:
            return None
        return max(pool, key=lambda e: e['stamp'][0])['key']


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------

def _rev(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:12]


def resolve(route: str, query: dict, index: Index) -> tuple[int, str, bytes]:
    """One GET, without a socket in sight.

    Split out of the handler so the fiddly half -- key resolution, pairing,
    staleness, the 404 -- is testable directly. `selftest.py` calls this.
    """
    if route in ('', 'index.html'):
        return 200, 'text/html; charset=utf-8', PAGE.encode()

    want = (query.get('ship') or [None])[0]

    if route == 'index':
        index.rescan()
        sel = want if want in index.by_key else None
        gone = bool(want) and sel is None
        if sel is None:
            sel = index.default()
        rev = None
        if sel is not None:
            try:
                rev = _rev(index.paths[sel].read_bytes())
            except OSError:
                rev = None
        return 200, 'application/json', json.dumps({
            'roots': index.labels,
            'ships': index.entries,
            # `req` is the key this answer is *about*. A poll in flight when the
            # page switches hulls comes back naming the old one, and without
            # this the page would take that as authority and snap back.
            'req': want,
            'sel': sel,
            'gone': gone,
            'rev': rev,
        }).encode()

    if route == 'scene.json':
        if want not in index.by_key:
            index.rescan()                           # maybe it appeared just now
        if want not in index.by_key:
            return 404, 'application/json', json.dumps(
                {'error': f'no such ship: {want}'}).encode()
        p = index.paths[want]
        try:
            raw = p.read_bytes()
            sc = scene.for_web(scene.build(model.load(p)))
        except OSError as e:                         # deleted between scan and read
            return 404, 'application/json', json.dumps(
                {'error': f'{type(e).__name__}: {e}'}).encode()
        except Exception as e:                       # noqa: BLE001
            # One bad hull is one bad hull -- the server is fine and says so.
            # Note the model is lenient: junk content builds a bare core rather
            # than raising, so this path is for I/O and for our own bugs.
            return 500, 'application/json', json.dumps(
                {'error': f'{type(e).__name__}: {e}'}).encode()
        # The scene says which revision it *is*, so the page can tell an already
        # drawn hull from a changed one and skip a re-fetch it does not need.
        sc['rev'] = _rev(raw)
        return 200, 'application/json', json.dumps(sc).encode()

    return 404, 'text/plain; charset=utf-8', b'not found\n'


class Handler(http.server.BaseHTTPRequestHandler):
    index: Index
    lock = threading.Lock()

    def log_message(self, *a):                                  # quiet
        pass

    def do_GET(self):                                           # noqa: N802
        raw = self.path.split('?', 1)
        route = raw[0].lstrip('/')
        query = urllib.parse.parse_qs(raw[1]) if len(raw) > 1 else {}
        try:
            with self.lock:
                status, ctype, body = resolve(route, query, self.index)
        except Exception as e:                                  # noqa: BLE001
            status, ctype = 500, 'application/json'
            body = json.dumps({'error': f'{type(e).__name__}: {e}'}).encode()
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------

#: Canvas draws with GM's conventions: y down, image_angle counterclockwise.
#: ctx.rotate is clockwise in a y-down frame, hence the negation below -- the one
#: place the two blitters differ in expression rather than in result.
PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ship preview</title>
<style>
  :root{--bg:#05070a;--fg:#cfe6cf;--dim:#7d8f7d;--line:#26331f;--warn:#ff6b60}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
       display:flex;flex-direction:column;height:100vh;overflow:hidden}
  header{padding:9px 14px;border-bottom:1px solid var(--line);
         display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
  h1{margin:0;font-size:14px;letter-spacing:.14em;text-transform:uppercase}
  select{background:#0b0f14;color:var(--fg);border:1px solid var(--line);
         border-radius:4px;padding:3px 6px;font:inherit;max-width:60ch}
  select:focus{outline:1px solid #62e07d}
  .stat{color:var(--dim)} .stat b{color:var(--fg);font-weight:600}
  main{flex:1;position:relative;min-height:0}
  canvas{position:absolute;inset:0;width:100%;height:100%;display:block;cursor:crosshair}
  #hud{position:absolute;left:12px;bottom:12px;pointer-events:none;
       background:rgba(5,7,10,.85);border:1px solid var(--line);border-radius:5px;
       padding:7px 10px;min-width:230px}
  #hud.empty{display:none}
  #hud b{color:#62e07d}
  #err{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
       background:rgba(5,7,10,.94);border:1px solid var(--warn);border-radius:5px;
       padding:12px 16px;max-width:70ch;color:var(--warn)}
  #err.hide{display:none}
  #err b{display:block;color:var(--fg);margin-bottom:4px}
  footer{border-top:1px solid var(--line);padding:8px 14px;
         display:flex;gap:16px;align-items:center;flex-wrap:wrap}
  label{display:flex;gap:6px;align-items:center;cursor:pointer;white-space:nowrap}
  input[type=range]{width:120px;accent-color:#62e07d}
  kbd{border:1px solid var(--line);border-radius:3px;padding:0 4px;color:var(--dim)}
  #live{color:var(--dim)} #live.on{color:#62e07d}
  .warn{color:var(--warn)}
</style></head><body>
<header>
  <select id="ship" title="ships in the watched roots"></select>
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
<main><canvas id="c"></canvas><div id="hud" class="empty"></div>
      <div id="err" class="hide"></div></main>
<footer>
  <label>zoom <input type="range" id="zoom" min="1" max="16" step="0.5" value="4"></label>
  <label><input type="checkbox" id="bridge" checked> bridge</label>
  <label><input type="checkbox" id="mounts"> mounts</label>
  <label><input type="checkbox" id="ids"> ids</label>
  <label><input type="checkbox" id="axes"> centreline</label>
  <span class="stat"><kbd>drag</kbd> pan · <kbd>wheel</kbd> zoom · <kbd>hover</kbd> inspect
    · <kbd>[</kbd><kbd>]</kbd> ship · <kbd>0</kbd> centre</span>
</footer>
<script>
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
const ui=id=>document.getElementById(id);
let SC=null,IMGS={},pan={x:0,y:0},drag=null,hover=null,rev='';
// Ship state. `sel` is the hull on show and lives in the URL; `loaded` is the
// one the canvas actually holds, so a switch repaints even when two files
// happen to hash alike. `stamps` is the last (mtime,size) seen per hull and
// `changed` the ones that moved while we were looking elsewhere.
let sel=new URLSearchParams(location.search).get('ship');
let loaded=null,loadedRev=null,files={},stamps={},changed=new Set(),sig='',toast=null;

function fit(){const r=cv.getBoundingClientRect(),d=devicePixelRatio||1;
  cv.width=r.width*d;cv.height=r.height*d;draw();}
addEventListener('resize',fit);

const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function showErr(title,msg){ui('err').className='';
  ui('err').innerHTML='<b></b>';ui('err').firstChild.textContent=title;
  ui('err').appendChild(document.createTextNode(msg));}
function clearErr(){ui('err').className='hide';}

// -- the dropdown ---------------------------------------------------------
function optLabel(e){
  const stem=e.file.replace(/\.[^.]+$/,'');
  return (e.pair?'   ↳ ':'')+e.file+(e.name===stem?'':' — '+e.name)+
         (e.stale?'  ⚠ stale':'')+(changed.has(e.key)?'  ●':'');
}
function rebuild(ix){
  const s=ui('ship');s.innerHTML='';
  const gs=ix.roots.map(l=>{const g=document.createElement('optgroup');
    g.label=l;return g;});
  for(const e of ix.ships){
    const o=document.createElement('option');
    o.value=e.key;o.textContent=optLabel(e);
    (gs[e.group]||gs[0]).appendChild(o);
  }
  for(const g of gs)if(g.children.length)s.appendChild(g);
  if(sel)s.value=sel;
}
function relabel(ix){                       // cheap: only the text can drift
  const byKey={};for(const e of ix.ships)byKey[e.key]=e;
  for(const o of ui('ship').options){
    const e=byKey[o.value];if(!e)continue;
    const t=optLabel(e);if(o.textContent!==t)o.textContent=t;
  }
}

function apply(ix){
  files={};for(const e of ix.ships)files[e.key]=e.file;
  // A hull that moved while we were watching another one earns a dot.
  for(const e of ix.ships){
    const was=stamps[e.key],now=e.stamp.join(':');
    if(was!==undefined&&was!==now&&e.key!==sel)changed.add(e.key);
    stamps[e.key]=now;
  }
  changed.delete(sel);
  for(const k of [...changed])if(!(k in files))changed.delete(k);

  const s=ix.roots.join('|')+'#'+ix.ships.map(e=>e.key+e.stale+e.name).join('|');
  if(s!==sig){sig=s;rebuild(ix);}else{relabel(ix);}

  // The list above is true whoever asked for it; the selection below is only
  // true of the hull this answer was about. A poll that left before a switch
  // names the previous one, and adopting that would undo the switch.
  if((ix.req||null)!==(sel||null))return;

  if(ix.sel!==sel){                         // server picked, or ours vanished
    // The hull under you leaving is worth saying, and saying somewhere the
    // replacement's own load will not immediately wipe. It rides in the header
    // until the next switch.
    if(ix.gone&&sel)toast=sel.split('/').pop()+' left the watched roots';
    sel=ix.sel;history.replaceState({ship:sel},'',sel?'?ship='+encodeURIComponent(sel):'.');
  }
  if(sel)ui('ship').value=sel;
  if(!sel){SC=null;loaded=null;ui('nm').textContent='—';
    showErr('no ships found','nothing with a .sb4 or .shp suffix in the watched roots yet.');
    draw();return;}

  rev=ix.rev;ui('rev').textContent=(rev||'').slice(0,7);
  if(loaded!==sel||loadedRev!==rev)loadScene();
}

// -- the scene ------------------------------------------------------------
async function fetchScene(key){
  const r=await fetch('scene.json?ship='+encodeURIComponent(key),{cache:'no-store'});
  return await r.json();
}
async function loadScene(){
  const key=sel;
  let sc=await fetchScene(key);
  if(sc.error){                 // a half-written ShipMaker save heals itself
    await sleep(200);
    if(key!==sel)return;
    sc=await fetchScene(key);
  }
  if(key!==sel)return;          // switched away mid-flight
  if(sc.error){SC=null;loaded=key;loadedRev=null;
    showErr(files[key]||key,sc.error);draw();return;}
  clearErr();
  const need=Object.entries(sc.sprites).filter(([k])=>!IMGS[k]);
  await Promise.all(need.map(([k,src])=>new Promise(res=>{
    const im=new Image();im.onload=()=>{IMGS[k]=im;res()};im.onerror=res;im.src=src;})));
  if(key!==sel)return;
  SC=sc;loaded=key;loadedRev=sc.rev;
  document.title=(files[key]||sc.name)+' — ship preview';
  ui('nm').textContent=sc.name;ui('ns').textContent=sc.counts.section;
  ui('nw').textContent=sc.counts.weapon;ui('nm2').textContent=sc.counts.module;
  ui('nd').textContent=sc.counts.doodad||0;
  const b=sc.bbox;ui('sz').textContent=Math.round(b[2]-b[0])+'×'+Math.round(b[3]-b[1]);
  const msgs=[...(toast?[toast]:[]),...sc.notes,
              ...(sc.missing.length?['unresolved: '+sc.missing.join(', ')]:[])];
  ui('notes').innerHTML=msgs.length?'<span class="warn">'+msgs.join(' · ')+'</span>':'';
  draw();
}

function visible(){const b=ui('bridge').checked;
  return SC.ops.filter(o=>b||o.kind!=='bridge');}

// A section is a two-tone mask multiplied by its colour. That multiply has to
// happen OFF-SCREEN: 'destination-in' composites against the whole canvas, not
// against the sprite being drawn, so tinting in place erases everything painted
// earlier and only the last masked op survives. Cached per sprite+colour, so
// each combination is built once -- and shared across ships, which is why
// switching hulls costs one fetch and no redecode.
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
  if(!SC)return;
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

// -- switching ------------------------------------------------------------
// Zoom, pan and the toggles deliberately survive a switch: flipping between two
// hulls at the same scale and screen position is a blink comparator, and that
// is most of the point of having them on one page. `0` re-centres, which is
// what makes keeping the pan safe.
function pick_ship(key){
  if(!key||key===sel)return;
  sel=key;ui('ship').value=key;changed.delete(key);clearErr();toast=null;
  history.pushState({ship:key},'','?ship='+encodeURIComponent(key));
  loadScene();
}
ui('ship').addEventListener('change',e=>pick_ship(e.target.value));
addEventListener('popstate',()=>{
  const k=new URLSearchParams(location.search).get('ship');
  if(k&&k!==sel){sel=k;ui('ship').value=k;clearErr();loadScene();}
});
function cycle(step){
  const opts=[...ui('ship').options];if(!opts.length)return;
  let i=opts.findIndex(o=>o.value===sel);
  i=(i<0?0:i+step+opts.length)%opts.length;
  pick_ship(opts[i].value);
}
function centre(){pan.x=pan.y=0;draw();}
cv.addEventListener('dblclick',centre);
addEventListener('keydown',e=>{
  if(e.target.tagName==='SELECT'||e.target.tagName==='INPUT')return;
  if(e.key==='[')cycle(-1);
  else if(e.key===']')cycle(1);
  else if(e.key==='0')centre();
});

async function poll(){
  try{
    const q=sel?('?ship='+encodeURIComponent(sel)):'';
    const ix=await (await fetch('index'+q,{cache:'no-store'})).json();
    ui('live').className='on';
    apply(ix);
  }catch(e){ui('live').className='';}
  setTimeout(poll,600);
}
fit();poll();
</script></body></html>'''


# --------------------------------------------------------------------------
# where it listens
# --------------------------------------------------------------------------

#: Tailscale hands every node an address in the CGNAT range. Checking the range
#: rather than trusting the command's output keeps a stray `100.x` public
#: address -- 100.0.0.0/8 is not all Tailscale -- from being offered as a
#: tailnet URL.
_CGNAT = ipaddress.ip_network('100.64.0.0/10')


def tailscale_ip() -> str | None:
    """This node's tailnet IPv4, or None if Tailscale is not up.

    The IP rather than the MagicDNS name on purpose: the name is the machine's
    hostname, and a URL is a thing people paste into places it should not go.
    """
    try:
        out = subprocess.run(['tailscale', 'ip', '-4'], capture_output=True,
                             text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode:
        return None
    for tok in out.stdout.split():
        try:
            addr = ipaddress.ip_address(tok)
        except ValueError:
            continue
        if addr.version == 4 and addr in _CGNAT:
            return tok
    return None


def addresses(bind: str) -> list[tuple[str, str]]:
    """(host, note) pairs to listen on.

    `auto` is loopback *and* the tailnet when there is one -- two sockets, not a
    wildcard bind, so the page is reachable from your other devices without
    also being offered to whatever network you happen to be on.
    """
    if bind != 'auto':
        return [(bind, '')]
    out = [('127.0.0.1', '')]
    ts = tailscale_ip()
    if ts:
        out.append((ts, 'tailnet — reachable from your other devices'))
    return out


def _serving_here(host: str, port: int) -> list[dict] | None:
    """The ship list of a preview already on this port, or None."""
    try:
        with urllib.request.urlopen(f'http://{host}:{port}/index', timeout=1) as r:
            got = json.loads(r.read(1 << 20))
        return got['ships'] if isinstance(got.get('ships'), list) else None
    except Exception:                                # noqa: BLE001
        return None


def _links(hosts: list[tuple[str, str]], port: int, key: str | None) -> list[str]:
    q = '?ship=' + urllib.parse.quote(key, safe='') if key else ''
    return [f'  http://{h}:{port}/{q}' + (f'   {note}' if note else '')
            for h, note in hosts]


def run(targets: list[str] | None = None, roots: list[str] | None = None,
        bind: str = 'auto', port: int = 8771) -> int:
    try:
        rs, first = resolve_roots(list(targets or []), roots)
    except FileNotFoundError as e:
        print(f'no such file: {e}', file=sys.stderr)
        return 2
    hosts = addresses(bind)

    # One preview covers every hull, so a second one on the same port is never
    # what anyone wants. If ours is already there, hand back the URL instead.
    running = _serving_here(hosts[0][0], port)
    if running is not None:
        key = None
        if first is not None:
            hit = next((e for e in running if e['file'] == first.name), None)
            if hit is None:
                print(f'a preview is already on port {port}, but it does not '
                      f'watch {first.name}.', file=sys.stderr)
                print(f'restart it over there, or use --port for a second one.',
                      file=sys.stderr)
                return 4
            key = hit['key']
        print(f'a preview is already watching here — reusing it')
        for line in _links(hosts, port, key):
            print(line)
        return 0

    Handler.index = Index(rs, first)
    n = len(Handler.index.entries)
    socketserver.TCPServer.allow_reuse_address = True
    servers = []
    for host, note in hosts:
        try:
            servers.append((socketserver.ThreadingTCPServer((host, port),
                                                            Handler), host, note))
        except OSError as e:
            print(f'cannot listen on {host}:{port} — {e}', file=sys.stderr)
    if not servers:
        return 1

    where = ', '.join(Handler.index.labels) or 'nothing'
    print(f'watching {n} hull{"" if n == 1 else "s"} in {where}')
    # Deep-link only to a hull that was actually asked for. With nothing named
    # the page picks the newest itself, and a link would just be a guess.
    for line in _links([(h, note) for _s, h, note in servers], port,
                       Handler.index.default() if first is not None else None):
        print(line)
    if not n:
        print('no ships there yet — the page will pick them up as they appear')
    print('the page follows the files, whoever writes them — Ctrl-C to stop')

    for srv, _h, _n in servers[1:]:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        servers[0][0].serve_forever()
    except KeyboardInterrupt:
        print('\nstopped')
    finally:
        for srv, _h, _n in servers:
            srv.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1:]))
