"""Index-only DBPF scanner.

dbpf.read() decompresses every resource as it walks. For a 79 GB install that
is unusable when the question is only "what kinds of resource live where".
This reads the header and index and stops - no entry data is touched - so a
1.8 GB package costs the same as a 2 MB one.

Yields (type, group, instance, offset, filesize, compression) so a caller can
filter on type and then fetch just the entries it wants.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import os
import struct
import sys
import zlib

COMPRESS_ZLIB = 0x5A42
COMPRESS_NONE = 0x0000
COMPRESS_REFPACK = 0xFFFF

# RefPack is the other codec in a Sims 4 package, and it matters here because it
# fails SILENTLY: a zlib-only reader hands back still-compressed bytes with no
# exception, and the caller sees noise where a header should be. EA's large
# resources - the master string table among them - are RefPack, so a reader that
# works perfectly on mods finds nothing in the base game and gives no reason.
#
# The decoder is imported from the sulskill checkout rather than copied, so the
# refusal gate it loads still runs. Set SULSKILL_REPO if the checkout moves.
_REPO = os.environ.get('SULSKILL_REPO') or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_REPO, 'sulskill-modbuild', 'scripts')


def _refpack():
    if _SCRIPTS not in sys.path:
        sys.path.insert(0, _SCRIPTS)
    import refpack
    return refpack


# NOTE: this table was written from a wiki and several ids in it are WRONG.
# Use restypes.type_names(), which extracts the table from the game's own
# bytecode. Kept only so older callers do not break.
TUNING_TYPES = {
    0x0333406C: 'XML_TUNING',      # generic tuning XML
    0x545AC67A: 'SIMDATA',         # binary tuning companion
    0x220557DA: 'STBL',            # string table
    0x02D5DF13: 'ASM',             # animation state machine
    0x6017E896: 'BUFF',
    0xCB5FDDC7: 'TRAIT',
    0x7DF2169C: 'SNIPPET',
    0x0C772E27: 'LOOT',
    0xE882D22F: 'INTERACTION',
    0x0C1FE246: 'MOOD',
    0x2D6BA5B3: 'ASPIRATION',
    0xE1477E5D: 'OBJECTIVE',
    0x5B02819E: 'STATISTIC',
    0xB61DE6B4: 'CAREER',
    0x9BD3C5C4: 'RECIPE',
    0xEBCBB16C: 'SITUATION',
    0xE1DFA3B9: 'CLIENT_OBJECT',
}


def index(path):
    """Yield (t, g, inst, off, fsz, comp) for every entry. No data read."""
    with open(path, 'rb') as f:
        head = f.read(96)
        if head[:4] != b'DBPF':
            return
        count = struct.unpack_from('<I', head, 0x24)[0]
        isize = struct.unpack_from('<I', head, 0x2C)[0]
        ioff = (struct.unpack_from('<Q', head, 0x40)[0]
                or struct.unpack_from('<I', head, 0x28)[0])
        if not count or not ioff:
            return
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
        p += 4                                     # memory size
        comp = 0
        if fsz & 0x80000000:
            comp = struct.unpack_from('<H', ix, p)[0]; p += 4
        yield t, g, (hi << 32) | lo, off, fsz & 0x7FFFFFFF, comp


def fetch(path, entries):
    """Read and decompress only the entries handed in.

    entries: iterable of (off, fsz, comp). Sorted by offset so the read is
    forward-only across a multi-gigabyte file rather than seeking at random.

    Raises on a codec it cannot decode rather than returning the compressed
    bytes. That is deliberate: the failure this guards against produces
    plausible-looking garbage, not an obvious error, and a caller that gets a
    exception can fix it while a caller that gets noise usually cannot tell.
    """
    with open(path, 'rb') as f:
        for off, fsz, comp in sorted(entries):
            f.seek(off)
            raw = f.read(fsz)
            yield decode(raw, comp)


def decode(raw, comp):
    """Decompress one resource payload given its DBPF compression word."""
    if comp == COMPRESS_ZLIB:
        return zlib.decompress(raw)
    rp = _refpack()
    if comp == COMPRESS_REFPACK or rp.is_refpack(raw):
        return rp.decompress(raw)
    if comp == COMPRESS_NONE:
        return raw
    raise ValueError(
        'unknown DBPF compression 0x%04X (%d bytes); refusing to return it '
        'undecoded - see notes/type-table-exceptions.md' % (comp, len(raw)))
