#!/usr/bin/env python3
"""Parse TwistedMexi's BetterExceptions conflict report into something actionable.

BE-ConflictReport.html is written by `tm.be.conflictscan` into
Mods\\<...>\\TMEX-Settings\\. It is 130-odd tables with no headings, so the shape
has to come from the content: a row whose two cells are both mod paths starts a
new pair, and every row after it is a resource those two mods both provide, until
the next pair.

Read it for what it is: a list of mods that COLLIDE, not an inventory. It names a
small fraction of an installed library and skips script mods entirely - for a
full mod list use MCCC's GetSystemInfo report instead (Sim menu -> Sim Commands
-> Logging Commands).

A conflict is not automatically a bug. Two mods sharing a StringTable is usually
harmless; two mods overriding the same tuning is usually not. The severity
heuristic below encodes that, and is a starting point for triage rather than a
verdict.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import collections
import html
import json
import os
import re
import sys

SIMS = os.environ.get('SIMS4_DIR') or os.path.join(
    os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')

# Resource types, and how much a collision on each actually matters.
TYPES = {
    '220557DA': ('StringTable', 'low'),
    '0C772E27': ('LootActions', 'high'),
    '7DF2169C': ('Snippet', 'high'),
    'E882D22F': ('Interaction', 'high'),
    'CB5FDDC7': ('Trait', 'high'),
    '6017E896': ('Buff', 'high'),
    '545AC67A': ('SimData', 'medium'),
    '62E94D38': ('CombinedTuning', 'high'),
    '034AEECB': ('CASPart', 'medium'),
    '00B2D882': ('Image', 'low'),
    '3C1AF1F2': ('Thumbnail', 'low'),
    '2F7D0004': ('Icon', 'low'),
    'D382BF57': ('ObjectDefinition', 'medium'),
    '319E4F1D': ('ObjectCatalog', 'medium'),
}


def find_report():
    for dp, _, fn in os.walk(os.path.join(SIMS, 'Mods')):
        for f in fn:
            if f == 'BE-ConflictReport.html':
                return os.path.join(dp, f)
    return None


def text(fragment):
    t = re.sub(r'<br\s*/?>', ' ', fragment, flags=re.I)
    t = re.sub(r'<[^>]+>', ' ', t)
    return html.unescape(re.sub(r'\s+', ' ', t)).strip()


def is_mod(cell):
    return cell.lower().endswith(('.package', '.ts4script', '.zip'))


def parse(path):
    raw = open(path, encoding='utf-8', errors='replace').read()
    body = re.sub(r'<(style|script).*?</\1>', '', raw, flags=re.S | re.I)

    pairs, current = [], None
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', body, re.S | re.I):
        cells = [text(m) for m in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S | re.I)]
        if len(cells) != 2:
            continue
        a, b = cells
        if is_mod(a) and is_mod(b):
            current = {'a': a, 'b': b, 'resources': []}
            pairs.append(current)
        elif current is not None and ':' in a:
            tid = a.split(':', 1)[0].upper()
            name, sev = TYPES.get(tid, (f'Unknown({tid})', 'medium'))
            note = ''
            m = re.search(r'first difference occurs on line (\d+)', b, re.I)
            if m:
                note = f'differs at line {m.group(1)}'
            current['resources'].append(
                {'key': a, 'type': name, 'severity': sev, 'note': note})
    return pairs


# Tuning classes that are METADATA, not behaviour. A collision on one of these
# is noise even though its resource type scores high. SmartCoreModInfoSnippet is
# the case that taught this: three Andirz mods all ship one under the SAME
# instance id, so only one registers - a bug in that framework, but nothing the
# player can or should fix, and no gameplay effect.
METADATA_CLASSES = ('SmartCoreModInfoSnippet', 'ModInfoSnippet', 'VersionSnippet')


def resource_text(package, instance):
    """Pull one resource out of a package as text, for diffing."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    '..', '..', 'sulskill-modbuild', 'scripts'))
    import dbpf
    for _t, _g, i, blob in dbpf.read(package):
        if i == instance:
            return blob.decode('utf-8', 'replace')
    return None


def resolve(name):
    """Find a mod by basename anywhere under Mods."""
    target = base(name).lower()
    for dp, _, fn in os.walk(os.path.join(SIMS, 'Mods')):
        for f in fn:
            if f.lower() == target:
                return os.path.join(dp, f)
    return None


def cmd_diff(pairs, which):
    """Show what actually differs between two mods that collide.

    This is the step that turns 'a conflict was reported' into 'here is what you
    lose'. A collision only matters if the two versions differ in a way you care
    about, and the only way to know is to read both.
    """
    import difflib
    sel = [q for q in pairs
           if which.lower() in q['a'].lower() or which.lower() in q['b'].lower()]
    if not sel:
        sys.exit(f"no conflict pair matching {which!r}")
    for q in sel:
        pa, pb = resolve(q['a']), resolve(q['b'])
        if not pa or not pb:
            print(f"  cannot locate both packages for {base(q['a'])} / {base(q['b'])}")
            continue
        print(f"\n=== {base(q['a'])}  vs  {base(q['b'])} ===")
        for r in q['resources']:
            if r['severity'] == 'low':
                continue
            try:
                inst = int(r['key'].split(':')[2], 16)
            except (IndexError, ValueError):
                continue
            ta, tb = resource_text(pa, inst), resource_text(pb, inst)
            if ta is None or tb is None:
                continue
            cls = re.search(r'<I c="([^"]+)"', ta)
            cls = cls.group(1) if cls else '?'
            tag = '  [METADATA - cosmetic]' if cls in METADATA_CLASSES else ''
            print(f"\n  {r['key']}  class={cls}{tag}")
            if ta == tb:
                print("     identical - harmless")
                continue
            la, lb = ta.splitlines(), tb.splitlines()
            print(f"     {len(la)} vs {len(lb)} lines")
            n = 0
            for line in difflib.unified_diff(la, lb, lineterm='', n=0):
                if line.startswith(('+', '-')) and not line.startswith(('+++', '---')):
                    print(f"     {line.strip()[:110]}")
                    n += 1
                if n >= 20:
                    print("     ...")
                    break


def severity_of(pair):
    sevs = {r['severity'] for r in pair['resources']}
    for level in ('high', 'medium', 'low'):
        if level in sevs:
            return level
    return 'low'


def base(name):
    return os.path.basename(name.replace('\\', '/'))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--report', help='path to BE-ConflictReport.html')
    p.add_argument('--severity', choices=('high', 'medium', 'low'),
                   help='only show pairs at this severity')
    p.add_argument('--exclude', action='append', default=[],
                   help='skip pairs whose either filename matches (repeatable)')
    p.add_argument('--json', action='store_true')
    p.add_argument('--mods', action='store_true', help='list every mod named')
    p.add_argument('--diff', metavar='MODNAME',
                   help='show what actually differs for pairs involving this mod')
    a = p.parse_args()

    path = a.report or find_report()
    if not path or not os.path.exists(path):
        sys.exit("BE-ConflictReport.html not found - run tm.be.conflictscan in game")
    pairs = parse(path)

    if a.exclude:
        pat = re.compile('|'.join(re.escape(x) for x in a.exclude), re.I)
        pairs = [q for q in pairs if not (pat.search(q['a']) or pat.search(q['b']))]
    if a.severity:
        pairs = [q for q in pairs if severity_of(q) == a.severity]

    if a.diff:
        cmd_diff(pairs, a.diff)
        return

    if a.json:
        print(json.dumps([dict(q, severity=severity_of(q)) for q in pairs], indent=1))
        return

    if a.mods:
        mods = collections.Counter()
        for q in pairs:
            mods[base(q['a'])] += 1
            mods[base(q['b'])] += 1
        print(f"{len(mods)} mod(s) named in the report\n")
        for m, n in mods.most_common():
            print(f"  {n:>3}  {m}")
        return

    buckets = collections.Counter(severity_of(q) for q in pairs)
    print(f"{os.path.relpath(path, SIMS)}")
    print(f"{len(pairs)} conflicting pair(s):  "
          + ", ".join(f"{k} {buckets[k]}" for k in ('high', 'medium', 'low') if buckets[k]))
    print()
    for q in sorted(pairs, key=lambda x: ('high', 'medium', 'low').index(severity_of(x))):
        sev = severity_of(q)
        kinds = collections.Counter(r['type'] for r in q['resources'])
        print(f"[{sev.upper():<6}] {base(q['a'])}")
        print(f"         {base(q['b'])}")
        print(f"         {len(q['resources'])} resource(s): "
              + ", ".join(f"{k} x{v}" for k, v in kinds.most_common()))
        notes = {r['note'] for r in q['resources'] if r['note']}
        if notes:
            print(f"         {sorted(notes)[0]}")
        print()


if __name__ == '__main__':
    main()
