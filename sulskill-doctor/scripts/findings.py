"""Findings page: a curated list of mods worth acting on, rendered in the SulSkill look.

The findings themselves are written by whoever audited the library (a person,
or an agent following sulskill-doctor). This renders them, grouped by the four
reasons a mod earns a row, and keeps them honest against the library as it is
NOW: a row whose files are all gone is dropped, a conflict left with fewer than
two mods is over, and each row's files are grouped under the mod a player can
actually search for (the Vortex mod, or the folder it was unzipped into).

findings JSON: {"summary": str, "note": str, "footer": str, "findings": [{
    "reason": 1-4, "mod": str, "files": [str], "claim": str, "evidence": str,
    "severity": "high"|"medium"|"low", "verified": bool, "action": str,
    "mb": float|null, "order": bool}]}
"files" are paths relative to Mods (or bare filenames); "*" globs and a
trailing " (note)" are allowed.

    py scripts/findings.py [findings.json] [--out page.html]
    (defaults: <out_dir>/review.json -> <out_dir>/mod_review.html)
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import fnmatch
import glob
import json
import os
import sys

import report_style
import vortex_state

REASONS = {
    1: ('Slowing the game down',
        'Problem implementations costing load time or play time, where it '
        'could be done better or should not be done at all.'),
    2: ('I could do this better',
        'Mods whose job is worth doing, done in a heavier or riskier way than '
        'it needs to be. Each is a candidate for a minimal rebuild.'),
    3: ("Doesn't do what it says",
        'Mods that cannot be doing their job on this install, with the evidence.'),
    4: ('Other objections',
        'Duplicates, redundant pairs, obsolete fixes, and dead weight.'),
}

CHIPS = """
      <button class="chip chip-rm" id="f-rm" aria-pressed="false">Recommend removing <b id="rm-n"></b></button>
      <button class="chip" id="f-high" aria-pressed="false">High severity</button>
      <button class="chip" id="f-ver" aria-pressed="false">Verified only</button>
      <button class="chip" id="f-set" aria-pressed="false">Not load-order dependent</button>
      <button class="chip" id="f-r1" aria-pressed="false">Slowing</button>
      <button class="chip" id="f-r2" aria-pressed="false">Do better</button>
      <button class="chip" id="f-r3" aria-pressed="false">Doesn't work</button>
      <button class="chip" id="f-r4" aria-pressed="false">Other</button>
      <button class="chip" id="f-clear" aria-pressed="false">Reset</button>"""

EXTRA_CSS = r"""
.row{grid-template-columns:minmax(0,22rem) minmax(0,1fr) 15rem;padding:14px 20px}
.mod{font-weight:650;font-size:15.5px}
.files{margin-top:4px;font-size:12.5px;color:var(--soft);word-break:break-all}
.vm{margin-top:8px}
.vm b{display:block;font-size:14px;font-weight:600;color:var(--ink);word-break:break-word}
.vm b::before{content:"Vortex mod  ";font-size:11px;font-weight:600;letter-spacing:.06em;
  text-transform:uppercase;color:var(--soft)}
.vm .files{margin:2px 0 0 0}
.claim{font-size:15.5px}
details{margin-top:6px}
summary{cursor:pointer;color:var(--ink-2);font-size:14px}
details p{margin:6px 0 0;font-size:14px;color:var(--ink-2);white-space:pre-wrap}
.f-high{background:#FBE3E0;color:#9A2A1C}
:root[data-theme="dark"] .f-high{background:#3A1A16;color:#F2A79C}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .f-high{
  background:#3A1A16;color:#F2A79C}}
.f-med{background:var(--cheat-wash);color:var(--cheat)}
.act{display:flex;justify-content:flex-end;margin-top:8px}
.act span{font-size:13px;font-weight:650;padding:4px 12px;border-radius:6px;
  border:1.5px solid transparent;letter-spacing:.01em}
.a-remove{background:var(--rm);color:#fff}
.a-pick{border-color:var(--rm) !important;color:var(--rm-ink);background:var(--rm-wash)}
.a-update{background:var(--cheat-wash);color:var(--cheat)}
.a-rebuild{background:var(--plumbob-wash);color:var(--plumbob-ink)}
.a-merge,.a-keep{border-color:var(--line) !important;color:var(--ink-2)}
.row.rm{box-shadow:inset 5px 0 0 var(--rm);background:var(--rm-wash)}
.row.pick{box-shadow:inset 5px 0 0 var(--rm-soft)}
.chip-rm{border-color:var(--rm);color:var(--rm-ink);font-weight:600}
.chip-rm:hover{border-color:var(--rm);color:var(--rm-ink)}
.chip-rm[aria-pressed="true"]{background:var(--rm);border-color:var(--rm);color:#fff}
:root{--rm:#B3261E;--rm-soft:#E8968F;--rm-ink:#8C1D16;--rm-wash:#FDF0EE}
:root[data-theme="dark"]{--rm:#D9483D;--rm-soft:#7A2E28;--rm-ink:#F4A9A1;--rm-wash:#2A1513}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --rm:#D9483D;--rm-soft:#7A2E28;--rm-ink:#F4A9A1;--rm-wash:#2A1513}}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));
  gap:0;border-top:1px solid var(--line)}
.stat{padding:14px 20px;border-right:1px solid var(--line)}
.stat b{display:block;font-size:24px;font-variant-numeric:tabular-nums}
.stat span{font-size:13.5px;color:var(--ink-2)}
@media (max-width:820px){.act{justify-content:flex-start}}
"""

SCRIPT = r"""
const DATA = __DATA__;
const REASONS = __REASONS__;
const list = document.getElementById('list');
const q = document.getElementById('q');
const countEl = document.getElementById('count');
const empty = document.getElementById('empty');
const emptyq = document.getElementById('emptyq');
const chips = {rm: f('f-rm'), high: f('f-high'), ver: f('f-ver'), set: f('f-set'), r1: f('f-r1'), r2: f('f-r2'),
               r3: f('f-r3'), r4: f('f-r4')};
function f(id){ return document.getElementById(id); }
const SEV = {high: 0, medium: 1, low: 2};
const ACT = {'Remove': ['a-remove', 'rm', 'Remove'], 'Pick one': ['a-pick', 'pick', 'Remove one of these'],
             'Update it': ['a-update', '', 'Update it'], 'I can rebuild this lighter': ['a-rebuild', '', 'I can rebuild this lighter'],
             'Merge': ['a-merge', '', 'Merge'], 'Keep, but know this': ['a-keep', '', 'Keep, but know this']};
function act(r){ return ACT[r.action] || ['a-keep', '', r.action]; }
const isRm = r => r.action === 'Remove' || r.action === 'Pick one';
f('rm-n').textContent = DATA.filter(isRm).length;

function row(r){
  const flags = [
    '<span class="flag ' + (r.severity === 'high' ? 'f-high' : r.severity === 'medium'
       ? 'f-med' : 'f-soft') + '">' + esc(r.severity) + '</span>',
    r.verified ? '<span class="flag f-good">verified</span>'
               : '<span class="flag f-soft">inferred</span>'];
  if (r.order) flags.push('<span class="flag f-med">depends on load order</span>');
  if (r.mb) flags.push('<span class="flag f-soft">' + r.mb.toFixed(1) + ' MB</span>');
  const a = act(r);
  return '<div class="row ' + a[1] + '" data-rm="' + (isRm(r)?1:0) + '" data-sev="' + r.severity + '" data-ver="' + (r.verified?1:0) + '" data-ord="' + (r.order?1:0) +
    '" data-hay="' + esc((r.mod + ' ' + r.vm.map(g => g[0]).join(' ') + ' ' + r.files.join(' ') + ' ' + r.claim + ' ' +
    r.evidence + ' ' + r.action).toLowerCase()) + '">' +
    '<div><div class="mod">' + esc(r.mod) + '</div>' +
    r.vm.map(g => '<div class="vm">' + (g[0] ? '<b>' + esc(g[0]) + '</b>' : '') +
      '<div class="files mono">' + g[1].map(esc).join('<br>') + '</div></div>').join('') + '</div>' +
    '<div><div class="claim">' + esc(r.claim) + '</div>' +
    '<details><summary>Evidence</summary><p>' + esc(r.evidence) + '</p></details></div>' +
    '<div><div class="flags">' + flags.join('') + '</div>' +
    '<div class="act"><span class="' + a[0] + '">' + esc(a[2]) + '</span></div></div></div>';
}

function build(){
  let html = '';
  for (const k of ['1','2','3','4']){
    const rows = DATA.filter(r => String(r.reason) === k)
      .sort((a, b) => isRm(b) - isRm(a) || SEV[a.severity] - SEV[b.severity] || (b.verified - a.verified));
    if (!rows.length) continue;
    html += '<section class="card" data-reason="' + k + '"><header><h2>' +
      esc(REASONS[k][0]) + '</h2><span class="n"></span><p>' + esc(REASONS[k][1]) +
      '</p></header><div class="rows">' + rows.map(row).join('') + '</div></section>';
  }
  list.innerHTML = html;
}

function apply(){
  const term = q.value.trim().toLowerCase();
  const rs = ['1','2','3','4'].filter(k => on(chips['r' + k]));
  let shown = 0;
  for (const card of list.querySelectorAll('.card[data-reason]')){
    let n = 0;
    const cardOk = !rs.length || rs.includes(card.dataset.reason);
    for (const r of card.querySelector('.rows').children){
      let ok = cardOk && (!term || r.dataset.hay.includes(term));
      if (ok && on(chips.rm) && r.dataset.rm !== '1') ok = false;
      if (ok && on(chips.high) && r.dataset.sev !== 'high') ok = false;
      if (ok && on(chips.ver) && r.dataset.ver !== '1') ok = false;
      if (ok && on(chips.set) && r.dataset.ord === '1') ok = false;
      r.hidden = !ok; if (ok) n++;
    }
    card.querySelector('.n').textContent = n;
    card.hidden = n === 0; shown += n;
  }
  countEl.textContent = shown + ' of ' + DATA.length + ' findings';
  empty.hidden = shown !== 0;
  emptyq.textContent = term ? 'No finding mentions “' + q.value.trim() + '”.'
                            : 'No finding matches those filters.';
}

build(); apply();
wireSearch(q, apply);
for (const c of Object.values(chips)) wireChip(c, apply);
f('f-clear').addEventListener('click', () => {
  q.value = '';
  for (const c of Object.values(chips)) c.setAttribute('aria-pressed', 'false');
  apply(); q.focus();
});
"""


def live_files(mods):
    """Every .package/.ts4script under Mods, as '/'-paths relative to it."""
    out = []
    for dp, _, fns in os.walk(mods):
        for fn in fns:
            if fn.lower().endswith(('.package', '.ts4script')):
                out.append(os.path.relpath(os.path.join(dp, fn), mods).replace(os.sep, '/'))
    return out


def is_mod_file(ref):
    return ref.lower().endswith(('.package', '.ts4script')) or '*' in ref


class Library:
    """Which mod owns a file: the Vortex mod when Vortex deployed it, else its top folder."""

    def __init__(self, mods=None, names=None):
        self.mods = mods or vortex_state.mods_dir()
        files = live_files(self.mods) if self.mods else []
        self.case = {x.lower(): x for x in files}     # match lower-case, display as on disk
        self.live = list(self.case)
        self.src = vortex_state.deployment(self.mods)
        self.names = names if names is not None else (vortex_state.mod_names() if self.src else {})

    def match(self, ref):
        """Live paths a finding's file reference names: exact, glob, or by bare filename."""
        rel = ref.replace('\\', '/').lower()
        bare = '/' not in rel
        if '*' in rel:
            return [x for x in self.live if fnmatch.fnmatch(x.rsplit('/', 1)[-1] if bare else x, rel)]
        if rel in self.live:
            return [rel]
        return [x for x in self.live if (x.rsplit('/', 1)[-1] == rel) if bare] or \
               [x for x in self.live if x.endswith('/' + rel)]

    def owner(self, path):
        mid = self.src.get(path)
        if mid:
            return vortex_state.display(mid, self.names)
        path = self.case.get(path, path)
        return path.split('/', 1)[0] if '/' in path else path


def attach_mods(findings, lib=None):
    """Drop rows already resolved on disk; group each row's files by owning mod (as r['vm'])."""
    lib = lib or Library()
    gone = []
    for r in list(findings):
        refs = [f.partition(' (')[0] for f in r['files']]
        hits = {x: lib.match(x) for x in refs if is_mod_file(x)}
        missing = [x for x, h in hits.items() if not h]
        before = {lib.owner(h[0]) if h else x for x, h in hits.items()}
        after = {lib.owner(p) for h in hits.values() for p in h}
        # a conflict between mods is over once fewer than two of them remain
        if missing and (not after or (len(before) >= 2 and len(after) < 2)):
            findings.remove(r)
            gone.append(r['mod'])
    for r in findings:
        groups = {}
        for f in r['files']:
            ref, _, note = f.partition(' (')
            found = lib.match(ref) if is_mod_file(ref) else None
            if found == []:
                continue                    # removed since the audit: leave it out entirely
            key = lib.owner(found[0]) if found else ''
            groups.setdefault(key, []).append(ref.replace('\\', '/').rsplit('/', 1)[-1] + (' (' + note if note else ''))
        r['vm'] = [[k, v] for k, v in groups.items()]
    return gone


def live_stats(d, mods):
    """Header numbers from the library as it is now and the rows that render."""
    pk = glob.glob(os.path.join(glob.escape(mods), '**', '*.package'), recursive=True)
    sc = glob.glob(os.path.join(glob.escape(mods), '**', '*.ts4script'), recursive=True)
    size = sum(os.path.getsize(f) for f in pk + sc)
    rows = d['findings']
    mb = sum((r.get('mb') or 0) for r in rows if r['action'] in ('Remove', 'Pick one'))
    return {'packages': '{:,}'.format(len(pk)), 'script mods': '{:,}'.format(len(sc)),
            'on disk': '%.1f GB' % (size / 1e9), 'findings': str(len(rows)),
            'verified': str(sum(1 for r in rows if r.get('verified'))),
            'high severity': str(sum(1 for r in rows if r['severity'] == 'high')),
            'to remove or pick': str(sum(1 for r in rows if r['action'] in ('Remove', 'Pick one'))),
            'reclaimable': '%.0f MB' % mb if mb >= 1 else 'none'}


def main(argv=None):
    ap = argparse.ArgumentParser(description='Render a findings JSON as the SulSkill findings page.')
    ap.add_argument('findings', nargs='?', default=os.path.join(gate.out_dir(), 'review.json'))
    ap.add_argument('--out', default=os.path.join(gate.out_dir(), 'mod_review.html'))
    a = ap.parse_args(argv)
    d = json.load(open(a.findings, encoding='utf-8'))
    lib = Library()
    gone = attach_mods(d['findings'], lib)
    if gone:
        print(len(gone), 'findings dropped, already resolved on disk:', *gone, sep='\n  ')
    stats = ''.join(f'<div class="stat"><b>{v}</b><span>{k}</span></div>'
                    for k, v in live_stats(d, lib.mods).items())
    body = ('<section class="card"><header><h2>The library</h2>'
            f'<p>{d.get("summary", "")}</p></header><div class="stats">{stats}</div></section>'
            '<div id="list"></div>')
    page = report_style.page(
        title="Mods I Wouldn't Keep",
        placeholder='Search mods, files, reasons…',
        chips_html=CHIPS,
        note_html=d.get('note', ''),
        body_html=body,
        footer_html=('<p><strong>SulSkill</strong> &mdash; ' + d.get('footer', '') + '</p>'),
        script=(SCRIPT.replace('__DATA__', json.dumps(d['findings'], ensure_ascii=False))
                      .replace('__REASONS__', json.dumps({str(k): v for k, v in REASONS.items()}))),
        extra_css=EXTRA_CSS)
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(page)
    print('wrote', a.out, len(d['findings']), 'findings')
    return 0


if __name__ == '__main__':
    sys.exit(main())
