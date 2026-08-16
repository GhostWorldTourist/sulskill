"""Group the exclude-list by the Vortex search string that selects them."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import json, os, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(gate.out_dir(), 'adult_inventory.json'),
                   encoding='utf-8'))
excl = d['adult'] + d['animation_props']

# Vortex mod-list search is a plain substring match on the mod name, so the
# job here is to find the fewest substrings that cover the exclude list.
#
# Those substrings are derived from the inventory in front of us rather than
# listed in this file. A hard-coded list is one library's mod names wearing a
# config's clothing: it works on the machine it was written on, matches
# nothing anywhere else, and POLICY.md says a mod list does not belong in this
# repository.
MIN_LEN = 3    # shorter than this matches half the library
MIN_HITS = 2   # a term covering one mod is no cheaper than disabling that mod


def candidates(name):
    """Substrings a person could plausibly type: whole words, and prefixes.

    Prefixes matter because the useful handle is often cut short by a
    separator that a word split throws away - 'WW_' is a term, 'WW' is two
    characters that appear all over an unrelated library.
    """
    out = set()
    for tok in re.split(r'[^A-Za-z0-9]+', name):
        if len(tok) >= MIN_LEN:
            out.add(tok)
    for k in range(MIN_LEN, min(len(name), 12) + 1):
        out.add(name[:k])
    return out


# A term that also selects something on the keep list is worse than no term:
# it tells you to Ctrl+A a block containing a mod you meant to keep, and
# nothing in the plan would show you that it had. Drop those outright.
keep_lower = [k.lower() for k in d['keep']]
pool = collections.Counter()
for m in excl:
    for c in candidates(m):
        pool[c] += 1
safe = {c: n for c, n in pool.items()
        if n >= MIN_HITS and not any(c.lower() in k for k in keep_lower)}

# Greedy set cover: take the term catching the most still-uncovered mods,
# repeat. Ties break towards the longer term, which is the more specific one.
#
# Sorted, because candidates() builds from a set and two terms can tie on both
# coverage and length - unsorted, which one wins depends on string hashing, and
# the same library produces a different plan from one run to the next.
groups, seen = [], set()
while True:
    best, best_hit = None, []
    for c in sorted(safe):
        low = c.lower()
        hit = [m for m in excl if m not in seen and low in m.lower()]
        if len(hit) > len(best_hit) or (len(hit) == len(best_hit) and best
                                        and len(c) > len(best)):
            best, best_hit = c, hit
    if not best or len(best_hit) < MIN_HITS:
        break
    seen.update(best_hit)
    groups.append((best, sorted(best_hit)))
leftovers = sorted(m for m in excl if m not in seen)

lines = []
lines.append("SFW PROFILE - MODS TO DISABLE")
lines.append("=" * 70)
lines.append(f"{len(excl)} mods to disable, {len(d['keep'])} to keep.")
lines.append("")
lines.append("Vortex's mod-list search box is a plain substring match, so each")
lines.append("block below = type the search term, Ctrl+A the filtered rows, disable.")
lines.append(f"{len(groups)} searches covers {len(excl) - len(leftovers)} of {len(excl)} mods.")
lines.append("No term below matches anything on the keep list; that is checked,")
lines.append("not assumed. Terms are derived from these mod names each run.")
lines.append("")
for label, hit in groups:
    lines.append(f"--- search: {label!r}   ({len(hit)} mods) ---")
    for m in hit:
        lines.append(f"    {m}")
    lines.append("")
if leftovers:
    lines.append(f"--- no shared substring, disable individually ({len(leftovers)}) ---")
    for m in leftovers:
        lines.append(f"    {m}")
    lines.append("")
lines.append("=" * 70)
lines.append("DRUGS / SUBSTANCES - separate decision, not sex mods:")
for m in d['adjacent_not_sex']:
    lines.append(f"    {m}")
lines.append("")
lines.append("=" * 70)
lines.append(f"KEEP ({len(d['keep'])}):")
for m in d['keep']:
    lines.append(f"    {m}")

out = os.path.join(gate.out_dir(), 'SFW_PROFILE_PLAN.txt')
open(out, 'w', encoding='utf-8').write('\n'.join(lines))
print(f"wrote {out}  ({len(lines)} lines)")
print(f"\n{len(groups)} search terms cover {len(excl)-len(leftovers)}/{len(excl)} mods:")
for label, hit in groups:
    print(f"   {len(hit):>4}  search: {label}")
if leftovers:
    print(f"   {len(leftovers):>4}  individually:")
    for m in leftovers:
        print(f"          {m}")
