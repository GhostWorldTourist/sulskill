#!/usr/bin/env python3
"""RefPack (QFS) decompression - the OTHER codec inside a Sims 4 package.

DBPF index entries carry a compression word: 0x5A42 is zlib, 0x0000 is stored,
and 0xFFFF is RefPack. Most mod resources are zlib, so a reader that only knows
zlib works fine on mods and then silently returns compressed garbage for EA's own
big resources. The master string table (STBL) is RefPack, which is exactly why a
byte-search for known text finds nothing in it.

Header:
    2 bytes signature, low byte 0xFB. Bit 0x0100 of the signature means a 3-byte
    COMPRESSED size precedes the uncompressed size. Bit 0x8000 means sizes are
    4 bytes rather than 3. Sizes are BIG-endian.

Control codes, each starting with a command byte:
    0x00-0x7F  2 bytes   literal 0-3, then back-reference
    0x80-0xBF  3 bytes   literal 0-3, longer reference
    0xC0-0xDF  4 bytes   literal 0-3, longest reference
    0xE0-0xFB  1 byte    literal run of 4-112, no reference
    0xFC-0xFF  1 byte    final literal run of 0-3, ends the stream

Back-references copy from the OUTPUT already produced, byte at a time, because
runs may overlap themselves.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import struct


def is_refpack(data):
    return len(data) > 2 and data[1] == 0xFB


def decompress(data):
    """Return the decompressed bytes of a RefPack blob."""
    if not is_refpack(data):
        raise ValueError('not RefPack (second byte is not 0xFB)')
    sig = struct.unpack_from('>H', data, 0)[0]
    p = 2
    width = 4 if sig & 0x8000 else 3

    def size_at(pos):
        if width == 3:
            return (data[pos] << 16) | (data[pos + 1] << 8) | data[pos + 2]
        return struct.unpack_from('>I', data, pos)[0]

    if sig & 0x0100:                      # compressed size present, and unused
        p += width
    out_len = size_at(p)
    p += width

    out = bytearray()
    n = len(data)
    while p < n:
        b0 = data[p]
        if b0 < 0x80:                                     # 2-byte form
            b1 = data[p + 1]
            p += 2
            literal = b0 & 0x03
            ref_len = ((b0 & 0x1C) >> 2) + 3
            ref_dist = ((b0 & 0x60) << 3) + b1 + 1
        elif b0 < 0xC0:                                   # 3-byte form
            b1, b2 = data[p + 1], data[p + 2]
            p += 3
            literal = (b1 >> 6) & 0x03
            ref_len = (b0 & 0x3F) + 4
            ref_dist = ((b1 & 0x3F) << 8) + b2 + 1
        elif b0 < 0xE0:                                   # 4-byte form
            b1, b2, b3 = data[p + 1], data[p + 2], data[p + 3]
            p += 4
            literal = b0 & 0x03
            ref_len = ((b0 & 0x0C) << 6) + b3 + 5
            ref_dist = ((b0 & 0x10) << 12) + (b1 << 8) + b2 + 1
        elif b0 < 0xFC:                                   # literal run
            p += 1
            literal = ((b0 & 0x1F) + 1) << 2
            ref_len = ref_dist = 0
        else:                                             # terminator
            p += 1
            literal = b0 & 0x03
            ref_len = ref_dist = 0

        if literal:
            out += data[p:p + literal]
            p += literal
        if ref_len:
            start = len(out) - ref_dist
            if start < 0:
                raise ValueError('RefPack back-reference before start of output')
            for i in range(ref_len):
                out.append(out[start + i])          # byte-at-a-time: runs overlap
        if b0 >= 0xFC:
            break

    if out_len and len(out) != out_len:
        # Not fatal - some resources pad - but worth knowing when it happens.
        pass
    return bytes(out)


def maybe_decompress(data, compression):
    """Dispatch on a DBPF index compression word."""
    import zlib
    if compression == 0x5A42:
        return zlib.decompress(data)
    if compression == 0xFFFF or is_refpack(data):
        return decompress(data)
    return data


if __name__ == '__main__':
    import sys
    with open(sys.argv[1], 'rb') as f:
        blob = f.read()
    out = decompress(blob)
    print(f"{len(blob):,} -> {len(out):,} bytes; starts {out[:16]!r}")
