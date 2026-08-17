"""Bisect a mod library to find what breaks a load, without false exonerations.

The obvious procedure - disable half, launch, keep the half that still fails -
is wrong, and wrong in a way that looks like progress. It assumes exactly one
culprit. When a library has two mods that each break the same thing on their
own, every half you disable still fails, because the other cause is still
enabled; the tool then "narrows" to a set that never contained the whole answer
and every later round is spent inside it. A real investigation lost about a
dozen launches to this before the assumption was noticed.

The asymmetry is the whole design:

    a CLEAN round  proves every cause is inside the set you disabled
    a FAILING round proves only that at least one cause is still enabled

So a failing round narrows nothing while you are still halving, and this script
refuses to act as if it did. Once any round comes back clean you have a proven
base, and the strategy inverts: hold that base disabled and add mods *back* in
groups. From then on both outcomes are informative, because the complement is
already known clean - which is why add-back is slower per round and finishes
sooner.

A mod is only ever *named* as a cause by adding it back, alone, to a proven
clean base and watching that fail. Nothing is named by elimination.

Rounds are made cheap by moving deployed files out rather than driving the mod
manager. Under a hardlink-deploying manager every file in the Mods tree is a
second name for the staging inode, so moving the Mods-side name hides the mod
and loses nothing; restoring is a rename back. Files are MOVED, never copied - a
copy makes a new inode and silently breaks the manager's link to staging.

    py scripts/bisect.py plan cut.txt      what would move, and what did not match
    py scripts/bisect.py arm cut.txt       move them out, stamp the round
    py scripts/bisect.py check             score the round, print the next set
    py scripts/bisect.py restore           move everything back
    py scripts/bisect.py status            what is out; has the manager undone it

The manifest is not rewritten, so the manager still believes these mods are
deployed. That is what makes arming and undoing a round instant - and it is also
why any deploy or purge silently restores everything. Do not deploy mid-round,
and do not run `resource_cfg.py --fix` mid-round either: it changes what loads,
which is the variable under test.

Named `bisect_mods` rather than `bisect` deliberately: every script here puts
this directory at the front of sys.path, and a module called `bisect.py` shadows
the standard library's, so anything importing it afterwards - including stdlib
modules that import it lazily - would silently get this one instead.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import os, sys, json, re, time, errno, argparse, datetime

# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
ROOT = os.path.join(SIMS, 'Mods')

# The holding directory has to sit on the same volume as Mods: os.rename across
# volumes fails, and the copy-then-delete that would "work" instead breaks the
# manager's hardlink. It must also live OUTSIDE Mods, or a Resource.cfg rule
# deep enough to reach it would load the very files being hidden. A sibling of
# Mods inside the Sims 4 user folder satisfies both.
HOLD = _os.environ.get('SULSKILL_BISECT_HOLD') or _os.path.join(
    SIMS, 'sulskill-bisect-hold')

# Reports are appended one at a time with pauses longer than a poll, so a file
# read while it is still being written reports a round as cleaner than it was.
SETTLE = 25.0


def ledger_path():
    return os.path.join(gate.out_dir(), 'bisect_state.json')


def blank():
    return {'target': None, 'hold': HOLD, 'moved': [], 'armed_at': None,
            'mode': 'halving', 'candidates': [], 'cleared': [], 'named': [],
            'clean_base': None, 'rounds': []}


def load():
    try:
        with open(ledger_path(), encoding='utf-8') as f:
            state = json.load(f)
    except (OSError, ValueError):
        return blank()
    base = blank()
    base.update(state)
    return base


def save(state):
    with open(ledger_path(), 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=1)


def units(root):
    """mod name -> [path relative to root].

    The manager's deployment manifest is the accurate answer because one mod is
    many files with unrelated names. Without it - a manual install - the best
    available unit is a top-level entry in Mods, which is what a person moving
    files by hand would treat as one mod anyway.
    """
    try:
        import variants
        src = variants.sources(root)
    except Exception:
        src = {}
    out = {}
    if src:
        for rel, name in src.items():
            if name:
                out.setdefault(name, []).append(rel)
        return out
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return {}
    for name in entries:
        if name.lower().endswith('.json'):
            continue
        out[name] = [name]
    return out


def wanted(path):
    """Mod names, one per line; blanks and # comments ignored."""
    names = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                names.append(line)
    return names


def resolve(root, names):
    index = units(root)
    matched, missing = {}, []
    for name in names:
        if name in index:
            matched[name] = index[name]
        else:
            missing.append(name)
    return matched, missing


def ts4_started():
    """Start time of the running game, or None.

    An artifact older than the process that wrote it cannot describe this round.
    Preferring the process start over the arm time catches the case where the
    round was armed long before anyone got round to launching.
    """
    try:
        import subprocess
        out = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             "(Get-Process -Name TS4_x64 -ErrorAction SilentlyContinue |"
             " Sort-Object StartTime | Select-Object -First 1)"
             ".StartTime.ToString('yyyy-MM-ddTHH:mm:ss')"],
            capture_output=True, text=True, timeout=20).stdout.strip()
        return datetime.datetime.fromisoformat(out).timestamp()
    except Exception:
        return None


def artifacts(since, marker=None):
    """Exception files written after `since`, and whether any is still settling.

    Both layers are read. A UI-only failure leaves lastException clean, so
    checking one of them and calling the round clean is a false negative.
    """
    hits, unsettled, now = [], False, time.time()
    try:
        names = os.listdir(SIMS)
    except OSError:
        return hits, unsettled
    for name in names:
        low = name.lower()
        if not (low.startswith('lastexception')
                or low.startswith('lastuiexception')):
            continue
        full = os.path.join(SIMS, name)
        try:
            st = os.stat(full)
        except OSError:
            continue
        if st.st_mtime < since:
            continue
        if now - st.st_mtime < SETTLE:
            unsettled = True
            continue
        if marker:
            try:
                with open(full, encoding='utf-8', errors='replace') as f:
                    if not re.search(marker, f.read()):
                        continue
            except OSError:
                continue
        hits.append(name)
    return sorted(hits), unsettled


def cmd_plan(root, names):
    matched, missing = resolve(root, names)
    files = sum(len(v) for v in matched.values())
    print('target : %s' % root)
    print('matched: %d mod(s), %d file(s)' % (len(matched), files))
    for name in sorted(matched):
        print('   %-55s %d file(s)' % (name, len(matched[name])))
    if missing:
        print('\nNOT DEPLOYED (already off, or the name is wrong) - %d:'
              % len(missing))
        for name in missing:
            print('   %s' % name)
    if not matched:
        print('\nnothing to move.', file=sys.stderr)
        return 2
    return 1 if missing else 0


def cmd_arm(root, names):
    state = load()
    if state['moved']:
        print('%d file(s) are already out. Run restore first.'
              % len(state['moved']), file=sys.stderr)
        return 2
    matched, missing = resolve(root, names)
    if not matched:
        print('none of those names are deployed - nothing to move.',
              file=sys.stderr)
        return 2

    moved, failed = [], []
    for name in sorted(matched):
        for rel in matched[name]:
            src = os.path.join(root, rel)
            dst = os.path.join(HOLD, rel)
            if not os.path.exists(src):
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.exists(dst):
                    os.remove(dst)
                os.rename(src, dst)      # same volume: inode preserved
                moved.append({'mod': name, 'rel': rel})
            except OSError as exc:
                if getattr(exc, 'errno', None) == errno.EXDEV:
                    print('holding directory is on another volume:\n  %s\n'
                          'Moving there would copy, which breaks the mod '
                          "manager's hardlink.\nSet SULSKILL_BISECT_HOLD to a "
                          'path on the same volume as Mods.' % HOLD,
                          file=sys.stderr)
                    _undo(root, moved)
                    return 2
                failed.append((rel, str(exc)))

    if not state['candidates']:
        state['candidates'] = sorted(matched)
    state.update({'target': root, 'hold': HOLD, 'moved': moved,
                  'armed_at': time.time()})
    save(state)

    print('armed: %d file(s) from %d mod(s) moved out'
          % (len(moved), len(matched)))
    if missing:
        print('skipped %d name(s) not deployed: %s'
              % (len(missing), ', '.join(missing)))
    for rel, why in failed:
        print('   FAILED %s  %s' % (rel, why))
    print('\nLaunch the game and perform the failing action, then: bisect.py check')
    return 1 if failed else 0


def _undo(root, moved):
    for item in moved:
        src = os.path.join(HOLD, item['rel'])
        dst = os.path.join(root, item['rel'])
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)
        except OSError:
            pass


def cmd_restore():
    state = load()
    if not state['moved']:
        print('nothing is out')
        return 0
    root = state['target']
    back, failed = 0, []
    for item in state['moved']:
        src = os.path.join(state.get('hold') or HOLD, item['rel'])
        dst = os.path.join(root, item['rel'])
        if not os.path.exists(src):
            failed.append((item['rel'], 'missing from the holding directory'))
            continue
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)
            back += 1
        except OSError as exc:
            failed.append((item['rel'], str(exc)))
    if failed:
        # Keep only what could not go back, so a rerun finishes the job rather
        # than losing track of the outstanding files.
        outstanding = {rel for rel, _ in failed}
        state['moved'] = [i for i in state['moved'] if i['rel'] in outstanding]
        save(state)
        print('restored %d, FAILED %d:' % (back, len(failed)))
        for rel, why in failed:
            print('   %s  %s' % (rel, why))
        return 1
    state['moved'], state['armed_at'] = [], None
    save(state)
    print('restored %d file(s)' % back)
    return 0


def cmd_status():
    state = load()
    print('mode      : %s' % state['mode'])
    print('candidates: %d' % len(state['candidates']))
    if state['named']:
        print('named     : %s' % ', '.join(state['named']))
    if state['cleared']:
        print('cleared   : %d mod(s)' % len(state['cleared']))
    for r in state['rounds']:
        print('  round %-3d %-8s disabled %-4d -> %d candidate(s)'
              % (r['n'], r['outcome'], r['disabled'], r['remaining']))
    if not state['moved']:
        print('\nnothing is out')
        return 0
    mods = sorted({i['mod'] for i in state['moved']})
    print('\n%d file(s) out, from %d mod(s):' % (len(state['moved']), len(mods)))
    for name in mods:
        print('   %s' % name)
    root = state['target']
    back = [i['rel'] for i in state['moved']
            if os.path.exists(os.path.join(root, i['rel']))]
    if back:
        print('\nWARNING: %d file(s) are back in Mods - the mod manager '
              'redeployed.\nThis round is void; restore and arm it again.'
              % len(back))
        return 1
    return 0


def recommend(state):
    """The next set to disable, given what is actually proven so far."""
    cands = sorted(state['candidates'])
    if state['mode'] == 'halving':
        return cands, ('disable every candidate at once. Until one round comes '
                       'back clean nothing can be narrowed, so the fastest '
                       'move is to establish a clean base.')
    base = sorted(state['clean_base'] or [])
    remaining = [m for m in cands if m in base]
    if len(remaining) <= 1:
        return base, ('add back the last candidate alone to name it, or '
                      'confirm with every named cause disabled.')
    half = remaining[:max(1, len(remaining) // 2)]
    keep_out = sorted(set(base) - set(half))
    return keep_out, ('disable this set - it adds %d candidate(s) back to the '
                      'clean base. Either outcome narrows now.' % len(half))


def cmd_check(marker):
    state = load()
    if state['armed_at'] is None:
        print('no round is armed. Run: bisect.py arm <file>', file=sys.stderr)
        return 2

    floor = state['armed_at']
    started = ts4_started()
    if started:
        floor = max(floor, started)
    hits, unsettled = artifacts(floor, marker)
    if unsettled:
        print('an exception file is still being written. Wait %ds and re-run - '
              'reading it now reports the round as cleaner than it was.'
              % int(SETTLE), file=sys.stderr)
        return 2

    disabled = sorted({i['mod'] for i in state['moved']})
    cands = set(state['candidates'])
    clean = not hits
    n = len(state['rounds']) + 1

    if clean:
        # Proven: every cause lies inside the set that was disabled.
        cleared = sorted(cands - set(disabled))
        state['cleared'] = sorted(set(state['cleared']) | set(cleared))
        state['candidates'] = sorted(cands & set(disabled))
        state['clean_base'] = disabled
        if state['mode'] == 'halving':
            print('CLEAN. That is a proven base - switching to add-back, where '
                  'both outcomes narrow.')
        state['mode'] = 'addback'
        outcome = 'clean'
    else:
        outcome = 'failed'
        if state['mode'] == 'addback' and state['clean_base']:
            # The complement is proven clean, so a failure is attributable to
            # whatever was added back on top of it.
            added = sorted(set(state['clean_base']) - set(disabled))
            if added:
                state['candidates'] = sorted(cands & set(added)) or added
                if len(added) == 1 and added[0] not in state['named']:
                    state['named'].append(added[0])
                    print('NAMED: %s breaks it on its own - added alone to a '
                          'proven clean base.' % added[0])
        else:
            # Halving: at least one cause is still enabled. That is all. The
            # disabled set is NOT cleared - with more than one cause, every
            # half fails and clearing them is how an investigation loses days.
            print('FAILED. That narrows nothing yet: it proves only that a '
                  'cause is still enabled,\nnot that the %d disabled mod(s) '
                  'are innocent.' % len(disabled))

    state['rounds'].append({
        'n': n, 'when': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'outcome': outcome, 'disabled': len(disabled),
        'remaining': len(state['candidates']),
        'artifacts': hits,
    })
    save(state)

    print('\nround %d: %s%s' % (n, outcome,
                                (' (%s)' % ', '.join(hits)) if hits else ''))
    print('candidates: %d' % len(state['candidates']))
    if state['named']:
        print('named so far: %s' % ', '.join(state['named']))
        print('Confirm with every named cause disabled and everything else '
              'live - a second\ncause only shows up once the first is out of '
              'the way.')

    nxt, why = recommend(state)
    print('\nnext round - %s' % why)
    out = os.path.join(gate.out_dir(), 'bisect_next.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('# next round, written by bisect.py check\n')
        f.write('\n'.join(nxt) + '\n')
    print('   %d mod(s) -> %s' % (len(nxt), out))
    return 1 if hits else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('action',
                    choices=('plan', 'arm', 'check', 'restore', 'status'))
    ap.add_argument('file', nargs='?', help='mod names, one per line')
    ap.add_argument('--root', default=ROOT, help='the Mods folder')
    ap.add_argument('--marker', help='regex a report must match to count as the '
                                     'symptom; default is any new report')
    a = ap.parse_args(argv)

    if a.action in ('plan', 'arm'):
        if not a.file:
            print('%s needs a file of mod names' % a.action, file=sys.stderr)
            return 2
        if not os.path.isdir(a.root):
            print('no Mods folder at %s' % a.root, file=sys.stderr)
            return 2
        names = wanted(a.file)
        return (cmd_plan if a.action == 'plan' else cmd_arm)(a.root, names)
    if a.action == 'check':
        return cmd_check(a.marker)
    if a.action == 'restore':
        return cmd_restore()
    return cmd_status()


if __name__ == '__main__':
    sys.exit(main())
