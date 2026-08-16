import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import struct, sys, os
import os as _o, sys as _s
_s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)),
                               '..', '..', 'sulskill-modbuild', 'scripts'))
import refpack
from idx import index

def get(path, off, fsz, comp):
    with open(path,'rb') as f:
        f.seek(off); raw = f.read(fsz)
    return refpack.maybe_decompress(raw, comp)

def load_stbl(blob):
    assert blob[:4] == b'STBL', blob[:8]
    ver = struct.unpack_from('<H', blob, 4)[0]
    compressed = blob[6]
    n = struct.unpack_from('<Q', blob, 7)[0]
    # 2 bytes reserved at 15, u32 string length at 17
    p = 21
    out = {}
    for _ in range(n):
        k = struct.unpack_from('<I', blob, p)[0]; p += 4
        flags = blob[p]; p += 1
        ln = struct.unpack_from('<H', blob, p)[0]; p += 2
        s = blob[p:p+ln].decode('utf-8','replace'); p += ln
        out[k] = s
    return ver, n, out
