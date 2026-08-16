"""Resource.cfg: what loads, and what only looks like it loads.

The quiet failure here is the worst kind in this repository. A package one
folder deeper than the deepest PackedFile rule is installed, present, listed by
every inventory tool - and never read by the game. Nothing raises. The mod just
does not work, and the player concludes the mod is broken.

Written from the design, not the implementation:

  - '*' does not cross '/'. That is the only reason a Resource.cfg carries one
    rule per depth. A matcher that let it cross would report full coverage for
    files the game never sees, which is exactly the bug the coverage check
    exists to catch - so it is asserted directly.
  - Deduplication must be a no-op. The claim --fix makes to the user is that
    the resolved load order is unchanged, so the tests assert the invariant
    (same (priority, glob) pairs, same order) rather than a specific rendering.
  - Rule order within a priority decides which of two matching mods wins, so it
    is preserved even though it looks like a detail.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402,F401

sys.path.insert(0, os.path.join(support.ROOT, 'sulskill-doctor', 'scripts'))
import resource_cfg as rc                                          # noqa: E402


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'')


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def pairs(blocks):
    """The load result, as the game resolves it: priority, glob, order."""
    return [(p, d.lower(), rc._rule_key(a))
            for p, rules in blocks for d, a in rules]


def run_main(argv):
    """Call the CLI and capture what it said. -> (exit code, combined output).

    Capturing rather than letting it through is not only tidiness. Uncaptured,
    each of these tests prints a full report into the run, and the line saying
    whether the suite passed scrolls off the top - a suite whose result you
    cannot see is a suite nobody reads. Having the text in hand also lets the
    tests assert that the tool *said* something, which is the actual claim in
    a report tool: a wrong exit code is loud, a silent one is not.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = rc.main(argv)
    return code, buf.getvalue()


DUPLICATED = """\
Priority 500
PackedFile *.package
PackedFile */*.package

Priority 1337
PackedFile Vortex Mods/*.package
PackedFile Vortex Mods/*/*.package
PackedFile Data/*Strings.tmcatalog

Priority 1337
PackedFile Vortex Mods/*.package
PackedFile Vortex Mods/*/*.package
"""


class Globs(unittest.TestCase):

    def test_star_does_not_cross_a_separator(self):
        r = rc.to_regex('*.package')
        self.assertTrue(r.match('Loose.package'))
        self.assertFalse(r.match('Sub/Loose.package'))

    def test_one_rule_per_depth(self):
        r = rc.to_regex('*/*/*.package')
        self.assertTrue(r.match('a/b/c.package'))
        self.assertFalse(r.match('a/b.package'))
        self.assertFalse(r.match('a/b/c/d.package'))

    def test_backslashes_and_case_are_the_same_rule(self):
        self.assertTrue(rc.to_regex(r'Vortex Mods\*.package')
                        .match('vortex mods/X.PACKAGE'))
        self.assertEqual(rc._rule_key(r'Vortex Mods\*.package'),
                         rc._rule_key('vortex mods/*.package'))


class Parsing(unittest.TestCase):

    def test_lines_before_the_first_priority_are_kept(self):
        blocks, _c, _u = rc.parse('PackedFile *.package\nPriority 5\n'
                                  'PackedFile */*.package\n')
        self.assertEqual([p for p, _r in blocks], [None, 5])

    def test_an_unrecognised_directive_is_reported_not_dropped(self):
        blocks, _c, unknown = rc.parse('Priority 1\nNonsense here\n'
                                       'PackedFile *.package\n')
        self.assertEqual(unknown, ['Nonsense here'])
        self.assertIn(('Nonsense', 'here'), blocks[0][1])


class Deduplication(unittest.TestCase):
    """--fix promises it cannot change what loads. That is the property."""

    def setUp(self):
        self.blocks, self.comments, _u = rc.parse(DUPLICATED)
        self.fixed, self.dup_rules, self.dup_blocks = rc.canonical(self.blocks)

    def test_it_finds_the_repeat(self):
        self.assertEqual(self.dup_blocks, [1337])
        self.assertEqual(len(self.dup_rules), 2)

    def test_load_result_is_unchanged(self):
        self.assertEqual(sorted(set(pairs(self.blocks))),
                         sorted(set(pairs(self.fixed))))

    def test_rule_order_within_a_priority_is_preserved(self):
        rules = dict((p, [rc._rule_key(a) for _d, a in r])
                     for p, r in self.fixed)[1337]
        self.assertEqual(rules, ['vortexmods/*.package',
                                 'vortexmods/*/*.package',
                                 'data/*strings.tmcatalog'])

    def test_the_richer_copy_of_a_repeated_block_survives(self):
        # The second 1337 block omits the tmcatalog rule. Merging must union,
        # not overwrite - taking the last block wholesale would silently drop
        # catalog strings and look like a successful cleanup.
        self.assertIn('data/*strings.tmcatalog',
                      [rc._rule_key(a) for p, r in self.fixed
                       for _d, a in r if p == 1337])

    def test_it_is_idempotent(self):
        again, dr, db = rc.canonical(self.fixed)
        self.assertEqual((dr, db), ([], []))
        self.assertEqual(pairs(again), pairs(self.fixed))

    def test_rendered_output_reparses_to_the_same_thing(self):
        reparsed, _c, _u = rc.parse(rc.render(self.fixed, self.comments))
        self.assertEqual(pairs(reparsed), pairs(self.fixed))

    def test_a_clean_file_is_left_alone(self):
        blocks, comments, _u = rc.parse(rc.render(self.fixed, self.comments))
        fixed, dr, db = rc.canonical(blocks)
        self.assertEqual((dr, db), ([], []))


class Coverage(unittest.TestCase):
    """A package no rule reaches is installed and not loading."""

    def setUp(self):
        self.mods = tempfile.mkdtemp()
        touch(os.path.join(self.mods, 'Top.package'))
        touch(os.path.join(self.mods, 'One', 'Mid.package'))
        touch(os.path.join(self.mods, 'One', 'Two', 'Deep.package'))
        touch(os.path.join(self.mods, 'One', 'Two', 'Script.ts4script'))

    def test_deeper_than_the_deepest_rule_is_unreachable(self):
        blocks, _c, _u = rc.parse('Priority 500\nPackedFile *.package\n'
                                  'PackedFile */*.package\n')
        cov, missed, seen, rule = rc.coverage(self.mods, blocks)
        self.assertEqual(cov, 2)
        self.assertEqual(missed, ['One/Two/Deep.package'])
        self.assertEqual((seen, rule), (2, 1))

    def test_full_depth_reaches_everything(self):
        blocks, _c, _u = rc.parse('Priority 500\nPackedFile *.package\n'
                                  'PackedFile */*.package\n'
                                  'PackedFile */*/*.package\n')
        cov, missed, _s, _r = rc.coverage(self.mods, blocks)
        self.assertEqual((cov, missed), (3, []))

    def test_scripts_are_not_governed_by_this_file(self):
        # .ts4script is found by the game itself; a PackedFile rule neither
        # helps nor hurts it. Counting it here would report a false gap on
        # every correctly configured install.
        blocks, _c, _u = rc.parse('Priority 500\nPackedFile *.package\n'
                                  'PackedFile */*.package\n'
                                  'PackedFile */*/*.package\n')
        _c2, missed, _s, _r = rc.coverage(self.mods, blocks)
        self.assertNotIn('One/Two/Script.ts4script', missed)


class Repair(unittest.TestCase):

    def setUp(self):
        self.mods = tempfile.mkdtemp()
        self.cfg = os.path.join(self.mods, 'Resource.cfg')
        with open(self.cfg, 'w', encoding='utf-8') as f:
            f.write(DUPLICATED)
        touch(os.path.join(self.mods, 'Top.package'))

    def test_fix_shrinks_the_file_and_keeps_a_backup(self):
        before = read(self.cfg)
        code, out = run_main(['--path', self.cfg, '--fix'])
        self.assertEqual(code, 0)
        self.assertLess(len(read(self.cfg)), len(before))
        baks = [f for f in os.listdir(self.mods) if f.endswith('.bak')]
        self.assertEqual(len(baks), 1)
        self.assertEqual(read(os.path.join(self.mods, baks[0])), before)
        # A backup nobody is told about is a backup nobody will find.
        self.assertIn(baks[0], out)

    def test_fix_preserves_the_load_result(self):
        before, _c, _u = rc.parse(read(self.cfg))
        run_main(['--path', self.cfg, '--fix'])
        after, _c, _u = rc.parse(read(self.cfg))
        self.assertEqual(sorted(set(pairs(before))), sorted(set(pairs(after))))

    def test_reporting_alone_does_not_write(self):
        before = read(self.cfg)
        code, out = run_main(['--path', self.cfg])
        self.assertEqual(code, 1)
        self.assertEqual(read(self.cfg), before)
        self.assertEqual([f for f in os.listdir(self.mods)
                          if f.endswith('.bak')], [])
        # Reporting without saying what to do about it is half a report.
        self.assertIn('--fix', out)

    def test_a_missing_file_is_not_silence(self):
        missing = os.path.join(self.mods, 'nope')
        code, out = run_main(['--path', missing])
        self.assertEqual(code, 2)
        # The name of the test is the assertion: an absent Resource.cfg means
        # the game loads nothing at all from Mods, and exiting 2 with an empty
        # console reads to a player exactly like a clean bill of health.
        self.assertIn(missing, out)
        self.assertTrue(out.strip(), 'exited 2 without saying anything')


if __name__ == '__main__':
    unittest.main()
