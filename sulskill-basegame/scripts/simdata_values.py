"""Read actual values out of SimData, not just its shape.

The existing parsers stop at structure: they will tell you a resource has a Buff
schema with a mood_weight column at offset 72, and then hand you nothing. The
values are what a diagnosis question is usually about - what IS this buff's mood
weight, which string does its name point at - so this reads them.

Two rules govern the whole module, and both were learned the expensive way.

READ BY COLUMN HASH, NEVER BY CACHED OFFSET. The same schema name ships in
several incompatible layouts in one install: `Buff` exists in four, with
mood_weight at offset 72, 64 or 80 depending on which pack built the resource.
Each resource embeds the schema it was built against, so the offset is only
meaningful within that resource. The column hash is stable - across 449 schemas
and 1004 distinct field names, not one name has two hashes. See notes/simdata.md.

EVERY OFFSET IS SELF-RELATIVE. A stored int32 is a delta from the position of
the field that holds it, not from the start of the resource. 0x80000000 is null.
Getting this wrong yields values that look like data.

Scalars are decoded. References - vectors, objects, variants - are returned as a
Ref rather than chased, because chasing them needs the object-table machinery
that lib/mergedtuning.py owns and duplicating it here would mean two decoders
disagreeing later.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import struct

MAGIC = b'DATA'
NULL_OFFSET = 0x80000000

# Verified against real payloads; see notes/simdata.md for the evidence and for
# which entries are inferred rather than decoded. 6 and 10 are the pair that
# would silently swap - both four bytes, both used for min/max_value_tuning -
# so both were confirmed by decoding, not by inference.
SCALARS = {
    0:  ('bool', '<?', 1),
    6:  ('int32', '<i', 4),
    7:  ('int64', '<q', 8),
    8:  ('uint64', '<Q', 8),
    9:  ('hashed_string', '<Q', 8),
    10: ('float32', '<f', 4),
    16: ('float3', '<3f', 12),
}
REFERENCE_TYPES = {11, 13, 14, 18, 19, 20, 21}


class Ref(object):
    """A value this module deliberately does not follow."""

    __slots__ = ('type', 'raw')

    def __init__(self, type_code, raw):
        self.type = type_code
        self.raw = raw

    def __repr__(self):
        return 'Ref(type=%d, raw=%r)' % (self.type, self.raw)


def _rel(data, pos):
    """Resolve a self-relative int32 pointer. None if null."""
    v = struct.unpack_from('<i', data, pos)[0]
    if (v & 0xFFFFFFFF) == NULL_OFFSET:
        return None
    return pos + v


def _cstr(data, pos):
    if pos is None:
        return None
    end = data.index(b'\0', pos)
    return data[pos:end].decode('utf-8', 'replace')


def parse(data):
    """Structure plus the row-data offset the other parsers drop.

    Returns {'version', 'schemas', 'tables'} where each table additionally
    carries 'data_offset' and a resolved 'schema'. That offset lives at table
    record + 20 and is the reason values were unreadable before.
    """
    if data[:4] != MAGIC:
        raise ValueError('not a SimData resource')
    version = struct.unpack_from('<I', data, 4)[0]
    table_pos, num_tables = _rel(data, 8), struct.unpack_from('<i', data, 12)[0]
    schema_pos, num_schemas = _rel(data, 16), struct.unpack_from('<i', data, 20)[0]

    schemas, by_pos, p = [], {}, schema_pos
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
        s = {'name': name, 'name_hash': name_hash, 'schema_hash': schema_hash,
             'size': size, 'columns': cols,
             'by_hash': dict((c['hash'], c) for c in cols),
             'by_name': dict((c['name'], c) for c in cols)}
        schemas.append(s)
        by_pos[p] = s
        p += 24

    tables, p = [], table_pos
    for _ in range(num_tables):
        tables.append({
            'name': _cstr(data, _rel(data, p)),
            'name_hash': struct.unpack_from('<I', data, p + 4)[0],
            'schema': by_pos.get(_rel(data, p + 8)),
            'data_type': struct.unpack_from('<I', data, p + 12)[0],
            'row_size': struct.unpack_from('<I', data, p + 16)[0],
            'data_offset': _rel(data, p + 20),
            'row_count': struct.unpack_from('<I', data, p + 24)[0],
        })
        p += 28
    return {'version': version, 'schemas': schemas, 'tables': tables}


def read_field(data, table, row, column):
    """One field of one row. `column` is a column dict from the table's schema.

    The caller passes the column rather than a name so that it is always the
    column from THIS resource's schema, which is the only one whose offset
    applies. Look it up via table['schema']['by_hash'].
    """
    base = table['data_offset']
    if base is None:
        return None
    pos = base + row * table['row_size'] + column['offset']
    code = column['type']
    if code in SCALARS:
        _, fmt, width = SCALARS[code]
        if pos + width > len(data):
            return None
        v = struct.unpack_from(fmt, data, pos)
        return v if len(v) > 1 else v[0]
    if code == 19:                       # resource key: type, group, instance
        t, g, lo, hi = struct.unpack_from('<IIII', data, pos)
        return (t, g, (hi << 32) | lo)
    if code == 20:                       # localization key
        return struct.unpack_from('<I', data, pos)[0]
    return Ref(code, data[pos:pos + 8])


def read_row(data, table, row=0):
    """A whole row as {field_name: value}. None if the table has no schema."""
    s = table.get('schema')
    if not s or table['data_offset'] is None:
        return None
    return dict((c['name'], read_field(data, table, row, c))
                for c in s['columns'])


def rows(data, table):
    """Every row of a table."""
    for i in range(table['row_count']):
        r = read_row(data, table, i)
        if r is not None:
            yield r


def find_tables(parsed, schema_name):
    """Tables in this resource built on a given schema, by schema name."""
    return [t for t in parsed['tables']
            if t.get('schema') and t['schema']['name'] == schema_name]
