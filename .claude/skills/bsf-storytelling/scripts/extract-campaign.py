#!/usr/bin/env python3
"""Extract the shipped campaign from the game and render it as CAMPAIGN.html.

The campaign text is the game's own, so it can never be committed here. This is
the generator; its output is git-ignored. Run it once and the skill has the
verbatim reference beside it:

    python3 .claude/skills/bsf-storytelling/scripts/extract-campaign.py

Everything comes straight out of `BattleshipsForever.exe` -- GM 7.0 keeps GML as
source text inside its resource tree, and `tools/gm7.py` already inverts the
"gmkrypt" encryption, so no wine, no running game and no memory dump are needed.
The whole run is well under a second.

WHAT IS AND IS NOT IN HERE
--------------------------
Extracted verbatim: every briefing title, briefing body and objectives list;
every line of comm traffic with its speaker and its colour; the beat number each
line hangs off; the staging calls around it (camera, pings, highlights, spawns,
autosaves, music, failure strings); and the Step-event conditions that advance
the chain.

NOT extracted, because it does not exist in the game: the editorial commentary,
per-episode locations and ranks, opposition summaries and "new this episode"
hull notes that a hand-written campaign document may carry. Those are somebody's
analysis, not data, and this script does not invent them.

THE FORMAT TRAPS, ALL MEASURED
------------------------------
* **GML has no string escapes.** A double-quoted string runs to the next `"`,
  full stop -- which is why the naive `"([^"]*)"` works here and why apostrophes
  inside dialogue are harmless.
* **Comments must be stripped string-aware, and they interleave with live code.**
  ctr_Mission0 opens a `/*` block, closes it mid-statement with `{*/` so the
  `showMessage` that follows IS live, then reopens `/*`. A regex that strips
  from the first `/*` to the last `*/` deletes real dialogue; one that ignores
  strings would trip over a `//` inside a message.
* **`#` is a line break inside a message string**, not a comment and not markup.
* Message strings are right-padded with spaces to size the panel; that padding
  is trimmed here.
* Beat numbers are deliberately sparse -- the game leaves gaps so branches can
  jump into them (`//MESSAGECOUNT 6 LEFT EMPTY`). Gaps are real and preserved.
"""
import argparse
import html
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# scripts -> bsf-storytelling -> skills -> .claude -> repo root
REPO = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, os.pardir, os.pardir))
OUT = os.path.join(os.path.dirname(HERE), 'CAMPAIGN.html')
CSS = os.path.join(HERE, 'campaign.css')

sys.path.insert(0, os.path.join(REPO, 'tools'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'bsf'))
try:
    import gm7                                                     # noqa: E402
    import gmobj                                                   # noqa: E402
    import paths                                                   # noqa: E402
except ImportError as exc:                                         # pragma: no cover
    sys.exit("cannot import the repo's game tools (%s).\n"
             "This script must run from inside a BSF Legacy checkout -- it "
             "needs tools/gm7.py, tools/gmobj.py and tools/bsf/paths.py." % exc)

MISSIONS = 8                      #: rm_Mission0..7 / ctr_Mission0..7 shipped

#: GM colour literal -> the stylesheet's channel class. The game writes BGR, so
#: c_red is $0000FF; both spellings of each channel appear in the source.
CHANNEL = {
    '$00FF00': 'hq',       'c_lime':  'hq',
    'c_red':   'foe',      '$0000FF': 'foe',
    '$FF00FF': 'alien',
    'c_white': 'log',      '$FFFFFF': 'log',
}

#: Staging calls worth reporting, and how to phrase each one.
STAGING = {
    'centreCamera':   lambda a: 'Camera centres on %s.' % _expr(a[0]),
    'showPing':       lambda a: 'Ping at %s, %s.' % (_expr(a[0]), _expr(a[1])),
    'showHighlight':  lambda a: 'Highlights %s.' % _expr(a[0]),
    'instance_create': lambda a: 'Spawns %s.' % _expr(a[-1]),
}


# ---------------------------------------------------------------- GML lexing

def strip_comments(code):
    """Remove `//` and `/* */` comments without touching string literals.

    Done as a single left-to-right walk because the three states genuinely
    interleave in this source -- see the module docstring.
    """
    out, i, n = [], 0, len(code)
    while i < n:
        c = code[i]
        if c == '"':                       # string: copy verbatim to its close
            j = code.find('"', i + 1)
            j = n if j < 0 else j + 1
            out.append(code[i:j])
            i = j
        elif code.startswith('//', i):
            j = code.find('\n', i)
            i = n if j < 0 else j
        elif code.startswith('/*', i):
            j = code.find('*/', i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def _block(code, start):
    """Return (body, end) for the brace-delimited block at or after `start`."""
    i = code.find('{', start)
    if i < 0:
        return '', start
    depth, j, n = 0, i, len(code)
    while j < n:
        c = code[j]
        if c == '"':
            k = code.find('"', j + 1)
            j = n if k < 0 else k + 1
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return code[i + 1:j], j + 1
        j += 1
    return code[i + 1:], n


def ladder(code, var):
    """Split an `if <var> = N then { ... }` chain into [(N, body, start, end)].

    Branches are keyed by the integer they test for, so the game's deliberate
    gaps survive as missing numbers rather than being renumbered. Spans come
    back too, because dialogue also lives *outside* the ladder in the same
    event and has to be told apart from it.
    """
    out, seen = [], set()
    for m in re.finditer(r'if\s+%s\s*==?\s*(\d+)\s*then' % re.escape(var), code):
        n = int(m.group(1))
        body, end = _block(code, m.end())
        if n in seen:
            continue
        seen.add(n)
        out.append((n, body, m.start(), end))
    return out


def outside(code, spans):
    """The parts of `code` not covered by `spans`, joined.

    A controller can call showMessage straight from its User Event 0 without
    testing the counter at all; that line is real and would be lost if only
    ladder bodies were read.
    """
    keep, at = [], 0
    for start, end in sorted((s, e) for _n, _b, s, e in spans):
        if start > at:
            keep.append(code[at:start])
        at = max(at, end)
    keep.append(code[at:])
    return '\n'.join(keep)


#: GM 7.0 event key -> a human label. Type 7 numbers 10..25 are User 0..15.
def event_label(key):
    kind, _, num = key.partition(':')
    num = int(num)
    if kind == '0':
        return 'create'
    if kind == '2':
        # Per the controller contract, Create arms alarm 2 to fire the opening
        # message -- that is the campaign's "start" beat in every mission.
        return 'start' if num == 2 else 'alarm %d' % num
    if kind == '3':
        return ('step', 'begin step', 'end step')[num] if num < 3 else 'step'
    if kind == '7' and 10 <= num <= 25:
        return 'user event %d' % (num - 10)
    if kind == '8':
        return 'draw'
    return 'event %s' % key


def args_of(call):
    """Split one call's argument list on top-level commas, strings respected."""
    out, depth, cur, i, n = [], 0, [], 0, len(call)
    while i < n:
        c = call[i]
        if c == '"':
            j = call.find('"', i + 1)
            j = n if j < 0 else j + 1
            cur.append(call[i:j])
            i = j
            continue
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        if c == ',' and depth == 0:
            out.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    if ''.join(cur).strip():
        out.append(''.join(cur).strip())
    return out


def calls(code, name):
    """Every `name(...)` in `code`, in order, as (arglist, position)."""
    out = []
    for m in re.finditer(r'\b%s\s*\(' % re.escape(name), code):
        body, _ = _paren(code, m.end() - 1)
        out.append((args_of(body), m.start()))
    return out


def _paren(code, start):
    """Return (inner, end) for the parenthesised group opening at `start`."""
    depth, j, n = 0, start, len(code)
    while j < n:
        c = code[j]
        if c == '"':
            k = code.find('"', j + 1)
            j = n if k < 0 else k + 1
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return code[start + 1:j], j + 1
        j += 1
    return code[start + 1:], n


def _str(tok):
    """The contents of a GML string literal, or None if `tok` is an expression."""
    tok = tok.strip()
    if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
        return tok[1:-1]
    return None


def _texts(tok):
    """The spoken string(s) in a message argument, longest-form first.

    Usually one literal. `choose("a","b",...)` picks one at random at run time,
    so every alternative is real dialogue and all of them come back. Whitespace-
    only results are dropped: the game pads panels with spaces and uses
    all-blank messages purely as timing spacers.
    """
    lit = _str(tok)
    if lit is not None:
        return [lit.rstrip()] if lit.strip() else []
    if re.match(r'^\s*choose\s*\(', tok):
        inner, _ = _paren(tok, tok.index('('))
        out = []
        for part in args_of(inner):
            s = _str(part)
            if s and s.strip():
                out.append(s.rstrip())
        return out
    return []


def _expr(tok):
    """A raw GML expression, tidied for prose."""
    return re.sub(r'\s+', ' ', tok.strip()).rstrip(';')


# ------------------------------------------------------------- game reading

def load_objects(exe):
    """Every object record in the exe's resource tree, keyed by name."""
    _raw, (_pos, _clen, blob) = gm7.load(str(exe))
    plain, _seed, _swap_start, _swap_off = gm7.gmkrypt_decrypt(blob)
    # gmobj reads a path; hand it the decrypted tree rather than re-implementing
    # its record walk here.
    fd, tmp = tempfile.mkstemp(suffix='.bin', prefix='bsf-tree-')
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(plain)
        objs = gmobj.main(tmp)
    finally:
        os.unlink(tmp)
    return {o['name']: o for o in objs}


def briefings(objs):
    """{mission: {title, paras, objectives, fleet}} from GUI_BriefingText."""
    code = strip_comments(objs['GUI_BriefingText']['events']['0:0'][0])
    out = {}
    for n, body, _start, _end in ladder(code, 'global.mission'):
        title = re.search(r'l_title\s*=\s*"([^"]*)"', body)
        text = re.search(r'l_text\s*=\s*"([^"]*)"', body)
        if not (title and text):
            continue
        fleet = {}
        for kind in ('BB', 'DD', 'PC'):
            m = re.search(r'global\.choose%s\s*=\s*(\d+)' % kind, body)
            if m and int(m.group(1)):
                fleet[kind] = int(m.group(1))
        paras, objectives = _split_briefing(text.group(1))
        out[n] = {'title': title.group(1).strip(), 'paras': paras,
                  'objectives': objectives, 'fleet': fleet}
    return out


def _split_briefing(text):
    """Briefing body -> (paragraphs, objectives).

    `#` is the game's line break; a blank line is `# #`. The objectives list is
    whatever follows an OBJECTIVES heading, one per `- ` line.
    """
    lines = [ln.strip() for ln in text.split('#')]
    head, objs, in_objs = [], [], False
    for ln in lines:
        if not ln:
            continue
        if re.fullmatch(r'OBJECTIVES?:?', ln, re.I):
            in_objs = True
            continue
        (objs if in_objs else head).append(ln.lstrip('- ').strip()
                                           if in_objs else ln)
    return head, objs


def content(body):
    """Pull dialogue, staging notes and tags out of one block of GML."""
    lines, notes, tags = [], [], []

    for a, _pos in calls(body, 'showMessage'):
        if len(a) < 4:
            continue
        said = _texts(a[3])
        if not said:
            # Empty-string calls are timing spacers, not dialogue -- the game
            # uses them to hold the panel open. Counting them would inflate
            # every line tally.
            continue
        who = (_str(a[2]) or '').strip()
        cls = CHANNEL.get(a[1].strip(), 'hq')
        if who.lower() == '[hint]':
            cls = 'hint'
        elif 'objective' in who.lower():
            cls = 'obj'
        for text in said:
            lines.append({'cls': cls, 'who': who, 'text': text})
        if len(said) > 1:
            notes.append('One of these %d lines is picked at random.'
                         % len(said))

    for name, phrase in STAGING.items():
        for a, _pos in calls(body, name):
            try:
                notes.append(phrase(a))
            except Exception:               # an arg shape this phrasing can't read
                pass

    if re.search(r'\bsaveGame\s*\(', body):
        tags.append(('save', 'autosave'))
    for a, _pos in calls(body, 'bgm_Play'):
        tags.append(('music', _expr(a[0])))
    if re.search(r'\bstopMusic\s*\(', body):
        tags.append(('music', 'music stops'))
    for a, _pos in calls(body, 'missionFail'):
        tags.append(('fail', _str(a[0]) or _expr(a[0])))
    if re.search(r'\bmissionSucc\s*\(', body):
        tags.append(('save', 'Mission Accomplished'))

    return lines, notes, tags


def beats(obj):
    """[{trig, lines, notes, tags}] for one mission controller.

    Dialogue is NOT confined to the User Event 0 ladder. The opening line comes
    from an alarm, ship-destroyed reactions come from a user event with no
    counter test at all, and wave spawners carry their own. Reading only the
    ladder loses about a quarter of the campaign's comm traffic, so every event
    is read and each group is labelled by where it came from.
    """
    ev = obj['events']
    user0 = strip_comments(ev.get('7:10', [''])[0])
    lad = ladder(user0, 'l_messagecount')
    steps = {n: body for n, body, _s, _e in
             ladder(strip_comments(ev.get('3:0', [''])[0]), 'l_messagecount')}

    ladder_keys = {'7:10'}
    out = []

    def add(trig, body, order):
        lines, notes, tags = content(body)
        if lines or tags:
            out.append({'trig': trig, 'lines': lines, 'notes': notes,
                        'tags': tags, '_o': order})

    # 1. Create and alarms -- the opening beat and any timed interjections.
    for key in sorted((k for k in ev if k.startswith(('0:', '2:'))),
                      key=lambda k: (k[0], int(k.split(':')[1]))):
        add(event_label(key), strip_comments(ev[key][0]), 0)

    # 2. The numbered ladder, in the game's own sparse numbering.
    for n, body, _s, _e in sorted(lad):
        lines, notes, tags = content(body)
        cond = steps.get(n)
        if cond:                      # the non-dialogue trigger that advances
            jump = re.search(r'l_messagecount\s*=\s*(\d+)', cond)
            test = re.search(r'if\s+(.+?)\s+then', cond, re.S)
            if test:
                notes.append('Advances%s when %s.'
                             % (' to beat %s' % jump.group(1) if jump else '',
                                _expr(test.group(1))))
        if lines or notes or tags:
            out.append({'trig': str(n), 'lines': lines, 'notes': notes,
                        'tags': tags, '_o': 1})

    # 3. Anything in User Event 0 that never tested the counter.
    add('user event 0 (always)', outside(user0, lad), 2)

    # 4. The remaining event-driven handlers.
    for key in sorted(k for k in ev if k not in ladder_keys
                      and not k.startswith(('0:', '2:'))):
        add(event_label(key), strip_comments(ev[key][0]), 3)

    out.sort(key=lambda b: (b['_o'], 0))
    for b in out:
        b.pop('_o')
    return out


# ----------------------------------------------------------------- rendering

def e(s):
    return html.escape(s, quote=False)


def breaks(s):
    """Render the game's `#` line breaks, escaping everything else."""
    return '<br>'.join(e(p.strip()) for p in s.split('#'))


def render(data, build):
    css = open(CSS, encoding='utf-8').read()
    o = []
    w = o.append
    w('<!doctype html>')
    w('<html lang="en">')
    w('<head>')
    w('<meta charset="utf-8">')
    w('<meta name="viewport" content="width=device-width, initial-scale=1">')
    w('<title>Battleships Forever — The Campaign</title>')
    w('<style>\n%s\n</style>' % css)
    w('</head>')
    w('<body>')
    w('<div class="wrap">')

    w('<header class="masthead">')
    w('  <div class="eyebrow">Wyrdysm Games · Battleships Forever · '
      'extracted reference</div>')
    w('  <h1>The Campaign<span class="cursor" aria-hidden="true"></span></h1>')
    w('  <p class="sub">Every briefing and every line of comm traffic in the '
      'shipped campaign, read straight out of the game\'s own resource tree. '
      'Dialogue is verbatim, including the game\'s typos and inconsistent '
      'spellings.</p>')
    w('  <div class="provenance">')
    w('    <span><b>Source</b> %s</span>' % e(build))
    w('    <span><b>Objects</b> ctr_Mission0 – ctr_Mission%d</span>' % (MISSIONS - 1))
    w('    <span><b>Generated by</b> extract-campaign.py</span>')
    w('  </div>')
    w('</header>')

    w('<section id="about">')
    w('  <div class="sec-head"><span class="n">00</span><h2>What this is</h2></div>')
    w('  <div class="prose">')
    w('    <p>Battleships Forever shipped a single-player campaign of eight '
      'missions. There is no cutscene system and no external script files — the '
      'whole narrative lives inside eight Game Maker controller objects as one '
      'chain of numbered dialogue beats. This document is that chain, '
      'unpacked.</p>')
    w('    <p>Beat numbers are the game\'s own <code>l_messagecount</code> '
      'values. They are deliberately sparse: the source leaves gaps so branches '
      'can jump into them, and those gaps are preserved here rather than '
      'renumbered.</p>')
    w('    <p>This file is generated and git-ignored. Regenerate it with '
      '<code>extract-campaign.py</code>; do not hand-edit it, and do not commit '
      'it — the campaign text belongs to the game.</p>')
    w('  </div>')
    w('</section>')

    for n in range(MISSIONS):
        ep = data.get(n)
        if not ep:
            continue
        b = ep['brief']
        w('<article class="episode" id="ep%d">' % (n + 1))
        w('  <div class="ep-head">')
        w('    <div class="ep-num">%02d</div>' % (n + 1))
        w('    <div class="ep-title">')
        w('      <h2>%s</h2>' % e(b['title']))
        w('      <div class="ep-meta">rm_Mission%d · ctr_Mission%d</div>' % (n, n))
        w('    </div>')
        w('  </div>')

        w('  <div class="briefing">')
        w('    <div class="btitle">%s</div>' % e(b['title']))
        for p in b['paras']:
            w('    <p>%s</p>' % e(p))
        if b['objectives']:
            w('    <ul class="objs">')
            w('      <li class="oh">Objectives</li>')
            for ob in b['objectives']:
                w('      <li>%s</li>' % e(ob))
            w('    </ul>')
        w('  </div>')

        w('  <dl class="strip">')
        if b['fleet']:
            names = {'BB': 'Battleship', 'DD': 'Destroyer', 'PC': 'Cutter'}
            parts = ['<span class="hi">%d</span> %s%s'
                     % (c, names[k], 's' if c > 1 else '')
                     for k, c in b['fleet'].items()]
            w('    <div><dt>Deployment</dt><dd>%s</dd></div>' % ' · '.join(parts))
        saves = sum(1 for x in ep['beats'] for t, _ in x['tags'] if t == 'save')
        lines = sum(len(x['lines']) for x in ep['beats'])
        w('    <div><dt>Beats</dt><dd>%d</dd></div>' % len(ep['beats']))
        w('    <div><dt>Comm lines</dt><dd>%d</dd></div>' % lines)
        w('    <div><dt>Autosaves</dt><dd>%d</dd></div>' % saves)
        w('  </dl>')

        w('  <div class="beats">')
        w('    <h3>Scenario</h3>')
        for x in ep['beats']:
            w('    <div class="beat">')
            w('      <div class="trig">%s</div>' % e(x['trig']))
            w('      <div class="bd">')
            for note in x['notes']:
                w('        <p class="note">%s</p>' % e(note))
            for ln in x['lines']:
                w('        <p class="line %s"><span class="who">%s</span>'
                  '<q>%s</q></p>' % (ln['cls'], e(ln['who']), breaks(ln['text'])))
            for kind, label in x['tags']:
                w('        <p><span class="tag %s">%s</span></p>'
                  % (kind, e(label)))
            w('      </div>')
            w('    </div>')
        w('  </div>')
        w('</article>')

    w('</div>')
    w('</body>')
    w('</html>')
    return '\n'.join(o) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--exe', help='BattleshipsForever.exe (default: discovered)')
    ap.add_argument('-o', '--out', default=OUT, help='output path')
    a = ap.parse_args()

    exe = a.exe or os.path.join(str(paths.GAME), 'BattleshipsForever.exe')
    if not os.path.exists(exe):
        sys.exit('game exe not found: %s\n'
                 'Point $BSF_GAME at your Battleships Forever install, or pass '
                 '--exe.' % exe)

    objs = load_objects(exe)
    briefs = briefings(objs)

    data = {}
    for n in range(MISSIONS):
        ctr = objs.get('ctr_Mission%d' % n)
        if not ctr or n not in briefs:
            continue
        data[n] = {'brief': briefs[n], 'beats': beats(ctr)}

    if not data:
        sys.exit('no campaign missions recovered -- is %s a stock v0.90d build?'
                 % exe)

    build = '%s (%d objects)' % (os.path.basename(exe), len(objs))
    out = render(data, build)
    with open(a.out, 'w', encoding='utf-8') as fh:
        fh.write(out)

    lines = sum(len(x['lines']) for d in data.values() for x in d['beats'])
    print('%s: %d missions, %d beats, %d comm lines, %.0f KB'
          % (os.path.relpath(a.out, REPO), len(data),
             sum(len(d['beats']) for d in data.values()), lines,
             len(out) / 1024))


if __name__ == '__main__':
    main()
