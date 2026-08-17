"""Bisection: narrowing that is wrong and looks exactly like progress.

The quiet failure here is a false exoneration. A failing round tempts you to
clear the mods you just disabled - "I pulled that half and it still broke" - and
that is sound only when exactly one mod is at fault. With two mods that each
break the load alone, every half fails, each failing round clears innocent and
guilty alike, and the candidate set narrows steadily into a region that never
held the answer. Nothing errors. The rounds keep halving. The report at the end
names a mod with total confidence and is wrong.

Written from the design in SKILL.md, not from the implementation:

  - A clean round proves every cause lies inside the disabled set. That is the
    only round that may narrow while halving, so it is asserted directly.
  - A failing round while halving must narrow NOTHING. This is the property the
    predecessor tool got wrong, so it is asserted on its own.
  - Add-back reverses that: with the complement proven clean, a failure is
    attributable to what was added, and both outcomes narrow.
  - A cause is named only by a single-mod add-back that fails. Elimination is
    not naming - it assumes the single culprit again.
  - An artifact older than the round says nothing about the round, and one
    still being written says nothing yet. Both must refuse to score rather than
    read as clean, because "clean" is the answer that ends the search.
"""
import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402,F401

sys.path.insert(0, os.path.join(support.ROOT, 'sulskill-doctor', 'scripts'))
import bisect_mods as bs                                           # noqa: E402


MODS = ('alpha', 'bravo', 'charlie', 'delta')


def install(tmp, mods=MODS, manifest=True):
    """A synthetic deployed library. -> the Mods folder."""
    root = os.path.join(tmp, 'Mods')
    vx = os.path.join(root, 'Vortex Mods')
    os.makedirs(vx, exist_ok=True)
    files = []
    for name in mods:
        rel = '%s.package' % name
        with open(os.path.join(vx, rel), 'wb') as f:
            f.write(b'\x00' * 8)
        files.append({'relPath': rel, 'source': name})
    if manifest:
        with open(os.path.join(vx, 'vortex.deployment.json'), 'w',
                  encoding='utf-8') as f:
            json.dump({'targetPath': vx, 'files': files}, f)
    return root


def cuts(tmp, names, fname='cut.txt'):
    path = os.path.join(tmp, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('# a round\n' + '\n'.join(names) + '\n')
    return path


@contextlib.contextmanager
def rig(mods=MODS, manifest=True):
    """A temp install with bisect reloaded against it. -> (tmp, mods root)."""
    tmp = tempfile.mkdtemp()
    root = install(tmp, mods, manifest)
    out = os.path.join(tmp, 'out')
    hold = os.path.join(tmp, 'hold')
    os.makedirs(out, exist_ok=True)
    with support.environment(SIMS4_DIR=tmp, SULSKILL_OUT=out,
                             SULSKILL_BISECT_HOLD=hold):
        importlib.reload(bs)
        bs.ts4_started = lambda: None      # no game process in a test
        yield tmp, root


def run(argv):
    """Call the CLI, capture what it said. -> (exit code, output)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = bs.main(argv)
    return code, buf.getvalue()


def state():
    with open(bs.ledger_path(), encoding='utf-8') as f:
        return json.load(f)


def poke(**kw):
    s = state()
    s.update(kw)
    bs.save(s)


def report(tmp, age, name='lastException.txt'):
    """An exception file `age` seconds old."""
    path = os.path.join(tmp, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('<report>posture_specs.py:1359</report>')
    when = time.time() - age
    os.utime(path, (when, when))
    return path


class FailingRoundNarrowsNothing(unittest.TestCase):
    """The property the predecessor tool inverted."""

    def test_failing_round_while_halving_clears_nobody(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha', 'bravo']), '--root', root])
            poke(armed_at=time.time() - 300)
            report(tmp, 100)
            code, out = run(['check'])
            self.assertEqual(code, 1)
            s = state()
            self.assertEqual(sorted(s['candidates']), ['alpha', 'bravo'])
            self.assertEqual(s['cleared'], [])
            self.assertIn('narrows nothing', out)

    def test_failing_round_names_nobody(self):
        """The candidates left enabled are the ones a wrong implementation
        would name, so the round has to leave some enabled - disabling the
        whole candidate set gives the mutation nothing to name and the test
        passes either way."""
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            poke(armed_at=time.time() - 300, candidates=list(MODS))
            report(tmp, 100)
            run(['check'])
            self.assertEqual(state()['named'], [])


class CleanRoundIsTheOnlyProof(unittest.TestCase):

    def test_clean_round_clears_the_enabled_and_keeps_the_disabled(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha', 'bravo']), '--root', root])
            poke(armed_at=time.time() - 300,
                 candidates=['alpha', 'bravo', 'charlie', 'delta'])
            code, out = run(['check'])
            self.assertEqual(code, 0)
            s = state()
            self.assertEqual(sorted(s['candidates']), ['alpha', 'bravo'])
            self.assertEqual(sorted(s['cleared']), ['charlie', 'delta'])

    def test_clean_round_switches_to_addback(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha', 'bravo']), '--root', root])
            poke(armed_at=time.time() - 300)
            _, out = run(['check'])
            self.assertEqual(state()['mode'], 'addback')
            self.assertEqual(sorted(state()['clean_base']), ['alpha', 'bravo'])
            self.assertIn('add-back', out)


class AddBackNarrowsBothWays(unittest.TestCase):

    def test_failure_after_adding_back_blames_what_was_added(self):
        with rig() as (tmp, root):
            # proven clean with all four out
            run(['arm', cuts(tmp, list(MODS)), '--root', root])
            poke(armed_at=time.time() - 300, candidates=list(MODS))
            run(['check'])
            run(['restore'])
            # add alpha and bravo back; it fails
            run(['arm', cuts(tmp, ['charlie', 'delta'], 'c2.txt'), '--root', root])
            poke(armed_at=time.time() - 300)
            report(tmp, 100)
            run(['check'])
            self.assertEqual(sorted(state()['candidates']), ['alpha', 'bravo'])

    def test_single_mod_addback_failure_names_it(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, list(MODS)), '--root', root])
            poke(armed_at=time.time() - 300, candidates=list(MODS))
            run(['check'])
            run(['restore'])
            run(['arm', cuts(tmp, ['bravo', 'charlie', 'delta'], 'c2.txt'),
                 '--root', root])
            poke(armed_at=time.time() - 300)
            report(tmp, 100)
            _, out = run(['check'])
            self.assertEqual(state()['named'], ['alpha'])
            self.assertIn('NAMED', out)

    def test_naming_one_prompts_the_confirmation_round(self):
        """A second cause is invisible until the first is out of the way."""
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, list(MODS)), '--root', root])
            poke(armed_at=time.time() - 300, candidates=list(MODS))
            run(['check'])
            run(['restore'])
            run(['arm', cuts(tmp, ['bravo', 'charlie', 'delta'], 'c2.txt'),
                 '--root', root])
            poke(armed_at=time.time() - 300)
            report(tmp, 100)
            _, out = run(['check'])
            self.assertIn('everything else live', out)


class ArtifactsMustBelongToTheRound(unittest.TestCase):

    def test_report_older_than_the_round_is_not_scored(self):
        with rig() as (tmp, root):
            report(tmp, 10_000)                    # from a previous session
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            poke(armed_at=time.time() - 300)
            code, _ = run(['check'])
            self.assertEqual(code, 0)              # clean, not a false failure

    def test_report_still_being_written_refuses_to_score(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            poke(armed_at=time.time() - 300)
            report(tmp, 1)                         # inside the settle window
            code, out = run(['check'])
            self.assertEqual(code, 2)
            self.assertIn('still being written', out)
            self.assertEqual(state()['rounds'], [])

    def test_ui_exceptions_count_too(self):
        """A UI-only failure leaves lastException clean; scoring one layer
        reads a broken round as healthy."""
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            poke(armed_at=time.time() - 300)
            report(tmp, 100, 'lastUIException_63922354494.txt')
            code, _ = run(['check'])
            self.assertEqual(code, 1)

    def test_check_without_an_armed_round_refuses(self):
        with rig() as (tmp, root):
            code, _ = run(['check'])
            self.assertEqual(code, 2)


class MovingIsReversible(unittest.TestCase):

    def test_arm_then_restore_round_trips(self):
        with rig() as (tmp, root):
            live = os.path.join(root, 'Vortex Mods', 'alpha.package')
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            self.assertFalse(os.path.exists(live))
            run(['restore'])
            self.assertTrue(os.path.exists(live))
            self.assertEqual(state()['moved'], [])

    def test_arming_twice_refuses(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            code, out = run(['arm', cuts(tmp, ['bravo'], 'c2.txt'),
                             '--root', root])
            self.assertEqual(code, 2)
            self.assertIn('already out', out)

    def test_interrupted_restore_keeps_only_the_outstanding(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha', 'bravo']), '--root', root])
            held = state()['moved']
            os.remove(os.path.join(tmp, 'hold', held[0]['rel']))
            code, _ = run(['restore'])
            self.assertEqual(code, 1)
            left = state()['moved']
            self.assertEqual([i['rel'] for i in left], [held[0]['rel']])

    def test_default_holding_directory_is_outside_mods(self):
        """Inside Mods, a deep enough Resource.cfg rule would load the very
        files being hidden.

        The default is what has to hold: an explicit SULSKILL_BISECT_HOLD is the
        caller's problem, and asserting against one the fixture chose would pass
        no matter what the default were.
        """
        tmp = tempfile.mkdtemp()
        root = install(tmp)
        with support.environment(SIMS4_DIR=tmp, SULSKILL_BISECT_HOLD=None):
            importlib.reload(bs)
            self.assertFalse(
                os.path.abspath(bs.HOLD).startswith(os.path.abspath(root) + os.sep))


class ManualInstalls(unittest.TestCase):

    def test_units_fall_back_to_top_level_entries(self):
        with rig(manifest=False) as (tmp, root):
            # no manifest: the unit is whatever sits at the top of Mods
            found = bs.units(root)
            self.assertIn('Vortex Mods', found)

    def test_plan_reports_names_that_do_not_resolve(self):
        with rig() as (tmp, root):
            code, out = run(['plan', cuts(tmp, ['alpha', 'nosuchmod']),
                             '--root', root])
            self.assertEqual(code, 1)
            self.assertIn('nosuchmod', out)

    def test_plan_moves_nothing(self):
        with rig() as (tmp, root):
            live = os.path.join(root, 'Vortex Mods', 'alpha.package')
            run(['plan', cuts(tmp, ['alpha']), '--root', root])
            self.assertTrue(os.path.exists(live))


if __name__ == '__main__':
    unittest.main()
