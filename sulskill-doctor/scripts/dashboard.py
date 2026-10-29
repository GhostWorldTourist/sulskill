"""SulSkill dashboard: one page over everything SulSkill knows about an install.

Joins, by mod (the Vortex mod when Vortex deployed it, else the folder it sits in):
- the library itself, with a one-line description of each mod (manifest.py)
- the open findings (findings.py), kept honest against the library as it is now
- console commands each script mod registers (commands.py)
- the mods you built yourself, checked byte for byte against what is deployed
- install health: last launch, exception reports, Resource.cfg reach, script
  validity, mods that define the same resources, variant sets

Every view filters, searches, and exports to PDF, Markdown or JSON from the page.

Read-only against the game folders, so it is safe to rebuild while the game runs.
Inputs it reads from <out_dir> when present, all optional:
  review.json          findings (see findings.py for the format)
  adult_inventory.json classify_adult.py output, for the "Hide adult" filter
  variants.json        variants.py output
  dashboard.json       your own builds and how to recognise your mods:
    {"author": "Your Name",
     "own_prefix": ["yourname_"],
     "repos": "~/repos", "repo_glob": "sims4-*", "extra_repos": ["path", ...],
     "builds": [{"label": str, "repo": str, "artifact": "file or zip in <repo>/out",
                 "member": "path inside the zip, or null", "deployed": "deployed filename"}]}

    py scripts/dashboard.py [--out page.html]      (default <out_dir>/dashboard.html)
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import collections
import glob
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
import zipfile

import commands as cmdscan
import findings as findings_page
import manifest
import report_style
import vortex_state

DOC = os.path.dirname(os.path.abspath(__file__))
MODS = vortex_state.mods_dir()
SIMS = os.path.dirname(MODS) if MODS else ''


def config():
    p = os.path.join(gate.out_dir(), 'dashboard.json')
    c = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    c.setdefault('author', '')
    c['own_prefix'] = tuple(x.lower() for x in c.get('own_prefix', []))
    c['repos'] = os.path.expanduser(c.get('repos', '~/repos'))
    c.setdefault('repo_glob', '')
    c['extra_repos'] = [os.path.expandvars(os.path.expanduser(x)) for x in c.get('extra_repos', [])]
    c.setdefault('builds', [])
    return c


def game_build():
    """The game's own version string, from Game/Bin/Default.ini."""
    ini = os.path.join(gate.game_dir() or '', 'Game', 'Bin', 'Default.ini')
    try:
        m = re.search(r'^\s*gameversion\s*=\s*(\S+)', open(ini, encoding='utf-8', errors='replace').read(), re.M)
        return m.group(1) if m else 'unknown'
    except OSError:
        return 'unknown'


def outfile(name):
    return os.path.join(gate.out_dir(), name)


# --- the library, by mod -----------------------------------------------------------

def library(lib, cfg):
    adult = set()
    if os.path.exists(outfile('adult_inventory.json')):
        adult = set(json.load(open(outfile('adult_inventory.json'), encoding='utf-8')).get('adult', []))
    mods = collections.OrderedDict()
    for dp, _, fns in os.walk(MODS):
        for fn in sorted(fns):
            low = fn.lower()
            if not low.endswith(('.package', '.ts4script')):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, MODS).replace(os.sep, '/')
            sid = lib.src.get(rel.lower(), '')
            disp = lib.owner(rel.lower()) if sid else (rel.split('/', 1)[0] if '/' in rel else fn)
            m = mods.setdefault(disp, {'name': disp, 'id': sid, 'files': [], 'size': 0, 'scripts': 0,
                                       'adult': False, 'summary': '', 'big': 0, 'own': False})
            size = os.path.getsize(p)
            m['files'].append(rel)
            m['size'] += size
            if low.endswith('.ts4script'):
                m['scripts'] += 1
            if cfg['own_prefix'] and low.startswith(cfg['own_prefix']):
                m['own'] = True
            if (sid and sid in adult) or manifest.NSFW.search(fn) or manifest.NSFW_TEXT.search(fn):
                m['adult'] = True
            if low.endswith('.package') and size > m['big']:
                try:
                    summary, _, _ = manifest.describe(p)
                except Exception:
                    summary = ''
                title = manifest.title_from_filename(fn)
                weak = (not summary or summary == 'no readable content'
                        or summary.startswith(('tuning:', 'adds:'))
                        or re.match(r'^[\d, ]*(Interaction|Buff|Snippet|SimData|CAS part|Image|Model)', summary))
                m['summary'] = (f'{title} - {summary}' if weak and title and summary else summary or title or '')
                m['big'] = size
                if manifest.NSFW_TEXT.search(m['summary']):
                    m['adult'] = True
    for m in mods.values():
        if not m['summary'] and m['scripts']:
            m['summary'] = 'script mod'
        m.pop('big')
    return mods


# --- health --------------------------------------------------------------------------

def md5(b):
    return hashlib.md5(b).hexdigest()


def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ''


def index_keys(path):
    with open(path, 'rb') as f:
        data = f.read()
    if data[:4] != b'DBPF':
        return []
    count, = struct.unpack_from('<I', data, 0x24)
    isize, = struct.unpack_from('<I', data, 0x2C)
    ioff = struct.unpack_from('<Q', data, 0x40)[0] or struct.unpack_from('<I', data, 0x28)[0]
    ix = data[ioff:ioff + isize]
    flags, = struct.unpack_from('<I', ix, 0)
    p, const = 4, {}
    for bit, key in ((0, 't'), (1, 'g'), (2, 'h')):
        if flags & (1 << bit):
            const[key], = struct.unpack_from('<I', ix, p); p += 4
    out = []
    for _ in range(count):
        v = {}
        for key in ('t', 'g', 'h'):
            if key in const:
                v[key] = const[key]
            else:
                v[key], = struct.unpack_from('<I', ix, p); p += 4
        lo, off, fsz, msz = struct.unpack_from('<IIII', ix, p); p += 16
        if fsz & 0x80000000:
            p += 4
        out.append((v['t'], v['g'], (v['h'] << 32) | lo))
    return out


def health(lib):
    h = {}
    # last launch
    logs = glob.glob(os.path.join(MODS, '**', '*.log'), recursive=True)
    last = max((os.path.getmtime(f) for f in logs), default=0)
    h['last_launch'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(last)) if last else 'unknown'
    exc = []
    for f in sorted(glob.glob(os.path.join(SIMS, 'last*Exception*.txt')), key=os.path.getmtime, reverse=True)[:6]:
        t = os.path.getmtime(f)
        body = open(f, encoding='utf-8', errors='replace').read()
        cat = re.search(r'<categoryid>([^<]*)', body)
        exc.append({'file': os.path.basename(f), 'when': time.strftime('%Y-%m-%d %H:%M', time.localtime(t)),
                    'this_launch': last and t >= last - 600, 'category': cat.group(1) if cat else ''})
    h['exceptions'] = exc
    h['running'] = os.name == 'nt' and 'TS4_x64.exe' in sh('tasklist')
    # last deploy: the mod manager's manifest when there is one, else the newest file in Mods
    man = glob.glob(os.path.join(glob.escape(MODS), '*', 'vortex.deployment.json')) + \
        glob.glob(os.path.join(glob.escape(MODS), 'vortex.deployment.json'))
    dep_t = max((os.path.getmtime(x) for x in man), default=0) or max(
        (os.path.getmtime(os.path.join(MODS, f)) for m in lib.values() for f in m['files']), default=0)
    h['deployed'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(dep_t))
    # Resource.cfg reach
    # Resource.cfg reach, from sulskill-doctor's own checker rather than a re-parse
    pk = [f for m in lib.values() for f in m['files'] if f.lower().endswith('.package')]
    out = sh(sys.executable, os.path.join(DOC, 'resource_cfg.py'))
    m = re.search(r'(\d+) package\(s\) reachable, deepest at (\d+) folder\(s\); rules reach (\d+)', out)
    reach, deepest, depth = (int(x) for x in m.groups()) if m else (0, 0, 0)
    h['cfg'] = {'rule_depth': depth, 'deepest': deepest, 'packages': len(pk), 'reachable': reach,
                'ok': bool(m) and reach >= len(pk)}
    # scripts: valid zip, py3.7 bytecode, depth <= 1 below Mods
    bad = []
    sc = [f for m in lib.values() for f in m['files'] if f.lower().endswith('.ts4script')]
    for f in sc:
        p = os.path.join(MODS, f)
        try:
            z = zipfile.ZipFile(p)
            pycs = [n for n in z.namelist() if n.endswith('.pyc')]
            if pycs and z.read(pycs[0])[:2] != b'\x42\x0d':
                bad.append((f, 'not Python 3.7 bytecode'))
        except zipfile.BadZipFile:
            bad.append((f, 'not a valid zip'))
        if f.count('/') > 1:
            bad.append((f, 'more than one folder deep'))
    h['scripts'] = {'count': len(sc), 'bad': bad}
    # collisions between mods (not within one), excluding S4Studio manifests
    owner = {}
    for m in lib.values():
        for f in m['files']:
            owner[f] = m['name']
    keys = collections.defaultdict(set)
    for f in pk:
        try:
            for k in index_keys(os.path.join(MODS, f)):
                if k[0] == 0x7FB6AD8A:
                    continue
                keys[k].add(owner[f])
        except (OSError, struct.error):
            pass
    pairs = collections.Counter()
    for k, ms in keys.items():
        if len(ms) > 1:
            pairs[tuple(sorted(ms))] += 1
    h['collisions'] = [{'mods': list(p), 'keys': n} for p, n in pairs.most_common()]
    # variant sets (tonight's scan)
    vf = outfile('variants.json')
    if os.path.exists(vf):
        v = json.load(open(vf, encoding='utf-8'))
        h['variants'] = {'generated': v.get('generated', ''), 'groups': len(v.get('groups', []))}
    return h


# --- your builds ------------------------------------------------------------------

def builds(lib, cfg):
    """Each configured build, hash-checked against the deployed file of the same name."""
    live = {}
    for m in lib.values():
        for f in m['files']:
            live.setdefault(os.path.basename(f).lower(), []).append(f)
    out = []
    for b in cfg['builds']:
        repo = os.path.join(cfg['repos'], b['repo'])
        path = os.path.join(repo, 'out', b['artifact'])
        status, detail = 'not built', ''
        if os.path.exists(path):
            data = zipfile.ZipFile(path).read(b['member']) if b.get('member') else open(path, 'rb').read()
            hits = [x for x in live.get(b['deployed'].lower(), []) if os.path.exists(os.path.join(MODS, x))]
            if not hits:
                status = 'not installed'
            else:
                same = [h for h in hits if md5(open(os.path.join(MODS, h), 'rb').read()) == md5(data)]
                if same and len(hits) == 1:
                    status = 'deployed'
                elif same:
                    status = 'deployed twice'
                    detail = 'also at ' + ', '.join(h for h in hits if h not in same)
                else:
                    status = 'original still deployed'
        out.append({'label': b['label'], 'repo': b['repo'], 'status': status, 'detail': detail,
                    'commit': sh('git', '-C', repo, 'log', '-1', '--format=%h %cs')})
    # repos with no configured build: a committed .package says whether it is deployed
    found = sorted(glob.glob(os.path.join(glob.escape(cfg['repos']), cfg['repo_glob']))) if cfg['repo_glob'] else []
    for p in found + [x for x in cfg['extra_repos'] if os.path.isdir(x)]:
        repo = os.path.basename(p)
        if any(b['repo'] == repo for b in out):
            continue
        rd = os.path.join(p, 'README.md')
        title = open(rd, encoding='utf-8').readline().lstrip('# ').strip() if os.path.exists(rd) else repo
        pk = [os.path.basename(f) for f in glob.glob(os.path.join(glob.escape(p), '*.package'))]
        dep = [f for f in pk if f.lower() in live]
        status = 'deployed' if dep else ('not installed' if pk else 'tool')
        if p in cfg['extra_repos']:
            repo = p.replace(os.path.expanduser('~'), '~').replace(os.sep, '/')
        out.append({'label': title, 'repo': repo, 'status': status, 'detail': ', '.join(dep),
                    'commit': sh('git', '-C', p, 'log', '-1', '--format=%h %cs')})
    return out


# --- page ------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description='Build the SulSkill dashboard.')
    ap.add_argument('--out', default=outfile('dashboard.html'))
    a = ap.parse_args(argv)
    if not MODS:
        raise SystemExit('no Mods folder found (set SIMS4_DIR to the folder that holds it)')
    cfg = config()
    flib = findings_page.Library(MODS)
    lib = library(flib, cfg)
    review = (json.load(open(outfile('review.json'), encoding='utf-8'))
              if os.path.exists(outfile('review.json')) else {'findings': []})
    findings_page.attach_mods(review['findings'], flib)
    findings = review['findings']
    by_mod = collections.defaultdict(list)
    for i, f in enumerate(findings):
        for g in f.get('vm', []):
            if g[0]:
                by_mod[g[0]].append(i)
    cmds = cmdscan.scan_all([MODS])
    cmd_mod = {}
    for m in lib.values():
        for f in m['files']:
            stem = os.path.splitext(os.path.basename(f))[0]
            if stem in cmds:
                cmd_mod.setdefault(m['name'], {}).update(cmds[stem])
    h = health(lib)
    b = builds(lib, cfg)
    mods = [{**m, 'findings': by_mod.get(m['name'], []), 'commands': len(cmd_mod.get(m['name'], {}))}
            for m in lib.values()]
    commands = [{'mod': mn, 'cmd': c, 'type': i.get('type') or '', 'args': i.get('args') or ''}
                for mn, cs in sorted(cmd_mod.items(), key=lambda kv: kv[0].lower())
                for c, i in sorted(cs.items())]
    build_id = game_build()
    data = {'mods': mods, 'findings': findings, 'health': h, 'builds': b, 'commands': commands,
            'reasons': {str(k): v for k, v in findings_page.REASONS.items()}, 'author': cfg['author'],
            'generated': time.strftime('%Y-%m-%d %H:%M'), 'game': build_id}
    total = sum(m['size'] for m in mods)
    stats = [('mods', f'{len(mods):,}'),
             ('packages', f"{h['cfg']['packages']:,}"),
             ('script mods', str(h['scripts']['count'])),
             ('on disk', f'{total / 1e9:.1f} GB'),
             ('open findings', str(len(findings)))]
    if b:
        stats.append(('your builds deployed', f"{sum(1 for x in b if x['status'] == 'deployed')}/{len(b)}"))
    body = ('<section class="card"><div class="stats">' +
            ''.join(f'<div class="stat"><b>{v}</b><span>{k}</span></div>' for k, v in stats) +
            '</div></section><div id="panel"></div>')
    page = report_style.page(
        title='SulSkill Dashboard',
        placeholder='Search mods, findings, commands…',
        chips_html=CHIPS,
        note_html=('One page over the whole install, rebuilt from the Mods folder, the mod manager and the game files each run. '
                   'Read-only, so it is safe to rebuild while the game is running.'),
        body_html=body,
        footer_html=(f'<p><strong>SulSkill</strong> &mdash; generated {data["generated"]} for game build {build_id}. '
                     'Findings come from the mod review; descriptions are read from each mod\'s own text and are hints, not a catalogue.</p>'),
        script=SCRIPT.replace('__DATA__', json.dumps(data, ensure_ascii=False)),
        extra_css=CSS)
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(page)
    print('wrote %s: %d mods, %d findings, %d builds, %d commands, %d collision pairs'
          % (a.out, len(mods), len(findings), len(b), len(commands), len(h['collisions'])))
    return 0


CHIPS = """
      <button class="chip tab" data-tab="overview" aria-pressed="true">Overview</button>
      <button class="chip tab" data-tab="todo" aria-pressed="false">To do</button>
      <button class="chip tab" data-tab="library" aria-pressed="false">Library</button>
      <button class="chip tab" data-tab="builds" aria-pressed="false">Your builds</button>
      <button class="chip tab" data-tab="health" aria-pressed="false">Health</button>
      <button class="chip tab" data-tab="commands" aria-pressed="false">Commands</button>
      <button class="chip" id="f-adult" aria-pressed="false">Hide adult</button>
      <span class="exports"><span class="muted">Export this view</span>
      <button class="chip" data-export="pdf">PDF</button>
      <button class="chip" data-export="md">Markdown</button>
      <button class="chip" data-export="json">JSON</button></span>"""

CSS = r"""
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(10rem,1fr));border-top:1px solid var(--line)}
.stat{padding:14px 20px;border-right:1px solid var(--line)}
.stat b{display:block;font-size:24px;font-variant-numeric:tabular-nums}
.stat span{font-size:13.5px;color:var(--ink-2)}
.tbl{width:100%;border-collapse:collapse;font-size:14.5px;table-layout:auto}
.tbl th{text-align:left;font-weight:600;color:var(--ink-2);padding:10px 20px;border-bottom:1px solid var(--line);font-size:13px}
.tbl td{padding:10px 20px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
.tbl tr:last-child td{border-bottom:0}
.muted{color:var(--soft);font-size:13px}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;overflow-wrap:anywhere}
.ok{color:var(--plumbob-ink);font-weight:600}
.warn{color:var(--cheat);font-weight:600}
.bad{color:#B3261E;font-weight:600}
:root[data-theme="dark"] .bad{color:#F4A9A1}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .bad{color:#F4A9A1}}
.row2{display:grid;grid-template-columns:minmax(0,20rem) minmax(0,1fr) 11rem;gap:16px;padding:12px 20px;border-bottom:1px solid var(--line)}
.row2>div{min-width:0;overflow-wrap:anywhere}
.row2:last-child{border-bottom:0}
.row2 .n{font-weight:650}
.row2.hl{background:var(--cheat-wash);transition:background 1.5s}
.pill{display:inline-block;font:inherit;font-size:12px;line-height:1.5;padding:2px 9px;border:0;border-radius:999px;margin:0 4px 4px 0;background:var(--warn-wash);color:var(--ink-2)}
button.pill{cursor:pointer}
button.pill:hover{filter:brightness(1.12);text-decoration:underline}
button.pill:focus-visible{outline:2px solid var(--focus);outline-offset:1px}
.pill.f{background:var(--cheat-wash);color:var(--cheat)}
.pill.c{background:var(--plumbob-wash);color:var(--plumbob-ink)}
.pill.o{background:var(--plumbob);color:#fff}
.pill.a{background:#FBE3E0;color:#9A2A1C}
.filterbar{display:flex;align-items:center;gap:10px;padding:10px 20px;border-bottom:1px solid var(--line);font-size:14px;background:var(--panel-2)}
.exports{display:inline-flex;align-items:center;gap:6px;margin-left:auto}
details{margin-top:6px}
summary{cursor:pointer;color:var(--ink-2);font-size:13.5px}
.kv{display:grid;grid-template-columns:12rem minmax(0,1fr);gap:6px 16px;padding:14px 20px;font-size:14.5px}
.kv dt{color:var(--ink-2)}
.chip.tab[aria-pressed="true"]{font-weight:650}
@media (max-width:820px){.row2{grid-template-columns:minmax(0,1fr)}.kv{grid-template-columns:minmax(0,1fr)}.exports{margin-left:0}}
@media print{
  .bar{position:static;box-shadow:none}
  .search,.chips,.note,.filterbar button,footer{display:none}
  body{background:#fff;color:#000}
  .card{box-shadow:none;break-inside:auto}
  .row2,.tbl tr{break-inside:avoid}
  details>summary{display:none}
  .print-only{display:block !important}
}
.print-only{display:none}
"""

SCRIPT = r"""
const D = __DATA__;
const panel = document.getElementById('panel');
const q = document.getElementById('q');
const countEl = document.getElementById('count');
const empty = document.getElementById('empty');
const emptyq = document.getElementById('emptyq');
const hideAdult = document.getElementById('f-adult');
const TABS = {overview: 'Overview', todo: 'To do', library: 'Library', builds: 'Your builds', health: 'Health', commands: 'Commands'};
let tab = 'overview';
let libFilter = null;      // 'own' | 'script' | 'adult' | 'findings' | 'commands'
let modFilter = null;      // To do / Commands narrowed to one Vortex mod
let focusFinding = null;   // finding index to scroll to and highlight
let printing = false;      // render every row, not the first few hundred
const MB = n => (n / 1e6).toFixed(n < 1e7 ? 1 : 0) + ' MB';
const card = (title, sub, inner) => '<section class="card"><header><h2>' + esc(title) + '</h2>' +
  (sub ? '<p>' + sub + '</p>' : '') + '</header>' + inner + '</section>';
const term = () => q.value.trim().toLowerCase();
const hit = s => !term() || s.toLowerCase().includes(term());
const adultHidden = () => on(hideAdult);
const modOf = name => D.mods.find(m => m.name === name) || {};
const STATUS = {deployed: 'ok', 'deployed twice': 'bad', 'original still deployed': 'warn', 'not installed': 'warn', 'not built': 'muted', tool: 'muted'};
const LIBF = {own: 'your mods', script: 'mods with a script', adult: 'adult mods', findings: 'mods with findings', commands: 'mods that add console commands'};
const go = (kind, arg) => '<button class="pill ' + ({own: 'o', finding: 'f', commands: 'c', adult: 'a'}[kind] || '') + '" data-go="' + kind + '" data-arg="' + esc(arg) + '">';

// ---- what each view holds: the screen, PDF, Markdown and JSON all read these ----

function todoFindings(){
  const todo = D.findings.filter(f => f.action !== 'Keep, but know this');
  return todo;
}
function overviewItems(){
  const h = D.health;
  const thisLaunch = h.exceptions.filter(e => e.this_launch);
  const gameExc = thisLaunch.filter(e => e.file.startsWith('lastException'));
  const ui = thisLaunch.filter(e => !e.file.startsWith('lastException'));
  const dupes = D.builds.filter(b => b.status === 'deployed twice');
  const waiting = D.builds.filter(b => b.status === 'not installed' || b.status === 'original still deployed');
  const todo = todoFindings();
  const items = [];
  items.push({level: gameExc.length ? 'bad' : 'ok', text: gameExc.length ? 'Game exception this launch' : 'No game exception this launch',
              note: ui.length ? ui.length + ' UI report: ' + ui[0].category : ''});
  items.push({level: h.cfg.ok ? 'ok' : 'bad', text: h.cfg.ok ? 'Every package is reachable' : 'Some packages are deeper than Resource.cfg reaches',
              note: 'deepest ' + h.cfg.deepest + ' folders, rules reach ' + h.cfg.rule_depth});
  items.push({level: h.scripts.bad.length ? 'bad' : 'ok', text: h.scripts.bad.length ? h.scripts.bad.length + ' script mod problems' : 'All ' + h.scripts.count + ' script mods load', note: ''});
  if (dupes.length) items.push({level: 'bad', text: dupes.length + ' of your builds deployed twice', note: dupes.map(b => b.label).join(', ')});
  if (waiting.length) items.push({level: 'warn', text: waiting.length + ' of your builds not installed yet', note: waiting.map(b => b.label).join(', ')});
  items.push({level: todo.length ? 'warn' : 'ok', text: todo.length ? todo.length + ' findings to act on' : 'Nothing to act on in the review', note: todo.length ? 'see To do' : ''});
  return items;
}
function findingsShown(){
  return D.findings.map((f, i) => ({...f, i})).filter(f =>
    (!modFilter || (f.vm || []).some(g => g[0] === modFilter)) &&
    hit(f.mod + ' ' + f.claim + ' ' + f.evidence + ' ' + JSON.stringify(f.vm || [])));
}
function modsShown(){
  return D.mods.filter(m => !(adultHidden() && m.adult) &&
      (!libFilter || (libFilter === 'own' ? m.own : libFilter === 'script' ? m.scripts : libFilter === 'adult' ? m.adult :
                      libFilter === 'findings' ? m.findings.length : m.commands)) &&
      hit(m.name + ' ' + m.summary + ' ' + m.files.join(' ')))
    .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
}
const buildsShown = () => D.builds.filter(b => hit(b.label + ' ' + b.repo + ' ' + b.detail));
const collisionsShown = () => D.health.collisions.filter(c => hit(c.mods.join(' ')));
const commandsShown = () => D.commands.filter(c => !(adultHidden() && modOf(c.mod).adult) &&
  (!modFilter || c.mod === modFilter) && hit(c.mod + ' ' + c.cmd + ' ' + c.args));

// ---- screen ----

function filterBar(text){
  return '<div class="filterbar"><span>Showing ' + text + '</span><button class="chip" data-go="clear">Show all</button></div>';
}
function findingRow(f){
  const i = f.i === undefined ? D.findings.indexOf(f) : f.i;
  const vm = (f.vm || []).map(g => (g[0] ? '<div class="n">' + esc(g[0]) + '</div>' : '') +
    '<div class="muted mono">' + g[1].map(esc).join('<br>') + '</div>').join('');
  return '<div class="row2" id="f' + i + '"><div>' + '<div class="n">' + esc(f.mod) + '</div>' + vm + '</div>' +
    '<div>' + esc(f.claim) + '<details' + (printing ? ' open' : '') + '><summary>Evidence</summary><p class="muted">' + esc(f.evidence) + '</p></details></div>' +
    '<div><span class="pill ' + (f.severity === 'high' ? 'a' : f.severity === 'medium' ? 'f' : '') + '">' + esc(f.severity) + '</span>' +
    '<div class="' + (f.action.startsWith('Update') || f.action.startsWith('Install') || f.action === 'Remove' ? 'warn' : 'muted') + '">' + esc(f.action) + '</div></div></div>';
}
function overview(){
  const h = D.health;
  const items = overviewItems().map(it => '<li><span class="' + it.level + '">' + esc(it.text) + '</span>' + (it.note ? ' <span class="muted">(' + esc(it.note) + ')</span>' : '') + '</li>');
  const todo = todoFindings();
  return [card('Where things stand', 'Game ' + esc(D.game) + ' · last launch ' + esc(h.last_launch) + (h.running ? ' (running now)' : '') + ' · last deploy ' + esc(h.deployed),
      '<ul style="margin:0;padding:14px 20px 14px 40px;line-height:1.9">' + items.join('') + '</ul>') +
    card('To do first', '', todo.length ? todo.map(findingRow).join('') : '<p class="muted" style="padding:14px 20px">Nothing.</p>'), null];
}
function todoTab(){
  const shown = findingsShown();
  const html = (modFilter ? '<section class="card">' + filterBar('findings for <strong>' + esc(modFilter) + '</strong>') + '</section>' : '') +
    Object.keys(D.reasons).map(k => {
      const rows = shown.filter(f => String(f.reason) === k);
      return rows.length ? card(D.reasons[k][0], esc(D.reasons[k][1]), rows.map(findingRow).join('')) : '';
    }).join('');
  return [html, shown.length];
}
function libraryTab(){
  const rows = modsShown();
  const shown = printing ? rows : rows.slice(0, 400);
  const html = card('Library', rows.length + ' Vortex mods' + (rows.length > shown.length ? ' (first 400 shown; search to narrow)' : ''),
    (libFilter ? filterBar(LIBF[libFilter]) : '') +
    shown.map(m => '<div class="row2"><div><div class="n">' + esc(m.name) + '</div><div class="muted">' + m.files.length + ' file' + (m.files.length > 1 ? 's' : '') + ' · ' + MB(m.size) + '</div></div>' +
      '<div>' + esc(m.summary) + '<details><summary>Files</summary><div class="muted mono">' + m.files.map(esc).join('<br>') + '</div></details></div>' +
      '<div>' + (m.own ? go('own', '') + 'yours</button>' : '') +
      (m.findings.length ? go('finding', m.name) + m.findings.length + ' finding' + (m.findings.length > 1 ? 's' : '') + '</button>' : '') +
      (m.commands ? go('commands', m.name) + m.commands + ' commands</button>' : '') +
      (m.scripts ? go('script', '') + 'script</button>' : '') + (m.adult ? go('adult', '') + 'adult</button>' : '') + '</div></div>').join(''));
  return [html, rows.length];
}
function buildsTab(){
  const rows = buildsShown();
  return [card('Your builds', 'Mods and fixes' + (D.author ? ' by ' + esc(D.author) : ' you built') + ', checked byte for byte against what is deployed.',
    '<table class="tbl"><tr><th>Build</th><th>Status</th><th>Repo</th><th>Last commit</th></tr>' +
    rows.map(b => '<tr><td>' + esc(b.label) + '</td><td><span class="' + (STATUS[b.status] || '') + '">' + esc(b.status) + '</span>' + (b.detail ? '<div class="muted">' + esc(b.detail) + '</div>' : '') + '</td><td class="mono">' + esc(repoPath(b)) + '</td><td class="muted">' + esc(b.commit) + '</td></tr>').join('') + '</table>'), rows.length];
}
const repoPath = b => b.repo.startsWith('~') ? b.repo : '~/repos/' + b.repo;
function installKV(){
  const h = D.health;
  const kv = [['Game build', D.game], ['Last launch', h.last_launch + (h.running ? ' · running now' : '')], ['Last deploy', h.deployed],
    ['Resource.cfg', h.cfg.packages + ' packages · deepest ' + h.cfg.deepest + ' folders · rules reach ' + h.cfg.rule_depth + ' · ' + (h.cfg.ok ? 'all reachable' : 'some unreachable')],
    ['Script mods', h.scripts.count + ' · ' + (h.scripts.bad.length ? h.scripts.bad.map(x => x[0] + ': ' + x[1]).join('; ') : 'all valid zips, Python 3.7 bytecode, depth ok')]];
  if (h.variants) kv.push(['Variant sets', h.variants.groups + ' groups (scan ' + h.variants.generated + ')']);
  return kv;
}
function healthTab(){
  const h = D.health;
  let html = card('Install', '', '<dl class="kv">' + installKV().map(([k, v]) => '<dt>' + esc(k) + '</dt><dd style="margin:0">' + esc(v) + '</dd>').join('') + '</dl>');
  html += card('Exception reports', 'Newest first. A UI report is a separate layer from game exceptions.',
    '<table class="tbl"><tr><th>File</th><th>When</th><th>Category</th></tr>' + h.exceptions.map(e => '<tr><td class="mono">' + esc(e.file) + (e.this_launch ? ' <span class="pill f">this launch</span>' : '') + '</td><td>' + esc(e.when) + '</td><td class="muted mono">' + esc(e.category) + '</td></tr>').join('') + '</table>');
  const col = collisionsShown();
  html += card('Mods that define the same resources', col.length + ' pairs. Usually deliberate (add-ons, compatibility patches, shared frameworks); which copy wins depends on load order, which has not been verified in game.',
    '<table class="tbl"><tr><th>Mods</th><th>Shared resources</th></tr>' + (printing ? col : col.slice(0, 200)).map(c => '<tr><td>' + c.mods.map(esc).join('<br>') + '</td><td>' + c.keys + '</td></tr>').join('') + '</table>');
  return [html, col.length];
}
function commandsTab(){
  const rows = commandsShown();
  const shown = printing ? rows : rows.slice(0, 600);
  return [card('Console commands', rows.length + ' commands registered by installed script mods' + (rows.length > shown.length ? ' (first 600 shown; search to narrow)' : '') + '. Type "Cheat" ones need testingcheats on.',
    (modFilter ? filterBar('commands from <strong>' + esc(modFilter) + '</strong>') : '') +
    '<table class="tbl"><tr><th>Command</th><th>Mod</th><th>Type</th></tr>' + shown.map(c => '<tr><td class="mono">' + esc(c.cmd) + '</td><td>' + esc(c.mod) + '</td><td class="muted">' + esc(c.type) + '</td></tr>').join('') + '</table>'), rows.length];
}

function render(){
  const [html, n] = ({overview, todo: todoTab, library: libraryTab, builds: buildsTab, health: healthTab, commands: commandsTab})[tab]();
  panel.innerHTML = '<p class="print-only muted">' + esc(TABS[tab] + (filterLine() ? ' · ' + filterLine() : '')) + '</p>' + html;
  countEl.textContent = n === null ? '' : n + ' shown';
  empty.hidden = !(n === 0);
  emptyq.textContent = term() ? 'Nothing here mentions “' + q.value.trim() + '”.' : 'Nothing to show.';
  if (focusFinding !== null){
    const el = document.getElementById('f' + focusFinding);
    focusFinding = null;
    if (el){ el.classList.add('hl'); el.querySelector('details').open = true; el.scrollIntoView({block: 'center'}); setTimeout(() => el.classList.remove('hl'), 1800); }
  } else if (!printing) window.scrollTo(0, 0);
}
function setTab(t){
  tab = t;
  document.querySelectorAll('.chip.tab').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.tab === t)));
}

document.querySelectorAll('.chip.tab').forEach(c => c.addEventListener('click', () => {
  libFilter = modFilter = null; setTab(c.dataset.tab); render();
}));
panel.addEventListener('click', e => {
  const b = e.target.closest('[data-go]');
  if (!b) return;
  const kind = b.dataset.go, arg = b.dataset.arg;
  if (kind === 'clear') { libFilter = modFilter = null; }
  else if (kind === 'finding') {
    q.value = ''; modFilter = arg; setTab('todo');
    const mine = modOf(arg).findings || [];
    if (mine.length === 1) focusFinding = mine[0];
  }
  else if (kind === 'commands') { q.value = ''; modFilter = arg; setTab('commands'); }
  else {
    libFilter = libFilter === kind ? null : kind;
    if (kind === 'adult' && adultHidden()) hideAdult.setAttribute('aria-pressed', 'false');
  }
  render();
});
wireChip(hideAdult, () => { if (adultHidden() && libFilter === 'adult') libFilter = null; render(); });
wireSearch(q, () => { if (tab === 'overview' && term()) setTab('library'); render(); });

// ---- exports: always the current view, with its search and filters, every row ----

function filtersNow(){
  return {query: q.value.trim() || null, hide_adult: adultHidden(), library_filter: libFilter, mod: modFilter};
}
function filterLine(){
  const f = filtersNow(), parts = [];
  if (f.query) parts.push('search “' + f.query + '”');
  if (f.library_filter && tab === 'library') parts.push(LIBF[f.library_filter]);
  if (f.mod && (tab === 'todo' || tab === 'commands')) parts.push('mod: ' + f.mod);
  if (f.hide_adult && (tab === 'library' || tab === 'commands')) parts.push('adult hidden');
  return parts.join(' · ');
}
const slim = f => ({severity: f.severity, action: f.action, mod: f.mod, vortex_mods: (f.vm || []).map(g => ({name: g[0], files: g[1]})),
                    claim: f.claim, evidence: f.evidence, reason: D.reasons[String(f.reason)] ? D.reasons[String(f.reason)][0] : f.reason});
function viewData(){
  if (tab === 'overview') return {status: overviewItems(), todo: todoFindings().map(slim)};
  if (tab === 'todo') return {findings: findingsShown().map(slim)};
  if (tab === 'library') return {mods: modsShown().map(m => ({name: m.name, summary: m.summary, files: m.files, size: m.size,
      yours: !!m.own, script: !!m.scripts, adult: !!m.adult, findings: m.findings.length, commands: m.commands}))};
  if (tab === 'builds') return {builds: buildsShown().map(b => ({...b, repo: repoPath(b)}))};
  if (tab === 'health') return {install: Object.fromEntries(installKV()), exceptions: D.health.exceptions, collisions: collisionsShown()};
  return {commands: commandsShown()};
}

const mdCell = s => String(s === undefined || s === null ? '' : s).replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');
const mdTable = (head, rows) => rows.length ? '| ' + head.join(' | ') + ' |\n|' + head.map(() => '---').join('|') + '|\n' +
  rows.map(r => '| ' + r.map(mdCell).join(' | ') + ' |').join('\n') + '\n' : '_Nothing._\n';
function mdFindings(list){
  return list.map(f => '### ' + f.mod + '\n\n**' + f.severity + '** · ' + f.action + '\n\n' +
    (f.vortex_mods.length ? f.vortex_mods.map(g => '- ' + (g.name ? '**' + g.name + '**: ' : '') + g.files.map(x => '`' + x + '`').join(', ')).join('\n') + '\n\n' : '') +
    f.claim + '\n\n> ' + f.evidence.replace(/\r?\n/g, ' ') + '\n').join('\n') || '_Nothing._\n';
}
function toMarkdown(){
  const d = viewData(), h = D.health;
  let md = '# SulSkill Dashboard: ' + TABS[tab] + '\n\nGenerated ' + D.generated + ' for game build ' + D.game + ' · exported ' + new Date().toLocaleString() +
    (filterLine() ? '\n\nFiltered: ' + filterLine() : '') + '\n\n';
  if (tab === 'overview') {
    md += '## Where things stand\n\nLast launch ' + h.last_launch + (h.running ? ' (running now)' : '') + ' · last deploy ' + h.deployed + '\n\n' +
      d.status.map(s => '- ' + (s.level === 'ok' ? '✅ ' : s.level === 'bad' ? '❌ ' : '⚠️ ') + s.text + (s.note ? ' (' + s.note + ')' : '')).join('\n') +
      '\n\n## To do first\n\n' + mdFindings(d.todo);
  } else if (tab === 'todo') {
    md += Object.keys(D.reasons).map(k => {
      const rows = d.findings.filter(f => f.reason === D.reasons[k][0]);
      return rows.length ? '## ' + D.reasons[k][0] + '\n\n' + D.reasons[k][1] + '\n\n' + mdFindings(rows) : '';
    }).filter(Boolean).join('\n') || '_Nothing._\n';
  } else if (tab === 'library') {
    md += d.mods.length + ' Vortex mods\n\n' + mdTable(['Mod', 'What it does', 'Files', 'Size', 'Tags'],
      d.mods.map(m => [m.name, m.summary, m.files.length, MB(m.size),
        [m.yours && 'yours', m.findings && m.findings + ' findings', m.commands && m.commands + ' commands', m.script && 'script', m.adult && 'adult'].filter(Boolean).join(', ')]));
  } else if (tab === 'builds') {
    md += mdTable(['Build', 'Status', 'Detail', 'Repo', 'Last commit'], d.builds.map(b => [b.label, b.status, b.detail, '`' + b.repo + '`', b.commit]));
  } else if (tab === 'health') {
    md += '## Install\n\n' + Object.entries(d.install).map(([k, v]) => '- **' + k + ':** ' + v).join('\n') +
      '\n\n## Exception reports\n\n' + mdTable(['File', 'When', 'Category', 'This launch'], d.exceptions.map(e => ['`' + e.file + '`', e.when, e.category, e.this_launch ? 'yes' : ''])) +
      '\n## Mods that define the same resources\n\n' + mdTable(['Mods', 'Shared resources'], d.collisions.map(c => [c.mods.join('<br>'), c.keys]));
  } else {
    md += d.commands.length + ' commands\n\n' + mdTable(['Command', 'Mod', 'Type', 'Arguments'], d.commands.map(c => ['`' + c.cmd + '`', c.mod, c.type, c.args]));
  }
  return md;
}
function toJSON(){
  const d = viewData();
  return JSON.stringify({generated: new Date().toISOString().slice(0, 19), source: 'sulskill-dashboard', dashboard_generated: D.generated,
    game_build: D.game, view: tab, filters: filtersNow(), count: Object.values(d).reduce((n, v) => Array.isArray(v) ? n + v.length : n, 0), ...d}, null, 2);
}
function download(name, text, type){
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], {type}));
  a.download = name; document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
const stem = () => 'sulskill-' + tab + '-' + new Date().toISOString().slice(0, 10);
window.addEventListener('beforeprint', () => { printing = true; render(); panel.querySelectorAll('details').forEach(x => x.open = true); });
window.addEventListener('afterprint', () => { printing = false; render(); });
document.querySelectorAll('[data-export]').forEach(b => b.addEventListener('click', () => {
  const k = b.dataset.export;
  if (k === 'pdf') { const t = document.title; document.title = stem(); window.print(); document.title = t; }
  else if (k === 'md') download(stem() + '.md', toMarkdown(), 'text/markdown');
  else download(stem() + '.json', toJSON(), 'application/json');
}));
if (!D.builds.length) document.querySelector('[data-tab=builds]').hidden = true;
render();
"""

if __name__ == '__main__':
    sys.exit(main())
