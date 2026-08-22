"""Extract the canonical Trait / Buff SimData schema from EA's own game packages.

Deriving the layout from EA is right on two counts. Functionally, the column
names, types and offsets are EA's - they describe how the game's binary loader
reads a Trait or Buff, so anything else misreads. Ethically, it means the schema
comes from the platform vendor whose format we must interoperate with, not from
a fellow modder's file.

Emits reference/simdata_schema.json for the generator to consume.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import glob
import json
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simdata                                                    # noqa: E402

def _game_dir():
    """Locate the install from the Maxis registry key, with an env fallback."""
    try:
        import winreg
        for key in (r"SOFTWARE\Maxis\The Sims 4",
                    r"SOFTWARE\WOW6432Node\Maxis\The Sims 4"):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                    return winreg.QueryValueEx(k, "Install Dir")[0]
            except OSError:
                continue
    except ImportError:
        pass
    return os.environ.get("SIMS4_GAME_DIR", "")


GAME = os.path.join(_game_dir(), "Data", "Client")
T_SIMDATA = 0x545AC67A
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'simdata_schema.json')
WANT = {'Trait', 'Buff'}


def resources(path):
    with open(path, 'rb') as f:
        head = f.read(96)
        if head[:4] != b'DBPF':
            return
        cnt = struct.unpack_from('<I', head, 36)[0]
        isz = struct.unpack_from('<I', head, 44)[0]
        ipos = struct.unpack_from('<Q', head, 64)[0] or struct.unpack_from('<I', head, 40)[0]
        if not cnt or not isz:
            return
        f.seek(ipos)
        ix = f.read(isz)
        flags = struct.unpack_from('<I', ix, 0)[0]
        p, const = 4, {}
        for bit, k in ((0, 't'), (1, 'g'), (2, 'h')):
            if flags & (1 << bit):
                const[k] = struct.unpack_from('<I', ix, p)[0]
                p += 4
        for _ in range(cnt):
            try:
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
                if t != T_SIMDATA:
                    continue
                f.seek(off)
                raw = f.read(fsz & 0x7FFFFFFF)
                yield zlib.decompress(raw) if comp == 0x5A42 else raw
            except (struct.error, zlib.error, ValueError):
                return


found = {}
files = sorted(glob.glob(os.path.join(GAME, '*.package')))
print(f"scanning {len(files)} EA packages for Trait/Buff SimData...")
for path in files:
    if WANT <= set(found):
        break
    n = 0
    for blob in resources(path):
        n += 1
        if n > 40000:
            break
        try:
            d = simdata.parse(blob)
        except Exception:
            continue
        for s in d['schemas']:
            if s['name'] in WANT and s['name'] not in found:
                cols = sorted(s['columns'], key=lambda c: c['offset'])
                found[s['name']] = {
                    'row_size': d['tables'][0]['row_size'],
                    'data_type': d['tables'][0]['data_type'],
                    'schema_hash': s['schema_hash'],
                    'schema_size': s['size'],
                    'columns': [{'name': c['name'], 'type': c['type'],
                                 'flags': c['flags'], 'offset': c['offset']}
                                for c in cols],
                }
                print(f"  {s['name']}: {len(cols)} columns, row_size "
                      f"{d['tables'][0]['row_size']}  <- {os.path.basename(path)}")
        if WANT <= set(found):
            break

if not found:
    sys.exit("no Trait/Buff SimData found in EA packages")
with open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
    json.dump(found, fh, indent=2)
print(f"\nwrote {OUT}")
for k, v in found.items():
    print(f"\n{k}  row_size={v['row_size']} schema_hash=0x{v['schema_hash']:08X}")
    for c in v['columns']:
        print(f"   +{c['offset']:>3}  {c['name']:<32} type=0x{c['type']:02X} flags={c['flags']}")
