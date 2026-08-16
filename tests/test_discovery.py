"""Finding mods without a mod manager.

Plenty of players drop files straight into Mods and have never installed
Vortex. A path hardcoded to a manager's staging folder finds nothing for
them, silently - which is how classify_adult.py came to crash outright on a
manual install while passing every check on a managed one.

These tests build synthetic installs in a temp directory rather than reading
whatever happens to be on the machine running them, so they mean the same
thing on a developer's laptop, a player's PC and CI.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402
import gate                                                        # noqa: E402


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(b'')


class ManualInstall(unittest.TestCase):
    """No manager. Loose files and unzipped folders directly in Mods."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sims = os.path.join(self.tmp, 'The Sims 4')
        self.mods = os.path.join(self.sims, 'Mods')
        touch(os.path.join(self.mods, 'Loose.package'))
        touch(os.path.join(self.mods, 'SomeMod', 'inner.package'))
        touch(os.path.join(self.mods, 'SomeMod', 'runtime.ts4script'))
        touch(os.path.join(self.mods, 'Resource.cfg'))
        self.env = support.environment(
            SIMS4_DIR=self.sims,
            VORTEX_TS4_MODS=os.path.join(self.tmp, 'no-vortex-here'))
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)

    def test_mods_folder_is_the_only_root(self):
        self.assertEqual([self.mods], gate.mod_roots())

    def test_units_are_loose_files_and_folders(self):
        labels = sorted(label for label, _ in gate.mod_units())
        self.assertEqual(['Loose.package', 'SomeMod'], labels)

    def test_units_skip_stray_non_mod_files(self):
        self.assertNotIn('Resource.cfg',
                         [label for label, _ in gate.mod_units()])

    def test_find_searches_recursively(self):
        hits = [os.path.basename(p) for p in gate.find_mod_files('*.package')]
        self.assertEqual(['Loose.package', 'inner.package'], sorted(hits))

    def test_find_mod_file_returns_a_nested_hit(self):
        hit = gate.find_mod_file('*.ts4script')
        self.assertIsNotNone(hit, 'nested script mod not found')
        self.assertTrue(hit.endswith('runtime.ts4script'))

    def test_find_returns_none_rather_than_raising(self):
        self.assertIsNone(gate.find_mod_file('*.nothing'))


class VortexInstall(unittest.TestCase):
    """Vortex deploys INTO Mods\\Vortex Mods\\, a subfolder of Mods, so one
    recursive walk of Mods covers a manager and a manual install both."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sims = os.path.join(self.tmp, 'The Sims 4')
        self.mods = os.path.join(self.sims, 'Mods')
        self.staging = os.path.join(self.tmp, 'staging')
        touch(os.path.join(self.mods, 'Vortex Mods', 'Deployed.package'))
        touch(os.path.join(self.staging, 'SomeMod-123', 'Staged.package'))
        self.env = support.environment(
            SIMS4_DIR=self.sims, VORTEX_TS4_MODS=self.staging)
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)

    def test_both_roots_are_used(self):
        self.assertEqual([self.mods, self.staging], gate.mod_roots())

    def test_deployed_file_is_found_by_walking_mods(self):
        hits = [os.path.basename(p) for p in
                gate.find_mod_files('*.package', roots=[self.mods])]
        self.assertEqual(['Deployed.package'], hits)


class NoInstallAtAll(unittest.TestCase):

    def test_missing_folders_yield_no_roots(self):
        tmp = tempfile.mkdtemp()
        with support.environment(
                SIMS4_DIR=os.path.join(tmp, 'nope'),
                VORTEX_TS4_MODS=os.path.join(tmp, 'also-nope')):
            self.assertEqual([], gate.mod_roots())
            self.assertEqual([], gate.mod_units())
            self.assertEqual([], gate.find_mod_files('*.package'))


class OutputLocation(unittest.TestCase):
    """Generated output describes one machine's library and must never
    default to somewhere inside the checkout."""

    def test_out_dir_is_outside_the_repository(self):
        with support.environment(SULSKILL_OUT=None):
            out = os.path.realpath(gate.out_dir())
        repo = os.path.realpath(support.ROOT)
        self.assertFalse(
            out == repo or out.startswith(repo + os.sep),
            f'out_dir() points inside the repository: {out}')

    def test_out_dir_honours_the_override(self):
        tmp = tempfile.mkdtemp()
        target = os.path.join(tmp, 'somewhere')
        with support.environment(SULSKILL_OUT=target):
            self.assertEqual(target, gate.out_dir())
        self.assertTrue(os.path.isdir(target), 'out_dir() should create it')


if __name__ == '__main__':
    unittest.main()
