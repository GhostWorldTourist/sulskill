"""What a mod library does to Sims' emotions, after load order is resolved.

The quiet failure here is a mod that wins an argument nobody knew was
happening. Two mods rebalance the same buff; the game reads both; the last one
read wins the whole resource, not the fields it meant to change. Nothing
errors, no log says a word, and the mod whose settings are in play is whichever
the loader happened to reach last - not the one the player chose. The other one
sits in the folder looking installed.

That is invisible from outside because a buff is not a setting a player can
read. It is a tuning resource, and the thing that actually decides how a Sim
feels is a single integer in it: `mood_weight`, summed across every active buff,
highest total becomes the Sim's emotion. A mod can nerf a system to nothing by
changing that integer to 0, or - quieter still - by dropping `mood_type`
entirely, which leaves the moodlet visible in the UI while it contributes no
emotion at all. Both read as "the mod is installed and working".

So this answers three questions no mod manager can:

  - **who wins.** Every buff defined more than once, resolved by real load
    order, with the winner and the losers named as the mods they came from.
  - **what changed.** For each of those, the difference the override made:
    mood, weight, visibility. That is the diff a player actually wants.
  - **what the library adds up to.** A census of every winning buff by mood,
    so "my Sims are always Tense" has an answer with mod names in it.

It is a census of what is *installed*, not a simulation of what is *running*. A
buff only pushes a mood while it is active on a Sim, and nothing here knows
which buffs a save has active. Read the ledger as the shape of the library's
emotional pressure, not as a prediction about any particular Sim.

Usage:
    py moodprint.py                    # ledger + overrides + what changed
    py moodprint.py --mood Tense       # only buffs pushing one mood
    py moodprint.py --mod chingyu      # only buffs from mods matching a name
    py moodprint.py --json OUT         # machine-readable, full detail
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse, collections, json, os, re, struct, sys, zlib      # noqa: E402

# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
ROOT = os.path.join(SIMS, 'Mods')

BUFF = 0x6017E896       # buff tuning. The type id is the discriminator: every
                        # tuning class has its own, so no XML sniffing is needed
MOOD = 0xBA7B60B8       # mood tuning, which is how custom moods get their names

# Base-game mood ids. These are not in any mod package - they live in the game
# install - so unlike custom moods they cannot be resolved from the library and
# have to be stated. Established by consensus across independently built
# packages rather than by reading any one mod's comments, because the comments
# in tuning are copy-pasted between builds and demonstrably wrong: 14637 is
# labelled Mood_Happy in 24 packages and Mood_Fine in 23. One vote per package,
# and the id that half the library calls Fine is Fine.
#
# 14645 is spelled Mood_Stressed in tuning and shown to players as Tense. Both
# names appear below because a player searching for either should find it.
EA_MOODS = {
    14632: 'Angry',       14633: 'Bored',       14634: 'Confident',
    14635: 'Embarrassed', 14636: 'Energized',   14637: 'Fine',
    14638: 'Flirty',      14639: 'Focused',     14640: 'Happy',
    14641: 'Inspired',    14642: 'Playful',     14643: 'Sad',
    14644: 'Dazed',       14645: 'Tense',       14646: 'Uncomfortable',
    251719: 'Scared',     27149: 'Asleep',
}

# Moods that make a Sim's life worse. Only used to order the ledger so the
# interesting half is at the top - nothing branches on it.
NEGATIVE = {'Angry', 'Bored', 'Embarrassed', 'Sad', 'Tense', 'Uncomfortable',
            'Dazed', 'Scared'}

# A weight this far above the normal range is not balancing, it is a mod
# deciding the argument in advance. EA's own buffs run 1-6 and the heaviest
# thing in a typical library is around 20; anything at three figures wins over
# every other buff a Sim could possibly have at once. Worth naming, both
# because it is invisible in game and because it makes the totals it lands in
# meaningless - one buff at 696969 is not a mood 696969 units strong, it is a
# mood that cannot be beaten while that buff is active.
HAMMER = 100

# Segments that describe the tuning rather than the mood, in the names custom
# moods ship under (Basemental_Moods_Stoned_Mood, Lumpinou_MP_Hurt_MoodTuning).
NOISE = {'mood', 'moods', 'tuning', 'moodtuning'}

# An id with no name behind it. Pack moods are the usual cause: the ones Cats
# and Dogs and Horse Ranch add are referenced by mods but defined in the game
# install, and the install does not ship them as Mood tuning resources this
# can read. They are counted, never guessed at, and never given a made-up name.
UNRESOLVED = re.compile(r'^mood \d+$')

RE_MOOD = re.compile(r'<T n="mood_type">\s*(\d+)')
RE_WEIGHT = re.compile(r'<T n="mood_weight">\s*(-?\d+)')
RE_VISIBLE = re.compile(r'<T n="visible">\s*(\w+)')
RE_ROOT = re.compile(r'<I\s+([^>]*)>')
RE_ATTR = re.compile(r'(\w+)="([^"]*)"')
# The two halves of a skill modifier are separated by a `</V>` and a newline,
# so they are not adjacent tags. Anchoring them together without allowing for
# that matches nothing at all, and a library full of skill changes reports as
# having none - which is the same silent-clear failure everything here is about.
RE_SKILL = re.compile(
    r'<E n="skill_tag">([^<]+)</E>.{0,80}?<T n="modifier_value">\s*(-?\d+)',
    re.S)


def read_index(path):
    """Yield (type, group, instance, offset, size, codec) per resource.

    The index only. Walking the whole library and decompressing every payload
    to find out which packages hold buffs would cost minutes to learn something
    the index already says. The location fields ride along so the packages that
    do hold buffs can have those specific blobs pulled afterwards without
    parsing the index a second time.
    """
    with open(path, 'rb') as f:
        hdr = f.read(96)
        if len(hdr) < 96 or hdr[:4] != b'DBPF':
            return
        cnt = struct.unpack_from('<I', hdr, 36)[0]
        isz = struct.unpack_from('<I', hdr, 44)[0]
        ipos = (struct.unpack_from('<Q', hdr, 64)[0]
                or struct.unpack_from('<I', hdr, 40)[0])
        if not cnt or not ipos:
            return
        f.seek(ipos)
        idx = f.read(isz)
    if len(idx) < 4:
        return
    flags = struct.unpack_from('<I', idx, 0)[0]
    p = 4
    const = {}
    for bit, k in ((0, 't'), (1, 'g'), (2, 'h')):
        if flags & (1 << bit):
            const[k] = struct.unpack_from('<I', idx, p)[0]
            p += 4
    for _ in range(cnt):
        try:
            t = const.get('t')
            if t is None:
                t = struct.unpack_from('<I', idx, p)[0]; p += 4
            g = const.get('g')
            if g is None:
                g = struct.unpack_from('<I', idx, p)[0]; p += 4
            h = const.get('h')
            if h is None:
                h = struct.unpack_from('<I', idx, p)[0]; p += 4
            lo = struct.unpack_from('<I', idx, p)[0]; p += 4
            off = struct.unpack_from('<I', idx, p)[0]; p += 4
            fsz = struct.unpack_from('<I', idx, p)[0]; p += 4
            p += 4                                          # uncompressed size
            codec = 0
            if fsz & 0x80000000:
                codec = struct.unpack_from('<H', idx, p)[0]; p += 4
            yield (t, g, (h << 32) | lo, off, fsz & 0x7FFFFFFF, codec)
        except struct.error:
            return


def payloads(path, wanted):
    """-> {(type, group, instance): text or None}. None means it would not decode.

    An entry that cannot be read yields None rather than being dropped. A
    dropped buff is a buff reported as contributing no mood, which is exactly
    the wrong direction to be wrong in here - it would look like a deliberate
    nerf by whichever mod shipped it.
    """
    out = {}
    entries = [e for e in read_index(path) if e[:3] in wanted]
    if not entries:
        return out
    with open(path, 'rb') as f:
        for t, g, i, off, size, codec in entries:
            f.seek(off)
            raw = f.read(size)
            try:
                if codec == 0x5A42:
                    raw = zlib.decompress(raw)
                elif codec:
                    raise ValueError('codec 0x%04X' % codec)
                out[(t, g, i)] = raw.decode('utf-8', 'replace')
            except Exception:                                # noqa: BLE001
                out[(t, g, i)] = None
    return out


def load_order(root):
    """Package paths in the order the game reads them, first read to last.

    Case-insensitive path order, which is why `[Kuttoe] X` loads before
    `chingyu_X`: '[' is ASCII 91 and sorts ahead of every letter once case
    stops mattering. Players rename mods to force this constantly, usually
    without knowing that is what they are doing.

    Order is the whole basis of every "who wins" answer below, so it is derived
    here once and nothing downstream re-sorts.
    """
    rels = []
    for dp, _dirs, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith('.package'):
                full = os.path.join(dp, fn)
                rels.append(os.path.relpath(full, root))
    return sorted(rels, key=lambda r: r.replace(os.sep, '/').lower())


def sources(root):
    """relPath -> the mod it was deployed from, per the mod manager's manifest.

    Without this the report names package files, and a package filename is not
    something anyone can act on: it is not what the mod is called in the mod
    manager, and it is not what has to be disabled to change the outcome. A
    finding the reader cannot act on is not a finding.

    Absent on a manual install, where the package filename is the only name
    there is and is therefore the right one to print.
    """
    man = os.path.join(root, 'Vortex Mods', 'vortex.deployment.json')
    try:
        with open(man, encoding='utf-8') as f:
            j = json.load(f)
    except (OSError, ValueError):
        return {}
    base = os.path.join('Vortex Mods', '')
    return {base + e['relPath'].replace('/', os.sep): e.get('source', '')
            for e in j.get('files', ())}


def parse_buff(text):
    """Pull the emotional payload out of one buff's tuning.

    `mood` None means the buff names no mood at all, which is not the same as
    naming one with weight 0. Both leave the Sim's emotion untouched, but the
    first is a buff that was never emotional and the second is one that was
    deliberately silenced - and telling those apart is most of the point of the
    override diff below.
    """
    if text is None:
        return {'unreadable': True}
    attrs = {}
    m = RE_ROOT.search(text)
    if m:
        attrs = dict(RE_ATTR.findall(m.group(1)))
    mood = RE_MOOD.search(text)
    weight = RE_WEIGHT.search(text)
    visible = RE_VISIBLE.search(text)
    skills = [(t.strip(), int(v)) for t, v in RE_SKILL.findall(text)]
    return {
        'name': attrs.get('n', ''),
        'mood': int(mood.group(1)) if mood else None,
        # Absent is reported as absent, never defaulted to 0. Guessing a
        # default would put invented weight into the ledger's totals.
        'weight': int(weight.group(1)) if weight else None,
        'visible': visible.group(1).lower() != 'false' if visible else True,
        'skills': sorted(set(skills)),
        'unreadable': False,
    }


def _shorten(raw_names):
    """Turn one package's mood tuning names into the words a player would use.

    They arrive as Author:Prefix_Mood_Thing_MoodTuning, and the only part worth
    printing is Thing. Two passes: drop the segments that describe the tuning
    rather than the mood, then drop whatever leading segments *every* mood in
    the package shares, which is how the author's own prefix is identified
    without keeping a list of author names. Basemental_Tripping beside
    Basemental_Stoned agree on Basemental, so Basemental is not the mood.

    The shared prefix is never allowed to eat the last segment. A package
    shipping one mood shares its whole name with itself, and stripping that
    leaves nothing to print.
    """
    split = {}
    for inst, n in raw_names.items():
        segs = [s for s in n.split(':')[-1].split('_')
                if s and s.lower() not in NOISE]
        split[inst] = segs or [n]

    common = 0
    if len(split) > 1:
        seqs = list(split.values())
        shortest = min(len(s) for s in seqs)
        while common < shortest - 1 and len({s[common].lower()
                                             for s in seqs}) == 1:
            common += 1
    return {inst: '_'.join(segs[common:]) or segs[-1]
            for inst, segs in split.items()}


def mood_names(pkgs, root):
    """id -> mood name, resolved from the library itself where possible.

    Custom moods - and there are more of these than people expect, since every
    mod adding an emotion ships one - carry their real name in a Mood tuning
    resource. Reading it is strictly better than reading the comment a buff
    leaves beside the id, because the comment is written by whoever built that
    buff and is wrong whenever it was copied from a different one: 14637 is
    commented Mood_Happy about as often as Mood_Fine.
    """
    names = dict(EA_MOODS)
    for rel in pkgs:
        full = os.path.join(root, rel)
        try:
            wanted = {e[:3] for e in read_index(full) if e[0] == MOOD}
        except OSError:
            continue
        raw = {}
        for (_t, _g, inst), text in payloads(full, wanted).items():
            if not text:
                continue
            m = RE_ROOT.search(text)
            if m:
                n = dict(RE_ATTR.findall(m.group(1))).get('n', '')
                if n:
                    raw[inst] = n
        for inst, short in _shorten(raw).items():
            names.setdefault(inst, short)
    return names


def analyse(root, quiet=False):
    order = load_order(root)
    src = sources(root)

    def owner(rel):
        """What to call this package in the report: the mod, then the file."""
        return src.get(rel) or os.path.basename(rel)

    # Which packages hold buffs, and where. One index pass over the library.
    #
    # Mood tuning is collected in the same pass rather than from the buff
    # holders, because nothing requires a mod to ship its moods and its buffs
    # in the same package and several do not. Looking only where the buffs are
    # leaves those moods unnamed, and the report prints a bare id - which is
    # the one thing in it a reader can do nothing with.
    holders, mood_holders, unreadable_pkgs = {}, [], []
    for rel in order:
        try:
            # Listed, not streamed: it is read twice below, and read_index is
            # a generator that would be empty the second time.
            index = list(read_index(os.path.join(root, rel)))
        except OSError:
            unreadable_pkgs.append(rel)
            continue
        keys = {e[:3] for e in index if e[0] == BUFF}
        if keys:
            holders[rel] = keys
        if any(e[0] == MOOD for e in index):
            mood_holders.append(rel)
    if not quiet:
        print('%d package(s), %d holding buffs' % (len(order), len(holders)),
              file=sys.stderr)

    # key -> packages that define it, in load order. Because `order` is already
    # sorted, appending in this loop preserves it and the last entry is the
    # winner by construction.
    defined = collections.defaultdict(list)
    for rel in order:
        for key in holders.get(rel, ()):
            defined[key].append(rel)

    contested = {k: v for k, v in defined.items() if len(v) > 1}
    needed = collections.defaultdict(set)
    for key, rels in defined.items():
        needed[rels[-1]].add(key)                    # every winner
    for key, rels in contested.items():
        for rel in rels:
            needed[rel].add(key)                     # and every loser

    parsed = {}
    for rel, keys in needed.items():
        for key, text in payloads(os.path.join(root, rel), keys).items():
            parsed[(rel, key)] = parse_buff(text)

    names = mood_names(mood_holders, root)

    def mood_of(b):
        if b.get('unreadable'):
            return None
        return names.get(b['mood'], 'mood %s' % b['mood']) if b['mood'] else None

    # The ledger: every winning buff that names a mood.
    ledger = collections.defaultdict(
        lambda: {'buffs': 0, 'weight': 0, 'weight_unstated': 0,
                 'invisible': 0, 'hammers': 0,
                 'mods': collections.Counter()})
    hammers, unreadable = [], 0
    for key, rels in defined.items():
        b = parsed.get((rels[-1], key), {})
        if b.get('unreadable'):
            unreadable += 1
            continue
        mood = mood_of(b)
        if not mood:
            continue
        e = ledger[mood]
        e['buffs'] += 1
        if b['weight'] is None:
            e['weight_unstated'] += 1
        else:
            e['weight'] += b['weight']
            if abs(b['weight']) >= HAMMER:
                e['hammers'] += 1
                hammers.append({'buff': b['name'], 'instance': key[2],
                                'mood': mood, 'weight': b['weight'],
                                'mod': owner(rels[-1]), 'file': rels[-1]})
        if not b['visible']:
            e['invisible'] += 1
        e['mods'][owner(rels[-1])] += 1
    hammers.sort(key=lambda h: -abs(h['weight']))

    # What the overrides actually changed.
    changes, eclipsed = [], collections.Counter()
    for key, rels in sorted(contested.items()):
        win_rel = rels[-1]
        win = parsed.get((win_rel, key), {})
        for lose_rel in rels[:-1]:
            eclipsed[lose_rel] += 1
            lose = parsed.get((lose_rel, key), {})
            if win.get('unreadable') or lose.get('unreadable'):
                continue
            diff = []
            if lose['mood'] != win['mood']:
                diff.append(('mood', mood_of(lose) or 'none',
                             mood_of(win) or 'none'))
            if lose['weight'] != win['weight']:
                diff.append(('weight',
                             'unstated' if lose['weight'] is None
                             else lose['weight'],
                             'unstated' if win['weight'] is None
                             else win['weight']))
            if lose['visible'] != win['visible']:
                diff.append(('visible', lose['visible'], win['visible']))
            if lose['skills'] != win['skills']:
                diff.append(('skills', lose['skills'], win['skills']))
            if not diff:
                continue
            # Silenced: it used to move an emotion, and now it does not. This
            # is the change that is invisible in game, because the moodlet can
            # still appear in the UI while contributing nothing.
            silenced = bool(
                (lose['mood'] and not win['mood'])
                or (lose['mood'] and win['mood']
                    and (lose['weight'] or 0) > 0 and win['weight'] == 0))
            changes.append({
                'buff': win.get('name') or lose.get('name') or '',
                'instance': key[2],
                'winner': owner(win_rel), 'winner_file': win_rel,
                'loser': owner(lose_rel), 'loser_file': lose_rel,
                'silenced': silenced,
                'changed': [[a, b, c] for a, b, c in diff],
            })

    # A package whose every buff lost. Its other resources may still be live,
    # so this is stated as what it is - no buff in it reaches the game - and
    # not as "this mod does nothing".
    #
    # Who beat it is the actionable half. An add-on named to sort early loses
    # every argument with the mod it was written to modify - `!` is ASCII 33
    # and sorts ahead of every letter, so the convention players use to give a
    # mod priority does the exact opposite where overriding is concerned. That
    # is not asserted about any particular file here; the winners are named and
    # the reader can see it.
    beaten = collections.defaultdict(collections.Counter)
    for key, rels in contested.items():
        for lose_rel in rels[:-1]:
            beaten[lose_rel][owner(rels[-1])] += 1
    dead = sorted(
        ({'mod': owner(rel), 'file': rel, 'buffs': len(holders[rel]),
          'beaten_by': beaten[rel].most_common(3)}
         for rel in holders if eclipsed[rel] == len(holders[rel])),
        key=lambda d: -d['buffs'])

    return {
        'root': root,
        'packages': len(order),
        'packages_with_buffs': len(holders),
        'buffs': len(defined),
        'contested': len(contested),
        'unreadable_buffs': unreadable,
        'unreadable_packages': unreadable_pkgs,
        'ledger': {m: {'buffs': e['buffs'], 'weight': e['weight'],
                       'weight_unstated': e['weight_unstated'],
                       'invisible': e['invisible'], 'hammers': e['hammers'],
                       'mods': e['mods'].most_common()}
                   for m, e in ledger.items()},
        'hammers': hammers,
        'changes': changes,
        'fully_eclipsed': dead,
    }


def report(res, mood_filter=None, mod_filter=None, limit=25):
    # 0 reads as "no limit" and behaved as "show nothing, then say how much was
    # hidden" - a report that suppresses everything and still claims to be one.
    if limit is not None and limit <= 0:
        limit = None
    print('%s\n  %d package(s), %d with buffs, %d buff(s) defined, %d contested'
          % (res['root'], res['packages'], res['packages_with_buffs'],
             res['buffs'], res['contested']))
    if res['unreadable_buffs']:
        print('  %d buff(s) would not decode and are left out'
              % res['unreadable_buffs'])

    def keep_mod(*names):
        return not mod_filter or any(mod_filter.lower() in n.lower()
                                     for n in names if n)

    rows = [(m, e) for m, e in res['ledger'].items()
            if (not mood_filter or mood_filter.lower() in m.lower())]
    # Unnamed ids are not moods anyone can act on, and listing eleven of them
    # as eleven separate moods overstates how varied the library is. Counted
    # on one line instead.
    unnamed = [r for r in rows if UNRESOLVED.match(r[0])]
    rows = [r for r in rows if not UNRESOLVED.match(r[0])]
    if rows or unnamed:
        # Negative moods first, then by weight. A player reading this is
        # almost always asking why their Sims feel bad, so that half goes on
        # top rather than being sorted into the middle by total weight.
        rows.sort(key=lambda r: (r[0] not in NEGATIVE, -r[1]['weight']))
        shown = rows if mood_filter else rows[:limit]
        print('\nEMOTIONAL LEDGER - every winning buff that names a mood')
        print('  %-18s %6s %9s  %s' % ('mood', 'buffs', 'weight', 'top mods'))
        for mood, e in shown:
            top = ', '.join('%s (%d)' % (n, c) for n, c in e['mods'][:3])
            print('  %-18s %6d %9d  %s'
                  % (mood[:18], e['buffs'], e['weight'], top[:64]))
            extra = []
            if e['hammers']:
                extra.append('%d buff(s) over %d - total is meaningless'
                             % (e['hammers'], HAMMER))
            if e['weight_unstated']:
                extra.append('%d state no weight' % e['weight_unstated'])
            if e['invisible']:
                extra.append('%d invisible' % e['invisible'])
            if extra:
                print('  %-18s        %s' % ('', '; '.join(extra)))
        if len(rows) > len(shown):
            tail = rows[len(shown):]
            print('  ... and %d more mood(s), %d buff(s) between them'
                  % (len(tail), sum(e['buffs'] for _m, e in tail)))
        if unnamed:
            print('  %d buff(s) name %d mood id(s) with no name in this library'
                  % (sum(e['buffs'] for _m, e in unnamed), len(unnamed)))
            print('  - pack moods live in the game install, not in Mods.')
        print("  Weight is what decides a Sim's emotion, summed over the buffs")
        print('  actually active. This counts what is installed, not what runs.')

    ham = [h for h in res['hammers'] if keep_mod(h['mod'])
           and (not mood_filter or mood_filter.lower() in h['mood'].lower())]
    if ham:
        print('\nOVERRIDE HAMMERS - weights big enough to settle it outright')
        print('  While one of these is active no ordinary buff can outweigh')
        print('  it, whatever else the Sim has going on.')
        for h in ham[:limit]:
            print('  %9d  %-14s %s' % (h['weight'], h['mood'][:14],
                                       h['buff'] or 'buff %d' % h['instance']))
            print('  %9s  %s' % ('', h['mod']))
        if limit is not None and len(ham) > limit:
            print('  ... and %d more' % (len(ham) - limit))

    ch = [c for c in res['changes']
          if keep_mod(c['winner'], c['loser'])
          and (not mood_filter or any(
              mood_filter.lower() in str(v).lower()
              for f, a, v in c['changed'] if f == 'mood'))]
    silenced = [c for c in ch if c['silenced']]
    if silenced:
        print('\nSILENCED - a buff that moved an emotion, and now does not')
        print('  The moodlet can still appear in game while contributing')
        print('  nothing, so this does not look like anything is wrong.')
        for c in silenced[:limit]:
            print('\n  %s' % (c['buff'] or 'buff %d' % c['instance']))
            print('    %s  overrides  %s' % (c['winner'], c['loser']))
            for field, was, now in c['changed']:
                print('      %-8s %s -> %s' % (field, was, now))
        if limit is not None and len(silenced) > limit:
            print('\n  ... and %d more' % (len(silenced) - limit))

    rest = [c for c in ch if not c['silenced']]
    if rest:
        print('\nOVERRIDDEN - the same buff defined twice, and what changed')
        for c in rest[:limit]:
            print('\n  %s' % (c['buff'] or 'buff %d' % c['instance']))
            print('    %s  overrides  %s' % (c['winner'], c['loser']))
            for field, was, now in c['changed']:
                print('      %-8s %s -> %s' % (field, was, now))
        if limit is not None and len(rest) > limit:
            print('\n  ... and %d more' % (len(rest) - limit))

    dead = [d for d in res['fully_eclipsed'] if keep_mod(d['mod'])]
    if dead and not mood_filter:
        print('\nEVERY BUFF OVERRIDDEN - these mods\' buffs never reach the game')
        print('  Other resources in them may still be live, so this is about')
        print('  their buffs, not the whole mod. The file is named as well as')
        print('  the mod because one mod often ships several, and only some of')
        print('  them lose - and because the filename is what decides this:')
        print('  the game reads Mods in path order and the last read wins, so')
        print('  a file named to sort early loses to everything after it.')
        for d in dead[:limit]:
            print('\n  %s' % d['mod'])
            print('    %-46s %d buff(s)'
                  % (os.path.basename(d['file'])[:46], d['buffs']))
            for who, n in d['beaten_by']:
                print('      beaten by %s (%d)' % (who, n))
        if limit is not None and len(dead) > limit:
            print('  ... and %d more' % (len(dead) - limit))

    if not rows and not ch and not dead:
        print('\nnothing matched.')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--mood', help='only this mood')
    ap.add_argument('--mod', help='only buffs won or lost by mods matching this')
    ap.add_argument('--limit', type=int, default=25,
                    help='rows per section (default 25)')
    ap.add_argument('--json', metavar='OUT',
                    help='write JSON here (default: moodprint.json in the '
                         'output directory)')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)

    if not os.path.isdir(a.root):
        print('no Mods directory at %s' % a.root, file=sys.stderr)
        return 2

    res = analyse(a.root, a.quiet)
    report(res, a.mood, a.mod, a.limit)

    out = a.json or os.path.join(gate.out_dir(), 'moodprint.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(res, f, indent=1)
    print('\nwrote %s' % out)
    return 1 if res['changes'] else 0


if __name__ == '__main__':
    sys.exit(main())
