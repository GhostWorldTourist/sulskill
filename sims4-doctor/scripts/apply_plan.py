"""Group the exclude-list by the Vortex search string that selects them."""
import json, os, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, 'adult_inventory.json'), encoding='utf-8'))
excl = d['adult'] + d['animation_props']

# Vortex mod-list search is a plain substring match on the mod name.
FILTERS = [
    ('WW_',            re.compile(r'^WW_|^ww_', re.I)),
    ('Mannequin',      re.compile(r'mannequin', re.I)),
    ('PECO',           re.compile(r'peco', re.I)),
    ('CE_',            re.compile(r'^CE_', re.I)),
    ('CRL',            re.compile(r'^CRL', re.I)),
    ('RAW_',           re.compile(r'^RAW_', re.I)),
    ('GAY',            re.compile(r'^GAY', re.I)),
    ('SNOB_',          re.compile(r'^SNOB_', re.I)),
    ('SMASH!',         re.compile(r'^SMASH!', re.I)),
    ('PC_',            re.compile(r'^PC_', re.I)),
    ('Wicked',         re.compile(r'wicked', re.I)),
    ('Nisa',           re.compile(r'nisa', re.I)),
    ('Cum',            re.compile(r'cum', re.I)),
    ('Azmodan',        re.compile(r'azmodan', re.I)),
    ('Noir',           re.compile(r'noir', re.I)),
    ('khlas',          re.compile(r'khlas', re.I)),
    ('SMSims',         re.compile(r'SMSims', re.I)),
    ('OOVO',           re.compile(r'oovo', re.I)),
    ('fouyaya',        re.compile(r'fouyaya', re.I)),
    ('Booty',          re.compile(r'booty', re.I)),
    ('Sensual',        re.compile(r'sensual|Extra_Picture_Frames', re.I)),
    ('MYOBI',          re.compile(r'myobi', re.I)),
    ('R-Lo',           re.compile(r'r-lo|r_lo', re.I)),
    ('jv',             re.compile(r'jv[_ ]|^jv', re.I)),
    ('YrSa',           re.compile(r'yrsa', re.I)),
    ('Nude',           re.compile(r'nude', re.I)),
    ('KIMONO',         re.compile(r'kimono', re.I)),
    ('school',         re.compile(r'school', re.I)),
    ('office',         re.compile(r'^office', re.I)),
    ('tangtop',        re.compile(r'tangtop', re.I)),
    ('Animation',      re.compile(r'anim', re.I)),
]

remaining = list(excl)
groups, seen = [], set()
for label, rx in FILTERS:
    hit = [m for m in remaining if rx.search(m) and m not in seen]
    if not hit:
        continue
    seen.update(hit)
    groups.append((label, sorted(hit)))
leftovers = sorted(m for m in excl if m not in seen)

lines = []
lines.append("SFW PROFILE - MODS TO DISABLE")
lines.append("=" * 70)
lines.append(f"{len(excl)} mods to disable, {len(d['keep'])} to keep.")
lines.append("")
lines.append("Vortex's mod-list search box is a plain substring match, so each")
lines.append("block below = type the search term, Ctrl+A the filtered rows, disable.")
lines.append(f"{len(groups)} searches covers {len(excl) - len(leftovers)} of {len(excl)} mods.")
lines.append("")
for label, hit in groups:
    lines.append(f"--- search: {label!r}   ({len(hit)} mods) ---")
    for m in hit:
        lines.append(f"    {m}")
    lines.append("")
if leftovers:
    lines.append(f"--- no shared prefix, disable individually ({len(leftovers)}) ---")
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

out = os.path.join(HERE, 'SFW_PROFILE_PLAN.txt')
open(out, 'w', encoding='utf-8').write('\n'.join(lines))
print(f"wrote {out}  ({len(lines)} lines)")
print(f"\n{len(groups)} search terms cover {len(excl)-len(leftovers)}/{len(excl)} mods:")
for label, hit in groups:
    print(f"   {len(hit):>4}  search: {label}")
if leftovers:
    print(f"   {len(leftovers):>4}  individually:")
    for m in leftovers:
        print(f"          {m}")
