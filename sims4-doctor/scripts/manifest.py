#!/usr/bin/env python3
"""Describe every installed mod, from the mods themselves.

The best offline description of a mod is its own UI text. A mod that adds "Ask
to Cook Dinner" ships that string in a STBL; a trait mod ships the trait's name
and description. So this reads each package's string table and tuning class
names and synthesises a one-line summary. No network, no API key, no guessing
from filenames alone.

Accuracy expectations, stated plainly: this is a useful index, not a catalogue.
A CAS or build-mode package often has no descriptive text at all and gets
summarised from its resource mix instead ("42 CAS parts"). Script mods are
opaque without their tuning. Treat every line as a hint.

NSFW handling
-------------
--hide-nsfw omits adult mods entirely - they are not listed, not counted in the
body, only tallied so the numbers still add up. The classifier is the same
pattern set the SFW-profile work uses, which the user curated by hand; it errs
toward marking things adult, because a false positive costs a line in a report
and a false negative puts porn in a document they might share.
"""
import argparse
import collections
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'sims4-modbuild', 'scripts'))

SIMS = os.environ.get('SIMS4_DIR') or os.path.join(
    os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')

TYPES = {
    0x220557DA: 'STBL', 0xCB5FDDC7: 'Trait', 0x6017E896: 'Buff',
    0x0C772E27: 'Loot', 0xE882D22F: 'Interaction', 0x7DF2169C: 'Snippet',
    0x545AC67A: 'SimData', 0x034AEECB: 'CAS part', 0x00B2D882: 'Image',
    0x319E4F1D: 'Object catalog', 0xD382BF57: 'Object def',
    0x02D5DF13: 'Model', 0x01D0E75D: 'Model LOD', 0x3C1AF1F2: 'Thumbnail',
    0x62E94D38: 'Combined tuning', 0x02019972: 'Region',
}

# Curated by hand for the SFW-profile work. Kept deliberately broad.
NSFW = re.compile('|'.join([
    r'^(CE_|CRL_|RAW_|SNOB_|GAY_|SMASH!|PC_|MTB_|BRZ_|DD_)', r'^(WW_|ww_)',
    r'_WW_|WWAnim|StripClub', r'wicked|turbodriver|nisa|perversion',
    r'cinerotique|sensual_studio|peco', r'cumshine|cum(shine|mesh|_layer|queen)',
    r'azmodan|strapon|futanari|penis|bulge|sp44',
    r'female_body_details|wild_guy|dimplesofvenus',
    r'noir[_ ]and[_ ]dark|bdsm|shackle|handcuff|dildo|pets_and_slaves',
    r'ts4nude|nudemodel|nudeyoga|pornstar|sexworker|simturbate',
    r'khlas|\bnude\b|naked|lewd|erotic|\bporn|sextape|condom',
    r'nipple|eve\d*skin|fouyaya|oovo|myobi|jv[_ ]|alonely|lupobianco',
    r'oll_animations|quinsims|tibo131|itsalazsha|azeu|booty|sensual',
    r'yrsa|r-lo|popdress|opend|^KIMONO|^tangtop|^office|school',
]), re.I)

# Shared-framework boilerplate. Several mods embed the same settings blurbs
# (start-up notifications, debug toggles), and those score well on the
# sentence heuristic while saying nothing about the mod.
BOILERPLATE = re.compile(
    r'enable this setting|disable this setting|start-?up notification|'
    r'properly installed the mod|check for updates|report any issues|'
    r'this mod (is|was) (made|created)|thank you for (using|downloading)|'
    r'join (my|our) discord|patreon|debug (mode|cheats?)', re.I)

# Strings that are UI furniture rather than description
NOISE = re.compile(r'^(ok|cancel|yes|no|close|back|next|on|off|none|default|'
                   r'\d+|\W+)$', re.I)
CREATOR = re.compile(r'^([A-Za-z0-9]{2,20})[_\- ]')


def load_stbls(path):
    import stbl
    import refpack                                              # noqa: F401
    out = {}
    try:
        for blob in stbl.read_stbls(path):
            try:
                out.update(stbl.parse(blob))
            except Exception:
                pass
    except Exception:
        pass
    return out


def describe(path):
    """-> (summary, counts, sample_strings)"""
    import dbpf
    import refpack
    counts = collections.Counter()
    strings, names = [], []
    try:
        with open(path, 'rb') as f:
            head = f.read(96)
            if head[:4] != b'DBPF':
                return 'not a DBPF package', counts, []
    except OSError as e:
        return f'unreadable: {e}', counts, []

    try:
        for t, g, i, blob in dbpf.read(path):
            counts[TYPES.get(t, f'0x{t:08X}')] += 1
            if t == 0x220557DA:
                # Packages ship one STBL per locale, and the high byte of the
                # instance id IS the locale index - 0x00 is ENG_US. Without this
                # filter the "best" sentence is whichever language happened to
                # sort first, so descriptions come back in Italian or Polish.
                if (i >> 56) != 0:
                    continue
                try:
                    import stbl
                    for s in stbl.parse(blob).values():
                        if s and not NOISE.match(s.strip()):
                            strings.append(s.strip())
                except Exception:
                    pass
            elif blob[:5] == b'<?xml' and len(names) < 40:
                m = re.search(rb'<I c="([^"]+)"[^>]*n="([^"]+)"', blob)
                if m:
                    names.append((m.group(1).decode(), m.group(2).decode()))
    except Exception:
        pass

    # Prefer a real sentence; fall back to the longest label.
    sentences = [s for s in strings if 25 <= len(s) <= 220 and ' ' in s
                 and not s.startswith('{') and not BOILERPLATE.search(s)]
    sentences.sort(key=lambda s: (s.count(' '), len(s)), reverse=True)
    labels = sorted({s for s in strings if 3 <= len(s) <= 60},
                    key=len, reverse=True)

    if sentences:
        summary = sentences[0]
    elif labels:
        summary = 'adds: ' + ', '.join(labels[:4])
    elif names:
        kinds = collections.Counter(c for c, _ in names)
        summary = 'tuning: ' + ', '.join(f'{k} x{v}' for k, v in kinds.most_common(3))
    else:
        top = [f'{v} {k}' for k, v in counts.most_common(3)]
        summary = ', '.join(top) if top else 'no readable content'
    return summary, counts, labels[:6]


def creator_of(name):
    m = CREATOR.match(name)
    return m.group(1) if m else ''


KNOWN_PREFIX = re.compile(
    r'^(MTS_|RVSN_|Tmex-|\[Kuttoe\] ?|Andirz_|frankk_|LittleMsSam_|Zerbu[ _-]?|'
    r'sims4me_|TURBODRIVER_|NisaK_|PECO_|GhostWorldTourist_|SCUMBUMBO_)', re.I)
VERSION_TAIL = re.compile(r'([_\- ]?v?[\d.]+)?(_?(FIXED|UPDATED|Official|Patreon))?$', re.I)


def title_from_filename(name):
    """A readable title from a filename.

    Tuning-only mods ship no descriptive strings at all, but their filenames are
    often the clearest statement of intent in the whole package -
    'KeepBooksAfterPublishing' says more than '6 SuperInteraction'. Strip the
    creator prefix and version tail, then split CamelCase and underscores.
    """
    n = os.path.splitext(name)[0]
    n = KNOWN_PREFIX.sub('', n)
    n = re.sub(r'_(Updated|Fixed)By\w+', '', n, flags=re.I)
    n = VERSION_TAIL.sub('', n)
    n = re.sub(r'[_\-]+', ' ', n)
    n = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', default=os.path.join(SIMS, 'Mods'))
    ap.add_argument('--hide-nsfw', action='store_true',
                    help='omit adult mods entirely (still counted in the total)')
    ap.add_argument('--only', help='substring filter on filename')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--html', metavar='OUT', help='write an HTML report')
    ap.add_argument('--scripts', action='store_true',
                    help='include .ts4script files (described by module names)')
    a = ap.parse_args()

    files = []
    for dp, _, fn in os.walk(a.root):
        for f in sorted(fn):
            if f.lower().endswith('.package') or (
                    a.scripts and f.lower().endswith('.ts4script')):
                files.append(os.path.join(dp, f))
    if a.only:
        files = [f for f in files if a.only.lower() in os.path.basename(f).lower()]
    files.sort(key=lambda p: os.path.basename(p).lower())
    if a.limit:
        files = files[:a.limit]

    rows, hidden = [], 0
    for p in files:
        base = os.path.basename(p)
        rel = os.path.relpath(p, a.root)
        if NSFW.search(base) or NSFW.search(rel):
            hidden += 1
            if a.hide_nsfw:
                continue
        if p.lower().endswith('.ts4script'):
            import zipfile
            try:
                z = zipfile.ZipFile(p)
                mods = sorted({n.split('/')[0] for n in z.namelist()
                               if n.endswith('.pyc')})
                summary = 'script mod: ' + ', '.join(mods[:3])
            except Exception as e:
                summary = f'script mod (unreadable: {e})'
            counts, labels = collections.Counter(), []
        else:
            summary, counts, labels = describe(p)
        title = title_from_filename(base)
        # Prefer the mod's own prose. Fall back to the filename title, which for
        # tuning-only mods is usually the clearest statement of intent there is.
        weak = summary.startswith(('tuning:', 'adds:')) or re.match(
            r'^[\d, ]*(Interaction|Buff|Snippet|SimData|CAS part|Image|Model)',
            summary)
        if weak and title:
            summary = f'{title} - {summary}'
        elif not summary or summary == 'no readable content':
            summary = title or '(no description available)'
        rows.append({
            'file': base, 'dir': os.path.dirname(rel) or '.', 'title': title,
            'size': os.path.getsize(p), 'creator': creator_of(base),
            'summary': summary, 'counts': dict(counts.most_common(4)),
        })

    if a.html:
        write_html(a.html, rows, hidden, a.hide_nsfw)
        print(f'wrote {a.html}  ({len(rows)} mods'
              + (f', {hidden} adult omitted)' if a.hide_nsfw else ')'))
        return

    print(f'{len(rows)} mod(s)'
          + (f'   [{hidden} adult mods omitted]' if a.hide_nsfw else
             f'   [{hidden} flagged adult]') + '\n')
    for r in rows:
        who = f" ({r['creator']})" if r['creator'] else ''
        print(f"{r['file']}{who}  {r['size']:,}b")
        print(f"    {r['summary'][:160]}")


def write_html(out, rows, hidden, hide):
    doc = ["<h1>Sims 4 mod manifest</h1>",
           f"<p>{len(rows)} mods"
           + (f" &middot; {hidden} adult mods omitted" if hide
              else f" &middot; {hidden} flagged adult") + "</p>",
           "<table><tr><th>Mod<th>Creator<th>What it appears to do<th>Size</tr>"]
    for r in rows:
        doc.append(
            "<tr><td>{f}<td>{c}<td>{s}<td style='text-align:right'>{z:,}</tr>".format(
                f=html.escape(r['file']), c=html.escape(r['creator']),
                s=html.escape(r['summary'][:300]), z=r['size']))
    doc.append("</table>")
    style = ("<style>body{font:14px system-ui;margin:2rem;max-width:1200px}"
             "table{border-collapse:collapse;width:100%}"
             "td,th{border-bottom:1px solid #ddd;padding:6px;vertical-align:top;"
             "font-size:13px}th{text-align:left;background:#f4f4f4}"
             "tr:hover{background:#fafafa}</style>")
    with open(out, 'w', encoding='utf-8') as f:
        f.write(style + '\n'.join(doc))


if __name__ == '__main__':
    main()
