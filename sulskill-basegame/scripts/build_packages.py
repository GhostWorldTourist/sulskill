"""Track E step 1: inventory every .package in the install.

out/packages.jsonl - one JSON object per package:
    ordinal, path, dir, name, pack, layer, surface, role, size, entries,
    tombstones, compression histogram, resource-type histogram, and the
    priority the governing Resource cfg mounts it at.

out/keys.bin - a compact side-table, one 24-byte record per index entry:
    <IIQIHH  (type, group, instance, package_ordinal, compression, flags)
so override pressure can be computed without rescanning 79 GB.

Index-only: no entry payload is read.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import json
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'lib'))

import dbpf_index   # noqa: E402
import resourcecfg  # noqa: E402
import restypes     # noqa: E402

GAME = os.environ.get('TS4_INSTALL') or gate.game_dir()
OUT = os.path.join(gate.out_dir(), 'basegame')

TOMBSTONE = 0xFFE0
REC = struct.Struct('<IIQIHH')

# See notes/type-table-exceptions.md. restypes is the table Python uses, not
# the engine's: it mislabels SimData and omits types the engine owns alone.
# Corrections applied on top, never inside the extractor.
OVERRIDE = {
    0x545AC67A: 'SIMDATA',      # restypes says PLAYLIST; payload magic 'DATA'
    0x220557DA: 'STBL',         # engine-side, absent from the Python enum
}

ROLES = (
    ('clientfullbuild', 'ClientFullBuild'),
    ('clientdeltabuild', 'ClientDeltaBuild'),
    ('simulationfullbuild', 'SimulationFullBuild'),
    ('simulationdeltabuild', 'SimulationDeltaBuild'),
    ('simulationpreload', 'SimulationPreload'),
    ('clipheader', 'ClipHeader'),
    ('strings_', 'Strings'),
    ('thumbnails', 'thumbnails'),
    ('magalog', 'magalog'),
    ('ui', 'UI'),
    ('consoletray', 'ConsoleTray'),
)


def classify(rel):
    """(pack, layer, role) from an install-relative path.

    Surface is NOT derived from the filename - it comes from which cfg mounts
    the file, because the two runtimes mount overlapping sets (magalog.package
    is mounted by both).
    """
    parts = rel.split('/')
    low = parts[-1].lower()
    if parts[0] == 'Data':
        pack, layer = 'BASE_GAME', 'base'
    elif parts[0] == 'Delta':
        pack, layer = parts[1], 'delta'
    else:
        pack, layer = parts[0], 'base'
    role = None
    for pre, label in ROLES:
        if low.startswith(pre):
            role = label
            break
    return pack, layer, role


def cfg_manager(directory, cfg_name):
    """'Client' or 'Simulation' - which runtime this cfg configures.

    Pack directories name the two explicitly. Data/ splits them by directory
    instead, and the engine's own copies (Game/Bin/res/ResourceClient.dat and
    ResourceSimulation.dat) carry the same two bodies, each headed 'CFG file
    used by the client runtime' / '...the server runtime'.
    """
    n = cfg_name.lower()
    if n.startswith('resourceclient'):
        return 'Client'
    if n.startswith('resourcesimulation'):
        return 'Simulation'
    tail = os.path.basename(directory).lower()
    if tail == 'client':
        return 'Client'
    if tail == 'simulation':
        return 'Simulation'
    return None


def cfg_priorities(directory):
    """{filename: {'Client': prio, 'Simulation': prio}} for one directory.

    Resource_LE.cfg is the low-end variant: a strict subset mounted when the
    machine cannot take the full build. It is not the shipping path, so it is
    excluded rather than allowed to lower anything.
    """
    out = {}
    try:
        listing = os.listdir(directory)
    except OSError:
        return out
    cfgs = [n for n in listing
            if n.lower().endswith('.cfg') and n.lower().startswith('resource')
            and '_le' not in n.lower()]
    files = [n for n in listing if os.path.isfile(os.path.join(directory, n))]
    for c in cfgs:
        mgr = cfg_manager(directory, c)
        if mgr is None:
            continue
        for prio, n, _sel in resourcecfg.mounts(os.path.join(directory, c),
                                                files):
            slot = out.setdefault(n, {})
            if mgr not in slot or prio > slot[mgr]:
                slot[mgr] = prio
    return out


def walk_packages(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            if fn.lower().endswith('.package'):
                yield os.path.join(dirpath, fn)


def main():
    os.makedirs(OUT, exist_ok=True)
    names = restypes.type_names()
    names.update(OVERRIDE)
    t0 = time.time()
    pkgs = list(walk_packages(GAME))
    prio_cache = {}
    # Both under `with`, because build_packs.py reads keys.bin back as a flat
    # record array and trusts its length. An exception escaping the loop below
    # used to leave whatever was still buffered unwritten, and a short keys.bin
    # does not look short - it looks like a library with fewer resources in it.
    with open(os.path.join(OUT, 'packages.jsonl'), 'w',
              encoding='utf-8') as jsonl, \
            open(os.path.join(OUT, 'keys.bin'), 'wb') as keys:
        total, tombs = _index_all(pkgs, prio_cache, names, jsonl, keys)
    sys.stderr.write('%d packages, %d entries, %d tombstones, %.1fs\n'
                     % (len(pkgs), total, tombs, time.time() - t0))


def _index_all(pkgs, prio_cache, names, jsonl, keys):
    """Index every package into the two open output files. -> (entries, tombs)"""
    total = tombs = 0
    for ordinal, path in enumerate(pkgs):
        rel = os.path.relpath(path, GAME).replace('\\', '/')
        d = os.path.dirname(path)
        if d not in prio_cache:
            prio_cache[d] = cfg_priorities(d)
        mounts = prio_cache[d].get(os.path.basename(path), {})
        pack, layer, role = classify(rel)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        hist, comps = {}, {}
        n = tomb = 0
        buf = bytearray()
        try:
            for t, g, inst, off, fsz, comp in dbpf_index.index(path):
                hist[t] = hist.get(t, 0) + 1
                comps[comp] = comps.get(comp, 0) + 1
                if comp == TOMBSTONE:
                    tomb += 1
                n += 1
                buf += REC.pack(t, g, inst, ordinal, comp,
                                1 if (off == 0 and fsz == 0) else 0)
        except Exception as e:                                  # noqa: BLE001
            jsonl.write(json.dumps({'ordinal': ordinal, 'path': rel,
                                    'size': size, 'error': repr(e)}) + '\n')
            continue
        keys.write(buf)
        total += n
        tombs += tomb
        jsonl.write(json.dumps({
            'ordinal': ordinal,
            'path': rel,
            'dir': os.path.dirname(rel),
            'name': os.path.basename(rel),
            'pack': pack,
            'layer': layer,
            'role': role,
            'mounts': mounts,          # {'Client': prio, 'Simulation': prio}
            'surfaces': sorted(mounts),
            'size': size,
            'entries': n,
            'tombstones': tomb,
            'compression': {('0x%04X' % c): v for c, v in
                            sorted(comps.items())},
            'types': {('0x%08X' % t): c for t, c in
                      sorted(hist.items(), key=lambda kv: -kv[1])},
            'type_names': {('0x%08X' % t): names.get(t)
                           for t in hist if names.get(t)},
        }) + '\n')
    return total, tombs


if __name__ == '__main__':
    main()
