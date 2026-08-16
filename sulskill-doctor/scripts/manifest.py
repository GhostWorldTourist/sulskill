#!/usr/bin/env python3
"""Describe every installed mod, from the mods themselves.

The best offline description of a mod is its own UI text. A mod that adds "Ask
to Cook Dinner" ships that string in a STBL; a trait mod ships the trait's name
and description. So this reads each package's string table and tuning class
names and synthesises a one-line summary. No network, no API key, no guessing
from filenames alone.

Accuracy expectations, stated plainly: this is a useful index, not a catalogue.
A CAS or build-mode package often has no descriptive text at all and gets
summarised from its resource mix instead ("42 CAS parts"). Script mods are
opaque without their tuning. Treat every line as a hint.

NSFW handling
-------------
--hide-nsfw omits adult mods entirely - they are not listed, not counted in the
body, only tallied so the numbers still add up. The classifier is the same
pattern set the SFW-profile work uses, and it errs toward marking things adult:
a false positive costs a line in a report, a false negative puts porn in a
document that might be shared.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import collections
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'sulskill-modbuild', 'scripts'))

SIMS = os.environ.get('SIMS4_DIR') or os.path.join(
    os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')

TYPES = {
    0x220557DA: 'STBL', 0xCB5FDDC7: 'Trait', 0x6017E896: 'Buff',
    0x0C772E27: 'Loot', 0xE882D22F: 'Interaction', 0x7DF2169C: 'Snippet',
    0x545AC67A: 'SimData', 0x034AEECB: 'CAS part', 0x00B2D882: 'Image',
    0x319E4F1D: 'Object catalog', 0xD382BF57: 'Object def',
    0x02D5DF13: 'Model', 0x01D0E75D: 'Model LOD', 0x3C1AF1F2: 'Thumbnail',
    0x62E94D38: 'Combined tuning', 0x02019972: 'Region',
}

# The pattern set lives in classify_adult.py and is IMPORTED, never retyped. A
# hand-copy that drops one alternation branch leaks that whole prefix silently.
def _load_patterns():
    src = os.path.join(HERE, 'classify_adult.py')
    ns = {}
    try:
        text = open(src, encoding='utf-8').read()
        block = re.search(r'^CERTAIN = re\.compile\(.*?^\]\), re\.I\)',
                          text, re.S | re.M)
        if block:
            exec('import re\n' + block.group(), ns)
            return ns['CERTAIN']
    except Exception:
        pass
    return None


NSFW = _load_patterns() or re.compile(
    r'wicked|turbodriver|nisa|perversion|\bnude\b|naked|\bporn|erotic', re.I)

# Filenames alone are not enough. A mod's own description can be explicit while
# its filename is neutral, so the extracted text is screened too.
NSFW_TEXT = re.compile(
    r'\bsex\b|sex toy|gloryhole|\bnude|naked|penis|vagina|nipple|orgasm|'
    r'\bhorny\b|blowjob|handjob|anal\b|masturbat|fetish|bdsm|strip(per|tease)|'
    r'\bporn|escort|brothel|prostitut|erotic|lewd|genital|\bcum\b|'
    r'orientation:\s*(straight|lesbian|gay|bi)|'
    # An adult mod's description usually names the framework it plugs into.
    r'wicked\s*whims|wickedwhims|\bWW\b\s*(anim|mod)|turbodriver|'
    r'wicked\s*perversions|basemental', re.I)

# Shared-framework boilerplate. Several mods embed the same settings blurbs
# (start-up notifications, debug toggles), and those score well on the
# sentence heuristic while saying nothing about the mod.
BOILERPLATE = re.compile(
    r'enable this setting|disable this setting|start-?up notification|'
    r'properly installed the mod|check for updates|report any issues|'
    r'this mod (is|was) (made|created)|thank you for (using|downloading)|'
    r'join (my|our) discord|patreon|debug (mode|cheats?)', re.I)

# Strings that are UI furniture rather than description
NOISE = re.compile(r'^(ok|cancel|yes|no|close|back|next|on|off|none|default|'
                   r'\d+|\W+)$', re.I)
CREATOR = re.compile(r'^([A-Za-z0-9]{2,20})[_\- ]')

# Data rows pass the length-and-space test as easily as prose does ("73F,
# Scattered Thunderstorms"). One function word separates a sentence from a row
# of values.
PROSE = re.compile(
    r'\b(a|an|the|to|of|for|with|when|that|which|will|can|is|are|be|been|'
    r'you|your|they|their|this|these|and|but|from|has|have|it|its|on|in|at|'
    r'not|now|no longer|allows?|lets|makes|adds|removes|instead|so|if)\b')
# A degree sign only ever appears in a temperature readout.
DEGREES = re.compile(r'[°]')

# Fallback for packages that hold no self-description at all - every string in
# them is data, so any heuristic quotes a value. Keep this small.
KNOWN_DESC = [
    (re.compile(r'^WRO[ _]', re.I),
     'Weather Realism Overhaul: real-world temperature ranges, forecasts and '
     'seasonal weather patterns replacing the default weather model.'),
]


def load_stbls(path):
    import stbl
    import refpack                                              # noqa: F401
    out = {}
    try:
        for blob in stbl.read_stbls(path):
            try:
                out.update(stbl.parse(blob))
            except Exception:
                pass
    except Exception:
        pass
    return out


def describe(path):
    """-> (summary, counts, sample_strings)"""
    import dbpf
    import refpack
    counts = collections.Counter()
    strings, names = [], []
    try:
        with open(path, 'rb') as f:
            head = f.read(96)
            if head[:4] != b'DBPF':
                return 'not a DBPF package', counts, []
    except OSError as e:
        return f'unreadable: {e}', counts, []

    try:
        for t, g, i, blob in dbpf.read(path):
            counts[TYPES.get(t, f'0x{t:08X}')] += 1
            if t == 0x220557DA:
                # Packages ship one STBL per locale, and the high byte of the
                # instance id IS the locale index - 0x00 is ENG_US. Without this
                # filter the "best" sentence is whichever language happened to
                # sort first, so descriptions come back in Italian or Polish.
                if (i >> 56) != 0:
                    continue
                try:
                    import stbl
                    for s in stbl.parse(blob).values():
                        if s and not NOISE.match(s.strip()):
                            strings.append(s.strip())
                except Exception:
                    pass
            elif blob[:5] == b'<?xml' and len(names) < 40:
                m = re.search(rb'<I c="([^"]+)"[^>]*n="([^"]+)"', blob)
                if m:
                    names.append((m.group(1).decode(), m.group(2).decode()))
    except Exception:
        pass

    # Prefer a real sentence; fall back to the longest label.
    sentences = [s for s in strings if 25 <= len(s) <= 220 and ' ' in s
                 and not s.startswith('{') and not BOILERPLATE.search(s)
                 and PROSE.search(s) and not DEGREES.search(s)]
    sentences.sort(key=lambda s: (s.count(' '), len(s)), reverse=True)
    labels = sorted({s for s in strings if 3 <= len(s) <= 60
                     and not DEGREES.search(s)},
                    key=len, reverse=True)

    for pat, text in KNOWN_DESC:
        if pat.search(os.path.basename(path)):
            return text, counts, labels[:6]

    if sentences:
        summary = sentences[0]
    elif labels:
        summary = 'adds: ' + ', '.join(labels[:4])
    elif names:
        kinds = collections.Counter(c for c, _ in names)
        summary = 'tuning: ' + ', '.join(f'{k} x{v}' for k, v in kinds.most_common(3))
    else:
        top = [f'{v} {k}' for k, v in counts.most_common(3)]
        summary = ', '.join(top) if top else 'no readable content'
    return summary, counts, labels[:6]


def creator_of(name):
    m = CREATOR.match(name)
    return m.group(1) if m else ''


KNOWN_PREFIX = re.compile(
    r'^(MTS_|RVSN_|Tmex-|\[Kuttoe\] ?|Andirz_|frankk_|LittleMsSam_|Zerbu[ _-]?|'
    r'sims4me_|TURBODRIVER_|NisaK_|PECO_|SCUMBUMBO_)', re.I)
VERSION_TAIL = re.compile(r'([_\- ]?v?[\d.]+)?(_?(FIXED|UPDATED|Official|Patreon))?$', re.I)


def title_from_filename(name):
    """A readable title from a filename.

    Tuning-only mods ship no descriptive strings at all, but their filenames are
    often the clearest statement of intent in the whole package -
    'KeepBooksAfterPublishing' says more than '6 SuperInteraction'. Strip the
    creator prefix and version tail, then split CamelCase and underscores.
    """
    n = os.path.splitext(name)[0]
    n = KNOWN_PREFIX.sub('', n)
    n = re.sub(r'_(Updated|Fixed)By\w+', '', n, flags=re.I)
    n = VERSION_TAIL.sub('', n)
    n = re.sub(r'[_\-]+', ' ', n)
    n = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', default=os.path.join(SIMS, 'Mods'))
    ap.add_argument('--hide-nsfw', action='store_true',
                    help='omit adult mods entirely (still counted in the total)')
    ap.add_argument('--only', help='substring filter on filename')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--html', metavar='OUT', help='write an HTML report')
    ap.add_argument('--scripts', action='store_true',
                    help='include .ts4script files (described by module names)')
    a = ap.parse_args()

    files = []
    for dp, _, fn in os.walk(a.root):
        for f in sorted(fn):
            if f.lower().endswith('.package') or (
                    a.scripts and f.lower().endswith('.ts4script')):
                files.append(os.path.join(dp, f))
    if a.only:
        files = [f for f in files if a.only.lower() in os.path.basename(f).lower()]
    files.sort(key=lambda p: os.path.basename(p).lower())
    if a.limit:
        files = files[:a.limit]

    rows, hidden = [], 0
    for p in files:
        base = os.path.basename(p)
        rel = os.path.relpath(p, a.root)
        if p.lower().endswith('.ts4script'):
            import zipfile
            try:
                z = zipfile.ZipFile(p)
                mods = sorted({n.split('/')[0] for n in z.namelist()
                               if n.endswith('.pyc')})
                summary = 'script mod: ' + ', '.join(mods[:3])
            except Exception as e:
                summary = f'script mod (unreadable: {e})'
            counts, labels = collections.Counter(), []
        else:
            summary, counts, labels = describe(p)
        title = title_from_filename(base)
        # Prefer the mod's own prose. Fall back to the filename title, which for
        # tuning-only mods is usually the clearest statement of intent there is.
        weak = summary.startswith(('tuning:', 'adds:')) or re.match(
            r'^[\d, ]*(Interaction|Buff|Snippet|SimData|CAS part|Image|Model)',
            summary)
        if weak and title:
            summary = f'{title} - {summary}'
        elif not summary or summary == 'no readable content':
            summary = title or '(no description available)'

        # Classify AFTER describing, and screen the description as well as the
        # path. A filename can be perfectly innocent while the mod's own text is
        # explicit - 'Noir Sex Toy - 01' and a gloryhole bar both slipped through
        # a filename-only check, as did every CRL&PC_ porn clip whose text reads
        # 'Orientation: Straight'.
        if (NSFW.search(base) or NSFW.search(rel)
                or NSFW_TEXT.search(base) or NSFW_TEXT.search(summary)):
            hidden += 1
            if a.hide_nsfw:
                continue

        rows.append({
            'file': base, 'dir': os.path.dirname(rel) or '.', 'title': title,
            'size': os.path.getsize(p), 'creator': creator_of(base),
            'summary': summary, 'counts': dict(counts.most_common(4)),
        })

    if a.html:
        write_html(a.html, rows, hidden, a.hide_nsfw)
        print(f'wrote {a.html}  ({len(rows)} mods'
              + (f', {hidden} adult omitted)' if a.hide_nsfw else ')'))
        return

    print(f'{len(rows)} mod(s)'
          + (f'   [{hidden} adult mods omitted]' if a.hide_nsfw else
             f'   [{hidden} flagged adult]') + '\n')
    for r in rows:
        who = f" ({r['creator']})" if r['creator'] else ''
        print(f"{r['file']}{who}  {r['size']:,}b")
        print(f"    {r['summary'][:160]}")


EXTRA_CSS = ('.row{grid-template-columns:minmax(0,30rem) 11rem minmax(0,1fr) '
             '7rem;padding:11px 20px;gap:20px}')

CHIPS = """
      <button class="chip" id="f-script" aria-pressed="false">Script mods</button>
      <button class="chip" id="f-desc" aria-pressed="false">Described only</button>
      <button class="chip" id="f-clear" aria-pressed="false">Reset</button>"""

NOTE = ('Every installed mod, described from its own string tables and tuning. '
        'Treat each line as a hint: build and CAS packages often carry no text '
        'to read, and are summarised from what is inside them instead.')

SCRIPT = r"""
const DATA = __DATA__;
const list = document.getElementById('list');
const q = document.getElementById('q');
const countEl = document.getElementById('count');
const empty = document.getElementById('empty');
const emptyq = document.getElementById('emptyq');
const fScript = document.getElementById('f-script');
const fDesc = document.getElementById('f-desc');
const fClear = document.getElementById('f-clear');
const kb = n => n >= 1048576 ? (n/1048576).toFixed(1) + ' MB'
                             : Math.max(1, Math.round(n/1024)) + ' KB';

function build(){
  const rows = DATA.map(r =>
    '<div class="row" data-script="' + (r.s?1:0) + '" data-desc="' + (r.d?1:0) +
    '" data-hay="' + esc((r.f+' '+r.c+' '+r.t).toLowerCase()) + '">' +
    '<div class="name mono">' + esc(r.f) + '</div>' +
    '<div class="who">' + esc(r.c) + '</div>' +
    '<div class="desc' + (r.d ? '' : ' muted') + '">' + esc(r.t) + '</div>' +
    '<div class="num">' + kb(r.z) + '</div></div>').join('');
  list.innerHTML =
    '<section class="card"><header><h2>Installed mods</h2>' +
    '<span class="n" id="secn"></span></header>' +
    '<div class="rows">' + rows + '</div></section>';
}

function apply(){
  const term = q.value.trim().toLowerCase();
  const onlyScript = on(fScript), onlyDesc = on(fDesc);
  let shown = 0;
  for (const row of list.querySelector('.rows').children){
    let ok = !term || row.dataset.hay.includes(term);
    if (ok && onlyScript && row.dataset.script !== '1') ok = false;
    if (ok && onlyDesc && row.dataset.desc !== '1') ok = false;
    row.hidden = !ok;
    if (ok) shown++;
  }
  countEl.textContent = shown.toLocaleString() + ' of '
    + DATA.length.toLocaleString() + ' mods';
  document.getElementById('secn').textContent = shown.toLocaleString();
  list.querySelector('.card').hidden = shown === 0;
  empty.hidden = shown !== 0;
  emptyq.textContent = term
    ? 'No mod, creator or description contains “' + q.value.trim() + '”.'
    : 'No mod matches those filters.';
}

build();
apply();
wireSearch(q, apply);
wireChip(fScript, apply);
wireChip(fDesc, apply);
fClear.addEventListener('click', () => {
  q.value = '';
  fScript.setAttribute('aria-pressed','false');
  fDesc.setAttribute('aria-pressed','false');
  apply(); q.focus();
});
"""


def write_html(out, rows, hidden, hide):
    # When hiding, the report must not advertise that anything was hidden -
    # "831 adult mods omitted" tells a reader exactly what it was meant to keep
    # private. Hidden rows simply do not exist as far as the document is aware.
    import json
    import report_style

    # A summary that fell back to counting resources ("42 CAS parts", "adds:
    # ...") is not a description; mark it so it can be filtered out and shown
    # in muted type rather than passed off as one.
    def described(s):
        return not (s.startswith(('adds:', 'tuning:')) or ' resource' in s
                    or s.endswith(('CAS part', 'CAS parts'))
                    or s in ('no readable content', 'not a DBPF package'))

    data = [{'f': r['file'], 'c': r['creator'], 't': r['summary'][:300],
             'z': r['size'], 's': r['file'].lower().endswith('.ts4script'),
             'd': described(r['summary'])} for r in rows]

    total_note = (f"{len(rows):,} mods"
                  + ("" if hide else f" &middot; {hidden} flagged adult"))
    page = report_style.page(
        title='Mod Manifest Report',
        placeholder='Search mods, creators, descriptions…',
        chips_html=CHIPS,
        note_html=NOTE,
        body_html='<div id="list"></div>',
        footer_html=(f'<p><strong>SulSkill</strong> &mdash; {total_note}, each '
                     'described from its own resources rather than from a '
                     'listing. Rebuild with <code>scripts/manifest.py</code>.</p>'),
        script=SCRIPT.replace('__DATA__', json.dumps(data, ensure_ascii=False)),
        extra_css=EXTRA_CSS)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(page)


if __name__ == '__main__':
    main()
