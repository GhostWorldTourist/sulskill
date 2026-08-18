"""Enumerate every diagnostic artifact on the install, and rank them.

Why this exists
---------------
A real investigation spent twenty-five bisect rounds narrowing towards a cause
that was named, in plain text, twenty-one times, in a file nobody opened. The
file was `mc_lastexception.html` - MC Command Center's own crash dump, sitting
in the Mods folder the whole time. A second file written in the same minute,
a WickedWhims exception report, independently corroborated it.

Neither was missed through carelessness. They were missed because the reader was
working from a **remembered list** of artifacts - lastException, lastUIException,
a handful of named mod logs - and anything not on that list did not exist. A
longer list would have fixed that one investigation and not the next one.

So this ships no list of files to go and find. It walks the install, treats
anything that looks diagnostic as evidence, and prints what it cannot identify
**loudest of all** - because the unrecognised file is the one that ends up
holding the answer.

    py scripts/evidence.py                  everything, worth-reading first
    py scripts/evidence.py --since-launch   only what the last session wrote
    py scripts/evidence.py --json           machine-readable

Exit 0 if there is nothing to read, 1 if there is evidence, 2 if the install
could not be found.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import os, sys, json, argparse, datetime

# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')

# Deliberately broad. A false positive costs one line of output; a false
# negative costs an investigation.
SUSPECT = ('.log', '.txt', '.html', '.xml', '.json', '.dmp', '.mdmp')
WORDS = ('exception', 'crash', 'error', 'log', 'report', 'dump', 'debug')
ALWAYS = ('.log', '.dmp', '.mdmp')

# Ranked by what a file is worth when something is broken, not by how well known
# it is. The top two are the ones that were missed.
KNOWN = (
    ('mc_lastexception',
     'MCCC crash dump - the failing frame WITH ITS LOCALS and arguments. Read '
     'this first; it routinely names a mod that the game report only shows the '
     'wreckage of', 1),
    ('_exception',
     'a mod shipping its own exception file - usually the mod closest to the '
     'fault, and more specific than the game-wide report', 2),
    ('lastexception',
     'game Python/gameplay exceptions. Un-suffixed means the most recent '
     'session; a _<timestamp> suffix means it was rotated at a later launch', 3),
    ('lastuiexception',
     'ActionScript/UI - a DIFFERENT layer. A UI-only failure leaves '
     'lastException clean, so "no exceptions" is not health', 3),
    ('guard',
     'a containment guard log - these only write when they fire, so any '
     'content at all means a fault was caught', 4),
    ('betterexceptions', 'Better Exceptions output or configuration', 4),
    ('config.log',
     'the game own startup log - proves a launch happened, and when', 5),
)


def classify(name):
    low = name.lower()
    for needle, why, rank in KNOWN:
        if needle in low:
            return why, rank
    return None, 9


def named_diagnostic(name):
    """Does the NAME alone say this is diagnostic?"""
    low = name.lower()
    if not low.endswith(SUSPECT):
        return False
    return low.endswith(ALWAYS) or any(w in low for w in WORDS)


def suspect_extension(name):
    return name.lower().endswith(SUSPECT)


def scan(root, mods_depth=3):
    """Every diagnostic-looking file under the install."""
    out, seen = [], set()
    roots = [(root, 1)]
    mods = os.path.join(root, 'Mods')
    if os.path.isdir(mods):
        roots.append((mods, mods_depth))
    for base, depth in roots:
        base_depth = base.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(base):
            if dirpath.count(os.sep) - base_depth >= depth:
                dirnames[:] = []
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                if full in seen or not suspect_extension(fn):
                    continue
                seen.add(full)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                why, rank = classify(fn)
                out.append({'path': os.path.relpath(full, root), 'name': fn,
                            'bytes': st.st_size, 'mtime': st.st_mtime,
                            'why': why, 'rank': rank,
                            'named': named_diagnostic(fn),
                            'recognised': why is not None})
    return out


def diagnostic(items, fresh_from):
    """Keep what is diagnostic by name, or by having been written this session.

    Requiring a diagnostic-sounding name would put the filter back on a list,
    which is the failure this script exists to avoid: the file holding the
    answer is the one nobody has a name for. But listing every .txt under Mods
    buries the signal under mod readmes, which is its own failure.

    Recency breaks the tie. A readme is not rewritten when the game launches;
    something the game or a mod just produced is evidence whatever it is called.
    """
    return [i for i in items
            if i['named'] or (fresh_from and i['mtime'] >= fresh_from)]


def launched_at(items):
    """When the game last ran, from whatever wrote most recently.

    Any log the game or a mod writes is evidence of a launch, so taking the
    newest avoids depending on one particular mod being installed.
    """
    times = [i['mtime'] for i in items if i['name'].lower().endswith('.log')]
    return max(times) if times else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--root', default=SIMS)
    ap.add_argument('--since-launch', action='store_true',
                    help='only what was written in the most recent session')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--limit', type=int, default=40)
    a = ap.parse_args(argv)

    if not os.path.isdir(a.root):
        print('no Sims 4 folder at %s' % a.root, file=sys.stderr)
        return 2

    everything = scan(a.root)
    launch = launched_at(everything)
    # A session writes its files over a minute or two, so anything within five
    # minutes of the newest log belongs to the same run.
    fresh_from = (launch - 300) if launch else None
    items = diagnostic(everything, fresh_from)
    if a.since_launch and fresh_from:
        items = [i for i in items if i['mtime'] >= fresh_from]

    if a.json:
        json.dump({'root': a.root, 'last_launch': launch, 'items': items},
                  sys.stdout, indent=1)
        return 1 if items else 0

    if not items:
        print('no diagnostic artifacts under %s' % a.root)
        return 0

    fresh = [i for i in items if fresh_from and i['mtime'] >= fresh_from]
    print('%d artifact(s); %d from the most recent session\n'
          % (len(items), len(fresh)))

    for i in sorted(items, key=lambda x: (x['rank'], -x['mtime']))[:a.limit]:
        when = datetime.datetime.fromtimestamp(i['mtime']).strftime('%Y-%m-%d %H:%M')
        mark = '*' if fresh_from and i['mtime'] >= fresh_from else ' '
        print('%s %s  %9d  %s' % (mark, when, i['bytes'], i['path']))
        if i['why']:
            print('      %s' % i['why'])

    unknown = [i for i in items if not i['recognised']]
    if unknown:
        # The whole point of the script. A file nobody has a name for is not a
        # file nobody needs to read - it is the one holding the answer.
        print('\n%d file(s) this tool cannot identify. READ THEM ANYWAY:'
              % len(unknown))
        for i in sorted(unknown, key=lambda x: -x['mtime'])[:25]:
            when = datetime.datetime.fromtimestamp(i['mtime']).strftime('%Y-%m-%d %H:%M')
            print('  %s  %9d  %s' % (when, i['bytes'], i['path']))

    if not any('mc_lastexception' in i['name'].lower() for i in items):
        print('\nNo mc_lastexception.html here. MC Command Center is either not')
        print('installed or has not crashed yet. Its dump carries the failing')
        print('frame with locals and arguments, which the game report does not,')
        print('and it is the single most useful thing to add to a library you')
        print('intend to diagnose.')

    print('\n* = written during the most recent session.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
