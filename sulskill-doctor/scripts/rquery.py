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
    if not got:
        # An absent value matches a negative comparison and nothing else, so
        # `-world:Windenburg` includes the households with no world at all.
        return op == '!='
    return any(_one(op, v, want, kind) for v in got)


def run(rows, text, schema, free_fields):
    """Filter `rows`. -> (matching rows, the parsed AST)."""
    node = parse(text, schema)
    return [r for r in rows if match(node, r, schema, free_fields)], node


# Kept here rather than in the docs so the tests and the pages use the same
# list. Each is a question somebody would ask, in the form the language takes.
EXAMPLES = [
    ('every female living alone, except in Windenburg',
     'size:1 gender:female -world:Windenburg'),
    ('households with more than four Sims', 'size>4'),
    ('anyone poorer than 1000 simoleons', 'funds<1000'),
    ('households with no home at all', '-housed:true'),
    ('cats or dogs', 'species:cat OR species:dog'),
    ('rich families in Willow Creek or Oasis Springs',
     'funds>=50000 (world:"Willow Creek" OR world:"Oasis Springs")'),
    ('a household called exactly Goth', 'name=Goth'),
    ('elders living alone with a pet', 'size:2 age:elder pets>0'),
]
