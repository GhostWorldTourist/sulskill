#!/usr/bin/env python3
"""Read, explain, and edit the settings of Kuttoe's Sims 4 mods from disk.

Each configurable Kuttoe mod keeps a flat JSON file at
    saves\\Kuttoe\\[Kuttoe] <Mod>_Settings.cfg
and some also register console commands under `kuttoe.<ns>.`. Settings are
addressed here as `Mod.key`, or bare `key` when it is unambiguous.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import collections
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

import os as _os
# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
CFGDIR = os.path.join(SIMS, "saves", "Kuttoe")
SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      '..', 'reference', 'kuttoe_schema.json')
DESCS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     '..', 'reference', 'kuttoe_descriptions.json')


PROFILE = os.path.join(SIMS, "saves", "SulSkill", "sims4_profile.json")


def load_profile():
    """Shared per-save facts (lifespan, scaling factors) that every mod-config
    skill reads. Lives beside the other mods' data in saves\\, not in the repo,
    because it describes this game rather than this tooling."""
    try:
        with open(PROFILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def save_profile(p):
    os.makedirs(os.path.dirname(PROFILE), exist_ok=True)
    if os.path.exists(PROFILE):
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        shutil.copy2(PROFILE, f"{PROFILE}.{stamp}.bak")
    with open(PROFILE, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(p, f, indent=2)
        f.write('\n')


def load_descs():
    try:
        with open(os.path.normpath(DESCS), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'settings': {}, 'patterns': []}


def describe(mod, key, d):
    """Meaning of a setting, with its provenance.

    Exact entries win over patterns. `source` matters: 'itch.io' was read off
    Kuttoe's own page and can be stated as fact, while 'inferred' was deduced
    from the key name and value and must be reported as inference.
    """
    addr = f"{mod}.{key}"
    hit = d.get('settings', {}).get(addr)
    if hit:
        return hit
    for pat in d.get('patterns', []):
        if re.search(pat['match'], addr):
            return pat
    return None


def load_schema():
    try:
        with open(os.path.normpath(SCHEMA), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        sys.exit("no schema - run: py scripts/extract_kuttoe.py")


def cfg_path(mod, sch):
    p = sch['mods'].get(mod, {}).get('config')
    if not p:
        sys.exit(f"{mod} has no config file")
    return p


def load_cfg(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_cfg(path, data):
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    if os.path.exists(path):
        bak = f"{path}.{stamp}.bak"
        shutil.copy2(path, bak)
        print(f"  backup -> {os.path.basename(bak)}")
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, indent=4, sort_keys=False)
        f.write('\n')


def game_running():
    """Kuttoe's framework rewrites the whole settings file when a console command
    changes a value, so a disk edit made while TS4 is up can be discarded."""
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq TS4_x64.exe'],
                             capture_output=True, text=True, timeout=20).stdout
        return 'TS4_x64.exe' in out
    except Exception:
        return False


def resolve(addr, sch):
    """'Mod.key' -> (mod, key); a bare key is accepted when unique across mods."""
    mods = sch['mods']
    if '.' in addr:
        mod, key = addr.split('.', 1)
        if mod in mods:
            return mod, key
    hits = [(m, addr) for m, d in mods.items() if addr in d['settings']]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        near = [f"{m}.{k}" for m, d in mods.items()
                for k in d['settings'] if addr.lower() in k.lower()][:6]
        sys.exit(f"unknown setting {addr!r}"
                 + (f"\n  did you mean: {', '.join(near)}" if near else ""))
    sys.exit(f"{addr!r} exists in several mods: "
             + ", ".join(f"{m}.{addr}" for m, _ in hits)
             + "\n  qualify it as Mod.key")


def coerce(raw, current, declared):
    if isinstance(current, bool) or declared == 'bool':
        low = raw.strip().lower()
        if low in ('true', '1', 'yes', 'on'):
            return True
        if low in ('false', '0', 'no', 'off'):
            return False
        raise ValueError(f"expected a boolean, got {raw!r}")
    if isinstance(current, float) or declared == 'float':
        return float(raw)
    if isinstance(current, int) and not isinstance(current, bool):
        return int(raw)
    if isinstance(current, (list, dict)) or declared in ('list', 'dict'):
        return json.loads(raw)
    return raw


# ------------------------------------------------------------------ commands
def cmd_mods(args):
    sch = load_schema()
    print(f"{sch['counts']['configurable_mods']} configurable Kuttoe mod(s); "
          f"{sch['counts']['settings']} settings, {sch['counts']['commands']} console commands\n")
    for name, m in sorted(sch['mods'].items()):
        if args.filter and args.filter.lower() not in name.lower():
            continue
        n = len(m['settings'])
        c = len(m['commands'])
        tag = '' if m['config'] else '   (no config file - commands only)'
        print(f"  {name:<28} {n:>4} settings  {c:>3} commands{tag}")
    if sch.get('config_without_script'):
        print(f"\n  config with no matching script: {sch['config_without_script']}")


def cmd_list(args):
    sch = load_schema()
    m = sch['mods'].get(args.mod)
    if not m:
        near = [k for k in sch['mods'] if args.mod.lower() in k.lower()]
        sys.exit(f"unknown mod {args.mod!r}" + (f"; did you mean {near}" if near else ""))
    d = load_descs()
    print(f"{args.mod}  ({len(m['settings'])} settings)")
    print(f"  config: {m['config']}\n")
    for k, v in sorted(m['settings'].items()):
        cur = json.dumps(v.get('current'))[:44] if 'current' in v else '<not in file>'
        print(f"  {k:<42} {cur}")
        if args.describe:
            desc = describe(args.mod, k, d)
            if desc:
                mark = '' if desc.get('source', '').startswith('itch.io') else '~ '
                print(f"        {mark}{wrap(desc['text'], 10)}")


def cmd_search(args):
    sch = load_schema()
    term = args.term.lower()
    n = 0
    for mod, m in sorted(sch['mods'].items()):
        hits = [(k, v) for k, v in sorted(m['settings'].items())
                if term in k.lower() or term in json.dumps(v.get('current', '')).lower()]
        if hits:
            print(f"\n{mod}")
            for k, v in hits:
                print(f"  {k:<42} {json.dumps(v.get('current'))[:60]}")
                n += 1
    print(f"\n{n} match(es) for {args.term!r}")


def cmd_get(args):
    sch = load_schema()
    for addr in args.keys:
        mod, key = resolve(addr, sch)
        s = sch['mods'][mod]['settings'][key]
        print(f"  {mod}.{key} = {json.dumps(s.get('current'))}")


def wrap(text, indent=16, width=94):
    out, line = [], ''
    for w in text.split():
        if len(line) + len(w) + 1 > width - indent:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    out.append(line)
    return ('\n' + ' ' * indent).join(out)


def cmd_explain(args):
    sch = load_schema()
    d = load_descs()
    for addr in args.keys:
        mod, key = resolve(addr, sch)
        s = sch['mods'][mod]['settings'][key]
        print(f"\n  {mod}.{key} = {json.dumps(s.get('current'))}")
        desc = describe(mod, key, d)
        if desc:
            src = desc.get('source', '?')
            tag = 'DOCUMENTED' if src.startswith('itch.io') else 'INFERRED'
            print(f"      [{tag} - {src}]")
            print(f"      {wrap(desc['text'], 6)}")
            if desc.get('unit'):
                print(f"      unit      {desc['unit']}")
            if desc.get('type_note'):
                print(f"      note      {wrap(desc['type_note'], 16)}")
        elif 'absent from config' in (s.get('note') or ''):
            # Derived from a console command whose stem is not a stored key -
            # an in-game action, not a persisted setting.
            print("      [COMMAND ONLY]")
            print("      Runs an action in-game; nothing is stored in the config "
                  "file, so there is nothing to set from disk here.")
        else:
            print("      [NO DESCRIPTION] name and value are the only evidence; "
                  "say so if you interpret it")
        print(f"      type      {s.get('type', '?')}   (from bytecode + live value)")
        if s.get('command'):
            print(f"      command   {s['command']}    <- also settable in-game")
        if s.get('note'):
            print(f"      note      {s['note']}")
        print(f"      file      {os.path.basename(sch['mods'][mod]['config'] or '-')}")


def cmd_commands(args):
    sch = load_schema()
    for mod, m in sorted(sch['mods'].items()):
        if args.mod and args.mod.lower() not in mod.lower():
            continue
        if not m['commands']:
            continue
        print(f"\n{mod}")
        for c in m['commands']:
            print(f"  {c}")


def cmd_set(args):
    sch = load_schema()
    # A dry run writes nothing, so the running-game guard must not block it.
    if not args.dry_run and game_running() and not args.force:
        sys.exit("ERROR: The Sims 4 is running.\n"
                 "  Kuttoe's settings framework rewrites the whole file when a\n"
                 "  console command changes a value, which would discard this edit.\n"
                 "  Quit the game and re-run, or pass --force.\n"
                 "  (Or set it in-game with the mod's kuttoe.* console command.)")
    by_mod = collections.defaultdict(list)
    for pair in args.assignments:
        if '=' not in pair:
            sys.exit(f"ERROR: expected [Mod.]KEY=VALUE, got {pair!r}")
        addr, raw = pair.split('=', 1)
        mod, key = resolve(addr.strip(), sch)
        by_mod[mod].append((key, raw))

    for mod, pairs in by_mod.items():
        path = cfg_path(mod, sch)
        d = load_cfg(path)
        changes = []
        for key, raw in pairs:
            if key not in d:
                sys.exit(f"ERROR: {mod}.{key} is not in {os.path.basename(path)} "
                         "(the mod would ignore it)")
            declared = sch['mods'][mod]['settings'].get(key, {}).get('type')
            try:
                new = coerce(raw, d[key], declared)
            except (ValueError, json.JSONDecodeError) as e:
                sys.exit(f"ERROR: {mod}.{key}: {e}")
            if d[key] == new:
                print(f"  {mod}.{key} already {json.dumps(new)} - skipped")
                continue
            changes.append((key, d[key], new))
            d[key] = new
        if not changes:
            continue
        print(f"\n{mod}  ->  {os.path.basename(path)}")
        for k, o, n in changes:
            print(f"  {k}: {json.dumps(o)} -> {json.dumps(n)}")
        if args.dry_run:
            print("  DRY RUN - not written")
            continue
        save_cfg(path, d)
        print(f"  wrote {path}")
    if not args.dry_run:
        print("\ntakes effect on next game load.")


def time_scale(p):
    """How much longer a life is here than the mod defaults assume.

    Always derived, never stored. The whole point of the profile is that setting
    the lifespan is the only action required - a hand-maintained factor beside it
    is one more thing to leave stale.
    """
    ls = p['lifespan']
    return ls['active_days'] / ls['reference_days']


def rescaled(base, scale, s):
    """Apply the derived scale in the direction the setting's encoding needs.

    'down' is not a different intention from 'up' - it is the same one written
    against a value expressed as a percentage of normal, where a longer life
    wants a smaller number.
    """
    if scale == 'up':
        val = base * s
    elif scale == 'down':
        val = base / s
    else:
        return None
    return round(val) if isinstance(base, int) else round(val, 2)


def cmd_profile(args):
    """Show or edit the shared save profile."""
    p = load_profile()
    if p is None:
        sys.exit(f"no profile at {PROFILE}")
    ls = p['lifespan']

    if args.lifespan:
        if args.lifespan not in ls['presets']:
            sys.exit(f"unknown preset {args.lifespan!r}; "
                     f"known: {', '.join(ls['presets'])}")
        ls['active_preset'] = args.lifespan
        ls['active_days'] = ls['presets'][args.lifespan]
        save_profile(p)
        print(f"updated {PROFILE}\n")

    print(f"lifespan  : {ls['active_preset']} = {ls['active_days']} days")
    print(f"reference : {ls['reference_preset']} = {ls['reference_days']} days "
          "(what mod defaults assume)")
    print(f"scale     : {time_scale(p):.2f}x  (derived - nothing to set)")
    print(f"\npresets: " + ", ".join(f"{k}={v}" for k, v in ls['presets'].items()))

    pins = p.get('scaling', {}).get('pins', {})
    if pins:
        print(f"\npinned by hand ({len(pins)}) - rescale will not touch these:")
        for addr, val in sorted(pins.items()):
            print(f"  {addr:<44} = {val}")


def cmd_rescale(args):
    """Recompute time-gated settings from the lifespan in the profile.

    Always from the mod default, never from the current value, so running this
    repeatedly is idempotent rather than compounding. Whether a setting moves at
    all is decided per setting in the reference data by one test - does the thing
    run out? - not by a global factor applied to everything time-shaped.
    """
    sch, d = load_schema(), load_descs()
    p = load_profile()
    if p is None:
        sys.exit(f"no profile at {PROFILE}")
    s = args.scale if args.scale is not None else time_scale(p)
    pins = p.get('scaling', {}).get('pins', {})

    print(f"scale {s:.2f}x   (lifespan {p['lifespan']['active_days']}d "
          f"vs reference {p['lifespan']['reference_days']}d)\n")
    plan = collections.defaultdict(dict)
    held = []
    live = {}

    def current(mod, key):
        """Read from the config file, not the schema.

        The schema is a snapshot taken by the last extract, so it goes stale the
        moment anything is `set`. A dry run that prints a stale 'now' is worse
        than no dry run at all - and the write path already compares against the
        file, so reading anything else here would just disagree with it.
        """
        if mod not in live:
            try:
                live[mod] = load_cfg(cfg_path(mod, sch))
            except Exception:
                live[mod] = {}
        return live[mod].get(key)

    for addr, meta in sorted(d.get('scaling', {}).items()):
        mod, key = addr.split('.', 1)
        cur = current(mod, key)
        base, how = meta['base'], meta.get('scale', 'no')

        if addr in pins:
            # A pin is a chosen value, not a note about one - so it is applied
            # like any other, just never computed.
            val = pins[addr]
            plan[mod][key] = val
            note = '' if cur == val else '  <-- change'
            print(f"  pin  {addr:<40} {val} by hand (now {cur}){note}")
            continue
        val = rescaled(base, how, s)
        if val is None:
            held.append((addr, 'no', meta.get('why', '')))
            continue

        lo, hi = meta.get('min'), meta.get('max')
        clamped = None
        if hi is not None and val > hi:
            val, clamped = hi, f"wanted {rescaled(base, how, s)}, max is {hi}"
        elif lo is not None and val < lo:
            val, clamped = lo, f"wanted {rescaled(base, how, s)}, min is {lo}"

        plan[mod][key] = val
        note = '' if cur == val else '  <-- change'
        print(f"  {how:<4} {addr:<40} base {base} -> {val} (now {cur}){note}")
        if clamped:
            print(f"       CLAMPED: {clamped}. The range cannot express this "
                  f"lifespan; a paired setting may be the real dial.")

    for addr, why, detail in held:
        print(f"  {'hold' if why == 'pinned' else 'keep':<4} {addr:<40} {detail}")

    if args.dry_run:
        print("\nDRY RUN - not written")
        return
    if game_running() and not args.force:
        sys.exit("\nERROR: The Sims 4 is running - quit first, or pass --force.")
    total = 0
    for mod, items in plan.items():
        path = cfg_path(mod, sch)
        cfg = load_cfg(path)
        changes = {k: v for k, v in items.items() if cfg.get(k) != v}
        if not changes:
            continue
        cfg.update(changes)
        save_cfg(path, cfg)
        print(f"\n  wrote {os.path.basename(path)} ({len(changes)} change(s))")
        total += len(changes)
    print(f"\n{total} setting(s) changed"
          + ("; takes effect on next game load." if total else " - already in sync."))


def cmd_apply(args):
    """Apply a batch of settings from a JSON file.

    Shaped for wide changes that would be unwieldy as KEY=VALUE pairs - e.g.
    Home Regions' 60 per-world keys. The file is either {"key": value, ...} for a
    single mod (with --mod), or {"plan": {...}} as produced by a planning script.
    Values are used as-is, so they must already be the right JSON type; every key
    must exist in the target config.
    """
    sch = load_schema()
    if not args.dry_run and game_running() and not args.force:
        sys.exit("ERROR: The Sims 4 is running - quit first, or pass --force.")
    with open(args.file, encoding='utf-8') as f:
        doc = json.load(f)
    plan = doc.get('plan', doc)

    by_mod = collections.defaultdict(dict)
    for key, val in plan.items():
        if args.mod:
            by_mod[args.mod][key] = val
        else:
            mod, k = resolve(key, sch)
            by_mod[mod][k] = val

    total = 0
    for mod, items in by_mod.items():
        path = cfg_path(mod, sch)
        d = load_cfg(path)
        unknown = [k for k in items if k not in d]
        if unknown:
            sys.exit(f"ERROR: {mod}: {len(unknown)} key(s) not in "
                     f"{os.path.basename(path)}: {unknown[:6]}")
        changes = [(k, d[k], v) for k, v in items.items() if d[k] != v]
        print(f"\n{mod}  ->  {os.path.basename(path)}")
        print(f"  {len(changes)} change(s) of {len(items)} key(s) in the plan")
        for k, o, n in changes[:args.show]:
            print(f"    {k}: {json.dumps(o)[:40]} -> {json.dumps(n)[:60]}")
        if len(changes) > args.show:
            print(f"    ... +{len(changes) - args.show} more")
        if args.dry_run or not changes:
            if args.dry_run:
                print("  DRY RUN - not written")
            continue
        for k, _, n in changes:
            d[k] = n
        save_cfg(path, d)
        print(f"  wrote {path}")
        total += len(changes)
    if not args.dry_run:
        print(f"\n{total} setting(s) changed; takes effect on next game load.")


def cmd_status(args):
    sch = load_schema()
    print(f"config dir : {sch['config_dir']}")
    print(f"game running: {game_running()}")
    missing = [m for m, d in sch['mods'].items()
               if d['config'] and not os.path.exists(d['config'])]
    stale = []
    for mod, m in sch['mods'].items():
        if not m['config'] or not os.path.exists(m['config']):
            continue
        try:
            live = load_cfg(m['config'])
        except Exception as e:
            stale.append(f"{mod}: UNREADABLE ({e})")
            continue
        known = set(m['settings'])
        drift = (set(live) - known) | {k for k in known
                                       if 'current' in m['settings'][k] and k not in live}
        if drift:
            stale.append(f"{mod}: {len(drift)} key(s) differ from schema -> re-run extract_kuttoe.py")
    print(f"\n{len(sch['mods'])} mods, {sch['counts']['settings']} settings")
    for s in stale:
        print(f"  {s}")
    if missing:
        print(f"  missing config files: {missing}")
    if not stale and not missing:
        print("  schema matches the live config files.")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('mods', help='configurable mods and their counts')
    s.add_argument('--filter'); s.set_defaults(func=cmd_mods)

    s = sub.add_parser('list', help='every setting of one mod')
    s.add_argument('mod')
    s.add_argument('--describe', action='store_true',
                   help='include plain-language meanings (~ marks inferred)')
    s.set_defaults(func=cmd_list)

    s = sub.add_parser('search', help='find settings by name or value')
    s.add_argument('term'); s.set_defaults(func=cmd_search)

    s = sub.add_parser('get', help='read settings')
    s.add_argument('keys', nargs='+', metavar='[Mod.]KEY'); s.set_defaults(func=cmd_get)

    s = sub.add_parser('explain', help='type, console command, and file for a setting')
    s.add_argument('keys', nargs='+', metavar='[Mod.]KEY'); s.set_defaults(func=cmd_explain)

    s = sub.add_parser('commands', help='console commands, optionally for one mod')
    s.add_argument('mod', nargs='?'); s.set_defaults(func=cmd_commands)

    s = sub.add_parser('set', help='change settings (type-checked)')
    s.add_argument('assignments', nargs='+', metavar='[Mod.]KEY=VALUE')
    s.add_argument('--dry-run', action='store_true')
    s.add_argument('--force', action='store_true',
                   help='write even if the game is running')
    s.set_defaults(func=cmd_set)

    s = sub.add_parser('profile', help='show/edit the shared save profile')
    s.add_argument('--lifespan', help='switch active preset (e.g. custom_long)')
    s.set_defaults(func=cmd_profile)

    s = sub.add_parser('rescale', help='recompute time-gated settings from the profile')
    s.add_argument('--scale', type=float,
                   help='override the derived scale once, to preview a what-if')
    s.add_argument('--dry-run', action='store_true')
    s.add_argument('--force', action='store_true')
    s.set_defaults(func=cmd_rescale)

    s = sub.add_parser('apply', help='apply a JSON batch of settings')
    s.add_argument('file')
    s.add_argument('--mod', help='target mod (skip per-key resolution)')
    s.add_argument('--show', type=int, default=12, help='how many changes to print')
    s.add_argument('--dry-run', action='store_true')
    s.add_argument('--force', action='store_true')
    s.set_defaults(func=cmd_apply)

    sub.add_parser('status', help='schema vs live config drift').set_defaults(func=cmd_status)

    args = p.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
