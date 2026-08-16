#!/usr/bin/env python3
"""Turn curated command JSON into the reference document.

commands.py finds every console command a mod registers - well over a thousand
in a large library, most of them internal. Judging which ones a player would
actually use is not something a regex can do, so that pass is done by reading
them, and this merges the result into a document.

The document describes one machine's installed mods, so it is a local artifact,
never part of the repository - this skill ships the tools, not anyone's mod
list. --out is required for that reason.

    py commands.py --json raw.json
    ... curate raw.json into one or more files shaped like:
        {"mods": [{"mod": "...", "summary": "...",
                   "commands": [{"cmd","desc","cheat","args","uncertain"}]}]}
    py commands_doc.py curated*.json --out ~/Downloads/console-commands.md

Every command written out is checked against the raw extraction first. A
curated entry naming a command that no installed mod registers is dropped and
reported - the point of the document is that the commands in it are real.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

HEADER = """# Sims 4 mod console commands

Open the console with **Ctrl+Shift+C**, type, press Enter. Commands marked
**cheat** need `testingcheats true` active.

This is a curated list: the mods below register far more commands than this,
most of them internal. What is here is what a player would plausibly want.
Generated from the mods themselves - see `scripts/commands.py` to rebuild it
against your own library, which will differ from this one.

"""

FOOTER = """
## Rebuilding this for your own mods

```
py scripts/commands.py                 # everything, grouped by mod
py scripts/commands.py --json raw.json # machine-readable
py scripts/commands.py --mod kuttoe    # one mod
```

`commands.py` reads the compiled scripts directly, so it reports what is
actually installed rather than what a wiki says. Two passes: it disassembles
the decorator that registers each command, and falls back to scanning string
constants for mods whose bytecode is obfuscated - MCCC and WickedWhims both
need the fallback. Entries found only by the fallback are marked *unverified*
below: the name is real, but nothing proved it is a registered command.
"""


def load_raw():
    """-> {command: mod} for everything actually installed."""
    import commands as C
    out = {}
    for mod, cmds in C.scan_all().items():
        for c, info in cmds.items():
            out[c] = (mod, info.get('via'))
    return out


def adult_pattern():
    """The curated NSFW pattern set, imported rather than retyped.

    The main document is meant to be shareable, and a page of explicit command
    names is not. Splitting by mod keeps the shareable file shareable without
    losing anything: the adult half is written separately and gitignored.
    """
    import re as _re
    src = os.path.join(HERE, 'classify_adult.py')
    ns = {}
    try:
        text = open(src, encoding='utf-8').read()
        block = _re.search(r'^CERTAIN = re\.compile\(.*?^\]\), re\.I\)',
                           text, _re.S | _re.M)
        if block:
            exec('import re\n' + block.group(), ns)
            return ns['CERTAIN']
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('curated', nargs='+', help='curated JSON file(s) or globs')
    # No default. The output is a list of THIS machine's mods, which is
    # exactly the kind of thing that must not land in the repository - so the
    # caller has to say where it goes, somewhere outside it.
    ap.add_argument('--out', required=True,
                    help='where to write the document (outside the repo)')
    ap.add_argument('--no-verify', action='store_true',
                    help='skip checking each command against the live scan')
    ap.add_argument('--adult-out', help='write adult mods here instead of --out')
    a = ap.parse_args()

    paths = []
    for pat in a.curated:
        paths.extend(sorted(glob.glob(pat)) or [pat])

    mods = {}
    for p in paths:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        for entry in data.get('mods', []):
            m = entry['mod']
            slot = mods.setdefault(m, {'summary': '', 'commands': {}})
            if entry.get('summary') and not slot['summary']:
                slot['summary'] = entry['summary']
            for c in entry.get('commands', []):
                slot['commands'][c['cmd']] = c

    raw = {} if a.no_verify else load_raw()
    dropped = []
    if raw:
        for m, slot in mods.items():
            for cmd in list(slot['commands']):
                if cmd not in raw:
                    dropped.append((m, cmd))
                    del slot['commands'][cmd]

    mods = {m: s for m, s in mods.items() if s['commands']}

    adult = {}
    if a.adult_out:
        pat = adult_pattern()
        if pat is None:
            sys.exit('classify_adult.py CERTAIN pattern could not be loaded; '
                     'refusing to guess which mods are adult')
        for m in list(mods):
            if pat.search(m):
                adult[m] = mods.pop(m)

    _write(a.out, mods, raw)
    if a.adult_out:
        _write(a.adult_out, adult, raw)

    if dropped:
        print(f'\ndropped {len(dropped)} curated entr(ies) not found in the '
              f'live scan:')
        for m, c in dropped[:25]:
            print(f'    {m}: {c}')
    return


def _write(out, mods, raw):
    total = sum(len(s['commands']) for s in mods.values())
    lines = [HEADER]
    for m in sorted(mods, key=lambda x: x.lower()):
        slot = mods[m]
        lines.append(f'## {m}')
        if slot['summary']:
            lines.append('')
            lines.append(f'*{slot["summary"]}*')
        lines.append('')
        lines.append('| command | does | needs |')
        lines.append('| --- | --- | --- |')
        for cmd in sorted(slot['commands']):
            c = slot['commands'][cmd]
            call = f'`{cmd}`' + (f' `{c["args"]}`' if c.get('args') else '')
            note = []
            if c.get('cheat'):
                note.append('cheats')
            if c.get('uncertain'):
                note.append('*uncertain*')
            if raw.get(cmd, ('', ''))[1] == 'strings':
                note.append('*unverified*')
            desc = c['desc'].replace('|', '\\|')
            lines.append(f'| {call} | {desc} | {", ".join(note)} |')
        lines.append('')
    lines.append(FOOTER)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))
    print(f'wrote {out}: {total} command(s) across {len(mods)} mod(s)')


if __name__ == '__main__':
    main()
