"""Find pick-one variant sets: packages that are alternatives, all installed at once.

Many mods ship several mutually exclusive builds - a working-time variant, a
difficulty tier, a "stronger"/"weaker" pair - and expect exactly one to be
installed. Install all of them and the game loads all of them; the last one to
be read wins, so the setting in play is whichever the loader happened to reach
last, not the one that was chosen. Nothing errors and no log says a word.

`deep_scan.py` sees these as conflicts, which is true but not useful: they sit
in the same list as two different mods fighting, and the two need opposite
fixes. A real conflict is resolved by picking a winner or a compat patch. A
variant set is resolved by deleting all but one - and until that happens, the
one left standing is not a decision anyone made.

The evidence is structural, not lexical. Two packages that are alternatives
describe the *same* resources: same types, same groups, same instance ids,
different contents. Two packages that are modules of one mod - the per-pack
splits, the addon and its base - describe *different* resources and never
appear here. That is the discriminator, and it is why this cannot be done by
reading filenames: the names of a module set and a variant set look identical.

Names are used only to corroborate, never to accuse. When two packages overlap
heavily but their names share no stem, they are not one mod's variants - they
are two unrelated mods colliding wholesale, which is worth knowing and is
reported separately as an OVERLAP rather than dressed up as a variant set.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import os, sys, json, re, zlib, struct, argparse, collections, itertools
import datetime

# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
ROOT = os.path.join(SIMS, 'Mods')

# A resource key held by more than this many packages is a shared framework key
# and carries no signal about any particular pair. Bucketing on the rest keeps
# the comparison to candidate pairs instead of every pair of packages.
COMMON_KEY = 12
MIN_KEYS = 2            # below this, resources alone cannot accuse; names must
MIN_SIM = 0.60          # containment floor for a pair to be worth reporting
SIZE_RATIO = 0.50       # smaller set over larger; below this it is an addon
MIN_STEM = 6            # chars; shorter shared prefixes mean nothing
STEM_FRAC = 0.40        # shared stem as a fraction of the shorter basename
MIN_TOKENS = 3          # fewer shared name tokens than this is not a pattern
TOKEN_FRAC = 0.60       # shared tokens as a fraction of the whole name

# Two kinds of resource say nothing about what a package does, and counting
# them makes near-identical builds look like they each bring something.
NAMEMAP = 0x0166038C            # per-package name bookkeeping; in nearly all
MANIFEST = b'llamalogic.snippets.modfilemanifest'

VERSION_TAIL = re.compile(r'[_\-. ]v?\d+([._]\d+)*$', re.I)
FLAVOUR_TAIL = re.compile(r'([_\-. ]|^)v?\d+([._]\d+)*$', re.I)
TOKEN = re.compile(r'[_\-. ]+|(?<=[a-z0-9])(?=[A-Z])')
SEP = re.compile(r'[_\-. ]+')


def read_index(path):
    """Yield (type, group, instance, offset, size, memsize, codec) per resource.

    The index alone, never the payloads: this runs over every package in the
    library and decompressing them all to answer a question about their keys
    would cost minutes to learn nothing. The location fields ride along so the
    few packages that turn out to be group members can have specific blobs
    pulled afterwards without parsing the index a second time.
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
            msz = struct.unpack_from('<I', idx, p)[0]; p += 4
            codec = 0
            if fsz & 0x80000000:
                codec = struct.unpack_from('<H', idx, p)[0]; p += 4
            yield (t, g, (h << 32) | lo, off, fsz & 0x7FFFFFFF, msz, codec)
        except struct.error:
            return


def manifests(path, wanted):
    """Which of `wanted` are a build manifest rather than anything the game runs.

    Sims 4 Studio and Llamalogic stamp a ModFileManifest snippet into each
    build, keyed on a hash of that build - so every member of a variant set
    carries one that no sibling has. Counted as content it makes each loser
    look like it still contributes something, and eight nanny schedules that
    are really seven inert copies report as eight builds mixing.

    Identified by the tuning class it declares. Not by its name and not by its
    key: the name is a per-build hex string and the instance is unique by
    construction, so there is nothing there to match against.

    A payload in a codec this does not decode is left out of the answer, so it
    counts as content. That is the safe direction to be wrong in - an unread
    resource gets reported as live, never quietly written off as bookkeeping.
    """
    out = set()
    entries = [e for e in read_index(path) if e[:3] in wanted]
    if not entries:
        return out
    with open(path, 'rb') as f:
        for t, g, i, off, size, _mem, codec in entries:
            f.seek(off)
            raw = f.read(size)
            if codec == 0x5A42:
                try:
                    raw = zlib.decompress(raw)
                except zlib.error:
                    continue
            elif codec:
                continue
            if MANIFEST in raw[:400]:
                out.add((t, g, i))
    return out


def boundaries(name):
    """Offsets in `name` where a token starts.

    Separators, camelCase humps, and the end of the string. The end matters
    because one build is often named by adding to another - `Mod_Traits` beside
    `Mod_Traits_V1.7.3` - and without it the whole of the shorter name is not a
    legal cut, so the stem falls back to the author prefix and the pair reads as
    two unrelated mods.
    """
    return {0, len(name)} | {m.start() for m in TOKEN.finditer(name)}


def shared_stem(a, b):
    """Longest common prefix of two names, cut back to a token boundary in `a`.

    Cutting back is what stops `KhyanTristanRoom` and `KhyanTristanScreen` from
    claiming a stem of `KhyanTristanS`, and what keeps a shared author prefix
    from being mistaken for a shared mod name.
    """
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    bounds = boundaries(a)
    while n and n not in bounds:
        n -= 1
    return a[:n]


def group_stem(names):
    """The stem shared by every name in a group.

    Folding pairwise is safe only because the end of a string counts as a token
    boundary: the accumulated stem is always a prefix of the first name cut at
    one of its boundaries, so its own boundary set agrees with that name's
    everywhere the fold can still cut. Take the end-of-string boundary away and
    the accumulator loses its last legal cut point and collapses to the author
    prefix on the third name.
    """
    stem = names[0]
    for n in names[1:]:
        stem = shared_stem(stem, n)
    return stem


def tokens(name):
    """The name split on separators and camelCase humps."""
    return [t for t in TOKEN.split(name) if t]


def one_token_apart(a, b):
    """Same token sequence but for a single position.

    A shared prefix only sees flavours that come last. Authors put them in the
    middle just as often - `chingyu_casVer_ToddlerTraits_V2.5` beside
    `chingyu_RewardVer_ToddlerTraits_V2.5`, where the common prefix is the
    author's name and nothing more. Everything but one token agreeing, in
    order, is a far stronger claim than a prefix of the same length.

    The floors are what stop it becoming a wildcard: two mods by one author
    named `Maker_Windows_V2` and `Maker_Doorframes_V2` also differ in exactly
    one position, and two shared tokens out of three is a naming convention,
    not a mod.
    """
    ta, tb = tokens(a), tokens(b)
    if len(ta) != len(tb) or not ta:
        return False
    same = sum(1 for x, y in zip(ta, tb) if x.lower() == y.lower())
    return (same == len(ta) - 1 and same >= MIN_TOKENS
            and same / len(ta) >= TOKEN_FRAC)


def _agree(seqs):
    """The longest leading run of tokens every sequence shares."""
    out = []
    for pos in zip(*seqs):
        if len({t.lower() for t in pos}) != 1:
            break
        out.append(pos[0])
    return out


def group_label(names, srcs):
    """A name for the whole set that says which mod, not which author.

    The shared prefix is the label whenever it is a real share of the names.
    When it is not - because the flavour token sits in the middle, so the prefix
    is only the author - the mod's name is what the members still agree on at
    both ends once their version tails are gone: `chingyu_casVer_SeasonsTraits`
    and `chingyu_RewardVer_SeasonsTraits` agree on `chingyu` and on
    `SeasonsTraits`, and only the middle is the choice being made.

    Splitting on separators alone here, not on camelCase humps, is deliberate:
    `RewardVer` and `casVer` both end in `Ver`, and splitting them would leave
    that fragment in the label as a token the two "agree" on.
    """
    stem = group_stem(names)
    if len(stem) >= MIN_STEM and len(stem) / min(map(len, names)) >= STEM_FRAC:
        return stem
    for source in (names, srcs):
        if not all(source):
            continue
        parts = [SEP.split(VERSION_TAIL.sub('', s)) for s in source]
        lead, trail = _agree(parts), _agree([p[::-1] for p in parts])[::-1]
        n = min(len(p) for p in parts)
        keep = (lead[:n] if len(lead) >= n
                else lead + trail[max(0, len(lead) + len(trail) - n):])
        label = '_'.join(keep)
        if len(label) >= MIN_STEM:
            return label
    return stem or names[0]


def same_mod(a, b):
    """Do these two basenames plausibly name builds of one mod?"""
    s = shared_stem(a, b)
    ok = len(s) >= MIN_STEM and len(s) / min(len(a), len(b)) >= STEM_FRAC
    return ok or one_token_apart(a, b), s


def tail(name, stem):
    """What distinguishes this member from the rest of its set."""
    return name[len(stem):].strip('_-. ') or '(base)'


def version_of(name, source):
    """This build's version, preferring the source archive over the filename.

    The filename is the weaker source and reads backwards surprisingly often:
    `chingyu_casVer_SeasonsTraits.package` carries no version at all and looks
    like the older build beside `..._V1.7.3.package`, but it ships inside
    `chingyu_SeasonsTraits_V1.10` and is in fact the newer one. Guessing from
    the suffix would recommend deleting the wrong file.
    """
    for text, where in ((source, 'source archive'), (name, 'filename')):
        m = VERSION_TAIL.search(text or '')
        if m:
            return m.group(0).strip('_-. '), where
    return None, None


def flavour(t):
    """A tail with any trailing version token removed - what the build is.

    Strips whatever version the name ends with, not the version this build was
    finally credited with. The two disagree whenever an author bumps the archive
    and leaves the filename alone, and removing only the credited version would
    leave the stale one sitting in the flavour, splitting one build into two
    flavours - after which nothing is ever superseded and the report says
    everything is fine.

    The leading separator in the pattern is what keeps `Tier2` intact: a number
    welded to a word is part of the name, a number after a separator is not.
    """
    return FLAVOUR_TAIL.sub('', t).strip('_-. ') or '(base)'


def _vkey(v):
    return tuple(int(x) for x in re.findall(r'\d+', v)) if v else ()


def sources(root):
    """relPath -> source archive, from the mod manager's deployment manifest.

    Absent on a manual install, which is fine - it only ever corroborates.
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


def index_all(root, quiet=False):
    keys, n = {}, 0
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if not fn.lower().endswith('.package'):
                continue
            full = os.path.join(dp, fn)
            try:
                # NameMap is per-package bookkeeping present in nearly every
                # well-built package, so two builds "agreeing" on it is
                # evidence of nothing - it only ever raises a score.
                keys[os.path.relpath(full, root)] = frozenset(
                    e[:3] for e in read_index(full) if e[0] != NAMEMAP)
            except OSError:
                continue
            n += 1
            if not quiet and n % 500 == 0:
                print('  indexed %d' % n, file=sys.stderr)
    return keys


def candidate_pairs(keys):
    """Pairs sharing at least one non-ubiquitous resource key."""
    by_key = collections.defaultdict(list)
    for rel, ks in keys.items():
        for k in ks:
            by_key[k].append(rel)
    out = set()
    for rels in by_key.values():
        if len(rels) > COMMON_KEY:
            continue
        out.update(itertools.combinations(sorted(rels), 2))
    return out


def similar(keys, pairs, floor):
    """Pairs where one package's resources sit substantially inside the other's.

    Containment - the share of the *smaller* set the other also describes - and
    not Jaccard. Alternatives differ by exactly the resource that is the choice
    being made, and Jaccard charges them for it: eight nanny schedules holding
    three resources each and agreeing on two score 0.50 and stay hidden, which is
    the whole failure this script exists to catch. Containment scores them 0.67.

    The size guard is what keeps containment honest. A three-resource tweak whose
    keys all sit inside a five-hundred-resource mod is fully contained too, and
    that is an addon overriding a subset - not an alternative to the whole thing.
    Alternatives are near enough the same size as each other; being the same
    thing built differently is what makes them alternatives.
    """
    for a, b in pairs:
        ka, kb = keys[a], keys[b]
        small, large = sorted((len(ka), len(kb)))
        if not small or small / large < SIZE_RATIO:
            continue
        c = len(ka & kb) / small
        if c >= floor:
            yield a, b, c


def group(edges):
    """Union-find, so four alternatives are one set and not six pairs."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    out = collections.defaultdict(list)
    for x in parent:
        out[find(x)].append(x)
    return [sorted(v) for v in out.values() if len(v) > 1]


def analyse(root, floor=MIN_SIM, quiet=False):
    keys = index_all(root, quiet)
    if not quiet:
        print('  %d packages indexed' % len(keys), file=sys.stderr)
    src = sources(root)

    sets_edges, overlap = [], []
    for a, b, j in similar(keys, candidate_pairs(keys), floor):
        na = os.path.splitext(os.path.basename(a))[0]
        nb = os.path.splitext(os.path.basename(b))[0]
        ok, stem = same_mod(na, nb)
        # A shared source archive says the mod itself shipped both, which is the
        # same claim the name stem makes and is better evidence when present.
        if not ok and src.get(a) and src.get(a) == src.get(b):
            ok, stem = True, os.path.commonprefix([na, nb])
        # Below MIN_KEYS a package has too little to say for its resources to
        # accuse anything on their own - one shared key between two one-key
        # packages is a coincidence worth no one's time. It is not a coincidence
        # once the names agree, which is why this only gates the unjudged list:
        # six files called `Mod_Age_Adult`, `Mod_Age_Elder` and so on, each
        # holding the same single resource, are as total an overwrite as exists.
        if not ok and (len(keys[a]) < MIN_KEYS or len(keys[b]) < MIN_KEYS):
            continue
        (sets_edges if ok else overlap).append((a, b, j, stem if ok else ''))

    groups = []
    for members in group([(a, b) for a, b, _, _ in sets_edges]):
        names = [os.path.splitext(os.path.basename(m))[0] for m in members]
        stem = group_stem(names)
        srcs = [src.get(m, '') for m in members]
        label = group_label(names, srcs)
        sims = [j for a, b, j, _ in sets_edges if a in members and b in members]

        # The game reads Mods in case-insensitive path order and the last read
        # of a resource key is the one that survives, so which build is in play
        # is decided by the filenames - not by anything anyone picked. Naming
        # it is the single most useful thing this report can say.
        active = max(members, key=str.lower)

        recs = []
        for m, n, s in zip(members, names, srcs):
            t = tail(n, stem)
            v, whence = version_of(n, s)
            # What this build defines that the winner does not, and so keeps
            # contributing. Zero means it is loaded and wholly overridden -
            # wasteful, but not changing the game. Above zero the set is not
            # "one build in play" at all; it is a blend of several.
            leak = keys[m] - keys[active]
            if leak and m != active:
                leak -= manifests(os.path.join(root, m), leak)
            recs.append({
                'package': m, 'tail': t, 'version': v, 'version_from': whence,
                'flavour': flavour(t), 'resources': len(keys[m]),
                'bytes': os.path.getsize(os.path.join(root, m)), 'source': s,
                'active': m == active, 'still_live': 0 if m == active
                else len(leak),
            })

        # Members that are the same build at different versions: same flavour,
        # different version. Everything but the highest is superseded, and that
        # is the one recommendation here that is unambiguous.
        best = {}
        for r in recs:
            if r['version']:
                f = r['flavour']
                if _vkey(r['version']) > _vkey(best.get(f, {}).get('version')):
                    best[f] = r
        for r in recs:
            win = best.get(r['flavour'])
            r['superseded_by'] = (win['version'] if win and win is not r
                                  and r['version'] != win['version'] else None)

        groups.append({
            'kind': ('version pair'
                     if len({r['flavour'] for r in recs}) == 1
                     and any(r['superseded_by'] for r in recs)
                     else 'variant set'),
            'stem': label,
            'similarity': round(min(sims), 3) if sims else None,
            'superseded': sum(1 for r in recs if r['superseded_by']),
            'active': active,
            'mixing': sum(r['still_live'] for r in recs),
            'members': recs,
        })
    groups.sort(key=lambda g: (-g['superseded'], -len(g['members']),
                               -(g['similarity'] or 0)))

    # A pair whose members already sit in the same group is explained by that
    # group. Repeating it here as "mod not identified" contradicts the section
    # above it.
    placed = {}
    for i, grp in enumerate(groups):
        for m in grp['members']:
            placed[m['package']] = i
    overlap = [o for o in overlap
               if placed.get(o[0], -1) != placed.get(o[1], -2)]
    overlap.sort(key=lambda x: -x[2])
    return {
        'generated': datetime.datetime.now().isoformat(timespec='seconds'),
        'packages_scanned': len(keys),
        'similarity_floor': floor,
        'groups': groups,
        'overlaps': [{'packages': [a, b], 'similarity': round(j, 3),
                      'shared_resources': len(keys[a] & keys[b])}
                     for a, b, j, _ in overlap],
    }


def report(res, show_overlaps=True):
    g = res['groups']
    print('%d package(s) scanned, similarity floor %.2f\n'
          % (res['packages_scanned'], res['similarity_floor']))
    if not g:
        print('no variant sets - every mod that ships alternatives has one '
              'installed.')
    for grp in g:
        print('=== %s: %s  (%d installed, %.0f%% of the smaller set overlaps)'
              % (grp['kind'].upper(), grp['stem'], len(grp['members']),
                 100 * (grp['similarity'] or 0)))
        for m in grp['members']:
            note = ''
            if m['superseded_by']:
                note = '  OLDER - superseded by %s' % m['superseded_by']
            elif m['version']:
                note = '  %s (per %s)' % (m['version'], m['version_from'])
            if m['still_live']:
                note += '  [%d resource(s) still live]' % m['still_live']
            print('  %s %-30s %6d res %8.2f MB  %s%s'
                  % ('IN PLAY ->' if m['active'] else '          ',
                     m['flavour'][:30], m['resources'], m['bytes'] / 1048576,
                     os.path.basename(m['package']), note))
        if grp['superseded']:
            print('    -> %d older build(s) still installed. Removing those is '
                  'safe.' % grp['superseded'])
        flavours = sorted({m['flavour'] for m in grp['members']})
        if len(flavours) > 1:
            joined = ', '.join(flavours)
            print('    -> %d alternatives%s.'
                  % (len(flavours),
                     ' (%s)' % joined if len(joined) <= 60 else ''))
            # Whether the also-rans do anything is the difference between a
            # tidying job and a bug, and it is not guessable from the names.
            if grp['mixing']:
                print('       %d resource(s) the other builds define are absent'
                      '\n       from the one in play, so they stay live: this '
                      'set is\n       running as a blend, not as one choice.'
                      % grp['mixing'])
            else:
                print('       The others are read and then wholly overridden, '
                      'so they\n       cost load time and nothing else. Still '
                      'worth deleting - and\n       worth checking, because '
                      'the filenames chose this one, not you.')
        print()
    if show_overlaps and res['overlaps']:
        print('=== heavy overlap, mod not identified (%d) ==='
              % len(res['overlaps']))
        print('    These share most of their resources but nothing ties them to'
              '\n    one mod - no common filename stem, no common source '
              'archive.\n    Either two mods colliding, or a variant set whose '
              'naming does\n    not say so. Worth a look; not safe to guess at.')
        for o in res['overlaps']:
            print('    %.0f%%  %d shared  %s\n              %s'
                  % (100 * o['similarity'], o['shared_resources'],
                     os.path.basename(o['packages'][0]),
                     os.path.basename(o['packages'][1])))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--min', type=float, default=MIN_SIM, dest='floor',
                    help='similarity floor (default %.2f)' % MIN_SIM)
    ap.add_argument('--json', metavar='OUT',
                    help='write JSON here (default: variants.json in the '
                         'output directory)')
    ap.add_argument('--no-overlaps', action='store_true',
                    help='only variant sets, not cross-mod overlaps')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)

    if not os.path.isdir(a.root):
        print('no Mods directory at %s' % a.root, file=sys.stderr)
        return 2

    res = analyse(a.root, a.floor, a.quiet)
    report(res, not a.no_overlaps)

    out = a.json or os.path.join(gate.out_dir(), 'variants.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(res, f, indent=1)
    print('\nwrote %s' % out)
    return 1 if res['groups'] else 0


if __name__ == '__main__':
    sys.exit(main())
