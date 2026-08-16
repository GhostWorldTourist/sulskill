#!/usr/bin/env python3
"""Extract Basemental Drugs' trait ids and settings surface from its bytecode.

This skill is deliberately READ-ONLY. Basemental stores its settings as traits
stamped onto every human teen+ Sim in the save (see SKILL.md), so there is no
config file to edit, and a mod that equipped those traits would just be a second
configurator fighting the in-game menus. The job here is to understand what is
set and advise, not to set it.

Produces reference/basemental.json: trait name -> id, plus the settings menu tree.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import collections
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'sulskill-modbuild', 'scripts'))
from pyc37 import load_pyc, walk                                  # noqa: E402

SIMS = os.environ.get('SIMS4_DIR') or os.path.join(
    os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
# Searched recursively under Mods, so a manual install works as well as a
# manager's deployment (Vortex puts its files in a subfolder of Mods).
MODS = os.path.join(SIMS, 'Mods')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', 'reference', 'basemental.json')

SCRIPTS = ['basementaldrugs.ts4script', 'basementalgangs.ts4script',
           'basementalgambling.ts4script', 'basementalecohacks.ts4script']

LOAD_CONST, STORE_NAME, EXTENDED_ARG = 100, 90, 144


def class_constants(code):
    """name -> int, from a class body of straight `NAME = <literal>` assignments."""
    out, pending, ext = {}, None, 0
    for i in range(0, len(code.code), 2):
        op, arg = code.code[i], code.code[i + 1] | (ext << 8)
        ext = 0
        if op == EXTENDED_ARG:
            ext = arg
            continue
        if op == LOAD_CONST:
            pending = code.consts[arg]
        elif op == STORE_NAME:
            if isinstance(pending, int) and not isinstance(pending, bool):
                out[code.names[arg]] = pending
            pending = None
    return out


def main():
    traits, menus, enums = {}, {}, {}
    for script in SCRIPTS:
        path = gate.find_mod_file(script)
        if not path:
            continue
        if not os.path.exists(path):
            continue
        z = zipfile.ZipFile(path)
        for n in z.namelist():
            if not n.endswith('.pyc'):
                continue
            try:
                co = load_pyc(z.read(n))
            except Exception:
                continue
            for c, _ in walk(co):
                if c.name in ('BmdTraits', 'BmdBuffs', 'BmdRewards'):
                    got = class_constants(c)
                    if got:
                        traits.update(got)
                        enums.setdefault(c.name, sorted(got))
                if c.name.startswith('basemental_settings'):
                    names = [x for x in c.names if x.isascii()]
                    menus[c.name] = {
                        'script': script,
                        'module': n,
                        'controls': sorted({x for x in names
                                            if x.isupper() and len(x) > 3}),
                        'submenus': sorted({x for x in names
                                            if x.startswith('basemental_settings')
                                            and x != c.name}),
                    }

    groups = collections.defaultdict(list)
    for name in traits:
        if name.startswith('LEG_GAMBLING_'):
            groups['legalize_gambling'].append(name)
        elif name.startswith('LEG_'):
            groups['legalize_cannabis'].append(name)
        elif name.startswith('PARENTAL_'):
            groups['parental_reactions'].append(name)
        elif name.startswith('POLICE_'):
            groups['police'].append(name)
        elif 'ADDICTION' in name:
            groups['addiction'].append(name)
        elif (name.startswith('NPC_') or name == 'BASEMENTAL_NPCS'
                or 'DEALER' in name):
            # Dealer traits do NOT share the NPC_ prefix - COCAINE_DEALER,
            # SPEED_DEALER, BIGSHOT_DEALER and friends would be missed by a
            # prefix rule alone.
            groups['npcs'].append(name)
        elif name in ('MISDEMEANOR', 'FELONY', 'HARD_FELONY', 'PRISON_OG',
                      'ORGANIZED_CRIME', 'GET_OUT_OF_JAIL_FREECARD',
                      'LAW_FIRM_BEST', 'LAW_FIRM_MED', 'LAW_FIRM_BAD'):
            groups['criminal_record'].append(name)

    doc = {
        '_about': 'Basemental Drugs trait ids and settings surface. READ-ONLY '
                  'reference: settings live as traits on every Sim, not in a file.',
        'traits': traits,
        'trait_groups': {k: sorted(v) for k, v in groups.items()},
        'menus': menus,
        'counts': {'traits': len(traits), 'menus': len(menus)},
    }
    os.makedirs(os.path.dirname(os.path.normpath(OUT)), exist_ok=True)
    with open(os.path.normpath(OUT), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write('\n')
    print(f"wrote {os.path.normpath(OUT)}")
    print(f"  traits {len(traits)}   menus {len(menus)}")
    for k, v in sorted(groups.items()):
        print(f"  {k:<20} {len(v)}")


if __name__ == '__main__':
    main()
