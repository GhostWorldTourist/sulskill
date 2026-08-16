"""Audit and repair Mods\\Resource.cfg - the file that decides what loads.

This file is the reason a package can sit on disk, correctly installed, and do
nothing. The game does not walk Mods; it loads exactly what the globs here
match. A package one folder deeper than the deepest rule is invisible, and
invisible looks identical to installed - no error, no log line, nothing to
notice. That is the failure this exists to make loud.

Two problems, and only one of them is safe to fix without asking:

  redundancy   repeated Priority blocks and repeated rules. Mod managers,
               installers and hand-edits append rather than merge, so the file
               grows copies of itself. Deduplicating is provably a no-op: the
               set of (priority, glob) pairs is unchanged, so the resolved load
               order is unchanged. --fix does this.

  coverage     packages deeper than any rule reaches. Fixing that means adding
               rules, which changes what loads - a judgment call about someone
               else's library. Reported, never applied.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse, datetime, json, os, re, shutil, sys

SIMS = os.environ.get('SIMS4_DIR') or os.path.join(
    os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
DEFAULT_CFG = os.path.join(SIMS, 'Mods', 'Resource.cfg')


def _rule_key(arg):
    """A glob's identity for deduplication: separators and case do not matter."""
    return re.sub(r'\s+', '', arg.replace('\\', '/')).lower()


def to_regex(glob):
    """Compile one PackedFile glob the way the game reads it.

    '*' stops at a directory separator. That is the whole reason a Resource.cfg
    carries one rule per depth instead of a single recursive pattern, and a
    matcher that let '*' cross '/' would report full coverage for a file the
    game never sees.
    """
    out = []
    for ch in glob.replace('\\', '/').strip():
        out.append('[^/]*' if ch == '*' else re.escape(ch))
    return re.compile('^' + ''.join(out) + '$', re.IGNORECASE)


def parse(text):
    """-> (blocks, comments, unknown)

    blocks is [(priority or None, [(directive, arg), ...]), ...] in file order.
    Lines before the first Priority land in a leading block with priority None,
    which is how the game reads them too.
    """
    blocks, comments, unknown = [], [], []
    cur = (None, [])
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#') or line.startswith('//'):
            comments.append(line)
            continue
        parts = line.split(None, 1)
        directive = parts[0]
        arg = parts[1].strip() if len(parts) > 1 else ''
        if directive.lower() == 'priority':
            if cur[1]:
                blocks.append(cur)
            try:
                cur = (int(arg), [])
            except ValueError:
                cur = (None, [])
                unknown.append(line)
            continue
        if directive.lower() not in ('packedfile', 'directoryfiles', 'override'):
            unknown.append(line)
        cur[1].append((directive, arg))
    if cur[1]:
        blocks.append(cur)
    return blocks, comments, unknown


def canonical(blocks):
    """Merge equal priorities, drop repeated rules, keep first-seen order.

    Order is preserved deliberately. Reordering rules within a priority would
    change which of two matching mods wins, and this function's contract is
    that nothing about the load result changes.
    """
    merged, order = {}, []
    dup_rules, dup_blocks = [], []
    for prio, rules in blocks:
        if prio in merged:
            dup_blocks.append(prio)
        else:
            merged[prio] = ([], set())
            order.append(prio)
        keep, seen = merged[prio]
        for directive, arg in rules:
            k = (directive.lower(), _rule_key(arg))
            if k in seen:
                dup_rules.append((prio, directive, arg))
                continue
            seen.add(k)
            keep.append((directive, arg))
    return [(p, merged[p][0]) for p in order], dup_rules, dup_blocks


def render(blocks, comments=()):
    out = list(comments)
    for i, (prio, rules) in enumerate(blocks):
        if out or i:
            out.append('')
        if prio is not None:
            out.append('Priority %d' % prio)
        out.extend('%s %s' % (d, a) if a else d for d, a in rules)
    return '\n'.join(out) + '\n'


def coverage(mods_dir, blocks):
    """Which .package files no rule reaches.

    Only packages. Script mods are not governed by this file at all - the game
    finds .ts4script itself and refuses anything more than one folder deep, so
    a Resource.cfg rule neither helps nor hurts them.
    """
    rx = [to_regex(a) for _p, rules in blocks
          for d, a in rules if d.lower() == 'packedfile']
    covered, missed, deepest_seen = 0, [], 0
    for dirpath, _dirs, files in os.walk(mods_dir):
        for f in files:
            if not f.lower().endswith('.package'):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f),
                                  mods_dir).replace('\\', '/')
            deepest_seen = max(deepest_seen, rel.count('/'))
            if any(r.match(rel) for r in rx):
                covered += 1
            else:
                missed.append(rel)
    deepest_rule = max([a.replace('\\', '/').count('/')
                        for _p, rules in blocks
                        for d, a in rules if d.lower() == 'packedfile'] or [-1])
    return covered, sorted(missed), deepest_seen, deepest_rule


def audit(path, mods_dir=None):
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        text = f.read()
    blocks, comments, unknown = parse(text)
    fixed, dup_rules, dup_blocks = canonical(blocks)
    result = {
        'path': path,
        'bytes': len(text.encode('utf-8')),
        'blocks': len(blocks),
        'rules': sum(len(r) for _p, r in blocks),
        'duplicate_priority_blocks': sorted(set(dup_blocks)),
        'duplicate_rules': [{'priority': p, 'rule': '%s %s' % (d, a)}
                            for p, d, a in dup_rules],
        'unrecognised_lines': unknown,
        'managed_by_mod_manager': None,
        'new_text': render(fixed, comments),
    }
    try:                                # a hardlinked cfg belongs to a manager
        result['managed_by_mod_manager'] = os.stat(path).st_nlink > 1
    except OSError:
        pass
    if mods_dir and os.path.isdir(mods_dir):
        cov, missed, seen, rule = coverage(mods_dir, fixed)
        result.update(packages_covered=cov, packages_unreachable=missed,
                      deepest_package=seen, deepest_rule=rule)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--path', default=DEFAULT_CFG, help='Resource.cfg to audit')
    ap.add_argument('--fix', action='store_true',
                    help='rewrite deduplicated, after a timestamped backup')
    ap.add_argument('--json', action='store_true',
                    help='also write resource_cfg.json to the output dir')
    a = ap.parse_args(argv)

    if not os.path.isfile(a.path):
        print('no Resource.cfg at %s' % a.path, file=sys.stderr)
        print('Without one the game loads nothing from Mods.', file=sys.stderr)
        return 2

    mods = os.path.dirname(a.path)
    r = audit(a.path, mods)
    redundant = bool(r['duplicate_priority_blocks'] or r['duplicate_rules'])

    print('%s\n  %d bytes, %d block(s), %d rule(s)'
          % (r['path'], r['bytes'], r['blocks'], r['rules']))
    if r.get('packages_covered') is not None:
        print('  %d package(s) reachable, deepest at %d folder(s); rules reach %d'
              % (r['packages_covered'], r['deepest_package'], r['deepest_rule']))

    if r['duplicate_priority_blocks']:
        print('\nrepeated Priority block(s): %s'
              % ', '.join(str(p) for p in r['duplicate_priority_blocks']))
    for d in r['duplicate_rules']:
        print('  repeated rule  [Priority %s]  %s' % (d['priority'], d['rule']))
    for line in r['unrecognised_lines']:
        print('  unrecognised   %s' % line)

    missed = r.get('packages_unreachable') or []
    if missed:
        print('\n%d package(s) NO RULE REACHES - installed and not loading:'
              % len(missed))
        for rel in missed[:20]:
            print('  %s' % rel)
        if len(missed) > 20:
            print('  ... and %d more' % (len(missed) - 20))
        print('Add a PackedFile rule one level deeper, or flatten the folders.')

    if a.json:
        out = os.path.join(gate.out_dir(), 'resource_cfg.json')
        json.dump({k: v for k, v in r.items() if k != 'new_text'},
                  open(out, 'w', encoding='utf-8'), indent=1)
        print('\nwrote %s' % out)

    if not redundant:
        print('\nno redundancy.')
        return 1 if missed else 0

    if not a.fix:
        print('\n--fix removes the redundancy. It cannot change what loads: the '
              'set of\n(priority, glob) pairs and their order are identical '
              'afterwards.')
        return 1

    if r['managed_by_mod_manager']:
        print('\nNOTE: this file is hardlinked, so a mod manager deployed it. '
              'It is\nrewritten in place rather than replaced, so the manager\'s'
              ' staging copy -\nthe same bytes on disk - is fixed too and the '
              'next deploy keeps it.')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    bak = '%s.%s.bak' % (a.path, stamp)
    shutil.copy2(a.path, bak)          # copy, not rename: keeps the hardlink
    with open(a.path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(r['new_text'])
    print('\nbackup %s\nfixed  %s  (%d -> %d bytes)'
          % (bak, a.path, r['bytes'],
             len(r['new_text'].encode('utf-8'))))
    return 1 if missed else 0


if __name__ == '__main__':
    sys.exit(main())
