"""Minimal Python 3.7 marshal reader - enough to recover function signatures
from The Sims 4's shipped .pyc files while running on a modern interpreter.

Only implements the type codes CPython 3.7 actually emits for compiled modules.
"""
import struct

FLAG_REF = 0x80


class Code:
    __slots__ = ('argcount', 'kwonlyargcount', 'nlocals', 'stacksize', 'flags',
                 'code', 'consts', 'names', 'varnames', 'freevars', 'cellvars',
                 'filename', 'name', 'firstlineno', 'lnotab')

    def __repr__(self):
        return f"<Code {self.name} args={self.argcount} varnames={self.varnames[:8]}>"

    def signature(self):
        """Reconstruct the parameter list as source would declare it."""
        pos = list(self.varnames[:self.argcount])
        kwonly = list(self.varnames[self.argcount:self.argcount + self.kwonlyargcount])
        out = list(pos)
        if self.flags & 0x04:      # CO_VARARGS
            idx = self.argcount + self.kwonlyargcount
            out.append('*' + self.varnames[idx])
        elif kwonly:
            out.append('*')
        out += kwonly
        if self.flags & 0x08:      # CO_VARKEYWORDS
            idx = self.argcount + self.kwonlyargcount + bool(self.flags & 0x04)
            out.append('**' + self.varnames[idx])
        return f"{self.name}({', '.join(out)})"


class Reader:
    def __init__(self, data):
        self.d = data
        self.i = 0
        self.refs = []

    def byte(self):
        b = self.d[self.i]; self.i += 1; return b

    def n(self, k):
        v = self.d[self.i:self.i + k]; self.i += k; return v

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.i)[0]; self.i += 4; return v

    def read(self):
        c = self.byte()
        ref = bool(c & FLAG_REF)
        t = chr(c & ~FLAG_REF)
        idx = None
        if ref:
            idx = len(self.refs); self.refs.append(None)

        def keep(v):
            if idx is not None:
                self.refs[idx] = v
            return v

        if t == 'N': return None
        if t == 'T': return keep(True)
        if t == 'F': return keep(False)
        if t == 'n': return None
        if t == '.': return Ellipsis
        if t == 'i': return keep(self.i32())
        if t == 'g': v = struct.unpack_from('<d', self.d, self.i)[0]; self.i += 8; return keep(v)
        if t == 'l':                                   # arbitrary-precision int
            # marshal stores |size| 15-bit digits, little-endian; sign from size
            size = self.i32()
            v = 0
            for k in range(abs(size)):
                digit = struct.unpack_from('<H', self.d, self.i)[0]
                self.i += 2
                v |= digit << (15 * k)
            return keep(-v if size < 0 else v)
        if t in 's':                                   # bytes
            ln = self.i32(); return keep(self.n(ln))
        if t in ('u', 't', 'a', 'A'):                  # unicode / interned / ascii
            ln = self.i32(); return keep(self.n(ln).decode('utf-8', 'replace'))
        if t in ('z', 'Z'):                            # short ascii (+interned)
            ln = self.byte(); return keep(self.n(ln).decode('utf-8', 'replace'))
        if t in ('(', ')'):                            # tuple / small tuple
            ln = self.i32() if t == '(' else self.byte()
            v = []
            if idx is not None: self.refs[idx] = v
            for _ in range(ln): v.append(self.read())
            v = tuple(v)
            if idx is not None: self.refs[idx] = v
            return v
        if t == '[':
            ln = self.i32(); v = []
            if idx is not None: self.refs[idx] = v
            for _ in range(ln): v.append(self.read())
            return v
        if t in ('<', '>'):                            # set / frozenset
            ln = self.i32(); v = [self.read() for _ in range(ln)]
            return keep(frozenset(x for x in v if isinstance(x, (int, str, bytes))))
        if t == '{':
            v = {}
            if idx is not None: self.refs[idx] = v
            while True:
                k = self.read()
                if k is None and self.d[self.i - 1] == ord('0'): break
                val = self.read()
                try: v[k] = val
                except TypeError: pass
            return v
        if t == 'r':                                   # back reference
            return self.refs[self.i32()]
        if t == 'c':                                   # code object
            co = Code()
            if idx is not None: self.refs[idx] = co
            co.argcount = self.i32()
            co.kwonlyargcount = self.i32()
            co.nlocals = self.i32()
            co.stacksize = self.i32()
            co.flags = self.i32()
            co.code = self.read()
            co.consts = self.read()
            co.names = self.read()
            co.varnames = self.read()
            co.freevars = self.read()
            co.cellvars = self.read()
            co.filename = self.read()
            co.name = self.read()
            co.firstlineno = self.i32()
            co.lnotab = self.read()
            return co
        raise ValueError(f"unhandled marshal type {t!r} (0x{c:02X}) at {self.i}")


def load_pyc(data):
    """Skip the 16-byte 3.7 header and unmarshal the module code object."""
    return Reader(data[16:]).read()


def walk(co, depth=0):
    yield co, depth
    for c in getattr(co, 'consts', ()) or ():
        if isinstance(c, Code):
            yield from walk(c, depth + 1)
