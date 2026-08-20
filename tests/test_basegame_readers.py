"""The readers underneath the base-game index.

These are the format readers every other claim rests on: if the DBPF walker
skips entries, or a codec silently returns still-compressed bytes, or a locale
is read from the wrong byte, then everything built on top is confidently wrong
and nothing raises. That is the failure class here - not crashes, but readers
that return *something*.

Written from the documented format rules in `sulskill/BASEGAME.md`, not from
these implementations:

  - A resource payload is zlib, RefPack, or stored, and a codec the reader does
    not know must RAISE. Returning the compressed bytes hands the caller
    plausible-looking garbage it cannot detect.
  - Locale is the top byte of the 64-bit string-table instance id.
  - Name hashing is FNV-1 - multiply THEN xor. FNV-1a matches 0 of 20,351 EA
    names, and the two differ only in operation order, so a test that does not
    pin the order does not pin anything.
  - Every SimData offset is self-relative, and the row-data offset at table
    record + 20 is what makes values readable at all.
  - A builder that cannot find the game must say so, not write an empty index
    that looks like a successful build.

Nothing here reads the real Sims 4 install.
"""
import contextlib
import importlib
import io
import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402,F401

SCRIPTS = os.path.join(support.ROOT, 'sulskill-basegame', 'scripts')
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(support.ROOT, 'sulskill-modbuild', 'scripts'))

import dbpf_index                                                  # noqa: E402
import combinedtuning                                              # noqa: E402
import mergedtuning                                                # noqa: E402
import resourcecfg                                                 # noqa: E402
import simdata_values                                              # noqa: E402
import stbl as bg_stbl                                             # noqa: E402


def fnv1a32(s):
    """The wrong variant, for contrast: xor THEN multiply."""
    h = 0x811C9DC5
    for b in s.encode('utf-8'):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def stbl_blob(entries):
    """A real STBL: magic, version 5, count at 7, then key/flags/len/UTF-8."""
    body = b''
    for key, text in entries:
        raw = text.encode('utf-8')
        body += struct.pack('<IBH', key, 0, len(raw)) + raw
    head = bytearray(bg_stbl.HEADER)
    head[0:4] = bg_stbl.MAGIC
    struct.pack_into('<H', head, 4, 5)
    struct.pack_into('<Q', head, 7, len(entries))
    return bytes(head) + body


class ResourcePayloads(unittest.TestCase):
    """Every entry, and every codec, or the index is quietly short."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.payloads = [b'stored payload', b'zlib payload' * 40,
                         b'refpack payload' * 12]
        self.pkg = support.write_pkg(self.tmp, 'x.package', [
            (0x0333406C, 1, self.payloads[0], 0),
            (0x0333406C, 2, self.payloads[1], 0x5A42),
            (0x0333406C, 3, self.payloads[2], 0xFFFF),
        ])

    def test_every_entry_is_indexed(self):
        self.assertEqual(len(list(dbpf_index.index(self.pkg))), 3)

    def test_the_64_bit_instance_id_is_reassembled(self):
        ids = sorted(e[2] for e in dbpf_index.index(self.pkg))
        self.assertEqual(ids, [1, 2, 3])

    def test_all_three_codecs_decode_to_the_original(self):
        got = {}
        for t, g, i, off, sz, comp in dbpf_index.index(self.pkg):
            got[i] = list(dbpf_index.fetch(self.pkg, [(off, sz, comp)]))[0]
        self.assertEqual(got[1], self.payloads[0])
        self.assertEqual(got[2], self.payloads[1])
        self.assertEqual(got[3], self.payloads[2])

    def test_an_unknown_codec_raises_rather_than_returning_junk(self):
        """The failure this guards produces plausible-looking garbage, not an
        obvious error - a caller that gets an exception can fix it, a caller
        that gets noise usually cannot tell."""
        with self.assertRaises(Exception):
            dbpf_index.decode(b'not really compressed', 0x1234)

    def test_stored_bytes_come_back_unchanged(self):
        self.assertEqual(dbpf_index.decode(b'plain', 0), b'plain')

    def test_zlib_round_trips(self):
        self.assertEqual(dbpf_index.decode(zlib.compress(b'hello'), 0x5A42),
                         b'hello')


class StringTables(unittest.TestCase):

    def test_locale_is_the_top_byte_of_the_instance_id(self):
        """Documented rule. Reading it from anywhere else silently attributes
        every string to the wrong language."""
        self.assertEqual(bg_stbl.language(0x0012345678ABCDEF), 0x00)
        self.assertEqual(bg_stbl.language(0x0712345678ABCDEF), 0x07)

    def test_english_is_locale_zero(self):
        self.assertEqual(bg_stbl.ENGLISH, 0x00)

    def test_entries_round_trip(self):
        entries = [(0x0000C3E4, 'a line of text'), (0x00001234, 'another')]
        self.assertEqual(list(bg_stbl.parse(stbl_blob(entries))), entries)

    def test_non_ascii_survives(self):
        entries = [(1, 'café — dash')]
        self.assertEqual(list(bg_stbl.parse(stbl_blob(entries))), entries)

    def test_a_still_compressed_blob_is_refused_by_name(self):
        """The most common mistake with these is forgetting to decompress, and
        the reader has to say so rather than yield nonsense."""
        with self.assertRaises(Exception) as raised:
            list(bg_stbl.parse(zlib.compress(stbl_blob([(1, 'x')]))))
        self.assertIn('compressed', str(raised.exception).lower())

    def test_a_truncated_table_is_refused(self):
        blob = stbl_blob([(1, 'abcdefgh')])
        with self.assertRaises(Exception):
            list(bg_stbl.parse(blob[:-4]))


class NameHashing(unittest.TestCase):

    def test_fnv32_is_fnv1_not_fnv1a(self):
        """They differ only in operation order, so pinning the value against a
        hand-computed FNV-1 is the only assertion that pins anything."""
        name = 'peco:trait_iscindyrotique'
        h = 0x811C9DC5
        for b in name.encode('utf-8'):
            h = ((h * 0x01000193) & 0xFFFFFFFF) ^ b
        self.assertEqual(combinedtuning.fnv32(name), h)

    def test_fnv32_differs_from_fnv1a(self):
        name = 'peco:trait_iscindyrotique'
        self.assertNotEqual(combinedtuning.fnv32(name), fnv1a32(name))


class CombinedTuningEncoding(unittest.TestCase):
    """Only three of 276 combined-tuning resources are text XML. A reader that
    cannot tell them apart samples the readable 1% and generalises."""

    TEXT = (b'<combinedTuning><R n="camera">'
            b'<I c="T" i="camera" n="x" s="1"/></R></combinedTuning>')
    PACKED = b'DATA' + b'\x01\x01\x00\x00' + b'\x00' * 64

    def test_the_text_form_is_recognised(self):
        self.assertTrue(combinedtuning.is_text(self.TEXT))
        self.assertFalse(combinedtuning.is_packed(self.TEXT))

    def test_the_packed_form_is_recognised(self):
        self.assertTrue(combinedtuning.is_packed(self.PACKED))
        self.assertFalse(combinedtuning.is_text(self.PACKED))

    def test_neither_form_claims_arbitrary_bytes(self):
        junk = b'\x00\x01\x02\x03 not either form \xff\xfe'
        self.assertFalse(combinedtuning.is_text(junk))
        self.assertFalse(combinedtuning.is_packed(junk))

    def test_mergedtuning_agrees_on_which_form_is_packed(self):
        self.assertTrue(mergedtuning.is_packed(self.PACKED))
        self.assertFalse(mergedtuning.is_packed(self.TEXT))


class ResourceCfg(unittest.TestCase):

    def write(self, text):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, 'Resource.cfg')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def test_directives_keep_file_order(self):
        """Rule order within a priority decides which of two matching mods
        wins, so it is preserved even though it looks like a detail."""
        path = self.write('Priority 500\n'
                          'PackedFile *.package\n'
                          'PackedFile */*.package\n')
        rules = [r[2] for r in resourcecfg.parse(path)]
        self.assertEqual(rules, ['*.package', '*/*.package'])

    def test_priority_applies_to_what_follows_it(self):
        path = self.write('Priority 500\nPackedFile a.package\n'
                          'Priority 501\nPackedFile b.package\n')
        got = {r[2]: r[0] for r in resourcecfg.parse(path)}
        self.assertEqual(got['a.package'], 500)
        self.assertEqual(got['b.package'], 501)

    def test_comments_and_blank_lines_are_ignored(self):
        path = self.write('# a comment\n\nPriority 500\n'
                          'PackedFile a.package  # trailing\n')
        self.assertEqual(len(resourcecfg.parse(path)), 1)


class SimDataOffsets(unittest.TestCase):
    """Every offset is self-relative and 0x80000000 is null. Getting either
    wrong yields values that look like data."""

    def blob(self):
        import simdata as mb                      # the modbuild writer
        try:
            return mb.build_trait('demo:trait_demo')
        except (KeyError, OSError) as exc:
            self.skipTest('no EA schema available: %s' % exc)

    def test_parse_resolves_a_usable_row_data_offset(self):
        """Asserting only that the key exists passes when the value is None,
        which is the same as not reading the offset at all - the bug this
        parser was written to fix. At least one table must resolve."""
        parsed = simdata_values.parse(self.blob())
        offsets = [t['data_offset'] for t in parsed['tables']]
        self.assertTrue(any(o is not None for o in offsets),
                        'no table resolved its row-data offset')

    def test_the_row_offset_lands_inside_the_resource(self):
        data = self.blob()
        parsed = simdata_values.parse(data)
        checked = 0
        for table in parsed['tables']:
            if table['data_offset'] is None:
                continue
            self.assertGreater(table['data_offset'], 0)
            self.assertLessEqual(table['data_offset'], len(data))
            checked += 1
        self.assertGreater(checked, 0, 'nothing was actually checked')

    def test_a_table_resolves_its_schema(self):
        parsed = simdata_values.parse(self.blob())
        self.assertTrue(any(t.get('schema') for t in parsed['tables']))

    def test_something_that_is_not_simdata_is_refused(self):
        with self.assertRaises(ValueError):
            simdata_values.parse(b'NOPE' + b'\x00' * 64)


class BuildersRefuseWithoutTheGame(unittest.TestCase):
    """An empty index that looks like a successful build is the worst outcome
    here: every later query returns 'not found' and reads as fact."""

    MODULES = ('build_instances', 'build_packages', 'build_packs',
               'build_python_api', 'build_simdata_schemas')

    def test_each_builder_fails_rather_than_writing_an_empty_index(self):
        """main() takes no arguments here. Calling it with one raises TypeError,
        and an assertion that treats any exception as a refusal then passes no
        matter what the builder does - so the call has to be right, and only a
        deliberate refusal counts."""
        import inspect
        tmp = tempfile.mkdtemp()
        nowhere = os.path.join(tmp, 'no-game-here')
        bad = []
        for name in self.MODULES:
            with support.environment(SULSKILL_OUT=tmp, TS4_INSTALL=nowhere):
                mod = importlib.import_module(name)
                importlib.reload(mod)
                self.assertEqual(
                    len(inspect.signature(mod.main).parameters), 0,
                    '%s.main changed shape; this test calls it wrongly' % name)
                buf = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buf), \
                            contextlib.redirect_stderr(buf):
                        code = mod.main()
                except SystemExit as exc:
                    code = exc.code if exc.code else 'refused'
                except (OSError, ValueError, KeyError, RuntimeError):
                    code = 'refused'          # a real failure to find the game
                if code in (0, None):
                    bad.append(name)
        self.assertEqual(bad, [], 'these reported success with no game '
                                  'installed: %s' % ', '.join(bad))


class BytecodeHelpers(unittest.TestCase):
    """Pure functions over the game's compiled Python, testable without it."""

    def test_an_archive_name_becomes_a_dotted_module(self):
        import pyapi
        self.assertEqual(pyapi.module_of(None, 'sims4/tuning/instance_manager.pyc'),
                         'sims4.tuning.instance_manager')

    def test_backslash_separators_are_handled_too(self):
        import pyapi
        self.assertEqual(pyapi.module_of(None, 'sims4\\resources.pyc'),
                         'sims4.resources')

    def test_a_class_body_is_identified_by_its_first_two_names(self):
        import pyapi

        class Stub:
            names = ('__name__', '__module__', 'whatever')

        class NotAClass:
            names = ('print', 'range')

        self.assertTrue(pyapi.is_class_body(Stub))
        self.assertFalse(pyapi.is_class_body(NotAClass))


class ReadersRefuseWithoutTheGame(unittest.TestCase):
    """These read the game's own archives. Without them the answer must be an
    error, never an empty mapping - an empty type table makes every resource
    read as an unknown type, which looks like data."""

    def test_restypes_raises_rather_than_returning_an_empty_table(self):
        import restypes
        tmp = tempfile.mkdtemp()
        with support.environment(TS4_INSTALL=os.path.join(tmp, 'no-game')):
            importlib.reload(restypes)
            with self.assertRaises(Exception):
                restypes.type_names()

    def test_the_tuning_schema_builder_exits_non_zero_without_a_game(self):
        """It is straight-line rather than a main(), so it is checked the way
        the repo checks its other straight-line scripts: as a subprocess."""
        import subprocess
        tmp = tempfile.mkdtemp()
        env = dict(os.environ, SULSKILL_OUT=tmp,
                   TS4_INSTALL=os.path.join(tmp, 'no-game'))
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, 'build_tuning_schema.py')],
            capture_output=True, text=True, env=env, timeout=120)
        self.assertNotEqual(proc.returncode, 0)


if __name__ == '__main__':
    unittest.main()
