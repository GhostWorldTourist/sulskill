#!/usr/bin/env python3
"""Read what Basemental Drugs currently has configured, by inspecting the save.

Why reading the SAVE and not a config file
------------------------------------------
Basemental stores its settings as traits stamped onto every human teen-or-older
Sim (library.pyc::add_trait iterates sim_info_manager().get_all()). There is no
settings file. So "what is legal here" is answered by asking whether the Sims in
the save carry LEG_<WORLD>.

That also means this tool is read-only by design. Writing would mean equipping
traits behind the mod's back - a second configurator fighting the first.
"""
import argparse
import collections
import glob
import json
import os
import struct
import sys
import zlib

SIMS = os.environ.get('SIMS4_DIR') or os.path.join(
    os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
SAVES = os.path.join(SIMS, 'saves')
REF = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', 'reference', 'basemental.json')
WORLDS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      '..', '..', 'sims4-worlds', 'reference', 'worlds.json')


def load_ref():
    with open(os.path.normpath(REF), encoding='utf-8') as f:
        return json.load(f)


def load_worlds():
    try:
        with open(os.path.normpath(WORLDS), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def newest_save():
    saves = [p for p in glob.glob(os.path.join(SAVES, 'Slot_*.save'))]
    if not saves:
        sys.exit(f"no saves in {SAVES}")
    return max(saves, key=os.path.getmtime)


def sim_blob(path):
    """The 0x0D resource holds sim/household data."""
    with open(path, 'rb') as f:
        head = f.read(96)
        if head[:4] != b'DBPF':
            sys.exit(f"not a save file: {path}")
        cnt = struct.unpack_from('<I', head, 0x24)[0]
        isz = struct.unpack_from('<I', head, 0x2C)[0]
        ioff = struct.unpack_from('<Q', head, 0x40)[0]
        f.seek(ioff)
        ix = f.read(isz)
        flags = struct.unpack_from('<I', ix, 0)[0]
        p, const = 4, {}
        for bit, k in ((0, 't'), (1, 'g'), (2, 'h')):
            if flags & (1 << bit):
                const[k] = struct.unpack_from('<I', ix, p)[0]
                p += 4
        out = []
        for _ in range(cnt):
            t = const.get('t')
            if t is None:
                t = struct.unpack_from('<I', ix, p)[0]; p += 4
            if const.get('g') is None:
                p += 4
            if const.get('h') is None:
                p += 4
            p += 4
            off = struct.unpack_from('<I', ix, p)[0]; p += 4
            fsz = struct.unpack_from('<I', ix, p)[0]; p += 4
            p += 4
            comp = 0
            if fsz & 0x80000000:
                comp = struct.unpack_from('<H', ix, p)[0]; p += 4
            if t != 0x0000000D:
                continue
            f.seek(off)
            raw = f.read(fsz & 0x7FFFFFFF)
            out.append(zlib.decompress(raw) if comp == 0x5A42 else raw)
    if not out:
        sys.exit("no sim data (0x0D) in save")
    return b''.join(out)


def varints(blob):
    """Every varint value in the blob, counted.

    Trait ids are protobuf varints, so rather than reconstruct the whole message
    schema we harvest candidate values and match them against known ids.

    Validated against a real save: EA's own trait ids come out at plausible
    counts - 34318 (young adult) on 102 Sims, 276492 (attracted to women) on 60 -
    which is what confirms an ABSENT id means the trait genuinely is not in the
    save rather than that the scan missed it.

    No magnitude filter: Basemental ids are all > 2**63, but EA's are small, and
    filtering would silently make this useless for anything but Basemental.
    """
    counts = collections.Counter()
    i, n = 0, len(blob)
    while i < n:
        v = s = 0
        start = i
        while i < n:
            b = blob[i]
            i += 1
            v |= (b & 0x7F) << s
            if not b & 0x80:
                break
            s += 7
            if s > 63:
                v = None
                break
        if v is not None:
            counts[v] += 1
        if i == start:
            i += 1
    return counts


def cmd_state(args):
    ref = load_ref()
    worlds = load_worlds()
    path = args.save or newest_save()
    print(f"save: {os.path.basename(path)}")
    print(f"      {os.path.getsize(path):,} bytes, "
          f"modified {__import__('datetime').datetime.fromtimestamp(os.path.getmtime(path))}\n")

    present = varints(sim_blob(path))
    by_id = {v: k for k, v in ref['traits'].items()}
    found = {by_id[v]: c for v, c in present.items() if v in by_id}

    # map Basemental trait -> readable world name
    label = {}
    if worlds:
        for w in worlds['worlds'].values():
            if w.get('basemental_trait'):
                label[w['basemental_trait']] = w['display']
                label[w.get('basemental_gambling_trait', '')] = w['display']

    for group in ('legalize_cannabis', 'legalize_gambling', 'police',
                  'parental_reactions', 'criminal_record', 'addiction', 'npcs'):
        members = ref['trait_groups'].get(group, [])
        on = [m for m in members if m in found]
        print(f"--- {group}  ({len(on)}/{len(members)} set) ---")
        if not on:
            print("      none")
        for m in sorted(on, key=lambda x: label.get(x, x)):
            nm = label.get(m, m)
            print(f"      {nm:<24} {m:<26} x{found[m]}")
        print()

    if args.all:
        other = {k: v for k, v in found.items()
                 if not any(k in ref['trait_groups'].get(g, [])
                            for g in ref['trait_groups'])}
        if other:
            print("--- other Basemental traits seen ---")
            for k, v in sorted(other.items(), key=lambda kv: -kv[1])[:40]:
                print(f"      {k:<34} {v}")


def cmd_menus(args):
    ref = load_ref()
    print(f"{ref['counts']['menus']} settings menus\n")
    for name, m in sorted(ref['menus'].items()):
        short = name.replace('basemental_settings_', '').replace('_menu', '')
        if args.filter and args.filter.lower() not in short.lower():
            continue
        print(f"  {short:<22} {m['script']}")
        if m['controls']:
            print(f"     controls: {', '.join(m['controls'][:6])}"
                  + (f"  (+{len(m['controls']) - 6})" if len(m['controls']) > 6 else ""))


def cmd_traits(args):
    ref = load_ref()
    term = (args.term or '').lower()
    hits = {k: v for k, v in ref['traits'].items() if term in k.lower()}
    print(f"{len(hits)} trait(s) matching {args.term!r}\n")
    for k in sorted(hits):
        print(f"  {k:<34} {hits[k]}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('state', help='what is currently configured, from the save')
    s.add_argument('--save', help='explicit .save path (default: newest)')
    s.add_argument('--all', action='store_true', help='also list ungrouped traits')
    s.set_defaults(func=cmd_state)

    s = sub.add_parser('menus', help='the in-game settings surface')
    s.add_argument('--filter')
    s.set_defaults(func=cmd_menus)

    s = sub.add_parser('traits', help='look up trait ids by name')
    s.add_argument('term', nargs='?', default='')
    s.set_defaults(func=cmd_traits)

    a = p.parse_args()
    a.func(a)


if __name__ == '__main__':
    main()
