"""Definitive adult classification. When uncertain -> exclude, and say so."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import os, re, json

HERE = os.path.dirname(os.path.abspath(__file__))

# One mod is a staging folder under a manager, or a loose file/folder in Mods
# without one. Reading a manager's staging folder directly used to be the only
# path here, which crashed outright for anyone who installs by hand.
UNITS = dict(gate.mod_units())
mods = sorted(UNITS)


def size_of(f):
    p = UNITS[f]
    if os.path.isfile(p):
        return os.path.getsize(p)
    t = 0
    for dp, _, fns in os.walk(p):
        for fn in fns:
            try:
                t += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return t


CERTAIN = re.compile('|'.join([
    r'^(CE_|CRL_|CRL&|RAW_|SNOB_|GAY_|GAY&|SMASH!|PC_|MTB_|BRZ_)',
    r'^(WW_|ww_)', r'_WW_|WW$|WWAnim|StripClub',
    r'wicked|turbodriver|nisa|perversion',
    r'cinerotique|sensual_studio|\bpeco',
    r'cumshine|spent_|cum[ _-]?(shine|mesh|layer|queen|glass|kiss)|\bcum\b',
    r'azmodan|strapon|futanari|penis|bulge|sp44',
    r'female_body_details|wild_guy|dimplesofvenus',
    r'noir[_ ]and[_ ]dark|bdsm|shackle|handcuff|manacle|smotherbox|madhox|r-lo|dildo|pets_and_slaves',
    r'ts4nude|nudemodel|nudeyoga|mortalib|pornstar|sexworker|onlysims|simturbate',
    r'khlas|\bnude\b|naked|lewd|erotic|\bporn|sextape|condom',
    r'nipple|piercing.*eve|eve\d*skin|SMSims[-_]eve|SMSims[-_]EVE',
    r'fouyaya|oovo|myobi|jv[_ ]|alonely|lupobianco|soleil_anim|elite_anim|machinima_anim',
    r'^DD_|oll_animations|quinsims|yummy-o-tummy|tibo131|itsalazsha|azeu',
    r'_UNZIP_ME!!!__Bazar',
    r'booty',
    r'sensual|Extra_Picture_Frames',   # Sensual Studio + its art-display frames
    r'yrsa',
    r'_WP_|wicked[ _]?perversions',
    r'gloryhole|glory[ _]hole',
    r'naughty',
    r'necrodog',   # HD feet/body detail replacements - common enough to earn a line
]), re.I)

# Deliberately absent: patterns that name one specific CC item rather than a
# creator, a framework, or the vocabulary. They cannot work anywhere but the
# library they were written against, and a list of them is a mod list, which
# POLICY.md says does not belong in this repository.
#
# Adult mods with innocuous names and no telling text inside are real, and no
# keyword will reach them. That is a limitation of this approach, not something
# to paper over by hard-coding your own. Add yours to LOCAL below.
#
# LOCAL: one regex per line, no header, gitignored. Same rules as above -
# match the mod or the creator, not a word that ordinary CC also uses; tolerate
# separators, since the same mod is walked as a folder and as a filename; and
# anchor single common words or a food or decor mod gets swept up.
_local = os.path.join(os.path.dirname(HERE), 'adult_patterns.local')
if os.path.exists(_local):
    with open(_local, encoding='utf-8') as f:
        _extra = [ln.strip() for ln in f if ln.strip() and not ln.startswith('#')]
    if _extra:
        CERTAIN = re.compile(CERTAIN.pattern + '|' + '|'.join(_extra), re.I)

# animation prop/object dependencies - useless without the anims
PROPS = re.compile(r'CC_for_animations|SupportPropsForAnimations|OBJ_Folder_for_Animations|'
                   r'Objects_required_for_some_animations', re.I)
# There is deliberately no list of exceptions here either. A named mod that
# matches a keyword without being adult is the same mod list as the one above,
# just on the other side of the decision, and it fails the same way: it only
# ever describes the library it was written against.
#
# The cost is a false positive now and then - a barefoot mod caught by 'naked',
# say. That is the trade this script's first line already chose: when uncertain,
# exclude, and say so. An over-excluded mod is named in the plan where a person
# reads it. An under-excluded one is the failure that gets noticed in front of
# somebody else.
ADJACENT = re.compile(r'basemental[-_ ]?(drug|gang|gambl)|^\[?e404p|\bblunt\b|hookah', re.I)

adult, props, adjacent, clean = [], [], [], []
for m in mods:
    if PROPS.search(m):
        props.append(m); continue
    if ADJACENT.search(m) and not CERTAIN.search(m):
        adjacent.append(m); continue
    if CERTAIN.search(m):
        adult.append(m); continue
    clean.append(m)

sizes = {m: size_of(m) for m in adult + props}
out = {'adult': sorted(adult), 'animation_props': sorted(props),
       'adjacent_not_sex': sorted(adjacent), 'keep': sorted(clean),
       'adult_bytes': sum(sizes[m] for m in adult),
       'prop_bytes': sum(sizes[m] for m in props)}
json.dump(out, open(os.path.join(gate.out_dir(), 'adult_inventory.json'), 'w',
                    encoding='utf-8'), indent=1)

print(f"total mods       : {len(mods)}")
print(f"  EXCLUDE (adult)  : {len(adult)}  ({out['adult_bytes']/1073741824:.2f} GB)")
print(f"  EXCLUDE (props)  : {len(props)}  ({out['prop_bytes']/1048576:.0f} MB)")
print(f"  drugs (your call): {len(adjacent)}")
print(f"  KEEP             : {len(clean)}")
print()
print("=== KEEP list, anything that still looks questionable ===")
sus = re.compile(r'sex|nud|naked|body|skin|underwear|thong|panti|booty|foot|feet|piercing', re.I)
for m in sorted(clean):
    if sus.search(m):
        print(f"   {m}")
