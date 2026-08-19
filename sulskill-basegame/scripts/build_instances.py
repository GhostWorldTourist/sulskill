"""Track A - index every tuning instance the install ships.

Walks all COMBINED_TUNING resources (type 0x62E94D38) across the game install,
pulls every <I> / <M> header out of each, and writes:

    out/instances.jsonl        one JSON object per tuning instance
    out/instances_summary.md   totals, per-type, per-package, override picture

Ids are written as a decimal string and a hex string, never as a JSON number:
they are 64-bit and routinely exceed 2^53, so a JSON number would silently
round. 6033337089883832568 parses back as 6033337089883832000 if you let it be
a number, which is a different instance.

Nothing here holds more than one decompressed resource at a time; the largest
is 32 MB and there are 276 of them.
"""
import collections
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'lib'))

import gate                                              # noqa: E402,F401
import dbpf_index                                        # noqa: E402
import restypes                                          # noqa: E402
import combinedtuning                                    # noqa: E402

COMBINED_TUNING = 0x62E94D38
GAME = os.environ.get('TS4_INSTALL') or gate.game_dir()
OUT = os.path.join(gate.out_dir(), 'basegame')


def tuning_type_map():
    """{i-attribute value: (TYPE_NAME, resource_type_id)} from the game's enum.

    restypes gives {'BUFF': {'name': 'buff', 'resource_type': 0x6017E896}}.
    The <I i="..."> attribute usually carries that 'name' - but where the enum
    entry also declares a 'file_extension', the i attribute carries *that*
    instead: RELATIONSHIP_BIT ships as i="relbit", STATIC_COMMODITY as
    i="scommodity". Keying on name alone loses 7000+ instances, so both go in.

    A lowercased key is added as a fallback because a handful of i values are
    spelled with capitals the enum does not use.
    """
    _binary, tuning = restypes.load()
    exact, lower = {}, {}
    for name, d in tuning.items():
        rt = d.get('resource_type')
        if not isinstance(rt, int):
            continue
        for key in (d.get('name'), d.get('file_extension')):
            if isinstance(key, str) and key:
                exact.setdefault(key, (name, rt))
                lower.setdefault(key.lower(), (name, rt))
    return exact, lower


def packages(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for f in sorted(filenames):
            if f.lower().endswith('.package'):
                yield os.path.join(dirpath, f)


def main():
    os.makedirs(OUT, exist_ok=True)
    exact, lower = tuning_type_map()

    jsonl = os.path.join(OUT, 'instances.jsonl')
    per_type = collections.Counter()
    per_pkg = collections.Counter()
    per_kind = collections.Counter()
    encodings = collections.Counter()
    unmapped = collections.Counter()
    mapped = 0
    total = 0
    # (type, id) -> [package index, ...]. Ints, not paths, to keep this small.
    seen = collections.defaultdict(list)
    pkg_names = []
    failures = []
    repairs = []
    repaired = []
    # CT resource key -> packages carrying it. The group id is the pack id.
    ct_keys = collections.defaultdict(set)
    per_group = collections.Counter()
    resources = 0

    t0 = time.time()
    with open(jsonl, 'w', encoding='utf-8', newline='\n') as out:
        for path in packages(GAME):
            rel = os.path.relpath(path, GAME).replace('\\', '/')
            try:
                keys = [(g, i, o, s, c) for t, g, i, o, s, c
                        in dbpf_index.index(path) if t == COMBINED_TUNING]
            except Exception as e:                       # noqa: BLE001
                failures.append((rel, 'index failed: %s' % e))
                continue
            if not keys:
                continue
            ents = [(o, s, c) for _g, _i, o, s, c in keys]
            pkg_id = len(pkg_names)
            pkg_names.append(rel)
            for n, blob in enumerate(dbpf_index.fetch(path, ents)):
                resources += 1
                ct_group, ct_inst = keys[n][0], keys[n][1]
                ct_key = '%08X-%016X' % (ct_group, ct_inst)
                ct_keys[ct_key].add(rel)
                enc = combinedtuning.encoding(blob)
                encodings[enc or 'unknown'] += 1
                try:
                    heads = list(combinedtuning.headers(blob, repairs=repairs))
                except Exception as e:                   # noqa: BLE001
                    failures.append((rel, 'parse failed (%s): %s' % (enc, e)))
                    continue
                for r in repairs:
                    repaired.append((rel, r))
                del repairs[:]
                for kind, a in heads:
                    ident = a['s']
                    try:
                        idv = int(ident)
                    except ValueError:
                        failures.append((rel, 'non-numeric instance id %r' % ident))
                        continue
                    itype = a.get('i')
                    rec = {
                        'id': ident,
                        'id_hex': '0x%016X' % idv,
                        'kind': kind,
                        'type': itype,
                        'name': a.get('n'),
                        'class': a.get('c'),
                        'module': a.get('m'),
                        'package': rel,
                        'ct_group': '0x%08X' % ct_group,
                        'ct_key': ct_key,
                    }
                    if itype:
                        hit = exact.get(itype) or lower.get(itype.lower())
                        if hit:
                            rec['type_name'], rec['type_id'] = hit
                            rec['type_id_hex'] = '0x%08X' % hit[1]
                            mapped += 1
                        else:
                            unmapped[itype] += 1
                    out.write(json.dumps(rec, ensure_ascii=False) + '\n')
                    total += 1
                    per_type[itype or ('<module:%s>' % kind)] += 1
                    per_pkg[rel] += 1
                    per_kind[kind] += 1
                    per_group[ct_key] += 1
                    seen[(itype, ident)].append(pkg_id)
                del blob
            sys.stderr.write('\r%-72s %8d' % (rel[-72:], total))
    sys.stderr.write('\n')

    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    dup_records = sum(len(v) for v in dupes.values())
    write_summary(OUT, total, resources, per_type, per_pkg, per_kind, encodings,
                  mapped, unmapped, dupes, dup_records, pkg_names, failures,
                  ct_keys, per_group, repaired, time.time() - t0)
    print('%d instances from %d resources in %d packages -> %s'
          % (total, resources, len(pkg_names), jsonl))
    if failures:
        print('%d failures - see the summary' % len(failures))


def write_summary(out, total, resources, per_type, per_pkg, per_kind,
                  encodings, mapped, unmapped, dupes, dup_records, pkg_names,
                  failures, ct_keys, per_group, repaired, secs):
    p = os.path.join(out, 'instances_summary.md')
    typed = sum(v for k, v in per_type.items() if not k.startswith('<module:'))
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        w = f.write
        w('# Tuning instance index\n\n')
        w('Generated by `build_a_instances.py` in %.0f s from `%s`.\n\n' % (secs, GAME))
        w('| | |\n| --- | --- |\n')
        w('| tuning instances | %d |\n' % total)
        w('| COMBINED_TUNING resources | %d |\n' % resources)
        w('| packages contributing | %d |\n' % len(pkg_names))
        w('| distinct tuning types | %d |\n' % len([k for k in per_type if not k.startswith('<module:')]))
        w('| `<I>` instance tuning | %d |\n' % per_kind.get('I', 0))
        w('| `<M>` module tuning | %d |\n' % per_kind.get('M', 0))
        w('| resource encodings | %s |\n' % ', '.join(
            '%s %d' % kv for kv in sorted(encodings.items())))
        w('| `i` values mapped to a resource type | %d / %d (%.2f%%) |\n'
          % (mapped, typed, 100.0 * mapped / typed if typed else 0))
        w('| distinct COMBINED_TUNING resource keys | %d |\n' % len(ct_keys))
        w('| parse failures | %d |\n' % len(failures))
        w('| resources needing a structural repair | %d |\n' % len(repaired))
        w('\n')

        w('## COMBINED_TUNING resource keys\n\n')
        w('There is exactly one COMBINED_TUNING resource per package, but not\n'
          'one key per package: the group id is the *pack* id, and the three or\n'
          'four packages belonging to a pack (FullBuild0 / DeltaBuild0 /\n'
          'Preload) all carry that pack\'s single key. Looking CT up by a fixed\n'
          'key therefore finds one pack and misses the rest; enumerate by type.\n\n')
        w('| key (group-instance) | instances | packages |\n| --- | ---: | --- |\n')
        for k, pkgs in sorted(ct_keys.items(),
                              key=lambda kv: -per_group.get(kv[0], 0)):
            w('| `%s` | %d | %s |\n'
              % (k, per_group.get(k, 0),
                 ', '.join('`%s`' % s for s in sorted(pkgs))))
        w('\n')

        w('## Unmapped tuning types\n\n')
        if unmapped:
            w('`i` values with no entry in `sims4.resources.Types`, by instance count.\n\n')
            w('| `i` | instances |\n| --- | ---: |\n')
            for k, v in unmapped.most_common():
                w('| `%s` | %d |\n' % (k, v))
        else:
            w('None - every `i` value resolved to a resource type.\n')
        w('\n')

        w('## Instances per tuning type\n\n')
        w('| tuning type | instances |\n| --- | ---: |\n')
        for k, v in per_type.most_common():
            w('| `%s` | %d |\n' % (k, v))
        w('\n')

        w('## Instances per source package\n\n')
        w('| package | instances |\n| --- | ---: |\n')
        for k, v in per_pkg.most_common():
            w('| `%s` | %d |\n' % (k, v))
        w('\n')

        w('## Duplication across packages\n\n')
        w('A (tuning type, instance id) pair present in more than one package.\n'
          'This is the override mechanism: the package the game loads last wins,\n'
          'so a duplicate is a pack (or a patch delta) replacing earlier tuning.\n\n')
        w('| | |\n| --- | --- |\n')
        w('| distinct (type, id) pairs | %d |\n' % (total - dup_records + len(dupes)))
        w('| pairs appearing in >1 package | %d |\n' % len(dupes))
        w('| instance records involved | %d |\n' % dup_records)
        w('\n')
        pairs = collections.Counter()
        for (t, _i), v in dupes.items():
            pairs[tuple(sorted(set(v)))] += 1
        w('### Package sets that share instances\n\n')
        w('| packages | shared instances |\n| --- | ---: |\n')
        for combo, n in pairs.most_common(25):
            w('| %s | %d |\n' % (' + '.join('`%s`' % pkg_names[i] for i in combo), n))
        w('\n')
        w('### Most-duplicated instances\n\n')
        w('| type | id | copies |\n| --- | --- | ---: |\n')
        for (t, i), v in sorted(dupes.items(), key=lambda kv: -len(kv[1]))[:25]:
            w('| `%s` | %s | %d |\n' % (t, i, len(v)))
        w('\n')

        w('## Failures\n\n')
        if failures:
            w('| package | problem |\n| --- | --- |\n')
            for rel, why in failures:
                w('| `%s` | %s |\n' % (rel, why))
        else:
            w('None. Every COMBINED_TUNING resource in the install parsed.\n')
        w('\n')

        w('## Structural repairs\n\n')
        if repaired:
            w('Malformed containers that were read anyway, and how.\n\n')
            w('| package | repair |\n| --- | --- |\n')
            for rel, why in repaired:
                w('| `%s` | %s |\n' % (rel, why))
        else:
            w('None needed.\n')


if __name__ == '__main__':
    main()
