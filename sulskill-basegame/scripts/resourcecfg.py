"""Parser for EA's ResourceConfig .cfg format - the file that defines load order.

The engine calls this EACore/ResourceConfig (the string is in TS4_x64.exe next
to the directive names). A .cfg is a flat list of directives:

    Priority <int>      sets the priority applied to everything that follows
    PackedFile <glob>   mount matching .package files at the current priority
    DirectoryFiles <d>  mount loose files under <d> at the current priority
    FileType <id> <ext> map an extension to a numeric resource type
    Select <NAME> ...   conditional block, closed by End
    Group / Scan / StopScan     (present in the engine, unused in shipped cfgs)
    #                   comment

Directive names come from the engine's own string table:
    'StopScan', 'Group', 'FileType', 'Scan', 'DirectoryFiles', 'autoupdate',
    'PackedFile'  -- adjacent to 'EACore/ResourceConfig/ConfigFileBuffer'

Higher priority number wins; see notes/track-e.md for the evidence.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import fnmatch
import os
import re

DIRECTIVE = re.compile(r'^\s*(\S+)\s*(.*?)\s*$')


def parse(path):
    """[(priority, directive, argument, select_context)] in file order."""
    out = []
    prio = 0
    select = None
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for raw in f:
            line = raw.split('#', 1)[0].strip()
            if not line:
                continue
            m = DIRECTIVE.match(line)
            if not m:
                continue
            key, arg = m.group(1), m.group(2)
            low = key.lower()
            if low == 'priority':
                try:
                    prio = int(arg)
                except ValueError:
                    pass
            elif low == 'select':
                select = arg
            elif low == 'end':
                select = None
            else:
                out.append((prio, key, arg, select))
    return out


def mounts(cfg_path, listing=None):
    """[(priority, filename)] for the .package files this cfg mounts.

    listing: filenames in the cfg's directory; read from disk if omitted.
    Globs are matched case-insensitively, as Windows would.
    """
    d = os.path.dirname(cfg_path)
    if listing is None:
        listing = [n for n in os.listdir(d)
                   if os.path.isfile(os.path.join(d, n))]
    out = []
    for prio, key, arg, select in parse(cfg_path):
        if key.lower() != 'packedfile':
            continue
        pat = arg.lower()
        for n in listing:
            if fnmatch.fnmatch(n.lower(), pat):
                out.append((prio, n, select))
    return out


def order(cfg_path, listing=None):
    """Filenames highest-priority-first, i.e. winner first."""
    seen, out = set(), []
    for prio, n, select in sorted(mounts(cfg_path, listing),
                                  key=lambda r: -r[0]):
        if n in seen:
            continue
        seen.add(n)
        out.append((prio, n, select))
    return out
