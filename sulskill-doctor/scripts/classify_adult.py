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


KEEP_ALWAYS = re.compile(r'Easel_Art_Catalog', re.I)

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
    r'opend|^KIMONO|^tangtop|^office',   # 'open/closed' CAS cluster - open variants are revealing
    r'sensual|Extra_Picture_Frames',   # Sensual Studio + its art-display frames
    r'popdress',
    r'yrsa',
    # Known adult mods no keyword can reach: innocuous names, no telling text
    # inside. Three rules when adding here:
    #   - match the mod, not the author. Prolific creators ship both (Ara_ is
    #     Ara_ExchangeActor, a WickedWhims add-on, and Ara_HighSchool, the
    #     script half of More Class Mates).
    #   - tolerate separators. The same mod is walked as a folder
    #     ("Fantasy Shorts by Raxys-247-...") and as a filename
    #     ("[Raxys]FantasyShorts.package").
    #   - anchor single common words, or a real food or decor mod gets swept up.
    r'Raxys|Fantasy\W*Shorts',
    r'Cerium Bath Sponge',
    r'ExchangeActor',
    r'Aurora\W*Cropped',
    r'By[+_ ]Beto',
    r'CK[+_ ]underware',
    r'GirlsBodyPillow',
    r'RiggedDica|CP_ymBottom',
    r'_WP_|wicked[ _]?perversions',
    r'khyan',
    r'PsBOSS|Lace[ _]Panties',
    r'gloryhole|glory[ _]hole|NNISM',
    r'^SKRIT\b',
    r'naughty',
    r'^(Lychee|Matcha|Tight)(\.package)?$|[\\/](Lychee|Matcha|Tight)\.package$',
    r'Vthena|Hanzo',
]), re.I)

# animation prop/object dependencies - useless without the anims
PROPS = re.compile(r'CC_for_animations|SupportPropsForAnimations|OBJ_Folder_for_Animations|'
                   r'Objects_required_for_some_animations', re.I)
# matches a keyword but is genuinely just clothing / a utility
NOT_ADULT = re.compile('|'.join([
    r'^New Skin Overlays',
    r"TwistedMexi's Searchable Pose Player", r'^Sports Fixes',
    r'^Men-|^Women-',
    r'TuningErrorNotifier',   # diagnostic tool, Nisa-compat patch only
    r'nakedfootfountain',    # sims4me: barefoot in the fountain, not nudity
]), re.I)
ADJACENT = re.compile(r'basemental[-_ ]?(drug|gang|gambl)|^\[?e404p|\bblunt\b|hookah', re.I)

adult, props, adjacent, clean = [], [], [], []
for m in mods:
    if KEEP_ALWAYS.search(m):
        clean.append(m); continue
    if NOT_ADULT.search(m):
        clean.append(m); continue
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
