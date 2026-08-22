"""The report query language.

    size:1 gender:female -world:Windenburg

The failure this language can produce is a quiet one, which is why it has a
real parser rather than a regex: a query that means something slightly other
than what was asked returns a confident list of the wrong households, and it
looks exactly like a right answer. So what is asserted here is mostly *shape* -
that precedence, negation and grouping mean what the grammar says, not what a
left-to-right scan happens to produce.

Two properties matter more than the rest:

  - **An unknown field is an error.** A query that silently matches nothing is
    indistinguishable from an honest empty result, and somebody will read the
    latter as "there are none of those in my save".
  - **An absent value is not a match, but IS a match for `!=`.** Otherwise
    `-world:Windenburg` quietly drops every household with no world at all,
    which on this data is 73 of 181 - a filter that removes 40% of the save
    while looking like it removed one neighbourhood.

`rquery.EXAMPLES` is shared: these tests parse and run every one, the terminal
accepts them, and the page prints them as clickable hints. A syntax the docs
advertise and the engine rejects cannot survive that.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402

sys.path.insert(0, os.path.join(support.ROOT, 'sulskill-doctor', 'scripts'))
import rquery                                                      # noqa: E402


SCHEMA = {
    'name': rquery.TEXT, 'world': rquery.TEXT, 'lot': rquery.TEXT,
    'member': rquery.LIST, 'gender': rquery.LIST, 'age': rquery.LIST,
    'species': rquery.LIST, 'funds': rquery.NUMBER, 'size': rquery.NUMBER,
    'people': rquery.NUMBER, 'pets': rquery.NUMBER, 'housed': rquery.BOOL,
    'creator': rquery.TEXT,
}
FREE = ('name', 'member', 'world', 'lot')


def hh(name, world='Willow Creek', funds=20000, size=1, genders=('Female',),
       ages=('Young Adult',), species=('Human',), members=None, housed=True,
       lot='A House', pets=0):
    return {'name': name, 'world': world if housed else '', 'lot': lot,
            'member': list(members or [name + ' Sim']), 'gender': list(genders),
            'age': list(ages), 'species': list(species), 'funds': funds,
            'size': size, 'people': size - pets, 'pets': pets,
            'housed': housed, 'creator': 'Tester'}


ROWS = [
    hh('Goth', 'Willow Creek', 45500, 4, ('Female', 'Male'),
       ('Child', 'Young Adult', 'Elder'),
       members=['Bella Goth', 'Mortimer Goth']),
    hh('Solo', 'Windenburg', 500, 1),                       # female, alone
    hh('Alone', 'Oasis Springs', 90000, 1),                 # female, alone
    hh('Bachelor', 'Willow Creek', 3000, 1, ('Male',)),
    hh('Drifter', '', 0, 1, lot=''),                        # no world at all
    hh('Kennel', 'Brindleton Bay', 12000, 3, ('Female', 'Male'),
       species=('Human', 'Dog'), pets=1),
]


def run(text):
    hits, _node = rquery.run(ROWS, text, SCHEMA, FREE)
    return sorted(r['name'] for r in hits)


class TheQuestionFromTheBrief(unittest.TestCase):

    def test_every_female_living_alone_except_windenburg(self):
        """The sentence this language exists to answer."""
        self.assertEqual(run('size:1 gender:female -world:Windenburg'),
                         ['Alone', 'Drifter'])

    def test_dropping_the_exception_puts_windenburg_back(self):
        """Proves the negation did the work, rather than the rest of the query
        having excluded Windenburg on its own."""
        self.assertEqual(run('size:1 gender:female'),
                         ['Alone', 'Drifter', 'Solo'])


class AbsentValues(unittest.TestCase):
    """The one that quietly eats 40% of a real save.

    Two different shapes, and the difference matters. A household with **no
    world** carries `world: ''` - an empty value that is still a value. A row
    that omits the key entirely has no value at all, and only the second
    reaches the absent-value branch.

    That distinction was found by a mutation escaping: every fixture here used
    the empty string, so breaking the absent-value branch changed nothing and
    the branch was effectively dead code with a test pointed at it. The
    assertions were right and the fixture could not tell them apart.
    """

    NO_KEY = dict(hh('Ghost'), name='Ghost')
    del NO_KEY['world']

    def rows(self):
        return ROWS + [self.NO_KEY]

    def run_with_ghost(self, text):
        hits, _n = rquery.run(self.rows(), text, SCHEMA, FREE)
        return sorted(r['name'] for r in hits)

    def test_a_negated_field_still_includes_rows_whose_value_is_empty(self):
        self.assertIn('Drifter', run('-world:Windenburg'))

    def test_a_negated_field_still_includes_rows_that_omit_it_entirely(self):
        self.assertIn('Ghost', self.run_with_ghost('-world:Windenburg'))

    def test_a_positive_match_excludes_rows_that_omit_the_field(self):
        self.assertNotIn('Ghost', self.run_with_ghost('world:Windenburg'))

    def test_not_equals_includes_rows_that_omit_the_field(self):
        """The absent-value branch itself: with no value at all there is
        nothing to compare, and only `!=` is true of nothing."""
        self.assertIn('Ghost', self.run_with_ghost('world!=Windenburg'))

    def test_a_positive_match_does_not_include_rows_with_an_empty_value(self):
        self.assertNotIn('Drifter', run('world:Windenburg'))

    def test_not_equals_includes_rows_with_an_empty_value(self):
        self.assertIn('Drifter', run('world!=Windenburg'))


class Grammar(unittest.TestCase):

    def test_two_terms_are_and_not_or(self):
        self.assertEqual(run('size:1 world:Windenburg'), ['Solo'])

    def test_or_is_wider_than_and(self):
        self.assertEqual(run('world:Windenburg OR world:"Oasis Springs"'),
                         ['Alone', 'Solo'])

    def test_and_binds_tighter_than_or(self):
        """`a b OR c` is `(a AND b) OR c`. A left-to-right scan would read it
        as `a AND (b OR c)` and answer a different question."""
        got = run('size:1 world:Windenburg OR name:Goth')
        self.assertEqual(got, ['Goth', 'Solo'])

    def test_parentheses_override_precedence(self):
        got = run('size:1 (world:Windenburg OR name:Goth)')
        self.assertEqual(got, ['Solo'])

    def test_not_applies_to_a_group(self):
        self.assertNotIn('Solo', run('-(world:Windenburg OR name:Goth)'))
        self.assertNotIn('Goth', run('-(world:Windenburg OR name:Goth)'))

    def test_minus_and_not_and_bang_are_the_same(self):
        for form in ('-world:Windenburg', 'NOT world:Windenburg',
                     '!world:Windenburg'):
            self.assertNotIn('Solo', run(form), form)

    def test_quoted_values_keep_their_spaces(self):
        self.assertEqual(run('world:"Oasis Springs"'), ['Alone'])

    def test_an_empty_query_matches_everything(self):
        self.assertEqual(len(run('')), len(ROWS))


class Comparisons(unittest.TestCase):

    def test_numbers_compare_numerically_not_as_text(self):
        """'90000' < '500' as text. A text comparison here would put the
        richest household in the poorest bucket and look plausible."""
        self.assertEqual(run('funds>50000'), ['Alone'])
        self.assertEqual(run('funds<1000'), ['Drifter', 'Solo'])

    def test_colon_on_a_number_is_equality(self):
        self.assertEqual(run('size:4'), ['Goth'])

    def test_colon_on_text_is_a_substring(self):
        self.assertEqual(run('world:willow'), ['Bachelor', 'Goth'])

    def test_equals_on_text_is_exact(self):
        self.assertEqual(run('world=willow'), [])
        self.assertEqual(run('world="willow creek"'), ['Bachelor', 'Goth'])

    def test_matching_is_case_insensitive(self):
        self.assertEqual(run('WORLD:WINDENBURG'), ['Solo'])

    def test_a_list_field_matches_if_any_element_does(self):
        """`gender:female` has to mean "somebody here is female", not "this
        household is female"."""
        self.assertIn('Goth', run('gender:male'))
        self.assertIn('Goth', run('gender:female'))

    def test_booleans_take_true_and_false(self):
        self.assertNotIn('Drifter', run('housed:false'))
        self.assertEqual(len(run('housed:true')), len(ROWS))


class FreeText(unittest.TestCase):

    def test_a_bare_word_searches_the_free_fields(self):
        self.assertEqual(run('bella'), ['Goth'])

    def test_a_bare_word_does_not_search_fields_left_out_of_free(self):
        """`creator` is queryable but not free text; otherwise every bare word
        would match every row through the account name."""
        self.assertEqual(run('Tester'), [])
        self.assertEqual(len(run('creator:Tester')), len(ROWS))


class ItRefusesRatherThanMatchingNothing(unittest.TestCase):

    def test_an_unknown_field_is_an_error(self):
        with self.assertRaises(rquery.QueryError) as caught:
            run('wrld:Windenburg')
        self.assertIn('wrld', str(caught.exception))

    def test_the_error_lists_the_fields_that_do_exist(self):
        with self.assertRaises(rquery.QueryError) as caught:
            run('wrld:Windenburg')
        self.assertIn('world', str(caught.exception))

    def test_an_unclosed_group_is_an_error(self):
        with self.assertRaises(rquery.QueryError):
            run('(size:1')

    def test_an_operator_with_no_value_is_an_error(self):
        with self.assertRaises(rquery.QueryError):
            run('size>')

    def test_a_text_field_refuses_a_greater_than(self):
        with self.assertRaises(rquery.QueryError):
            run('name>Goth')


class TheExamplesAreReal(unittest.TestCase):
    """The page prints these as clickable hints and the terminal accepts them.
    A syntax the docs advertise and the engine rejects cannot survive this."""

    def test_every_documented_example_parses_and_runs(self):
        for label, qs in rquery.EXAMPLES:
            with self.subTest(example=qs):
                hits, _node = rquery.run(ROWS, qs, SCHEMA, FREE)
                self.assertIsInstance(hits, list, label)

    def test_every_example_has_a_plain_english_label(self):
        """The labels are what an agent maps a question onto, so an example
        with no sentence attached is not usable for that."""
        for label, qs in rquery.EXAMPLES:
            self.assertTrue(label and label[0].islower(), label)
            self.assertTrue(qs.strip())


if __name__ == '__main__':
    unittest.main()
