#!/usr/bin/env python3
"""Read and edit frankk's Language Barriers settings (lb_settings.cfg).

The mod gives Sims native and second languages and makes conversation depend on
whether they share one. Its config is a plain sectioned text file, so unlike
Basemental (traits in the save) or MCCC (rewritten from memory in-game), this one
is genuinely a file you can edit.

Where the file lives
--------------------
`fklb/data/configurations.pyc::get_config` resolves 'lb_settings.cfg' relative to
`__file__` - the script's OWN directory. So the cfg must sit beside
frankk_LanguageBarriers.ts4script, wherever that ends up. Vortex deploying the
mod folder flat into Mods\\Vortex Mods\\ satisfies that; a cfg left behind in a
subfolder does not, and the mod logs 'SETTINGS FILE MISSING' and runs on
defaults rather than failing loudly.

The file is optional. The README says to delete it if you are not customising,
which means an absent file is normal and not a fault.

Format
------
Sections in [BRACKETS], then `Key = Value` with padding for alignment. The
regional section is different: each line is a WORLD, and its value is

    Native / Secondary, Secondary, ...

Native before the slash, comma-separated secondaries after.
"""
import argparse
import json
import os
import re
import shutil
import sys
import datetime

SIMS = os.environ.get('SIMS4_DIR') or os.path.join(
    os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
WORLDS_REF = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          '..', '..', 'sims4-worlds', 'reference', 'worlds.json')

REGION_SECTION = 'REGIONAL LANGUAGES'


def find_cfg():
    """Beside the script if deployed, else the Vortex staging copy."""
    for root in (os.path.join(SIMS, 'Mods'),
                 os.path.join(os.environ.get('APPDATA', ''), 'Vortex',
                              'thesims4', 'mods')):
        if not os.path.isdir(root):
            continue
        for dp, _, fn in os.walk(root):
            if 'lb_settings.cfg' in fn:
                return os.path.join(dp, 'lb_settings.cfg')
    return None


def parse(path):
    """-> (sections, order) preserving section order and raw key spelling."""
    sections, order, cur = {}, [], None
    for raw in open(path, encoding='utf-8').read().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        m = re.fullmatch(r'\[(.+)\]', line)
        if m:
            cur = m.group(1).strip()
            sections[cur] = {}
            order.append(cur)
            continue
        if cur is None or '=' not in line:
            continue
        k, v = line.split('=', 1)
        sections[cur][k.strip()] = v.strip()
    return sections, order


def write(path, sections, order):
    """Rewrite preserving section order and the file's aligned look."""
    if os.path.exists(path):
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        shutil.copy2(path, f"{path}.{stamp}.bak")
        print(f"  backup -> {os.path.basename(path)}.{stamp}.bak")
    out = []
    for i, sec in enumerate(order):
        if i:
            out.append('')
            out.append('')
        out.append(f'[{sec}]')
        keys = sections[sec]
        width = max((len(k) for k in keys), default=0)
        for k, v in keys.items():
            out.append(f'{k.ljust(width)} = {v}')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(out) + '\n')


def languages(sections):
    """Every language named anywhere in the regional table."""
    langs = set()
    for v in sections.get(REGION_SECTION, {}).values():
        native, _, rest = v.partition('/')
        langs.add(native.strip())
        langs.update(x.strip() for x in rest.split(',') if x.strip())
    return sorted(l for l in langs if l)


def known_worlds():
    try:
        with open(os.path.normpath(WORLDS_REF), encoding='utf-8') as f:
            d = json.load(f)
        return {w['display']: w for w in d['worlds'].values()}
    except Exception:
        return {}


def cmd_show(args):
    path = args.cfg or find_cfg()
    if not path:
        sys.exit("lb_settings.cfg not found (the mod treats it as optional)")
    sections, order = parse(path)
    print(f"{path}\n")
    for sec in order:
        if sec == REGION_SECTION and not args.all:
            print(f"[{sec}]  ({len(sections[sec])} worlds - use 'regions')\n")
            continue
        print(f"[{sec}]")
        for k, v in sections[sec].items():
            print(f"  {k:<22} {v}")
        print()


def cmd_regions(args):
    path = args.cfg or find_cfg()
    if not path:
        sys.exit("lb_settings.cfg not found")
    sections, _ = parse(path)
    table = sections.get(REGION_SECTION, {})
    worlds = known_worlds()

    print(f"{len(table)} world(s) mapped; languages: {', '.join(languages(sections))}\n")
    for world, val in table.items():
        if args.filter and args.filter.lower() not in (world + val).lower():
            continue
        native, _, rest = val.partition('/')
        second = [x.strip() for x in rest.split(',') if x.strip()]
        print(f"  {world:<20} native {native.strip():<14} + {', '.join(second)}")

    if worlds:
        # The mod's world list and the game's are not the same. Vacation worlds
        # with no residents have nobody to assign a language to.
        # Compare case-insensitively: the mod writes "Strangerville" where EA
        # writes "StrangerVille", and treating that as an unknown world would
        # report a problem that does not exist.
        lower = {w.lower() for w in table}
        missing = [n for n in worlds
                   if worlds[n].get('landmass') and not worlds[n].get('hidden')
                   and n.lower() not in lower]
        known_lower = {n.lower() for n in worlds}
        unknown = [w for w in table if w.lower() not in known_lower]
        if missing:
            print(f"\n  in the game but NOT mapped: {', '.join(sorted(missing))}")
        if unknown:
            print(f"  mapped but not a known world: {', '.join(sorted(unknown))}")


def cmd_set(args):
    path = args.cfg or find_cfg()
    if not path:
        sys.exit("lb_settings.cfg not found")
    sections, order = parse(path)
    valid_langs = set(languages(sections))
    changes = []
    for pair in args.assignments:
        if '=' not in pair:
            sys.exit(f"expected [SECTION.]KEY=VALUE, got {pair!r}")
        addr, val = pair.split('=', 1)
        addr, val = addr.strip(), val.strip()
        sec, _, key = addr.rpartition('.')
        if sec:
            sec = sec.upper()
            if sec not in sections:
                sys.exit(f"unknown section [{sec}]; have: {', '.join(sections)}")
            target = [sec]
        else:
            target = [s for s in sections if key in sections[s]]
            if not target:
                near = [f"{s}.{k}" for s in sections for k in sections[s]
                        if key.lower() in k.lower()][:5]
                sys.exit(f"unknown key {key!r}"
                         + (f"; did you mean {', '.join(near)}" if near else ""))
            if len(target) > 1:
                sys.exit(f"{key!r} is in several sections: "
                         + ", ".join(f"{s}.{key}" for s in target))
        sec = target[0]
        if key not in sections[sec]:
            sys.exit(f"{sec} has no key {key!r}")
        # A regional line must name languages the mod actually knows about;
        # a typo here silently gives that world no shared language at all.
        if sec == REGION_SECTION:
            native, _, rest = val.partition('/')
            named = [native.strip()] + [x.strip() for x in rest.split(',') if x.strip()]
            bad = [n for n in named if n and n not in valid_langs]
            if bad and not args.force:
                sys.exit(f"unknown language(s) {bad}; known: {sorted(valid_langs)}\n"
                         "  (pass --force if adding a language from an add-on)")
        old = sections[sec][key]
        if old == val:
            print(f"  {sec}.{key} already {val!r} - skipped")
            continue
        changes.append((sec, key, old, val))
        sections[sec][key] = val

    if not changes:
        print("nothing to change.")
        return
    for sec, key, old, new in changes:
        print(f"  [{sec}] {key}: {old!r} -> {new!r}")
    if args.dry_run:
        print("\nDRY RUN - not written")
        return
    write(path, sections, order)
    print(f"\nwrote {path}\n  takes effect on next game load.")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--cfg', help='explicit lb_settings.cfg path')
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('show', help='all behavioural settings')
    s.add_argument('--all', action='store_true', help='include the regional table')
    s.set_defaults(func=cmd_show)

    s = sub.add_parser('regions', help='world -> native/second languages')
    s.add_argument('--filter')
    s.set_defaults(func=cmd_regions)

    s = sub.add_parser('set', help='change settings')
    s.add_argument('assignments', nargs='+', metavar='[SECTION.]KEY=VALUE')
    s.add_argument('--dry-run', action='store_true')
    s.add_argument('--force', action='store_true',
                   help='allow language names the base mod does not define')
    s.set_defaults(func=cmd_set)

    a = p.parse_args()
    a.func(a)


if __name__ == '__main__':
    main()
