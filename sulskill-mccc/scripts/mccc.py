#!/usr/bin/env python3
"""Read and edit MC Command Center settings.

mc_settings.cfg is JSON despite the extension, and MCCC rewrites it itself
whenever settings change in-game, so edits go to the live file by default and
survive on their own terms.

With a mod manager installed, edits can instead be staged as a managed mod and
deployed - useful for versioning a settings set or shipping it between installs.
Without one, the live file is the only target and is used automatically.

The config is found wherever MCCC actually put it: a manager's deployment
folder, or straight in Mods for a manual install.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import collections
import datetime
import json
import os
import shutil
import subprocess
import sys
import zipfile

import os as _os
# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
# MCCC writes its configs beside its own scripts, wherever those ended up: a
# manager's deployment folder, or straight in Mods for a manual install. Find
# them rather than assuming one layout - the hardcoded manager path made every
# command silently invisible to anyone who installs by hand.
LIVE = (gate.find_mod_file("mc_settings.cfg")
        or os.path.join(SIMS, "Mods", "mc_settings.cfg"))
DRESSER = (gate.find_mod_file("mc_dresser.cfg")
           or os.path.join(SIMS, "Mods", "mc_dresser.cfg"))
STAGING_ROOT = _os.environ.get('VORTEX_TS4_MODS') or _os.path.join(
    _os.environ.get('APPDATA', _os.path.expanduser('~')), 'Vortex', 'thesims4', 'mods')
# Same convention as every other artifact: named for the owning skill.
# A folder name cannot contain a slash, which is the only reason this is
# hyphenated rather than namespaced with one.
MANAGED = "sulskill-mccc-settings"      # the mod this skill owns
# Renamed from an older assistant-branded name. Anything still using it is
# adopted on sight rather than orphaned.
LEGACY_MANAGED = ("ClaudeMCCCSettings", "SulSkillMCCCSettings",
                  "SulSkill_MCCC_Settings")
HELP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    '..', 'reference', 'mccc_help.json')
SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      '..', 'reference', 'mccc_schema.json')


# ---------------------------------------------------------------- plumbing
def have_vortex():
    return os.path.isdir(STAGING_ROOT)


def managed_dir():
    """Locate our staging mod.

    Installing the zip through Vortex creates its OWN staging folder (named
    after the archive, often with an id suffix), so prefer any staging folder
    that already holds an mc_settings.cfg and looks like ours.
    """
    exact = os.path.join(STAGING_ROOT, MANAGED)
    if os.path.exists(os.path.join(exact, 'mc_settings.cfg')):
        return exact
    if os.path.isdir(STAGING_ROOT):
        wanted = (MANAGED,) + LEGACY_MANAGED
        cands = [d for d in sorted(os.listdir(STAGING_ROOT))
                 if any(w.lower() in d.lower() for w in wanted)
                 and os.path.exists(os.path.join(STAGING_ROOT, d, 'mc_settings.cfg'))]
        if cands:
            return os.path.join(STAGING_ROOT, cands[0])
    return exact


def managed_cfg():
    return os.path.join(managed_dir(), 'mc_settings.cfg')


def target_path(args):
    """Where writes go.

    Default is the LIVE config: mc_settings.cfg is NOT a Vortex-managed file
    (MCCC creates it at runtime and it is absent from the deployment manifest),
    so direct edits are durable and are not reverted by a redeploy.
    --managed opts into the packaged-mod workflow instead.
    """
    if getattr(args, 'managed', False) and have_vortex():
        return managed_cfg()
    return LIVE


def read_path(args):
    if getattr(args, 'file', None):
        return args.file
    if getattr(args, 'managed', False) and have_vortex() \
            and os.path.exists(managed_cfg()):
        return managed_cfg()
    return LIVE


def load(path):
    """Read a config, failing with something a player can act on.

    mc_settings.cfg is JSON despite the extension. A hand-edit that drops a
    comma leaves the game silently on defaults, and the raw JSONDecodeError
    traceback tells someone who does not write code nothing at all - so say
    which file, which line, and what to do about it.
    """
    with open(path, encoding='utf-8') as f:
        text = f.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        line = text.splitlines()[e.lineno - 1] if e.lineno <= len(
            text.splitlines()) else ''
        sys.exit(f"{path}\n"
                 f"  is not valid JSON: {e.msg} at line {e.lineno}, "
                 f"column {e.colno}\n"
                 f"  {line.strip()[:70]}\n"
                 f"  MCCC rewrites this file itself; if you edited it by hand, "
                 f"the usual cause is a\n  missing comma or a trailing one "
                 f"before a closing brace. Fix that line, or delete\n"
                 f"  the file and let MCCC regenerate it with defaults.")


def dump_text(data):
    return json.dumps(data, indent=4, sort_keys=True) + '\n'


def save(path, data, backup=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if backup and os.path.exists(path):
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        bak = f"{path}.{stamp}.bak"
        shutil.copy2(path, bak)
        print(f"  backup -> {bak}")
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(dump_text(data))


def ensure_managed():
    """Seed the managed mod from the live file the first time."""
    m = managed_cfg()
    if os.path.exists(m):
        return False
    if not os.path.exists(LIVE):
        sys.exit(f"no live config to seed from: {LIVE}")
    os.makedirs(managed_dir(), exist_ok=True)
    shutil.copy2(LIVE, m)
    print(f"  seeded managed mod from live config ({len(load(m))} settings)")
    return True


def build_zip(data, out, name):
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        # root of archive -> deploys to Mods\Vortex Mods\ where MCCC looks
        z.writestr('mc_settings.cfg', dump_text(data))
        z.writestr('README.txt',
                   f"{name}\n\nMCCC settings ({len(data)} settings), managed by the\n"
                   "sulskill-mccc skill. mc_settings.cfg sits at the archive root so\n"
                   "Vortex deploys it beside the MCCC scripts; MCCC does not read\n"
                   "subfolders.\n\nMCCC rewrites this file when settings change\n"
                   "in-game, so Vortex may report it as externally modified.\n")
    return out


def load_help():
    try:
        with open(os.path.normpath(HELP), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'verified': {}, 'ambiguous': {}, 'all_strings': []}


def load_schema():
    """Type/default/range/legal-codes per setting, extracted from MCCC's bytecode.

    Regenerate with scripts/extract_schema.py after an MCCC update.
    """
    try:
        with open(os.path.normpath(SCHEMA), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'settings': {}, 'difficulty_curve': {}}


def game_running():
    """True if The Sims 4 is running.

    This matters for writes: MCCC holds its whole config in memory and flushes
    ALL of it to mc_settings.cfg whenever a setting is changed in-game. A write
    made while the game is up is therefore liable to be silently overwritten,
    and since settings only load at game start it buys nothing anyway.
    """
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq TS4_x64.exe'],
                             capture_output=True, text=True, timeout=20).stdout
        return 'TS4_x64.exe' in out
    except Exception:
        return False        # can't tell - don't block the user


def validate(key, value, schema):
    """Return an error string if `value` is illegal for `key`, else None.

    MCCC does not reject a bad value; the branch that reads it simply matches
    nothing, so the feature quietly disappears. Setting Show_Computer_Menu_Type
    to 'S' (legal for the SIM menu, meaningless for the computer menu) hides the
    computer menu entirely with no error anywhere. Hence checking up front.
    """
    s = schema.get(key)
    if not s:
        return None
    codes = s.get('codes')
    # Codes marked unreliable came from the heuristic scrape and are known to be
    # incomplete; blocking on them would reject legal values.
    if s.get('codes_reliable') is False:
        codes = None
    if codes and isinstance(value, str):
        if s.get('strlist'):
            if not value.strip():
                return None                      # empty strlist = "all"
            parts = [p.strip() for p in value.split(',') if p.strip()]
        else:
            parts = [value]
        bad = [p for p in parts if p not in codes]
        if bad:
            return (f"{', '.join(repr(b) for b in bad)} not a legal value; "
                    f"MCCC accepts {codes}"
                    + (f"\n      codes from: {s['codes_source']}" if s.get('codes_source') else ""))
    if isinstance(value, int) and not isinstance(value, bool):
        if s.get('min') is not None and value < s['min']:
            return f"{value} is below MCCC's minimum of {s['min']}"
        if s.get('max') is not None and value > s['max']:
            return f"{value} is above MCCC's maximum of {s['max']}"
    return None


def module_of(key):
    return key.split('_')[0] if '_' in key else key


def coerce(raw, current):
    if isinstance(current, bool):
        low = raw.strip().lower()
        if low in ('true', '1', 'yes', 'on'):
            return True
        if low in ('false', '0', 'no', 'off'):
            return False
        raise ValueError(f"expected a boolean, got {raw!r}")
    if isinstance(current, int) and not isinstance(current, bool):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, (dict, list)):
        return json.loads(raw)
    return raw


# ---------------------------------------------------------------- commands
def cmd_status(args):
    print(f"Vortex detected : {have_vortex()}")
    print(f"live config     : {LIVE}")
    print(f"                  {'exists' if os.path.exists(LIVE) else 'MISSING'}"
          f"{', ' + str(len(load(LIVE))) + ' settings' if os.path.exists(LIVE) else ''}")
    m = managed_cfg()
    print(f"managed mod     : {managed_dir()}")
    if os.path.exists(m):
        md = load(m)
        print(f"                  exists, {len(md)} settings")
        if os.path.exists(LIVE):
            lv = load(LIVE)
            diff = [k for k in set(md) | set(lv) if md.get(k) != lv.get(k)]
            print(f"                  {len(diff)} setting(s) differ from live"
                  + (" -> redeploy pending" if diff else ""))
    else:
        print("                  not created yet (run 'set' or 'init')")


def cmd_init(args):
    if not have_vortex():
        # 'init' only exists to create a managed staging mod, which needs a mod
        # manager. Without one there is nothing to initialise - the live file is
        # already the target, so say that rather than naming a flag.
        sys.exit("No mod manager staging folder found, so there is nothing to\n"
                 "initialise: 'set' already writes the live config directly at\n"
                 f"  {LIVE}\n"
                 "This is the normal setup for a manual install.")
    created = ensure_managed()
    print("already initialised." if not created else "initialised.")
    print(f"  {managed_cfg()}")


def cmd_modules(args):
    d = load(read_path(args))
    groups = collections.Counter(module_of(k) for k in d)
    print(f"{len(d)} settings in {read_path(args)}\n")
    for mod, n in groups.most_common():
        if args.filter and args.filter.lower() not in mod.lower():
            continue
        print(f"  {n:>4}  {mod}")


def cmd_search(args):
    d = load(read_path(args))
    term = args.term.lower()
    hits = [(k, v) for k, v in sorted(d.items())
            if term in k.lower() or term in str(v).lower()]
    print(f"{len(hits)} match(es) for {args.term!r}\n")
    for k, v in hits:
        print(f"  {k} = {json.dumps(v)}")


def cmd_get(args):
    d = load(read_path(args))
    for k in args.keys:
        if k in d:
            print(f"  {k} = {json.dumps(d[k])}")
        else:
            print(f"  {k} = <NOT FOUND>")
            for c in [c for c in d if k.lower() in c.lower()][:5]:
                print(f"        did you mean: {c}")


def cmd_explain(args):
    """Describe a setting. Only asserts descriptions we could verify."""
    d = load(read_path(args))
    h = load_help()
    sch = load_schema()
    schema = sch.get('settings', {})
    for k in args.keys:
        cur = json.dumps(d[k]) if k in d else '<not in config>'
        print(f"\n  {k} = {cur}")

        # Schema facts are extracted from MCCC's bytecode, so unlike the tooltip
        # mapping they are exact. Print them for EVERY setting, including the
        # ~400 whose description could never be verified.
        s = schema.get(k, {})
        if any(f in s for f in ('type', 'default', 'min', 'max', 'codes')):
            bits = []
            if 'type' in s:
                bits.append(f"type {s['type']}")
            if 'default' in s:
                bits.append(f"default {json.dumps(s['default'])}")
            if s.get('min') is not None or s.get('max') is not None:
                bits.append(f"range {s.get('min', '-')}..{s.get('max', '-')}")
            print(f"      [SCHEMA - from MCCC's bytecode] {', '.join(bits)}")
            if 'codes' in s:
                print(f"      legal values: {s['codes']}"
                      + (" (comma-separated list; empty = all)" if s.get('strlist') else ""))
        if 'semantics' in s:
            print(f"      [SEMANTICS] {s['semantics']}")
        if k.endswith('_Difficulty_Adjustment'):
            c = sch.get('difficulty_curve', {})
            for lbl, meaning in (c.get('meaning') or {}).items():
                print(f"      {lbl:>16} : {meaning}")

        if k in h['verified']:
            print(f"      [VERIFIED - MCCC's own tooltip]")
            print(f"      {h['verified'][k]}")
            continue
        # fall back to corpus search; present as candidates, never as fact
        toks = [t.lower() for t in
                __import__('re').findall(r'[A-Z][a-z]+|[a-z]+', k) if len(t) > 3]
        scored = []
        for s in h['all_strings']:
            sl = s.lower()
            score = sum(1 for t in toks if t in sl)
            if score:
                scored.append((score, s))
        scored.sort(key=lambda x: (-x[0], -len(x[1])))
        if scored:
            print(f"      [UNVERIFIED - candidate tooltips, judge by wording]")
            for sc, s in scored[:args.candidates]:
                print(f"      ? ({sc}) {s[:220]}")
        else:
            print("      no description found in MCCC's strings; "
                  "check deaderpool-mccc.com")


def cmd_schema(args):
    """Show the machine-verified contract for settings (no guessing involved)."""
    sch = load_schema()
    settings = sch.get('settings', {})
    if not settings:
        sys.exit("no schema yet - run: py scripts/extract_schema.py")
    if not args.keys:
        c = sch.get('counts', {})
        print(f"{c.get('total', len(settings))} settings; "
              f"{c.get('with_type', 0)} typed, {c.get('with_range', 0)} ranged, "
              f"{c.get('with_codes', 0)} with legal-value lists")
        print(f"extracted from {sch.get('generated_from', '?')}")
        print("\nsettings with enumerated legal values:")
        for k, v in sorted(settings.items()):
            if 'codes' in v:
                print(f"  {k:<42} {v['codes']}")
        return
    for k in args.keys:
        v = settings.get(k)
        print(f"\n  {k}")
        if not v:
            near = [c for c in settings if k.lower() in c.lower()][:5]
            print("      not in schema" + (f"; did you mean: {', '.join(near)}" if near else ""))
            continue
        for f in ('type', 'default', 'min', 'max', 'codes', 'strlist', 'note',
                  'semantics', 'codes_source', 'source'):
            if f in v:
                print(f"      {f:<13} {v[f]}")


def cmd_helpsearch(args):
    h = load_help()
    term = args.term.lower()
    hits = [s for s in h['all_strings'] if term in s.lower()]
    print(f"{len(hits)} tooltip(s) mentioning {args.term!r} "
          f"(of {len(h['all_strings'])})\n")
    for s in hits[:args.limit]:
        print(f"  - {s[:300]}\n")


def cmd_set(args):
    if game_running() and not args.force:
        sys.exit("ERROR: The Sims 4 is running.\n"
                 "  MCCC rewrites the whole of mc_settings.cfg from memory when a\n"
                 "  setting is changed in-game, so this write could be discarded.\n"
                 "  Settings only load at game start, so waiting costs nothing.\n"
                 "  Quit the game and re-run, or pass --force.")
    schema = load_schema().get('settings', {})
    if args.managed and have_vortex():
        ensure_managed()
        path = managed_cfg()
        where = f"managed mod ({MANAGED})"
    else:
        path = LIVE
        where = "LIVE config (not Vortex-managed; edits persist across redeploys)"
    d = load(path)
    changes = []
    for pair in args.assignments:
        if '=' not in pair:
            sys.exit(f"ERROR: expected KEY=VALUE, got {pair!r}")
        k, raw = pair.split('=', 1)
        k = k.strip()
        if k not in d:
            if not args.allow_new:
                near = [c for c in d if k.lower() in c.lower()][:5]
                msg = f"ERROR: unknown key {k!r} (MCCC would silently ignore it)."
                if near:
                    msg += "\n  close matches: " + ", ".join(near)
                sys.exit(msg)
            old, new = None, raw
        else:
            old = d[k]
            try:
                new = coerce(raw, old)
            except (ValueError, json.JSONDecodeError) as e:
                sys.exit(f"ERROR: {k}: {e}")
        err = validate(k, new, schema)
        if err and not args.force:
            sys.exit(f"ERROR: {k}: {err}\n"
                     "  MCCC accepts bad values silently - the feature just stops\n"
                     "  working. Fix the value, or pass --force to write it anyway.")
        if err:
            print(f"  WARNING: {k}: {err}")
        if old == new:
            print(f"  {k} already {json.dumps(new)} - skipped")
            continue
        changes.append((k, old, new))
        d[k] = new

    if not changes:
        print("nothing to change.")
        return
    print(f"target: {where}")
    if args.dry_run:
        print("DRY RUN - not written:")
    for k, old, new in changes:
        print(f"  {k}: {json.dumps(old)} -> {json.dumps(new)}")
    if args.dry_run:
        return
    save(path, d)
    print(f"\nwrote {path}")
    if path == LIVE:
        print("takes effect on next game load.")
    else:
        out = build_zip(d, os.path.join(managed_dir(), f"{MANAGED}.zip"), MANAGED)
        print(f"repackaged -> {out}")
        print("\nNEXT: redeploy in Vortex, then load the game.")


def cmd_sync(args):
    """Pull live -> managed, after MCCC rewrote settings in-game."""
    if not os.path.exists(managed_cfg()):
        sys.exit("no managed mod yet; run 'init' first.")
    live, mng = load(LIVE), load(managed_cfg())
    diff = [k for k in set(live) | set(mng) if live.get(k) != mng.get(k)]
    if not diff:
        print("already in sync.")
        return
    print(f"{len(diff)} setting(s) differ (live -> managed):")
    for k in sorted(diff):
        print(f"  {k}: managed {json.dumps(mng.get(k))} <- live {json.dumps(live.get(k))}")
    if args.dry_run:
        print("\nDRY RUN - not written.")
        return
    save(managed_cfg(), live)
    build_zip(live, os.path.join(managed_dir(), f"{MANAGED}.zip"), MANAGED)
    print("\nmanaged mod now matches live; zip rebuilt.")


def cmd_package(args):
    d = load(read_path(args))
    out = args.out or os.path.join(os.getcwd(), f"{args.name}.zip")
    build_zip(d, out, args.name)
    print(f"wrote {out}")
    print(f"  mc_settings.cfg at archive root ({len(d)} settings)")
    print("  install via Vortex; deploys to Mods\\Vortex Mods\\")


def cmd_diff(args):
    a = load(read_path(args))
    b = load(args.other if args.other else LIVE)
    label_b = args.other or LIVE
    keys = sorted(set(a) | set(b))
    diff = [(k, a[k], b[k]) for k in keys if k in a and k in b and a[k] != b[k]]
    print(f"A = {read_path(args)}\nB = {label_b}\n")
    print(f"{len(diff)} differing\n")
    for k, va, vb in diff:
        print(f"  {k}\n      A: {json.dumps(va)}\n      B: {json.dumps(vb)}")
    for k in [k for k in keys if k not in b]:
        print(f"  only in A: {k} = {json.dumps(a[k])}")
    for k in [k for k in keys if k not in a]:
        print(f"  only in B: {k} = {json.dumps(b[k])}")


def cmd_dresser(args):
    path = DRESSER
    if not os.path.exists(path):
        sys.exit(f"not found: {path}\nMCCC only reads mc_dresser.cfg from its own "
                 "folder (Mods\\Vortex Mods\\), not from subfolders.")
    rows = [l.strip() for l in open(path, encoding='utf-8') if l.strip()]
    kinds = collections.Counter(r.split(',')[0].split('.')[0] for r in rows)
    groups = collections.Counter('.'.join(r.split(',')[0].split('.')[1:]) for r in rows)
    print(f"{path}\n{len(rows)} lines (CSV, not JSON)\n")
    print("  record types:", dict(kinds))
    print("\n  per age/gender group:")
    for g, n in sorted(groups.items()):
        print(f"      {g:<14} {n}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--file', help='explicit config to read')
    p.add_argument('--managed', action='store_true',
                   help='use the packaged-mod workflow instead of editing live '
                        '(only needed for portable/versioned presets)')
    sub = p.add_subparsers(dest='cmd', required=True)

    sub.add_parser('status', help='show live vs managed state').set_defaults(func=cmd_status)
    sub.add_parser('init', help='create the managed mod').set_defaults(func=cmd_init)

    s = sub.add_parser('modules', help='settings grouped by module')
    s.add_argument('--filter'); s.set_defaults(func=cmd_modules)

    s = sub.add_parser('search', help='find settings by substring')
    s.add_argument('term'); s.set_defaults(func=cmd_search)

    s = sub.add_parser('get', help='read setting values')
    s.add_argument('keys', nargs='+'); s.set_defaults(func=cmd_get)

    s = sub.add_parser('explain', help='describe a setting (verified or candidates)')
    s.add_argument('keys', nargs='+')
    s.add_argument('--candidates', type=int, default=3)
    s.set_defaults(func=cmd_explain)

    s = sub.add_parser('helpsearch', help='search MCCC tooltip text')
    s.add_argument('term'); s.add_argument('--limit', type=int, default=10)
    s.set_defaults(func=cmd_helpsearch)

    s = sub.add_parser('set', help='change settings (type- and schema-checked)')
    s.add_argument('assignments', nargs='+', metavar='KEY=VALUE')
    s.add_argument('--allow-new', action='store_true')
    s.add_argument('--dry-run', action='store_true')
    s.add_argument('--force', action='store_true',
                   help='write despite a schema violation or a running game')
    s.set_defaults(func=cmd_set)

    s = sub.add_parser('schema', help='verified type/range/legal values for a setting')
    s.add_argument('keys', nargs='*')
    s.set_defaults(func=cmd_schema)

    s = sub.add_parser('sync', help='pull live settings into the managed mod')
    s.add_argument('--dry-run', action='store_true')
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser('package', help='build a Vortex-installable zip')
    s.add_argument('--name', default=MANAGED); s.add_argument('--out')
    s.set_defaults(func=cmd_package)

    s = sub.add_parser('diff', help='compare against live (or another file)')
    s.add_argument('other', nargs='?'); s.set_defaults(func=cmd_diff)

    sub.add_parser('dresser', help='summarize mc_dresser.cfg').set_defaults(func=cmd_dresser)

    args = p.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
