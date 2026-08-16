#!/usr/bin/env python3
"""Read and WRITE Sims 4 SimData (DBPF type 0x545AC67A, magic 'DATA').

Why this exists
---------------
A custom Trait or Buff needs a matching SimData resource. Across 2328 local mod
packages, 781 of 784 Trait resources and 3115 of 3134 Buff resources ship one -
so it is effectively mandatory. The usual shortcut is to copy a SimData blob out
of another mod, but those blobs embed that author's identifying strings
("PECO:trait_isCindyRotique", "Andirz_RandomSim_Buff_Hidden_MakePansexual") and
redistributing them is not ours to do. This builds the bytes instead.

The column layout comes from EA's own packages via extract_ea_schema.py, not from
any modder's file: it is the binary interface the game's loader reads, so it must
match exactly, and it is the platform vendor's format rather than a peer's work.

Format facts that cost time to establish
----------------------------------------
* Every offset is RELATIVE TO THE FIELD THAT HOLDS IT. A pointer at absolute
  position P holding V points at P + V. Writing needs two passes: lay bytes out,
  then back-fill each pointer once its own address is known.
* Name hashes are **FNV-1 over the LOWERCASED name** - not FNV-1a, and not the
  original casing. Verified against real resources: fnv1(lower(
  "PECO:trait_isCindyRotique")) == 0xD736EE1D as stored. FNV-1a and as-is casing
  both produce the wrong value.
* A schema's `name_hash` is not a string hash at all - it is the tuning TYPE id
  (Trait 0xCB5FDDC7, Buff 0x6017E896).
* `schema_hash` identifies the column layout and therefore CHANGES BETWEEN PATCHES.
  EA's current Buff schema is 12 columns / row 96 bytes; older mods in the wild
  carry a 10 column / 80 byte version. Re-run extract_ea_schema.py after a patch.
* Table `data_type` is 0x0D for these single-object tables.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import json
import os
import struct

MAGIC = b'DATA'
VERSION = 0x101
DATA_TYPE_OBJECT = 0x0D

SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'reference', 'simdata_schema.json')

# tuning type ids, used as each schema's name_hash
TYPE_ID = {'Trait': 0xCB5FDDC7, 'Buff': 0x6017E896}


def fnv32(s):
    """FNV-1 (multiply THEN xor) over the lowercased name. See module docstring."""
    h = 0x811C9DC5
    for b in s.lower().encode('utf-8'):
        h = ((h * 0x01000193) & 0xFFFFFFFF) ^ b
    return h


def fnv64(s):
    """64-bit tuning instance id, high bit set to mark it mod-authored."""
    h = 0xCBF29CE484222325
    for b in s.encode('utf-8'):
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h | 0x8000000000000000


def load_schemas():
    with open(os.path.normpath(SCHEMA_FILE), encoding='utf-8') as f:
        return json.load(f)


# ------------------------------------------------------------------ reading
def _rel(data, pos):
    v = struct.unpack_from('<i', data, pos)[0]
    return None if v == -1 else pos + v


def _cstr(data, pos):
    if pos is None:
        return None
    return data[pos:data.index(b'\x00', pos)].decode('utf-8', 'replace')


def parse(data):
    if data[:4] != MAGIC:
        raise ValueError('not a SimData resource')
    version = struct.unpack_from('<I', data, 4)[0]
    table_pos, num_tables = _rel(data, 8), struct.unpack_from('<i', data, 12)[0]
    schema_pos, num_schemas = _rel(data, 16), struct.unpack_from('<i', data, 20)[0]

    schemas, p = [], schema_pos
    for _ in range(num_schemas):
        name = _cstr(data, _rel(data, p))
        name_hash, schema_hash, size = struct.unpack_from('<III', data, p + 4)
        col_pos = _rel(data, p + 16)
        ncols = struct.unpack_from('<i', data, p + 20)[0]
        cols, cp = [], col_pos
        for _ in range(ncols):
            cols.append({
                'name': _cstr(data, _rel(data, cp)),
                'hash': struct.unpack_from('<I', data, cp + 4)[0],
                'type': struct.unpack_from('<H', data, cp + 8)[0],
                'flags': struct.unpack_from('<H', data, cp + 10)[0],
                'offset': struct.unpack_from('<I', data, cp + 12)[0],
            })
            cp += 20
        schemas.append({'name': name, 'name_hash': name_hash,
                        'schema_hash': schema_hash, 'size': size, 'columns': cols})
        p += 24

    tables, p = [], table_pos
    for _ in range(num_tables):
        tables.append({
            'name': _cstr(data, _rel(data, p)),
            'name_hash': struct.unpack_from('<I', data, p + 4)[0],
            'data_type': struct.unpack_from('<I', data, p + 12)[0],
            'row_size': struct.unpack_from('<I', data, p + 16)[0],
            'row_count': struct.unpack_from('<I', data, p + 24)[0],
        })
        p += 28
    return {'version': version, 'schemas': schemas, 'tables': tables,
            'size': len(data)}


# ------------------------------------------------------------------ writing
class _Writer:
    def __init__(self):
        self.buf = bytearray()
        self.fixups = []
        self.marks = {}

    def mark(self, k):
        self.marks[k] = len(self.buf)

    def u32(self, v):
        self.buf += struct.pack('<I', v & 0xFFFFFFFF)

    def i32(self, v):
        self.buf += struct.pack('<i', v)

    def u16(self, v):
        self.buf += struct.pack('<H', v & 0xFFFF)

    def raw(self, b):
        self.buf += b

    def align(self, n=16):
        while len(self.buf) % n:
            self.buf += b'\x00'

    def ptr(self, k):
        self.fixups.append((len(self.buf), k))
        self.buf += b'\x00\x00\x00\x00'

    def null(self):
        self.buf += struct.pack('<i', -1)

    def finish(self):
        for pos, k in self.fixups:
            if k not in self.marks:
                raise KeyError(f'unresolved pointer {k!r}')
            struct.pack_into('<i', self.buf, pos, self.marks[k] - pos)
        return bytes(self.buf)


def build(class_name, instance_name, schemas=None):
    """Emit a SimData resource for one Trait or Buff tuning instance.

    The row payload is zero-filled: for a hidden trait/buff every field is either
    unset or carried by the XML tuning, and SimData's job here is to present a
    correctly shaped schema to the binary loader. This is the one part that
    warrants an in-game check, since a malformed SimData fails silently.
    """
    schemas = schemas or load_schemas()
    if class_name not in schemas:
        raise KeyError(f'no schema for {class_name!r}; run extract_ea_schema.py')
    sch = schemas[class_name]
    cols, row_size = sch['columns'], sch['row_size']

    w = _Writer()
    w.raw(MAGIC)
    w.u32(VERSION)
    w.ptr('tables'); w.i32(1)
    w.ptr('schema'); w.i32(1)

    w.mark('tables')
    w.ptr('s_inst')
    w.u32(fnv32(instance_name))
    w.ptr('schema')
    w.u32(DATA_TYPE_OBJECT)
    w.u32(row_size)
    w.ptr('rows')
    w.u32(1)

    w.align(16)
    w.mark('rows')
    w.raw(b'\x00' * row_size)

    w.align(16)
    w.mark('schema')
    w.ptr('s_class')
    w.u32(TYPE_ID[class_name])          # schema name_hash IS the tuning type id
    w.u32(sch['schema_hash'])
    w.u32(row_size)
    w.ptr('cols')
    w.i32(len(cols))

    w.mark('cols')
    for c in cols:
        w.ptr('s_c_' + c['name'])
        w.u32(fnv32(c['name']))
        w.u16(c['type'])
        w.u16(c['flags'])
        w.u32(c['offset'])
        w.null()

    w.mark('s_inst'); w.raw(instance_name.encode('utf-8') + b'\x00')
    w.mark('s_class'); w.raw(class_name.encode('utf-8') + b'\x00')
    for c in cols:
        w.mark('s_c_' + c['name'])
        w.raw(c['name'].encode('utf-8') + b'\x00')
    return w.finish()


def build_trait(instance_name):
    return build('Trait', instance_name)


def build_buff(instance_name):
    return build('Buff', instance_name)


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'rb') as f:
            print(json.dumps(parse(f.read()), indent=2)[:3000])
    else:
        for fn, nm in ((build_trait, 'demo:trait_demo'), (build_buff, 'demo:buff_demo')):
            blob = fn(nm)
            p = parse(blob)
            s, t = p['schemas'][0], p['tables'][0]
            ok = (t['name'] == nm and t['name_hash'] == fnv32(nm)
                  and s['name_hash'] == TYPE_ID[s['name']])
            print(f"{nm:<20} {len(blob):>5}b  schema={s['name']} "
                  f"cols={len(s['columns'])} row={t['row_size']}  "
                  f"roundtrip={'OK' if ok else 'FAIL'}")
