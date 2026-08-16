"""Pick-one variant sets: alternatives of one mod, all installed at once.

This is the quietest failure in a big library. A mod ships six working-time
builds and expects one installed; six installed all load, and the last one read
wins. Nothing errors, no log mentions it, and every inventory tool reports six
healthy packages. The setting in play is simply not the one that was chosen.

Two properties have to hold or the tool is worse than nothing:

- **Resource sets decide, names only corroborate.** A module set and a variant
  set have identical naming shapes - `_EP02`/`_EP03` beside `_10min`/`_25min`.
  What separates them is that modules describe *different* resources while
  alternatives describe the *same* ones. A name-driven tool cheerfully tells
  people to delete half of a module set.
- **A version is dereferenced, never read off the filename.** The build with no
  version in its name is very often the newer one, shipped from an archive that
  carries the version. Guessing from the suffix recommends deleting the newer
  file and keeping the older, which is the one outcome worse than silence.

NO TEST HERE MAY CONTAIN A REAL BLOCKLIST TERM - see support.py. Every mod name
below is invented.
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
import variants                                                     # noqa: E402

TUNING = 0x6017E896


def keys(*instances):
    """Package entries occupying exactly these resource instances."""
    return [(TUNING, i, b'<I n="x" />', 0) for i in instances]


class Fixture(unittest.TestCase):
    """A synthetic Mods tree, optionally with a deployment manifest."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mods = os.path.join(self.tmp, 'Mods', 'Vortex Mods')
        os.makedirs(self.mods)
        self.manifest = {}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pkg(self, name, instances, source=None):
        support.write_pkg(self.mods, name, keys(*instances))
        if source:
            self.manifest[name] = source

    def run_tool(self, floor=variants.MIN_SIM):
        if self.manifest:
            with open(os.path.join(self.mods, 'vortex.deployment.json'), 'w',
                      encoding='utf-8') as f:
                json.dump({'files': [{'relPath': k, 'source': v}
                                     for k, v in self.manifest.items()]}, f)
        return variants.analyse(os.path.join(self.tmp, 'Mods'), floor,
                                quiet=True)

    def only_group(self, res):
        self.assertEqual(len(res['groups']), 1,
                         'expected exactly one group, got %d'
                         % len(res['groups']))
        return res['groups'][0]

    def by_file(self, grp):
        return {os.path.basename(m['package']): m for m in grp['members']}


class Stems(unittest.TestCase):
    """The name check corroborates. It must not fire on an author prefix."""

    def test_cut_back_to_a_separator(self):
        self.assertEqual(
            variants.shared_stem('Maker_Thing_Fast', 'Maker_Thing_Slow'),
            'Maker_Thing')

    def test_cut_back_to_a_camel_hump(self):
        # No separator anywhere, so a raw character-prefix rule would claim
        # 'BrightHouseS' and invent a mod name that does not exist.
        self.assertEqual(
            variants.shared_stem('BrightHouseSideTable', 'BrightHouseStool'),
            'BrightHouse')

    def test_a_whole_name_inside_a_longer_one_is_a_stem(self):
        # The commonest real shape: one build adds a version to the other's
        # name. Without the end of the string counting as a token boundary the
        # cut falls back to the author prefix and the pair is never grouped.
        ok, stem = variants.same_mod('Maker_Traits', 'Maker_Traits_V1.7.3')
        self.assertTrue(ok)
        self.assertEqual(stem, 'Maker_Traits')

    def test_shared_author_prefix_is_not_a_shared_mod(self):
        ok, stem = variants.same_mod('Maker_Windows_V2', 'Maker_Doorframes_V2')
        self.assertFalse(ok, 'two unrelated mods by one author matched as one')
        self.assertEqual(stem, 'Maker')

    def test_a_stem_too_small_a_share_of_the_name_is_not_enough(self):
        # Long enough to pass MIN_STEM, but seven characters of agreement
        # across two thirty-character names is a coincidence, not a mod.
        ok, stem = variants.same_mod('CoreKit_Lighting_Ceiling_Recolours',
                                     'CoreKit_Plumbing_Sinks_Recolours')
        self.assertFalse(ok)
        self.assertEqual(stem, 'CoreKit')

    def test_group_stem_survives_a_third_name(self):
        # Folding pairwise trims the accumulator's later boundaries away. If
        # the end of a string were not itself a boundary, the accumulator would
        # have no legal cut left and would collapse to the author prefix here.
        names = ['Maker_Thing_Alpha', 'Maker_Thing_Beta', 'Maker_Thing_Gamma']
        self.assertEqual(variants.group_stem(names), 'Maker_Thing')

    def test_group_stem_narrows_when_a_later_name_diverges_early(self):
        names = ['Maker_ThingAlpha', 'Maker_ThingBeta', 'Maker_Other']
        self.assertEqual(variants.group_stem(names), 'Maker')

    def test_a_flavour_in_the_middle_of_the_name_still_counts(self):
        # The common prefix here is the author's name and nothing more, so a
        # prefix rule alone leaves this pair unexplained - while the identical
        # pair that happened to ship in one archive gets grouped. One report
        # cannot call the same shape both things.
        ok, _ = variants.same_mod('Maker_casVer_ToddlerTraits_V2.5',
                                  'Maker_RewardVer_ToddlerTraits_V2.5')
        self.assertTrue(ok)

    def test_one_differing_token_out_of_three_is_a_convention_not_a_mod(self):
        self.assertFalse(variants.one_token_apart('Maker_Windows_V2',
                                                  'Maker_Doorframes_V2'))

    def test_two_differing_tokens_are_two_mods(self):
        self.assertFalse(
            variants.one_token_apart('Maker_casVer_ToddlerTraits_V2.5',
                                     'Maker_RewardVer_ToddlerSkills_V2.5'))

    def test_names_of_different_token_counts_do_not_line_up(self):
        self.assertFalse(
            variants.one_token_apart('Maker_casVer_Traits_Extra_V2',
                                     'Maker_RewardVer_Traits_V2'))

    def test_a_number_welded_to_a_word_is_not_a_version(self):
        # 'Tier2' is what the build is; '_V2' is which build it is.
        self.assertEqual(variants.flavour('Tier2'), 'Tier2')
        self.assertEqual(variants.flavour('Tier2_V2'), 'Tier2')
        self.assertEqual(variants.flavour('V2'), '(base)')


class Discrimination(Fixture):
    """Resource sets decide membership; names never promote on their own."""

    def test_same_resources_and_shared_stem_is_a_variant_set(self):
        self.pkg('Maker_Homework_Addon_10min.package', [1, 2, 3, 4])
        self.pkg('Maker_Homework_Addon_25min.package', [1, 2, 3, 4])
        g = self.only_group(self.run_tool())
        self.assertEqual(g['stem'], 'Maker_Homework_Addon')
        self.assertEqual(sorted(m['flavour'] for m in g['members']),
                         ['10min', '25min'])

    def test_modules_of_one_mod_are_not_a_variant_set(self):
        # Identical naming shape to the case above. The only thing saying these
        # are complements is that they describe different resources - which is
        # exactly the evidence a filename-driven tool does not have.
        self.pkg('Maker_Challenges_EP02.package', [1, 2, 3, 4])
        self.pkg('Maker_Challenges_EP03.package', [5, 6, 7, 8])
        res = self.run_tool()
        self.assertEqual(res['groups'], [])
        self.assertEqual(res['overlaps'], [])

    def test_same_resources_without_a_shared_name_is_only_an_overlap(self):
        self.pkg('Maker_LaundryBuffs.package', [1, 2, 3, 4])
        self.pkg('Other_ChoreBuffs.package', [1, 2, 3, 4])
        res = self.run_tool()
        self.assertEqual(res['groups'], [],
                         'accused two unrelated mods of being one mod')
        self.assertEqual(len(res['overlaps']), 1)
        self.assertEqual(res['overlaps'][0]['similarity'], 1.0)

    def test_a_shared_source_archive_stands_in_for_a_shared_stem(self):
        # The names share only 'Maker', but the mod itself shipped both files,
        # which is the same claim a stem makes and better evidence than one.
        self.pkg('Maker_CasVer_Traits.package', [1, 2, 3, 4],
                 source='Maker_Traits_V3')
        self.pkg('Maker_RewardVer_Traits.package', [1, 2, 3, 4],
                 source='Maker_Traits_V3')
        g = self.only_group(self.run_tool())
        self.assertEqual(len(g['members']), 2)
        self.assertEqual(g['stem'], 'Maker_Traits',
                         'group labelled from the archive should drop its '
                         'version tail')

    def test_one_shared_resource_out_of_many_is_not_a_variant_set(self):
        self.pkg('Maker_Thing_Alpha.package', list(range(1, 11)))
        self.pkg('Maker_Thing_Beta.package', [1] + list(range(20, 30)))
        res = self.run_tool()
        self.assertEqual(res['groups'], [])

    def test_alternatives_are_not_charged_for_the_resource_that_differs(self):
        # Eight schedules, three resources each, agreeing on two. Jaccard scores
        # that 0.50 and hides all eight, because the one resource each package
        # does not share is the very thing that makes it the schedule it is.
        for hour in (8, 10, 12, 14, 16, 18, 20, 22):
            self.pkg('Maker_Nanny_WorkingTime_%dh.package' % hour,
                     [1, 2, 100 + hour])
        g = self.only_group(self.run_tool())
        self.assertEqual(len(g['members']), 8)

    def test_a_small_package_inside_a_large_one_is_an_addon_not_an_alternative(
            self):
        # Fully contained - every resource of the smaller is in the larger - and
        # still not a choice between two builds of one thing. Without the size
        # guard, containment calls this a variant set and tells the user to
        # delete one of them.
        self.pkg('Maker_Thing.package', list(range(1, 31)))
        self.pkg('Maker_Thing_Patch.package', [1, 2, 3])
        res = self.run_tool()
        self.assertEqual(res['groups'], [])
        self.assertEqual(res['overlaps'], [])

    def test_one_resource_each_is_a_variant_set_when_the_names_agree(self):
        # As total an overwrite as exists: six files, one resource, same
        # resource. Nothing here is additive - five of the six do nothing.
        for age in ('Adult', 'Elder', 'Teen', 'Toddler', 'Child', 'Infant'):
            self.pkg('Maker_Nanny_Age_%s.package' % age, [1])
        self.assertEqual(len(self.only_group(self.run_tool())['members']), 6)

    def test_one_resource_each_accuses_nothing_when_the_names_do_not(self):
        # The same single shared resource, without names to corroborate it, is
        # two unrelated mods touching one tuning - not worth reporting at all.
        self.pkg('Maker_Alpha.package', [1])
        self.pkg('Stranger_Beta.package', [1])
        res = self.run_tool()
        self.assertEqual(res['groups'], [])
        self.assertEqual(res['overlaps'], [])

    def test_a_clean_library_reports_nothing(self):
        self.pkg('Maker_Alpha.package', [1, 2, 3, 4])
        self.pkg('Other_Beta.package', [5, 6, 7, 8])
        res = self.run_tool()
        self.assertEqual(res['groups'], [])
        self.assertEqual(res['overlaps'], [])
        self.assertEqual(res['packages_scanned'], 2)


class Versions(Fixture):
    """Which build is newer is dereferenced, never inferred from the suffix."""

    def two_builds(self):
        # The real shape: the unsuffixed file is V1.10, shipped inside an
        # archive that names the version; the file that spells a version in its
        # own name is the OLDER one.
        self.pkg('Maker_Traits.package', [1, 2, 3, 4],
                 source='Maker_Traits_V1.10')
        self.pkg('Maker_Traits_V1.7.3.package', [1, 2, 3, 4],
                 source='Maker_Traits_V1.7.3')
        return self.only_group(self.run_tool())

    def test_versions_compare_numerically_not_as_text(self):
        # '1.10' sorts before '1.7.3' as text, and that is the wrong answer.
        self.assertGreater(variants._vkey('V1.10'), variants._vkey('V1.7.3'))

    def test_the_unsuffixed_build_can_be_the_newer_one(self):
        m = self.by_file(self.two_builds())['Maker_Traits.package']
        self.assertEqual(m['version'], 'V1.10')
        self.assertEqual(m['version_from'], 'source archive')
        self.assertIsNone(m['superseded_by'])

    def test_the_older_build_is_the_one_marked(self):
        g = self.two_builds()
        old = [m for m in g['members'] if m['superseded_by']]
        self.assertEqual(len(old), 1)
        self.assertEqual(os.path.basename(old[0]['package']),
                         'Maker_Traits_V1.7.3.package')
        self.assertEqual(old[0]['superseded_by'], 'V1.10')

    def test_two_builds_of_one_thing_are_labelled_a_version_pair(self):
        self.assertEqual(self.two_builds()['kind'], 'version pair')

    def test_different_flavours_at_one_version_supersede_nothing(self):
        self.pkg('Maker_Traits_CasVer_V2.package', [1, 2, 3, 4],
                 source='Maker_Traits_CasVer_V2')
        self.pkg('Maker_Traits_RewardVer_V2.package', [1, 2, 3, 4],
                 source='Maker_Traits_RewardVer_V2')
        g = self.only_group(self.run_tool())
        self.assertEqual(g['superseded'], 0)
        self.assertEqual(g['kind'], 'variant set')

    def test_the_archive_wins_when_the_two_disagree(self):
        # The author bumped V2 to V4 and never renamed the file. Read the
        # filenames and the answer inverts: the file marked V2 looks stale and
        # the recommendation is to delete the only current build in the set.
        self.pkg('Maker_Curfew_V2.package', [1, 2, 3, 4],
                 source='Maker_Curfew_V4')
        self.pkg('Maker_Curfew_V3.package', [1, 2, 3, 4],
                 source='Maker_Curfew_V3')
        m = self.by_file(self.only_group(self.run_tool()))
        current, stale = m['Maker_Curfew_V2.package'], m['Maker_Curfew_V3.package']
        self.assertEqual(current['version'], 'V4')
        self.assertEqual(current['version_from'], 'source archive')
        self.assertIsNone(current['superseded_by'])
        self.assertEqual(stale['superseded_by'], 'V4')

    def test_a_stale_filename_version_does_not_split_the_flavour(self):
        # If the filename's V2 survived into the flavour while the archive's V4
        # was the credited version, the two builds would be different flavours
        # and neither would ever supersede the other.
        self.pkg('Maker_Curfew_V2.package', [1, 2, 3, 4],
                 source='Maker_Curfew_V4')
        self.pkg('Maker_Curfew_V3.package', [1, 2, 3, 4],
                 source='Maker_Curfew_V3')
        g = self.only_group(self.run_tool())
        self.assertEqual({m['flavour'] for m in g['members']}, {'(base)'})

    def test_a_filename_version_is_used_when_there_is_no_archive(self):
        self.pkg('Maker_Curfew_V2.package', [1, 2, 3, 4])
        self.pkg('Maker_Curfew_V3.package', [1, 2, 3, 4])
        m = self.by_file(self.only_group(self.run_tool()))
        self.assertEqual(m['Maker_Curfew_V2.package']['version_from'],
                         'filename')
        self.assertEqual(m['Maker_Curfew_V2.package']['superseded_by'], 'V3')
        self.assertIsNone(m['Maker_Curfew_V3.package']['superseded_by'])


class Grouping(Fixture):
    """Four alternatives are one decision, not six."""

    def four_alternatives(self):
        for tag in ('Base', 'Higher', 'EvenHigher', 'Edited'):
            self.pkg('Maker_ClubFilter%s.package' % tag, [1, 2, 3, 4])
        return self.run_tool()

    def test_four_alternatives_form_one_group(self):
        g = self.only_group(self.four_alternatives())
        self.assertEqual(len(g['members']), 4)
        self.assertEqual(g['stem'], 'Maker_ClubFilter')

    def test_a_group_is_not_labelled_with_just_the_author_prefix(self):
        # Seven characters of author name clears MIN_STEM and still tells the
        # reader nothing about which mod they have to make a decision about.
        self.pkg('Foundry_casVer_SeasonsTraits.package', [1, 2, 3, 4],
                 source='Foundry_SeasonsTraits_V1.10')
        self.pkg('Foundry_RewardVer_SeasonsTraits.package', [1, 2, 3, 4],
                 source='Foundry_SeasonsTraits_V1.10')
        self.assertEqual(self.only_group(self.run_tool())['stem'],
                         'Foundry_SeasonsTraits')

    def test_the_archive_names_a_group_whose_filenames_share_nothing(self):
        # One archive offering two alternatives, each file named for the choice
        # it makes and nothing else. The filenames agree on no token at either
        # end, so the only thing that knows what this mod is called is the
        # archive it arrived in.
        self.pkg('Autonomous.package', [1, 2, 3, 4],
                 source='Foundry_HomeworkTweak_V3')
        self.pkg('PlayerDirected.package', [1, 2, 3, 4],
                 source='Foundry_HomeworkTweak_V3')
        self.assertEqual(self.only_group(self.run_tool())['stem'],
                         'Foundry_HomeworkTweak')

    def test_the_label_survives_archives_that_disagree_about_the_flavour(self):
        # The real shape this was found in: the author carried the flavour token
        # in the archive name for one release and dropped it for the next, so no
        # two of the four archives share a prefix past `Foundry`. A label read
        # off the front of the names cannot get past that - the mod's name is
        # what all four still agree on at the *end*.
        for flav in ('casVer', 'RewardVer'):
            self.pkg('Foundry_%s_SeasonsTraits.package' % flav, [1, 2, 3, 4],
                     source='Foundry_SeasonsTraits_V1.10')
            self.pkg('Foundry_%s_SeasonsTraits_V1.7.3.package' % flav,
                     [1, 2, 3, 4],
                     source='Foundry_%s_SeasonsTraits_V1.7.3' % flav)
        self.assertEqual(self.only_group(self.run_tool())['stem'],
                         'Foundry_SeasonsTraits')

    def test_an_infix_flavour_groups_without_any_archive(self):
        self.pkg('Foundry_casVer_SeasonsTraits.package', [1, 2, 3, 4])
        self.pkg('Foundry_RewardVer_SeasonsTraits.package', [1, 2, 3, 4])
        res = self.run_tool()
        self.assertEqual(len(self.only_group(res)['members']), 2)
        self.assertEqual(res['overlaps'], [])

    def test_two_separate_mods_stay_separate(self):
        self.pkg('Maker_Homework_10min.package', [1, 2, 3, 4])
        self.pkg('Maker_Homework_25min.package', [1, 2, 3, 4])
        self.pkg('Other_Curfew_Early.package', [10, 11, 12, 13])
        self.pkg('Other_Curfew_Late.package', [10, 11, 12, 13])
        res = self.run_tool()
        self.assertEqual(len(res['groups']), 2)
        self.assertEqual({g['stem'] for g in res['groups']},
                         {'Maker_Homework', 'Other_Curfew'})

    def test_no_pair_is_reported_in_both_sections(self):
        # A pair listed as a known variant set AND as "mod not identified" in
        # one run leaves the reader no way to tell which section to believe.
        for tag in ('Base', 'Higher', 'EvenHigher', 'Edited'):
            self.pkg('Maker_ClubFilter%s.package' % tag, [1, 2, 3, 4])
        self.pkg('Stranger_Filter.package', [1, 2, 3, 4])
        res = self.run_tool()
        self.assertTrue(res['overlaps'], 'nothing to be double-reported')
        inside = {m['package'] for m in res['groups'][0]['members']}
        for o in res['overlaps']:
            self.assertFalse(set(o['packages']) <= inside,
                             '%s reported as both grouped and unexplained'
                             % o['packages'])


class TwoVersionsOfTwoFlavours(Fixture):
    """The shape that motivated the tool: 2 flavours x 2 versions, all four
    installed. Only the source archives say which two are stale, and the
    cross-pairs (casVer 1.10 against rewardVer 1.7.3) share no name stem and no
    archive - so they are the pairs that must not surface as unexplained
    overlaps after the group has already accounted for them."""

    def setUp(self):
        super().setUp()
        for flavour in ('CasVer', 'RewardVer'):
            self.pkg('Maker_%s_Traits.package' % flavour, [1, 2, 3, 4],
                     source='Maker_Traits_V1.10')
            self.pkg('Maker_%s_Traits_V1.7.3.package' % flavour, [1, 2, 3, 4],
                     source='Maker_Traits_V1.7.3')

    def test_all_four_are_one_group(self):
        self.assertEqual(len(self.only_group(self.run_tool())['members']), 4)

    def test_the_group_is_named_from_the_archives(self):
        # No filename stem longer than 'Maker' survives four names.
        self.assertEqual(self.only_group(self.run_tool())['stem'],
                         'Maker_Traits')

    def test_both_stale_builds_are_marked_and_no_current_one_is(self):
        g = self.only_group(self.run_tool())
        self.assertEqual(g['superseded'], 2)
        stale = {os.path.basename(m['package']) for m in g['members']
                 if m['superseded_by'] == 'V1.10'}
        self.assertEqual(stale, {'Maker_CasVer_Traits_V1.7.3.package',
                                 'Maker_RewardVer_Traits_V1.7.3.package'})

    def test_the_two_flavours_are_kept_apart(self):
        # If flavour were taken from the raw tail, the version suffix would
        # make four flavours and nothing would ever be superseded.
        g = self.only_group(self.run_tool())
        self.assertEqual({m['flavour'] for m in g['members']},
                         {'CasVer_Traits', 'RewardVer_Traits'})

    def test_the_cross_pairs_are_not_reported_as_unexplained(self):
        res = self.run_tool()
        self.assertEqual(res['overlaps'], [],
                         'pairs already inside a group re-reported as '
                         '"mod not identified"')


SNIPPET = 0x7DF2169C


def manifest(tag):
    """A blob shaped like the build manifest Studio stamps into every build."""
    return (b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<I c="ModFileManifest" i="snippet" '
            b'm="llamalogic.snippets.modfilemanifest" '
            b'n="llamalogic:manifest_' + tag + b'" s="1">\n</I>')


class WhichBuildIsInPlay(Fixture):
    """Naming the survivor, and saying whether the rest do anything.

    "Keep one" is only half an instruction. Which one is already in play is
    decided by case-insensitive path order with the last read winning, so it
    is knowable - and it is the half that tells someone whether the library
    has been quietly running the build they wanted or its opposite.
    """

    def raw(self, name, entries):
        support.write_pkg(self.mods, name, entries)

    def tuning(self, *instances):
        return [(TUNING, i, b'<I n="x" />', 0) for i in instances]

    def test_the_last_path_read_is_the_one_named(self):
        for tag in ('Early', 'Late', 'Middle'):
            self.pkg('Maker_Curfew_%s.package' % tag, [1, 2, 3, 4])
        g = self.only_group(self.run_tool())
        self.assertTrue(g['active'].endswith('Maker_Curfew_Middle.package'),
                        'named %s' % g['active'])
        active = [m for m in g['members'] if m['active']]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]['package'], g['active'])

    def test_case_does_not_decide_the_winner(self):
        # A byte-wise sort puts every capital ahead of every lowercase, so
        # `Maker_Curfew_all.package` would lose to `Maker_Curfew_Z.package`.
        # The game does not read them that way, and getting this backwards
        # names the wrong build with total confidence.
        self.pkg('Maker_Curfew_all.package', [1, 2, 3, 4])
        self.pkg('Maker_Curfew_Z.package', [1, 2, 3, 4])
        g = self.only_group(self.run_tool())
        self.assertTrue(g['active'].endswith('Maker_Curfew_Z.package'),
                        'named %s' % g['active'])

    def test_siblings_that_are_wholly_overridden_are_not_called_mixing(self):
        for tag in ('Early', 'Late'):
            self.pkg('Maker_Curfew_%s.package' % tag, [1, 2, 3, 4])
        g = self.only_group(self.run_tool())
        self.assertEqual(g['mixing'], 0)
        self.assertEqual([m['still_live'] for m in g['members']], [0, 0])

    def test_a_resource_missing_from_the_winner_is_reported_live(self):
        self.pkg('Maker_Traits_A.package', [1, 2, 3])
        self.pkg('Maker_Traits_B.package', [1, 2])
        g = self.only_group(self.run_tool())
        self.assertTrue(g['active'].endswith('Maker_Traits_B.package'))
        self.assertEqual(g['mixing'], 1)

    def test_a_build_manifest_is_not_mistaken_for_content(self):
        # Every build carries one, keyed on a hash of that build, so no two
        # siblings share it. Counted as content it makes each loser look like
        # it still contributes and every set reads as mixed.
        for tag in (b'aaaa', b'bbbb'):
            self.raw('Maker_Curfew_%s.package' % tag.decode(),
                     self.tuning(1, 2, 3)
                     + [(SNIPPET, int(tag, 16), manifest(tag), 0)])
        g = self.only_group(self.run_tool())
        self.assertEqual(len(g['members']), 2)
        self.assertEqual(g['mixing'], 0,
                         'a per-build manifest counted as a live resource')

    def test_a_manifest_is_still_recognised_when_compressed(self):
        for tag in (b'aaaa', b'bbbb'):
            self.raw('Maker_Curfew_%s.package' % tag.decode(),
                     self.tuning(1, 2, 3)
                     + [(SNIPPET, int(tag, 16), manifest(tag), 0x5A42)])
        self.assertEqual(self.only_group(self.run_tool())['mixing'], 0)

    def test_a_payload_that_cannot_be_read_counts_as_content(self):
        # RefPack is not decoded here. The resource must then be reported as
        # live rather than assumed to be bookkeeping: over-reporting costs a
        # look, and the other way round writes off a real conflict unseen.
        for tag in (b'aaaa', b'bbbb'):
            self.raw('Maker_Curfew_%s.package' % tag.decode(),
                     self.tuning(1, 2, 3)
                     + [(SNIPPET, int(tag, 16), manifest(tag), 0xFFFF)])
        self.assertEqual(self.only_group(self.run_tool())['mixing'], 1)

    def test_namemap_is_not_a_shared_resource(self):
        # Bookkeeping present in nearly every package. Left in the key sets it
        # is a free point of agreement between any two packages, which is
        # exactly enough to push a pair that shares one real resource out of
        # three over the floor and report two unrelated builds as a variant set.
        #
        # Written out from the support module rather than read off variants: a
        # fixture that asks the tool which type to write agrees with it whatever
        # it says, so pointing the constant elsewhere would move the package too
        # and the test would keep passing over code that excludes nothing.
        for tag, unique in (('A', 10), ('B', 11)):
            self.raw('Maker_Thing_%s.package' % tag,
                     self.tuning(1, unique)
                     + [(support.NAMEMAP, 0, b'\x00\x00\x00\x00', 0)])
        self.assertEqual(self.run_tool()['groups'], [],
                         'NameMap counted as agreement between two builds')


if __name__ == '__main__':
    unittest.main()
