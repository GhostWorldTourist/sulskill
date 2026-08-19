"""Whole-install STBL extraction, on top of the repo's existing readers.

The parser and the RefPack decoder already exist and are correct:
``sulskill-modbuild/scripts/stbl.py`` and ``refpack.py``. This module imports
them rather than forking them. Everything here is what those two do not do.

WHAT WAS ADDED, AND WHY

* **Coverage.** ``stbl.load_game_strings()`` reads exactly one file,
  ``Data/Client/Strings_ENG_US.package``. That is the base-game client table
  and nothing else - no expansion, game or stuff pack, and no ``Delta``
  patches. It is a fine answer for "what does the base game call this", and
  the wrong answer for mod diagnosis, where the buff being overridden is as
  likely to come from EP08 as from the base game. Each ``Strings_<LOCALE>``
  package holds exactly one STBL, so that call returns 58,312 strings; walking
  the install's 228 such packages returns 166,673. Roughly two of every three
  strings in the game are invisible to the single-file reader.

* **Delta ordering.** ``Delta\\<PACK>`` patches ``<PACK>`` and must be merged
  after it. A plain path sort puts Delta first (``D`` < ``E``) and the stale
  text wins. Measured on EP01: 133 of 4485 English keys differ between the two,
  and the Delta side is the corrected one - 0x88B37572 is
  'Retail Lot name Placeholder' in ``EP01`` and 'Magnolia Promenade' in
  ``Delta\\EP01``.

* **Locale.** The language is the top byte of the 64-bit instance id; the group
  is always 0 and carries nothing. Neither repo module looks at the instance at
  all, because within one ``Strings_<LOCALE>.package`` it does not need to.
  Walking the install it does: a caller pointed at a mods folder will otherwise
  merge 24 languages into one dict.

* **Strict decoding and a failure count.** The repo parser decodes with
  ``errors='replace'``, which is the right call for a tool that must not lose
  58k strings to one bad byte, but it means a corrupt table is indistinguishable
  from a clean one. Here the default is ``strict`` so the extraction can state
  that nothing failed. It does not: all 268,069 entries decode as clean UTF-8.

RESOURCE TYPE. 0x220557DA, confirmed from payloads, not from a table.
``sims4.resources.Types`` has no name for it - string tables are loaded
engine-side and never reach the Python layer, so ``restypes`` cannot help.
Every resource of this type in the install decompresses to a blob whose first
four bytes are ``STBL``.

COMPRESSION. Three codecs, all present: 188 RefPack (0xFFFF), 39 stored
(0x0000), 1 zlib (0x5A42). A RefPack-unaware reader does not raise on those
188 - it returns compressed bytes that parse as noise.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import struct

import dbpf_index

# The readers live in the checkout, next to the gate that this tree already
# located. Importing them from there keeps one copy of the format knowledge.
_REPO = _os.path.dirname(_os.path.dirname(
    _sys.modules['_sulskill_gate'].__file__))
_SCRIPTS = _os.path.join(_REPO, 'sulskill-modbuild', 'scripts')
if _SCRIPTS not in _sys.path:
    _sys.path.insert(0, _SCRIPTS)
import refpack                                            # noqa: E402


def _load_repo_stbl():
    """The repo module is also called 'stbl'. Import it by path, under another
    name, or a plain `import stbl` from another track gets this module back at
    half-initialised and the collision is silent."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        '_sulskill_repo_stbl', _os.path.join(_SCRIPTS, 'stbl.py'))
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_repo_stbl = _sys.modules.get('_sulskill_repo_stbl') or _load_repo_stbl()

STBL = _repo_stbl.T_STBL                                  # 0x220557DA
MAGIC = _repo_stbl.MAGIC
HEADER = _repo_stbl.HEADER_SIZE                           # 21

COMPRESS_REFPACK = 0xFFFF
COMPRESS_NONE = 0x0000

#: instance-id top byte -> locale. Established from mod packages that ship the
#: full set: 43,551 tables in the user's Mods folder, high bytes 0x00-0x17 with
#: ~2,460 tables each. The base install carries only 0x00.
LANGUAGES = {
    0x00: 'ENG_US', 0x01: 'CHS', 0x02: 'CHT', 0x03: 'CZE', 0x04: 'DAN',
    0x05: 'DUT', 0x06: 'FIN', 0x07: 'FRE', 0x08: 'GER', 0x09: 'GRE',
    0x0A: 'HUN', 0x0B: 'ITA', 0x0C: 'JPN', 0x0D: 'KOR', 0x0E: 'NOR',
    0x0F: 'POL', 0x10: 'POR', 0x11: 'PTB', 0x12: 'RUS', 0x13: 'SPA',
    0x14: 'SWE', 0x15: 'THA', 0x16: 'ESP_MX', 0x17: 'ENG_GB',
}

ENGLISH = 0x00

StblError = ValueError


def language(instance):
    """Locale byte of an STBL instance id."""
    return (instance >> 56) & 0xFF


def language_name(instance):
    b = language(instance)
    return LANGUAGES.get(b, '0x%02X' % b)


def parse(blob, errors='strict'):
    """Yield (key, text). The repo parser with the decode mode exposed.

    ``_repo_stbl.parse`` is fixed at errors='replace' and returns a dict, which
    hides both bad bytes and duplicate keys within one table. The walk is
    identical - u32 key, u8 flags, u16 byte length, UTF-8 text, packed.
    """
    if blob[:4] != MAGIC:
        raise StblError('not an STBL: %r - almost certainly still compressed'
                        % blob[:4])
    version = struct.unpack_from('<H', blob, 4)[0]
    if version != 5:
        raise StblError('unsupported STBL version %d' % version)
    count = struct.unpack_from('<Q', blob, 7)[0]
    p, n = HEADER, len(blob)
    for k in range(count):
        if p + 7 > n:
            raise StblError('truncated header at entry %d of %d' % (k, count))
        key, _flags, ln = struct.unpack_from('<IBH', blob, p)
        p += 7
        if p + ln > n:
            raise StblError('entry 0x%08X runs past end of resource' % key)
        yield key, blob[p:p + ln].decode('utf-8', errors)
        p += ln


def tables(path):
    """Yield (instance, decompressed_bytes) for every STBL in a package.

    Unlike ``_repo_stbl.read_stbls`` this keeps the instance id, which is where
    the locale lives.
    """
    ents = [(o, fz, c, i) for t, g, i, o, fz, c
            in dbpf_index.index(path) if t == STBL]
    if not ents:
        return
    ents.sort()
    with open(path, 'rb') as f:
        for off, fsz, comp, inst in ents:
            f.seek(off)
            yield inst, refpack.maybe_decompress(f.read(fsz), comp)


def packages(root):
    """Every .package under root, in merge order - later overrides earlier."""
    out = []
    for d, _dirs, files in _os.walk(root):
        for f in files:
            if f.lower().endswith('.package'):
                out.append(_os.path.join(d, f))
    delta = _os.path.join(root, 'Delta') + _os.sep
    out.sort(key=lambda p: (p.startswith(delta), p))
    return out


def load(root, lang=ENGLISH, errors='strict'):
    """(strings, stats) for one locale across every package under root.

    stats carries tables/entries/duplicates/conflicts/failures so the caller can
    report the shape of the extraction instead of asserting it went fine.
    """
    strings = {}
    stats = {'tables': 0, 'entries': 0, 'duplicates': 0, 'conflicts': 0,
             'packages': 0, 'failures': []}
    for path in packages(root):
        hit = False
        try:
            for inst, blob in tables(path):
                if language(inst) != lang:
                    continue
                hit = True
                stats['tables'] += 1
                try:
                    for key, text in parse(blob, errors):
                        stats['entries'] += 1
                        if key in strings:
                            stats['duplicates'] += 1
                            if strings[key] != text:
                                stats['conflicts'] += 1
                        strings[key] = text
                except (StblError, UnicodeDecodeError) as e:
                    stats['failures'].append('%s 0x%016X: %s'
                                             % (path, inst, e))
        except Exception as e:                                # noqa: BLE001
            stats['failures'].append('%s: %s' % (path, e))
        stats['packages'] += hit
    return strings, stats


def locales(root):
    """{locale_byte: table_count} present under root."""
    counts = {}
    for path in packages(root):
        try:
            for t, g, i, o, fz, c in dbpf_index.index(path):
                if t == STBL:
                    b = (i >> 56) & 0xFF
                    counts[b] = counts.get(b, 0) + 1
        except Exception:                                     # noqa: BLE001
            pass
    return counts


def _tree():
    return _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))


# --------------------------------------------------------------------------
# Tuning -> string. The point of the whole track.
#
# THE LINKAGE IS NOT A HASH AT LOOKUP TIME. This was the expectation going in
# and the data says otherwise. A display name is a TunableLocalizedString, and
# sims4/localization/__init__.pyc shows its _convert_to_value is `int(value)` -
# no hashing, no indirection. The tuning stores the 32-bit STBL key literally:
#
#     <I c="Buff" i="buff" m="buffs.buff" n="Buff_FocusedByPotion" s="26329">
#       <T n="buff_name">0xAB64F94</T>
#
# and 0x0AB64F94 is a key in the table above, holding 'Focused by Potion'.
# Tuning -> text is one dict lookup. There is nothing to reverse.
#
# The hash EA does use is FNV-1 32-bit over the LOWERCASED name - multiply
# then xor, not FNV-1a. Verified against EA's own SimData in
# SimulationFullBuild0: 28,703 of 28,703 column names and 4,002 of 4,002 named
# tables reproduce their stored hash. FNV-1a scores 0 of 34,611. It is not what
# produces STBL keys, though: EA's keys come from string identifiers in a
# localisation pipeline that does not ship, and the keys are uniform over the
# full 32-bit range with no recoverable preimage.
#
# Two forms a value can take in merged tuning, and a reader that handles only
# the first loses about 40% of them:
#     <T n="display_name">0xC1D2E3F4</T>        inline
#     <r n="display_name" x="1162" />           pooled - slot 1162 of the
#                                               <g s="merged"> constant pool
# --------------------------------------------------------------------------

COMBINED_TUNING = 0x62E94D38

import re                                                  # noqa: E402

_I = re.compile(r'<I ([^>]*)>(.*?)</I>', re.S)
_ATTR = re.compile(r'(\w+)="([^"]*)"')
_POOL_SCALAR = re.compile(r'<T x="(\d+)">([^<]*)</T>')
_INLINE = re.compile(r'<T n="([^"]+)">([^<]*)</T>')
_POOLED = re.compile(r'<r n="([^"]+)" x="(\d+)"\s*/>')

#: Field that holds the player-visible name, most specific first. Taken from a
#: field census over SimulationFullBuild0, not from guesswork: traits and
#: interactions use display_name, buffs use buff_name, skills stat_name, and so
#: on. First hit wins.
NAME_FIELDS = ('display_name', 'buff_name', 'stat_name', 'trait_name',
               '_display_name', 'pie_menu_name', 'name', 'display_text',
               'title', 'template_name', 'text', 'TagLocalizedName')

#: Same, for the sentence under the name.
DESC_FIELDS = ('buff_description', 'trait_description', 'recipe_description',
               'situation_description', 'skill_description',
               'locked_description', 'level_description', 'description',
               'descriptive_text', 'title_description', 'tooltip', '_tooltip')


def tuning_type_ids():
    """{tuning type name as it appears in <I i="...">: resource type id}."""
    import restypes
    _binary, tuning = restypes.load()
    out = {}
    for _member, d in tuning.items():
        rt = d.get('resource_type')
        nm = d.get('name')
        if rt and nm:
            out[nm] = rt
    return out


def constant_pool(text):
    """{slot: text} for the scalar slots of a merged-tuning constant pool.

    Only ``<T x="N">value</T>`` slots, which is all a name reference can point
    at. Expanding a whole instance is Track B's job and needs far more.
    """
    end = text.find('</g>')
    if end < 0:
        end = len(text)
    return {int(m.group(1)): m.group(2)
            for m in _POOL_SCALAR.finditer(text, 0, end)}


def instance_strings(text, strings, types=None):
    """Yield one dict per <I> that has a resolvable name or description.

    text is a decompressed COMBINED_TUNING resource, decoded. strings is the
    {key: text} map from load(). Values that are not valid keys are reported in
    'unresolved' rather than dropped, so a caller can see the miss rate.
    """
    types = types or {}
    pool = constant_pool(text)
    body_start = text.find('</g>')
    for m in _I.finditer(text, body_start if body_start > 0 else 0):
        at = dict(_ATTR.findall(m.group(1)))
        body = m.group(2)
        found, unresolved = {}, []
        for field, raw in _INLINE.findall(body):
            _collect(field, raw, strings, found, unresolved)
        for field, slot in _POOLED.findall(body):
            _collect(field, pool.get(int(slot), ''), strings, found,
                     unresolved)
        if not found:
            continue
        rec = {
            'tuning_type': at.get('i'),
            'type_id': types.get(at.get('i')),
            'instance': int(at.get('s', 0)),
            'name': at.get('n'),
            'class': at.get('c'),
            'module': at.get('m'),
        }
        for label, fields in (('display', NAME_FIELDS),
                              ('description', DESC_FIELDS)):
            for f in fields:
                if f in found:
                    key, txt = found[f]
                    rec[label + '_key'] = '0x%08X' % key
                    rec[label] = txt
                    rec[label + '_field'] = f
                    break
        if unresolved:
            rec['unresolved'] = unresolved
        if 'display' in rec or 'description' in rec:
            yield rec


def _collect(field, raw, strings, found, unresolved):
    if not raw.startswith('0x') or field in found:
        return
    try:
        key = int(raw, 16)
    except ValueError:
        return
    if key > 0xFFFFFFFF:
        return
    text = strings.get(key)
    if text is None:
        unresolved.append('%s=%s' % (field, raw))
    else:
        found[field] = (key, text)


def build_names(root, strings=None, skipped=None):
    """Walk every COMBINED_TUNING in the install; yield instance_strings recs.

    COVERAGE, STATED PLAINLY. Only 3 of the install's 276 COMBINED_TUNING
    resources are the text XML this reads. The other 273 are SimData
    ('DATA' magic) holding a PackedXmlDocument - a binary DOM with schemas
    PackedXmlDocument / PackedXmlNode / PackedXmlAttribute over a NUL-separated
    string pool. The names are in there, but reaching them needs a SimData row
    reader, which is the merged-tuning reader Track B owns. Until that exists
    this covers the base game (20,351 instances), GP01 (1,448) and FP01 (42),
    and nothing from EP01-EP21 or the other packs.

    Do not paper over this by pattern-matching the packed pool: a field name is
    interned once per document, so 'buff_name' appears exactly once in a
    4.3 MB EP04 document against 2,859 string keys. Adjacency recovers one buff
    and mis-attributes the rest.

    skipped, if given a list, collects the packed resources passed over.
    """
    strings = strings if strings is not None else load(root)[0]
    types = tuning_type_ids()
    for path in packages(root):
        ents = [(o, fz, c) for t, g, i, o, fz, c
                in dbpf_index.index(path) if t == COMBINED_TUNING]
        if not ents:
            continue
        src = _os.path.relpath(path, root)
        with open(path, 'rb') as f:
            for off, fsz, comp in sorted(ents):
                f.seek(off)
                blob = refpack.maybe_decompress(f.read(fsz), comp)
                if blob[:4] != b'<com':
                    if skipped is not None:
                        skipped.append((src, blob[:4], len(blob)))
                    continue
                text = blob.decode('utf-8', 'replace')
                for rec in instance_strings(text, strings, types):
                    rec['package'] = src
                    yield rec


class Names:
    """Loaded out/display_names.jsonl, indexed for lookup.

    This is the thing mod diagnosis actually calls:

        names = Names.load()
        names.of(0x6017E896, 26329)['display']   -> 'Focused by Potion'
    """

    def __init__(self, records):
        self.records = records
        self.by_id = {}
        self.by_name = {}
        for r in records:
            self.by_id[(r.get('type_id'), r['instance'])] = r
            self.by_id.setdefault((None, r['instance']), r)
            if r.get('name'):
                self.by_name[r['name'].lower()] = r

    @classmethod
    def load(cls, path=None):
        import json
        path = path or _os.path.join(_tree(), 'out', 'display_names.jsonl')
        with open(path, encoding='utf-8') as f:
            return cls([json.loads(line) for line in f if line.strip()])

    def of(self, type_id, instance):
        """Record for a tuning instance, or None. type_id may be None."""
        return (self.by_id.get((type_id, instance))
                or self.by_id.get((None, instance)))

    def display(self, type_id, instance, default=None):
        r = self.of(type_id, instance)
        return r.get('display', default) if r else default

    def lookup(self, tuning_name):
        return self.by_name.get(tuning_name.lower())


def load_english(root=None):
    """{key: text} for the whole install. Convenience for other tracks."""
    return load(root or _os.environ.get('TS4_INSTALL') or gate.game_dir())[0]


if __name__ == '__main__':
    import io
    import json
    _sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8',
                                   errors='replace')
    root = _os.environ.get('TS4_INSTALL') or gate.game_dir()
    strings, stats = load(root)
    out = _os.path.join(_tree(), 'out')
    _os.makedirs(out, exist_ok=True)
    dest = _os.path.join(out, 'strings_en.jsonl')
    with open(dest, 'w', encoding='utf-8', newline='\n') as f:
        for key in sorted(strings):
            f.write(json.dumps({'key': '0x%08X' % key, 'text': strings[key]},
                               ensure_ascii=False) + '\n')
    print('packages    %d' % stats['packages'])
    print('tables      %d' % stats['tables'])
    print('entries     %d' % stats['entries'])
    print('unique keys %d' % len(strings))
    print('duplicates  %d (%d where the text differs)'
          % (stats['duplicates'], stats['conflicts']))
    print('failures    %d' % len(stats['failures']))
    for m in stats['failures']:
        print('  ' + m)
    print('wrote %s' % dest)

    dest2 = _os.path.join(out, 'display_names.jsonl')
    n = named = described = unres = 0
    skipped = []
    with open(dest2, 'w', encoding='utf-8', newline='\n') as f:
        for rec in build_names(root, strings, skipped):
            n += 1
            named += 'display' in rec
            described += 'description' in rec
            unres += len(rec.get('unresolved', ()))
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print()
    print('tuning instances with text  %d' % n)
    print('  with a display name       %d' % named)
    print('  with a description        %d' % described)
    print('  values that look like a key but are not in the '
          'English table: %d' % unres)
    print('  COMBINED_TUNING resources skipped as packed binary: %d'
          % len(skipped))
    print('    (SimData/PackedXmlDocument - needs Track B, see build_names)')
    print('wrote %s' % dest2)
