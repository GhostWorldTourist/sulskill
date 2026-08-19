"""Static reader for The Sims 4's Python 3.7 gameplay bytecode.

Two layers:

  * a 3.7 opcode table + linear symbolic evaluator (`Frame.run`) that
    reconstructs expressions from straight-line bytecode without executing
    anything, and
  * helpers built on it: class discovery (`classes_in`), and tunable-schema
    recovery (`tunables_of`) for the declarative TunableFactory dicts EA
    writes in class bodies.

The evaluator is deliberately linear: it ignores jumps. Class bodies and
module-level tuning declarations are straight-line, so this is exact for the
thing we care about and merely noisy elsewhere. Anything it cannot model
becomes an `Unknown` node rather than a wrong answer.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# pyc37 is shared with sulskill-modbuild rather than copied: a second
# copy of a Python 3.7 marshal reader is a second thing to keep correct.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'sulskill-modbuild', 'scripts'))
import pyc37  # noqa: E402
from pyc37 import Code  # noqa: E402

# --------------------------------------------------------------------------
# CPython 3.7 opcodes (only what the gameplay code emits)
# --------------------------------------------------------------------------
POP_TOP = 1
ROT_TWO, ROT_THREE, DUP_TOP, DUP_TOP_TWO = 2, 3, 4, 5
NOP = 9
UNARY_POSITIVE, UNARY_NEGATIVE, UNARY_NOT, UNARY_INVERT = 10, 11, 12, 15
STORE_SUBSCR, DELETE_SUBSCR = 60, 61
GET_ITER = 68
LOAD_BUILD_CLASS = 71
YIELD_FROM = 72
GET_AWAITABLE = 73
RETURN_VALUE = 83
IMPORT_STAR = 84
SETUP_ANNOTATIONS = 85
YIELD_VALUE = 86
POP_BLOCK, END_FINALLY, POP_EXCEPT = 87, 88, 89
STORE_NAME, DELETE_NAME = 90, 91
UNPACK_SEQUENCE, FOR_ITER, UNPACK_EX = 92, 93, 94
STORE_ATTR, DELETE_ATTR = 95, 96
STORE_GLOBAL, DELETE_GLOBAL = 97, 98
LOAD_CONST, LOAD_NAME = 100, 101
BUILD_TUPLE, BUILD_LIST, BUILD_SET, BUILD_MAP = 102, 103, 104, 105
LOAD_ATTR, COMPARE_OP, IMPORT_NAME, IMPORT_FROM = 106, 107, 108, 109
JUMP_FORWARD = 110
JUMP_IF_FALSE_OR_POP, JUMP_IF_TRUE_OR_POP = 111, 112
JUMP_ABSOLUTE, POP_JUMP_IF_FALSE, POP_JUMP_IF_TRUE = 113, 114, 115
LOAD_GLOBAL = 116
CONTINUE_LOOP, SETUP_LOOP, SETUP_EXCEPT, SETUP_FINALLY = 119, 120, 121, 122
LOAD_FAST, STORE_FAST, DELETE_FAST = 124, 125, 126
RAISE_VARARGS = 130
CALL_FUNCTION, MAKE_FUNCTION, BUILD_SLICE = 131, 132, 133
LOAD_CLOSURE, LOAD_DEREF, STORE_DEREF, DELETE_DEREF = 135, 136, 137, 138
CALL_FUNCTION_KW, CALL_FUNCTION_EX = 141, 142
SETUP_WITH = 143
EXTENDED_ARG = 144
LIST_APPEND, SET_ADD, MAP_ADD = 145, 146, 147
LOAD_CLASSDEREF = 148
BUILD_LIST_UNPACK, BUILD_MAP_UNPACK = 149, 150
BUILD_MAP_UNPACK_WITH_CALL, BUILD_TUPLE_UNPACK, BUILD_SET_UNPACK = 151, 152, 153
SETUP_ASYNC_WITH = 154
FORMAT_VALUE, BUILD_CONST_KEY_MAP, BUILD_STRING = 155, 156, 157
BUILD_TUPLE_UNPACK_WITH_CALL = 158
LOAD_METHOD, CALL_METHOD = 160, 161

HAVE_ARG = 90

BINOPS = {
    16: '@', 19: '**', 20: '*', 22: '%', 23: '+', 24: '-', 25: '[]',
    26: '//', 27: '/', 62: '<<', 63: '>>', 64: '&', 65: '^', 66: '|',
}
INPLACE = {
    17: '@', 55: '+', 56: '-', 57: '*', 59: '%', 67: '**',
    28: '//', 29: '/', 75: '<<', 76: '>>', 77: '&', 78: '^', 79: '|',
}
CMP_OPS = ('<', '<=', '==', '!=', '>', '>=', 'in', 'not in', 'is',
           'is not', 'exception match', 'BAD')


def ops(co):
    """Yield (offset, op, arg) from 3.7 wordcode, folding EXTENDED_ARG."""
    ext = 0
    code = co.code
    for i in range(0, len(code), 2):
        op, arg = code[i], code[i + 1] | ext
        if op == EXTENDED_ARG:
            ext = arg << 8
            continue
        ext = 0
        yield i, op, arg


# --------------------------------------------------------------------------
# expression nodes
# --------------------------------------------------------------------------
class Node:
    kind = 'node'

    def __repr__(self):
        return self.render()

    def render(self):
        return '?'


class Const(Node):
    kind = 'const'

    def __init__(self, v):
        self.value = v

    def render(self):
        v = self.value
        if isinstance(v, Code):
            return '<code %s>' % v.name
        return repr(v)


class Name(Node):
    kind = 'name'

    def __init__(self, n):
        self.id = n

    def render(self):
        return self.id


class Attr(Node):
    kind = 'attr'

    def __init__(self, obj, attr):
        self.obj, self.attr = obj, attr

    def render(self):
        return '%s.%s' % (self.obj.render(), self.attr)


class Call(Node):
    kind = 'call'

    def __init__(self, func, args, kwargs, star=False):
        self.func, self.args, self.kwargs, self.star = func, args, kwargs, star

    @property
    def name(self):
        f = self.func
        return f.render() if isinstance(f, (Name, Attr)) else f.render()

    @property
    def base(self):
        """Bare callable name, without dotted prefix."""
        return self.name.rsplit('.', 1)[-1]

    def render(self):
        parts = [a.render() for a in self.args]
        parts += ['%s=%s' % (k, v.render()) for k, v in self.kwargs.items()]
        if self.star:
            parts.append('...')
        return '%s(%s)' % (self.name, ', '.join(parts))


class Seq(Node):
    def __init__(self, kind, items):
        self.kind, self.items = kind, items

    def render(self):
        inner = ', '.join(i.render() for i in self.items)
        if self.kind == 'tuple':
            return '(%s)' % inner
        if self.kind == 'list':
            return '[%s]' % inner
        return '{%s}' % inner


class DictNode(Node):
    kind = 'dict'

    def __init__(self, items):
        self.items = items          # list of (Node key, Node value)

    def str_items(self):
        out = []
        for k, v in self.items:
            if isinstance(k, Const) and isinstance(k.value, str):
                out.append((k.value, v))
        return out

    def render(self):
        return '{%s}' % ', '.join('%s: %s' % (k.render(), v.render())
                                  for k, v in self.items)


class Op(Node):
    kind = 'op'

    def __init__(self, sym, *operands):
        self.sym, self.operands = sym, operands

    def render(self):
        if len(self.operands) == 1:
            return '%s%s' % (self.sym, self.operands[0].render())
        if self.sym == '[]':
            return '%s[%s]' % (self.operands[0].render(),
                               self.operands[1].render())
        return '(%s %s %s)' % (self.operands[0].render(), self.sym,
                               self.operands[1].render())


class Func(Node):
    kind = 'func'

    def __init__(self, code, qualname):
        self.code, self.qualname = code, qualname

    def render(self):
        return '<function %s>' % self.qualname


class ClassDef(Node):
    kind = 'class'

    def __init__(self, name, body, bases, kwargs):
        self.name, self.body, self.bases, self.kwargs = name, body, bases, kwargs

    def render(self):
        return '<class %s(%s)>' % (self.name,
                                   ', '.join(b.render() for b in self.bases))


class Unknown(Node):
    kind = 'unknown'

    def __init__(self, why=''):
        self.why = why

    def render(self):
        return '<?%s>' % (':' + self.why if self.why else '')


BUILD_CLASS = Node()
BUILD_CLASS.render = lambda: '__build_class__'


# --------------------------------------------------------------------------
# the evaluator
# --------------------------------------------------------------------------
class Frame:
    """Linear symbolic execution of one code object.

    `store` accumulates STORE_NAME assignments in order; `classes` collects
    every __build_class__ call seen anywhere in the frame.
    """

    def __init__(self, co):
        self.co = co
        self.stack = []
        self.store = []             # (name, Node) in source order
        self.classes = []           # ClassDef
        self.calls = []             # every Call built, in source order

    # -- stack helpers -----------------------------------------------------
    def pop(self, n=1):
        if n == 0:
            return []
        if len(self.stack) < n:
            missing = n - len(self.stack)
            got = self.stack[:]
            self.stack = []
            return [Unknown('underflow')] * missing + got
        out = self.stack[-n:]
        del self.stack[-n:]
        return out

    def push(self, v):
        self.stack.append(v)

    # -- main loop ---------------------------------------------------------
    def run(self):
        co = self.co
        for _off, op, arg in ops(co):
            try:
                self.step(op, arg)
            except Exception:                                # noqa: BLE001
                self.stack = []
        return self

    def step(self, op, arg):
        co = self.co
        if op == LOAD_CONST:
            self.push(Const(co.consts[arg]))
        elif op == LOAD_NAME:
            self.push(Name(co.names[arg]))
        elif op == LOAD_GLOBAL:
            self.push(Name(co.names[arg]))
        elif op == LOAD_FAST:
            self.push(Name(co.varnames[arg]))
        elif op in (LOAD_DEREF, LOAD_CLASSDEREF, LOAD_CLOSURE):
            cells = co.cellvars + co.freevars
            self.push(Name(cells[arg] if arg < len(cells) else '<cell%d>' % arg))
        elif op in (LOAD_ATTR, LOAD_METHOD):
            (obj,) = self.pop(1)
            self.push(Attr(obj, co.names[arg]))
        elif op == STORE_NAME:
            (v,) = self.pop(1)
            self.store.append((co.names[arg], v))
        elif op in (STORE_FAST,):
            self.pop(1)
        elif op in (STORE_GLOBAL, STORE_DEREF):
            self.pop(1)
        elif op == STORE_ATTR:
            self.pop(2)
        elif op == STORE_SUBSCR:
            self.pop(3)
        elif op == DELETE_SUBSCR:
            self.pop(2)
        elif op in (CALL_FUNCTION, CALL_METHOD):
            args = self.pop(arg)
            (f,) = self.pop(1)
            self.push(self._call(f, args, {}))
        elif op == CALL_FUNCTION_KW:
            (names,) = self.pop(1)
            kwnames = names.value if isinstance(names, Const) else ()
            if not isinstance(kwnames, tuple):
                kwnames = ()
            vals = self.pop(arg)
            npos = len(vals) - len(kwnames)
            args = vals[:npos]
            kwargs = dict(zip(kwnames, vals[npos:]))
            (f,) = self.pop(1)
            self.push(self._call(f, args, kwargs))
        elif op == CALL_FUNCTION_EX:
            # f(*args) or f(*args, **kw). Keep whatever literal keywords the
            # mapping still carries -- factories declare their whole schema
            # as `super().__init__(field=Tunable(...), ..., **kwargs)`.
            got = self.pop(2 if arg & 0x01 else 1)
            kwargs = {}
            if arg & 0x01 and isinstance(got[-1], DictNode):
                for k, v in got[-1].str_items():
                    kwargs[k] = v
            args = []
            if isinstance(got[0], Seq):
                args = list(got[0].items)
            (f,) = self.pop(1)
            self.push(self._call(f, args, kwargs, star=True))
        elif op == BUILD_TUPLE:
            self.push(Seq('tuple', self.pop(arg)))
        elif op == BUILD_LIST:
            self.push(Seq('list', self.pop(arg)))
        elif op == BUILD_SET:
            self.push(Seq('set', self.pop(arg)))
        elif op == BUILD_STRING:
            self.pop(arg)
            self.push(Unknown('fstring'))
        elif op == BUILD_MAP:
            flat = self.pop(arg * 2)
            self.push(DictNode([(flat[i], flat[i + 1])
                                for i in range(0, len(flat), 2)]))
        elif op == BUILD_CONST_KEY_MAP:
            (keys,) = self.pop(1)
            vals = self.pop(arg)
            kt = keys.value if isinstance(keys, Const) else ()
            if not isinstance(kt, tuple):
                kt = ()
            self.push(DictNode(list(zip([Const(k) for k in kt], vals))))
        elif op in (BUILD_MAP_UNPACK, BUILD_MAP_UNPACK_WITH_CALL):
            parts = self.pop(arg)
            merged = []
            for p in parts:
                if isinstance(p, DictNode):
                    merged.extend(p.items)
            self.push(DictNode(merged))
        elif op in (BUILD_TUPLE_UNPACK, BUILD_TUPLE_UNPACK_WITH_CALL,
                    BUILD_LIST_UNPACK, BUILD_SET_UNPACK):
            parts = self.pop(arg)
            merged = []
            for p in parts:
                if isinstance(p, Seq):
                    merged.extend(p.items)
                else:
                    merged.append(Op('*', p))
            self.push(Seq('tuple' if op in (BUILD_TUPLE_UNPACK,
                                            BUILD_TUPLE_UNPACK_WITH_CALL)
                          else 'list', merged))
        elif op == MAKE_FUNCTION:
            code, qual = self.pop(2)
            extras = bin(arg).count('1')
            self.pop(extras)
            q = qual.value if isinstance(qual, Const) else '?'
            c = code.value if isinstance(code, Const) else None
            self.push(Func(c, q))
        elif op == LOAD_BUILD_CLASS:
            self.push(BUILD_CLASS)
        elif op == BUILD_SLICE:
            self.pop(arg)
            self.push(Unknown('slice'))
        elif op == COMPARE_OP:
            a, b = self.pop(2)
            self.push(Op(CMP_OPS[arg] if arg < len(CMP_OPS) else '?', a, b))
        elif op in BINOPS:
            a, b = self.pop(2)
            self.push(Op(BINOPS[op], a, b))
        elif op in INPLACE:
            a, b = self.pop(2)
            self.push(Op(INPLACE[op], a, b))
        elif op in (UNARY_NEGATIVE, UNARY_POSITIVE, UNARY_NOT, UNARY_INVERT):
            (a,) = self.pop(1)
            self.push(Op({UNARY_NEGATIVE: '-', UNARY_POSITIVE: '+',
                          UNARY_NOT: 'not ', UNARY_INVERT: '~'}[op], a))
        elif op == POP_TOP:
            self.pop(1)
        elif op == DUP_TOP:
            if self.stack:
                self.push(self.stack[-1])
        elif op == DUP_TOP_TWO:
            if len(self.stack) >= 2:
                self.stack.extend(self.stack[-2:])
        elif op == ROT_TWO:
            if len(self.stack) >= 2:
                self.stack[-1], self.stack[-2] = self.stack[-2], self.stack[-1]
        elif op == ROT_THREE:
            if len(self.stack) >= 3:
                a = self.stack.pop()
                self.stack.insert(-2, a)
        elif op == IMPORT_NAME:
            self.pop(2)
            self.push(Name(co.names[arg]))
        elif op == IMPORT_FROM:
            self.push(Name(co.names[arg]))
        elif op in (RETURN_VALUE, YIELD_VALUE, POP_JUMP_IF_FALSE,
                    POP_JUMP_IF_TRUE, GET_ITER, YIELD_FROM, GET_AWAITABLE,
                    RAISE_VARARGS, IMPORT_STAR, LIST_APPEND, SET_ADD):
            if op == RAISE_VARARGS:
                self.pop(arg)
            elif op in (RETURN_VALUE, YIELD_VALUE, POP_JUMP_IF_FALSE,
                        POP_JUMP_IF_TRUE, IMPORT_STAR):
                self.pop(1)
            elif op in (LIST_APPEND, SET_ADD):
                self.pop(1)
        elif op == MAP_ADD:
            self.pop(2)
        elif op == FORMAT_VALUE:
            self.pop(2 if arg & 0x04 else 1)
            self.push(Unknown('format'))
        elif op in (UNPACK_SEQUENCE, UNPACK_EX):
            self.pop(1)
            n = arg if op == UNPACK_SEQUENCE else (arg & 0xFF) + (arg >> 8) + 1
            for _ in range(n):
                self.push(Unknown('unpack'))
        elif op in (JUMP_IF_FALSE_OR_POP, JUMP_IF_TRUE_OR_POP):
            pass
        elif op in (FOR_ITER,):
            self.push(Unknown('iter'))
        else:
            # jumps, block setup, exception machinery, NOP: no model needed
            pass

    def _call(self, f, args, kwargs, star=False):
        if f is BUILD_CLASS:
            # __build_class__(func, name, *bases, **kwds)
            body = args[0] if args else Unknown()
            nm = args[1].value if len(args) > 1 and isinstance(args[1], Const) \
                else '?'
            cd = ClassDef(nm, body.code if isinstance(body, Func) else None,
                          list(args[2:]), kwargs)
            self.classes.append(cd)
            return cd
        c = Call(f, list(args), dict(kwargs), star=star)
        self.calls.append(c)
        return c


# --------------------------------------------------------------------------
# module-level helpers
# --------------------------------------------------------------------------
def is_class_body(co):
    return (len(co.names) >= 2 and co.names[0] == '__name__'
            and co.names[1] == '__module__')


def module_of(zf, arcname):
    return arcname[:-4].replace('/', '.').replace('\\', '.')


def load(zf, arcname):
    return pyc37.load_pyc(zf.read(arcname))


def scan_module(co):
    """Walk every code object, evaluating each frame.

    Returns (frames_by_code_id, classdefs) where classdefs is a list of
    (ClassDef, owning Frame) in definition order across the whole module.
    """
    out = []
    for c, _d in pyc37.walk(co):
        f = Frame(c).run()
        if f.classes:
            out.append((c, f))
    return out
