import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import struct, os, sys, json
import os as _o, sys as _s
_s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                               '..', '..', 'sulskill-modbuild', 'scripts'))

def index(path):
    """Yield (type, group, instance, offset, filesize, memsize, comp). Index only."""
    with open(path,'rb') as f:
        head = f.read(96)
        if head[:4] != b'DBPF': return
        count = struct.unpack_from('<I', head, 0x24)[0]
        isize = struct.unpack_from('<I', head, 0x2C)[0]
        ioff  = struct.unpack_from('<Q', head, 0x40)[0] or struct.unpack_from('<I', head, 0x28)[0]
        f.seek(ioff); ix = f.read(isize)
    flags = struct.unpack_from('<I', ix, 0)[0]
    p, const = 4, {}
    for bit,k in ((0,'t'),(1,'g'),(2,'h')):
        if flags & (1<<bit):
            const[k] = struct.unpack_from('<I', ix, p)[0]; p += 4
    out = []
    for _ in range(count):
        t = const.get('t')
        if t is None: t = struct.unpack_from('<I', ix, p)[0]; p += 4
        g = const.get('g')
        if g is None: g = struct.unpack_from('<I', ix, p)[0]; p += 4
        hi = const.get('h')
        if hi is None: hi = struct.unpack_from('<I', ix, p)[0]; p += 4
        lo, off, fsz, msz = struct.unpack_from('<IIII', ix, p); p += 16
        comp = 0
        if fsz & 0x80000000:
            comp = struct.unpack_from('<H', ix, p)[0]; p += 4
        out.append((t, g, (hi<<32)|lo, off, fsz & 0x7FFFFFFF, msz, comp))
    return out

def fetch(path, off, fsz, msz, comp):
    import zlib
    import refpack
    with open(path,'rb') as f:
        f.seek(off); raw = f.read(fsz)
    if comp == 0x5A42: return zlib.decompress(raw)
    if comp == 0xFFFF or comp == 0: return raw
    return refpack.maybe_decompress(raw)
