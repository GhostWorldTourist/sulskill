"""Catalogue every SimData schema the base game defines.

SimData is the binary companion to tuning: where the merged XML says what an
instance IS, SimData carries the typed fields the engine reads directly -
mood_weight, ui_sort_order, the localization keys behind a buff's name. There
are ~324,000 SimData resources in the install and only a small number of
distinct schemas, so the catalogue converges long before the scan does.

The find that makes this worth keeping: a schema's name_hash is the tuning
resource type id. The 'Buff' schema hashes to 1612179606, which is 0x6017E896,
which is Types.BUFF. So a SimData resource identifies its own tuning type
without reference to anything external.

Reads a bounded sample per package rather than all 324k resources - schemas
repeat, payloads do not, and decompressing the lot would buy nothing.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'lib'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'sulskill-modbuild', 'scripts'))

import dbpf_index as D          # noqa: E402
import restypes                 # noqa: E402
import simdata                  # noqa: E402

SIMDATA = 0x545AC67A            # Types calls this PLAYLIST; it is not
GAME = os.environ.get('TS4_INSTALL') or gate.game_dir()
PER_PACKAGE = 300               # enough to see every schema a package uses

# SimData column types. The game's Python never names these - the same silence
# it keeps about STBL, and for the same reason: the engine owns the format and
# the script layer never sees it. So unlike restypes, this table is DERIVED, and
# each entry carries how far the evidence actually goes.
#
#   verified - decoded real bytes and the values were unambiguous
#   strong   - byte width plus field semantics leave one reading
#   probable - consistent with the evidence, other readings not excluded
#
# Two were settled by decoding rather than by inference, and they are the two
# that matter most because they are the same width and would silently swap:
# type 10 read as float gives Commodity max_value_tuning = 1440 and 60, which
# are minutes in a sim day and an hour; type 6 read as uint32 gives Statistic
# max_value_tuning = 10 and 999999999. Each reading is nonsense under the other
# code. A parser that confuses them reports plausible numbers that are wrong.
TYPECODE = {
    0:  ('bool', 'strong'),            # 1 byte: is_hidden, disabled
    6:  ('int32', 'verified'),
    7:  ('int64', 'probable'),
    8:  ('uint64', 'strong'),          # 8 bytes: key, trait_type
    9:  ('hashed_string', 'probable'),  # 8 bytes, all *Name fields
    10: ('float32', 'verified'),
    11: ('string', 'probable'),        # asm params
    13: ('vector', 'probable'),        # _components, arrow_data
    14: ('vector', 'probable'),        # objectives, category - most common code
    16: ('float3', 'strong'),          # 12 bytes: Position, Color, CameraTarget
    18: ('object_ref', 'probable'),    # 8 bytes: reward, primary_trait
    19: ('resource_key', 'strong'),    # 16 bytes = type + group + instance
    20: ('localization_key', 'strong'),  # display_name, descriptive_text
    21: ('variant', 'probable'),       # tooltip, ui_category
}


def main():
    schemas = {}                       # schema_hash -> record
    seen_in = collections.defaultdict(set)
    counts = collections.Counter()
    failures = collections.Counter()
    scanned = 0
    with_simdata = 0

    pkgs = sorted(glob.glob(os.path.join(GAME, '**', '*.package'),
                            recursive=True))
    for p in pkgs:
        rel = os.path.relpath(p, GAME)
        try:
            ents = [(o, f, c) for t, g, i, o, f, c in D.index(p)
                    if t == SIMDATA and f > 0]
        except Exception as e:
            failures['index: %s' % type(e).__name__] += 1
            continue
        if not ents:
            continue
        with_simdata += 1
        for blob in D.fetch(p, ents[:PER_PACKAGE]):
            scanned += 1
            try:
                rec = simdata.parse(blob)
            except Exception as e:
                failures['parse: %s: %s' % (type(e).__name__, str(e)[:60])] += 1
                continue
            for s in rec.get('schemas', []):
                h = s.get('schema_hash')
                counts[s.get('name')] += 1
                seen_in[h].add(rel)
                if h not in schemas:
                    schemas[h] = {
                        'name': s.get('name'),
                        'name_hash': s.get('name_hash'),
                        'schema_hash': h,
                        'size': s.get('size'),
                        'columns': [
                            {'name': c.get('name'),
                             'hash': c.get('hash'),
                             'type': c.get('type'),
                             'type_name': TYPECODE.get(
                                 c.get('type'), ('unknown', 'none'))[0],
                             'type_confidence': TYPECODE.get(
                                 c.get('type'), ('unknown', 'none'))[1],
                             'offset': c.get('offset')}
                            for c in s.get('columns', [])
                        ],
                    }

    names = restypes.type_names()
    out = os.path.join(HERE, 'out', 'simdata_schemas.json')
    for h, rec in schemas.items():
        rec['packages'] = len(seen_in[h])
        # name_hash is the tuning resource type id - resolve it where the
        # game's own table knows the name.
        rec['tuning_type'] = names.get(rec.get('name_hash'))
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(sorted(schemas.values(), key=lambda r: r['name'] or ''),
                  f, indent=2)

    print('packages scanned      : %d' % len(pkgs))
    print('packages with SimData : %d' % with_simdata)
    print('resources parsed      : %d' % scanned)
    print('distinct schemas      : %d' % len(schemas))
    print('parse failures        : %d' % sum(failures.values()))
    for k, v in failures.most_common(8):
        print('    %6d  %s' % (v, k))
    print()
    matched = sum(1 for r in schemas.values() if r['tuning_type'])
    print('schemas whose name_hash resolves to a known tuning type: %d/%d'
          % (matched, len(schemas)))
    print()
    print('%-34s %-22s %5s %5s' % ('schema', 'tuning type', 'cols', 'pkgs'))
    for r in sorted(schemas.values(), key=lambda r: -r['packages'])[:40]:
        print('%-34s %-22s %5d %5d' % (
            (r['name'] or '?')[:34], r['tuning_type'] or '-',
            len(r['columns']), r['packages']))
    print()
    print('wrote %s' % out)


if __name__ == '__main__':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    main()
