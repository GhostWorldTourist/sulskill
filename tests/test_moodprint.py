"""moodprint: who wins a contested buff, and what winning changed.

The quiet failure here is confident wrongness. Every other tool in this
repository can be wrong by finding nothing; this one is wrong by naming the
wrong mod as the winner and printing a clean, plausible report about it.
Nothing raises, the counts look right, and the player disables a mod that was
already losing.

That risk sits almost entirely in one line - the load-order sort - so it is
asserted from the game's behaviour rather than from the implementation:

  - The game reads Mods in **case-insensitive** path order and the **last**
    read of a resource key wins. Python's default sort is case-*sensitive*,
    which puts every capitalised filename ahead of every lowercase one and
    silently reverses the outcome for those pairs.
  - Punctuation sorts ahead of letters, so a file named to sort early loses.
    This is the opposite of what the `!` prefix convention is meant to do, and
    it is the finding the tool exists to surface, so it is pinned here.

The rest cover reporting a change as no change: an absent weight read as 0, a
mood id whose value is followed by an inline XML comment, and a buff the reader
could not decode being dropped rather than counted.

No package here is a real mod. The names are invented.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402

sys.path.insert(0, os.path.join(support.ROOT, 'sulskill-doctor', 'scripts'))
import moodprint as mp                                             # noqa: E402


TENSE, HAPPY, SAD = 14645, 14640, 14643


def buff(name, mood=None, weight=None, visible=None, comment=''):
    """Buff tuning as the game ships it, one line per field.

    `comment` puts an XML comment between the mood value and its closing tag,
    which is where EA and every mod author put the mood's name. A matcher
    anchored on </T> reads none of those - about five in six real buffs.
    """
    body = ''
    if mood is not None:
        body += '  <T n="mood_type">%d%s</T>\n' % (mood, comment)
    if weight is not None:
        body += '  <T n="mood_weight">%d</T>\n' % weight
    if visible is not None:
        body += '  <T n="visible">%s</T>\n' % ('True' if visible else 'False')
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<I c="Buff" i="buff" m="buffs.buff" n="%s" s="1">\n%s</I>\n'
            % (name, body)).encode('utf-8')


def mood(name):
    return ('<I c="Mood" i="mood" m="statistics.mood" n="%s" s="1"/>\n'
            % name).encode('utf-8')


class Library(unittest.TestCase):
    """A synthetic Mods folder, built one package at a time."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def pkg(self, name, *entries, **kw):
        """entries: (instance, payload) or (instance, payload, codec)."""
        sub = kw.get('sub')
        d = os.path.join(self.root, sub) if sub else self.root
        os.makedirs(d, exist_ok=True)
        rows = [(kw.get('type_id', mp.BUFF), e[0], e[1],
                 e[2] if len(e) > 2 else 0x5A42) for e in entries]
        support.write_pkg(d, name, rows)

    def run_it(self):
        return mp.analyse(self.root, quiet=True)

    def winner(self, res, instance):
        for c in res['changes']:
            if c['instance'] == instance:
                return c
        return None


class LoadOrder(Library):

    def test_case_does_not_decide_the_winner(self):
        # 'apex' vs 'Broad': case-insensitively apex loses, case-sensitively
        # 'Broad' (B, 66) sorts first and apex would win. A default sort here
        # names the wrong mod in every mixed-case pair in a real library.
        self.pkg('apex_traits.package', (500, buff('b', TENSE, 5)))
        self.pkg('Broad_traits.package', (500, buff('b', HAPPY, 5)))
        c = self.winner(self.run_it(), 500)
        self.assertEqual(c['winner'], 'Broad_traits.package')
        self.assertEqual(c['loser'], 'apex_traits.package')

    def test_punctuation_sorts_ahead_of_letters_and_therefore_loses(self):
        # The finding this tool exists to surface: a file named to load first
        # is read first, and the last read wins, so it loses every argument.
        self.pkg('!addon_stronger.package', (700, buff('b', TENSE, 90)))
        self.pkg('base_traits.package', (700, buff('b', TENSE, 5)))
        res = self.run_it()
        self.assertEqual(self.winner(res, 700)['loser'], '!addon_stronger.package')
        dead = res['fully_eclipsed']
        self.assertEqual([d['file'] for d in dead], ['!addon_stronger.package'])
        # Naming the loser without naming who beat it leaves the reader with
        # nothing to do about it.
        self.assertEqual(dead[0]['beaten_by'], [('base_traits.package', 1)])

    def test_a_package_that_lost_only_some_buffs_is_not_called_eclipsed(self):
        self.pkg('!addon.package', (10, buff('a', TENSE, 5)),
                 (11, buff('b', SAD, 5)))
        self.pkg('base.package', (10, buff('a', HAPPY, 5)))
        self.assertEqual(self.run_it()['fully_eclipsed'], [])

    def test_order_is_over_the_path_not_the_filename(self):
        # The folder is part of the sort, so where a mod is installed changes
        # who wins. These two are chosen so the two schemes *disagree*: by
        # path, 'mmm...' precedes 'sub/aaa...' and the subfolder wins; by
        # basename, 'aaa...' precedes 'mmm...' and the root file wins. An
        # earlier fixture here had them agree, so it asserted the right
        # property and could not have caught the wrong one.
        self.pkg('mmm_traits.package', (20, buff('b', TENSE, 5)))
        self.pkg('aaa_traits.package', (20, buff('b', HAPPY, 5)), sub='Sub')
        c = self.winner(self.run_it(), 20)
        self.assertEqual((c['winner'], c['loser']),
                         ('aaa_traits.package', 'mmm_traits.package'))


class WhatChanged(Library):

    def test_an_inline_comment_does_not_hide_the_mood(self):
        self.pkg('a.package',
                 (30, buff('b', TENSE, 5, comment='<!--Mood_Stressed-->')))
        self.pkg('b.package', (30, buff('b', HAPPY, 5)))
        c = self.winner(self.run_it(), 30)
        self.assertEqual(c['changed'], [['mood', 'Tense', 'Happy']])

    def test_an_absent_weight_is_unstated_not_zero(self):
        # A buff that states weight 0 was deliberately silenced. One that
        # states none may inherit anything. Printing both as 0 reports a real
        # change as no change, and hides the silencing this tool looks for.
        self.pkg('a.package', (40, buff('b', TENSE, 5)))
        self.pkg('b.package', (40, buff('b', TENSE)))
        c = self.winner(self.run_it(), 40)
        self.assertEqual(c['changed'], [['weight', 5, 'unstated']])
        self.assertEqual(self.run_it()['ledger']['Tense']['weight_unstated'], 1)

    def test_identical_definitions_are_not_reported_as_a_change(self):
        self.pkg('a.package', (50, buff('b', TENSE, 5)))
        self.pkg('b.package', (50, buff('b', TENSE, 5)))
        res = self.run_it()
        self.assertEqual(res['contested'], 1)
        self.assertEqual(res['changes'], [])

    def test_visibility_alone_is_a_change(self):
        self.pkg('a.package', (60, buff('b', TENSE, 5)))
        self.pkg('b.package', (60, buff('b', TENSE, 5, visible=False)))
        c = self.winner(self.run_it(), 60)
        self.assertEqual(c['changed'], [['visible', True, False]])
        self.assertEqual(self.run_it()['ledger']['Tense']['invisible'], 1)


class Silenced(Library):
    """The change that looks like nothing happened.

    The moodlet still appears in game. It just stops moving the Sim's emotion,
    which is the one override effect a player cannot see and cannot attribute.
    Both routes to it are asserted, because the detector fired zero times on
    the library it was written against and a detector that has never fired has
    not been shown to work.
    """

    def test_dropping_the_mood_entirely_is_silencing(self):
        self.pkg('a.package', (70, buff('b', TENSE, 5)))
        self.pkg('b.package', (70, buff('b')))
        c = self.winner(self.run_it(), 70)
        self.assertTrue(c['silenced'])
        self.assertEqual(c['changed'][0], ['mood', 'Tense', 'none'])

    def test_keeping_the_mood_at_zero_weight_is_silencing(self):
        self.pkg('a.package', (80, buff('b', TENSE, 5)))
        self.pkg('b.package', (80, buff('b', TENSE, 0)))
        self.assertTrue(self.winner(self.run_it(), 80)['silenced'])

    def test_a_rebalance_is_not_silencing(self):
        self.pkg('a.package', (90, buff('b', TENSE, 5)))
        self.pkg('b.package', (90, buff('b', TENSE, 1)))
        self.assertFalse(self.winner(self.run_it(), 90)['silenced'])

    def test_giving_a_mood_to_a_buff_that_had_none_is_not_silencing(self):
        self.pkg('a.package', (91, buff('b')))
        self.pkg('b.package', (91, buff('b', TENSE, 5)))
        self.assertFalse(self.winner(self.run_it(), 91)['silenced'])


class Ledger(Library):

    def test_only_the_winner_is_counted(self):
        # Summing every definition instead of every winner inflates the census
        # by exactly the mods that are not running, which is the number the
        # tool exists to correct.
        self.pkg('a.package', (100, buff('b', TENSE, 40)))
        self.pkg('b.package', (100, buff('b', HAPPY, 7)))
        led = self.run_it()['ledger']
        self.assertNotIn('Tense', led)
        self.assertEqual(led['Happy']['weight'], 7)

    def test_an_extreme_weight_is_flagged(self):
        self.pkg('a.package', (110, buff('b', SAD, mp.HAMMER * 7)))
        res = self.run_it()
        self.assertEqual(res['hammers'][0]['weight'], mp.HAMMER * 7)
        self.assertEqual(res['ledger']['Sad']['hammers'], 1)

    def test_a_buff_that_names_no_mood_is_left_out(self):
        self.pkg('a.package', (120, buff('b')))
        self.assertEqual(self.run_it()['ledger'], {})

    def test_a_buff_the_reader_cannot_decode_is_counted_not_dropped(self):
        # Silence towards "clear" is the failure mode of every reader here. A
        # buff that could not be opened is not a buff that does nothing.
        self.pkg('a.package', (130, b'not a valid stream', 0x1234))
        res = self.run_it()
        self.assertEqual(res['unreadable_buffs'], 1)
        self.assertEqual(res['buffs'], 1)


class MoodNames(Library):

    def test_a_custom_mood_is_named_from_its_own_tuning(self):
        # 900001 is in no table anywhere. Without reading the Mood resource the
        # report prints an id, and an id is not something a player can act on.
        self.pkg('m.package', (900001, mood('Someone:Custom_Mood_Grumpy')),
                 type_id=mp.MOOD)
        self.pkg('a.package', (140, buff('b', 900001, 5)))
        self.assertIn('Custom_Grumpy', self.run_it()['ledger'])

    def test_one_mood_in_a_package_keeps_its_name(self):
        # The shared-prefix strip must never eat the last segment: a package
        # shipping one mood shares its whole name with itself.
        self.assertEqual(mp._shorten({1: 'Someone:Grumpy_Mood'}), {1: 'Grumpy'})

    def test_a_shared_author_prefix_is_not_the_mood_name(self):
        short = mp._shorten({1: 'X:Someone_Tripping_Mood',
                             2: 'X:Someone_Stoned_Mood'})
        self.assertEqual(set(short.values()), {'Tripping', 'Stoned'})

    def test_a_known_id_is_not_renamed_by_a_mod(self):
        # A mod shipping its own Mood tuning at an EA id must not rewrite what
        # every other buff in the library means by that id.
        self.pkg('m.package', (TENSE, mood('Someone:Renamed')),
                 type_id=mp.MOOD)
        self.pkg('a.package', (150, buff('b', TENSE, 5)))
        self.assertIn('Tense', self.run_it()['ledger'])


class Dereference(Library):
    """A package filename is not something anyone can act on."""

    def test_findings_name_the_mod_the_manager_knows(self):
        os.makedirs(os.path.join(self.root, 'Vortex Mods'))
        self.pkg('later.package', (160, buff('b', HAPPY, 5)), sub='Vortex Mods')
        self.pkg('early.package', (160, buff('b', TENSE, 5)), sub='Vortex Mods')
        # relPath is relative to Vortex Mods, not to Mods. Joining it against
        # Mods produces a key that matches nothing, every lookup misses, and
        # the report silently falls back to filenames - which reads as a
        # manual install rather than as a bug.
        with open(os.path.join(self.root, 'Vortex Mods',
                               'vortex.deployment.json'), 'w') as f:
            json.dump({'files': [{'relPath': 'later.package',
                                  'source': 'Sensible Traits v3'},
                                 {'relPath': 'early.package',
                                  'source': 'Old Traits v1'}]}, f)
        c = self.winner(self.run_it(), 160)
        self.assertEqual(c['winner'], 'Sensible Traits v3')
        self.assertEqual(c['loser'], 'Old Traits v1')

    def test_a_manual_install_falls_back_to_the_filename(self):
        self.pkg('a.package', (170, buff('b', TENSE, 5)))
        self.pkg('b.package', (170, buff('b', HAPPY, 5)))
        self.assertEqual(self.winner(self.run_it(), 170)['winner'], 'b.package')


if __name__ == '__main__':
    unittest.main()
