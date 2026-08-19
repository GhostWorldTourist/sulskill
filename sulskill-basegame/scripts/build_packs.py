"""Track E step 2: build the pack map from evidence in the install.

Three independent sources, kept separate so a consumer can tell them apart:

  identifiers  sims4/common.pyc in Data/Simulation/Gameplay/core.zip declares
               class Pack(enum.Int): BASE_GAME, SP01.., GP01.., EP01.., FP01.
               This gives the identifier NAMESPACE. It does NOT give the numeric
               values (they come from the native _common_types module) and its
               declaration order is NOT value order - the source declares
               reserved future slots in blocks (EP21 is followed by GP11..GP19,
               then SP31..SP99), so the nth name is not pack n.

  pack ids     the GROUP field of a resource key IS the Pack enum value. Proved
               from the game's own bytecode: gsi_handlers/sim_handlers.pyc,
               generate_available_buffs_list, compiles to

                   LOAD_GLOBAL str / LOAD_GLOBAL Pack
                   LOAD_FAST pack_specific_key / LOAD_ATTR group
                   CALL_FUNCTION 1 / CALL_FUNCTION 1 / STORE_FAST pack_id

               i.e. `pack_id = str(Pack(key.group))`. So a pack's numeric id can
               be read straight off its resources. COMBINED_TUNING (0x62E94D38)
               is the cleanest carrier: exactly one per package, one distinct
               (group, instance) per pack.

  titles       __Installer/DLC/<PACK>/__Installer/installerdata.xml carries
               <gameTitle locale="en_US">, the shipping product name.

Writes out/packs.json. Every entry records where its title and its id came
from, so "evidence-backed" is a property of the data, not of the prose.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import collections
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(gate.out_dir(), 'basegame')

GAME = os.environ.get('TS4_INSTALL') or gate.game_dir()
TITLE = re.compile(r'<gameTitle\s+locale="en_US">(.*?)</gameTitle>', re.S)
CONTENT_ID = re.compile(r'<contentID>(.*?)</contentID>', re.S)
# A manifest that just repeats the folder name is a placeholder, not a title.
PLACEHOLDER = re.compile(r'^(The|Die|Los|Les)\s+Sims.{0,3}\s*4\s+[A-Z]{2}\d+$')


def manifest(pack):
    p = os.path.join(GAME, '__Installer', 'DLC', pack, '__Installer',
                     'installerdata.xml')
    if not os.path.exists(p):
        return None
    return open(p, encoding='utf-8', errors='replace').read()


COMBINED_TUNING = 0x62E94D38
REC = struct.Struct('<IIQIHH')


def pack_ids():
    """{pack: (id, source)} read off resource group ids.

    Primary: COMBINED_TUNING, one per package, one key per pack.
    Fallback: a small group id seen in that pack's packages and in no other -
    enough for most kits that ship no tuning. Kits whose only groups are the
    shared 0x0 / 0x1 / 0x2 / 0x3 / 0x101 / 0x102 buckets cannot be resolved
    this way and are left null rather than guessed.
    """
    pj = os.path.join(OUT, 'packages.jsonl')
    if not os.path.exists(pj):
        return {}
    pk = {r['ordinal']: r['pack'] for r in
          (json.loads(l) for l in open(pj, encoding='utf-8'))}
    data = open(os.path.join(OUT, 'keys.bin'), 'rb').read()
    out = {}
    small = collections.defaultdict(set)     # pack -> {small group ids}
    for i in range(len(data) // REC.size):
        t, g, _inst, o, _c, _f = REC.unpack_from(data, i * REC.size)
        p = pk[o]
        if t == COMBINED_TUNING:
            out[p] = (g, 'combined-tuning-group')
        if g < 2048:
            small[p].add(g)
    owners = collections.defaultdict(set)
    for p, gs in small.items():
        for g in gs:
            owners[g].add(p)
    taken = {v for v, _s in out.values()}
    for p in small:
        if p in out:
            continue
        cand = sorted(g for g in small[p]
                      if len(owners[g]) == 1 and g not in taken)
        if len(cand) == 1:
            out[p] = (cand[0], 'exclusive-group-id')
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    delta = set()
    dd = os.path.join(GAME, 'Delta')
    if os.path.isdir(dd):
        delta = {n for n in os.listdir(dd)
                 if os.path.isdir(os.path.join(dd, n))}
    # A pack can exist as a Delta only (SP87 does): patch-delivered, with no
    # base install directory. Directory listing alone would miss it.
    dirs = sorted({n for n in list(os.listdir(GAME)) + list(delta)
                   if re.fullmatch(r'(EP|GP|SP|FP)\d\d', n)})
    ids = pack_ids()

    packs = {}
    for pack in dirs:
        x = manifest(pack)
        title, src, cid = None, 'none', None
        if x:
            m = TITLE.search(x)
            if m:
                t = m.group(1).strip().replace('\u2122', '')
                t = re.sub(r'\s+', ' ', t)
                if PLACEHOLDER.match(t):
                    src = 'manifest-placeholder'
                    title = None
                else:
                    src = 'manifest'
                    title = re.sub(r'^The Sims 4\s+', '', t)
            c = CONTENT_ID.search(x)
            if c:
                cid = c.group(1).strip()
        pid, psrc = ids.get(pack, (None, 'undetermined'))
        packs[pack] = {
            'id': pack,
            'kind': {'EP': 'Expansion Pack', 'GP': 'Game Pack',
                     'SP': 'Stuff Pack / Kit', 'FP': 'Free Pack'}[pack[:2]],
            'title': title,
            'title_source': src,
            'pack_id': pid,               # == the resource key GROUP field
            'pack_id_source': psrc,
            'contentID': cid,
            'installed_base_dir': os.path.isdir(os.path.join(GAME, pack)),
            'has_delta': pack in delta,
        }
    bid, bsrc = ids.get('BASE_GAME', (None, 'undetermined'))
    packs['BASE_GAME'] = {
        'id': 'BASE_GAME', 'kind': 'Base Game',
        'title': 'The Sims 4', 'title_source': 'directory-layout',
        'pack_id': bid, 'pack_id_source': bsrc,
        'contentID': None, 'installed_base_dir': True, 'has_delta': False,
    }
    json.dump({'title_source': 'installerdata.xml <gameTitle locale="en_US">',
               'pack_id_source': 'resource key GROUP field; '
                                 'Pack(key.group) per sim_handlers.pyc',
               'packs': packs},
              open(os.path.join(OUT, 'packs.json'), 'w', encoding='utf-8'),
              indent=1, sort_keys=True)
    named = sum(1 for v in packs.values() if v['title_source'] == 'manifest')
    ph = [k for k, v in packs.items()
          if v['title_source'] == 'manifest-placeholder']
    withid = sum(1 for v in packs.values() if v['pack_id'] is not None)
    sys.stderr.write('%d packs, %d titled from manifest (placeholders: %s), '
                     '%d with a numeric pack id\n'
                     % (len(packs), named, ', '.join(sorted(ph)) or 'none',
                        withid))


if __name__ == '__main__':
    main()
