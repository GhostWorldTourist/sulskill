"""Ask the base-game database a question.

Built because the alternative - grepping 350 MB of JSONL - failed in the way
that matters: a lookup of instance 14965 returned zero hits, and zero hits from
a scan is indistinguishable from "not present". The field was named `id`, not
`instance`, and the value was a string, not an int. Both mistakes are silent.

So every id argument here is normalised before it is used: 14965, '14965',
0x3A75 and 0X00003a75 all reach the same row, and if a name is genuinely not
present the tool says so rather than shrugging.

    py scripts/q.py id 14965                what is this instance?
    py scripts/q.py id 0xBD4843C7696569F2   hex works the same
    py scripts/q.py name commodity_conti    tuning whose name contains this
    py scripts/q.py find fish bowl          full-text over tuning names
    py scripts/q.py text stuck flirty       full-text over player-visible strings
    py scripts/q.py string 0x0000C3E4       one string by key
    py scripts/q.py sig protocol_list       Python signatures with this name
    py scripts/q.py cls InstanceManager     a class, its methods, where it lives
    py scripts/q.py pkg SimulationDelta     packages matching a name
    py scripts/q.py schema                  what tables and columns exist
    py scripts/q.py sql "SELECT ..."        anything else

`schema` exists so nothing has to be guessed. Run it first when writing a query.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import json
import os
import sqlite3
import sys

DB = os.environ.get('TS4_DB') or os.path.join(
    gate.out_dir(), 'basegame', 'ts4.db')
LIMIT = 40


def canon(v):
    """Any spelling of an id -> (decimal string, padded hex). (None, None) if
    it is not a number at all, which the caller reports rather than guessing."""
    s = str(v).strip()
    try:
        n = int(s, 16) if s.lower().startswith('0x') else int(s)
    except ValueError:
        try:
            n = int(s, 16)
        except ValueError:
            return None, None
    return str(n), '0x%016X' % n


def connect():
    if not os.path.isfile(DB):
        print('no database at %s\nBuild it: py scripts/index.py' % DB,
              file=sys.stderr)
        raise SystemExit(2)
    cx = sqlite3.connect('file:%s?mode=ro' % DB.replace('\\', '/'), uri=True)
    cx.row_factory = sqlite3.Row
    return cx


def show(rows, cols=None, limit=LIMIT):
    rows = list(rows)
    if not rows:
        print('  (nothing)')
        return 0
    cols = cols or rows[0].keys()
    widths = {c: max(len(c), *(len(str(r[c] if r[c] is not None else ''))
                               for r in rows[:limit])) for c in cols}
    widths = {c: min(w, 60) for c, w in widths.items()}
    print('  ' + '  '.join(c.ljust(widths[c]) for c in cols))
    print('  ' + '  '.join('-' * widths[c] for c in cols))
    for r in rows[:limit]:
        print('  ' + '  '.join(
            str(r[c] if r[c] is not None else '')[:widths[c]].ljust(widths[c])
            for c in cols))
    if len(rows) > limit:
        print('  ... and %d more' % (len(rows) - limit))
    return len(rows)


def cmd_id(cx, value):
    dec, hx = canon(value)
    if dec is None:
        print('%r is not a number in any base I recognise.' % value,
              file=sys.stderr)
        return 2
    print('id %s  (%s)\n' % (dec, hx))
    n = show(cx.execute(
        'SELECT id, id_hex, type, name, class, module, package '
        'FROM instances WHERE id = ? OR id_hex = ?', (dec, hx)))
    disp = list(cx.execute(
        'SELECT tuning_type, name, display, display_field '
        'FROM display_names WHERE instance = ?', (dec,)))
    if disp:
        print('\nplayer-visible:')
        show(disp)
    if not n:
        print('\nNot a vanilla instance. If a mod defines it, the id is the '
              'mod\'s own -\nsee mod-vs-vanilla.md for how to classify it.')
        return 1
    return 0


def cmd_name(cx, pattern):
    return 0 if show(cx.execute(
        'SELECT id, type, name, class, module, package FROM instances '
        'WHERE name LIKE ? ORDER BY type, name', ('%%%s%%' % pattern,))) else 1


def cmd_find(cx, words):
    return 0 if show(cx.execute(
        'SELECT name, type, id FROM fts_names WHERE fts_names MATCH ? '
        'ORDER BY rank', (' '.join(words),))) else 1


def cmd_text(cx, words):
    return 0 if show(cx.execute(
        'SELECT key_hex, text FROM fts_strings WHERE fts_strings MATCH ? '
        'ORDER BY rank', (' '.join(words),))) else 1


def cmd_string(cx, key):
    dec, hx = canon(key)
    if dec is None:
        return cmd_text(cx, [key])
    return 0 if show(cx.execute(
        'SELECT key_hex, text FROM strings WHERE key_int = ? OR key_hex = ?',
        (int(dec), key))) else 1


def cmd_sig(cx, name):
    print('methods:')
    a = show(cx.execute(
        'SELECT module, class_name, name, sig, line FROM py_methods '
        'WHERE name = ? ORDER BY module', (name,)))
    print('\nfunctions:')
    b = show(cx.execute(
        'SELECT module, name, sig, line FROM py_functions '
        'WHERE name = ? ORDER BY module', (name,)))
    return 0 if (a or b) else 1


def cmd_cls(cx, name):
    print('classes:')
    a = show(cx.execute(
        'SELECT module, name, qualname, line, bases FROM py_classes '
        'WHERE name = ? ORDER BY module', (name,)))
    print('\nmethods:')
    show(cx.execute(
        'SELECT module, name, sig, line FROM py_methods '
        'WHERE class_name = ? ORDER BY line', (name,)), limit=200)
    return 0 if a else 1


def cmd_pkg(cx, pattern):
    return 0 if show(cx.execute(
        'SELECT ordinal, name, pack, layer, role, entries, tombstones, size '
        'FROM packages WHERE name LIKE ? OR path LIKE ? ORDER BY ordinal',
        ('%%%s%%' % pattern, '%%%s%%' % pattern))) else 1


def cmd_schema(cx, _):
    for (sql,) in cx.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
            "AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name"):
        print(sql.strip() + ';\n')
    print('-- row counts')
    for r in cx.execute("SELECT k, v FROM meta ORDER BY k"):
        print('--   %-22s %s' % (r['k'], r['v']))
    return 0


def cmd_sql(cx, query):
    try:
        return 0 if show(cx.execute(query), limit=200) else 1
    except sqlite3.Error as exc:
        print('%s\n\nRun `q.py schema` - guessing column names is what this '
              'tool exists to stop.' % exc, file=sys.stderr)
        return 2


ACTIONS = {'id': cmd_id, 'name': cmd_name, 'find': cmd_find, 'text': cmd_text,
           'string': cmd_string, 'sig': cmd_sig, 'cls': cmd_cls,
           'pkg': cmd_pkg, 'schema': cmd_schema, 'sql': cmd_sql}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('action', choices=sorted(ACTIONS))
    ap.add_argument('rest', nargs='*')
    a = ap.parse_args(argv)

    cx = connect()
    fn = ACTIONS[a.action]
    if a.action in ('find', 'text'):
        if not a.rest:
            print('%s needs something to search for' % a.action, file=sys.stderr)
            return 2
        return fn(cx, a.rest)
    if a.action == 'schema':
        return fn(cx, None)
    if not a.rest:
        print('%s needs an argument' % a.action, file=sys.stderr)
        return 2
    return fn(cx, ' '.join(a.rest))


if __name__ == '__main__':
    sys.exit(main())
