#!/usr/bin/env python3
"""Extract every premade Sim in The Sims 4 - name, age, gender, traits, household,
world, and bio - from the game's own packages.

Why the game and not a save
---------------------------
Sim bios are not in a save at all; the only prose in a save's sim blob is the
world description. Save sim data also sits behind a container layer, and a played
save carries the player's own edits. Game data gives the pristine premade roster.

The chain (four resource types, one join each)
----------------------------------------------
    HOUSEHOLD_DESCRIPTION 0x729F6C4F        the hub
      +- u32 STBL key  -> household name
      +- u32 STBL key  -> household BIO
      +- u64           -> LOT_DESCRIPTION 0x01942E2C
      |                     +- u64 -> WORLD_DESCRIPTION 0xA680EA4B
      |                                 +- u64 -> REGION_DESCRIPTION 0xD65DAFF9  (world name)
      +- u64           -> HOUSEHOLD_BINARY 0xB3C438F0   Sims, ages, genders, traits

The bio key is NOT in the household binary - that record is name-literal ("Goth",
"Mortimer") and the localized name/bio live only in the description record.

Gotchas worth keeping
---------------------
* Delta must win over Full, and filename sort gets it backwards: ClientDeltaBuild0
  sorts BEFORE ClientFullBuild0, so a naive sorted() walk leaves the stale Full
  copy in place. Order is forced explicitly below.
* Delta packages ship zero-length HOUSEHOLD_DESCRIPTION records as tombstones.
* HOUSEHOLD_BINARY declares a payload size one byte short of the real remainder
  at version 2 - treat it as a bound, never assert equality.
* Age and walk-style are ordinary entries in the same trait list as personality
  traits; filter by name prefix if you want only personality.
* Only 3 Combined Tuning resources install-wide are XML; the rest are EA's binary
  DATA container, so roughly a fifth of trait ids resolve to a name. The ids
  always extract - only the naming is short.
"""
import argparse
import collections
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'sims4-modbuild', 'scripts'))

from idx import index                                             # noqa: E402
from s4io import get, load_stbl                                   # noqa: E402
from s4types import T                                             # noqa: E402
from pb import parse, uv                                          # noqa: E402
import stbl as stblmod                                            # noqa: E402

CACHE = os.path.join(HERE, '..', 'reference', 'roster.json')
COMBINED_TUNING = 0x62E94D38

HDBASE = {7: 0x46, 10: 0x52, 11: 0x6A, 14: 0x6A, 18: 0x6A}
AGE = {1: 'Baby', 2: 'Toddler', 4: 'Child', 8: 'Teen',
       16: 'YoungAdult', 32: 'Adult', 64: 'Elder'}
GENDER = {4096: 'Male', 8192: 'Female'}

u32 = lambda b, o: struct.unpack_from('<I', b, o)[0]              # noqa: E731
u64 = lambda b, o: struct.unpack_from('<Q', b, o)[0]              # noqa: E731


def packages(root):
    """Every .package, Full before Delta so Delta overrides win on collision."""
    full, delta = [], []
    for dp, _, fn in os.walk(root):
        for f in fn:
            if not f.endswith('.package'):
                continue
            (delta if 'Delta' in f or 'Delta' in dp else full).append(
                os.path.join(dp, f))
    return sorted(full) + sorted(delta)


def collect(root):
    """One pass over every package, gathering everything the roster needs."""
    want = {T['HOUSEHOLD_DESCRIPTION'], T['HOUSEHOLD_BINARY'],
            T['LOT_DESCRIPTION'], T['WORLD_DESCRIPTION'],
            T['REGION_DESCRIPTION'], T['STBL'], COMBINED_TUNING}
    store = collections.defaultdict(dict)
    strings, traits = {}, {}
    for path in packages(root):
        try:
            entries = index(path) or []
        except Exception:
            continue
        for t, g, i, off, fsz, msz, comp in entries:
            if t not in want:
                continue
            try:
                blob = get(path, off, fsz, comp)
            except Exception:
                continue
            if t == T['STBL']:
                try:
                    _, _, d = load_stbl(blob)
                    strings.update(d)
                except Exception:
                    pass
            elif t == COMBINED_TUNING:
                # Only the XML form is readable; the DATA container form needs
                # simdata.py and yields no trait names today.
                if blob[:9] == b'<combined':
                    s = blob.decode('utf-8', 'replace')
                    for m in re.finditer(r'<I ([^>]*)>', s):
                        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
                        if a.get('c') == 'Trait' and 's' in a:
                            traits[int(a['s'])] = a['n']
            else:
                store[t][i] = blob                 # later package wins
    return store, strings, traits


def sims_from_binary(blob):
    """Decode HOUSEHOLD_BINARY protobuf into Sim dicts."""
    if len(blob) < 12:
        return []
    ver = u32(blob, 0)
    p = 4 + (8 if ver >= 2 else 0)
    p += 4                                          # declared size: a bound only
    out = []
    for fn, wt, v in parse(blob[p:]):
        if fn != 1 or wt != 2:
            continue
        for hfn, hwt, hv in parse(v):
            if hfn != 6 or hwt != 2:
                continue
            sim = {'traits': []}
            for sfn, swt, sv in parse(hv):
                if sfn == 5 and swt == 2:
                    sim['first'] = sv.decode('utf-8', 'replace')
                elif sfn == 6 and swt == 2:
                    sim['last'] = sv.decode('utf-8', 'replace')
                elif sfn == 7 and swt == 0:
                    sim['gender'] = GENDER.get(sv, sv)
                elif sfn == 8 and swt == 0:
                    sim['age'] = AGE.get(sv, sv)
                elif sfn == 30 and swt == 2:
                    for tfn, twt, tv in parse(sv):
                        if tfn != 10 or twt != 2:
                            continue
                        for gfn, gwt, gv in parse(tv):
                            if gfn == 1 and gwt == 2:
                                i = 0
                                while i < len(gv):
                                    val, i = uv(gv, i)
                                    sim['traits'].append(val)
            if sim.get('first') or sim.get('last'):
                out.append(sim)
    return out


def build(root):
    store, strings, traits = collect(root)
    HD = store[T['HOUSEHOLD_DESCRIPTION']]
    LOT = store[T['LOT_DESCRIPTION']]
    WORLD = store[T['WORLD_DESCRIPTION']]
    REGION = store[T['REGION_DESCRIPTION']]
    HB = store[T['HOUSEHOLD_BINARY']]

    households = []
    for inst, b in sorted(HD.items()):
        if len(b) < 8:                              # Delta tombstone
            continue
        ver = u32(b, 0)
        base = HDBASE.get(ver)
        if base is None or len(b) < base + 24:
            continue
        lot_id = u64(b, base)
        name_key = u32(b, base + 8)
        bio_key = u32(b, base + 12)
        hb_id = u64(b, base + 16)

        world_name = region_name = None
        lot = LOT.get(lot_id)
        if lot and len(lot) >= 12:
            w = WORLD.get(u64(lot, 4))
            if w and len(w) >= 24:
                world_name = strings.get(u32(w, 4))
                r = REGION.get(u64(w, 16))
                if r and len(r) >= 8:
                    region_name = strings.get(u32(r, 4))

        sims = sims_from_binary(HB[hb_id]) if hb_id in HB else []
        for s in sims:
            s['trait_names'] = [traits.get(t, str(t)) for t in s['traits']]

        households.append({
            'instance': f"0x{inst:X}",
            'version': ver,
            'name': strings.get(name_key),
            'bio': strings.get(bio_key),
            'world': world_name,
            'region': region_name,
            'placed': lot_id != 0,
            'sims': sims,
        })
    return {'households': households,
            'counts': {
                'households': len(households),
                'with_sims': sum(1 for h in households if h['sims']),
                'with_bio': sum(1 for h in households if h['bio']),
                'with_region': sum(1 for h in households if h['region']),
                'named_traits': len(traits),
                'strings': len(strings),
            }}


def load(rebuild=False):
    path = os.path.normpath(CACHE)
    if not rebuild and os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    root = stblmod.game_dir()
    if not root:
        sys.exit("game install not found; set SIMS4_GAME_DIR")
    print(f"scanning {root} ... (a full pass, takes a few minutes)", file=sys.stderr)
    doc = build(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    return doc


def show(h, bio=True):
    where = f"{h['world']} / {h['region']}" if h['region'] else 'unplaced'
    print(f"\n{h['name'] or '?'}  [{h['instance']}]  {where}")
    if bio and h['bio']:
        print(f"   {h['bio']}")
    for s in h['sims']:
        personality = [t for t in s['trait_names']
                       if not t.startswith(('trait_WalkStyle', 'trait_baby',
                                            'trait_toddler', 'trait_child',
                                            'trait_teen', 'trait_youngAdult',
                                            'trait_adult', 'trait_elder'))]
        print(f"   {s.get('first',''):<12} {s.get('last',''):<20} "
              f"{str(s.get('age','')):<11} {str(s.get('gender','')):<7} "
              f"{', '.join(personality)}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--rebuild', action='store_true', help='rescan the game files')
    p.add_argument('--search', help='match household name, Sim name, world or bio')
    p.add_argument('--region', help='only households in this world/region')
    p.add_argument('--unplaced', action='store_true', help='include unplaced households')
    p.add_argument('--no-bio', action='store_true')
    p.add_argument('--counts', action='store_true', help='just the totals')
    a = p.parse_args()

    doc = load(a.rebuild)
    if a.counts:
        for k, v in doc['counts'].items():
            print(f"  {k:<16} {v}")
        return

    hs = doc['households']
    if not a.unplaced:
        hs = [h for h in hs if h['placed']]
    if a.region:
        hs = [h for h in hs if (h['region'] or '').lower() == a.region.lower()
              or (h['world'] or '').lower() == a.region.lower()]
    if a.search:
        t = a.search.lower()
        hs = [h for h in hs if t in json.dumps(h).lower()]
    for h in hs:
        show(h, bio=not a.no_bio)
    print(f"\n{len(hs)} household(s)")


if __name__ == '__main__':
    main()
