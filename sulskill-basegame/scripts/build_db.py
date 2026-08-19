"""Fold the extracted JSONL into one queryable SQLite database.

Why this exists
---------------
The extraction produced 350 MB of JSONL. That is the right shape for building
it and the wrong shape for using it. Answering "what is instance 14965?" meant
a linear scan of a 213 MB file, and the first attempt returned **zero hits** -
not because the answer was missing, but because the query guessed the field
name (`instance`, when it is `id`) and the value type (int, when ids are stored
as strings so the ones above 2^63 survive). A wrong field name and a wrong type
both look exactly like "not found".

SQLite fixes precisely that class of failure:

  - `.schema` states the field names, so nothing has to be guessed.
  - Typed columns and a normalising query layer mean 14965, '14965' and
    0x3A75 all reach the same row.
  - An index turns a 213 MB scan into a lookup, so asking is cheap enough to
    do casually - which matters, because the expensive queries tonight were
    the ones I talked myself out of running.
  - Joins that were impractical across separate files - instance to display
    string, tuning to the Python class that implements it - become one query.

Ids are stored as TEXT, deliberately. Instance ids run to 2^64-1 and SQLite's
INTEGER is signed 64-bit, so the largest ones overflow into negatives. Both the
decimal and hex spellings are stored and indexed; `q.py` normalises whatever it
is handed into both.

    py scripts/build_db.py            # fold the extracted JSONL into one database
    py scripts/build_db.py --force    # rebuild from scratch
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(gate.out_dir(), 'basegame')
DB = os.path.join(OUT, 'ts4.db')
BATCH = 20000

SCHEMA = """
PRAGMA journal_mode = OFF;
PRAGMA synchronous = OFF;

-- One row per vanilla tuning instance. id is TEXT: see the module docstring.
CREATE TABLE instances (
    id        TEXT NOT NULL,       -- canonical decimal, e.g. '14965'
    id_hex    TEXT NOT NULL,       -- '0x0000000000003A75'
    kind      TEXT,
    type      TEXT,                -- tuning type, e.g. 'object', 'interaction'
    name      TEXT,
    class     TEXT,
    module    TEXT,
    package   TEXT,
    ct_group  TEXT,
    ct_key    TEXT
);

-- English string table. key is the literal 32-bit STBL key, not a hash of it.
CREATE TABLE strings (
    key_hex  TEXT NOT NULL,
    key_int  INTEGER NOT NULL,
    text     TEXT
);

-- Tuning that carries a player-visible name, already joined at build time.
CREATE TABLE display_names (
    tuning_type   TEXT,
    type_id       TEXT,
    instance      TEXT,
    name          TEXT,
    class         TEXT,
    module        TEXT,
    display_key   TEXT,
    display       TEXT,
    display_field TEXT,
    package       TEXT
);

CREATE TABLE packages (
    ordinal    INTEGER,
    path       TEXT,
    dir        TEXT,
    name       TEXT,
    pack       TEXT,
    layer      TEXT,
    role       TEXT,
    size       INTEGER,
    entries    INTEGER,
    tombstones INTEGER,
    mounts     TEXT,               -- JSON: manager -> priority
    types      TEXT                -- JSON: type id -> count
);

-- The game's own Python, flattened so a signature can be looked up directly.
CREATE TABLE py_modules   (module TEXT, archive TEXT, file TEXT);
CREATE TABLE py_classes   (module TEXT, name TEXT, qualname TEXT,
                           line INTEGER, bases TEXT);
CREATE TABLE py_methods   (module TEXT, class_name TEXT, name TEXT,
                           sig TEXT, line INTEGER);
CREATE TABLE py_functions (module TEXT, name TEXT, sig TEXT, line INTEGER);

-- What this database is and when it was built, so it can describe itself.
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
"""

INDICES = """
CREATE INDEX ix_inst_id     ON instances(id);
CREATE INDEX ix_inst_hex    ON instances(id_hex);
CREATE INDEX ix_inst_name   ON instances(name);
CREATE INDEX ix_inst_type   ON instances(type);
CREATE INDEX ix_inst_class  ON instances(class);
CREATE INDEX ix_inst_pkg    ON instances(package);
CREATE INDEX ix_str_hex     ON strings(key_hex);
CREATE INDEX ix_str_int     ON strings(key_int);
CREATE INDEX ix_disp_inst   ON display_names(instance);
CREATE INDEX ix_disp_name   ON display_names(name);
CREATE INDEX ix_pkg_name    ON packages(name);
CREATE INDEX ix_pycls_name  ON py_classes(name);
CREATE INDEX ix_pymeth_name ON py_methods(name);
CREATE INDEX ix_pyfun_name  ON py_functions(name);
CREATE INDEX ix_pymeth_cls  ON py_methods(class_name);
"""


def rows(path):
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue


def canon(v):
    """Any spelling of an id -> (decimal string, 0x-padded hex string)."""
    if v is None:
        return None, None
    s = str(v).strip()
    try:
        n = int(s, 16) if s.lower().startswith('0x') else int(s)
    except ValueError:
        return s, None
    return str(n), '0x%016X' % n


def load_instances(cx, path, note):
    buf = []
    for r in rows(path):
        dec, hx = canon(r.get('id'))
        buf.append((dec, hx or r.get('id_hex'), r.get('kind'), r.get('type'),
                    r.get('name'), r.get('class'), r.get('module'),
                    r.get('package'), r.get('ct_group'), r.get('ct_key')))
        if len(buf) >= BATCH:
            cx.executemany('INSERT INTO instances VALUES (?,?,?,?,?,?,?,?,?,?)', buf)
            buf.clear()
    if buf:
        cx.executemany('INSERT INTO instances VALUES (?,?,?,?,?,?,?,?,?,?)', buf)
    note('instances', cx.execute('SELECT count(*) FROM instances').fetchone()[0])


def load_strings(cx, path, note):
    buf = []
    for r in rows(path):
        key = r.get('key')
        dec, _ = canon(key)
        buf.append((key, int(dec) if dec and dec.isdigit() else 0, r.get('text')))
        if len(buf) >= BATCH:
            cx.executemany('INSERT INTO strings VALUES (?,?,?)', buf)
            buf.clear()
    if buf:
        cx.executemany('INSERT INTO strings VALUES (?,?,?)', buf)
    note('strings', cx.execute('SELECT count(*) FROM strings').fetchone()[0])


def load_display(cx, path, note):
    buf = []
    for r in rows(path):
        inst, _ = canon(r.get('instance'))
        tid, _ = canon(r.get('type_id'))
        buf.append((r.get('tuning_type'), tid, inst, r.get('name'),
                    r.get('class'), r.get('module'), r.get('display_key'),
                    r.get('display'), r.get('display_field'), r.get('package')))
        if len(buf) >= BATCH:
            cx.executemany('INSERT INTO display_names VALUES (?,?,?,?,?,?,?,?,?,?)', buf)
            buf.clear()
    if buf:
        cx.executemany('INSERT INTO display_names VALUES (?,?,?,?,?,?,?,?,?,?)', buf)
    note('display_names',
         cx.execute('SELECT count(*) FROM display_names').fetchone()[0])


def load_packages(cx, path, note):
    buf = []
    for r in rows(path):
        buf.append((r.get('ordinal'), r.get('path'), r.get('dir'), r.get('name'),
                    r.get('pack'), r.get('layer'), r.get('role'), r.get('size'),
                    r.get('entries'), r.get('tombstones'),
                    json.dumps(r.get('mounts')), json.dumps(r.get('types'))))
    cx.executemany('INSERT INTO packages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', buf)
    note('packages', len(buf))


def load_python(cx, path, note):
    mods, classes, methods, funcs = [], [], [], []
    for r in rows(path):
        module = r.get('module')
        mods.append((module, r.get('archive'), r.get('file')))
        for c in r.get('classes') or ():
            classes.append((module, c.get('name'), c.get('qualname'),
                            c.get('line'), json.dumps(c.get('bases'))))
            for m in c.get('methods') or ():
                methods.append((module, c.get('name'), m.get('name'),
                                m.get('sig'), m.get('line')))
        for fn in r.get('functions') or ():
            funcs.append((module, fn.get('name'), fn.get('sig'), fn.get('line')))
    cx.executemany('INSERT INTO py_modules VALUES (?,?,?)', mods)
    cx.executemany('INSERT INTO py_classes VALUES (?,?,?,?,?)', classes)
    cx.executemany('INSERT INTO py_methods VALUES (?,?,?,?,?)', methods)
    cx.executemany('INSERT INTO py_functions VALUES (?,?,?,?)', funcs)
    for name, n in (('py_modules', len(mods)), ('py_classes', len(classes)),
                    ('py_methods', len(methods)), ('py_functions', len(funcs))):
        note(name, n)


def build_fts(cx):
    """Search by words, for when the exact name is not known.

    Kept as separate contentless-ish tables rather than one, because a hit in a
    tuning name and a hit in player-visible text mean different things and
    merging them makes the result harder to act on.
    """
    cx.execute("CREATE VIRTUAL TABLE fts_names USING fts5("
               "name, type, id UNINDEXED, tokenize='unicode61')")
    cx.execute("INSERT INTO fts_names SELECT name, type, id FROM instances "
               "WHERE name IS NOT NULL")
    cx.execute("CREATE VIRTUAL TABLE fts_strings USING fts5("
               "text, key_hex UNINDEXED, tokenize='unicode61')")
    cx.execute("INSERT INTO fts_strings SELECT text, key_hex FROM strings "
               "WHERE text IS NOT NULL")


SOURCES = (
    ('instances.jsonl', load_instances),
    ('strings_en.jsonl', load_strings),
    ('display_names.jsonl', load_display),
    ('packages.jsonl', load_packages),
    ('python_api.jsonl', load_python),
)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', default=DB)
    ap.add_argument('--force', action='store_true', help='rebuild from scratch')
    a = ap.parse_args(argv)

    if os.path.exists(a.out):
        if not a.force:
            print('%s exists; --force to rebuild' % a.out, file=sys.stderr)
            return 2
        os.remove(a.out)

    started = time.time()
    counts = {}

    def note(name, n):
        counts[name] = n
        print('  %-16s %9d' % (name, n))

    cx = sqlite3.connect(a.out)
    cx.executescript(SCHEMA)
    for fname, loader in SOURCES:
        path = os.path.join(OUT, fname)
        if not os.path.isfile(path):
            print('  %-16s MISSING (%s)' % (fname, path), file=sys.stderr)
            continue
        loader(cx, path, note)
        cx.commit()
    print('  building indices ...')
    cx.executescript(INDICES)
    print('  building full-text search ...')
    build_fts(cx)
    cx.execute('INSERT INTO meta VALUES (?,?)',
               ('built_at', time.strftime('%Y-%m-%dT%H:%M:%S')))
    for k, v in counts.items():
        cx.execute('INSERT INTO meta VALUES (?,?)', ('rows_' + k, str(v)))
    cx.commit()
    cx.execute('VACUUM')
    cx.execute('ANALYZE')
    cx.commit()
    cx.close()

    size = os.path.getsize(a.out)
    print('\n%s\n  %.1f MB, built in %.0fs'
          % (a.out, size / 1e6, time.time() - started))
    return 0


if __name__ == '__main__':
    sys.exit(main())
