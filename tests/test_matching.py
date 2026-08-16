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
import unittest.mock

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


class MultiSegmentHandles(unittest.TestCase):
    """A handle spelled with a separator inside it is the same claim.

    'Sunny_Side_Kitchen' and 'SunnySide_Kitchen' name the same author, so a
    matcher that reads only the first segment lets a handle escape by being
    written with an underscore in it - a one-character edit, and the kind of
    near-miss that looks clear and is not.
    """

    def setUp(self):
        self.ctx = support.blocklist(['auth BLOCK sunnyside'])
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)

    def test_the_handle_blocks_however_it_is_spelled(self):
        for name in ('sunnyside_Kitchen.package',
                     'Sunny_Side_Kitchen.package',
                     'Sunny-Side-Kitchen.package',
                     '[Sunny Side] Kitchen.package',
                     'Kitchen by Sunny_Side.package'):
            with self.subTest(name=name):
                self.assertEqual('BLOCK', gate.matches(name))

    def test_a_title_is_still_a_title(self):
        # The whole reason creator tags exist. Spaces separate words in a
        # name; '_' and '-' separate a claim from what is claimed. Accepting
        # a bare space here would block every mod with the phrase in its name.
        for name in ('Sunny Side Kitchen.package',
                     'Sunnyside Diner Recolour.package',
                     'A Sunny Side Up Breakfast.package'):
            with self.subTest(name=name):
                self.assertIsNone(gate.matches(name))

    def test_the_claim_has_to_be_at_the_front(self):
        self.assertIsNone(gate.matches('a_b_sunnyside_Kitchen.package'))

    def test_accumulation_is_bounded(self):
        # gate.PREFIX_SEGS segments, deliberately: without a bound, every
        # prefix of every separator-heavy name becomes a candidate handle and
        # the false-positive rate climbs with name length. A handle sliced
        # finer than that is a known, accepted gap - not an oversight.
        self.assertEqual(3, gate.PREFIX_SEGS)
        self.assertIsNone(gate.matches('sun_ny_si_de_Kitchen.package'))


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
        _lines, bad, _weak = blocklist_add.compile_terms(['sub BLOCK abcd'])
        self.assertTrue(bad, 'short sub term should have been rejected')


class CompileTimeReachability(unittest.TestCase):
    """The compiler puts every term back through the matcher before keeping it.

    This is the only moment it can be asked. Downstream there are only digests,
    and a digest cannot be inverted to find out whether any name would produce
    it - so a dead term stays dead and invisible for the life of the list.
    """

    def setUp(self):
        import blocklist_add
        self.bl = blocklist_add

    def test_a_term_the_tokeniser_cannot_produce_is_rejected(self):
        """The historical bug, reintroduced deliberately.

        Before `_tokens` emitted alphanumeric runs, 'q7zx' was split into
        'q' + '7' + 'zx' and the digest for the whole handle was never looked
        up. The term compiled fine and matched nothing, forever. With the old
        tokeniser back in place the compiler must now refuse it outright.
        """
        import re
        with unittest.mock.patch.object(gate, '_ALNUM', re.compile(r'(?!x)x')):
            lines, bad, _weak = self.bl.compile_terms(['tok BLOCK q7zx'])
        self.assertEqual([], lines, 'a dead term must not reach the list')
        self.assertTrue(bad, 'a term matching nothing must be rejected')
        self.assertIn('dead', bad[0][1])

    def test_the_same_term_is_kept_once_the_tokeniser_can_reach_it(self):
        """The other half of the mutation: unbroken, the term compiles."""
        lines, bad, _weak = self.bl.compile_terms(['tok BLOCK q7zx'])
        self.assertEqual([], bad)
        self.assertEqual(1, len(lines))

    def test_a_dead_term_is_not_rescued_by_a_live_one(self):
        """Each term is verified against itself alone, not against the batch.

        The two terms here are chosen so that they overlap: the probe built for
        the dead token 'q7zx' is "q7zx Mod.package", which normalises to
        something the live substring 'q7zxmod' matches. Verified against the
        whole compiled list, the dead term would be credited with the live
        term's hit and kept - looking reachable while matching nothing on its
        own. Verified alone, it is correctly refused.
        """
        import re
        terms = ['tok BLOCK q7zx', 'sub BLOCK q7zxmod']
        with unittest.mock.patch.object(gate, '_ALNUM', re.compile(r'(?!x)x')):
            lines, bad, _weak = self.bl.compile_terms(terms)
        self.assertEqual(1, len(lines), 'only the reachable term should remain')
        self.assertEqual(1, len(bad))
        self.assertIn('q7zx', bad[0][0])
        self.assertNotIn('q7zxmod', bad[0][0], 'the live term must survive')

    def test_a_spelling_that_normalisation_eats_is_reported_as_weak(self):
        """'wild guy' is reachable, but not written that way.

        Normalisation removes the space, so the digest is for 'wildguy'. A mod
        called "Wild Guy Extras" tokenises to 'wild' and 'guy' and never
        produces it. The term still catches 'WildGuy_Extras', so it is kept -
        but whoever typed it was expecting the other one, and should be told.
        """
        lines, bad, weak = self.bl.compile_terms(['tok BLOCK wild guy'])
        self.assertEqual([], bad)
        self.assertEqual(1, len(lines), 'a weak term is still worth keeping')
        self.assertTrue(weak, 'the spelling gap must be reported')
        self.assertIn('as written', weak[0][1])

    def test_an_ordinary_term_is_reachable_in_every_spelling(self):
        for term in ('tok BLOCK q7zx', 'auth BLOCK zz42',
                     'sub BLOCK exampleblockedmod'):
            with self.subTest(term=term):
                _lines, bad, weak = self.bl.compile_terms([term])
                self.assertEqual([], bad)
                self.assertEqual([], weak, 'should match however it is spelled')

    def test_verification_leaves_the_gate_pointed_where_it_found_it(self):
        """It swaps the blocklist out to test one term. It must put it back."""
        before, state = gate.BLOCKLIST, dict(gate._state)
        self.bl.compile_terms(['tok BLOCK q7zx'])
        self.assertEqual(before, gate.BLOCKLIST)
        self.assertEqual(state, gate._state)

    def test_the_seed_window_cannot_outgrow_the_shortest_substring(self):
        """A structural invariant the shipped list depends on.

        `matches` only looks up a substring at a position whose first SEED
        characters are a known seed. If SEED ever exceeded MIN_SUB, no sub
        term would be long enough to carry one and every substring term on the
        shipped list would go dead at once - silently, and with no way left to
        detect it, because by then the terms are digests.
        """
        self.assertLessEqual(gate.SEED, self.bl.MIN_SUB)


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
