"""Read the tuning-instance headers out of a COMBINED_TUNING resource.

A COMBINED_TUNING resource (type 0x62E94D38) comes in two encodings and the
install ships both. Anything that reads them has to handle both or it silently
sees 1% of the game.

  text form    starts b'<combined'. Interned XML exactly as PLAN.md describes.
               Three resources in the whole install use it.

  packed form  starts b'DATA'. A SimData container (version 0x101) holding a
               binary DOM under three schemas - PackedXmlDocument,
               PackedXmlNode, PackedXmlAttribute. 273 resources use it, every
               DeltaBuild and Preload among them, which means the packed form
               is what the running game actually loads. Decoding it yields the
               identical document: same tags, same interned <r x="N"/> pool,
               same <I> headers.

The SimData container, as verified against the install (all offsets are signed
and relative to the position of the field holding them; 0x80000000 is null):

  header   'DATA', u32 version, table_info_offset, table_info_count,
           schema_offset, schema_count, then two more words.
  table    name_offset, name_hash, schema_offset, data_type, row_size,
           row_offset, row_count                                   (28 bytes)
  schema   name_offset, name_hash, schema_hash, schema_size,
           column_offset, column_count                             (24 bytes)
  column   name_offset, name_hash, data_type, row_offset, schema  (20 bytes)

Name hashes are FNV-1 32-bit (multiply then xor), basis 0x811C9DC5.

headers() is the entry point: it yields one dict per <I> or <M> header and
nothing else, so a 32 MB resource costs one pass and no DOM.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import re
import struct

NULL = 0x80000000
FNV32_BASIS = 0x811C9DC5
FNV32_PRIME = 0x01000193

DATA_TYPES = {0: 'Bool', 1: 'Char8', 2: 'Int8', 3: 'UInt8', 4: 'Int16',
              5: 'UInt16', 6: 'Int32', 7: 'UInt32', 8: 'Int64', 9: 'UInt64',
              10: 'Float', 11: 'String8', 12: 'HashedString8', 13: 'Object',
              14: 'Vector', 15: 'Float2', 16: 'Float3', 17: 'Float4',
              18: 'TableSetReference', 19: 'ResourceKey', 20: 'LocalizationKey',
              21: 'Variant', 22: 'Undefined'}

_ATTR = re.compile(rb'([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"')
_HDR = re.compile(rb'<([IM])\s([^>]*?)/?>')

_ENT = {'&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&apos;': "'"}


def fnv32(s):
    h = FNV32_BASIS
    for c in s.encode('utf-8'):
        h = (h * FNV32_PRIME) & 0xFFFFFFFF
        h ^= c
    return h


def _unescape(s):
    if '&' not in s:
        return s
    for k, v in _ENT.items():
        s = s.replace(k, v)
    return s


def is_packed(blob):
    return blob[:4] == b'DATA'


def is_text(blob):
    return blob[:9] == b'<combined'


# ---------------------------------------------------------------- text form

def _headers_text(blob):
    for m in _HDR.finditer(blob):
        kind = m.group(1).decode()
        a = {k.decode(): _unescape(v.decode('utf-8', 'replace'))
             for k, v in _ATTR.findall(m.group(2))}
        if 's' in a and 'n' in a:
            yield kind, a


# -------------------------------------------------------------- packed form

class SimData:
    """Minimal SimData reader - schemas and table descriptors only."""

    def __init__(self, blob):
        self.b = blob
        if blob[:4] != b'DATA':
            raise ValueError('not a SimData container')
        self.version = self.u32(4)
        tinfo, tcount = 8 + self.u32(8), self.u32(0x0C)
        sinfo, scount = 0x10 + self.u32(0x10), self.u32(0x14)
        self.schemas = {}
        for i in range(scount):
            p = sinfo + i * 24
            cat, ncol = p + 16 + self.u32(p + 16), self.u32(p + 20)
            cols = {}
            for j in range(ncol):
                c = cat + j * 20
                cols[self.cstr(self.ref(c))] = (self.u32(c + 8), self.u32(c + 12))
            self.schemas[p] = {'name': self.cstr(self.ref(p)),
                               'size': self.u32(p + 12), 'cols': cols}
        self.tables = []
        self.repairs = []
        for i in range(tcount):
            p = tinfo + i * 28
            self.tables.append({'name': self.cstr(self.ref(p)),
                                'schema': self.ref(p + 8),
                                'type': self.u32(p + 12),
                                'row_size': self.u32(p + 16),
                                'row_off': self.ref(p + 20),
                                'count': self.u32(p + 24)})
        self._by_size = {}
        for pos, s in self.schemas.items():
            self._by_size.setdefault(s['size'], []).append(pos)

    def u32(self, p):
        return struct.unpack_from('<I', self.b, p)[0]

    def ref(self, p):
        v = struct.unpack_from('<I', self.b, p)[0]
        if v == NULL:
            return None
        return p + struct.unpack_from('<i', self.b, p)[0]

    def cstr(self, p):
        if p is None:
            return None
        e = self.b.index(b'\0', p)
        return self.b[p:e].decode('utf-8', 'replace')

    def schema_of(self, t):
        """The schema a table is laid out with, or None if it has no schema.

        A table's schema field is normally a ref onto a schema record. One
        resource in the install - EP01/SimulationFullBuild0 - ships two tables
        whose schema refs land inside the column arrays instead, 0x50 and 0x8C
        past the record they should point at. The container is otherwise
        self-consistent, so this is an EA build artifact, not a variant format.

        Where the ref misses, fall back to matching the table's row_size
        against the schema sizes. In every packed COMBINED_TUNING the three
        schemas are 20 / 12 / 8 bytes, so a row_size identifies the schema
        unambiguously; the fallback is refused if it is ever ambiguous.
        Repairs are recorded on self.repairs so callers can report them.
        """
        pos = t['schema']
        if pos is None:
            return None
        s = self.schemas.get(pos)
        if s is not None:
            return s
        cand = self._by_size.get(t['row_size'], ())
        if len(cand) != 1:
            raise ValueError(
                'table schema ref 0x%X is not a schema and row_size %d matches '
                '%d schemas' % (pos, t['row_size'], len(cand)))
        s = self.schemas[cand[0]]
        msg = ('schema ref 0x%X invalid; matched %s by row_size %d'
               % (pos, s['name'], t['row_size']))
        if msg not in self.repairs:      # tables get resolved more than once
            self.repairs.append(msg)
        return s

    def table_named_schema(self, schema_name):
        for t in self.tables:
            s = self.schema_of(t)
            if s is not None and s['name'] == schema_name:
                return t
        return None


def documents(sd):
    """[(first_element, top_element, element_count, [strings])] per document."""
    t = sd.table_named_schema('PackedXmlDocument')
    if t is None or t['row_off'] is None:
        return []
    cols = sd.schema_of(t)['cols']
    o_first = cols['first_element'][1]
    o_top = cols['top_element'][1]
    o_count = cols['element_count'][1]
    o_st = cols['string_table'][1]
    out = []
    for r in range(t['count']):
        p = t['row_off'] + r * t['row_size']
        st = sd.ref(p + o_st)
        n = sd.u32(p + o_st + 4)
        strs = []
        for i in range(n):
            sp = sd.ref(st + i * 4) if st is not None else None
            strs.append(sd.cstr(sp) if sp is not None else '')
        out.append((sd.ref(p + o_first), sd.ref(p + o_top),
                    sd.u32(p + o_count), strs))
    return out


def _headers_packed(blob, repairs=None):
    sd = SimData(blob)
    docs = documents(sd)
    if len(docs) != 1:
        raise ValueError('expected 1 PackedXmlDocument, found %d' % len(docs))
    strs = docs[0][3]
    nt = sd.table_named_schema('PackedXmlNode')
    if nt is None or nt['row_off'] is None:
        return
    ncols = sd.schema_of(nt)['cols']
    o_text = ncols['text'][1]
    o_attrs = ncols['attrs'][1]
    at = sd.table_named_schema('PackedXmlAttribute')
    acols = sd.schema_of(at)['cols']
    o_an, o_av = acols['name'][1], acols['value'][1]
    if repairs is not None:
        repairs.extend(sd.repairs)

    # Which string-table slots hold the two tag names we care about. The pool
    # can intern the same text more than once, so this is a set, not an index.
    want = {i for i, s in enumerate(strs) if s in ('I', 'M')}
    if not want:
        return

    base, size, count = nt['row_off'], nt['row_size'], nt['count']
    b = sd.b
    for r in range(count):
        p = base + r * size
        ti = struct.unpack_from('<I', b, p + o_text)[0]
        if ti not in want:
            continue
        ap = sd.ref(p + o_attrs)
        if ap is None:
            continue                      # bare text node that happens to read 'I'
        a, i = {}, ap
        while True:
            ar = sd.ref(i)
            if ar is None:
                break
            a[strs[sd.u32(ar + o_an)]] = strs[sd.u32(ar + o_av)]
            i += 4
        if 's' in a and 'n' in a:
            yield strs[ti], a


# --------------------------------------------------------------------- api

def headers(blob, repairs=None):
    """Yield (kind, attrs) for every <I> / <M> tuning header in the resource.

    kind is 'I' (instance tuning: c/i/m/n/s) or 'M' (module tuning: n/s).
    Raises ValueError on a resource in neither encoding. If a list is passed
    as repairs, any structural defect worked around is appended to it, so a
    caller can report what it had to fix rather than fixing it silently.
    """
    if is_text(blob):
        return _headers_text(blob)
    if is_packed(blob):
        return _headers_packed(blob, repairs)
    raise ValueError('unrecognised COMBINED_TUNING encoding: %r' % blob[:16])


def encoding(blob):
    return 'text' if is_text(blob) else ('packed' if is_packed(blob) else None)
