"""Lifespan scaling: does a setting move, by how much, and does it stay put.

Written from the design, not from the implementation. The claims under test are
the ones stated in sulskill-kuttoe/SKILL.md and in `_scaling_about` in
kuttoe_descriptions.json - the scale is derived and never stored, every value is
recomputed from the MOD DEFAULT so repeated runs cannot compound, a pin is a
chosen value rather than a note about one, and a setting that repeats forever is
left alone no matter how long a life gets. Each test asserts one of those
promises. Where the code disagrees with a promise, the test is right.

The failure this suite exists to catch is compounding. `rescale` is safe to run
twice only because it computes from `base`; the moment anything reads the
current value instead, a second run multiplies an already-scaled number and the
config drifts a little further every time it is touched. Nothing about that
looks wrong in a diff - the numbers are plausible, just increasingly absurd -
so it would be found by a Sim waiting eleven sim-years for a spell.

Everything runs against a synthetic install in a temp directory: invented mods,
invented settings, an invented lifespan. Nothing here reads the machine's real
config, so these mean the same thing on any machine, and no fact about anyone's
library or play style is recorded in this repository.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KUTTOE_PY = os.path.join(ROOT, 'sulskill-kuttoe', 'scripts', 'kuttoe.py')
DESCS_JSON = os.path.join(ROOT, 'sulskill-kuttoe', 'reference',
                          'kuttoe_descriptions.json')
SCHEMA_JSON = os.path.join(ROOT, 'sulskill-kuttoe', 'reference',
                           'kuttoe_schema.json')


def _load_module():
    """Import kuttoe.py by path - it is a script, not an installed package."""
    spec = importlib.util.spec_from_file_location('kuttoe_under_test',
                                                  KUTTOE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


k = _load_module()


class Rig(unittest.TestCase):
    """A synthetic install `rescale` can be pointed at.

    Builds a schema, a descriptions file, a profile and real config files on
    disk, then redirects the module's globals at them. Config files are real
    because the write path reads and rewrites them, and a test that stubbed
    that out would not notice the file being written in the wrong shape.
    """

    #: Overridden per test class. addr -> scaling metadata.
    SCALING = {}
    #: Overridden per test. mod -> {key: starting value on disk}.
    CONFIG = {}
    ACTIVE_DAYS = 560
    REFERENCE_DAYS = 94
    PINS = {}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        mods = {}
        for mod, values in self.CONFIG.items():
            path = os.path.join(self.tmp, f'[Kuttoe] {mod}_Settings.cfg')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                json.dump(values, f, indent=4)
            mods[mod] = {
                'config': path,
                'settings': {key: {'current': val}
                             for key, val in values.items()},
            }

        self.schema_path = os.path.join(self.tmp, 'schema.json')
        self._dump(self.schema_path, {'mods': mods})

        self.descs_path = os.path.join(self.tmp, 'descs.json')
        self._dump(self.descs_path, {'settings': {}, 'patterns': [],
                                     'scaling': self.SCALING})

        self.profile_path = os.path.join(self.tmp, 'profile.json')
        self._dump(self.profile_path, {
            'lifespan': {'active_days': self.ACTIVE_DAYS,
                         'reference_days': self.REFERENCE_DAYS},
            'scaling': {'pins': dict(self.PINS)},
        })

        self._patch('SCHEMA', self.schema_path)
        self._patch('DESCS', self.descs_path)
        self._patch('PROFILE', self.profile_path)
        # Never shell out to tasklist from a test; the guard itself is not
        # what is under test here.
        self._patch('game_running', lambda: False)

    def _dump(self, path, obj):
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(obj, f, indent=2)

    def _patch(self, name, value):
        old = getattr(k, name)
        setattr(k, name, value)
        self.addCleanup(setattr, k, name, old)

    def rescale(self, scale=None, dry_run=False):
        """Run the command, return its printed report."""
        args = types.SimpleNamespace(scale=scale, dry_run=dry_run, force=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            k.cmd_rescale(args)
        return buf.getvalue()

    def value(self, mod, key):
        """Read a setting back off disk, which is the only thing that counts."""
        path = os.path.join(self.tmp, f'[Kuttoe] {mod}_Settings.cfg')
        with open(path, encoding='utf-8') as f:
            return json.load(f)[key]


class DerivedScale(unittest.TestCase):
    """The scale is computed from the lifespan, never stored beside it.

    The whole reason there is no `time_scale` field in the profile is that a
    hand-maintained copy of a derivable number goes stale the moment the
    lifespan preset changes, and nothing complains when it does.
    """

    def scale(self, active, reference):
        return k.time_scale({'lifespan': {'active_days': active,
                                          'reference_days': reference}})

    def test_scale_is_active_over_reference(self):
        self.assertAlmostEqual(self.scale(560, 94), 560 / 94)

    def test_a_reference_length_life_needs_no_scaling(self):
        self.assertEqual(self.scale(94, 94), 1.0)

    def test_switching_preset_is_the_only_action_required(self):
        """Doubling the lifespan doubles the scale, with nothing else touched."""
        self.assertAlmostEqual(self.scale(1120, 94), self.scale(560, 94) * 2)

    def test_a_shorter_than_reference_life_scales_down(self):
        self.assertLess(self.scale(47, 94), 1.0)


class Direction(unittest.TestCase):
    """up multiplies, down divides, no declines to answer.

    `down` exists for values written as a percentage of normal, where a longer
    life wants a SMALLER number. It is the same intention as `up` against an
    inverted encoding, so the two must stay exact inverses of each other.
    """

    def test_up_multiplies_the_base(self):
        self.assertEqual(k.rescaled(3, 'up', 6.0), 18)

    def test_down_divides_the_base(self):
        self.assertEqual(k.rescaled(100, 'down', 4.0), 25)

    def test_up_and_down_are_inverses(self):
        self.assertAlmostEqual(k.rescaled(100.0, 'up', 4.0) / 100.0,
                               100.0 / k.rescaled(100.0, 'down', 4.0),
                               places=6)

    def test_no_declines_to_produce_a_value(self):
        self.assertIsNone(k.rescaled(4320, 'no', 6.0))

    def test_a_scale_of_one_changes_nothing(self):
        self.assertEqual(k.rescaled(240, 'up', 1.0), 240)
        self.assertEqual(k.rescaled(240, 'down', 1.0), 240)

    def test_an_int_setting_stays_an_int(self):
        """The config cannot distinguish 240 from 240.0, and the framework's
        validate_int rejects the float - so a scaled int must not become one."""
        out = k.rescaled(240, 'up', 5.957446808510638)
        self.assertIsInstance(out, int)
        self.assertEqual(out, 1430)

    def test_a_float_setting_stays_a_float(self):
        out = k.rescaled(1.5, 'up', 5.957446808510638)
        self.assertIsInstance(out, float)
        self.assertAlmostEqual(out, 8.94)

    def test_a_float_keeps_two_decimals(self):
        """Enough precision to matter, few enough digits to read."""
        self.assertEqual(k.rescaled(0.33, 'up', 3.0), 0.99)


class ComputedFromBase(Rig):
    """Every run recomputes from the mod default, so runs cannot compound.

    This is the property that makes `rescale` safe to run whenever, which is
    in turn what makes "just switch the preset" a true statement.
    """

    SCALING = {
        'Warfare.days_at_war': {'base': 3, 'scale': 'up', 'unit': 'days',
                                'why': 'A finite tour of duty.'},
    }
    CONFIG = {'Warfare': {'days_at_war': 3}}
    ACTIVE_DAYS = 564          # exactly 6x reference, so the arithmetic is
    REFERENCE_DAYS = 94        # obvious on inspection rather than rounded

    def test_first_run_scales_the_default(self):
        self.rescale()
        self.assertEqual(self.value('Warfare', 'days_at_war'), 18)

    def test_running_twice_does_not_compound(self):
        self.rescale()
        self.rescale()
        self.assertEqual(self.value('Warfare', 'days_at_war'), 18)

    def test_the_second_run_reports_nothing_to_do(self):
        self.rescale()
        self.assertIn('already in sync', self.rescale())

    def test_an_already_scaled_value_is_not_scaled_again(self):
        """The exact shape of the compounding bug: the config already holds a
        scaled number, and the run must ignore it in favour of `base`."""
        self.CONFIG['Warfare']['days_at_war'] = 18
        self.setUp()
        self.rescale()
        self.assertEqual(self.value('Warfare', 'days_at_war'), 18)

    def test_a_hand_mangled_value_is_recovered_not_multiplied(self):
        self.CONFIG['Warfare']['days_at_war'] = 9999
        self.setUp()
        self.rescale()
        self.assertEqual(self.value('Warfare', 'days_at_war'), 18)

    def test_a_dry_run_writes_nothing(self):
        report = self.rescale(dry_run=True)
        self.assertIn('18', report)
        self.assertEqual(self.value('Warfare', 'days_at_war'), 3)

    def test_an_explicit_scale_overrides_the_lifespan(self):
        self.rescale(scale=2.0)
        self.assertEqual(self.value('Warfare', 'days_at_war'), 6)

    def test_an_explicit_scale_does_not_change_the_profile(self):
        """`--scale` is a what-if. It must not quietly become the new setting."""
        before = open(self.profile_path, encoding='utf-8').read()
        self.rescale(scale=2.0)
        self.assertEqual(open(self.profile_path, encoding='utf-8').read(),
                         before)


class LeftAlone(Rig):
    """`no` means never written, however far the config has drifted.

    A repeating trait trigger has no end state to run out of. Stretching it
    does not preserve anything - it just makes the trait look broken - so the
    correct action is no action, including no correction back to the default.
    """

    SCALING = {
        'Traits.hobby_cooldown_days': {
            'base': 2, 'scale': 'no', 'unit': 'days',
            'why': 'Ambient trait flavour with no end state.'},
    }
    CONFIG = {'Traits': {'hobby_cooldown_days': 7}}

    def test_a_no_setting_is_not_written(self):
        self.rescale()
        self.assertEqual(self.value('Traits', 'hobby_cooldown_days'), 7)

    def test_a_no_setting_is_not_reset_to_its_default(self):
        """Deliberately distinct from 'not scaled'. The user's own 7 stands."""
        self.rescale()
        self.assertNotEqual(self.value('Traits', 'hobby_cooldown_days'), 2)

    def test_the_reason_is_reported_rather_than_the_setting_vanishing(self):
        report = self.rescale(dry_run=True)
        self.assertIn('hobby_cooldown_days', report)
        self.assertIn('no end state', report)


class Pins(Rig):
    """A pin is the setting, not a note about it.

    Two settings that derive identically can still want different values, and
    no scalar expresses that. So a pin is written like anything else - it is
    only exempt from being COMPUTED.
    """

    SCALING = {
        'Magic.tome_cooldown': {'base': 240, 'scale': 'up',
                                'unit': 'sim-minutes', 'why': 'Finite.'},
        'Magic.teachspell_cooldown': {'base': 3600, 'scale': 'up',
                                      'unit': 'sim-minutes', 'why': 'Finite.'},
    }
    CONFIG = {'Magic': {'tome_cooldown': 240, 'teachspell_cooldown': 3600}}
    PINS = {'Magic.teachspell_cooldown': 10080}

    def test_a_pin_is_written(self):
        self.rescale()
        self.assertEqual(self.value('Magic', 'teachspell_cooldown'), 10080)

    def test_a_pin_beats_what_the_scale_would_give(self):
        derived = k.rescaled(3600, 'up', 560 / 94)
        self.assertNotEqual(derived, 10080)          # otherwise this proves nothing
        self.rescale()
        self.assertEqual(self.value('Magic', 'teachspell_cooldown'), 10080)

    def test_an_unpinned_neighbour_still_derives(self):
        self.rescale()
        self.assertEqual(self.value('Magic', 'tome_cooldown'),
                         k.rescaled(240, 'up', 560 / 94))

    def test_a_pin_survives_a_second_run(self):
        self.rescale()
        self.rescale()
        self.assertEqual(self.value('Magic', 'teachspell_cooldown'), 10080)

    def test_a_pin_is_reported_as_chosen_rather_than_derived(self):
        self.assertIn('by hand', self.rescale(dry_run=True))

    def test_the_report_shows_the_value_on_disk_not_a_stale_snapshot(self):
        """The dry run's `now` column must agree with the write path, or the
        preview says a change is pending that has already happened."""
        self.rescale()
        report = self.rescale(dry_run=True)
        self.assertIn('(now 10080)', report)


class AuthorsRatio(Rig):
    """Scaling one half of a deliberate ratio destroys the mechanic.

    Kuttoe sets the two spellbook routes 15:1 on purpose - the rare route is
    the rare one. Pinning the rarer and deriving the commoner silently flattens
    that to about 7:1, which is not a smaller change but a different mod. Both
    ends are therefore pinned, and this is the test that says why.
    """

    SCALING = {
        'Magic.tome_cooldown': {'base': 240, 'scale': 'up',
                                'unit': 'sim-minutes', 'why': 'Finite.'},
        'Magic.teachspell_cooldown': {'base': 3600, 'scale': 'up',
                                      'unit': 'sim-minutes', 'why': 'Finite.'},
    }
    CONFIG = {'Magic': {'tome_cooldown': 240, 'teachspell_cooldown': 3600}}

    def ratio(self):
        return (self.value('Magic', 'teachspell_cooldown')
                / self.value('Magic', 'tome_cooldown'))

    def test_the_defaults_are_fifteen_to_one(self):
        self.assertEqual(3600 / 240, 15.0)

    def test_scaling_both_ends_preserves_the_ratio(self):
        """A uniform scale is ratio-preserving; it is the pin that endangers it."""
        self.rescale()
        self.assertAlmostEqual(self.ratio(), 15.0, delta=0.05)

    def test_pinning_one_end_alone_breaks_the_ratio(self):
        self.PINS = {'Magic.teachspell_cooldown': 10080}
        self.setUp()
        self.rescale()
        self.assertLess(self.ratio(), 10.0)

    def test_pinning_both_ends_restores_it_exactly(self):
        self.PINS = {'Magic.teachspell_cooldown': 10080,
                     'Magic.tome_cooldown': 672}
        self.setUp()
        self.rescale()
        self.assertEqual(self.ratio(), 15.0)


class Clamping(Rig):
    """A range that cannot express the lifespan is a finding, not a silent cap.

    When the scaled value runs off the end of what a mod will accept, the
    number is capped - but quietly capping it would hide the actual conclusion,
    which is usually that some paired setting is the real dial.
    """

    SCALING = {
        'Aliens.hours_between_visits': {
            'base': 24, 'scale': 'up', 'unit': 'hours', 'max': 24,
            'why': 'Finite rationed event.'},
        'Aliens.visit_length': {
            'base': 6, 'scale': 'down', 'unit': 'hours', 'min': 4,
            'why': 'Inverted encoding.'},
    }
    CONFIG = {'Aliens': {'hours_between_visits': 24, 'visit_length': 6}}

    def test_a_value_over_the_maximum_is_capped(self):
        self.rescale()
        self.assertEqual(self.value('Aliens', 'hours_between_visits'), 24)

    def test_the_cap_is_reported_not_swallowed(self):
        report = self.rescale(dry_run=True)
        self.assertIn('CLAMPED', report)
        self.assertIn('max is 24', report)

    def test_the_report_says_what_was_wanted(self):
        report = self.rescale(dry_run=True)
        self.assertIn(str(k.rescaled(24, 'up', 560 / 94)), report)

    def test_a_value_under_the_minimum_is_raised(self):
        self.rescale()
        self.assertEqual(self.value('Aliens', 'visit_length'), 4)

    def test_a_clamped_value_is_stable_across_runs(self):
        self.rescale()
        self.rescale()
        self.assertEqual(self.value('Aliens', 'hours_between_visits'), 24)


class InRange(Rig):
    """A declared range that the value sits inside must not touch it."""

    SCALING = {
        'Aliens.hours_between_visits': {
            'base': 2, 'scale': 'up', 'unit': 'hours', 'min': 1, 'max': 24,
            'why': 'Finite rationed event.'},
    }
    CONFIG = {'Aliens': {'hours_between_visits': 2}}
    ACTIVE_DAYS = 188
    REFERENCE_DAYS = 94

    def test_a_value_inside_the_range_is_left_at_the_computed_number(self):
        self.rescale()
        self.assertEqual(self.value('Aliens', 'hours_between_visits'), 4)

    def test_nothing_is_reported_as_clamped(self):
        self.assertNotIn('CLAMPED', self.rescale(dry_run=True))


class ShippedReferenceData(unittest.TestCase):
    """The committed scaling metadata is complete and addresses real settings.

    A typo in an address is invisible: the entry simply never matches, the
    setting silently never scales, and the report looks correct because the
    line is absent rather than wrong.
    """

    @classmethod
    def setUpClass(cls):
        with open(DESCS_JSON, encoding='utf-8') as f:
            cls.descs = json.load(f)
        cls.scaling = cls.descs.get('scaling', {})

    def test_there_is_scaling_metadata_at_all(self):
        self.assertTrue(self.scaling)

    def test_the_design_is_explained_in_the_file_itself(self):
        """The file has to carry its own reasoning; whoever reads it next will
        not have the conversation that produced it."""
        self.assertIn('_scaling_about', self.descs)

    def test_every_entry_declares_a_base(self):
        for addr, meta in self.scaling.items():
            with self.subTest(addr=addr):
                self.assertIn('base', meta)
                self.assertIsInstance(meta['base'], (int, float))

    def test_every_entry_declares_a_known_direction(self):
        for addr, meta in self.scaling.items():
            with self.subTest(addr=addr):
                self.assertIn(meta.get('scale'), ('up', 'down', 'no'))

    def test_every_entry_declares_its_unit(self):
        """Cooldowns are stored in sim-minutes where the mod page documents
        hours; without the unit a reader converts the number wrongly."""
        for addr, meta in self.scaling.items():
            with self.subTest(addr=addr):
                self.assertTrue(meta.get('unit'))

    def test_every_entry_says_why_in_words(self):
        for addr, meta in self.scaling.items():
            with self.subTest(addr=addr):
                self.assertGreater(len(meta.get('why', '')), 20,
                                   'the reason is the point of the entry')

    def test_a_range_is_ordered(self):
        for addr, meta in self.scaling.items():
            if 'min' in meta and 'max' in meta:
                with self.subTest(addr=addr):
                    self.assertLess(meta['min'], meta['max'])

    def test_addresses_are_mod_dot_key(self):
        for addr in self.scaling:
            with self.subTest(addr=addr):
                self.assertIn('.', addr)

    def test_every_address_exists_in_the_schema(self):
        if not os.path.exists(SCHEMA_JSON):
            self.skipTest('schema is generated; run extract_kuttoe.py')
        with open(SCHEMA_JSON, encoding='utf-8') as f:
            mods = json.load(f)['mods']
        for addr in self.scaling:
            mod, key = addr.split('.', 1)
            with self.subTest(addr=addr):
                self.assertIn(mod, mods)
                self.assertIn(key, mods[mod].get('settings', {}))


if __name__ == '__main__':
    unittest.main(verbosity=2)
