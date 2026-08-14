#!/usr/bin/env python3
"""Build a schema for Kuttoe's Sims 4 mods by reading their shipped bytecode.

Kuttoe's mods share one settings framework. Each mod that is configurable ships
a `<package>/settings.pyc` declaring its setting keys, and registers a console
command per setting under the `kuttoe.<mod>.` namespace:

    kuttoe.spellcaster_tweaks.toggle_copypasto_nerf     -> bool setting
    kuttoe.spellcaster_tweaks.set_tome_cooldown         -> numeric setting

State is persisted to `saves\\Kuttoe\\[Kuttoe] <Name>_Settings.cfg`, a flat JSON
object. So the command list and the config keys are two views of one thing, and
the command VERB is a reliable type signal - which matters because the config
file alone cannot distinguish an int from a float that currently holds a whole
number, and writing the wrong one is how these settings silently stop applying.

The framework also exposes validate_bool / validate_int / validate_float, so
types are enforced mod-side; matching them here just moves the error earlier.

Run after updating any Kuttoe mod; rewrites reference/kuttoe_schema.json.
"""
import glob
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pyc37 import load_pyc, walk                                # noqa: E402

import os as _os
# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
MODS = _os.path.join(SIMS, 'Mods', 'Vortex Mods')
CFGDIR = _os.path.join(SIMS, 'saves', 'Kuttoe')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', 'reference', 'kuttoe_schema.json')

CMD_RE = re.compile(r'^kuttoe\.([a-z0-9_]+)\.([a-z0-9_]+)$')


def script_strings(path):
    """Every string constant in a .ts4script, plus the top-level package name."""
    out, pkg = set(), None
    try:
        z = zipfile.ZipFile(path)
    except Exception:
        return out, pkg
    for entry in z.namelist():
        if not entry.endswith('.pyc'):
            continue
        if pkg is None and '/' in entry:
            pkg = entry.split('/')[0]
        try:
            mod = load_pyc(z.read(entry))
        except Exception:
            continue
        for co, _ in walk(mod):
            for k in (co.consts or ()):
                if isinstance(k, str) and 0 < len(k) < 80:
                    out.add(k)
    return out, pkg


def main():
    if not os.path.isdir(MODS):
        sys.exit(f"mods folder not found: {MODS}")

    # live config files, keyed by the mod name embedded in the filename
    live = {}
    for p in glob.glob(os.path.join(CFGDIR, '*_Settings.cfg')):
        name = os.path.basename(p)
        m = re.match(r'\[Kuttoe\] (.+)_Settings\.cfg$', name)
        if not m:
            continue
        try:
            live[m.group(1)] = (p, json.load(open(p, encoding='utf-8')))
        except Exception as e:
            live[m.group(1)] = (p, {'__error__': str(e)})

    def norm(s):
        return re.sub(r'[^a-z0-9]', '', s.lower())

    def match_cfg(label):
        """Config filenames don't always equal script names - the Career Overhaul
        Suite ships as CareerOverhaulSuite.ts4script but writes
        [Kuttoe] CareerOverhaul_Settings.cfg. Match on normalised prefix, longest
        first, so the pairing survives that kind of drift."""
        if label in live:
            return label
        n = norm(label)
        cands = [k for k in live if n.startswith(norm(k)) or norm(k).startswith(n)]
        return max(cands, key=lambda k: len(norm(k))) if cands else None

    mods, used = {}, set()
    for path in sorted(glob.glob(os.path.join(MODS, '[[]Kuttoe[]] *.ts4script'))):
        label = re.sub(r'^\[Kuttoe\] |\.ts4script$', '', os.path.basename(path))
        strings, pkg = script_strings(path)

        cmds = {}
        for s in strings:
            m = CMD_RE.match(s)
            if m:
                cmds.setdefault(m.group(1), []).append(s)
        cfg_key = match_cfg(label)
        if not cmds and cfg_key is None:
            continue                                  # nothing configurable here
        if cfg_key:
            used.add(cfg_key)

        cfg_path, cfg = live.get(cfg_key, (None, {}))
        keys = {}
        for ns, cl in cmds.items():
            for full in cl:
                verb = full.rsplit('.', 1)[1]
                for prefix, kind in (('toggle_', 'bool'), ('set_', 'number')):
                    if verb.startswith(prefix):
                        key = verb[len(prefix):]
                        rec = keys.setdefault(key, {})
                        rec['command'] = full
                        rec['type'] = kind
        # reconcile against the live file: it is the authority on which keys
        # actually exist, and on the concrete type of the stored value
        for k, v in (cfg or {}).items():
            if k.startswith('__'):
                continue
            rec = keys.setdefault(k, {})
            rec['current'] = v
            rec.setdefault('type', type(v).__name__)
            if rec.get('type') == 'number':
                rec['type'] = type(v).__name__
            if k not in strings:
                rec['note'] = 'in config but not found in bytecode strings'
        for k in list(keys):
            if 'current' not in keys[k] and cfg:
                keys[k]['note'] = 'command exists but key absent from config file'

        mods[label] = {
            'package': pkg,
            'script': os.path.basename(path),
            'config': cfg_path,
            'settings': keys,
            'commands': sorted(c for cl in cmds.values() for c in cl),
        }

    orphans = sorted(set(live) - used)
    doc = {
        'mods_dir': MODS,
        'config_dir': CFGDIR,
        'mods': mods,
        'config_without_script': orphans,
        'counts': {
            'configurable_mods': len(mods),
            'settings': sum(len(m['settings']) for m in mods.values()),
            'commands': sum(len(m['commands']) for m in mods.values()),
        },
    }
    os.makedirs(os.path.dirname(os.path.normpath(OUT)), exist_ok=True)
    with open(os.path.normpath(OUT), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write('\n')
    print(f"wrote {os.path.normpath(OUT)}")
    for k, v in doc['counts'].items():
        print(f"  {k:<20} {v}")
    print()
    for name, m in sorted(mods.items()):
        print(f"  {name:<28} {len(m['settings']):>4} settings  "
              f"{len(m['commands']):>4} commands  "
              f"{'cfg' if m['config'] else 'NO CFG'}")
    if orphans:
        print(f"\n  config files with no matching script: {orphans}")


if __name__ == '__main__':
    main()
