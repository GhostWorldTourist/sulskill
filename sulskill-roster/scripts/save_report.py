"""A page about your save: who lives in your world, where, and how they got on.

Reads a `.save` with savegame.py and writes one self-contained HTML file. It is
about the *world*, not the mod library - the population by life stage, the
money, which neighbourhoods filled up and which never got touched, the families
that grew and the ones that never left the unhoused pool.

Every number on the page is counted from the save in front of it. Nothing is
estimated, and the page ends with a section saying exactly which fields were
read and how they were checked, because a report about somebody's game should
be able to show its working.

    py scripts/save_report.py --out ~/Downloads/save.html
    py scripts/save_report.py --slot Slot_00000002.save --out ~/Downloads/s2.html
    py scripts/save_report.py --list
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                  '..', '..', 'sulskill-doctor', 'scripts'))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import datetime
import html
import json
import os
import sys

import savegame
import report_style
import rquery


# What a query may ask about. The page and `--query` share this, so a query
# that works in one works in the other - and an unknown field is an error in
# both rather than a silent empty result.
SCHEMA = {
    'name': rquery.TEXT,        # household name
    'world': rquery.TEXT,
    'lot': rquery.TEXT,
    'creator': rquery.TEXT,
    'member': rquery.LIST,      # any Sim in it, by name
    'gender': rquery.LIST,      # any member's gender
    'age': rquery.LIST,         # any member's life stage
    'species': rquery.LIST,     # any member's species
    'funds': rquery.NUMBER,
    'size': rquery.NUMBER,      # everybody, pets included
    'people': rquery.NUMBER,
    'pets': rquery.NUMBER,
    'housed': rquery.BOOL,
}
FREE_FIELDS = ('name', 'member', 'world', 'lot')

CHIPS = """
      <button class="chip" id="f-housed" aria-pressed="false">Housed</button>
      <button class="chip" id="f-unhoused" aria-pressed="false">No home</button>
      <label class="wealth" for="f-wealth">Funds at least
        <output id="f-wealthout">§0</output>
        <input type="range" id="f-wealth" min="0" max="__MAXFUNDS__"
               step="__STEP__" value="0" aria-label="Minimum household funds">
      </label>
      <button class="chip" id="f-clear" aria-pressed="false">Reset</button>
      <p class="qerr" id="qerr" hidden></p>"""

EXTRA_CSS = r"""
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:14px;margin:0 0 26px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:14px 16px;box-shadow:var(--shadow)}
.stat b{display:block;font-size:26px;line-height:1.15;color:var(--ink);
  font-variant-numeric:tabular-nums}
.stat span{display:block;font-size:12.5px;color:var(--ink-2);margin-top:3px}
.stat em{display:block;font-size:11.5px;color:var(--soft);font-style:normal;
  margin-top:6px}
h2{font-size:17px;margin:30px 0 12px;color:var(--ink)}
h2 small{font-weight:400;font-size:13px;color:var(--ink-2);margin-left:8px}
.ages{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:16px 18px;box-shadow:var(--shadow);margin-bottom:26px}
.age{display:grid;grid-template-columns:96px 1fr 56px;gap:12px;
  align-items:center;padding:4px 0}
.age .lbl{font-size:13.5px;color:var(--ink-2)}
.age .n{font-size:13.5px;text-align:right;font-variant-numeric:tabular-nums;
  color:var(--ink)}
.track{background:var(--panel-3);border-radius:6px;height:16px;overflow:hidden;
  display:flex}
.track i{display:block;height:100%}
.track .m{background:var(--focus)}
.track .f{background:var(--plumbob)}
.key{display:flex;gap:16px;font-size:12.5px;color:var(--ink-2);
  margin:10px 0 0;align-items:center}
.key b{display:inline-block;width:10px;height:10px;border-radius:3px;
  margin-right:5px;vertical-align:-1px}
.wrow{grid-template-columns:1fr 90px 90px 90px}
.hrow{grid-template-columns:1fr 150px 90px 110px}
.rows header.row{border-top:0;font-size:12px;text-transform:uppercase;
  letter-spacing:.06em;color:var(--soft);background:var(--panel-2)}
.prov{background:var(--panel-2);border:1px solid var(--line);border-radius:12px;
  padding:18px 20px;margin:30px 0 0;font-size:14px;color:var(--ink-2)}
.prov h3{margin:0 0 10px;font-size:14.5px;color:var(--ink)}
.prov li{margin:5px 0}
.prov code{font-size:12.5px;background:var(--panel-3);padding:1px 5px;
  border-radius:4px}
.wealth{display:flex;align-items:center;gap:8px;font-size:13px;
  color:var(--ink-2);white-space:nowrap}
.wealth output{font-variant-numeric:tabular-nums;color:var(--ink);
  min-width:74px;display:inline-block}
.wealth input[type=range]{accent-color:var(--plumbob);width:150px;
  vertical-align:middle}
.wrow{cursor:pointer}
.wrow:hover{background:var(--panel-3)}
.wrow[aria-pressed="true"]{background:var(--plumbob-wash);
  box-shadow:inset 3px 0 0 var(--plumbob)}
.rows header.wrow{cursor:default}
.rows header.wrow:hover{background:var(--panel-2)}
/* In the sticky bar, not in the page body: an error about what you are
   typing has to be visible from where you are typing it. */
.qerr{flex-basis:100%;margin:2px 0 0;padding:8px 13px;border-radius:9px;
  font-size:13.5px;background:var(--cheat-wash);color:var(--cheat);
  border:1px solid var(--cheat)}
.qerr[hidden]{display:none}
.qerr code{background:transparent;padding:0}
.qhint{margin:0 0 14px;font-size:13px;color:var(--soft)}
.qhint b{color:var(--ink-2);font-weight:600}
.qhint code{background:var(--panel-3);padding:1px 5px;border-radius:4px;
  cursor:pointer}
.qhint code:hover{background:var(--plumbob-wash);color:var(--plumbob-ink)}
.ok{color:var(--plumbob-ink)}
.bad{color:var(--cheat)}
"""

# Uses the helpers report_style.SCRIPT already defines - esc, wireChip, on,
# wireSearch - rather than its own. They share one <script> block, so a second
# `const esc` here is not a shadowed copy, it is a SyntaxError that stops the
# whole block and silently leaves the page with no list on it.
# Uses the helpers report_style.SCRIPT already defines - esc, wireChip, on,
# wireSearch - rather than its own. They share one <script> block, so a second
# `const esc` here is not a shadowed copy, it is a SyntaxError that stops the
# whole block and silently leaves the page with no list on it.
SCRIPT = r"""
const HH = __DATA__;
const SCHEMA = __SCHEMA__;
const FREE = __FREE__;
const EXAMPLES = __EXAMPLES__;
const list = document.getElementById('list');
const q = document.getElementById('q');
const qerr = document.getElementById('qerr');
const cHoused = document.getElementById('f-housed');
const cNoHome = document.getElementById('f-unhoused');
const wealth = document.getElementById('f-wealth');
const wealthOut = document.getElementById('f-wealthout');
let world = null;

function money(n){ return '\u00A7' + n.toLocaleString(); }

function render(){
  const text = (q.value || '').trim();
  let node = ['all'];
  qerr.hidden = true;
  if(text){
    try {
      node = rqParse(text, SCHEMA);
    } catch (e) {
      // Say what is wrong and show NOTHING, rather than falling back to a
      // plain-text search: a query with a typo that silently degrades into a
      // different question is worse than one that refuses.
      qerr.hidden = false;
      qerr.innerHTML = '<strong>That query did not parse.</strong> '
        + esc(e.message);
      list.innerHTML = '';
      document.getElementById('count').textContent = 'query error';
      document.getElementById('empty').hidden = true;
      return;
    }
  }
  const wantHoused = on(cHoused), wantNoHome = on(cNoHome);
  const floor = Number(wealth.value) || 0;
  let rows = '', n = 0;
  for(const h of HH){
    if(wantHoused && !h.housed) continue;
    if(wantNoHome && h.housed) continue;
    if(world !== null && h.world !== world) continue;
    if(h.funds < floor) continue;
    if(!rqMatch(node, h, SCHEMA, FREE)) continue;
    n++;
    rows += '<div class="row hrow"><div><div class="desc">' + esc(h.name)
      + '</div><div class="name muted">' + esc(h.member.join(', ') || 'nobody')
      + '</div></div><div class="name">'
      + (h.housed ? esc(h.lot) + '<br><span class="muted">' + esc(h.world)
                    + '</span>'
                  : '<span class="muted">no home</span>')
      + '</div><div class="num">' + h.size + '</div>'
      + '<div class="num">' + money(h.funds) + '</div></div>';
  }
  list.innerHTML = n ? ('<div class="card"><div class="rows">'
    + '<header class="row hrow"><div>Household</div><div>Lives at</div>'
    + '<div class="num">Sims</div><div class="num">Funds</div></header>'
    + rows + '</div></div>') : '';
  document.getElementById('count').textContent =
    n + ' of ' + HH.length + ' households'
    + (world !== null ? ' in ' + world : '');
  document.getElementById('empty').hidden = n > 0;
  document.getElementById('emptyq').textContent =
    text ? '\u201C' + text + '\u201D' : '';
}

// Clicking a neighbourhood filters the list to it; clicking it again clears.
// The whole row is the control, so it carries button semantics rather than
// looking clickable and being unreachable from a keyboard.
for(const row of document.querySelectorAll('.wrow[data-world]')){
  const pick = () => {
    const name = row.getAttribute('data-world');
    world = (world === name) ? null : name;
    for(const other of document.querySelectorAll('.wrow[data-world]'))
      other.setAttribute('aria-pressed',
        other.getAttribute('data-world') === world ? 'true' : 'false');
    render();
    if(world !== null) list.scrollIntoView({behavior:'smooth', block:'start'});
  };
  row.addEventListener('click', pick);
  row.addEventListener('keydown', e => {
    if(e.key === 'Enter' || e.key === ' '){ e.preventDefault(); pick(); }
  });
}

function syncWealth(){ wealthOut.textContent = money(Number(wealth.value)||0); }
wealth.addEventListener('input', () => { syncWealth(); render(); });

wireChip(cHoused, () => {
  if(on(cHoused)) cNoHome.setAttribute('aria-pressed','false');
  render();
});
wireChip(cNoHome, () => {
  if(on(cNoHome)) cHoused.setAttribute('aria-pressed','false');
  render();
});
document.getElementById('f-clear').addEventListener('click', () => {
  for(const c of [cHoused, cNoHome]) c.setAttribute('aria-pressed','false');
  for(const other of document.querySelectorAll('.wrow[data-world]'))
    other.setAttribute('aria-pressed','false');
  world = null;
  wealth.value = 0; syncWealth();
  q.value = ''; render();
});
wireSearch(q, render);

// Clicking an example loads it, so the language is discoverable by poking at
// it rather than by reading a grammar.
for(const el of document.querySelectorAll('.qhint code')){
  el.addEventListener('click', () => {
    q.value = el.textContent; q.focus(); render();
  });
}

// ?q=... so an agent can hand somebody a link that opens on the answer.
const fromUrl = new URLSearchParams(location.search).get('q');
if(fromUrl){ q.value = fromUrl; }

syncWealth();
render();
"""


def money(n):
    return '§' + format(int(n or 0), ',')


def stat(value, label, note=''):
    em = '<em>%s</em>' % html.escape(note) if note else ''
    return ('<div class="stat"><b>%s</b><span>%s</span>%s</div>'
            % (html.escape(str(value)), html.escape(label), em))


def age_bars(save):
    """Life stages, youngest to oldest, split by gender within each bar."""
    rows = []
    counts = save.by_age()
    top = max((n for _a, n in counts), default=1)
    for age, n in counts:
        of_age = [s for s in save.sims if s['age'] == age]
        male = sum(1 for s in of_age if save.gender_name(s) == 'Male')
        female = n - male
        width = 100.0 * n / top
        m_pct = (100.0 * male / n) if n else 0
        rows.append(
            '<div class="age"><div class="lbl">%s</div>'
            '<div class="track" style="width:%.1f%%">'
            '<i class="m" style="width:%.1f%%"></i>'
            '<i class="f" style="width:%.1f%%"></i></div>'
            '<div class="n">%d</div></div>'
            % (html.escape(save.ages.get(age, 'Value %s' % age)),
               width, m_pct, 100 - m_pct, n))
    key = ('<p class="key"><span><b class="m" style="background:var(--focus)">'
           '</b>Male</span><span><b class="f" '
           'style="background:var(--plumbob)"></b>Female</span></p>')
    return '<div class="ages">' + ''.join(rows) + key + '</div>'


def world_rows(save):
    worlds = sorted(save.worlds,
                    key=lambda w: (-w['population'], w['name'].lower()))
    body = []
    for w in worlds:
        occupied = sum(1 for l in w['lots'] if l['household'])
        empty_note = '' if w['households'] else ' class="muted"'
        name = w['name'] or '(unnamed)'
        # A world with nobody in it has nothing to filter to, so it is not a
        # control - making it one would offer an empty list as a result.
        clickable = bool(w['households'])
        attrs = ('' if not clickable else
                 ' data-world="%s" role="button" tabindex="0" '
                 'aria-pressed="false"' % html.escape(name, quote=True))
        body.append(
            '<div class="row wrow%s"%s><div%s>%s</div>'
            '<div class="num">%d</div><div class="num">%d</div>'
            '<div class="num">%d</div></div>'
            % ('' if clickable else ' quiet', attrs, empty_note,
               html.escape(name), len(w['lots']), occupied, w['population']))
    return ('<div class="card"><div class="rows">'
            '<header class="row wrow quiet"><div>World</div>'
            '<div class="num">Lots</div><div class="num">Lived in</div>'
            '<div class="num">Sims</div></header>'
            + ''.join(body) + '</div></div>')


def pet_row(save):
    """The animals, if there are any. Silent when there are none rather than
    printing a row of zeroes about a household that has never owned a cat."""
    pets = save.pets()
    if not pets:
        return ''
    counts = save.by_species()
    chips = ''.join(
        '<div class="stat"><b>%d</b><span>%s%s</span></div>'
        % (n, html.escape(save.species.get(sp, 'Unknown')),
           '' if n == 1 else 's')
        for sp, n in counts)
    withpets = len({id(s['household']) for s in pets if s['household']})
    return ('<h2>Animals <small>%d in %d household%s</small></h2>'
            '<div class="stats">%s</div>'
            % (len(pets), withpets, '' if withpets == 1 else 's', chips))


def notable(save):
    """The handful of facts worth reading before any table."""
    out = []
    housed = save.housed()
    if save.households:
        big = max(save.households, key=lambda h: len(h['members']))
        if big['members']:
            out.append(('Largest household', '%s, %d Sims'
                        % (big['name'], len(big['members']))))
        rich = max(save.households, key=lambda h: h['funds'] or 0)
        out.append(('Richest household',
                    '%s, %s' % (rich['name'], money(rich['funds']))))
        broke = [h for h in housed if not h['funds']]
        if broke:
            out.append(('Households with nothing',
                        '%d living on §0' % len(broke)))
    names = save.surnames(1)
    if names:
        out.append(('Most common surname',
                    '%s, %d Sims' % (names[0][0], names[0][1])))
    empty_worlds = [w for w in save.worlds if not w['households']]
    if empty_worlds:
        out.append(('Worlds with nobody in them',
                    '%d of %d' % (len(empty_worlds), len(save.worlds))))
    rows = ''.join(
        '<div class="row" style="grid-template-columns:220px 1fr">'
        '<div class="name muted">%s</div><div class="desc">%s</div></div>'
        % (html.escape(k), html.escape(v)) for k, v in out)
    return '<div class="card"><div class="rows">' + rows + '</div></div>'


def provenance(save, complaints):
    """What was read, and how it was checked. The page shows its working."""
    if complaints:
        verdict = ('<p class="bad"><strong>Some checks did not pass.</strong> '
                   'Treat the affected numbers with suspicion - a game patch '
                   'may have renumbered a field:</p><ul>%s</ul>'
                   % ''.join('<li>%s</li>' % html.escape(c)
                             for c in complaints))
    else:
        verdict = ('<p class="ok"><strong>Every check passed.</strong> '
                   'The joins below were re-run against this save when the '
                   'page was built.</p>')
    joined = sum(1 for s in save.sims if s['household'])
    in_world = sum(1 for l in save.lots if l['world'])
    return f"""<div class="prov">
  <h3>How this page was read</h3>
  <p>A <code>.save</code> is a DBPF package. Everything above comes from the
  one resource inside it of type <code>0x0000000D</code>, a single protobuf
  message holding the whole simulated world. There is no published schema for
  it, so each field was established by reading real saves and then checked in a
  way that could fail.</p>
  <p><strong>This is your world as it stands, not the population the game
  ships with.</strong> Premades you deleted are simply absent; ones you renamed,
  aged up, moved or married off appear the way you left them; Sims you made
  yourself are counted alongside them. Nothing here is compared against EA's
  originals, and no Sim is labelled premade or player-made, because the save
  does not say and guessing would be inventing something about your game.</p>
  {verdict}
  <ul>
    <li><strong>{joined} of {len(save.sims)} Sims</strong> joined a household
    record, and each household's own name was compared against the surname the
    Sim record carries separately.</li>
    <li><strong>{in_world} of {len(save.lots)} lots</strong> resolved to a
    world.</li>
    <li><strong>Life stage and gender names came from {save.enum_source}</strong>
    &mdash; read out of <code>sims/sim_info_types.pyc</code> rather than
    remembered, so a patch that adds a life stage is picked up instead of
    mislabelled.</li>
    <li><strong>Species came from the same place</strong> &mdash; and needed
    both <code>Species</code> and <code>SpeciesExtended</code>, because the
    small dog is only in the second. Reading one of them is how a save's small
    dogs become a value nothing can name. Every species value here is named by
    the game with none left over, and non-humans only ever take the three life
    stages pets have.</li>
    <li><strong>Pregnancy is not reported, and that is not an oversight.</strong>
    The only field rare enough to be a candidate links Sims in pairs, and the
    link is <em>mutual</em> &mdash; A points at B and B points back. Pregnancy
    is asymmetric, so whatever that field is, it is not that. Nothing about
    traits, skills or relationships is claimed either, for the same reason: a
    guess about somebody's game is worse than a gap.</li>
  </ul>
</div>"""


def row_of(save, h):
    """One household as the query engine sees it.

    The page and `--query` both read this, so an answer given in the terminal
    and a link handed to somebody cannot disagree about what a field means.
    """
    members = h['members']
    pets = [s for s in members if s['species'] != savegame.HUMAN]
    return {
        'name': h['name'] or '(unnamed)',
        'world': (h['world'] or {}).get('name', '') if h['world'] else '',
        'lot': (h['lot'] or {}).get('name', '') if h['lot'] else '',
        'creator': h['creator'] or '',
        'member': sorted(s['name'] for s in members if s['name']),
        'gender': sorted({save.gender_name(s) for s in members}),
        'age': sorted({save.age_name(s) for s in members}),
        'species': sorted({save.species_name(s) for s in members}),
        'funds': int(h['funds'] or 0),
        'size': len(members),
        'people': len(members) - len(pets),
        'pets': len(pets),
        'housed': bool(h['lot']),
    }


def query_hint():
    """A few real questions in the query language, clickable.

    Discoverable by poking rather than by reading a grammar - and they are the
    same EXAMPLES the tests parse and the terminal accepts, so the page cannot
    advertise a syntax the engine does not take.
    """
    bits = ' &nbsp; '.join('<code>%s</code>' % html.escape(qs)
                           for _label, qs in rquery.EXAMPLES[:4])
    return ('<p class="qhint"><b>Ask it anything:</b> %s '
            '&nbsp;&mdash;&nbsp; fields: %s</p>'
            % (bits, ', '.join(sorted(SCHEMA))))


def build(save):
    complaints = save.verify()
    housed, unhoused = save.housed(), save.unhoused()
    when = datetime.datetime.fromtimestamp(save.mtime)
    creators = {h['creator'] for h in save.households if h['creator']}

    people, pets = save.people(), save.pets()
    stats = ''.join((
        stat(format(len(people), ','), 'people',
             ('and %d animals' % len(pets)) if pets else 'no animals'),
        stat(format(len(save.households), ','), 'households',
             '%d housed, %d without a home' % (len(housed), len(unhoused))),
        stat(format(len(save.occupied_worlds()), ','), 'worlds lived in',
             'of %d in the save' % len(save.worlds)),
        stat(format(len(save.lots), ','), 'lots',
             '%d with somebody in them'
             % sum(1 for l in save.lots if l['household'])),
        stat(money(save.total_funds()), 'in the world',
             'across every household'),
    ))

    note = ('Read from <strong>%s</strong> (%.1f MB, saved %s)%s. '
            'Search or filter the households below.'
            % (html.escape(save.slot), save.size / 1048576.0,
               when.strftime('%d %B %Y at %H:%M'),
               ', created by <strong>%s</strong>'
               % html.escape(sorted(creators)[0]) if len(creators) == 1 else ''))

    # The slider only has to reach the richest household; a fixed ceiling
    # would either stop short of it or leave most of the track unusable.
    top = max([int(h['funds'] or 0) for h in save.households] or [0])
    step = max(500, (top // 200) // 500 * 500 or 500)
    chips = (CHIPS.replace('__MAXFUNDS__', str(top))
                  .replace('__STEP__', str(step)))

    data = [row_of(save, h) for h in sorted(
        save.households,
        key=lambda x: (-len(x['members']), (x['name'] or '').lower()))]

    body = (
        '<div class="stats">' + stats + '</div>'
        + '<h2>Who lives here <small>the people, by life stage</small></h2>'
        + age_bars(save)
        + pet_row(save)
        + '<h2>Worth knowing</h2>' + notable(save)
        + '<h2>The neighbourhoods <small>busiest first</small></h2>'
        + world_rows(save)
        + '<h2>Every household <small>search or filter above</small></h2>'
        + query_hint()
        + '<div id="list"></div>'
        + provenance(save, complaints))

    footer = ('%s Sims in %s households across %s worlds, read from %s.'
              % (format(len(save.sims), ','),
                 format(len(save.households), ','),
                 format(len(save.occupied_worlds()), ','),
                 html.escape(save.slot)))

    return report_style.page(
        title='Your Save',
        placeholder='size:1 gender:female -world:Windenburg  —  or just a name…',
        chips_html=chips,
        note_html=note,
        body_html=body,
        footer_html=footer,
        script=(report_style.QUERY_JS + SCRIPT.replace('__DATA__',
                               json.dumps(data, ensure_ascii=False))
                .replace('__SCHEMA__', json.dumps(SCHEMA))
                .replace('__FREE__', json.dumps(list(FREE_FIELDS)))
                .replace('__EXAMPLES__',
                         json.dumps([list(e) for e in
                                     rquery.EXAMPLES]))),
        extra_css=EXTRA_CSS,
        byline='from your save file'), complaints


def main(argv=None):
    # The simoleon sign is the whole point of printing money, and a console
    # that cannot encode it mangles every figure. Ask for UTF-8 and carry on if
    # the stream will not take it.
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):                       # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', help='where to write the page (required)')
    ap.add_argument('--slot', help='which save; default is the most recent')
    ap.add_argument('--saves', help='the saves folder, if it is not the usual')
    ap.add_argument('--list', action='store_true',
                    help='list the saves and exit')
    ap.add_argument('--query', help='filter with the report query language; '
                                    'prints the matches')
    ap.add_argument('--fields', action='store_true',
                    help='what a query can ask about, with examples')
    a = ap.parse_args(argv)

    found = savegame.find_saves(a.saves)
    if not found:
        print('no saves found in %s' % (a.saves or savegame.saves_dir()),
              file=sys.stderr)
        return 2

    if a.list:
        for p in found:
            when = datetime.datetime.fromtimestamp(os.path.getmtime(p))
            print('%-24s %6.1f MB  %s'
                  % (os.path.basename(p), os.path.getsize(p) / 1048576.0,
                     when.strftime('%Y-%m-%d %H:%M')))
        return 0

    if a.fields:
        print('fields a query can ask about:')
        for f in sorted(SCHEMA):
            print('   %-10s %s' % (f, SCHEMA[f]))
        print('free text: %s' % ', '.join(FREE_FIELDS))
        print('')
        for label, qs in rquery.EXAMPLES:
            print('   %-50s %s' % (qs, label))
        return 0

    if not a.out and not a.query:
        print('--out is required: this page is about one person\'s save and '
              'does not belong\nnext to the code.', file=sys.stderr)
        return 2

    path = found[0]
    if a.slot:
        want = [p for p in found
                if os.path.basename(p).lower() == a.slot.lower()]
        if not want:
            print('no save called %s. Try --list.' % a.slot, file=sys.stderr)
            return 2
        path = want[0]

    save = savegame.Save(path)

    if a.query:
        rows = [row_of(save, h) for h in save.households]
        try:
            hits, _node = rquery.run(rows, a.query, SCHEMA, FREE_FIELDS)
        except rquery.QueryError as exc:
            print('bad query: %s' % exc, file=sys.stderr)
            return 2
        print('%d of %d households match' % (len(hits), len(rows)))
        for r in sorted(hits, key=lambda x: (-x['size'], x['name'].lower())):
            where = ('%s, %s' % (r['lot'], r['world'])) if r['housed'] \
                else 'no home'
            print('   %-26s %-32s %2d  %10s'
                  % (r['name'][:26], where[:32], r['size'], money(r['funds'])))
            if r['member']:
                print('      %s' % ', '.join(r['member']))
        if not a.out:
            return 0

    page, complaints = build(save)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or '.', exist_ok=True)
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(page)

    print('wrote %s' % a.out)
    print('  %s: %d Sims, %d households, %d worlds lived in'
          % (save.slot, len(save.sims), len(save.households),
             len(save.occupied_worlds())))
    if complaints:
        print('  checks that did not pass (the page says so too):')
        for c in complaints:
            print('    %s' % c)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
