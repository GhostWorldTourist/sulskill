"""The base-game index: lookups that fail by finding nothing.

The quiet failure this covers is a query that returns zero rows for a reason
that has nothing to do with the data. A real lookup of instance 14965 against
the raw JSONL returned no hits - not because the instance was absent, but
because the field is `id` and not `instance`, and because ids are stored as
strings so the ones above 2^63 survive. A wrong field name and a wrong value
type both look exactly like "not present", and "not present" is an answer people
act on.

So the assertions here are mostly about **id spellings reaching the same row**.
Decimal, hex, padded hex and mixed case are all things a person or an agent will
type, and any of them silently missing puts the tool back where the JSONL was.

Written from the design:

  - Any spelling of an id finds the same row, or the tool says the id is not a
    number rather than returning an empty result.
  - The writer and the reader agree on where the database lives. They did not,
    after the port, and nothing would have failed until someone built an index
    and could not query it.
  - Building is resumable: a stage whose outputs exist is skipped, so a failed
    run is fixed by running it again.
  - Nothing here needs the game installed. These tests never touch a real
    Sims 4 folder.
"""
import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support                                                     # noqa: E402,F401

SCRIPTS = os.path.join(support.ROOT, 'sulskill-basegame', 'scripts')
sys.path.insert(0, SCRIPTS)
import build_db                                                    # noqa: E402
import index as indexer                                            # noqa: E402
import q                                                           # noqa: E402


ROWS = [
    {'id': '14965', 'id_hex': '0x0000000000003A75', 'kind': 'I', 'type': 'object',
     'name': 'object_sim', 'class': 'Sim', 'module': 'sims.sim',
     'package': 'Data/Simulation/SimulationDeltaBuild0.package',
     'ct_group': '0x00000000', 'ct_key': 'abc'},
    # deliberately above 2**63, the reason ids are stored as TEXT
    {'id': '16730440671020297696', 'id_hex': '0xE8380D2E9E1A45E0', 'kind': 'I',
     'type': 'buff', 'name': 'buff_Example', 'class': 'Buff', 'module': 'buffs',
     'package': 'Data/Simulation/SimulationDeltaBuild0.package',
     'ct_group': '0x00000000', 'ct_key': 'def'},
    # id written as hex at the source. A build that does not normalise stores
    # '0x3A76' verbatim, and a decimal lookup then finds nothing - which is the
    # original failure wearing a different hat.
    {'id': '0x3A76', 'id_hex': '0x0000000000003A76', 'kind': 'I',
     'type': 'object', 'name': 'object_hexsourced', 'class': 'Thing',
     'module': 'things', 'package': 'Data/Simulation/X.package',
     'ct_group': '0x00000000', 'ct_key': 'ghi'},
]


@contextlib.contextmanager
def built():
    """A tiny index built from synthetic JSONL. -> (out dir, tmp)."""
    tmp = tempfile.mkdtemp()
    with support.environment(SULSKILL_OUT=tmp, TS4_DB=None):
        importlib.reload(build_db)
        importlib.reload(q)
        os.makedirs(build_db.OUT, exist_ok=True)
        with open(os.path.join(build_db.OUT, 'instances.jsonl'), 'w',
                  encoding='utf-8') as f:
            for r in ROWS:
                f.write(json.dumps(r) + '\n')
        with open(os.path.join(build_db.OUT, 'strings_en.jsonl'), 'w',
                  encoding='utf-8') as f:
            f.write(json.dumps({'key': '0x0000C3E4', 'text': 'a line of text'}) + '\n')
        run_quiet(build_db.main, [])
        yield build_db.OUT, tmp


def run_quiet(fn, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = fn(argv)
    return code, buf.getvalue()


class AnySpellingOfAnIdFindsTheRow(unittest.TestCase):

    def test_decimal(self):
        with built():
            code, out = run_quiet(q.main, ['id', '14965'])
            self.assertEqual(code, 0)
            self.assertIn('object_sim', out)

    def test_bare_hex(self):
        with built():
            _, out = run_quiet(q.main, ['id', '0x3A75'])
            self.assertIn('object_sim', out)

    def test_padded_hex(self):
        with built():
            _, out = run_quiet(q.main, ['id', '0x0000000000003A75'])
            self.assertIn('object_sim', out)

    def test_lowercase_hex(self):
        with built():
            _, out = run_quiet(q.main, ['id', '0x3a75'])
            self.assertIn('object_sim', out)

    def test_an_id_above_2_63_survives(self):
        """SQLite INTEGER is signed 64-bit, which is why ids are stored as TEXT.
        Stored as an integer this one comes back negative or not at all."""
        with built():
            _, out = run_quiet(q.main, ['id', '16730440671020297696'])
            self.assertIn('buff_Example', out)

    def test_an_id_written_as_hex_at_the_source_is_normalised(self):
        """The build must canonicalise, not store what it was handed. Otherwise
        a decimal lookup misses a row that is plainly there."""
        with built():
            _, out = run_quiet(q.main, ['id', '14966'])
            self.assertIn('object_hexsourced', out)

    def test_a_genuinely_absent_id_says_so(self):
        with built():
            code, out = run_quiet(q.main, ['id', '999999999'])
            self.assertEqual(code, 1)
            self.assertIn('Not a vanilla instance', out)

    def test_something_that_is_not_a_number_is_not_silently_empty(self):
        with built():
            code, out = run_quiet(q.main, ['id', 'not-an-id-at-all'])
            self.assertEqual(code, 2)
            self.assertIn('not a number', out)


class TheToolExplainsItself(unittest.TestCase):

    def test_schema_lists_the_tables(self):
        with built():
            code, out = run_quiet(q.main, ['schema'])
            self.assertEqual(code, 0)
            self.assertIn('CREATE TABLE instances', out)

    def test_a_bad_column_points_at_schema(self):
        """Guessing column names is the failure this tool exists to end, so a
        SQL error has to say where the real names are."""
        with built():
            code, out = run_quiet(q.main, ['sql', 'SELECT nosuchcolumn FROM instances'])
            self.assertEqual(code, 2)
            self.assertIn('schema', out)

    def test_a_missing_database_says_how_to_build_it(self):
        tmp = tempfile.mkdtemp()
        with support.environment(SULSKILL_OUT=tmp, TS4_DB=None):
            importlib.reload(q)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                with self.assertRaises(SystemExit) as raised:
                    q.main(['id', '1'])
            self.assertEqual(raised.exception.code, 2)
            self.assertIn('index.py', buf.getvalue())


class WriterAndReaderAgree(unittest.TestCase):

    def test_the_database_is_written_where_it_is_read(self):
        """They did not agree after the port, and nothing would have caught it
        until somebody built an index and could not query it."""
        tmp = tempfile.mkdtemp()
        with support.environment(SULSKILL_OUT=tmp, TS4_DB=None):
            importlib.reload(build_db)
            importlib.reload(q)
            self.assertEqual(build_db.DB, q.DB)


class BuildingIsResumable(unittest.TestCase):

    def test_list_names_every_stage_and_its_outputs(self):
        code, out = run_quiet(indexer.main, ['--list'])
        self.assertEqual(code, 0)
        self.assertIn('instances.jsonl', out)
        self.assertIn('ts4.db', out)

    def test_an_unknown_stage_is_refused(self):
        code, out = run_quiet(indexer.main, ['--only', 'nosuchstage'])
        self.assertEqual(code, 2)

    def test_a_missing_game_is_reported_not_guessed(self):
        tmp = tempfile.mkdtemp()
        with support.environment(SULSKILL_OUT=tmp,
                                 TS4_INSTALL=os.path.join(tmp, 'nope')):
            importlib.reload(indexer)
            code, out = run_quiet(indexer.main, [])
            self.assertEqual(code, 2)
            self.assertIn('cannot find The Sims 4', out)

    def test_a_stage_already_built_is_skipped(self):
        tmp = tempfile.mkdtemp()
        with support.environment(SULSKILL_OUT=tmp):
            importlib.reload(indexer)
            os.makedirs(indexer.OUT, exist_ok=True)
            for name in ('packs.json',):
                with open(os.path.join(indexer.OUT, name), 'w') as f:
                    f.write('{}')
            stage = [s for s in indexer.STAGES if s[0] == 'packs'][0]
            self.assertTrue(indexer.produced(stage))


if __name__ == '__main__':
    unittest.main()
