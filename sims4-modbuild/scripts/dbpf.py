#!/usr/bin/env python3
"""Minimal DBPF (.package) reader/writer for Sims 4 mod resources.

Enough to author tuning mods: build an index, zlib-compress each resource, write
a valid v2.1 package. Deliberately small - it does not attempt to be a general
DBPF library.

Header fields that matter (offsets into the 96-byte header):
    0x00  'DBPF'
    0x04  major version (2)
    0x08  minor version (1)
    0x20  index record entry count       <- some tools read this
    0x24  index entry count
    0x2C  index size in bytes
    0x3C  index version (3)
    0x40  index offset (u64)

Index entries are preceded by a flags word saying which of type/group/instance-hi
are CONSTANT across all entries (and therefore stored once, not per entry). This
writer emits flags = 0, i.e. every field stored per entry, which every reader
handles.
"""
import struct
import zlib

COMPRESS_ZLIB = 0x5A42

# resource types used when authoring tuning
T_TRAIT = 0xCB5FDDC7
T_BUFF = 0x6017E896
T_SIMDATA = 0x545AC67A
T_SNIPPET = 0x7DF2169C
T_LOOT = 0x0C772E27
T_INTERACTION = 0xE882D22F
T_STBL = 0x220557DA

# SimData resources are grouped by the tuning type they describe
SIMDATA_GROUP = {T_TRAIT: 0x005FDD0C, T_BUFF: 0x0017E8F6}


def read(path):
    """Yield (type, group, instance, bytes) for every resource in a package."""
    with open(path, 'rb') as f:
        head = f.read(96)
        if head[:4] != b'DBPF':
            raise ValueError(f'not a DBPF: {path}')
        count = struct.unpack_from('<I', head, 0x24)[0]
        isize = struct.unpack_from('<I', head, 0x2C)[0]
        ioff = struct.unpack_from('<Q', head, 0x40)[0] or struct.unpack_from('<I', head, 0x28)[0]
        f.seek(ioff)
        ix = f.read(isize)
        flags = struct.unpack_from('<I', ix, 0)[0]
        p, const = 4, {}
        for bit, key in ((0, 't'), (1, 'g'), (2, 'h')):
            if flags & (1 << bit):
                const[key] = struct.unpack_from('<I', ix, p)[0]
                p += 4
        for _ in range(count):
            t = const.get('t')
            if t is None:
                t = struct.unpack_from('<I', ix, p)[0]; p += 4
            g = const.get('g')
            if g is None:
                g = struct.unpack_from('<I', ix, p)[0]; p += 4
            hi = const.get('h')
            if hi is None:
                hi = struct.unpack_from('<I', ix, p)[0]; p += 4
            lo = struct.unpack_from('<I', ix, p)[0]; p += 4
            off = struct.unpack_from('<I', ix, p)[0]; p += 4
            fsz = struct.unpack_from('<I', ix, p)[0]; p += 4
            p += 4                                        # memory size
            comp = 0
            if fsz & 0x80000000:
                comp = struct.unpack_from('<H', ix, p)[0]; p += 4
            f.seek(off)
            raw = f.read(fsz & 0x7FFFFFFF)
            yield t, g, (hi << 32) | lo, (
                zlib.decompress(raw) if comp == COMPRESS_ZLIB else raw)


def write(path, resources):
    """resources: iterable of (type, group, instance, bytes)."""
    body, index, offset = bytearray(), [], 96
    for t, g, i, data in resources:
        blob = zlib.compress(data, 9)
        body += blob
        index.append((t, g, i, offset, len(blob), len(data)))
        offset += len(blob)

    ix = bytearray(struct.pack('<I', 0))                  # flags: nothing constant
    for t, g, i, off, csize, usize in index:
        ix += struct.pack('<IIIIIIIHH', t, g, i >> 32, i & 0xFFFFFFFF, off,
                          csize | 0x80000000, usize, COMPRESS_ZLIB, 1)

    head = bytearray(96)
    head[0:4] = b'DBPF'
    struct.pack_into('<I', head, 0x04, 2)                 # major
    struct.pack_into('<I', head, 0x08, 1)                 # minor
    struct.pack_into('<I', head, 0x20, len(index))
    struct.pack_into('<I', head, 0x24, len(index))
    struct.pack_into('<I', head, 0x2C, len(ix))
    struct.pack_into('<I', head, 0x3C, 3)                 # index version
    struct.pack_into('<Q', head, 0x40, 96 + len(body))

    with open(path, 'wb') as f:
        f.write(head)
        f.write(body)
        f.write(ix)
    return len(index), 96 + len(body) + len(ix)


def audit(path, forbidden):
    """Return any forbidden byte-strings found in a package's decompressed
    resources. Used as a release gate so no third-party identifier ever ships."""
    hits = {}
    for t, g, i, blob in read(path):
        for needle in forbidden:
            n = needle.encode() if isinstance(needle, str) else needle
            if n in blob:
                hits.setdefault(needle, []).append(f'0x{t:08X}:0x{i:016X}')
    return hits
