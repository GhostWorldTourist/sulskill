#!/usr/bin/env python3
"""Render the curated command set as a searchable single-page report.

Same input as commands_doc.py - curated JSON, verified against a live scan -
but built for use at the console rather than for reading top to bottom. A
player alt-tabs out mid-game knowing roughly what they want; the page's whole
job is to get them from a half-remembered word to an exact command they can
type. So: instant search across command, description and mod, filters for the
states that change whether a command will work, and click-to-copy.

    py commands_html.py curated/*.json --out ~/Downloads/commands.html
    py commands_html.py curated/*.json --out ~/Downloads/all.html --include-adult

The page lists one machine's installed mods, so write it outside the repository:
this skill ships tools, not anyone's mod list.

Adult mods are omitted by default, matching commands_doc.py. Pass
--include-adult for a personal copy that has everything.

Styling comes from report_style.py so every report this skill generates looks
like part of one set.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import glob
import json
import os
import sys

import report_style                                              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# The command column carries the thing being read; give it room before the
# description competes for it.
EXTRA_CSS = '.row{grid-template-columns:minmax(0,34rem) 1fr auto}'

CHIPS = """
      <button class="chip" id="f-cheat" aria-pressed="false">Needs cheats</button>
      <button class="chip" id="f-sure" aria-pressed="false">Confirmed only</button>
      <button class="chip" id="f-clear" aria-pressed="false">Reset</button>"""

NOTE = ('Open the console with <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd>, '
        'type, press Enter. Anything marked <em>needs cheats</em> needs '
        '<code>testingcheats true</code> active. Click a command to copy it.')

FOOTER = """<p><strong>SulSkill</strong> &mdash; read from the installed mods
  themselves, not from a wiki &mdash; __TOTAL__ commands kept out of __RAW__
  registered across __MODS__ mods. <em>uncertain</em> marks a command whose name
  is real but whose behaviour is inferred; <em>unverified</em> marks one
  recovered from an obfuscated mod's string constants rather than from its
  registration code. Rebuild for a different library with
  <code>scripts/commands.py</code>.</p>"""

SCRIPT = r"""
const DATA = __DATA__;
const list = document.getElementById('list');
const q = document.getElementById('q');
const countEl = document.getElementById('count');
const empty = document.getElementById('empty');
const emptyq = document.getElementById('emptyq');
const fCheat = document.getElementById('f-cheat');
const fSure = document.getElementById('f-sure');
const fClear = document.getElementById('f-clear');

function build(){
  const frag = document.createDocumentFragment();
  for (const mod of DATA){
    const sec = document.createElement('section');
    sec.className = 'card';
    const rows = mod.commands.map(c => {
      const args = c.args ? ' <span class="arg">' + esc(c.args) + '</span>' : '';
      const flags = [];
      if (c.cheat) flags.push('<span class="flag f-cheat">needs cheats</span>');
      if (c.uncertain) flags.push('<span class="flag f-soft">uncertain</span>');
      if (c.unverified) flags.push('<span class="flag f-soft">unverified</span>');
      return '<div class="row" data-cheat="' + (c.cheat?1:0) +
        '" data-sure="' + ((c.uncertain||c.unverified)?0:1) +
        '" data-hay="' + esc((c.cmd+' '+c.desc+' '+mod.mod).toLowerCase()) + '">' +
        '<button class="cmd" type="button" data-copy="' + esc(c.cmd) + '">' +
          esc(c.cmd) + args + '</button>' +
        '<div class="desc">' + esc(c.desc) + '</div>' +
        '<div class="flags">' + flags.join('') + '</div></div>';
    }).join('');
    sec.innerHTML =
      '<header><h2>' + esc(mod.mod) + '</h2>' +
      '<span class="n">' + mod.commands.length + '</span>' +
      (mod.summary ? '<p>' + esc(mod.summary) + '</p>' : '') +
      '</header><div class="rows">' + rows + '</div>';
    frag.appendChild(sec);
  }
  list.appendChild(frag);
}

function apply(){
  const term = q.value.trim().toLowerCase();
  const onlyCheat = on(fCheat), onlySure = on(fSure);
  let shown = 0, mods = 0;
  for (const sec of list.children){
    let vis = 0;
    for (const row of sec.querySelector('.rows').children){
      let ok = !term || row.dataset.hay.includes(term);
      if (ok && onlyCheat && row.dataset.cheat !== '1') ok = false;
      if (ok && onlySure && row.dataset.sure !== '1') ok = false;
      row.hidden = !ok;
      if (ok) vis++;
    }
    sec.hidden = vis === 0;
    if (vis){ mods++; shown += vis; sec.querySelector('.n').textContent = vis; }
  }
  countEl.textContent = shown.toLocaleString() + ' command' + (shown===1?'':'s')
    + ' · ' + mods + ' mod' + (mods===1?'':'s');
  empty.hidden = shown !== 0;
  emptyq.textContent = term
    ? 'No command, description or mod contains “' + q.value.trim() + '”.'
    : 'No command matches those filters.';
}

build();
apply();
wireSearch(q, apply);
wireChip(fCheat, apply);
wireChip(fSure, apply);
fClear.addEventListener('click', () => {
  q.value = '';
  fCheat.setAttribute('aria-pressed','false');
  fSure.setAttribute('aria-pressed','false');
  apply(); q.focus();
});

/* Clipboard can be blocked in a sandboxed frame. Selecting the text is a real
   fallback - the player can still hit Ctrl+C - so never claim "copied" unless
   the write actually resolved. */
list.addEventListener('click', async e => {
  const btn = e.target.closest('.cmd');
  if (!btn) return;
  let done = false;
  try {
    if (navigator.clipboard){
      await navigator.clipboard.writeText(btn.dataset.copy); done = true;
    }
  } catch (_) { done = false; }
  if (!done){
    const r = document.createRange();
    r.selectNodeContents(btn);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
  } else {
    btn.classList.add('copied');
    setTimeout(() => btn.classList.remove('copied'), 1100);
  }
});
"""


def load_curated(paths):
    mods = {}
    for p in paths:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        for entry in data.get('mods', []):
            slot = mods.setdefault(entry['mod'], {'summary': '', 'commands': {}})
            if entry.get('summary') and not slot['summary']:
                slot['summary'] = entry['summary']
            for c in entry.get('commands', []):
                slot['commands'][c['cmd']] = c
    return mods


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('curated', nargs='+')
    ap.add_argument('--out', required=True,
                    help='where to write the page (outside the repo)')
    ap.add_argument('--include-adult', action='store_true',
                    help='keep adult mods in the page (default: omit them)')
    ap.add_argument('--no-verify', action='store_true')
    a = ap.parse_args()

    paths = []
    for pat in a.curated:
        paths.extend(sorted(glob.glob(pat)) or [pat])
    mods = load_curated(paths)

    raw, raw_total = {}, 0
    if not a.no_verify:
        import commands as C
        scan = C.scan_all()
        raw_total = sum(len(v) for v in scan.values())
        for m, cmds in scan.items():
            for c, info in cmds.items():
                raw[c] = info.get('via')

    if not a.include_adult:
        import commands_doc
        pat = commands_doc.adult_pattern()
        if pat is None:
            sys.exit('cannot load the adult pattern set; refusing to guess')
        for m in list(mods):
            if pat.search(m):
                del mods[m]

    out, dropped, total = [], 0, 0
    for m in sorted(mods, key=lambda x: x.lower()):
        cmds = []
        for name in sorted(mods[m]['commands']):
            c = mods[m]['commands'][name]
            if raw and name not in raw:
                dropped += 1
                continue
            cmds.append({'cmd': name, 'desc': c['desc'],
                         'args': c.get('args') or '',
                         'cheat': bool(c.get('cheat')),
                         'uncertain': bool(c.get('uncertain')),
                         'unverified': raw.get(name) == 'strings'})
        if cmds:
            out.append({'mod': m, 'summary': mods[m].get('summary') or '',
                        'commands': cmds})
            total += len(cmds)

    page = report_style.page(
        title='Console Commands Report',
        placeholder='Search commands, descriptions, mods…',
        chips_html=CHIPS,
        note_html=NOTE,
        body_html='<div id="list"></div>',
        footer_html=(FOOTER.replace('__TOTAL__', f'{total:,}')
                     .replace('__RAW__', f'{raw_total:,}' if raw_total else 'all')
                     .replace('__MODS__', str(len(out)))),
        script=SCRIPT.replace('__DATA__', json.dumps(out, ensure_ascii=False)),
        extra_css=EXTRA_CSS)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(page)
    print(f'wrote {a.out}: {total} command(s) across {len(out)} mod(s)'
          + (f', {dropped} unverifiable dropped' if dropped else ''))


if __name__ == '__main__':
    main()
