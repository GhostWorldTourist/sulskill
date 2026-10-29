"""What Vortex knows about a Sims 4 library: which archive deployed each file, and its name.

Players search Vortex by mod, not by package, so a report that lists packages
makes them do the join by hand. Two sources answer it:

- `vortex.deployment.json`, which Vortex writes beside the files it deploys,
  maps every deployed file to the staging folder (the mod id) it came from.
- Vortex's LevelDB state holds each mod's display name. The live database is
  locked while Vortex runs, so this reads a COPY of its `.ldb` tables, with a
  small pure-Python LevelDB/Snappy reader. Changes still sitting in Vortex's
  write-ahead `.log` are not seen until Vortex compacts them, so a mod renamed
  minutes ago can show its old name.

Neither exists on a manual install. Every function here returns empty then,
and callers fall back to the folder a mod sits in (see gate.mod_units).

    py scripts/vortex_state.py        # -> <out_dir>/vortex_names.json
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import glob
import json
import os
import shutil
import struct
import sys
import tempfile

GAME = 'thesims4'


def mods_dir():
    """The live Mods folder (first of gate.mod_roots), or '' when there is none."""
    roots = gate.mod_roots()
    return roots[0] if roots and os.path.basename(roots[0]).lower() == 'mods' else ''


def deployment(mods=None):
    """{path relative to Mods, lower-case, '/'-separated: Vortex mod id} for every deployed file.

    Vortex writes one manifest per deployment target, usually in Mods/Vortex Mods,
    so look at Mods itself and one level down.
    """
    mods = mods or mods_dir()
    out = {}
    if not mods:
        return out
    for man in [os.path.join(mods, 'vortex.deployment.json')] + glob.glob(
            os.path.join(glob.escape(mods), '*', 'vortex.deployment.json')):
        try:
            files = json.load(open(man, encoding='utf-8'))['files']
        except (OSError, ValueError, KeyError):
            continue
        base = os.path.relpath(os.path.dirname(man), mods)
        base = '' if base == '.' else base.replace(os.sep, '/') + '/'
        for f in files:
            out[(base + f['relPath'].replace('\\', '/')).lower()] = f['source']
    return out


# --- LevelDB, read-only, from copied tables ---------------------------------------

def _varint(b, p):
    r = s = 0
    while True:
        c = b[p]
        p += 1
        r |= (c & 0x7f) << s
        s += 7
        if c < 0x80:
            return r, p


def _unsnappy(b):
    _, p = _varint(b, 0)
    out = bytearray()
    while p < len(b):
        tag = b[p]
        p += 1
        t = tag & 3
        if t == 0:
            ln = tag >> 2
            if ln >= 60:
                nb = ln - 59
                ln = int.from_bytes(b[p:p + nb], 'little')
                p += nb
            ln += 1
            out += b[p:p + ln]
            p += ln
            continue
        if t == 1:
            ln = ((tag >> 2) & 7) + 4
            off = ((tag >> 5) << 8) | b[p]
            p += 1
        elif t == 2:
            ln = (tag >> 2) + 1
            off = int.from_bytes(b[p:p + 2], 'little')
            p += 2
        else:
            ln = (tag >> 2) + 1
            off = int.from_bytes(b[p:p + 4], 'little')
            p += 4
        for _ in range(ln):
            out.append(out[-off])
    return bytes(out)


def _block(f, off, size):
    f.seek(off)
    raw = f.read(size + 5)
    return _unsnappy(raw[:size]) if raw[size] == 1 else raw[:size]


def _entries(d):
    nr = struct.unpack_from('<I', d, len(d) - 4)[0]
    end = len(d) - 4 - 4 * nr
    p, key = 0, b''
    while p < end:
        sh, p = _varint(d, p)
        ns, p = _varint(d, p)
        vl, p = _varint(d, p)
        key = key[:sh] + d[p:p + ns]
        p += ns
        v = d[p:p + vl]
        p += vl
        yield key, v


def _table(path):
    with open(path, 'rb') as f:
        f.seek(-48, 2)
        foot = f.read(48)
        _, p = _varint(foot, 0)
        _, p = _varint(foot, p)
        io, p = _varint(foot, p)
        isz, p = _varint(foot, p)
        for _, h in _entries(_block(f, io, isz)):
            o, q = _varint(h, 0)
            s, q = _varint(h, q)
            for k, v in _entries(_block(f, o, s)):
                seq = struct.unpack('<Q', k[-8:])[0]
                yield k[:-8], seq >> 8, seq & 0xff, v


def _load(d):
    best = {}
    for path in glob.glob(os.path.join(glob.escape(d), '*.ldb')):
        try:
            for k, s, t, v in _table(path):
                if k not in best or best[k][0] < s:
                    best[k] = (s, t, v)
        except (OSError, IndexError, struct.error):
            continue                      # a table mid-compaction: skip it, never guess
    return {k: v for k, (s, t, v) in best.items() if t == 1}


def state_dir():
    return os.environ.get('VORTEX_STATE') or os.path.join(
        os.environ.get('APPDATA', os.path.expanduser('~')), 'Vortex', 'state.v2')


def mod_names(state=None, game=GAME):
    """{Vortex mod id: {customFileName, logicalFileName, name, fileName}} for one game."""
    state = state or state_dir()
    if not os.path.isdir(state):
        return {}
    tmp = tempfile.mkdtemp(prefix='sulskill-vortex-')
    try:
        for f in glob.glob(os.path.join(glob.escape(state), '*.ldb')):
            try:
                shutil.copy2(f, tmp)
            except OSError:
                continue
        kv = _load(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    names = {}
    want = game.encode()
    for k, v in kv.items():
        parts = k.split(b'###')
        if (len(parts) == 6 and parts[:3] == [b'persistent', b'mods', want] and parts[4] == b'attributes'
                and parts[5] in (b'customFileName', b'logicalFileName', b'name', b'fileName')):
            try:
                names.setdefault(parts[3].decode('utf-8', 'replace'), {})[parts[5].decode()] = json.loads(v)
            except ValueError:
                pass
    return names


def display(mod_id, names):
    a = names.get(mod_id, {})
    return a.get('customFileName') or a.get('logicalFileName') or a.get('name') or mod_id


def main():
    names = mod_names()
    out = os.path.join(gate.out_dir(), 'vortex_names.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(names, f, ensure_ascii=False, indent=1)
    print('%d Vortex mods named; %d deployed files mapped; wrote %s' % (len(names), len(deployment()), out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
