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
  - A round nobody played produces no artifact, and so does a game that died
    before the first frame - too fast to write a report or to be caught by a
    process poll. Both are byte-identical to a pass, so absence of an artifact
    is only a pass when something else shows the game actually ran.
  - Starting the game is the tool's job; deciding what happened is not. Arming
    must not launch unless asked, and launching must never score.
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
import warnings

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
    # SIMS4_LAUNCH_CMD and SIMS4_GAME_DIR are pinned so that no code path -
    # including a mutated one - can start the real game from a test run. A
    # mutation that made arm() launch unconditionally did exactly that once,
    # and a suite that touches the machine it runs on is not a suite.
    with support.environment(SIMS4_DIR=tmp, SULSKILL_OUT=out,
                             SULSKILL_BISECT_HOLD=hold,
                             SIMS4_GAME_DIR=tmp,
                             SIMS4_LAUNCH_CMD='%s -c pass' % sys.executable), \
            warnings.catch_warnings():
        warnings.simplefilter('ignore', ResourceWarning)
        importlib.reload(bs)
        bs.ts4_started = lambda: None      # no game process in a test
        bs.LAUNCH_WAIT = 0                 # never sit waiting for one either
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


def played(tmp, age=50, name='mc_cmd_center.log'):
    """Evidence the game actually ran: a mod log touched during the round.

    Without this a round nobody launched is indistinguishable from one that
    passed - both produce no exception file - so the fixtures have to say
    which happened.
    """
    path = os.path.join(tmp, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('launch\n')
    when = time.time() - age
    os.utime(path, (when, when))
    return path


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
            played(tmp)
            code, out = run(['check'])
            self.assertEqual(code, 0)
            s = state()
            self.assertEqual(sorted(s['candidates']), ['alpha', 'bravo'])
            self.assertEqual(sorted(s['cleared']), ['charlie', 'delta'])

    def test_clean_round_switches_to_addback(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha', 'bravo']), '--root', root])
            poke(armed_at=time.time() - 300)
            played(tmp)
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
            played(tmp)
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
            played(tmp)
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
            played(tmp)
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
            played(tmp)
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


class ARoundNobodyPlayedIsNotAPass(unittest.TestCase):
    """No artifact is what a passing round looks like AND what an unplayed one
    looks like - and what a game that died before the first frame looks like,
    since that is too fast to write a report or to be seen by a process poll.
    Silently reading any of those as clean is a false exoneration."""

    def test_no_artifact_and_no_sign_of_a_run_refuses_to_score(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            poke(armed_at=time.time() - 300)
            code, out = run(['check'])
            self.assertEqual(code, 2)
            self.assertIn('NO EVIDENCE', out)

    def test_no_evidence_records_no_round(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            poke(armed_at=time.time() - 300, candidates=list(MODS))
            run(['check'])
            self.assertEqual(state()['rounds'], [])

    def test_no_evidence_clears_nobody(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            poke(armed_at=time.time() - 300, candidates=list(MODS))
            run(['check'])
            self.assertEqual(state()['cleared'], [])

    def test_a_running_game_with_no_report_yet_is_not_a_pass(self):
        """While the game is still up, silence means "not answered yet", not
        "passed". One real round read as clean 51 seconds in and produced the
        failure at three minutes - the reports arrive when the player triggers
        the thing, not at startup."""
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            poke(armed_at=time.time() - 300, candidates=list(MODS))
            played(tmp)                          # it launched...
            bs.ts4_started = lambda: time.time() - 200   # ...and is still up
            code, out = run(['check'])
            self.assertEqual(code, 2)
            self.assertIn('IN PROGRESS', out)
            self.assertEqual(state()['rounds'], [])
            self.assertEqual(state()['cleared'], [])

    def test_a_finished_run_with_no_report_is_a_pass(self):
        """The discriminating half: same silence, but the game has exited and
        the logs show it ran. That is the only shape that is actually clean."""
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            poke(armed_at=time.time() - 300, candidates=list(MODS))
            played(tmp)
            code, _ = run(['check'])
            self.assertEqual(code, 0)

    def test_a_log_written_before_the_round_is_not_evidence(self):
        with rig() as (tmp, root):
            played(tmp, age=10_000)            # a previous session's launch
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            poke(armed_at=time.time() - 300)
            code, out = run(['check'])
            self.assertEqual(code, 2)
            self.assertIn('NO EVIDENCE', out)


class Launching(unittest.TestCase):

    def test_a_process_that_never_appears_is_reported_as_a_result(self):
        """A crash before the first frame is a different symptom, not a tool
        failure, so it must not read as an error the caller shrugs off."""
        with rig() as (tmp, root):
            with support.environment(
                    SIMS4_LAUNCH_CMD='%s -c pass' % sys.executable), \
                    warnings.catch_warnings():
                # launch() detaches on purpose - it starts a game and returns
                # rather than waiting for it - so the stand-in process outlives
                # the call and GC reports it. Expected here, not a leak.
                warnings.simplefilter('ignore', ResourceWarning)
                up, why = bs.launch(wait=0)
            self.assertFalse(up)
            self.assertIn('result', why)

    def test_arm_does_not_launch_unless_asked(self):
        with rig() as (tmp, root):
            calls = []
            bs.launch = lambda *a, **k: (calls.append(1), (True, 'up'))[1]
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            self.assertEqual(calls, [])

    def test_arm_launches_when_asked(self):
        with rig() as (tmp, root):
            calls = []
            bs.launch = lambda *a, **k: (calls.append(1), (True, 'up'))[1]
            run(['arm', cuts(tmp, ['alpha']), '--root', root, '--launch'])
            self.assertEqual(calls, [1])


class MovingIsReversible(unittest.TestCase):

    def test_arm_then_restore_round_trips(self):
        with rig() as (tmp, root):
            live = os.path.join(root, 'Vortex Mods', 'alpha.package')
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            self.assertFalse(os.path.exists(live))
            run(['restore'])
            self.assertTrue(os.path.exists(live))
            # What is out is answered by the holding directory, not the ledger.
            self.assertEqual(bs.hold(root).held()['out'], [])

    def test_arming_twice_refuses(self):
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha']), '--root', root])
            code, out = run(['arm', cuts(tmp, ['bravo'], 'c2.txt'),
                             '--root', root])
            self.assertEqual(code, 2)
            self.assertIn('already out', out)

    def test_a_file_lost_from_the_hold_is_reported_not_dropped(self):
        """A held file that is on neither side is the one case this tool
        cannot fix, so it has to be the loudest thing it says. The old
        behaviour was to record it as outstanding and print a generic failure,
        which reads like something a rerun would clear up."""
        with rig() as (tmp, root):
            run(['arm', cuts(tmp, ['alpha', 'bravo']), '--root', root])
            h = bs.hold(root)
            gone = h.held()['out'][0]['rel']
            os.remove(h.locate(gone))
            code, out = run(['restore'])
            self.assertEqual(code, 1)
            self.assertIn('MISSING', out)
            self.assertIn(gone, out)
            # the other one still went home
            self.assertEqual(h.held()['out'], [])

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
