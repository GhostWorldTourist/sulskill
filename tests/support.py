"""Builders the tests need: real DBPF packages, real RefPack streams.

The point of these is that the tests exercise the actual decoders against
actual encoded bytes. A test that hands review.py a dict of names would pass
happily while every real package on disk read as empty - which is the bug
that was actually shipped.

NOTHING IN tests/ MAY CONTAIN A REAL BLOCKLIST TERM. The blocklist ships as
digests because this repository is public and a readable list is a search
index. A test file naming the terms would undo that completely. Where a test
needs terms, it invents ones with the same SHAPE (letters mixed with digits,
handle that is also an English word) and compiles them itself.
"""
import contextlib
import os
import struct
import sys
import tempfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED = os.path.join(ROOT, '_shared')
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

import gate                                                        # noqa: E402

STBL = 0x220557DA
CASP = 0x034AEECB
NAMEMAP = 0x0166038C


def u24(v):
    return bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])


def refpack(payload):
    """Encode as RefPack using literal runs only.

    A literal-only stream is valid RefPack and exercises the same header
    parsing and opcode dispatch as a compressed one, without needing a
    match-finder in the test support. Back-references are covered separately
    by a hand-built stream in test_review.
    """
    body = bytearray()
    i, n = 0, len(payload)
    while n - i >= 4:
        chunk = min(((n - i) // 4) * 4, 112)      # 0xE0..0xFB carry 4..112
        body.append(0xE0 + (chunk // 4) - 1)
        body += payload[i:i + chunk]
        i += chunk
    rest = n - i                                   # 0xFC..0xFF carry 0..3
    body.append(0xFC + rest)
    body += payload[i:]
    # 0x10FB, the signature EA actually writes: low byte 0xFB marks RefPack,
    # bit 0x8000 clear means 3-byte sizes, and bit 0x0100 is CLEAR, so no
    # compressed-size field follows - only the uncompressed size. Emitting one
    # anyway shifts the opcode stream by three bytes and decodes to garbage.
    return b'\x10\xfb' + u24(len(payload)) + bytes(body)


def dbpf(entries):
    """Build a package. entries: (type_id, instance, payload, codec).

    codec 0 stored, 0x5A42 zlib, 0xFFFF RefPack. Any other value is written
    into the index verbatim without encoding the payload, which is how a test
    produces an entry the reader must refuse to decode.
    """
    header = bytearray(96)
    header[0:4] = b'DBPF'
    data = bytearray()
    records = []
    for type_id, inst, payload, codec in entries:
        if codec == 0x5A42:
            blob = zlib.compress(payload)
        elif codec == 0xFFFF:
            blob = refpack(payload)
        else:
            blob = payload
        records.append((type_id, inst, 96 + len(data), len(blob),
                        len(payload), codec))
        data += blob

    index = bytearray(struct.pack('<I', 0))        # flags: nothing constant
    for type_id, inst, off, size, mem, codec in records:
        index += struct.pack(
            '<IIIIIII', type_id, 0, (inst >> 32) & 0xFFFFFFFF,
            inst & 0xFFFFFFFF, off, size | (0x80000000 if codec else 0), mem)
        if codec:
            index += struct.pack('<HH', codec, 1)

    struct.pack_into('<I', header, 0x24, len(records))
    struct.pack_into('<I', header, 0x2C, len(index))
    struct.pack_into('<Q', header, 0x40, 96 + len(data))
    return bytes(header) + bytes(data) + bytes(index)


def stbl(*strings):
    """A blob shaped like a string table: the reader scans it for ASCII runs."""
    return b'\x00\x01'.join(s.encode('ascii') for s in strings)


def casp(*names):
    """A blob shaped like a CAS part: names are UTF-16LE, which is the whole
    reason a byte-oriented reader saw nothing in CAS packages."""
    return b'\x00\x00'.join(n.encode('utf-16-le') for n in names)


def write_pkg(tmpdir, name, entries):
    path = os.path.join(tmpdir, name)
    with open(path, 'wb') as f:
        f.write(dbpf(entries))
    return path


@contextlib.contextmanager
def blocklist(terms):
    """Point the gate at a blocklist compiled from `terms` for the duration.

    terms are '<mode> <tier> <term>' lines, compiled through the real
    blocklist_add so the test covers the compile->match round trip rather
    than a hand-written digest that could agree with a broken compiler.
    """
    import blocklist_add
    lines, bad = blocklist_add.compile_terms(terms)
    if bad:
        raise AssertionError(f'test terms rejected by compiler: {bad}')
    fd, path = tempfile.mkstemp(suffix='.txt', text=True)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write('# test blocklist\n' + '\n'.join(lines) + '\n')
    old = gate.BLOCKLIST
    gate.BLOCKLIST = path
    gate._state.clear()
    try:
        yield
    finally:
        gate.BLOCKLIST = old
        gate._state.clear()
        os.unlink(path)


@contextlib.contextmanager
def environment(**kw):
    """Set env vars for the duration; None deletes."""
    old = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
