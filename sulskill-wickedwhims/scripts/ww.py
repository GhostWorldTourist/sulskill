#!/usr/bin/env python3
"""Read and edit WickedWhims settings profiles.

OWNERSHIP RULE: this script only ever writes to profiles it created itself
(marked with "_managed_by"). Profiles you made in-game are read-only here, so
your own settings can never be clobbered. Use `init` to create a managed
profile, then switch to it in WickedWhims' in-game settings.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import datetime
import glob
import json
import os
import shutil
import sys
import time

import os as _os
# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
PROFILE_DIR = _os.path.join(SIMS, 'saves', 'WickedWhimsMod',
                            'settings_profiles')
MARK = "_managed_by"
# Artifacts are stamped with the name of the skill that owns them, in the
# same form the skills themselves use. One convention, and it survives a
# rename because it is derived from the skill name rather than invented.
OWNER = "sulskill-wickedwhims"
# Profiles written before the rename carry the old marker. Treat them as
# ours too, or this script stops recognising files it created itself and
# refuses to touch them.
LEGACY_OWNERS = ("claude-wwskill", "sulskill", "sulskill/wickedwhims")


def profile_paths(directory):
    return sorted(glob.glob(os.path.join(directory, 'SettingsProfile_*.json')))


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save(path, data, backup=True):
    if backup and os.path.exists(path):
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        bak = f"{path}.{stamp}.bak"
        shutil.copy2(path, bak)
        print(f"  backup -> {bak}")
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, separators=(', ', ': '))


def is_managed(d):
    return d.get(MARK) == OWNER or d.get(MARK) in LEGACY_OWNERS


def count(d):
    return sum(len(v) for v in d.get('data', {}).values() if isinstance(v, dict))


def all_profiles(directory):
    return [(p, load(p)) for p in profile_paths(directory)]


def resolve(directory, wanted, require_managed=False):
    loaded = all_profiles(directory)
    if not loaded:
        sys.exit(f"no profiles found in {directory}")
    if wanted:
        m = [(p, d) for p, d in loaded
             if wanted.lower() in str(d.get('name', '')).lower()
             or wanted.lower() in os.path.basename(p).lower()]
        if not m:
            names = ', '.join(str(d.get('name')) for _, d in loaded)
            sys.exit(f"no profile matching {wanted!r}. available: {names}")
        if len(m) > 1:
            sys.exit(f"{wanted!r} is ambiguous: "
                     + ', '.join(str(d.get('name')) for _, d in m))
        path, d = m[0]
    else:
        managed = [(p, d) for p, d in loaded if is_managed(d)]
        pool = managed or loaded
        pool.sort(key=lambda pd: -count(pd[1]))
        path, d = pool[0]
    if require_managed and not is_managed(d):
        sys.exit(
            f"REFUSING to write to {d.get('name')!r} - not created by this skill.\n"
            f"  Your in-game profiles are read-only here.\n"
            f"  Run:  ww.py init --name wwskill_1 --from {d.get('name')}\n"
            f"  then switch to it in WickedWhims' in-game settings.")
    return path, d


def cmd_init(args):
    existing = all_profiles(args.dir)
    for p, d in existing:
        if d.get('name') == args.name:
            sys.exit(f"profile {args.name!r} already exists: {os.path.basename(p)}")
    base = {}
    base_name = None
    base_version = None
    if args.copy_from:
        _, src = resolve(args.dir, args.copy_from)
        base = json.loads(json.dumps(src.get('data', {})))
        base_name = src.get('name')
        base_version = src.get('mod_version')
    elif existing:
        rich = max(existing, key=lambda pd: count(pd[1]))
        base_version = rich[1].get('mod_version')

    created = int(time.time())
    fname = f"SettingsProfile_{args.name}{created}.json"
    path = os.path.join(args.dir, fname)
    prof = {
        "name": args.name,
        "file_name": fname,
        "identifier": -(created % 10_000_000),
        "created_at": created,
        "mod_version": base_version or "unknown",
        "version_control": 4,
        MARK: OWNER,
        "data": base,
    }
    save(path, prof, backup=False)
    print(f"created managed profile {args.name!r}")
    print(f"  {path}")
    print(f"  {count(prof)} settings"
          + (f" copied from {base_name!r}" if base_name else " (empty - WW defaults)"))
    print("\nNEXT: in-game, open WickedWhims settings and switch the active")
    print(f"      settings profile to {args.name!r}. Until you do, edits here")
    print("      have no effect on your game.")
    print("\nNOTE: a hand-created profile is not something WW writes itself.")
    print("      Verify it appears in the in-game profile list before relying on it.")


def cmd_profiles(args):
    loaded = all_profiles(args.dir)
    print(f"{len(loaded)} profile(s) in {args.dir}\n")
    for p, d in loaded:
        tag = "MANAGED (writable)" if is_managed(d) else "yours (read-only here)"
        n = count(d)
        note = '  (empty - inherits defaults)' if n == 0 else ''
        print(f"  {d.get('name')}   [{d.get('mod_version')}]  {n} settings"
              f" in {len(d.get('data', {}))} categories{note}")
        print(f"      {os.path.basename(p)}   {tag}")


def cmd_categories(args):
    path, d = resolve(args.dir, args.profile)
    print(f"profile: {d.get('name')}  ({os.path.basename(path)})\n")
    for cat, vals in sorted(d.get('data', {}).items()):
        if isinstance(vals, dict):
            print(f"  {cat:<20} {len(vals)} settings")
    if not d.get('data'):
        print("  (no settings stored - inherits WW defaults)")


def cmd_search(args):
    path, d = resolve(args.dir, args.profile)
    term = args.term.lower()
    hits = []
    for cat, vals in sorted(d.get('data', {}).items()):
        if isinstance(vals, dict):
            for k, v in sorted(vals.items()):
                if term in k.lower() or term in cat.lower():
                    hits.append((f"{cat}.{k}", v))
    print(f"profile {d.get('name')}: {len(hits)} match(es) for {args.term!r}\n")
    for k, v in hits:
        print(f"  {k} = {json.dumps(v)}")


def split_addr(addr):
    if '.' not in addr:
        sys.exit(f"ERROR: expected CATEGORY.KEY, got {addr!r}")
    return addr.split('.', 1)


def cmd_get(args):
    path, d = resolve(args.dir, args.profile)
    data = d.get('data', {})
    for addr in args.keys:
        cat, key = split_addr(addr)
        if cat in data and key in data[cat]:
            print(f"  {addr} = {json.dumps(data[cat][key])}")
        else:
            print(f"  {addr} = <NOT FOUND>")
            for c, vals in data.items():
                for n in [k for k in vals if key.lower() in k.lower()][:4]:
                    print(f"        did you mean: {c}.{n}")


def coerce(raw, current):
    if isinstance(current, bool):
        return raw.strip().lower() in ('true', '1', 'yes', 'on')
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, (dict, list)):
        return json.loads(raw)
    return raw


def game_running():
    """True if The Sims 4 is running.

    WW keeps its settings in memory and writes the whole profile out when the
    game saves, so an edit made while TS4 is up gets overwritten. This was
    documented as prose the user had to remember; enforcing it is cheaper.
    Changes apply on next save load anyway, so waiting costs nothing.
    """
    import subprocess
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq TS4_x64.exe'],
                             capture_output=True, text=True, timeout=20).stdout
        return 'TS4_x64.exe' in out
    except Exception:
        return False        # can't tell - don't block the user


def refuse_if_running(force):
    if game_running() and not force:
        sys.exit("ERROR: The Sims 4 is running.\n"
                 "  WickedWhims rewrites its profile from memory when the game\n"
                 "  saves, which would discard this edit. Settings apply on next\n"
                 "  save load, so quitting first costs nothing.\n"
                 "  Quit the game and re-run, or pass --force.")


def cmd_set(args):
    refuse_if_running(getattr(args, 'force', False))
    path, d = resolve(args.dir, args.profile, require_managed=True)
    data = d.setdefault('data', {})
    changes = []
    for pair in args.assignments:
        if '=' not in pair:
            sys.exit(f"ERROR: expected CATEGORY.KEY=VALUE, got {pair!r}")
        addr, raw = pair.split('=', 1)
        cat, key = split_addr(addr.strip())
        if cat not in data or key not in data[cat]:
            if not args.allow_new:
                sys.exit(f"ERROR: unknown setting {addr!r} in {d.get('name')!r} "
                         "(WW ignores unrecognized settings silently). "
                         "Use 'search', or --allow-new.")
            data.setdefault(cat, {})
            old, new = None, raw
        else:
            old = data[cat][key]
            try:
                new = coerce(raw, old)
            except (ValueError, json.JSONDecodeError) as e:
                sys.exit(f"ERROR: {addr}: {e}")
        if old == new:
            print(f"  {addr} already {json.dumps(new)} - skipped")
            continue
        changes.append((addr, old, new))
        data[cat][key] = new

    if not changes:
        print("nothing to change.")
        return
    print(f"target: managed profile {d.get('name')!r}")
    if args.dry_run:
        print("DRY RUN - not written:")
    for addr, old, new in changes:
        print(f"  {addr}: {json.dumps(old)} -> {json.dumps(new)}")
    if args.dry_run:
        return
    save(path, d)
    print(f"\nwrote {path}")
    print("close the game before editing; applies when the save is next loaded.")


def flatten(d):
    out = {}
    for cat, vals in d.get('data', {}).items():
        if isinstance(vals, dict):
            for k, v in vals.items():
                out[f"{cat}.{k}"] = v
    return out


def cmd_diff(args):
    _, da = resolve(args.dir, args.a)
    _, db = resolve(args.dir, args.b)
    fa, fb = flatten(da), flatten(db)
    keys = sorted(set(fa) | set(fb))
    diff = [(k, fa[k], fb[k]) for k in keys if k in fa and k in fb and fa[k] != fb[k]]
    only_a = [k for k in keys if k not in fb]
    only_b = [k for k in keys if k not in fa]
    print(f"A = {da.get('name')} ({len(fa)})\nB = {db.get('name')} ({len(fb)})\n")
    print(f"{len(diff)} differing, {len(only_a)} only in A, {len(only_b)} only in B\n")
    for k, va, vb in diff[:200]:
        print(f"  {k}\n      A: {json.dumps(va)}\n      B: {json.dumps(vb)}")
    if only_a:
        print(f"\n  only in A: {len(only_a)} (e.g. {', '.join(only_a[:5])})")
    if only_b:
        print(f"  only in B: {len(only_b)} (e.g. {', '.join(only_b[:5])})")


def cmd_export(args):
    path, d = resolve(args.dir, args.profile)
    preset = {'_source_profile': d.get('name'),
              '_mod_version': d.get('mod_version'),
              'data': d.get('data', {})}
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(preset, f, indent=2, sort_keys=True)
    print(f"exported {count(d)} settings from {d.get('name')} -> {args.out}")
    print("NOTE: portable preset, not a Vortex-installable mod - WW settings")
    print("      live under saves\\, so there is nothing for Vortex to deploy.")


def cmd_import(args):
    refuse_if_running(getattr(args, 'force', False))
    path, d = resolve(args.dir, args.profile, require_managed=True)
    with open(args.src, encoding='utf-8') as f:
        preset = json.load(f)
    incoming = preset.get('data', {})
    if not incoming:
        sys.exit(f"{args.src} has no 'data' block")
    data = d.setdefault('data', {})
    n = 0
    for cat, vals in incoming.items():
        for k, v in vals.items():
            if data.get(cat, {}).get(k) != v:
                data.setdefault(cat, {})[k] = v
                n += 1
    print(f"applying {n} changed setting(s) to managed profile {d.get('name')!r}")
    if args.dry_run:
        print("DRY RUN - not written.")
        return
    save(path, d)
    print(f"wrote {path}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--dir', default=PROFILE_DIR)
    p.add_argument('--profile', help='profile name or filename fragment')
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('init', help='create a managed profile this skill may write')
    s.add_argument('--name', default='wwskill_1')
    s.add_argument('--from', dest='copy_from',
                   help='seed values from an existing profile')
    s.set_defaults(func=cmd_init)

    sub.add_parser('profiles', help='list profiles').set_defaults(func=cmd_profiles)
    sub.add_parser('categories', help='list categories').set_defaults(func=cmd_categories)

    s = sub.add_parser('search', help='find settings'); s.add_argument('term')
    s.set_defaults(func=cmd_search)

    s = sub.add_parser('get'); s.add_argument('keys', nargs='+', metavar='CATEGORY.KEY')
    s.set_defaults(func=cmd_get)

    s = sub.add_parser('set', help='change settings (managed profiles only)')
    s.add_argument('assignments', nargs='+', metavar='CATEGORY.KEY=VALUE')
    s.add_argument('--allow-new', action='store_true')
    s.add_argument('--dry-run', action='store_true')
    s.add_argument('--force', action='store_true', help='write even if the game is running')
    s.set_defaults(func=cmd_set)

    s = sub.add_parser('diff'); s.add_argument('a'); s.add_argument('b')
    s.set_defaults(func=cmd_diff)

    s = sub.add_parser('export'); s.add_argument('out'); s.set_defaults(func=cmd_export)

    s = sub.add_parser('import'); s.add_argument('src')
    s.add_argument('--dry-run', action='store_true')
    s.add_argument('--force', action='store_true', help='write even if the game is running')
    s.set_defaults(func=cmd_import)

    args = p.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
