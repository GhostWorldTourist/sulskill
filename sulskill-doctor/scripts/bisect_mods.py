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

Most players have no mod manager, and for them that paragraph is false: the
deployed file is the only file, and moving it puts this tool in sole custody of
somebody's mod. `install.py` tells the two apart by asking whether a second copy
exists anywhere rather than by naming a manager, and `holdlog.py` performs every
move through an append-only journal kept beside the files themselves - so the
undo survives this script, its ledger, and the manager all being gone. Nothing
is overwritten, nothing is deleted, and every collision is refused and reported.

That split is the design and is worth keeping: WHAT to move is a judgement and
lives here, in the strategy below. HOW to move it is not a judgement at all, and
lives in holdlog.py, where it is boring, journalled and reversible.

    py scripts/bisect_mods.py plan cut.txt          what would move, what did not match
    py scripts/bisect_mods.py arm cut.txt --launch  move them out and start the game
    py scripts/bisect_mods.py check                 score the round, print the next set
    py scripts/bisect_mods.py restore               move everything back
    py scripts/bisect_mods.py status                what is out, and what is recoverable

`holdlog.py status` and `holdlog.py restore` do the last two without this script
at all, reading the journal in the holding directory. That is the recovery path
when the ledger is gone.

`--launch` is worth using every round. The tester's only irreducible job is
watching the screen and saying what happened; making them go and start the game
themselves hands back a context switch twenty times over. The game appearing IS
the instruction.

Under a manager the manifest is not rewritten, so the manager still believes
these mods are deployed. That is what makes arming and undoing a round instant -
and it is also why any deploy or purge silently restores everything. Do not
deploy mid-round, and do not run `resource_cfg.py --fix` mid-round either: it
changes what loads, which is the variable under test. Without a manager there is
no such accident available, and no such safety net either.

Named `bisect_mods` rather than `bisect` deliberately: every script here puts
this directory at the front of sys.path, and a module called `bisect.py` shadows
the standard library's, so anything importing it afterwards - including stdlib
modules that import it lazily - would silently get this one instead.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import os, sys, json, re, time, argparse, datetime
import holdlog
import install as installinfo

# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
ROOT = os.path.join(SIMS, 'Mods')

# The holding directory has to sit on the same volume as Mods: os.rename cannot
# cross volumes, and the copy-then-delete that would "work" instead duplicates
# the file rather than relocating it - which breaks a manager's hardlink to
# staging, and on a manual install puts the only copy of a mod through a delete.
# It must also live OUTSIDE Mods, or a Resource.cfg rule deep enough to reach it
# would load the very files being hidden. A sibling of Mods inside the Sims 4
# user folder satisfies both.
HOLD = _os.environ.get('SULSKILL_BISECT_HOLD') or _os.path.join(
    SIMS, 'sulskill-bisect-hold')

# Reports are appended one at a time with pauses longer than a poll, so a file
# read while it is still being written reports a round as cleaner than it was.
SETTLE = 25.0

# How long to wait for the game process after starting it. A module constant
# rather than only a default argument so a test can set it to 0 and never sit
# waiting for a game it must not start.
LAUNCH_WAIT = 90


def ledger_path():
    return os.path.join(gate.out_dir(), 'bisect_state.json')


def hold(root=None):
    """The journalled mover for this run. Everything on disk goes through it."""
    return holdlog.Hold(HOLD, root or ROOT)


def blank():
    """The strategy state, and only the strategy state.

    What this holds is a judgement: which mods are still candidates, what has
    been proven clean, which round we are on. Losing it costs an investigation
    and nothing else.

    What it deliberately does NOT hold is the record of which files are moved
    out. That used to live here, and because this file is loaded with a bare
    `except` that falls back to empty, a truncated write or a cleared
    %LOCALAPPDATA% made `restore` say "nothing is out" while the files sat in
    the holding directory. The files' own location is now the record - see
    holdlog.py - and `round_disabled` below is only the names this round chose,
    which is strategy, not custody.
    """
    return {'target': None, 'hold': HOLD, 'round_disabled': [],
            'armed_at': None, 'mode': 'halving', 'candidates': [],
            'cleared': [], 'named': [], 'clean_base': None, 'rounds': []}


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
    """Write via a temp file and os.replace, so an interrupted save leaves the
    previous state rather than a truncated one. `open(path, 'w')` truncates
    first, which is how the old ledger managed to come back empty."""
    path = ledger_path()
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def units(root):
    """mod name -> [FILE path relative to root].

    The manager's deployment manifest is the accurate answer because one mod is
    many files with unrelated names. Without it - a manual install - the best
    available unit is a top-level entry in Mods, which is what a person moving
    files by hand would treat as one mod anyway.

    A folder unit is expanded to the files inside it rather than handed on as a
    single path. Renaming the folder would move the mod correctly and still be
    wrong: the journal would record one entry named after a directory, the
    holding directory would contain the files inside it, and reconciling those
    two reports the directory as MISSING - the loudest thing this tool can say,
    for a mod sitting safely on disk. One rel is one file, everywhere.
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
        full = os.path.join(root, name)
        if os.path.isdir(full):
            files = []
            for dirpath, _dirs, fns in os.walk(full):
                for fn in fns:
                    files.append(os.path.relpath(os.path.join(dirpath, fn),
                                                 root))
            if files:
                out[name] = sorted(files)
        else:
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


def launch(wait=None):
    """Start the game and wait for the process. -> (pid_seen, message).

    The tester has exactly one job that cannot be automated: looking at the
    screen and saying what happened. Printing "now go and launch it" hands back
    a context switch every round, twenty times over. Starting it here also makes
    the anchor stricter, because the round can no longer be armed hours before
    anybody plays it.

    Set SIMS4_LAUNCH_CMD to launch through a storefront instead of the
    executable: a storefront applies the launch options the player configured,
    and running the exe directly tests a configuration they never play.

    Never score from here. A tool that starts the game looks like a tool that
    could also decide the outcome, and it cannot - only the person watching can.
    """
    import subprocess
    wait = LAUNCH_WAIT if wait is None else wait
    cmd = _os.environ.get('SIMS4_LAUNCH_CMD')
    if not cmd:
        base = ''
        try:
            base = gate.game_dir() or ''
        except Exception:
            base = ''
        exe = os.path.join(base, 'Game', 'Bin', 'TS4_x64.exe') if base else ''
        if not exe or not os.path.isfile(exe):
            return False, ('cannot find the game. Set SIMS4_GAME_DIR, or '
                           'SIMS4_LAUNCH_CMD to launch through a storefront.')
        cmd = '"%s"' % exe
    try:
        subprocess.Popen(cmd, shell=True,
                         cwd=os.path.dirname(cmd.strip('"')) or None)
    except Exception as exc:
        return False, 'could not start the game: %s' % exc

    deadline = time.time() + wait
    while time.time() < deadline:
        if ts4_started():
            return True, 'game is up'
        time.sleep(2)
    # Not an error. A failure before the first frame is a different symptom
    # from the one being bisected, and it is a result in its own right.
    return False, ('the game process never appeared within %ds. That is a '
                   'result, not a tool failure - a crash before the first '
                   'frame is a different symptom.' % wait)


def ran_since(since):
    """Did the game run at all after `since`?

    Mod logs are timestamped per launch, so they answer this even when the
    process has already exited. Without it, a round nobody played reads exactly
    like a round that passed - which is a false exoneration of the same family
    the rest of this tool exists to prevent.
    """
    try:
        names = os.listdir(SIMS)
    except OSError:
        return False
    for name in names:
        if not name.lower().endswith('.log'):
            continue
        try:
            if os.stat(os.path.join(SIMS, name)).st_mtime >= since:
                return True
        except OSError:
            continue
    return False


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
    # The install shape decides what the warnings have to say, so it is printed
    # before the plan rather than after somebody has already armed it.
    for line in installinfo.describe(installinfo.detect(root)):
        print(line)
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


def cmd_arm(root, names, start_game=False):
    state = load()
    h = hold(root)

    # What is out is answered by the holding directory, never by the ledger.
    # The ledger can come back empty; the files cannot.
    already = h.held()
    if already['out'] or already['conflict']:
        print('%d file(s) are already out. Run restore first.'
              % (len(already['out']) + len(already['conflict'])),
              file=sys.stderr)
        print('\n'.join(holdlog.report(already)), file=sys.stderr)
        return 2

    matched, missing = resolve(root, names)
    if not matched:
        print('none of those names are deployed - nothing to move.',
              file=sys.stderr)
        return 2

    # Everything that must hold is checked before the first file moves. A move
    # that fails halfway leaves a library in a state nobody chose.
    ok, why = h.preflight()
    if not ok:
        for line in why:
            print(line, file=sys.stderr)
        return 2

    info = installinfo.detect(root)
    h.open_session('bisect_mods', info)
    for line in installinfo.describe(info):
        print(line)
    print('')

    moved, failed = [], []
    for name in sorted(matched):
        for rel in matched[name]:
            ok, err = h.hold_file(name, rel)
            if ok:
                moved.append({'mod': name, 'rel': rel})
            elif err != 'not deployed':
                failed.append((rel, err))

    if failed and not info['second_copy']:
        # No manager can put this right, so a half-armed round is not something
        # to hand back to somebody. Undo it and let them fix the cause.
        back, problems = h.restore_all()
        print('could not arm the whole round, and this install has no second '
              'copy to fall\nback on - so the round was undone. %d file(s) put '
              'back.' % back, file=sys.stderr)
        for rel, err in failed:
            print('   FAILED %s  %s' % (rel, err), file=sys.stderr)
        for rel, err in problems:
            print('   STILL OUT %s  %s' % (rel, err), file=sys.stderr)
        return 2

    if not state['candidates']:
        state['candidates'] = sorted(matched)
    state.update({'target': root, 'hold': HOLD,
                  'round_disabled': sorted({i['mod'] for i in moved}),
                  'armed_at': time.time()})
    save(state)

    print('armed: %d file(s) from %d mod(s) moved out'
          % (len(moved), len({i['mod'] for i in moved})))
    if missing:
        print('skipped %d name(s) not deployed: %s'
              % (len(missing), ', '.join(missing)))
    for rel, why in failed:
        print('   FAILED %s  %s' % (rel, why))

    if start_game:
        up, why = launch()
        print('\n%s' % why)
        if up:
            print('ROUND IS UP - when you see the game, perform the failing '
                  'action, then: bisect_mods.py check')
        else:
            print('Nothing was scored. Launch it yourself, or re-arm.')
    else:
        print('\nLaunch the game and perform the failing action, '
              'then: bisect_mods.py check')
    return 1 if failed else 0


def cmd_restore():
    """Put everything back, driven by the holding directory rather than the
    ledger - so it works with a lost ledger, a corrupt one, or none at all."""
    state = load()
    h = hold(state.get('target'))
    before = h.held()
    if not (before['out'] or before['conflict'] or before['missing']):
        print('nothing is out')
        return 0

    back, failed = h.restore_all()
    print('restored %d file(s)' % back)
    if before['missing']:
        print('\nMISSING - %d file(s) the journal recorded are on neither '
              'side.' % len(before['missing']))
        print('Something outside this tool moved or deleted them; they cannot '
              'be restored')
        print('from here. Reinstall those mods from their source:')
        for i in before['missing'][:10]:
            print('   %-50s (%s)' % (i['rel'], i['mod']))
    for rel, why in failed:
        print('   FAILED %-45s %s' % (rel, why))

    if not failed:
        state['armed_at'] = None
        state['round_disabled'] = []
        save(state)
    return 1 if (failed or before['missing']) else 0


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

    root = state.get('target') or ROOT
    h = hold(root)
    held = h.held()
    info = (installinfo.detect(held['root']) if held['root']
            and os.path.isdir(held['root']) else None)
    print('')
    print('\n'.join(holdlog.report(held, info)))

    if held['conflict']:
        # Same observation, two different events. Under a manager it is a
        # redeploy, which is routine and voids the round. Without one, nothing
        # ordinary puts a file back, so it is worth saying so rather than
        # blaming a manager that is not installed.
        if info and info['kind'] == 'vortex':
            print('\nThe mod manager redeployed. This round is void; restore '
                  'and arm it again.')
        else:
            print('\nSomething outside this tool put those files back. This '
                  'round is void.')
        return 1
    return 1 if held['missing'] else 0


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

    # Three situations all produce no exception file and only one is a pass.
    # Collapsing them into "clean" is a false exoneration, the exact failure
    # this tool exists to prevent, so each gets its own verdict.
    if not hits:
        if started:
            # The game is up and has written nothing YET. One real round read
            # as clean 51 seconds in and failed at three minutes; the reports
            # arrive when the player triggers the thing, not at startup.
            print('IN PROGRESS - the game is running and has written nothing '
                  'yet.', file=sys.stderr)
            print('That is not a pass, it is a round nobody has answered. '
                  'Re-run after the', file=sys.stderr)
            print('failing action, or once the game has exited.',
                  file=sys.stderr)
            return 2
        if not ran_since(floor):
            # Never played, or died before the first frame - too fast to write
            # a report and gone before any process poll could have seen it.
            print('NO EVIDENCE - no exception file, and nothing shows the game '
                  'ran since', file=sys.stderr)
            print('this round was armed. Not scored. Either it was never '
                  'played, or it died', file=sys.stderr)
            print('before the first frame, which is a different symptom from '
                  'the one being bisected.', file=sys.stderr)
            return 2

    # What this round disabled is strategy, recorded when the round was armed.
    # Deliberately not re-derived from the holding directory: the question here
    # is what the round TESTED, and a file that has since been put back by a
    # redeploy does not change that - it invalidates the round, which `status`
    # reports separately.
    disabled = sorted(state['round_disabled'])
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
    ap.add_argument('--launch', action='store_true',
                    help='start the game once the round is armed')
    a = ap.parse_args(argv)

    if a.action in ('plan', 'arm'):
        if not a.file:
            print('%s needs a file of mod names' % a.action, file=sys.stderr)
            return 2
        if not os.path.isdir(a.root):
            print('no Mods folder at %s' % a.root, file=sys.stderr)
            return 2
        names = wanted(a.file)
        if a.action == 'plan':
            return cmd_plan(a.root, names)
        return cmd_arm(a.root, names, a.launch)
    if a.action == 'check':
        return cmd_check(a.marker)
    if a.action == 'restore':
        return cmd_restore()
    return cmd_status()


if __name__ == '__main__':
    sys.exit(main())
