"""Inventory every module/class/method in the shipped gameplay bytecode.

Writes one JSON object per module to out/python_api.jsonl:

    {"module": "buffs.buff", "archive": "simulation", "file": "T:\\...",
     "classes": [{"name": "Buff", "qualname": "Buff", "line": 124,
                  "bases": [...], "meta": {"metaclass": "...",
                  "manager": "..."}, "tuning_type": "BUFF",
                  "tunable_blocks": {"INSTANCE_TUNABLES": [...names...]},
                  "methods": [{"name": ..., "sig": ..., "line": ...,
                               "deco": "property"}],
                  "attrs": [[name, rendered]]}],
     "functions": [...], "constants": [[name, rendered]]}

Nothing is executed. See pyapi.py for the evaluator.
"""
import io
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: F401,E402
import pyapi  # noqa: E402
from pyapi import Attr, Call, Const, DictNode, Func, Name, Seq  # noqa: E402

GAME = os.environ.get('TS4_INSTALL') or gate.game_dir()
GAMEPLAY = os.path.join(GAME, 'Data', 'Simulation', 'Gameplay')
ARCHIVES = {'simulation': os.path.join(GAMEPLAY, 'simulation.zip'),
            'core': os.path.join(GAMEPLAY, 'core.zip')}

OUT = os.path.join(gate.out_dir(), 'basegame')

DECOS = ('property', 'staticmethod', 'classmethod', 'blueprintmethod',
         'blueprintproperty', 'classproperty', 'flexmethod', 'flexproperty',
         'constproperty', 'exception_protected', 'cached', 'distributor',
         'contextmanager', 'abstractmethod')

TUNING_BLOCK = re.compile(r'^(INSTANCE_TUNABLES|FACTORY_TUNABLES|'
                          r'REMOVE_INSTANCE_TUNABLES|INSTANCE_SUBCLASSES_ONLY|'
                          r'_TUNABLES)$')

MANAGER_RE = re.compile(r'Types\.([A-Z0-9_]+)')


def unwrap(v):
    """(Func, decorator-name) for a class-body value, else (None, None)."""
    if isinstance(v, Func):
        return v, None
    if isinstance(v, Call):
        base = v.base
        for a in v.args:
            f, _ = unwrap(a)
            if f is not None:
                return f, base
    return None, None


def sig_of(code, name):
    if code is None:
        return name + '(?)'
    s = code.signature()
    return s if s.startswith(name + '(') else name + s[s.index('('):]


def class_record(cd, line_hint=None):
    body = cd.body
    if body is None:
        return None
    bf = pyapi.Frame(body).run()
    rec = {'name': cd.name, 'line': body.firstlineno,
           'bases': [b.render() for b in cd.bases],
           'meta': {k: v.render() for k, v in cd.kwargs.items()}}
    mgr = rec['meta'].get('manager', '')
    m = MANAGER_RE.search(mgr)
    if m:
        rec['tuning_type'] = m.group(1)
    methods, attrs, blocks = [], [], {}
    seen = set()
    for name, v in bf.store:
        if name in ('__module__', '__qualname__'):
            if name == '__qualname__' and isinstance(v, Const):
                rec['qualname'] = v.value
            continue
        f, deco = unwrap(v)
        if f is not None:
            key = (name, f.code.firstlineno if f.code else 0)
            if key in seen:
                continue
            seen.add(key)
            e = {'name': name, 'sig': sig_of(f.code, name),
                 'line': f.code.firstlineno if f.code else 0}
            if deco and deco in DECOS:
                e['deco'] = deco
            elif deco:
                e['deco'] = deco
            methods.append(e)
        elif TUNING_BLOCK.match(name):
            if isinstance(v, DictNode):
                blocks[name] = [k for k, _ in v.str_items()]
            elif isinstance(v, Seq):
                blocks[name] = [i.value for i in v.items
                                if isinstance(i, Const)]
            else:
                blocks[name] = []
        else:
            attrs.append([name, v.render()[:300]])
    rec['methods'] = methods
    if attrs:
        rec['attrs'] = attrs
    if blocks:
        rec['tunable_blocks'] = blocks
    # nested classes
    nested = [class_record(c) for c in bf.classes]
    nested = [n for n in nested if n]
    if nested:
        rec['nested'] = nested
    return rec


def module_record(archive, arcname, co):
    mf = pyapi.Frame(co).run()
    classes = [class_record(c) for c in mf.classes]
    classes = [c for c in classes if c]
    funcs, consts = [], []
    for name, v in mf.store:
        f, deco = unwrap(v)
        if f is not None:
            e = {'name': name, 'sig': sig_of(f.code, name),
                 'line': f.code.firstlineno if f.code else 0}
            if deco:
                e['deco'] = deco
            funcs.append(e)
        elif not name.startswith('__'):
            consts.append([name, v.render()[:300]])
    return {'module': arcname[:-4].replace('/', '.'),
            'archive': archive,
            'file': co.filename,
            'classes': classes,
            'functions': funcs,
            'constants': consts}


def count(cs):
    """(classes, methods) including nested classes."""
    nc = nm = 0
    for c in cs:
        nc += 1
        nm += len(c['methods'])
        sc, sm = count(c.get('nested', []))
        nc += sc
        nm += sm
    return nc, nm


def main():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'python_api.jsonl')
    nmod = ncls = nmeth = nfun = 0
    fails = []
    with io.open(path, 'w', encoding='utf-8', newline='\n') as fh:
        for archive, zp in ARCHIVES.items():
            z = zipfile.ZipFile(zp)
            for arc in sorted(z.namelist()):
                if not arc.endswith('.pyc'):
                    continue
                try:
                    co = pyapi.load(z, arc)
                    rec = module_record(archive, arc, co)
                except Exception as e:                        # noqa: BLE001
                    fails.append((archive, arc, repr(e)))
                    continue
                nmod += 1
                nfun += len(rec['functions'])

                c, m = count(rec['classes'])
                ncls += c
                nmeth += m
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    sys.stderr.write('modules=%d classes=%d methods=%d functions=%d fails=%d\n'
                     % (nmod, ncls, nmeth, nfun, len(fails)))
    for f in fails[:20]:
        sys.stderr.write('  FAIL %s %s %s\n' % f)


if __name__ == '__main__':
    main()
