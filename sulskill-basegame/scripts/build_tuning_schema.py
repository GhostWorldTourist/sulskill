"""Recover the tunable schema of the gameplay tuning types from bytecode.

EA declares every tuning type's shape declaratively, as a dict of
Tunable*(...) constructor calls assigned to INSTANCE_TUNABLES (for
instance-tuning classes) or FACTORY_TUNABLES (for TunableFactory
sub-blocks), in the class body. The class body is a code object; the dict is
built by BUILD_CONST_KEY_MAP/BUILD_MAP from LOAD_CONST keys and constructor
calls whose keyword arguments -- including the human-readable
`description=` EA writes for the tuning editor -- are literal constants.

So the schema is fully present in the shipped bytecode and needs no
execution to read. This walks it and emits:

    out/tuning_schema.md    prose, per tuning type
    out/tunables.json       every class that declares tunables, machine form

Run after build_api.py (it reads out/python_api.jsonl for the class index).
"""
import collections
import io
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: F401,E402
import pyapi  # noqa: E402
import restypes  # noqa: E402
from pyapi import Attr, Call, Const, DictNode, Name, Node, Op, Seq  # noqa: E402

GAME = os.environ.get('TS4_INSTALL') or gate.game_dir()
GAMEPLAY = os.path.join(GAME, 'Data', 'Simulation', 'Gameplay')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(gate.out_dir(), 'basegame')

BLOCKS = ('INSTANCE_TUNABLES', 'FACTORY_TUNABLES', 'REMOVE_INSTANCE_TUNABLES')

# kwargs that carry structure, not decoration
NOISE = {'description', 'tuning_group', 'export_modes', 'display_name',
         'tuning_filter', 'deprecated', 'needs_tuning', 'callback',
         'verify_tunable_callback', 'unique_entries', 'tuple_name',
         'locked_args_verification'}


# --------------------------------------------------------------------------
# harvesting
# --------------------------------------------------------------------------
def harvest():
    """{(module, qualname): {'bases':…, 'meta':…, 'blocks':{name:[(k,Node)]}}}"""
    out = {}
    for arcname, zp in (('simulation', os.path.join(GAMEPLAY, 'simulation.zip')),
                        ('core', os.path.join(GAMEPLAY, 'core.zip'))):
        z = zipfile.ZipFile(zp)
        for arc in sorted(z.namelist()):
            if not arc.endswith('.pyc'):
                continue
            mod = arc[:-4].replace('/', '.')
            try:
                co = pyapi.load(z, arc)
            except Exception:                                 # noqa: BLE001
                continue
            _walk_frame(pyapi.Frame(co).run(), mod, out)
    return out


def _walk_frame(frame, mod, out, prefix=''):
    for cd in frame.classes:
        if cd.body is None:
            continue
        bf = pyapi.Frame(cd.body).run()
        qual = prefix + cd.name
        blocks = {}
        attrs = {}
        for name, v in bf.store:
            if name in BLOCKS:
                if isinstance(v, DictNode):
                    blocks[name] = v.str_items()
                elif isinstance(v, Seq):
                    blocks[name] = [(i.value, None) for i in v.items
                                    if isinstance(i, Const)]
                elif isinstance(v, Const) and isinstance(v.value, (tuple, list)):
                    blocks[name] = [(x, None) for x in v.value
                                    if isinstance(x, str)]
                elif isinstance(v, Name) and v.id in blocks:
                    blocks[name] = list(blocks[v.id])
                else:
                    blocks[name] = []
            elif not name.startswith('__') and isinstance(
                    v, (Const, Call, Name, Attr, Seq, DictNode, Op)):
                attrs[name] = v
        bases = [b.render() for b in cd.bases]
        # second declaration style: a Tunable* subclass whose whole schema is
        # the keyword list of its super().__init__ call, not a dict in the
        # class body. TunableCommodityState is the canonical example.
        if (not blocks and any(w in b for b in bases
                               for w in ('Tunable', 'Factory', 'Variant'))):
            kw = _init_kwargs(bf)
            if kw:
                blocks['FACTORY_INIT'] = kw
        out[(mod, qual)] = {
            'bases': bases,
            'meta': {k: x.render() for k, x in cd.kwargs.items()},
            'blocks': blocks,
            'attrs': attrs,
            'line': cd.body.firstlineno,
        }
        _walk_frame(bf, mod, out, qual + '.')


def _init_kwargs(class_frame):
    """[(field, Node)] from the widest `super().__init__(**literals)` call."""
    best = []
    for name, v in class_frame.store:
        if name != '__init__' or not hasattr(v, 'code') or v.code is None:
            continue
        for c in pyapi.Frame(v.code).run().calls:
            if c.base == '__init__' and len(c.kwargs) > len(best):
                best = [(k, x) for k, x in c.kwargs.items()
                        if k not in ('description', 'kwargs')]
    return best


# --------------------------------------------------------------------------
# rendering a tunable declaration compactly
# --------------------------------------------------------------------------
def desc_of(node):
    if isinstance(node, Call):
        d = node.kwargs.get('description')
        if isinstance(d, Const) and isinstance(d.value, str):
            return re.sub(r'\s+', ' ', d.value).strip()
        for a in node.args:
            s = desc_of(a)
            if s:
                return s
    return ''


def callee(node):
    """Readable callee name: drop lowercase module prefix, keep the rest.

    `game_effect_modifier.GameEffectModifiers.TunableFactory` becomes
    `GameEffectModifiers.TunableFactory`, which is the part that says what
    the field actually is; `sims4.tuning.tunable.TunableReference` becomes
    `TunableReference`.
    """
    full = node.name
    parts = full.split('.')
    for i, p in enumerate(parts):
        if p[:1].isupper():
            return '.'.join(parts[i:])
    return parts[-1]


def short(node, depth=0):
    """Structure-preserving one-line type for a tunable declaration."""
    if node is None:
        return '?'
    if isinstance(node, Const):
        v = node.value
        if isinstance(v, str):
            return repr(v if len(v) < 40 else v[:37] + '...')
        return repr(v)
    if isinstance(node, (Name, Attr, Op, Seq, DictNode)):
        return node.render()[:120]
    if isinstance(node, Call):
        if depth > 3:
            return callee(node) + '(...)'
        parts = []
        for a in node.args:
            parts.append(short(a, depth + 1))
        for k, v in node.kwargs.items():
            if k in NOISE:
                continue
            parts.append('%s=%s' % (k, short(v, depth + 1)))
        inner = ', '.join(parts)
        if len(inner) > 200:
            inner = inner[:197] + '...'
        return '%s(%s)' % (callee(node), inner)
    return node.render()[:120]


# --------------------------------------------------------------------------
# hierarchy
# --------------------------------------------------------------------------
def build_index(classes):
    """simple-name -> [(module, qualname)] for base resolution."""
    idx = collections.defaultdict(list)
    for (mod, qual) in classes:
        idx[qual.rsplit('.', 1)[-1]].append((mod, qual))
        idx[qual].append((mod, qual))
    return idx


def resolve_base(bname, idx, home_mod):
    """Best-effort: a rendered base expression -> (module, qualname)."""
    simple = bname.rsplit('.', 1)[-1]
    cands = idx.get(simple) or []
    if not cands:
        return None
    same = [c for c in cands if c[0] == home_mod]
    if same:
        return same[0]
    # prefer a module sharing the top-level package
    pkg = home_mod.split('.')[0]
    near = [c for c in cands if c[0].split('.')[0] == pkg]
    if len(cands) == 1:
        return cands[0]
    if near:
        return near[0]
    return cands[0] if len(cands) < 4 else None


def mro_chain(key, classes, idx, seen=None):
    """Linearised base chain (depth-first, dedup) for tunable accumulation."""
    if seen is None:
        seen = []
    if key in seen or key not in classes:
        return seen
    seen.append(key)
    mod = key[0]
    for b in classes[key]['bases']:
        r = resolve_base(b, idx, mod)
        if r and r != key:
            mro_chain(r, classes, idx, seen)
    return seen


def subclasses(classes, idx):
    """(module, qualname) -> set of direct subclass keys."""
    kids = collections.defaultdict(set)
    for key, rec in classes.items():
        for b in rec['bases']:
            r = resolve_base(b, idx, key[0])
            if r:
                kids[r].add(key)
    return kids


def descendants(key, kids, limit=4000):
    out, stack = set(), [key]
    while stack and len(out) < limit:
        k = stack.pop()
        for c in kids.get(k, ()):
            if c not in out:
                out.add(c)
                stack.append(c)
    return out


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    cs = harvest()
    print('classes harvested:', len(cs))
    n = sum(1 for r in cs.values() if r['blocks'])
    print('classes declaring tunable blocks:', n)
