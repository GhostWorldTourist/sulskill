#!/usr/bin/env python3
"""Parse a Scarlet's Mod List CSV export and cross-reference it with what is
actually installed.

Scarlet maintains a community list of Sims 4 mods and their patch status. Her
site exports a "Your Mods" CSV of whatever you have ticked:

    Selected, ID, Mod Name, Creator

Note what that export does NOT contain: any broken/updated status. It is your
SELECTION, not a health verdict - the status lives on her site. So the value here
is the join, not the file: which tracked mods are missing from disk, and which
installed mods nobody is tracking.

The CSV is the user's own copy of someone else's work. This script takes a path
and never vendors the data - nothing from it belongs in this repo.

Matching mod names to filenames is fuzzy by nature. Names are prose ("Add vanity
function to all desks!") and filenames are not, so this normalises both to
alphanumeric-only and looks for containment in either direction, plus a creator
hint. Expect false negatives on heavily abbreviated filenames; that is why
unmatched entries are reported rather than silently dropped.
"""
import argparse
import collections
import csv
import os
import re
import sys

SIMS = os.environ.get('SIMS4_DIR') or os.path.join(
    os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')

STOP = {'the', 'a', 'an', 'and', 'of', 'for', 'to', 'all', 'in', 'on', 'with',
        'mod', 'set', 'by', 'your', 'more', 'new'}


def norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())


def tokens(s):
    """Words in a name, splitting CamelCase as well as punctuation.

    Filenames are CamelCase far more often than spaced, so without the case
    split "CelebQuirkToggle" is one opaque token and matches nothing.
    """
    spaced = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', s)
    return [t for t in re.split(r'[^a-zA-Z0-9]+', spaced.lower())
            if len(t) > 2 and t not in STOP]


def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    if not rows:
        sys.exit('empty CSV')
    head = [h.strip().lower() for h in rows[0]]
    try:
        i_sel = head.index('selected')
        i_name = head.index('mod name')
        i_cre = head.index('creator')
    except ValueError:
        sys.exit(f'unexpected columns: {rows[0]}')
    i_id = head.index('id') if 'id' in head else None
    out = []
    for r in rows[1:]:
        if len(r) <= max(i_sel, i_name, i_cre):
            continue
        out.append({
            'selected': r[i_sel].strip().upper() == 'TRUE',
            'id': r[i_id].strip() if i_id is not None and len(r) > i_id else '',
            'name': r[i_name].strip(),
            'creator': r[i_cre].strip(),
        })
    return out


def installed_files():
    mods = os.path.join(SIMS, 'Mods')
    out = []
    for dp, _, fn in os.walk(mods):
        for f in fn:
            if f.lower().endswith(('.package', '.ts4script')):
                out.append(f)
    return out


def tok_hit(tok, ftoks, nf):
    """Does this word appear in a filename, allowing for abbreviation?

    Creators abbreviate aggressively - "Celebrity Quirks Toggle" ships as
    Tmex-CelebQuirkToggle. Plain substring matching misses every one of those, so
    a token also counts when it shares a prefix with a filename token. Four
    characters is the shortest prefix that does not start matching everything.
    """
    if tok in nf:
        return True
    for ft in ftoks:
        if len(tok) >= 4 and len(ft) >= 4 and (ft.startswith(tok[:4])
                                               or tok.startswith(ft[:4])):
            if ft.startswith(tok) or tok.startswith(ft):
                return True
    return False


def match(entry, files, norm_files, file_tokens):
    """Best scoring file on disk for this entry, or None.

    Scored rather than first-hit: with 2,477 files a greedy match lands on the
    wrong one often enough to matter.
    """
    n = norm(entry['name'])
    if len(n) >= 8:
        for f, nf in zip(files, norm_files):
            if n in nf or (len(nf) >= 8 and nf in n):
                return f, 'exact'

    toks = tokens(entry['name'])
    ctoks = tokens(entry['creator'])
    if not toks:
        return None, None

    best, best_score = None, 0.0
    for f, nf, ftoks in zip(files, norm_files, file_tokens):
        hits = sum(1 for t in toks if tok_hit(t, ftoks, nf))
        if not hits:
            continue
        score = hits / len(toks)
        if any(tok_hit(c, ftoks, nf) for c in ctoks):
            score += 0.25                      # same creator corroborates
        if score > best_score:
            best, best_score = f, score
    # Require most of the name to land; below that it is coincidence.
    if best_score >= 0.75:
        return best, f'{best_score:.2f}'
    return None, None


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('csv', help="path to Scarlet's Mod List CSV export")
    p.add_argument('--missing', action='store_true',
                   help='only tracked mods with nothing matching on disk')
    p.add_argument('--creators', action='store_true', help='summarise by creator')
    p.add_argument('--unselected', action='store_true', help='include Selected=FALSE rows')
    a = p.parse_args()

    entries = read_csv(a.csv)
    if not a.unselected:
        entries = [e for e in entries if e['selected']]
    files = installed_files()
    norm_files = [norm(f) for f in files]
    file_tokens = [tokens(f) for f in files]

    print(f"{len(entries)} tracked mod(s); {len(files)} file(s) installed\n")

    if a.creators:
        c = collections.Counter(e['creator'] for e in entries)
        for k, v in c.most_common():
            print(f"  {v:>4}  {k}")
        print(f"\n  {len(c)} creator(s)")
        return

    found, missing = [], []
    for e in entries:
        hit, how = match(e, files, norm_files, file_tokens)
        (found if hit else missing).append((e, hit))

    if not a.missing:
        print(f"matched on disk : {len(found)}")
    print(f"no match on disk: {len(missing)}\n")
    for e, _ in missing:
        who = f" [{e['creator']}]" if e['creator'] else ''
        print(f"  {e['name']}{who}")
    if not a.missing and found:
        print(f"\n(matched examples: "
              + ", ".join(e['name'] for e, _ in found[:3]) + " ...)")


if __name__ == '__main__':
    main()
