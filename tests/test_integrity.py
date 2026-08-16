"""The shipped blocklist and the shims that load it.

These check the repository's own files rather than synthetic ones. They can
do that without naming anything, because every property that matters here is
structural: a digest is the right length, a tier is one of two words, a
shim is in place and current.

That last one is not hypothetical. Adding an export to _shared/shim.py does
nothing until the shim is copied into every skill, and forgetting a copy
leaves that one skill importing a gate module missing the function it is
about to call - which surfaces as an AttributeError in front of a player.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402
import gate                                                        # noqa: E402

ROOT = support.ROOT


class ShippedBlocklist(unittest.TestCase):
    """Structure only. The terms stay hashed; that is the whole design."""

    def setUp(self):
        with open(gate.BLOCKLIST, encoding='utf-8') as f:
            self.lines = [l.strip() for l in f
                          if l.strip() and not l.startswith('#')]

    def test_it_is_not_empty(self):
        self.assertTrue(self.lines, 'blocklist has no entries')

    def test_every_line_parses(self):
        gate._state.clear()
        sub, tok, auth, count = gate._load()
        self.assertEqual(count, len(self.lines))
        self.assertTrue(sub['by_length'] or tok or auth)

    def test_modes_and_tiers_are_known(self):
        for line in self.lines:
            bits = line.split(':')
            with self.subTest(mode=bits[0]):
                self.assertIn(bits[0], ('sub', 'tok', 'auth'))
                self.assertIn(bits[1], ('BLOCK', 'REVIEW'))

    def test_digests_are_the_right_width(self):
        """blake2b(digest_size=8) is 16 hex characters. A truncated or
        hand-edited digest silently matches nothing."""
        for line in self.lines:
            bits = line.split(':')
            digests = [bits[3], bits[4]] if bits[0] == 'sub' else [bits[2]]
            for d in digests:
                with self.subTest(digest=d):
                    self.assertEqual(16, len(d))
                    int(d, 16)

    def test_substring_terms_are_long_enough_to_be_safe(self):
        """Below the compiler's minimum a substring starts matching inside
        ordinary words, which would refuse innocent libraries."""
        import blocklist_add
        for line in self.lines:
            bits = line.split(':')
            if bits[0] == 'sub':
                with self.subTest(line=bits[2]):
                    self.assertGreaterEqual(int(bits[2]), blocklist_add.MIN_SUB)

    def test_substring_terms_are_long_enough_to_be_found(self):
        """The prefilter hashes a SEED-length window, so a term shorter than
        the seed can never be reached however it is spelled."""
        for line in self.lines:
            bits = line.split(':')
            if bits[0] == 'sub':
                self.assertGreaterEqual(int(bits[2]), gate.SEED)

    def test_no_plaintext_terms_leaked_into_the_file(self):
        """Digest lines only. A term left in as a comment or a stray line is
        the failure this whole design exists to prevent."""
        for line in self.lines:
            with self.subTest(line=line[:24]):
                self.assertRegex(
                    line,
                    r'^(sub:(BLOCK|REVIEW):\d+:[0-9a-f]{16}:[0-9a-f]{16}'
                    r'|(tok|auth):(BLOCK|REVIEW):[0-9a-f]{16})$')


class Shims(unittest.TestCase):

    def test_every_listed_skill_exists(self):
        missing = [s for s in gate.SKILLS
                   if not os.path.isdir(os.path.join(ROOT, s))]
        self.assertEqual([], missing, f'SKILLS names a missing skill: {missing}')

    def test_every_skill_has_a_shim(self):
        missing = [s for s in gate.SKILLS
                   if not os.path.exists(
                       os.path.join(ROOT, s, 'scripts', 'gate.py'))]
        self.assertEqual([], missing)

    def test_every_shim_is_current(self):
        """A stale copy is worse than a missing one: it imports, and then
        lacks whatever was added to the shared shim since it was copied."""
        with open(os.path.join(ROOT, '_shared', 'shim.py'),
                  encoding='utf-8') as f:
            master = f.read()
        stale = []
        for skill in gate.SKILLS:
            path = os.path.join(ROOT, skill, 'scripts', 'gate.py')
            if not os.path.exists(path):
                continue
            with open(path, encoding='utf-8') as f:
                if f.read() != master:
                    stale.append(skill)
        self.assertEqual([], stale, f'shim out of date, re-copy: {stale}')

    def test_integrity_check_passes_on_this_checkout(self):
        self.assertEqual([], gate._integrity())


class Portability(unittest.TestCase):
    """The shim is reached through a link in normal use - the assistant's
    skills directory links to wherever the checkout actually lives. abspath
    keeps the link path and then fails to find _shared beside it."""

    def test_shim_resolves_symlinks(self):
        with open(os.path.join(ROOT, '_shared', 'shim.py'),
                  encoding='utf-8') as f:
            src = f.read()
        self.assertIn('realpath', src)
        self.assertNotIn('os.path.abspath(__file__)', src)


if __name__ == '__main__':
    unittest.main()
