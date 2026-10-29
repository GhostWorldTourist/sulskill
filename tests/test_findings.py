"""findings.py / vortex_state.py: rows name the mod a player can search for, and stay true.

Two promises, each of which once failed on a real library:

- **A row names the mod, not the package.** Players search their manager by mod
  (the archive they installed), so every file is grouped under the Vortex mod
  that deployed it, or the folder it sits in on a manual install.
- **A row that is already resolved disappears.** Findings are written once and
  read after every deploy. A row whose files are all gone, or a conflict left
  with fewer than two mods, is not something to act on any more.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                      # noqa: E402

sys.path.insert(0, os.path.join(support.ROOT, 'sulskill-doctor', 'scripts'))
import findings                                                     # noqa: E402
import vortex_state                                                 # noqa: E402


def touch(root, rel):
    p = os.path.join(root, *rel.split('/'))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'wb').close()


class Library(unittest.TestCase):

    def setUp(self):
        self.mods = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.mods)
        touch(self.mods, 'Vortex Mods/alpha_core.package')
        touch(self.mods, 'Vortex Mods/alpha_addon.package')
        touch(self.mods, 'Vortex Mods/beta.package')
        touch(self.mods, 'Unzipped Gamma/gamma.package')
        with open(os.path.join(self.mods, 'Vortex Mods', 'vortex.deployment.json'), 'w') as f:
            json.dump({'files': [{'relPath': 'alpha_core.package', 'source': 'Alpha-1-2'},
                                 {'relPath': 'alpha_addon.package', 'source': 'Alpha-1-2'},
                                 {'relPath': 'beta.package', 'source': 'Beta-9'}]}, f)
        self.lib = findings.Library(self.mods, names={'Alpha-1-2': {'customFileName': 'Alpha Mod'}})

    def row(self, *files, mod='x'):
        return {'mod': mod, 'files': list(files), 'claim': '', 'evidence': '', 'severity': 'low',
                'action': 'Keep, but know this', 'reason': 4}

    def test_deployment_paths_are_relative_to_mods(self):
        dep = vortex_state.deployment(self.mods)
        self.assertEqual('Alpha-1-2', dep['vortex mods/alpha_core.package'])

    def test_files_group_under_the_vortex_mod_or_its_folder(self):
        rows = [self.row('Vortex Mods/alpha_core.package', 'alpha_addon.package', 'beta.package', 'gamma.package')]
        findings.attach_mods(rows, self.lib)
        groups = dict((k, v) for k, v in rows[0]['vm'])
        self.assertEqual(['alpha_core.package', 'alpha_addon.package'], groups['Alpha Mod'])
        self.assertEqual(['beta.package'], groups['Beta-9'])          # no display name: the id
        self.assertEqual(['gamma.package'], groups['Unzipped Gamma'])  # manual install: its folder

    def test_globs_match(self):
        self.assertEqual(2, len(self.lib.match('alpha_*.package')))

    def test_a_row_whose_files_are_gone_is_dropped(self):
        rows = [self.row('removed.package', mod='gone'), self.row('beta.package', mod='kept')]
        dropped = findings.attach_mods(rows, self.lib)
        self.assertEqual(['gone'], dropped)
        self.assertEqual(['kept'], [r['mod'] for r in rows])

    def test_a_conflict_left_with_one_mod_is_over(self):
        rows = [self.row('beta.package', 'removed_rival.package', mod='pair')]
        self.assertEqual(['pair'], findings.attach_mods(rows, self.lib))

    def test_a_removed_file_inside_a_live_row_is_left_out(self):
        rows = [self.row('alpha_core.package', 'beta.package', 'removed.package')]
        findings.attach_mods(rows, self.lib)
        shown = [f for _, fs in rows[0]['vm'] for f in fs]
        self.assertNotIn('removed.package', shown)

    def test_no_manager_means_no_names_not_a_crash(self):
        with support.environment(VORTEX_STATE=os.path.join(self.mods, 'nowhere')):
            self.assertEqual({}, vortex_state.mod_names())


if __name__ == '__main__':
    unittest.main()
