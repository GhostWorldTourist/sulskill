"""Extract the authoritative resource-type table from the game's own code.

sims4.resources.Types is an enum whose class body does two things: plain
NAME = <int> assignments for binary resource types, and _add_inst_tuning(...)
calls for every tuning type the instance managers load. Both are recoverable
from the 3.7 bytecode without executing it.

Any type table written from a wiki is a guess. This one is the game's.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import sys, os, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# pyc37 is shared with sulskill-modbuild rather than copied: a second
# copy of a Python 3.7 marshal reader is a second thing to keep correct.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'sulskill-modbuild', 'scripts'))
import pyc37

GAME = os.environ.get('TS4_INSTALL') or gate.game_dir()
GAMEPLAY = os.path.join(GAME, 'Data', 'Simulation', 'Gameplay')
CORE = os.path.join(GAMEPLAY, 'core.zip')
SIMULATION = os.path.join(GAMEPLAY, 'simulation.zip')

COMBINED_TUNING = 0x62E94D38

LOAD_CONST, STORE_NAME, LOAD_NAME = 100, 90, 101
CALL_FUNCTION, CALL_FUNCTION_KW, EXTENDED_ARG = 131, 141, 144


def ops(co):
    """Yield (op, arg) from 3.7 wordcode, folding EXTENDED_ARG."""
    ext = 0
    code = co.code
    for i in range(0, len(code), 2):
        op, arg = code[i], code[i + 1] | ext
        ext = (arg << 8) if op == EXTENDED_ARG else 0
        if op != EXTENDED_ARG:
            yield op, arg


def extract(co):
    """(binary_types, tuning_types) from the Types class body."""
    binary, tuning, stack = {}, {}, []
    for op, arg in ops(co):
        if op == LOAD_CONST:
            stack.append(co.consts[arg])
        elif op == LOAD_NAME:
            stack.append(('<name>', co.names[arg]))
        elif op == STORE_NAME:
            name = co.names[arg]
            if stack:
                v = stack.pop()
                if isinstance(v, int) and not isinstance(v, bool):
                    binary[name] = v
                elif isinstance(v, dict):
                    tuning[name] = v
            stack.clear()
        elif op in (CALL_FUNCTION, CALL_FUNCTION_KW):
            # _add_inst_tuning(<positional...>, **kw). In KW form the final
            # const is the tuple of keyword names; positionals come first.
            kwnames = stack.pop() if op == CALL_FUNCTION_KW else ()
            args = stack[-arg:] if arg else []
            del stack[len(stack) - arg:]
            if stack and stack[-1] == ('<name>', '_add_inst_tuning'):
                stack.pop()
            npos = len(args) - len(kwnames)
            d = {'name': args[0] if args else None}
            for k, v in zip(kwnames, args[npos:]):
                d[k] = v
            stack.append(d)
    return binary, tuning


def load():
    """(binary_types, tuning_types) as {NAME: id} / {NAME: {...}}."""
    z = zipfile.ZipFile(CORE)
    mod = pyc37.load_pyc(z.read('sims4/resources.pyc'))
    for c in mod.consts:
        if isinstance(c, pyc37.Code) and c.name == 'Types':
            return extract(c)
    raise SystemExit('Types class body not found')


def type_names():
    """{resource_type_id: 'NAME'} over both tables."""
    binary, tuning = load()
    out = {v: k for k, v in binary.items()}
    for name, d in tuning.items():
        rt = d.get('resource_type')
        if rt:
            out[rt] = name
    return out


if __name__ == '__main__':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
    binary, tuning = load()
    print('# binary / non-tuning resource types: %d' % len(binary))
    for n, v in sorted(binary.items(), key=lambda kv: kv[1]):
        print('  0x%08X  %s' % (v, n))
    print()
    print('# instance-tuning types: %d' % len(tuning))
    for n, d in sorted(tuning.items(),
                       key=lambda kv: kv[1].get('resource_type') or 0):
        rt = d.get('resource_type')
        print('  0x%08X  %-28s %-26s %s' % (
            rt or 0, n, d.get('name'), d.get('manager_type') or
            d.get('manager_name') or ''))
