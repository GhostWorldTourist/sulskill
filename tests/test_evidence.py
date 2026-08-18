"""Evidence that exists and is never surfaced.

The quiet failure here is a file nobody looks at. A real investigation ran
twenty-five bisect rounds while the answer sat in `mc_lastexception.html`, in
the Mods folder, naming the culprit twenty-one times. It was not missed through
carelessness - it was missed because the reader worked from a remembered list of
artifacts, and a file not on the list does not exist.

That is the failure this covers, and it is why the important assertions here are
about the files the tool does NOT know. A tool with a longer allowlist fixes one
investigation. A tool that reports what it cannot identify fixes the next one
too, which is the only version worth shipping.

Written from the design:

  - Anything diagnostic-looking is evidence, whether or not it is recognised.
  - Unrecognised files must be reported, and reported prominently, because the
    unknown file is the one most likely to hold the answer.
  - Recognition adds an explanation and a rank; it must never be the filter that
    decides whether a file is mentioned at all.
  - A missing MCCC dump is itself a finding, since it is the highest-value
    artifact and its absence is invisible.
"""
import contextlib
import importlib
import io
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402,F401

sys.path.insert(0, os.path.join(support.ROOT, 'sulskill-doctor', 'scripts'))
import evidence                                                    # noqa: E402


def install(tmp, files):
    """files: {relative path: age in seconds}. -> the Sims 4 root."""
    root = os.path.join(tmp, 'The Sims 4')
    for rel, age in files.items():
        full = os.path.join(root, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w', encoding='utf-8') as f:
            f.write('x')
        when = time.time() - age
        os.utime(full, (when, when))
    return root


def run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = evidence.main(argv)
    return code, buf.getvalue()


BASE = {
    'Mods/Vortex Mods/mc_lastexception.html': 100,
    'lastException.txt': 120,
    'Config.log': 200,
}


class UnknownFilesAreThePoint(unittest.TestCase):

    def test_an_unrecognised_artifact_is_still_listed(self):
        tmp = tempfile.mkdtemp()
        root = install(tmp, dict(BASE, **{'somebody_elses_debug.log': 90}))
        _, out = run(['--root', root])
        self.assertIn('somebody_elses_debug.log', out)

    def test_unrecognised_artifacts_get_their_own_call_to_action(self):
        tmp = tempfile.mkdtemp()
        root = install(tmp, dict(BASE, **{'mystery_output.txt': 90}))
        _, out = run(['--root', root])
        self.assertIn('READ THEM ANYWAY', out)
        after = out.split('READ THEM ANYWAY', 1)[1]
        self.assertIn('mystery_output.txt', after)

    def test_a_mod_shipping_its_own_exception_file_is_recognised(self):
        """The second file that was missed - a mod's own crash report, which is
        usually closer to the fault than the game-wide one."""
        tmp = tempfile.mkdtemp()
        root = install(tmp, dict(BASE, **{'SomeMod_v1.2_Exception.txt': 90}))
        _, out = run(['--root', root])
        self.assertIn('SomeMod_v1.2_Exception.txt', out)
        self.assertNotIn('SomeMod_v1.2_Exception.txt',
                         out.split('READ THEM ANYWAY')[-1]
                         if 'READ THEM ANYWAY' in out else '')

    def test_non_diagnostic_files_are_not_listed(self):
        tmp = tempfile.mkdtemp()
        root = install(tmp, dict(BASE, **{'Mods/SomeMod.package': 90,
                                          'Saves/slot_00000001.save': 90}))
        _, out = run(['--root', root])
        self.assertNotIn('SomeMod.package', out)
        self.assertNotIn('slot_00000001.save', out)


class RankingPutsTheUsefulThingFirst(unittest.TestCase):

    def test_the_mccc_dump_outranks_the_game_report(self):
        """The dump must sort first because it is worth more, not because it
        happens to be newer - so the fixture makes it the OLDER file. With
        equal-age files any ordering passes and the assertion proves nothing."""
        tmp = tempfile.mkdtemp()
        root = install(tmp, {'Mods/Vortex Mods/mc_lastexception.html': 5000,
                             'lastException.txt': 100,
                             'Config.log': 90})
        _, out = run(['--root', root])
        self.assertLess(out.index('mc_lastexception.html'),
                        out.index('lastException.txt'))

    def test_a_recognised_file_carries_an_explanation(self):
        tmp = tempfile.mkdtemp()
        root = install(tmp, BASE)
        _, out = run(['--root', root])
        self.assertIn('LOCALS', out)

    def test_a_missing_mccc_dump_is_itself_reported(self):
        """Its absence is invisible otherwise, and it is the single most useful
        thing to add to a library you intend to diagnose."""
        tmp = tempfile.mkdtemp()
        root = install(tmp, {'lastException.txt': 100, 'Config.log': 200})
        _, out = run(['--root', root])
        self.assertIn('No mc_lastexception.html', out)

    def test_no_such_advice_when_the_dump_is_present(self):
        tmp = tempfile.mkdtemp()
        root = install(tmp, BASE)
        _, out = run(['--root', root])
        self.assertNotIn('No mc_lastexception.html', out)


class SessionScoping(unittest.TestCase):

    def test_since_launch_drops_older_artifacts(self):
        tmp = tempfile.mkdtemp()
        root = install(tmp, {'Config.log': 60,
                             'lastException.txt': 90,
                             'lastException_ancient.txt': 500_000})
        _, out = run(['--root', root, '--since-launch'])
        self.assertIn('lastException.txt', out)
        self.assertNotIn('ancient', out)

    def test_artifacts_from_this_session_are_marked(self):
        tmp = tempfile.mkdtemp()
        root = install(tmp, {'Config.log': 60, 'lastException.txt': 90})
        _, out = run(['--root', root])
        self.assertIn('* ', out)


class ExitCodes(unittest.TestCase):

    def test_evidence_present_is_exit_1(self):
        tmp = tempfile.mkdtemp()
        root = install(tmp, BASE)
        code, _ = run(['--root', root])
        self.assertEqual(code, 1)

    def test_nothing_to_read_is_exit_0(self):
        tmp = tempfile.mkdtemp()
        root = install(tmp, {'Mods/SomeMod.package': 10})
        code, _ = run(['--root', root])
        self.assertEqual(code, 0)

    def test_missing_install_is_exit_2(self):
        code, _ = run(['--root', os.path.join(tempfile.mkdtemp(), 'nope')])
        self.assertEqual(code, 2)


if __name__ == '__main__':
    unittest.main()
