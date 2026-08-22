"""A small query language for the HTML reports, and for the terminal.

    size:1 gender:female -world:Windenburg

...is "every household of one, containing a female, except in Windenburg". That
is the whole point: a question somebody would actually ask, written in one line,
with no SQL and no dependency.

Why a new one rather than SQL, JMESPath or Lucene
-------------------------------------------------
Three requirements pulled the same way. It has to be **typeable by a person**
mid-thought, so no `SELECT ... WHERE`. It has to be **reliably writable by a
language model** from a sentence, which favours the GitHub/Jira `field:value`
shape that every model has seen a great deal of. And it has to be **safe to
paste into a URL**, so nothing that evaluates code. A tiny grammar with a real
parser satisfies all three; a regex over the raw string would not, because the
moment somebody writes `NOT (a OR b)` a regex quietly gets it wrong.

The grammar, entire
-------------------
    query   := or
    or      := and (('OR' | '|') and)*
    and     := unary (('AND' | '&')? unary)*        implicit AND
    unary   := ('NOT' | '-' | '!') unary | primary
    primary := '(' or ')' | term
    term    := field OP value | bare-word | "quoted phrase"
    OP      := ':' | '=' | '!=' | '>' | '>=' | '<' | '<='

`field:value` is a **substring, case-insensitive** match on text, and equality
on numbers. `field=value` is exact. A bare word searches every field the schema
marks as free text. A field whose value is a list matches if **any** element
does, which is what makes `gender:female` mean "somebody in this household is
female" rather than requiring a household to be female.

Unknown field names are an error rather than a silent no-match. A query that
quietly matches nothing looks exactly like an honest empty result, and the
person reading it cannot tell which they got.

Two implementations, one grammar
--------------------------------
This module is the reference: it runs in the terminal and it is what the tests
exercise. `report_style.QUERY_JS` is its twin, running in the page. They are
kept honest by `EXAMPLES` below - every one is parsed and evaluated here by the
test suite, and the same list is embedded in each page and re-run in the
browser, so a divergence shows up as a page whose own examples fail.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import difflib
import re


class QueryError(ValueError):
    """A query that cannot be parsed, or names a field that does not exist."""


TEXT, NUMBER, LIST, BOOL = 'text', 'number', 'list', 'bool'

_TOKEN = re.compile(r'''
    \s*(?:
      (?P<lparen>\()
    | (?P<rparen>\))
    | (?P<op>>=|<=|!=|:|=|>|<)
    | (?P<quoted>"[^"]*"|'[^']*')
    | (?P<word>[^\s()"':=<>!&|-][^\s()"':=<>!]*|[-!&|]+)
    )
''', re.X)


def tokenize(text):
    out, i = [], 0
    while i < len(text):
        m = _TOKEN.match(text, i)
        if not m or m.end() == i:
            if text[i].isspace():
                i += 1
                continue
            raise QueryError('cannot read %r at position %d' % (text[i], i))
        i = m.end()
        kind = m.lastgroup
        val = m.group(kind)
        if kind == 'quoted':
            out.append(('value', val[1:-1]))
        elif kind == 'word':
            upper = val.upper()
            if upper in ('AND', 'OR', 'NOT'):
                out.append((upper.lower(), val))
            elif val in ('&', '&&'):
                out.append(('and', val))
            elif val in ('|', '||'):
                out.append(('or', val))
            elif val in ('-', '!'):
                out.append(('not', val))
            else:
                out.append(('value', val))
        else:
            out.append((kind, val))
    return out


class _Parser:
    def __init__(self, tokens, schema):
        self.t, self.i, self.schema = tokens, 0, schema

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        if not self.t:
            return ('all',)
        node = self.parse_or()
        if self.i < len(self.t):
            raise QueryError('unexpected %r' % (self.t[self.i][1],))
        return node

    def parse_or(self):
        node = self.parse_and()
        while self.peek()[0] == 'or':
            self.take()
            node = ('or', node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_unary()
        while True:
            kind = self.peek()[0]
            if kind == 'and':
                self.take()
            elif kind not in ('value', 'lparen', 'not'):
                return node
            node = ('and', node, self.parse_unary())

    def parse_unary(self):
        if self.peek()[0] == 'not':
            self.take()
            return ('not', self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        kind, val = self.take()
        if kind == 'lparen':
            node = self.parse_or()
            if self.take()[0] != 'rparen':
                raise QueryError('missing )')
            return node
        if kind != 'value':
            raise QueryError('expected a term, got %r' % (val,))
        # A field comparison only if an operator actually follows; otherwise
        # this is a bare word and the colon-looking thing was part of a name.
        if self.peek()[0] == 'op':
            _k, op = self.take()
            nxt = self.peek()
            if nxt[0] != 'value':
                raise QueryError('%s%s needs a value' % (val, op))
            self.take()
            field = val.lower()
            if field not in self.schema:
                raise QueryError(
                    'no field called %r. Try: %s'
                    % (val, ', '.join(sorted(self.schema))))
            # Ordering a text field is refused HERE rather than while matching,
            # so it is an error about the query instead of a run that quietly
            # returns nothing. `name>Goth` used to match no rows and look like
            # an honest answer.
            if op in ('>', '>=', '<', '<=') and self.schema[field] == TEXT:
                raise QueryError(
                    '%s is text, so %s does not mean anything on it. Use : for '
                    'a substring or = for an exact match.' % (val, op))
            return ('cmp', field, op, nxt[1])
        return ('free', val)


def parse(text, schema):
    """-> an AST. Raises QueryError with something a person can act on."""
    return _Parser(tokenize(text or ''), schema).parse()


def _as_number(v):
    try:
        return float(str(v).replace(',', '').lstrip('§$'))
    except (TypeError, ValueError):
        return None


def _values(row, field):
    v = row.get(field)
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple, set)) else [v]


def _one(op, have, want, kind):
    if kind == NUMBER or op in ('>', '>=', '<', '<='):
        a, b = _as_number(have), _as_number(want)
        if a is None or b is None:
            return False
        return {':': a == b, '=': a == b, '!=': a != b, '>': a > b,
                '>=': a >= b, '<': a < b, '<=': a <= b}[op]
    if kind == BOOL:
        want_true = str(want).lower() in ('1', 'true', 'yes', 'y')
        got = bool(have)
        return got == want_true if op in (':', '=') else got != want_true
    a, b = str(have).lower(), str(want).lower()
    if op == ':':
        return b in a
    if op == '=':
        return a == b
    if op == '!=':
        return a != b
    raise QueryError('%s does not work on text' % op)


def match(node, row, schema, free_fields):
    kind = node[0]
    if kind == 'all':
        return True
    if kind == 'and':
        return match(node[1], row, schema, free_fields) and \
               match(node[2], row, schema, free_fields)
    if kind == 'or':
        return match(node[1], row, schema, free_fields) or \
               match(node[2], row, schema, free_fields)
    if kind == 'not':
        return not match(node[1], row, schema, free_fields)
    if kind == 'free':
        want = node[1].lower()
        for f in free_fields:
            for v in _values(row, f):
                if want in str(v).lower():
                    return True
        return False
    _c, field, op, want = node
    kind = schema[field]
    got = _values(row, field)
    if want == '*':
        # `field:*` means "has one at all", which is how somebody excludes the
        # rows that make a negation surprising.
        present = [v for v in got if str(v).strip()]
        return bool(present) if op in (':', '=') else not present
    if not got or not [v for v in got if str(v).strip()]:
        # An absent value matches a negative comparison and nothing else, so
        # `-world:Windenburg` includes the households with no world at all.
        # `diagnose()` says so when they dominate the result.
        return op == '!='
    return any(_one(op, v, want, kind) for v in got)


def _walk(node):
    yield node
    for child in node[1:]:
        if isinstance(child, tuple) and child and isinstance(child[0], str) \
                and child[0] in ('and', 'or', 'not', 'cmp', 'free', 'all'):
            yield from _walk(child)


def _cmps(node):
    return [n for n in _walk(node) if n[0] == 'cmp']


def _adjacent(node):
    """(cmp, free) pairs written next to each other, which is what an unquoted
    two-word value parses into: `world:Willow Creek` is `world:Willow` AND the
    bare word `Creek`, silently a different question."""
    out = []
    for n in _walk(node):
        if n[0] == 'and' and n[1][0] == 'cmp' and n[2][0] == 'free':
            out.append((n[1], n[2]))
        elif n[0] == 'and' and n[1][0] == 'and' and n[1][2][0] == 'cmp' \
                and n[2][0] == 'free':
            out.append((n[1][2], n[2]))
    return out


def _column(rows, field):
    seen = []
    for r in rows:
        for v in _values(r, field):
            if v not in seen:
                seen.append(v)
    return seen


def _hits(rows, field, op, want, kind):
    return any(_one(op, v, want, kind)
               for r in rows for v in _values(r, field))


def _negated_fields(node, negated=False):
    """(field, term-as-written) for comparisons under a NOT.

    The term comes back with the field because that is what the note has to
    quote - `-world` on its own is not something anybody can type.
    """
    out = set()
    if node[0] == 'not':
        out |= _negated_fields(node[1], not negated)
    elif node[0] in ('and', 'or'):
        for child in node[1:]:
            out |= _negated_fields(child, negated)
    elif node[0] == 'cmp' and negated:
        _c, field, op, want = node
        shown = '%s%s%s' % (field, op, ('"%s"' % want) if ' ' in str(want)
                            else want)
        out.add((field, '-' + shown))
    return out


def diagnose(rows, node, schema, matched):
    """Things worth saying about a query that ran without erroring.

    Every one of these is a way a query answers a slightly different question
    than the one asked while looking perfectly successful:

      * a two-word value written without quotes, which parses as a one-word
        match plus a loose word and can even return a plausible count
      * a value that appears nowhere in that column, which returns zero and is
        indistinguishable from an honest "you have none of those"
      * a negated field where most of what came back has no value for it at
        all - `-world:Windenburg` is true of every homeless household, and on
        a real save they were 34 of the 41 rows returned
    """
    notes = []

    for cmp_node, free_node in _adjacent(node):
        _c, field, op, want = cmp_node
        kind = schema.get(field)
        if kind not in (TEXT, LIST) or op not in (':', '='):
            continue
        joined = '%s %s' % (want, free_node[1])
        if _hits(rows, field, op, joined, kind):
            notes.append(
                'did you mean %s:"%s"? As written, %s:%s is one term and %s is '
                'a separate word searched on its own.'
                % (field, joined, field, want, free_node[1]))

    for _c, field, op, want in _cmps(node):
        kind = schema.get(field)
        if kind not in (TEXT, LIST) or op not in (':', '='):
            continue
        if want == '*':                       # a presence check, not a value
            continue
        if _hits(rows, field, op, want, kind):
            continue
        column = [str(v) for v in _column(rows, field) if str(v)]
        near = difflib.get_close_matches(str(want), column, n=3, cutoff=0.6)
        if not near:
            low = str(want).lower()
            near = [v for v in column if low in v.lower()][:3]
        msg = 'nothing has %s matching %r' % (field, want)
        if near:
            msg += '. Closest: %s' % ', '.join('"%s"' % v for v in near)
        elif len(column) <= 12:
            msg += '. This save has: %s' % ', '.join('"%s"' % v
                                                     for v in sorted(column))
        notes.append(msg)

    for field, term in sorted(_negated_fields(node)):
        blank = [r for r in matched if not [v for v in _values(r, field)
                                            if str(v).strip()]]
        if blank and len(blank) * 2 >= len(matched):
            # Quote the WHOLE term. Saying `"not world" is true of them` reads
            # as though `-world` were a thing you can write, and it is not -
            # the minus negates an entire term, so the value has to come with
            # it or the note teaches a syntax that does not exist.
            notes.append(
                '%d of these %d have no %s at all, and %s is true of them. '
                'Add %s:* to require one.'
                % (len(blank), len(matched), field, term, field))
    return notes


def run(rows, text, schema, free_fields):
    """Filter `rows`. -> (matching rows, notes worth reading).

    The notes are not warnings about failure - the query ran. They are the
    ways it can succeed at answering something else.
    """
    node = parse(text, schema)
    hits = [r for r in rows if match(node, r, schema, free_fields)]
    return hits, diagnose(rows, node, schema, hits)


# Kept here rather than in the docs so the tests and the pages use the same
# list. Each is a question somebody would ask, in the form the language takes.
EXAMPLES = [
    ('every female living alone, except in Windenburg',
     'size:1 gender:female -world:Windenburg'),
    ('households with more than four Sims', 'size>4'),
    ('anyone poorer than 1000 simoleons', 'funds<1000'),
    ('households with no home at all', 'housed:false'),
    ('single women, and only ones who actually live somewhere',
     'size:1 gender:female world:*'),
    ('cats or dogs', 'species:cat OR species:dog'),
    ('rich families in Willow Creek or Oasis Springs',
     'funds>=50000 (world:"Willow Creek" OR world:"Oasis Springs")'),
    ('a household called exactly Goth', 'name=Goth'),
    ('elders living alone with a pet', 'size:2 age:elder pets>0'),
]
