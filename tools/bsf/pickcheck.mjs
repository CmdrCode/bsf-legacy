// Does the preview page's hover pick agree with the blitter?
//
// The PIL renderer already keeps an id buffer: for every pixel, the index of
// the op that painted it. That is exactly what a pick is asking, so the buffer
// is the answer key -- no second opinion to write and nothing to keep in sync.
//
// This runs the page's *own* JS, lifted out of `serve.PAGE`, against a stub DOM.
// Testing a port of the picker would only prove the port right; the bug it
// exists to catch (a hover box centred on the origin, over a sheet that is 4%
// art) lived in the shipped source and scored 39.9%.
//
// Driven by `selftest.py`, which builds the input. Standalone:
//     python3 selftest.py            # skips cleanly when node is absent
import fs from 'fs';
import vm from 'vm';

const T = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

// `let`/`const` at a vm script's top level bind in the declarative scope rather
// than on the global object, so the page hands out accessors for its own state.
const js = T.js.replace(/fit\(\);poll\(\);\s*$/, '') +
  '\nglobalThis.__t={IMGS,ALPHA,pan,pickStack,setSC(v){SC=v}};\n';

const el = () => ({
  value: '1', checked: false, className: '', innerHTML: '', textContent: '',
  children: [], options: [], style: {}, dataset: {},
  addEventListener() {}, appendChild() {}, closest() { return null; },
  getBoundingClientRect: () => ({ left: 0, top: 0, width: T.W, height: T.H }),
});
const els = {};
const ctx = new Proxy({}, { get: (_t, k) => (k === 'canvas' ? els.c : () => {}) });
els.c = el();
els.c.getContext = () => ctx;
els.c.width = T.W;
els.c.height = T.H;

const sandbox = {
  document: { getElementById: id => (els[id] ||= el()),
              createElement: () => ({ getContext: () => ctx, width: 0, height: 0 }) },
  devicePixelRatio: 1, addEventListener() {}, setTimeout() {}, fetch() {},
  location: { search: '' }, history: { replaceState() {}, pushState() {} },
  URLSearchParams: class { get() { return null; } }, Image: class {}, console,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(js, sandbox);
const page = sandbox.__t;

page.setSC({ ops: T.ops });
for (const o of T.ops) page.IMGS[o.spr] = { naturalWidth: 1, naturalHeight: 1 };
// Skip the page's own canvas read -- there is no canvas here -- and seed the
// cache with the alpha the browser would have found in the same sheets.
for (const [spr, a] of Object.entries(T.alphas)) {
  const raw = Buffer.from(a.a, 'base64');
  const d = new Uint8ClampedArray(raw.length * 4);
  for (let i = 0; i < raw.length; i++) d[i * 4 + 3] = raw[i];
  page.ALPHA[spr] = { w: a.w, d };
}
els.zoom.value = '1';
els.bridge.checked = true;
page.pan.x = page.pan.y = 0;

const ids = new Int32Array(Buffer.from(T.ids, 'base64').buffer.slice(0));
const at = (x, y) => ids[y * T.W + x];

// Interior pixels only. The two blitters resample a rotated edge differently
// and round a sub-pixel placement differently, so a one-pixel seam along every
// silhouette is expected and is not what this measures.
function interior(x, y) {
  const v = at(x, y);
  for (let dy = -1; dy <= 1; dy++)
    for (let dx = -1; dx <= 1; dx++)
      if (at(x + dx, y + dy) !== v) return false;   // in range: the loop insets by 1
  return true;
}

let painted = 0, hitOk = 0, empty = 0, emptyOk = 0;
const bad = [];
for (let y = 1; y < T.H - 1; y++) {
  for (let x = 1; x < T.W - 1; x++) {
    if (!interior(x, y)) continue;
    const want = at(x, y);
    // The cursor position that lands on this pixel's centre, at zoom 1, no pan.
    const st = page.pickStack((x + 0.5 - T.cx) + T.W / 2, (y + 0.5 - T.cy) + T.H / 2);
    const got = st.length ? T.ops.indexOf(st[0]) : -1;
    if (want === -1) { empty++; if (got === -1) emptyOk++; }
    else { painted++; if (got === want) hitOk++; }
    if (got !== want && bad.length < 8)
      bad.push({ x, y, want, got, over: want === -1 ? 'clear space' : T.ops[want].name });
  }
}

const pct = (n, d) => (d ? (100 * n / d).toFixed(3) : '0.000') + '%';
console.log(JSON.stringify({
  painted, hitOk, empty, emptyOk,
  onArt: pct(hitOk, painted), onClearSpace: pct(emptyOk, empty), bad,
}));
process.exit(hitOk === painted && emptyOk === empty ? 0 : 1);
