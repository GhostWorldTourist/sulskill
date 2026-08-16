"""Sorting a library into what a profile disables and what it keeps.

Both failures worth guarding here produce output that reads as correct.

A mod that lands in no bucket is invisible: the counts still print, the plan
still says it covers everything, and the mod is simply never named. It then
stays enabled in a profile built to exclude it, and the first sign of that is
somebody seeing it in the game.

A derived search term that also matches something on the keep list is worse
than no term at all. The plan says to type it, select the whole filtered block
and disable it, and the keeper in that block goes with the rest. Nothing in the
plan looks any different when this happens.

The classifier is deliberately built out of creators, frameworks and
vocabulary, with no list of individual mods on either side of the decision -
not the adult ones and not the exceptions. So the tests are about the shape of
the sorting, not about any particular mod being in any particular bucket.

No package or creator here is real. Every name is invented.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402

SCRIPTS = os.path.join(support.ROOT, 'sulskill-doctor', 'scripts')
CLASSIFY = os.path.join(SCRIPTS, 'classify_adult.py')
PLAN = os.path.join(SCRIPTS, 'apply_plan.py')
LOCAL = os.path.join(support.ROOT, 'sulskill-doctor', 'adult_patterns.local')


class Harness(unittest.TestCase):
    """A synthetic Mods folder and a synthetic output directory."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sims = os.path.join(self.tmp, 'The Sims 4')
        self.mods = os.path.join(self.sims, 'Mods')
        self.out = os.path.join(self.tmp, 'out')
        os.makedirs(self.mods)
        os.makedirs(self.out)
        # A local pattern file belonging to whoever is running the tests must
        # not change what they say. Move it aside and put it back.
        if os.path.exists(LOCAL):
            os.rename(LOCAL, LOCAL + '.testing')
            self.addCleanup(os.rename, LOCAL + '.testing', LOCAL)

    def mod(self, name):
        """One mod, as a loose package. Content is irrelevant - the classifier
        reads names, which is the whole of its reach and its limitation."""
        with open(os.path.join(self.mods, name + '.package'), 'wb') as f:
            f.write(b'')

    def run_script(self, path):
        env = dict(os.environ, SIMS4_DIR=self.sims, SULSKILL_OUT=self.out,
                   VORTEX_TS4_MODS=os.path.join(self.tmp, 'no-vortex-here'))
        p = subprocess.run([sys.executable, path], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        text = p.stdout.decode('utf-8', 'replace').replace('\r\n', '\n')
        if p.returncode:
            raise AssertionError('%s exited %d:\n%s'
                                 % (os.path.basename(path), p.returncode, text))
        return text

    def classify(self):
        text = self.run_script(CLASSIFY)
        with open(os.path.join(self.out, 'adult_inventory.json'),
                  encoding='utf-8') as f:
            return json.load(f), text

    def local_patterns(self, body):
        with open(LOCAL, 'w', encoding='utf-8') as f:
            f.write(body)
        self.addCleanup(lambda: os.path.exists(LOCAL) and os.unlink(LOCAL))


class Buckets(Harness):
    """Which pile a mod lands in, and that it lands in exactly one."""

    def test_vocabulary_excludes(self):
        self.mod('AcmeStudios_LewdPoses')
        d, _ = self.classify()
        self.assertEqual(['AcmeStudios_LewdPoses.package'], d['adult'])

    def test_an_ordinary_mod_is_kept(self):
        self.mod('PlainJane_BetterCoffee')
        d, _ = self.classify()
        self.assertEqual(['PlainJane_BetterCoffee.package'], d['keep'])
        self.assertEqual([], d['adult'])

    def test_matching_ignores_case(self):
        self.mod('AcmeStudios_LEWDPoses')
        d, _ = self.classify()
        self.assertEqual([], d['keep'])
        self.assertEqual(1, len(d['adult']))

    def test_animation_props_are_their_own_bucket(self):
        """Props are useless without the animations but are not sex content.

        Folding them into `adult` would be defensible right up until someone
        wants the count of what they are actually removing.
        """
        self.mod('CC_for_animations')
        d, _ = self.classify()
        self.assertEqual(['CC_for_animations.package'], d['animation_props'])
        self.assertEqual([], d['adult'])

    def test_drug_mods_are_a_separate_decision(self):
        """Wanting no porn in a save is not wanting no Basemental in it."""
        self.mod('Basemental_Drugs_v3')
        d, _ = self.classify()
        self.assertEqual(['Basemental_Drugs_v3.package'], d['adjacent_not_sex'])
        self.assertEqual([], d['adult'])

    def test_a_drug_mod_that_is_also_adult_counts_as_adult(self):
        """The separate decision is about drugs, not about an adult add-on
        that happens to plug into a drugs mod."""
        self.mod('Basemental_Drugs_LewdAddon')
        d, _ = self.classify()
        self.assertEqual(['Basemental_Drugs_LewdAddon.package'], d['adult'])
        self.assertEqual([], d['adjacent_not_sex'])

    def test_every_mod_lands_in_exactly_one_bucket(self):
        """The quiet one. A mod in no bucket is never named anywhere, and
        stays installed in a profile built to remove it."""
        names = ['AcmeStudios_LewdPoses', 'PlainJane_BetterCoffee',
                 'CC_for_animations', 'Basemental_Drugs_v3',
                 'TidyDesk_Utility', 'BrightMoon_EroticSet']
        for n in names:
            self.mod(n)
        d, _ = self.classify()
        placed = (d['adult'] + d['animation_props']
                  + d['adjacent_not_sex'] + d['keep'])
        self.assertEqual(sorted(n + '.package' for n in names), sorted(placed))
        self.assertEqual(len(placed), len(set(placed)))


class LocalPatterns(Harness):
    """The escape hatch for mods no keyword can reach.

    It exists because the shipped patterns deliberately name no individual
    mod. Without somewhere for those to go, the pressure is to put them back
    into the script, which is where they were and why they were wrong.
    """

    def test_a_local_pattern_reclassifies(self):
        self.mod('QuietName_Bundle')
        d, _ = self.classify()
        self.assertEqual(['QuietName_Bundle.package'], d['keep'])

        self.local_patterns('QuietName_Bundle\n')
        d, _ = self.classify()
        self.assertEqual(['QuietName_Bundle.package'], d['adult'])

    def test_comments_and_blank_lines_are_ignored(self):
        """Both of these are regex injection into a file people write prose in.

        A comment is only safely a comment if it never reaches `re.compile` -
        the one below has an unbalanced bracket, which takes the whole pattern
        down with it. A blank line is worse than it looks: an empty branch in
        an alternation matches at every position, so every mod in the library
        becomes adult and the run still exits zero.
        """
        self.mod('QuietName_Bundle')
        self.mod('PlainJane_BetterCoffee')
        self.local_patterns('# things I decided about (see notes\n'
                            '\n'
                            'QuietName_Bundle\n')
        d, _ = self.classify()
        self.assertEqual(['QuietName_Bundle.package'], d['adult'])
        self.assertEqual(['PlainJane_BetterCoffee.package'], d['keep'])

    def test_no_local_file_changes_nothing(self):
        self.mod('QuietName_Bundle')
        self.assertFalse(os.path.exists(LOCAL))
        d, _ = self.classify()
        self.assertEqual(['QuietName_Bundle.package'], d['keep'])


class Review(Harness):
    """What replaced the hard-coded exception list.

    A mod that reads as questionable and was kept anyway gets printed for a
    person to look at. Silence there is the failure: the script would be
    reporting a clean sort of a library it never actually decided about.
    """

    def test_a_questionable_keep_is_printed_for_review(self):
        self.mod('PlainJane_UnderwearBasics')
        d, text = self.classify()
        self.assertEqual(['PlainJane_UnderwearBasics.package'], d['keep'])
        section = text.split('still looks questionable')[-1]
        self.assertIn('PlainJane_UnderwearBasics', section)

    def test_an_ordinary_keep_is_not_printed_for_review(self):
        self.mod('PlainJane_BetterCoffee')
        _, text = self.classify()
        section = text.split('still looks questionable')[-1]
        self.assertNotIn('PlainJane_BetterCoffee', section)


class SearchTerms(Harness):
    """apply_plan turns the exclude list into Vortex search-box keystrokes."""

    def inventory(self, adult, keep, props=(), adjacent=()):
        d = {'adult': sorted(adult), 'animation_props': sorted(props),
             'adjacent_not_sex': sorted(adjacent), 'keep': sorted(keep),
             'adult_bytes': 0, 'prop_bytes': 0}
        with open(os.path.join(self.out, 'adult_inventory.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(d, f)
        return d

    def plan(self):
        self.run_script(PLAN)
        with open(os.path.join(self.out, 'SFW_PROFILE_PLAN.txt'),
                  encoding='utf-8') as f:
            return f.read()

    def blocks(self, text):
        """{search term: [mods under it]}, plus '' for the individual list."""
        out, cur = {}, None
        for line in text.split('\n'):
            if line.startswith('--- search: '):
                cur = line.split("'")[1]
                out[cur] = []
            elif line.startswith('--- no shared substring'):
                cur = ''
                out[cur] = []
            elif line.startswith('==='):
                cur = None
            elif cur is not None and line.startswith('    ') and line.strip():
                out[cur].append(line.strip())
        return out

    def test_no_term_selects_something_on_the_keep_list(self):
        """The one that costs a person a mod they wanted.

        The fixture has to make the *widest* term the unsafe one, or it proves
        nothing: with two excluded mods sharing a long prefix, preferring the
        longer term already avoids the collision by accident, and dropping the
        check entirely changes no output. Here 'Acme' covers all three
        excluded mods and is what a widest-first pass reaches for - and it
        also selects the keeper. The safe answer covers less.
        """
        self.inventory(adult=['AcmeLewdOne', 'AcmeLewdTwo', 'AcmeEroticSet'],
                       keep=['AcmeCoffeeMaker'])
        blocks = self.blocks(self.plan())
        for term in blocks:
            if term:
                self.assertNotIn(term.lower(), 'acmecoffeemaker',
                                 'term %r also selects the keeper' % term)

    def test_the_plan_prefers_fewer_searches(self):
        """The point of the plan is the click count, not the grouping.

        'Zed' takes three of these in one search. 'Alpha' takes two and comes
        first in the term order, so the wide term has to sort after the narrow
        one or the fixture cannot tell a widest-first pass from a first-found
        one - both would answer 'Zed' and look right doing it. Splitting these
        across two searches produces a plan that reads as perfectly correct
        while doubling the work it exists to save.
        """
        self.inventory(adult=['Alpha_Zed', 'Beta_Zed', 'Gamma_Zed',
                              'Alpha_Bee'], keep=[])
        blocks = self.blocks(self.plan())
        self.assertEqual(1, len([t for t in blocks if t]), blocks)

    def test_a_term_actually_selects_what_it_is_listed_against(self):
        self.inventory(adult=['AcmeLewdPoses', 'AcmeLewdProps'], keep=[])
        for term, mods in self.blocks(self.plan()).items():
            for m in mods:
                if term:
                    self.assertIn(term.lower(), m.lower())

    def test_a_mod_no_term_reaches_is_listed_individually(self):
        """Not dropped. A plan that silently omits a mod reads as complete."""
        self.inventory(adult=['AcmeLewdPoses', 'AcmeLewdProps', 'Qwx7Standalone'],
                       keep=[])
        blocks = self.blocks(self.plan())
        self.assertIn('Qwx7Standalone', blocks.get('', []))

    def test_every_excluded_mod_appears_exactly_once(self):
        mods = ['AcmeLewdPoses', 'AcmeLewdProps', 'Qwx7Standalone',
                'BrightMoonEroticOne', 'BrightMoonEroticTwo']
        self.inventory(adult=mods, keep=['AcmeCoffeeMaker'])
        listed = [m for v in self.blocks(self.plan()).values() for m in v]
        self.assertEqual(sorted(mods), sorted(listed))

    def test_terms_come_from_this_inventory_not_a_fixed_list(self):
        """A hard-coded list works on one library and covers nothing on the
        next, while still printing a plan that looks like a plan."""
        self.inventory(adult=['Zzyzx_Bundle_One', 'Zzyzx_Bundle_Two'], keep=[])
        terms = [t for t in self.blocks(self.plan()) if t]
        self.assertTrue(any('Zzyzx' in t for t in terms), terms)

    def test_props_are_planned_alongside_adult(self):
        """They are a separate bucket to count, but the same click to disable."""
        self.inventory(adult=['AcmeLewdPoses'], keep=[],
                       props=['AcmeLewdPropPack'])
        listed = [m for v in self.blocks(self.plan()).values() for m in v]
        self.assertIn('AcmeLewdPropPack', listed)


class Output(Harness):
    """Neither script may write into the checkout - see POLICY.md."""

    def test_the_inventory_is_written_outside_the_repository(self):
        self.mod('PlainJane_BetterCoffee')
        self.classify()
        self.assertTrue(os.path.exists(
            os.path.join(self.out, 'adult_inventory.json')))
        self.assertFalse(os.path.exists(
            os.path.join(support.ROOT, 'adult_inventory.json')))
        self.assertFalse(os.path.exists(
            os.path.join(SCRIPTS, 'adult_inventory.json')))


if __name__ == '__main__':
    unittest.main()
