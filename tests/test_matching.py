"""The matcher: does a compiled term actually match the name it was written for?

This is the regression suite for the worst class of bug this gate can have -
a term that is on the list, looks fine in the file, and matches nothing. It
fails silently and forever, and the only symptom is a mod passing that should
not. Five real terms were dead this way before the tokeniser was fixed.

Every term below is invented. Real ones stay hashed - see support.py.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402
import gate                                                        # noqa: E402


class TokenReachability(unittest.TestCase):
    """A tok term must match a name built from that term.

    The shapes here are the ones that broke: a handle mixing letters and
    digits. The tokeniser split on the letter/digit boundary, so 'q7zx'
    became 'q' + '7' + 'zx' and the digest for 'q7zx' was never looked up.
    """

    SHAPES = ['q7zx', 'zz42', 'w9', 'vv7v', 'plainhandle', 'mix3d9word']

    def test_every_shape_is_reachable(self):
        terms = [f'tok BLOCK {t}' for t in self.SHAPES]
        with support.blocklist(terms):
            dead = [t for t in self.SHAPES
                    if gate.matches(f'{t}_SomeMod.package') != 'BLOCK']
        self.assertEqual([], dead, f'compiled but unmatchable: {dead}')

    def test_reachable_in_several_spellings(self):
        """One mod is spelled many ways on disk. All must hit."""
        with support.blocklist(['tok BLOCK q7zx']):
            for name in ('q7zx_Thing.package',
                         'q7zx Thing.package',
                         '[q7zx] Thing.package',
                         'Thing by q7zx.package',
                         'Q7ZX-Thing-1234-1-0-0-1699999999.package',
                         'Some Folder/q7zx thing.ts4script'):
                with self.subTest(name=name):
                    self.assertEqual('BLOCK', gate.matches(name))

    def test_token_does_not_match_inside_a_longer_run(self):
        """The reason these are tokens and not substrings.

        A short handle as a substring hits innocent mods. 'q7zxtra' is one
        alphanumeric run, so it does not contain the token 'q7zx'.
        """
        with support.blocklist(['tok BLOCK q7zx']):
            self.assertIsNone(gate.matches('q7zxtra_Curtains.package'))
            self.assertIsNone(gate.matches('Deq7zx.package'))


class CreatorTags(unittest.TestCase):
    """auth terms: handles that are also ordinary English words.

    As a bare token such a handle blocks innocent mods that merely use the
    word in a title. It only counts where a creator actually claims the file.
    """

    def setUp(self):
        self.ctx = support.blocklist(['auth BLOCK sunny'])
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)

    def test_claimed_positions_match(self):
        for name in ('sunny_BedroomSet.package',
                     'sunny-BedroomSet.package',
                     '[sunny] Bedroom Set.package',
                     '(sunny) Bedroom Set.package',
                     'Bedroom Set by sunny.package',
                     'Bedroom Set by_sunny.package'):
            with self.subTest(name=name):
                self.assertEqual('BLOCK', gate.matches(name))

    def test_the_word_alone_is_innocent(self):
        for name in ('Sunny Bedroom Set.package',
                     'A Sunny Day Overlay.package',
                     'sunnyside_Kitchen.package'):
            with self.subTest(name=name):
                self.assertIsNone(gate.matches(name))


class Substrings(unittest.TestCase):

    def test_long_name_matches_anywhere(self):
        with support.blocklist(['sub BLOCK exampleblockedmod']):
            self.assertEqual(
                'BLOCK', gate.matches('exampleblockedmod.package'))
            self.assertEqual(
                'BLOCK', gate.matches('[Repack] Example Blocked Mod v3.package'))
            self.assertEqual(
                'BLOCK', gate.matches('zzz_ExampleBlockedMod_FIXED.package'))

    def test_short_substrings_are_refused_at_compile_time(self):
        """A 4-letter substring would match inside ordinary words. The
        compiler rejects it rather than shipping a term that ruins a library."""
        import blocklist_add
        _lines, bad = blocklist_add.compile_terms(['sub BLOCK abcd'])
        self.assertTrue(bad, 'short sub term should have been rejected')


class Tiers(unittest.TestCase):

    def test_block_wins_over_review(self):
        """A name hitting both tiers must refuse hard, not ask for a look."""
        with support.blocklist(['tok BLOCK q7zx', 'tok REVIEW zz42']):
            self.assertEqual('BLOCK', gate.matches('q7zx_zz42_Thing.package'))

    def test_review_is_returned_on_its_own(self):
        with support.blocklist(['tok REVIEW zz42']):
            self.assertEqual('REVIEW', gate.matches('zz42_Thing.package'))

    def test_clean_name_is_none(self):
        with support.blocklist(['tok BLOCK q7zx', 'sub BLOCK exampleblockedmod']):
            for name in ('Better Exceptions.ts4script',
                         'MCCC Command Center.package',
                         'cfTop_CuteDress.package',
                         'Weather Realism Overhaul 2.1.6.package'):
                with self.subTest(name=name):
                    self.assertIsNone(gate.matches(name))


class Normalisation(unittest.TestCase):

    def test_collapses_the_ways_a_name_appears_on_disk(self):
        self.assertEqual('examplemod', gate._norm('Example_Mod'))
        self.assertEqual('examplemod', gate._norm('[Example] Mod'))
        self.assertEqual('examplemod', gate._norm('example-mod'))
        self.assertEqual('examplemod1234100', gate._norm(
            'Example Mod-1234-1-0-0'))

    def test_tokens_cover_both_granularities(self):
        t = gate._tokens('q7zx_Thing')
        self.assertIn('q7zx', t, 'letter/digit run must survive as one token')
        self.assertIn('thing', t)

    def test_camel_case_is_split(self):
        self.assertIn('wild', gate._tokens('wildGuy'))
        self.assertIn('guy', gate._tokens('wildGuy'))


if __name__ == '__main__':
    unittest.main()
