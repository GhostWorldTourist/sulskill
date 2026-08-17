"""SimData: hashes and pointers that are wrong without ever raising.

Two quiet failures, both found by measuring against the base game rather than
by anything going bang:

  - A name hash computed the wrong way returns a plausible 32- or 64-bit
    number. The package builds, the resource is written, and the game simply
    never finds it under the name it claims. FNV-1a matches 0 of 20,351 EA
    names; FNV-1 over the lowercased name matches 28,703 of 28,703 SimData
    columns. `fnv64` shipped as FNV-1a over the original casing - wrong twice
    - with a docstring inviting callers to use it for instance ids.
  - A null pointer read as an ordinary offset resolves to an address about
    2 GB below the buffer. `_rel` knew only -1, but the format's null is
    0x80000000, so table names decoded as fragments and schema pointers landed
    outside the resource. Nothing raised; parse() just returned nonsense for
    the tables that had no schema.

Written from the design: the format facts asserted here are the ones stated in
simdata.py's own module docstring and in the base-game format notes, not
whatever the implementation happened to do.
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402,F401

sys.path.insert(0, os.path.join(support.ROOT, 'sulskill-modbuild', 'scripts'))
import simdata                                                     # noqa: E402


def fnv1a32(s):
    """The wrong variant, for contrast: xor THEN multiply, original casing."""
    h = 0x811C9DC5
    for b in s.encode('utf-8'):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


class NameHashes(unittest.TestCase):

    def test_fnv32_matches_a_real_stored_value(self):
        """The anchor from the module docstring, measured off a real resource."""
        self.assertEqual(simdata.fnv32('PECO:trait_isCindyRotique'), 0xD736EE1D)

    def test_fnv32_is_not_fnv1a(self):
        name = 'PECO:trait_isCindyRotique'
        self.assertNotEqual(simdata.fnv32(name), fnv1a32(name))

    def test_hashes_lowercase_the_name(self):
        self.assertEqual(simdata.fnv32('AbC'), simdata.fnv32('abc'))
        self.assertEqual(simdata.fnv64('AbC'), simdata.fnv64('abc'))

    def test_fnv64_is_fnv1_multiply_then_xor(self):
        """Same rule as fnv32, widened - not FNV-1a, which is what shipped."""
        h = 0xCBF29CE484222325
        for b in 'demo:trait_demo'.encode('utf-8'):
            h = ((h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF) ^ b
        self.assertEqual(simdata.fnv64('demo:trait_demo'),
                         h | 0x8000000000000000)

    def test_fnv64_marks_mod_authorship(self):
        self.assertTrue(simdata.fnv64('demo:trait_demo') & 0x8000000000000000)


class NullPointers(unittest.TestCase):

    def test_the_format_null_resolves_to_none(self):
        """0x80000000, not -1, is the null this format uses."""
        data = struct.pack('<i', -0x80000000)
        self.assertIsNone(simdata._rel(data, 0))

    def test_minus_one_also_resolves_to_none(self):
        data = struct.pack('<i', -1)
        self.assertIsNone(simdata._rel(data, 0))

    def test_an_ordinary_offset_is_self_relative(self):
        """A pointer at P holding V points at P + V, not at V."""
        data = b'\x00\x00\x00\x00' + struct.pack('<i', 8)
        self.assertEqual(simdata._rel(data, 4), 12)

    def test_a_null_name_does_not_decode_garbage(self):
        self.assertIsNone(simdata._cstr(b'whatever', None))


class ParseExposesEnoughToReadAValue(unittest.TestCase):
    """Describing a resource is not the same as being able to read one."""

    def setUp(self):
        try:
            self.blob = simdata.build_trait('demo:trait_demo')
        except (KeyError, OSError) as exc:      # schema reference not extracted
            self.skipTest('no EA schema available: %s' % exc)
        self.parsed = simdata.parse(self.blob)

    def test_tables_carry_a_row_offset(self):
        for t in self.parsed['tables']:
            self.assertIn('row_pos', t)

    def test_the_row_offset_lands_inside_the_resource(self):
        for t in self.parsed['tables']:
            if t['row_pos'] is None:
                continue
            end = t['row_pos'] + t['row_size'] * t['row_count']
            self.assertGreater(t['row_pos'], 0)
            self.assertLessEqual(end, len(self.blob))

    def test_tables_carry_a_schema_offset(self):
        for t in self.parsed['tables']:
            self.assertIn('schema_pos', t)


if __name__ == '__main__':
    unittest.main()
