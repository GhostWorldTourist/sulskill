"""Moving mods out of the way, and the promise that every one comes back.

The bug this module was written against: the record of what had been moved
lived in a single JSON file outside Mods, its loader swallowed every read error
and returned empty, and so a truncated write or a cleared %LOCALAPPDATA% made
`restore` print "nothing is out" while the files sat in the holding directory.
Under a mod manager that is recoverable by redeploying. Without one - which is
most players - those were the only copies, and the tool had just said everything
was fine.

So the properties asserted here are the ones that make the undo real rather than
reported:

  - The filesystem is the truth. Destroy the ledger, destroy the journal,
    destroy both: every held file still comes home, because the holding
    directory mirrors Mods and its own layout is a restore plan.
  - Nothing is overwritten and nothing is deleted. Every collision is refused,
    on both the way out and the way back. An undo that can destroy something is
    not an undo.
  - A file on neither side is reported as MISSING. That is the one case this
    cannot repair, so silence about it is the worst possible answer.
  - Cross-volume is refused BEFORE the first move, not discovered during it -
    a copy-then-delete duplicates the inode instead of relocating it, which
    breaks a manager's hardlink and, without a manager, puts the only copy of a
    mod through a delete.
  - A manual install is detected as such and told the truth about what its undo
    depends on, because the reassuring paragraph written for Vortex is false
    for it.
"""
import contextlib
import importlib
import json
import os
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402

sys.path.insert(0, os.path.join(support.ROOT, 'sulskill-doctor', 'scripts'))
import holdlog                                                     # noqa: E402
import install as installinfo                                      # noqa: E402
import bisect_mods as bs                                           # noqa: E402


def mods(tmp, files=('alpha.package', 'bravo.package'), managed=True):
    """A library on disk. -> the Mods folder.

    `managed` decides whether Vortex's deployment manifest is there, which is
    what separates the two safety stories.
    """
    root = os.path.join(tmp, 'Mods')
    base = os.path.join(root, 'Vortex Mods') if managed else root
    os.makedirs(base, exist_ok=True)
    entries = []
    for name in files:
        path = os.path.join(base, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(name.encode())
        entries.append({'relPath': name.replace(os.sep, '/'), 'source': name})
    if managed:
        with open(os.path.join(base, 'vortex.deployment.json'), 'w',
                  encoding='utf-8') as f:
            json.dump({'targetPath': base, 'files': entries}, f)
    return root


def rel(name, managed=True):
    return os.path.join('Vortex Mods', name) if managed else name


@contextlib.contextmanager
def rig(files=('alpha.package', 'bravo.package'), managed=True):
    """A library, a holding directory, and a Hold wired to them."""
    tmp = tempfile.mkdtemp()
    root = mods(tmp, files, managed)
    hold = os.path.join(tmp, 'hold')
    # VORTEX_TS4_MODS is pinned so staging detection cannot wander off to the
    # real machine running the suite and report a second copy that is not this
    # fixture's.
    staging = os.path.join(tmp, 'staging')
    if managed:
        os.makedirs(staging, exist_ok=True)
        with open(os.path.join(staging, 'x'), 'w') as f:
            f.write('staged')
    with support.environment(SIMS4_DIR=tmp, VORTEX_TS4_MODS=staging,
                             SULSKILL_BISECT_HOLD=hold,
                             APPDATA=os.path.join(tmp, 'appdata')):
        yield tmp, root, holdlog.Hold(hold, root)


def arm(h, names, managed=True):
    for name in names:
        ok, err = h.hold_file(name, rel(name, managed))
        if not ok:
            raise AssertionError('could not hold %s: %s' % (name, err))


class TheFilesystemIsTheTruth(unittest.TestCase):
    """Every way the bookkeeping can be lost, and the files still come back."""

    def test_restore_works_with_the_journal_deleted(self):
        with rig() as (tmp, root, h):
            arm(h, ['alpha.package', 'bravo.package'])
            os.remove(h.journal)
            done, failed = h.restore_all()
            self.assertEqual((done, failed), (2, []))
            for name in ('alpha.package', 'bravo.package'):
                self.assertTrue(os.path.exists(os.path.join(root, rel(name))))

    def test_a_deleted_journal_still_reports_the_files_as_out(self):
        """The failure being prevented: "nothing is out" while mods sit in the
        holding directory."""
        with rig() as (tmp, root, h):
            arm(h, ['alpha.package'])
            os.remove(h.journal)
            state = holdlog.Hold(h.dir, root).held()
            self.assertEqual(len(state['out']), 1)
            self.assertEqual(state['unjournalled'], state['out'])
            # The exact sentence the predecessor printed over a full holding
            # directory. It must not appear while a file is still out.
            self.assertNotIn('nothing is out', '\n'.join(holdlog.report(state)))

    def test_a_truncated_journal_loses_names_not_files(self):
        with rig() as (tmp, root, h):
            arm(h, ['alpha.package', 'bravo.package'])
            with open(h.journal, 'r+', encoding='utf-8') as f:
                body = f.read()
                f.seek(0)
                f.truncate()
                f.write(body[:len(body) // 2] + '{"op":"ho')  # torn line
            state = h.held()
            self.assertEqual(len(state['out']), 2)
            self.assertGreaterEqual(state['damaged_lines'], 1)
            done, failed = h.restore_all()
            self.assertEqual((done, failed), (2, []))

    def test_an_unparseable_journal_is_counted_not_ignored(self):
        with rig() as (tmp, root, h):
            arm(h, ['alpha.package'])
            with open(h.journal, 'a', encoding='utf-8') as f:
                f.write('this is not json\n')
            self.assertEqual(h.held()['damaged_lines'], 1)

    def test_a_hold_reached_with_no_root_argument_finds_it_in_the_journal(self):
        """Recovery from another directory, another session, another tool."""
        with rig() as (tmp, root, h):
            h.open_session('test', installinfo.detect(root))
            arm(h, ['alpha.package'])
            fresh = holdlog.Hold(h.dir)          # no root passed
            self.assertEqual(os.path.abspath(fresh.root),
                             os.path.abspath(root))
            done, failed = fresh.restore_all()
            self.assertEqual((done, failed), (1, []))


class NothingIsOverwrittenAndNothingIsDeleted(unittest.TestCase):

    def test_holding_over_an_existing_held_file_refuses(self):
        """The predecessor called os.remove(dst) to clear the way, which on a
        manual install deletes the only copy of a previously held mod."""
        with rig() as (tmp, root, h):
            arm(h, ['alpha.package'])
            held = h.locate(rel('alpha.package'))
            with open(os.path.join(root, rel('alpha.package')), 'wb') as f:
                f.write(b'a different file with the same name')
            ok, err = h.hold_file('alpha.package', rel('alpha.package'))
            self.assertFalse(ok)
            self.assertIn('already held', err)
            self.assertTrue(os.path.exists(held))
            with open(held, 'rb') as f:
                self.assertEqual(f.read(), b'alpha.package')

    def test_restoring_onto_an_occupied_path_refuses(self):
        with rig() as (tmp, root, h):
            arm(h, ['alpha.package'])
            live = os.path.join(root, rel('alpha.package'))
            with open(live, 'wb') as f:
                f.write(b'redeployed by the manager')
            done, failed = h.restore_all()
            self.assertEqual(done, 0)
            self.assertEqual(len(failed), 1)
            with open(live, 'rb') as f:
                self.assertEqual(f.read(), b'redeployed by the manager')
            self.assertTrue(os.path.exists(h.locate(rel('alpha.package'))))

    def test_a_file_present_on_both_sides_is_a_conflict_not_a_restore(self):
        with rig() as (tmp, root, h):
            arm(h, ['alpha.package'])
            with open(os.path.join(root, rel('alpha.package')), 'wb') as f:
                f.write(b'back again')
            state = h.held()
            self.assertEqual(len(state['conflict']), 1)
            self.assertEqual(state['out'], [])

    def test_prune_never_removes_a_directory_holding_something(self):
        with rig(files=('deep/one.package', 'deep/two.package')) as (
                tmp, root, h):
            arm(h, ['deep/one.package', 'deep/two.package'])
            h.unhold_file(rel('deep/one.package'))
            h._prune()
            self.assertTrue(os.path.exists(h.locate(rel('deep/two.package'))))


class AMissingFileIsSaidOutLoud(unittest.TestCase):

    def test_a_file_on_neither_side_is_missing(self):
        with rig() as (tmp, root, h):
            arm(h, ['alpha.package'])
            os.remove(h.locate(rel('alpha.package')))
            state = h.held()
            self.assertEqual(len(state['missing']), 1)
            self.assertEqual(state['out'], [])
            self.assertIn('MISSING', '\n'.join(holdlog.report(state)))

    def test_missing_names_the_mod_it_belonged_to(self):
        with rig() as (tmp, root, h):
            arm(h, ['alpha.package'])
            os.remove(h.locate(rel('alpha.package')))
            self.assertEqual(h.held()['missing'][0]['mod'], 'alpha.package')


class CrossVolumeIsRefusedUpFront(unittest.TestCase):

    def test_preflight_refuses_a_different_volume(self):
        with rig() as (tmp, root, h):
            with mock(installinfo, 'same_volume', lambda a, b: False):
                ok, why = h.preflight()
            self.assertFalse(ok)
            self.assertIn('different volume', '\n'.join(why))

    def test_preflight_refuses_when_the_volume_cannot_be_told(self):
        """Unknown is not permission. Finding out during the move is how a
        library ends up half somewhere else."""
        with rig() as (tmp, root, h):
            with mock(installinfo, 'same_volume', lambda a, b: None):
                ok, why = h.preflight()
            self.assertFalse(ok)
            self.assertIn('cannot tell', '\n'.join(why))

    def test_the_refusal_explains_the_copy_not_only_the_hardlink(self):
        """The old message named only the manager's hardlink, which says
        nothing to the majority who have no manager - and understates them."""
        with rig() as (tmp, root, h):
            with mock(installinfo, 'same_volume', lambda a, b: False):
                _ok, why = h.preflight()
            text = '\n'.join(why)
            self.assertIn('manual install', text)
            self.assertIn('hardlink', text)


class TheLegacyLayoutIsStillFound(unittest.TestCase):
    """Somebody will upgrade mid-round. The previous version put held files
    straight into the holding directory with no files/ level, and a version
    that could not see them would greet them with "nothing is out"."""

    def test_files_in_the_old_layout_are_reported_as_out(self):
        with rig() as (tmp, root, h):
            os.makedirs(os.path.join(h.dir, 'Vortex Mods'), exist_ok=True)
            os.rename(os.path.join(root, rel('alpha.package')),
                      os.path.join(h.dir, rel('alpha.package')))
            state = h.held()
            self.assertEqual([i['rel'] for i in state['out']],
                             [rel('alpha.package')])

    def test_files_in_the_old_layout_restore(self):
        with rig() as (tmp, root, h):
            os.makedirs(os.path.join(h.dir, 'Vortex Mods'), exist_ok=True)
            os.rename(os.path.join(root, rel('alpha.package')),
                      os.path.join(h.dir, rel('alpha.package')))
            done, failed = h.restore_all()
            self.assertEqual((done, failed), (1, []))
            self.assertTrue(os.path.exists(os.path.join(root,
                                                        rel('alpha.package'))))

    def test_the_journal_and_readme_are_never_mistaken_for_held_mods(self):
        with rig() as (tmp, root, h):
            h.open_session('test')
            arm(h, ['alpha.package'])
            rels = {i['rel'] for i in h.held()['out']}
            self.assertEqual(rels, {rel('alpha.package')})


class TheJournalIsReadableByOtherThings(unittest.TestCase):

    def test_every_line_is_one_json_object(self):
        with rig() as (tmp, root, h):
            h.open_session('bisect_mods', installinfo.detect(root))
            arm(h, ['alpha.package'])
            with open(h.journal, encoding='utf-8') as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
            self.assertTrue(lines)
            for ln in lines:
                self.assertIsInstance(json.loads(ln), dict)

    def test_intent_is_written_before_the_move_and_done_after(self):
        with rig() as (tmp, root, h):
            arm(h, ['alpha.package'])
            phases = [(r.get('op'), r.get('phase')) for r in h.records()]
            self.assertEqual(phases, [('hold', 'intent'), ('hold', 'done')])

    def test_the_session_record_names_the_root_and_the_install(self):
        with rig() as (tmp, root, h):
            h.open_session('bisect_mods', installinfo.detect(root))
            rec = [r for r in h.records() if r['op'] == 'session'][-1]
            self.assertEqual(os.path.abspath(rec['root']),
                             os.path.abspath(root))
            self.assertEqual(rec['install'], 'vortex')
            self.assertTrue(rec['second_copy'])

    def test_a_readme_is_left_with_the_files(self):
        """This directory is a sibling of Mods inside the folder that every
        Sims 4 support answer tells people to delete."""
        with rig() as (tmp, root, h):
            h.open_session('bisect_mods')
            with open(h.readme, encoding='utf-8') as f:
                text = f.read()
            self.assertIn('DO NOT DELETE', text)
            self.assertIn(root, text)


class TheInstallIsDetected(unittest.TestCase):

    def test_a_manifest_means_vortex(self):
        with rig() as (tmp, root, h):
            self.assertEqual(installinfo.detect(root)['kind'], 'vortex')

    def test_no_manifest_means_manual(self):
        with rig(managed=False) as (tmp, root, h):
            self.assertEqual(installinfo.detect(root)['kind'], 'manual')

    def test_second_copy_is_about_staging_not_about_the_manager(self):
        """A Vortex install whose staging folder is gone has no second copy,
        and a tool that answered "Vortex, therefore recoverable" would be
        confidently wrong about the one thing that matters."""
        with rig() as (tmp, root, h):
            self.assertTrue(installinfo.detect(root)['second_copy'])
            with support.environment(VORTEX_TS4_MODS=os.path.join(tmp, 'nope')):
                self.assertFalse(installinfo.detect(root)['second_copy'])

    def test_a_manual_install_never_claims_a_second_copy(self):
        """Found by running it, not by a fixture. Staging detection fell back
        to the machine's real Vortex folder, which exists on any machine that
        has ever run Vortex - so a manual install was told staging held a
        second copy of files staging has never seen. A populated staging folder
        is only a second copy of THIS library if the deployment manifest inside
        Mods ties the two together."""
        with rig(managed=False) as (tmp, root, h):
            full = os.path.join(tmp, 'someone-elses-staging')
            os.makedirs(full, exist_ok=True)
            with open(os.path.join(full, 'x'), 'w') as f:
                f.write('a different library')
            with support.environment(VORTEX_TS4_MODS=full):
                info = installinfo.detect(root)
            self.assertFalse(info['second_copy'])
            self.assertIn('THIS TOOL ONLY',
                          '\n'.join(installinfo.describe(info)))

    def test_an_explicit_staging_path_replaces_the_default(self):
        """Additive lookup is how the bug above happened: a caller naming an
        empty directory to say "no staging here" was answered with the default
        one instead."""
        with rig() as (tmp, root, h):
            empty = os.path.join(tmp, 'empty')
            os.makedirs(empty, exist_ok=True)
            with support.environment(VORTEX_TS4_MODS=empty,
                                     APPDATA=os.path.expanduser('~')):
                self.assertEqual(installinfo.staging_dirs(), [])

    def test_an_empty_staging_folder_is_not_a_second_copy(self):
        with rig() as (tmp, root, h):
            empty = os.path.join(tmp, 'empty-staging')
            os.makedirs(empty, exist_ok=True)
            with support.environment(VORTEX_TS4_MODS=empty):
                self.assertFalse(installinfo.detect(root)['second_copy'])

    def test_a_manual_install_is_told_its_undo_depends_on_this_tool(self):
        with rig(managed=False) as (tmp, root, h):
            with support.environment(VORTEX_TS4_MODS=os.path.join(tmp, 'nope')):
                text = '\n'.join(installinfo.describe(installinfo.detect(root)))
            self.assertIn('THIS TOOL ONLY', text)
            self.assertIn('restore before uninstalling', text)

    def test_a_managed_install_is_told_where_the_second_copy_is(self):
        with rig() as (tmp, root, h):
            text = '\n'.join(installinfo.describe(installinfo.detect(root)))
            self.assertIn('second copy', text)
            self.assertNotIn('THIS TOOL ONLY', text)


class TheLayoutIsDetected(unittest.TestCase):
    """A manual install's shape decides whether one unit is one mod."""

    def test_loose_files_at_the_top_are_a_flat_layout(self):
        with rig(files=('a.package', 'b.package'), managed=False) as (
                tmp, root, h):
            self.assertEqual(installinfo.layout(root)['shape'], 'flat')

    def test_one_folder_per_mod_is_the_shape_bisection_assumes(self):
        with rig(files=('modA/a.package', 'modB/b.package'),
                 managed=False) as (tmp, root, h):
            self.assertEqual(installinfo.layout(root)['shape'], 'folders')

    def test_both_together_is_mixed(self):
        with rig(files=('modA/a.package', 'loose.package'),
                 managed=False) as (tmp, root, h):
            self.assertEqual(installinfo.layout(root)['shape'], 'mixed')

    def test_a_flat_layout_is_warned_about_splitting_multi_file_mods(self):
        """The exact outcome the warning exists for: a mod that ships several
        loose files is several units, so a round can disable half of one -
        which behaves like a broken mod and is not one."""
        with rig(files=('a.package', 'b.package'), managed=False) as (
                tmp, root, h):
            text = '\n'.join(installinfo.describe(installinfo.detect(root)))
            self.assertIn('half', text)

    def test_a_fat_category_folder_is_no_longer_a_hazard(self):
        """It used to be one, and was warned about: units came from the top
        level of Mods, so a folder called "cas" holding thirty mods became a
        single unit and bisecting it could only ever name "cas".

        manual_units() descends to the folder that directly holds the files, so
        the nesting is now the information rather than the problem. The warning
        is gone because the behaviour it warned about is gone.
        """
        many = tuple('cas/mod%02d/f.package' % i for i in range(30))
        with manual_rig(files=many) as (tmp, root):
            info = installinfo.detect(root)
            self.assertEqual(info['layout']['category'], [])
            self.assertNotIn('categories rather than mods',
                             '\n'.join(installinfo.describe(info)))
            got = bs.units(root)
            self.assertEqual(len(got), 30)
            self.assertIn(os.path.join('cas', 'mod00'), got)

    def test_a_managed_install_is_not_given_a_layout_warning(self):
        with rig() as (tmp, root, h):
            info = installinfo.detect(root)
            self.assertEqual(info['layout']['shape'], 'managed')
            self.assertNotIn('half', '\n'.join(installinfo.describe(info)))


class AnOrganisedLibraryIsReadTheWayItWasOrganised(unittest.TestCase):
    """A library filed into named folders already records where one mod ends.
    That is better evidence than anything this tool can infer, so the rule is
    to read it rather than flatten it.

    Taking top-level entries instead made a folder called "Gameplay" one unit
    holding every gameplay mod in the library, so a bisection could name the
    filing cabinet and nothing inside it.
    """

    ORGANISED = ('Gameplay/MCCC/mccc.package',
                 'Gameplay/MCCC/mccc.ts4script',
                 'Gameplay/Basemental/bm.package',
                 'Gameplay/Basemental/Addons/extra.package',
                 'CAS/Hair/skysims/hair.package',
                 'loose.package')

    def units(self, files):
        with manual_rig(files=files) as (tmp, root):
            return bs.units(root)

    def test_a_category_is_descended_into_not_taken_as_one_mod(self):
        got = self.units(self.ORGANISED)
        self.assertNotIn('Gameplay', got)
        self.assertIn(os.path.join('Gameplay', 'MCCC'), got)
        self.assertIn(os.path.join('Gameplay', 'Basemental'), got)

    def test_a_mod_keeps_its_own_subfolder(self):
        """Basemental/Addons belongs to Basemental. Splitting them would make
        a round disable half a mod, which behaves like a broken mod."""
        got = self.units(self.ORGANISED)
        self.assertEqual(got[os.path.join('Gameplay', 'Basemental')],
                         [os.path.join('Gameplay', 'Basemental', 'Addons',
                                       'extra.package'),
                          os.path.join('Gameplay', 'Basemental', 'bm.package')])
        self.assertNotIn(os.path.join('Gameplay', 'Basemental', 'Addons'), got)

    def test_categories_nest_as_deep_as_they_like(self):
        got = self.units(self.ORGANISED)
        self.assertIn(os.path.join('CAS', 'Hair', 'skysims'), got)

    def test_a_loose_file_at_the_top_is_still_its_own_mod(self):
        self.assertIn('loose.package', self.units(self.ORGANISED))

    def test_every_file_lands_in_exactly_one_unit(self):
        """No file may be claimed twice, and none may be dropped - either would
        arm a round that is not the round the caller asked for."""
        got = self.units(self.ORGANISED)
        seen = [rel for files in got.values() for rel in files]
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(len(seen), len(self.ORGANISED))

    def test_a_folder_mixing_packages_and_subfolders_stays_one_mod(self):
        """The two signals disagree. Too coarse costs rounds; splitting a mod
        costs a wrong answer, so it is read as one mod - and flagged."""
        with manual_rig(files=('Mixed/top.package',
                               'Mixed/Sub/inner.package')) as (tmp, root):
            got = bs.units(root)
            self.assertEqual(sorted(got), ['Mixed'])
            self.assertEqual(len(got['Mixed']), 2)
            info = installinfo.detect(root)
            self.assertEqual(info['layout']['ambiguous'], ['Mixed'])
            self.assertIn('loose packages AND',
                          '\n'.join(installinfo.describe(info)))

    def test_an_organised_layout_is_told_it_is_the_good_shape(self):
        with manual_rig(files=self.ORGANISED[:-1]) as (tmp, root):
            text = '\n'.join(installinfo.describe(installinfo.detect(root)))
            self.assertIn('one folder per mod', text)
            self.assertNotIn('behaves like a broken mod', text)

    def test_a_manager_manifest_still_wins(self):
        """None of this applies to a managed install - the manifest is the
        accurate answer and must not be second-guessed by folder shape."""
        with rig() as (tmp, root, h):
            self.assertEqual(sorted(bs.units(root)),
                             ['alpha.package', 'bravo.package'])


class NamingAModInACutFile(unittest.TestCase):

    ORGANISED = ('Gameplay/MCCC/mccc.package',
                 'CAS/Hair/skysims/hair.package',
                 'Gameplay/Fixes/a.package',
                 'CAS/Fixes/b.package')

    def test_a_leaf_name_resolves_when_it_is_unambiguous(self):
        with manual_rig(files=self.ORGANISED) as (tmp, root):
            matched, missing, amb = bs.resolve(root, ['MCCC'])
            self.assertEqual(sorted(matched), [os.path.join('Gameplay', 'MCCC')])
            self.assertEqual((missing, amb), ([], []))

    def test_a_full_path_resolves_with_either_separator(self):
        with manual_rig(files=self.ORGANISED) as (tmp, root):
            for written in ('Gameplay/MCCC', 'Gameplay\\MCCC'):
                matched, _m, _a = bs.resolve(root, [written])
                self.assertEqual(sorted(matched),
                                 [os.path.join('Gameplay', 'MCCC')], written)

    def test_a_leaf_matching_two_mods_is_refused_not_guessed(self):
        """Resolving to whichever sorted first would cut a mod nobody named and
        prove something about a library nobody was testing."""
        with manual_rig(files=self.ORGANISED) as (tmp, root):
            matched, missing, amb = bs.resolve(root, ['Fixes'])
            self.assertEqual(matched, {})
            self.assertEqual(missing, ['Fixes'])
            self.assertEqual(amb[0][0], 'Fixes')
            self.assertEqual(amb[0][1], [os.path.join('CAS', 'Fixes'),
                                         os.path.join('Gameplay', 'Fixes')])

    def test_arming_an_ambiguous_name_moves_nothing(self):
        with manual_rig(files=self.ORGANISED) as (tmp, root):
            before = tree(root)
            code, out = run_bs(['arm', cut(tmp, ['Fixes']), '--root', root])
            self.assertEqual(code, 2)
            self.assertIn('more than one mod', out)
            self.assertEqual(tree(root), before)

    def test_plan_lists_the_candidates_for_an_ambiguous_name(self):
        with manual_rig(files=self.ORGANISED) as (tmp, root):
            code, out = run_bs(['plan', cut(tmp, ['Fixes']), '--root', root])
            self.assertIn('AMBIGUOUS', out)
            self.assertIn(os.path.join('CAS', 'Fixes'), out)
            self.assertIn(os.path.join('Gameplay', 'Fixes'), out)

    def test_plan_can_show_every_file_a_mod_covers(self):
        with manual_rig(files=self.ORGANISED) as (tmp, root):
            code, out = run_bs(['plan', cut(tmp, ['MCCC']), '--root', root,
                                '--files'])
            self.assertIn('mccc.package', out)

    def test_a_name_that_matches_nothing_is_still_reported_missing(self):
        with manual_rig(files=self.ORGANISED) as (tmp, root):
            _m, missing, amb = bs.resolve(root, ['NoSuchMod'])
            self.assertEqual(missing, ['NoSuchMod'])
            self.assertEqual(amb, [])


class StandaloneRecovery(unittest.TestCase):
    """The undo must not need the tool that armed the round."""

    def test_status_reports_what_is_out(self):
        with rig() as (tmp, root, h):
            h.open_session('bisect_mods', installinfo.detect(root))
            arm(h, ['alpha.package'])
            code, out = cli(['status', '--hold', h.dir, '--root', root])
            self.assertEqual(code, 0)
            self.assertIn('1 file(s) out', out)

    def test_restore_puts_them_back(self):
        with rig() as (tmp, root, h):
            h.open_session('bisect_mods', installinfo.detect(root))
            arm(h, ['alpha.package'])
            code, out = cli(['restore', '--hold', h.dir, '--root', root])
            self.assertEqual(code, 0)
            self.assertIn('restored 1', out)
            self.assertTrue(os.path.exists(os.path.join(root,
                                                        rel('alpha.package'))))

    def test_a_holding_directory_that_never_existed_is_not_an_error(self):
        with rig() as (tmp, root, h):
            code, out = cli(['status', '--hold', os.path.join(tmp, 'nope'),
                             '--root', root])
            self.assertEqual(code, 0)
            self.assertIn('nothing was ever moved out', out)


class ArmingAManualInstall(unittest.TestCase):
    """End to end through bisect_mods, which is where the warnings surface."""

    def test_arming_warns_that_this_tool_is_the_only_undo(self):
        with manual_rig() as (tmp, root):
            code, out = run_bs(['arm', cut(tmp, ['a.package']), '--root', root])
            self.assertEqual(code, 0)
            self.assertIn('THIS TOOL ONLY', out)

    def test_a_partial_arm_is_undone_when_there_is_no_second_copy(self):
        """Half a round armed is a state nobody chose, and without a manager
        nothing else can put it right."""
        with manual_rig() as (tmp, root):
            real = holdlog.Hold.hold_file

            def only_the_first(self, mod, rel_):
                if mod == 'b.package':
                    return False, 'disk on fire'
                return real(self, mod, rel_)

            with mock(holdlog.Hold, 'hold_file', only_the_first):
                code, out = run_bs(['arm', cut(tmp, ['a.package', 'b.package']),
                                    '--root', root])
            self.assertEqual(code, 2)
            self.assertIn('the round was undone', out)
            for name in ('a.package', 'b.package'):
                self.assertTrue(os.path.exists(os.path.join(root, name)))

    def test_status_does_not_blame_a_manager_that_is_not_installed(self):
        with manual_rig() as (tmp, root):
            run_bs(['arm', cut(tmp, ['a.package']), '--root', root])
            with open(os.path.join(root, 'a.package'), 'wb') as f:
                f.write(b'put back by hand')
            code, out = run_bs(['status'])
            self.assertEqual(code, 1)
            self.assertIn('Something outside this tool', out)
            self.assertNotIn('mod manager redeployed', out)

    def test_a_folder_mod_is_journalled_as_its_files_not_as_a_folder(self):
        """Found by running it. A folder unit was moved with one rename, so the
        journal held one entry named after a directory while the holding
        directory held the files inside it. Reconciling those two reported the
        directory as MISSING - the loudest thing this tool says - for a mod
        sitting safely on disk, and left the real files with no mod name."""
        with manual_rig(files=('BigMod/one.package', 'BigMod/two.package',
                               'loose.package')) as (tmp, root):
            code, out = run_bs(['arm', cut(tmp, ['BigMod']), '--root', root])
            self.assertEqual(code, 0)
            self.assertIn('2 file(s)', out)
            state = bs.hold(root).held()
            self.assertEqual(state['missing'], [])
            self.assertEqual(state['unjournalled'], [])
            self.assertEqual({i['mod'] for i in state['out']}, {'BigMod'})

    def test_a_folder_mod_round_trips(self):
        with manual_rig(files=('BigMod/one.package',
                               'BigMod/sub/two.package')) as (tmp, root):
            run_bs(['arm', cut(tmp, ['BigMod']), '--root', root])
            code, _ = run_bs(['restore'])
            self.assertEqual(code, 0)
            for rel_ in ('BigMod/one.package', 'BigMod/sub/two.package'):
                self.assertTrue(os.path.exists(os.path.join(root, rel_)),
                                '%s did not come back' % rel_)

    def test_status_does_not_cry_missing_over_a_healthy_round(self):
        with manual_rig(files=('BigMod/one.package', 'loose.package')) as (
                tmp, root):
            run_bs(['arm', cut(tmp, ['BigMod']), '--root', root])
            code, out = run_bs(['status'])
            self.assertEqual(code, 0)
            self.assertNotIn('MISSING', out)
            self.assertNotIn('(unrecorded)', out)

    def test_the_whole_mods_tree_is_identical_after_a_round(self):
        """The promise to anyone who filed their library by hand: their folder
        names and their nesting are theirs, and a round trip returns the tree
        exactly - same directories, same paths, same bytes. Asserted over the
        WHOLE tree rather than the files that moved, because the failure worth
        catching is a tidy-up that removes an emptied folder or flattens a
        level nobody asked it to touch."""
        with manual_rig(files=(
                'Gameplay/MCCC/mccc.package',
                'Gameplay/MCCC/mccc.ts4script',
                'Gameplay/Basemental/bm.package',
                'Gameplay/Basemental/Addons/extra.package',
                'CAS/Hair/skysims/hair.package',
                'loose.package')) as (tmp, root):
            os.makedirs(os.path.join(root, 'Build', 'Empty'), exist_ok=True)
            before = tree(root)
            run_bs(['arm', cut(tmp, ['MCCC', 'Basemental', 'skysims']),
                    '--root', root])
            code, _ = run_bs(['restore'])
            self.assertEqual(code, 0)
            self.assertEqual(tree(root), before)

    def test_arming_leaves_the_folders_standing(self):
        """Emptied folders stay put during a round, so the library still looks
        like the library while a mod is pulled out of it."""
        with manual_rig(files=('Gameplay/MCCC/mccc.package',)) as (tmp, root):
            run_bs(['arm', cut(tmp, ['MCCC']), '--root', root])
            self.assertTrue(os.path.isdir(os.path.join(root, 'Gameplay',
                                                       'MCCC')))

    def test_restore_after_a_lost_ledger_still_works(self):
        """The whole point, end to end: destroy the bookkeeping the tool keeps
        for itself and the mods still go home."""
        with manual_rig() as (tmp, root):
            run_bs(['arm', cut(tmp, ['a.package']), '--root', root])
            os.remove(bs.ledger_path())
            code, out = run_bs(['restore'])
            self.assertEqual(code, 0)
            self.assertIn('restored 1', out)
            self.assertTrue(os.path.exists(os.path.join(root, 'a.package')))


# ---- helpers ----------------------------------------------------------

def tree(root):
    """Every directory and every file under `root`, with contents.

    Directories are included on purpose: a restore that put the files back but
    dropped an emptied folder would pass a files-only comparison and would
    still have rearranged somebody's library.
    """
    out = {}
    for dirpath, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        for d in dirs:
            out[os.path.join(rel_dir, d) + os.sep] = None
        for f in files:
            with open(os.path.join(dirpath, f), 'rb') as fh:
                out[os.path.join(rel_dir, f)] = fh.read()
    return out


@contextlib.contextmanager
def mock(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def cli(argv):
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = holdlog.main(argv)
    return code, buf.getvalue()


def run_bs(argv):
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = bs.main(argv)
    return code, buf.getvalue()


def cut(tmp, names, fname='cut.txt'):
    path = os.path.join(tmp, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(names) + '\n')
    return path


@contextlib.contextmanager
def manual_rig(files=('a.package', 'b.package')):
    """A manual install with bisect_mods reloaded against it."""
    tmp = tempfile.mkdtemp()
    root = mods(tmp, files, managed=False)
    out = os.path.join(tmp, 'out')
    os.makedirs(out, exist_ok=True)
    with support.environment(SIMS4_DIR=tmp, SULSKILL_OUT=out,
                             SULSKILL_BISECT_HOLD=os.path.join(tmp, 'hold'),
                             VORTEX_TS4_MODS=os.path.join(tmp, 'no-staging'),
                             APPDATA=os.path.join(tmp, 'appdata'),
                             SIMS4_GAME_DIR=tmp,
                             SIMS4_LAUNCH_CMD='%s -c pass' % sys.executable), \
            warnings.catch_warnings():
        warnings.simplefilter('ignore', ResourceWarning)
        importlib.reload(bs)
        bs.ts4_started = lambda: None
        bs.LAUNCH_WAIT = 0
        yield tmp, root


if __name__ == '__main__':
    unittest.main()
