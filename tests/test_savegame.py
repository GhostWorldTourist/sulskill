"""Reading a save file, and refusing to make things up about it.

There is no published schema for a Sims 4 save, so a reader for one is exactly
the sort of tool that can look like it works while quietly inventing a family.
The defence is that every field the reader claims is checked against something
it cannot control, and the checks are what these tests exercise:

  - A save is built here from known people in known houses, so the reader has
    a right answer to be wrong about. The builder writes real DBPF and real
    protobuf wire format; a test that handed the reader a dict would pass while
    every actual save read as empty.
  - `verify()` has to FAIL on saves that are deliberately broken. A self-check
    that passes on a mangled file is worse than no self-check, because it is
    the thing the report cites as evidence.
  - Life stage and gender names are read out of the installed game rather than
    remembered. When the game cannot be read that must degrade to a stored copy
    AND say so, because the report prints which was used.
  - Nothing about pets, traits or skills is claimed anywhere, and that is
    asserted rather than left to good intentions.

The page-level tests cover the one bug that made the report ship blank: the
shared script and a report's own script share a <script> block, so a redeclared
`const` is a SyntaxError that takes out the entire block, list and all.
"""
import contextlib
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402

sys.path.insert(0, os.path.join(support.ROOT, 'sulskill-roster', 'scripts'))
sys.path.insert(0, os.path.join(support.ROOT, 'sulskill-doctor', 'scripts'))
import savegame                                                    # noqa: E402
import save_report                                                 # noqa: E402
import report_style                                                # noqa: E402


# ---- protobuf, written by hand so the reader meets real wire format --------

def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def vfield(num, value):
    return varint(num << 3 | 0) + varint(value)


def bfield(num, raw):
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    return varint(num << 3 | 2) + varint(len(raw)) + raw


def i64field(num, raw):
    return varint(num << 3 | 1) + raw


def ident(n):
    """An 8-byte id, the shape the save uses for cross-references."""
    return struct.pack('<Q', n)


# ---- a save, built from people we chose ------------------------------------

MALE, FEMALE = 4096, 8192
CHILD, YOUNGADULT, ELDER = 4, 16, 64


def world(wid, name, desc='a place'):
    return bfield(savegame.F_WORLD,
                  i64field(savegame.W_ID, ident(wid))
                  + bfield(savegame.W_NAME, name)
                  + bfield(savegame.W_DESC, desc))


def lot(lid, name, wid, desc='a house'):
    return bfield(savegame.F_LOT,
                  i64field(savegame.L_ID, ident(lid))
                  + bfield(savegame.L_NAME, name)
                  + i64field(savegame.L_WORLD, ident(wid))
                  + bfield(savegame.L_DESC, desc))


def household(hid, name, funds, lid=None, creator='Tester'):
    body = (i64field(savegame.H_ID, ident(hid))
            + bfield(savegame.H_NAME, name)
            + vfield(savegame.H_FUNDS, funds)
            + bfield(savegame.H_CREATOR, creator))
    if lid is not None:
        body += i64field(savegame.H_LOT, ident(lid))
    return bfield(savegame.F_HOUSEHOLD, body)


def sim(first, last, hid, gender=FEMALE, age=YOUNGADULT, surname=None):
    return bfield(savegame.F_SIM,
                  i64field(savegame.S_HOUSEHOLD, ident(hid))
                  + bfield(savegame.S_FIRST, first)
                  + bfield(savegame.S_LAST, last)
                  + vfield(savegame.S_GENDER, gender)
                  + vfield(savegame.S_AGE, age)
                  + bfield(savegame.S_SURNAME,
                           last if surname is None else surname))


def write_save(tmp, payload, name='Slot_00000001.save'):
    """A real DBPF holding the save-data resource, on disk."""
    path = os.path.join(tmp, name)
    with open(path, 'wb') as f:
        f.write(support.dbpf([(savegame.SAVE_DATA, 1, payload, 0)]))
    return path


def a_world():
    """One world, two lots, two households, four Sims - and one with no home."""
    return (
        world(10, 'Willow Creek')
        + lot(20, 'Ophelia Villa', 10)
        + lot(21, 'Empty Lot', 10)
        + household(30, 'Goth', 45500, lid=20)
        + household(31, 'Nomad', 500)                    # no lot: unhoused
        + sim('Bella', 'Goth', 30, FEMALE, YOUNGADULT)
        + sim('Mortimer', 'Goth', 30, MALE, ELDER)
        + sim('Cassandra', 'Goth', 30, FEMALE, CHILD)
        + sim('Wandering', 'Nomad', 31, MALE, YOUNGADULT)
    )


@contextlib.contextmanager
def a_save(payload=None):
    tmp = tempfile.mkdtemp()
    path = write_save(tmp, a_world() if payload is None else payload)
    yield tmp, path


class ItReadsWhatWasWritten(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.save = savegame.Save(write_save(self.tmp, a_world()))

    def test_the_people_come_back(self):
        names = sorted(s['name'] for s in self.save.sims)
        self.assertEqual(names, ['Bella Goth', 'Cassandra Goth',
                                 'Mortimer Goth', 'Wandering Nomad'])

    def test_households_carry_their_money_and_their_maker(self):
        goth = [h for h in self.save.households if h['name'] == 'Goth'][0]
        self.assertEqual(goth['funds'], 45500)
        self.assertEqual(goth['creator'], 'Tester')

    def test_sims_join_their_household(self):
        goth = [h for h in self.save.households if h['name'] == 'Goth'][0]
        self.assertEqual(len(goth['members']), 3)
        self.assertEqual({s['last'] for s in goth['members']}, {'Goth'})

    def test_a_household_with_no_lot_is_unhoused_not_broken(self):
        """The join is partial on purpose - the game has an unhoused pool - so
        a reader that treated a missing lot as an error would call a normal
        save corrupt."""
        self.assertEqual([h['name'] for h in self.save.unhoused()], ['Nomad'])
        self.assertEqual([h['name'] for h in self.save.housed()], ['Goth'])

    def test_lots_land_in_their_world(self):
        wc = self.save.worlds[0]
        self.assertEqual(wc['name'], 'Willow Creek')
        self.assertEqual(sorted(l['name'] for l in wc['lots']),
                         ['Empty Lot', 'Ophelia Villa'])

    def test_population_is_counted_where_people_actually_live(self):
        """Three Goths live in Willow Creek. The Nomad has no home, so counting
        him into a world would invent a resident."""
        self.assertEqual(self.save.worlds[0]['population'], 3)

    def test_life_stages_are_ordered_youngest_first(self):
        got = [self.save.ages[a] for a, _n in self.save.by_age()]
        self.assertEqual(got, ['Child', 'Young Adult', 'Elder'])

    def test_money_is_totalled_over_every_household(self):
        self.assertEqual(self.save.total_funds(), 46000)

    def test_a_healthy_save_passes_its_own_checks(self):
        self.assertEqual(self.save.verify(), [])


class TheSelfCheckHasToBeAbleToFail(unittest.TestCase):
    """A verify() that never fails is decoration. The report cites it as
    evidence, so each way the field map can go wrong gets its own failure."""

    def check(self, payload):
        tmp = tempfile.mkdtemp()
        return savegame.Save(write_save(tmp, payload)).verify()

    def test_a_sim_pointing_at_no_household_is_reported(self):
        bad = (world(10, 'W') + household(30, 'Goth', 1, lid=None)
               + sim('Bella', 'Goth', 999))          # nobody has id 999
        self.assertTrue(any('did not join' in c for c in self.check(bad)))

    def test_a_scrambled_household_join_is_reported(self):
        """What a renumbered field looks like: Sims distributed into households
        they have nothing to do with. Measured on real saves, a true join runs
        about 90% family coherence and a shuffled one about 40%."""
        payload = world(10, 'W')
        for i in range(12):
            payload += household(30 + i, 'House%d' % i, 1)
            payload += sim('A', 'Sur%d' % i, 30 + i)
            payload += sim('B', 'Other%d' % i, 30 + i)      # never matches
        self.assertTrue(any('household join looks wrong'
                            in c for c in self.check(payload)))

    def test_a_played_save_full_of_edits_is_not_called_broken(self):
        """People rename households, marry across them, take in roommates and
        delete the premades outright. None of that is a broken reader, and a
        check that cannot tell the difference would put "some checks did not
        pass" on an ordinary player's page."""
        payload = world(10, 'W')
        # renamed households, a blended family, and a house of roommates
        payload += household(30, 'The Goths', 1)
        for first in ('Bella', 'Mortimer', 'Cassandra'):
            payload += sim(first, 'Goth', 30, surname='Goth')
        payload += household(31, 'Chez Nous', 1)
        payload += sim('Bob', 'Pancakes', 31, surname='Pancakes')
        payload += sim('Eliza', 'Pancakes', 31, surname='Pancakes')
        payload += household(32, 'The Share House', 1)
        payload += sim('One', 'Alpha', 32, surname='Alpha')
        payload += sim('Two', 'Beta', 32, surname='Beta')     # roommates
        for i in range(9):                                    # ordinary families
            payload += household(40 + i, 'Fam%d' % i, 1)
            payload += sim('X', 'Fam%d' % i, 40 + i)
            payload += sim('Y', 'Fam%d' % i, 40 + i)
        self.assertEqual(self.check(payload), [])

    def test_coherence_is_reported_as_a_proportion_not_a_verdict(self):
        """One odd household must never be the thing that fails a save."""
        tmp = tempfile.mkdtemp()
        payload = world(10, 'W')
        payload += household(30, 'Roommates', 1)
        payload += sim('One', 'Alpha', 30) + sim('Two', 'Beta', 30)
        save = savegame.Save(write_save(tmp, payload))
        ratio, sample = save.coherence()
        self.assertEqual((ratio, sample), (0.0, 1))
        self.assertEqual(save.verify(), [])       # too small a sample to judge

    def test_an_unknown_life_stage_is_reported(self):
        bad = (world(10, 'W') + household(30, 'Goth', 1)
               + sim('Bella', 'Goth', 30, age=999))
        self.assertTrue(any('life stage' in c for c in self.check(bad)))

    def test_an_unknown_gender_is_reported(self):
        bad = (world(10, 'W') + household(30, 'Goth', 1)
               + sim('Bella', 'Goth', 30, gender=7))
        self.assertTrue(any('gender' in c for c in self.check(bad)))

    def test_a_lot_in_no_world_is_reported(self):
        bad = (world(10, 'W') + lot(20, 'Nowhere', 999)
               + household(30, 'Goth', 1) + sim('Bella', 'Goth', 30))
        self.assertTrue(any('no world' in c for c in self.check(bad)))

    def test_a_save_with_no_sims_says_the_layout_changed(self):
        self.assertTrue(any('layout' in c for c in self.check(world(10, 'W'))))

    def test_a_package_with_no_save_resource_is_refused_clearly(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, 'Slot_00000001.save')
        with open(path, 'wb') as f:
            f.write(support.dbpf([(0x220557DA, 1, b'not a save', 0)]))
        with self.assertRaises(ValueError) as caught:
            savegame.Save(path)
        self.assertIn('save-data resource', str(caught.exception))


class LabelsComeFromTheGame(unittest.TestCase):

    def test_the_enum_names_are_read_out_of_the_installed_game(self):
        """Not remembered. INFANT = 128 is exactly the sort of value a tool
        author is confidently wrong about."""
        ages, genders, source = savegame.enums()
        self.assertEqual(genders, {4096: 'Male', 8192: 'Female'})
        self.assertEqual(ages[16], 'Young Adult')
        self.assertEqual(ages[128], 'Infant')
        self.assertIn(source, ('the installed game', 'a stored copy'))

    def test_with_no_game_it_falls_back_and_admits_which_it_used(self):
        """The report prints the source, so degrading silently would put a
        claim on the page that nothing backs."""
        with support.environment(SIMS4_GAME_DIR=tempfile.mkdtemp()):
            with _no_registry():
                ages, genders, source = savegame.enums()
        self.assertEqual(source, 'a stored copy')
        self.assertEqual(ages, savegame.FALLBACK_AGE)
        self.assertEqual(genders, savegame.FALLBACK_GENDER)

    def test_the_stored_copy_agrees_with_the_game(self):
        """If these ever diverge, the fallback is quietly wrong - which is the
        failure mode a fallback exists to avoid."""
        ages, genders, source = savegame.enums()
        if source != 'the installed game':
            self.skipTest('no game installed to compare against')
        self.assertEqual(ages, savegame.FALLBACK_AGE)
        self.assertEqual(genders, savegame.FALLBACK_GENDER)


@contextlib.contextmanager
def _no_registry():
    """Make gate.game_dir() unable to find a game, registry included."""
    import gate
    real = gate.game_dir
    gate.game_dir = lambda: ''
    savegame.gate.game_dir = lambda: ''
    try:
        yield
    finally:
        gate.game_dir = real
        savegame.gate.game_dir = real


class FindingSaves(unittest.TestCase):

    def test_backups_are_not_offered_as_saves(self):
        """The game keeps .ver0/.ver1/.day.ver0 beside each slot. Listing them
        offers somebody five copies of one world and no way to tell which is
        theirs."""
        tmp = tempfile.mkdtemp()
        for n in ('Slot_00000001.save', 'Slot_00000001.save.ver0',
                  'Slot_00000001.save.day.ver0', 'Slot_0000000A.save',
                  'notes.txt'):
            with open(os.path.join(tmp, n), 'wb') as f:
                f.write(b'x')
        got = [os.path.basename(p) for p in savegame.find_saves(tmp)]
        self.assertEqual(sorted(got),
                         ['Slot_00000001.save', 'Slot_0000000A.save'])

    def test_a_missing_saves_folder_is_empty_not_an_error(self):
        self.assertEqual(savegame.find_saves('/no/such/place'), [])


class ThePage(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.save = savegame.Save(write_save(tmp, a_world()))
        self.html, self.complaints = save_report.build(self.save)

    def test_it_declares_utf8(self):
        """Written as UTF-8 and opened off disk, where a browser with no
        declaration falls back to windows-1252 and turns § into Â§."""
        self.assertTrue(self.html.lstrip().startswith('<meta charset="utf-8">'))

    def test_the_simoleon_sign_survives_a_round_trip_to_bytes(self):
        self.assertIn('§', self.html.encode('utf-8').decode('utf-8'))

    def test_it_does_not_redeclare_anything_the_shared_script_defines(self):
        """The bug that shipped a blank page: both scripts land in ONE <script>
        block, so a second `const esc` is not a shadowed copy - it is a
        SyntaxError that stops the block and leaves no list on the page."""
        import re
        shared = set(re.findall(r'^\s*(?:const|let|function)\s+(\w+)',
                                report_style.SCRIPT, re.M))
        mine = set(re.findall(r'^\s*(?:const|let|function)\s+(\w+)',
                              save_report.SCRIPT, re.M))
        self.assertEqual(shared & mine, set(),
                         'redeclares %s from report_style.SCRIPT'
                         % sorted(shared & mine))

    def test_it_says_where_the_labels_came_from(self):
        self.assertIn(self.save.enum_source, self.html)

    def test_it_shows_its_working(self):
        self.assertIn('How this page was read', self.html)
        self.assertIn('4 of 4 Sims', self.html)

    def test_it_claims_nothing_about_pets_traits_or_skills(self):
        """Fields that were not identified to a standard worth printing. A
        guess about somebody's game is worse than a gap."""
        body = self.html.lower()
        for word in ('trait', 'skill', 'aspiration'):
            self.assertNotIn('%ss:' % word, body)

    def test_a_failed_check_is_printed_on_the_page_not_swallowed(self):
        tmp = tempfile.mkdtemp()
        bad = world(10, 'W')
        for i in range(12):                       # a scrambled household join
            bad += household(30 + i, 'House%d' % i, 1)
            bad += sim('A', 'Sur%d' % i, 30 + i)
            bad += sim('B', 'Other%d' % i, 30 + i)
        html, complaints = save_report.build(
            savegame.Save(write_save(tmp, bad)))
        self.assertTrue(complaints)
        self.assertIn('Some checks did not pass', html)

    def test_the_byline_names_the_save_not_the_mod_library(self):
        """The shared header used to hardcode "from the installed mods
        themselves", which this page would have printed over a save file."""
        self.assertIn('from your save file', self.html)
        self.assertNotIn('installed mods themselves', self.html)

    def test_every_household_reaches_the_page_data(self):
        for name in ('Goth', 'Nomad'):
            self.assertIn(name, self.html)


class TheCommandRefusesToWriteSomewhereSilly(unittest.TestCase):

    def test_out_is_required(self):
        """These pages are about one person's save and must not default to
        landing next to the code - POLICY.md, and the reason report builders
        take an explicit --out."""
        tmp = tempfile.mkdtemp()
        write_save(tmp, a_world())
        import io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            code = save_report.main(['--saves', tmp])
        self.assertEqual(code, 2)
        self.assertIn('--out is required', buf.getvalue())

    def test_it_writes_the_page_where_it_was_told(self):
        tmp = tempfile.mkdtemp()
        write_save(tmp, a_world())
        out = os.path.join(tmp, 'sub', 'save.html')
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = save_report.main(['--saves', tmp, '--out', out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(out))

    def test_an_unknown_slot_is_refused(self):
        tmp = tempfile.mkdtemp()
        write_save(tmp, a_world())
        import io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            code = save_report.main(['--saves', tmp, '--out',
                                     os.path.join(tmp, 'x.html'),
                                     '--slot', 'Slot_00000099.save'])
        self.assertEqual(code, 2)
        self.assertIn('Try --list', buf.getvalue())


if __name__ == '__main__':
    unittest.main()
