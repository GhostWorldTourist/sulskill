"""snapshot: what changed in Mods since the last run.

The quiet failure here is that "nothing changed" and "the baseline was wrong"
produce the same report, and the report is the only thing anyone looks at.

Every way this can break lands on one of two indistinguishable outputs:

  - A baseline written when it should not have been swallows the change. The
    next run says +0 / -0 / ~0, which is exactly what a library nobody touched
    says. The tool is then reporting on a state it created itself.
  - A baseline read from the wrong place makes files that were reconciled long
    ago read as new every run. Nothing raises; the counts are large and
    plausible, and the reader learns to skim past them.

So the baseline is asserted from the documented behaviour rather than the
implementation: the saved snapshot beats `index.pkl`, `index.pkl` beats
nothing, `--save` is the only thing that writes one, and a run with no baseline
at all still runs the script-validity check - that check needs no baseline, and
losing it to a traceback is losing the half of this script that finds the
crashes.

Run as a subprocess, because that is a straight-line script with no entry
point and no seam: importing it is running it, and the thing a player invokes
is the thing under test.

No package or script here is a real mod. Every name is invented.
"""
import json
import os
import pickle
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402

SCRIPT = os.path.join(support.ROOT, 'sulskill-doctor', 'scripts', 'snapshot.py')

PY37, PY311 = 3394, 3495


class Tree(unittest.TestCase):
    """A synthetic Sims 4 folder, its own output directory, and a runner."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sims = os.path.join(self.tmp, 'The Sims 4')
        self.mods = os.path.join(self.sims, 'Mods')
        self.out = os.path.join(self.tmp, 'out')
        os.makedirs(self.mods)
        os.makedirs(self.out)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- fixtures ---------------------------------------------------------

    def file(self, rel, size=1):
        """A file of a given size. snapshot only stats these, never opens
        them, so nothing here needs to be a real package."""
        p = os.path.join(self.mods, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(b'x' * size)
        return p

    def script(self, rel, magic=PY37, source=False, zipped=True):
        """A .ts4script. Real ZIP, real pyc magic - the check reads both."""
        p = os.path.join(self.mods, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if not zipped:
            with open(p, 'wb') as f:
                f.write(b'not a zip archive')
            return p
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('mod/thing.pyc', struct.pack('<H', magic) + b'\0' * 14)
            if source:
                z.writestr('mod/thing.py', b'pass\n')
        return p

    def index_pkl(self, *rels):
        """The older baseline: a package list with no sizes in it."""
        with open(os.path.join(self.out, 'index.pkl'), 'wb') as f:
            pickle.dump({r: None for r in rels}, f)

    def saved(self):
        with open(os.path.join(self.out, 'snapshot.json'), encoding='utf-8') as f:
            return json.load(f)

    # -- runner -----------------------------------------------------------

    def run_it(self, *args):
        env = dict(os.environ, SIMS4_DIR=self.sims, SULSKILL_OUT=self.out)
        p = subprocess.run([sys.executable, SCRIPT, *args], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return p.returncode, p.stdout.decode('utf-8', 'replace')

    def out_ok(self, *args):
        code, text = self.run_it(*args)
        self.assertEqual(code, 0, text)
        return text

    def counts(self, text, kind):
        """The (+added / -removed / ~changed) triple for one section."""
        for line in text.splitlines():
            if line.startswith('=== %s:' % kind):
                body = line.split('(')[1].split(')')[0]
                return tuple(int(t.strip().lstrip('+-~'))
                             for t in body.split('/'))
        raise AssertionError('no %s section in:\n%s' % (kind, text))


class Baseline(Tree):
    """Which prior state the diff is taken against."""

    def test_the_saved_snapshot_wins_over_the_index(self):
        # Both exist and they disagree. index.pkl knows only about the old
        # file; the snapshot knows about both. Reading the index instead
        # would report a package as new that was reconciled runs ago - the
        # stale-index bug this script's persistence exists to fix.
        self.file('old.package')
        self.out_ok('--save')
        self.file('new.package')
        self.index_pkl('old.package')
        text = self.out_ok()
        added = [l for l in text.splitlines() if l.lstrip().startswith('+ ')]
        self.assertIn('previous snapshot', text)
        self.assertEqual(self.counts(text, 'packages'), (1, 0, 0))
        self.assertEqual(len(added), 1)
        self.assertIn('new.package', added[0])

    def test_the_index_is_the_baseline_before_any_snapshot_exists(self):
        self.file('old.package')
        self.file('new.package')
        self.index_pkl('old.package')
        text = self.out_ok()
        self.assertIn('index.pkl', text)
        self.assertEqual(self.counts(text, 'packages'), (1, 0, 0))

    def test_no_baseline_at_all_reads_as_everything_added(self):
        # Honest, and it says so: with nothing to compare against, every file
        # is new. The alternative this replaced was a traceback.
        self.file('a.package')
        self.file('b.package')
        text = self.out_ok()
        self.assertIn('no baseline yet', text)
        self.assertEqual(self.counts(text, 'packages'), (2, 0, 0))

    def test_the_validity_check_still_runs_with_no_baseline(self):
        # This is the half of the script that needs no baseline at all, and
        # it is the half that finds a mod that cannot load. A traceback on
        # the missing baseline takes it with it, silently.
        self.script('broken.ts4script', magic=PY311)
        text = self.out_ok()
        self.assertIn('no baseline yet', text)
        self.assertIn('broken.ts4script', text)
        self.assertIn('NO .py fallback', text)


class Saving(Tree):
    """`--save` is the only thing that moves the baseline."""

    def test_a_plain_run_does_not_write_a_baseline(self):
        self.file('a.package')
        self.out_ok()
        self.assertFalse(os.path.exists(os.path.join(self.out, 'snapshot.json')))

    def test_a_change_stays_visible_until_it_is_saved(self):
        # The property SKILL.md states: run twice without the flag and you are
        # still comparing against the last saved state, not against yourself.
        # If a plain run wrote the baseline, the second run below would report
        # +0 - and a change nobody acted on would look like no change at all.
        self.file('a.package')
        self.out_ok('--save')
        self.file('b.package')
        first = self.out_ok()
        second = self.out_ok()
        self.assertEqual(self.counts(first, 'packages'), (1, 0, 0))
        self.assertEqual(self.counts(second, 'packages'), (1, 0, 0))

    def test_saving_makes_the_next_run_quiet(self):
        self.file('a.package')
        self.out_ok('--save')
        text = self.out_ok()
        self.assertEqual(self.counts(text, 'packages'), (0, 0, 0))

    def test_the_saved_baseline_is_the_state_just_walked(self):
        self.file('a.package', size=7)
        self.file('cfg/mod.cfg')
        self.script('s.ts4script')
        self.out_ok('--save')
        snap = self.saved()
        self.assertEqual(sorted(snap['packages']), ['a.package'])
        self.assertEqual(snap['packages']['a.package'][0], 7)
        self.assertEqual(len(snap['scripts']), 1)
        self.assertEqual(len(snap['other']), 1)


class Diff(Tree):
    """Added, removed, changed - and what is none of those."""

    def test_a_resized_package_is_a_change_not_an_add_and_a_remove(self):
        self.file('a.package', size=4)
        self.out_ok('--save')
        self.file('a.package', size=9)
        text = self.out_ok()
        self.assertEqual(self.counts(text, 'packages'), (0, 0, 1))
        self.assertIn('4 -> 9 bytes', text)

    def test_a_deleted_package_is_reported_as_removed(self):
        self.file('a.package')
        self.file('b.package')
        self.out_ok('--save')
        os.unlink(os.path.join(self.mods, 'b.package'))
        text = self.out_ok()
        self.assertEqual(self.counts(text, 'packages'), (0, 1, 0))
        self.assertIn('- b.package', text)

    def test_a_baseline_that_records_no_size_reports_no_size_changes(self):
        # index.pkl carries names only, so every package in it has size 0.
        # Comparing that against a real size would mark the entire library as
        # changed on the fallback run - hundreds of lines of noise with the
        # one genuine addition buried in it.
        self.file('old.package', size=500)
        self.file('new.package', size=500)
        self.index_pkl('old.package')
        text = self.out_ok()
        self.assertEqual(self.counts(text, 'packages'), (1, 0, 0))

    def test_a_file_touched_but_not_resized_is_not_a_change(self):
        # Size is the signal, deliberately: a deploy relinks files and moves
        # every mtime in the library without changing a byte of any of them.
        self.file('a.package', size=6)
        self.out_ok('--save')
        os.utime(os.path.join(self.mods, 'a.package'), (1, 1))
        self.assertEqual(self.counts(self.out_ok(), 'packages'), (0, 0, 0))


class WhatIsWatched(Tree):
    """Which files land in which of the three buckets."""

    def test_extensions_are_matched_without_regard_to_case(self):
        # The game is case-insensitive about this and mods ship `.Package`.
        # A case-sensitive test here makes those files invisible to every
        # count in the report while they load perfectly well in game.
        self.file('Loud.PACKAGE')
        self.file('Quiet.Ts4Script')
        text = self.out_ok()
        self.assertEqual(self.counts(text, 'packages'), (1, 0, 0))
        self.assertEqual(self.counts(text, 'scripts'), (1, 0, 0))

    def test_a_script_is_not_also_counted_as_a_package(self):
        self.script('s.ts4script')
        text = self.out_ok()
        self.assertEqual(self.counts(text, 'packages'), (0, 0, 0))
        self.assertEqual(self.counts(text, 'scripts'), (1, 0, 0))

    def test_config_files_are_watched_and_documents_are_not(self):
        # Settings files are the ones that change between sessions without
        # anyone installing anything, which is most of why this is run.
        for name in ('mod.cfg', 'mod.json', 'mod.ini', 'mod.py', 'mod.pyc'):
            self.file(name)
        self.file('readme.txt')
        self.file('preview.jpg')
        self.assertEqual(self.counts(self.out_ok(), 'other'), (5, 0, 0))

    def test_files_in_subfolders_are_walked(self):
        self.file('Deep/Deeper/a.package')
        text = self.out_ok()
        self.assertEqual(self.counts(text, 'packages'), (1, 0, 0))
        self.assertIn(os.path.join('Deep', 'Deeper', 'a.package'), text)


class ScriptValidity(Tree):
    """Whether a .ts4script can load at all - no baseline involved."""

    def test_py37_bytecode_at_depth_one_is_clean(self):
        self.script('Mod/s.ts4script')
        text = self.out_ok()
        self.assertIn('all valid ZIPs', text)

    def test_newer_bytecode_with_no_source_is_flagged(self):
        self.script('s.ts4script', magic=PY311)
        text = self.out_ok()
        self.assertIn('py3.11', text)
        self.assertIn('NO .py fallback', text)

    def test_newer_bytecode_with_a_source_fallback_says_so(self):
        # zipimport falls back to the .py, so this one still loads. Reporting
        # it the same as the case above sends a player to delete a mod that
        # works.
        self.script('s.ts4script', magic=PY311, source=True)
        text = self.out_ok()
        self.assertIn('.py fallback present', text)
        self.assertNotIn('NO .py fallback', text)

    def test_a_script_too_deep_to_load_is_flagged(self):
        # Present, listed by every inventory, never read by the game.
        self.script('One/Two/s.ts4script')
        text = self.out_ok()
        self.assertIn('TOO DEEP', text)

    def test_a_script_that_is_not_a_zip_is_flagged(self):
        self.script('s.ts4script', zipped=False)
        text = self.out_ok()
        self.assertIn('NOT A ZIP ARCHIVE', text)


if __name__ == '__main__':
    unittest.main()
