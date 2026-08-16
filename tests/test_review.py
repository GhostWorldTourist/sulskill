"""review.py: can it actually read a package?

Three separate bugs once made this tool report packages as clear when it had
read nothing out of them at all:

  * it sniffed for zlib's magic bytes and only knew one of the three that
    real compression levels produce
  * it had no RefPack decoder, and CAS packages are almost entirely RefPack
  * CASP names are UTF-16LE, so an ASCII scan found nothing in exactly the
    packages most worth reading

All three fail the same way - silently, and in the direction of "clear". So
every test here builds a real encoded package and asserts the names come back
out, and one asserts that unreadable input is never called clear.
"""
import os
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402
import review                                                      # noqa: E402


class Decoding(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_zlib_at_every_compression_level(self):
        """The magic-sniffing bug: a zlib stream starts 78 01, 78 9c or 78 da
        depending on level, and the reader only knew one of them."""
        for level in (1, 6, 9):
            with self.subTest(level=level):
                raw = zlib.compress(b'x' * 200, level)
                self.assertEqual(0x78, raw[0])
                path = support.write_pkg(
                    self.tmp, f'z{level}.package',
                    [(support.STBL, 1, support.stbl('DistinctiveName'), 0x5A42)])
                names, unread = review.names_in_package(path)
                self.assertEqual(0, unread)
                self.assertIn('DistinctiveName', names)

    def test_refpack(self):
        """CAS packages are RefPack. Without this decoder they read empty."""
        path = support.write_pkg(
            self.tmp, 'refpack.package',
            [(support.STBL, 1, support.stbl('RefpackedName'), 0xFFFF)])
        names, unread = review.names_in_package(path)
        self.assertEqual(0, unread)
        self.assertIn('RefpackedName', names)

    def test_refpack_back_reference_overlaps(self):
        """Runs are copied a byte at a time because a back-reference may
        overlap the output it is still writing. Copying as a slice truncates."""
        # literal 'ab' via terminator is too short; build: 4 literals then a
        # 2-byte-form back-reference of length 5 at distance 2, which must
        # extend the run rather than copy two bytes.
        stream = bytearray(b'\x10\xfb')
        stream += support.u24(9)                   # uncompressed size only
        stream += bytes([0xE0]) + b'abcd'          # 4 literals
        # 2-byte form: b0 bits - literal count 0, len ((b0&0x1C)>>2)+3,
        # dist ((b0&0x60)<<3)+b1+1. Want len 5 -> (b0&0x1C)>>2 == 2.
        stream += bytes([0x08, 0x01])              # len 5, dist 2
        stream += bytes([0xFC])                    # terminator, 0 literals
        out = review.decompress(bytes(stream))
        self.assertEqual(b'abcdcdcdc', out)

    def test_casp_names_are_utf16(self):
        path = support.write_pkg(
            self.tmp, 'cas.package',
            [(support.CASP, 1, support.casp('yuSkinDetailThing'), 0)])
        names, unread = review.names_in_package(path)
        self.assertEqual(0, unread)
        self.assertIn('yuSkinDetailThing', names)

    def test_real_cas_shape_is_not_empty(self):
        """The actual failure: RefPack-compressed CASP with UTF-16 names.
        Both bugs at once, and the file reported clear."""
        path = support.write_pkg(
            self.tmp, 'realcas.package',
            [(support.CASP, 1, support.casp('cfBodyNudeThing'), 0xFFFF)])
        r = review.inspect(path)
        self.assertGreater(r['names'], 0, 'read nothing from a CAS package')
        self.assertTrue(r['cas_body'])


class NeverFalselyClear(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_undecodable_entry_counts_as_unread(self):
        path = support.write_pkg(
            self.tmp, 'bogus.package',
            [(support.STBL, 1, b'not really encoded', 0x1234)])
        names, unread = review.names_in_package(path)
        self.assertEqual(1, unread)
        self.assertEqual(set(), names)

    def test_empty_package_reports_nothing_read_not_clear(self):
        """inspect() must distinguish 'read it, found nothing bad' from
        'could not read it'. The second is not a clearance."""
        path = support.write_pkg(self.tmp, 'empty.package',
                                 [(support.STBL, 1, b'', 0x1234)])
        r = review.inspect(path)
        self.assertEqual(0, r['names'])
        self.assertGreater(r['unread'], 0)


class MinorDetection(unittest.TestCase):
    """A minor age code only matters on a body part.

    There is an enormous amount of ordinary children's CC. A tool that shouts
    at every 'cf' part is a tool nobody reads, and the signal is lost.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _inspect(self, *names):
        path = support.write_pkg(
            self.tmp, f'{abs(hash(names))}.package',
            [(support.CASP, 1, support.casp(*names), 0)])
        return review.inspect(path)

    def test_ordinary_childrens_clothing_is_not_a_finding(self):
        r = self._inspect('cfTop_CuteDress', 'cfHair_Bob', 'tmBottom_Shorts')
        self.assertTrue(r['cas_minor'], 'age code should still be detected')
        self.assertEqual([], r['cas_body'], 'ordinary child CC flagged')

    def test_body_cc_for_a_minor_is_a_finding(self):
        r = self._inspect('cfBodyNude')
        self.assertTrue(r['cas_body'])

    def test_ea_barefoot_slot_is_not_nudity(self):
        """EA's barefoot slot is literally named Shoes_Nude. It means no
        shoes. Every barefoot child CC would read as a body part."""
        r = self._inspect('cfShoes_Nude')
        self.assertEqual([], r['cas_body'])

    def test_adult_body_cc_is_not_a_minor_finding(self):
        r = self._inspect('yuSkinDetail_Overlay', 'afBodyNude')
        self.assertEqual([], r['cas_body'])


if __name__ == '__main__':
    unittest.main()
