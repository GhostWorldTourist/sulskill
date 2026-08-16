"""Snapshot the Mods tree and diff against the previous snapshot.

Persists snapshot.json so each run compares against the last, not a stale index.
Falls back to the package list in index.pkl, and then to an empty baseline -
with no baseline every file reads as added, which is the truthful answer and
still leaves the script-validity check (which needs no baseline) running.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import os, json, pickle, zipfile, struct, datetime, sys

import os as _os
# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
ROOT = _os.path.join(SIMS, 'Mods')
HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(gate.out_dir(), 'snapshot.json')

pkgs, scripts, other = {}, {}, {}
for dp, _, fns in os.walk(ROOT):
    for fn in fns:
        p = os.path.join(dp, fn)
        rel = os.path.relpath(p, ROOT)
        try:
            st = os.stat(p)
        except OSError:
            continue
        rec = [st.st_size, int(st.st_mtime)]
        low = fn.lower()
        if low.endswith('.package'):
            pkgs[rel] = rec
        elif low.endswith('.ts4script'):
            scripts[rel] = rec
        elif low.endswith(('.cfg', '.json', '.ini', '.py', '.pyc')):
            other[rel] = rec

cur = {'packages': pkgs, 'scripts': scripts, 'other': other}

EMPTY = {'packages': {}, 'scripts': {}, 'other': {}}
PKL = os.path.join(gate.out_dir(), 'index.pkl')

if os.path.exists(SNAP):
    prev = json.load(open(SNAP, encoding='utf-8'))
    src = 'previous snapshot'
elif os.path.exists(PKL):
    old = pickle.load(open(PKL, 'rb'))
    prev = dict(EMPTY, packages={k: [0, 0] for k in old})
    src = 'index.pkl baseline (packages only)'
else:
    # No baseline at all - first run here, or the output directory moved.
    # Everything reads as added, which is honest; a traceback would also skip
    # the script-validity check below, which does not need a baseline at all.
    prev = EMPTY
    src = 'nothing (no baseline yet - run again with --save to establish one)'

print(f"comparing against: {src}\n")
for kind in ('packages', 'scripts', 'other'):
    a, b = prev.get(kind, {}), cur[kind]
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = sorted(k for k in set(a) & set(b)
                     if a[k][0] != b[k][0] and a[k][0] and b[k][0])
    print(f"=== {kind}: {len(a)} -> {len(b)}  (+{len(added)} / -{len(removed)}"
          f" / ~{len(changed)}) ===")
    for k in added:
        sz = b[k][0] / 1048576
        dt = datetime.datetime.fromtimestamp(b[k][1]).strftime('%Y-%m-%d %H:%M')
        print(f"   + {dt}  {sz:8.2f} MB  {k}")
    for k in removed:
        print(f"   - {k}")
    for k in changed:
        print(f"   ~ {k}  ({a[k][0]} -> {b[k][0]} bytes)")
    print()

if '--save' in sys.argv:
    json.dump(cur, open(SNAP, 'w', encoding='utf-8'))
    print('[snapshot saved]')

# validity of every script, every run
MAG = {3394: 'py3.7 OK', 3413: 'py3.8', 3425: 'py3.9', 3439: 'py3.10', 3495: 'py3.11'}
bad = []
for rel in sorted(scripts):
    p = os.path.join(ROOT, rel)
    if rel.count(os.sep) > 1:
        bad.append((rel, f"TOO DEEP ({rel.count(os.sep)} folders); scripts load at depth <=1"))
    if not zipfile.is_zipfile(p):
        bad.append((rel, "NOT A ZIP ARCHIVE - will not load")); continue
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        mags = set()
        for n in names:
            if n.endswith('.pyc'):
                h = z.read(n)[:2]
                if len(h) == 2:
                    mags.add(struct.unpack('<H', h)[0])
    wrong = [m for m in mags if m != 3394]
    if wrong:
        src_ok = any(n.endswith('.py') for n in names)
        bad.append((rel, f"pyc {[MAG.get(m, m) for m in wrong]}"
                    + (" (.py fallback present)" if src_ok else " (NO .py fallback)")))
print(f"=== script validity: {len(scripts)} scripts ===")
if bad:
    for rel, why in bad:
        print(f"   !! {rel}\n        {why}")
else:
    print("   all valid ZIPs, py3.7 bytecode, depth ok")
