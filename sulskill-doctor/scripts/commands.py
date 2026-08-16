#!/usr/bin/env python3
"""Extract the cheat-console commands every installed script mod registers.

Sims 4 script mods add console commands by decorating a function:

    @sims4.commands.Command('mccc.settings', command_type=...)
    def _mccc_settings(...):

The command name is a constant loaded immediately before the decorator call, so
this disassembles each compiled module rather than guessing from strings. A
plain string scan cannot tell 'mccc.settings' from 'services.get_zone' - both
are dotted lowercase - and gets the answer wrong in both directions.

What it recovers per command: the name, the mod that registers it, the handler's
parameter list (which is what the arguments actually are), and the command type
Live/Cheat/DebugOnly/Automation, since DebugOnly commands are invisible to a
normal player and Cheat ones need testingcheats.

    py commands.py                     # every command, grouped by mod
    py commands.py --json out.json     # machine-readable, for building a doc
    py commands.py --mod mccc          # one mod
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import collections
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'sulskill-modbuild', 'scripts'))

STAGING = os.environ.get('VORTEX_TS4_MODS') or os.path.join(
    os.environ.get('APPDATA', os.path.expanduser('~')), 'Vortex', 'thesims4', 'mods')
SIMS = os.environ.get('SIMS4_DIR') or os.path.join(
    os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')

# A command name is dotted or bare lowercase, never a path or a format string.
NAME = re.compile(r'^[a-z][a-z0-9_]{1,20}(\.[a-z0-9_]{2,30})+$')
# Anything with a file extension is a path, not a command.
NOT_A_COMMAND = re.compile(
    r'\.(exe|dll|py|pyc|txt|log|cfg|json|xml|package|ts4script|zip|dat)$', re.I)

# sims4.commands.CommandType members, in declaration order.
CMD_TYPE = {0: 'DebugOnly', 1: 'Automation', 2: 'Cheat', 3: 'Live'}

# Opcodes needed to spot the decorator call. Python 3.7 numbering - the host
# interpreter's dis module is wrong here, 3.11 renumbered everything.
LOAD_CONST, LOAD_NAME, LOAD_ATTR, LOAD_GLOBAL = 100, 101, 106, 116
LOAD_METHOD, CALL_FUNCTION, CALL_FUNCTION_KW, CALL_METHOD = 160, 131, 141, 161
HAS_ARG = 90


def _ops(code):
    """Yield (offset, opcode, arg) with EXTENDED_ARG folded in."""
    ext = 0
    i = 0
    while i < len(code):
        op = code[i]
        if op >= HAS_ARG:
            arg = code[i + 1] | ext
            ext = 0
            if op == 144:                       # EXTENDED_ARG
                ext = arg << 8
                i += 2
                continue
            yield i, op, arg
            i += 2
        else:
            yield i, op, None
            i += 2


def commands_in(co, Code):
    """-> [(name, command_type_or_None)] registered in this code object."""
    out = []
    ops = list(_ops(co.code))
    for idx, (_off, op, arg) in enumerate(ops):
        # The decorator is an attribute access named Command, either as
        # sims4.commands.Command or a from-import.
        is_cmd = ((op in (LOAD_ATTR, LOAD_METHOD) and arg < len(co.names)
                   and co.names[arg] == 'Command')
                  or (op in (LOAD_NAME, LOAD_GLOBAL) and arg < len(co.names)
                      and co.names[arg] == 'Command'))
        if not is_cmd:
            continue
        # The command name is the first constant loaded after it.
        name = ctype = None
        for _o2, op2, arg2 in ops[idx + 1:idx + 14]:
            if op2 == LOAD_CONST and arg2 < len(co.consts):
                c = co.consts[arg2]
                if name is None and isinstance(c, str) and NAME.match(c) \
                        and not NOT_A_COMMAND.match(c):
                    name = c
                elif isinstance(c, int) and c in CMD_TYPE and ctype is None:
                    ctype = CMD_TYPE[c]
            elif op2 in (LOAD_ATTR, LOAD_NAME, LOAD_GLOBAL) and arg2 < len(co.names):
                n = co.names[arg2]
                if n in CMD_TYPE.values():
                    ctype = n
            elif op2 in (CALL_FUNCTION, CALL_FUNCTION_KW, CALL_METHOD):
                break
        if name:
            out.append((name, ctype))
    return out


def handler_args(co, Code, name):
    """Best-effort parameter list for the function the decorator wraps."""
    for c in co.consts or ():
        if isinstance(c, Code) and c.name not in ('<module>',):
            sig = c.signature()
            # Command handlers always end with the connection kwarg.
            if '_connection' in sig or 'connection' in sig:
                return sig
    return ''


# Roots of game and stdlib modules. A dotted constant starting with one of
# these is an import path, not a command.
MODULE_ROOT = {
    'sims4', 'sims', 'services', 'objects', 'interactions', 'event_testing',
    'ui', 'distributor', 'protocolbuffers', 'singletons', 'alarms', 'clock',
    'date_and_time', 'traits', 'buffs', 'statistics', 'situations', 'careers',
    'routing', 'placement', 'autonomy', 'zone', 'world', 'server', 'client',
    'os', 'sys', 're', 'json', 'math', 'random', 'time', 'collections',
    'itertools', 'functools', 'enum', 'typing', 'logging', 'traceback',
    'io', 'struct', 'zlib', 'weakref', 'copy', 'operator', 'builtins',
    'self', 'cls', 'super', 'utf', 'http', 'https', 'www',
}
# A command reads as <namespace>.<verb>, at least one dot, no path separators.
DOTTED = re.compile(r'^[a-z][a-z0-9_]{1,20}(\.[a-z0-9_]{2,30})+$')


def constants_scan(module, Code):
    """Command-shaped string constants, for mods whose bytecode is obfuscated.

    MCCC is the case that forces this: its modules are minified to the point
    that the decorator call does not disassemble, but the command names are
    still ordinary string constants. Reading them from co_consts rather than
    raw bytes matters - a byte scan picks up the next value's marshal type tag
    and yields 'mc.show_sim_menuc'.

    Lower confidence than the disassembly pass by definition: this knows the
    string looks like a command, not that anything registers it.
    """
    import pyc37
    out = set()
    for co, _depth in pyc37.walk(module):
        for c in co.consts or ():
            if (isinstance(c, str) and DOTTED.match(c)
                    and not NOT_A_COMMAND.search(c)
                    and c.split('.')[0] not in MODULE_ROOT):
                out.add(c)
    return out


def scan_script(path):
    """-> {command: {'type':..., 'args':..., 'module':...}} for one .ts4script."""
    import pyc37
    found = {}
    try:
        with zipfile.ZipFile(path) as z:
            pycs = [i for i in z.infolist() if i.filename.endswith('.pyc')]
            registers = any(b'sims4.commands' in z.read(i) for i in pycs)
            if not registers:
                return found
            for info in pycs:
                blob = z.read(info)
                if b'Command' not in blob and b'.' not in blob:
                    continue
                try:
                    module = pyc37.load_pyc(blob)
                except Exception:
                    continue
                for co, _depth in pyc37.walk(module):
                    for nm, ct in commands_in(co, pyc37.Code):
                        prev = found.get(nm, {})
                        found[nm] = {
                            'type': ct or prev.get('type'),
                            'args': prev.get('args') or handler_args(
                                co, pyc37.Code, nm),
                            'module': info.filename,
                            'via': 'disasm',
                        }
                for nm in constants_scan(module, pyc37.Code):
                        found.setdefault(nm, {'type': None, 'args': '',
                                              'module': info.filename,
                                              'via': 'strings'})
    except Exception:
        pass
    return found


def scan_all(roots=None):
    """-> {mod_name: {command: info}} across every installed script mod."""
    roots = roots or [r for r in (STAGING, os.path.join(SIMS, 'Mods'))
                      if os.path.isdir(r)]
    seen_files = set()
    out = {}
    for root in roots:
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if not fn.lower().endswith('.ts4script'):
                    continue
                if fn in seen_files:          # same mod staged and deployed
                    continue
                seen_files.add(fn)
                cmds = scan_script(os.path.join(dirpath, fn))
                if cmds:
                    out[os.path.splitext(fn)[0]] = cmds
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json', metavar='OUT', help='write the raw result as JSON')
    ap.add_argument('--mod', help='only mods whose filename contains this')
    ap.add_argument('--type', help='only this command type (Live/Cheat/DebugOnly)')
    a = ap.parse_args()

    data = scan_all()
    if a.mod:
        data = {k: v for k, v in data.items() if a.mod.lower() in k.lower()}
    if a.type:
        data = {k: {c: i for c, i in v.items()
                    if (i['type'] or '').lower() == a.type.lower()}
                for k, v in data.items()}
        data = {k: v for k, v in data.items() if v}

    total = sum(len(v) for v in data.values())
    print(f'{total} command(s) in {len(data)} mod(s)\n')
    for mod in sorted(data, key=lambda m: -len(data[m])):
        print(f'=== {mod}  ({len(data[mod])})')
        for cmd in sorted(data[mod]):
            info = data[mod][cmd]
            t = f"[{info['type']}]" if info['type'] else ''
            print(f'    {cmd:<44} {t:<12} {info["args"][:60]}')
        print()

    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1, sort_keys=True)
        print(f'wrote {a.json}')

    kinds = collections.Counter(
        i['type'] or 'unknown' for v in data.values() for i in v.values())
    print('by type:', dict(kinds))


if __name__ == '__main__':
    main()
