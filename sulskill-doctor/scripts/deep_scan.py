"""Comprehensive Sims 4 mod health scan. Emits report.json + a readable summary."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import gate  # noqa: F401,E402  refusal gate - see _shared/gate.py
import os, sys, json, zlib, struct, hashlib, zipfile, collections, datetime, re

import os as _os
# Resolved at runtime so the skill works on any machine and no account name
# is committed. Override with SIMS4_DIR if the game data lives elsewhere.
SIMS = _os.environ.get('SIMS4_DIR') or _os.path.join(
    _os.path.expanduser('~'), 'Documents', 'Electronic Arts', 'The Sims 4')
ROOT = _os.path.join(SIMS, 'Mods')
HERE = os.path.dirname(os.path.abspath(__file__))
STBL = 0x220557DA
# Read from the install, not remembered: a hardcoded patch date is right on
# the day it is written and wrong every day after. None means 'game not
# found', and then pre_patch is reported as null rather than guessed.
PATCH_DATE = gate.patch_time()


def read_index(path):
    with open(path, 'rb') as f:
        hdr = f.read(96)
        if len(hdr) < 96 or hdr[:4] != b'DBPF':
            return
        cnt = struct.unpack_from('<I', hdr, 36)[0]
        isz = struct.unpack_from('<I', hdr, 44)[0]
        ipos = struct.unpack_from('<Q', hdr, 64)[0] or struct.unpack_from('<I', hdr, 40)[0]
        if not cnt or not ipos:
            return
        f.seek(ipos)
        idx = f.read(isz)
        if len(idx) < 4:
            return
        flags = struct.unpack_from('<I', idx, 0)[0]
        p = 4
        const = {}
        for bit, k in ((0, 't'), (1, 'g'), (2, 'h')):
            if flags & (1 << bit):
                const[k] = struct.unpack_from('<I', idx, p)[0]; p += 4
        for _ in range(cnt):
            try:
                t = const.get('t')
                if t is None:
                    t = struct.unpack_from('<I', idx, p)[0]; p += 4
                g = const.get('g')
                if g is None:
                    g = struct.unpack_from('<I', idx, p)[0]; p += 4
                h = const.get('h')
                if h is None:
                    h = struct.unpack_from('<I', idx, p)[0]; p += 4
                lo = struct.unpack_from('<I', idx, p)[0]; p += 4
                off = struct.unpack_from('<I', idx, p)[0]; p += 4
                fsz = struct.unpack_from('<I', idx, p)[0]; p += 4
                msz = struct.unpack_from('<I', idx, p)[0]; p += 4
                comp = 0
                if fsz & 0x80000000:
                    comp = struct.unpack_from('<H', idx, p)[0]; p += 4
                yield (t, g, (h << 32) | lo, off, fsz & 0x7FFFFFFF, msz, comp)
            except struct.error:
                return


hdr_re = re.compile(rb'<([IM])\s([^>]{0,900}?)>')
attr_re = re.compile(rb'(\w)="([^"]*)"')

# ---------------------------------------------------------------- collect
packages, scripts = [], []
for dp, _, fns in os.walk(ROOT):
    for fn in fns:
        p = os.path.join(dp, fn)
        rel = os.path.relpath(p, ROOT)
        low = fn.lower()
        if low.endswith('.package'):
            packages.append(rel)
        elif low.endswith('.ts4script'):
            scripts.append(rel)
packages.sort(); scripts.sort()
print(f"{len(packages)} packages, {len(scripts)} scripts", file=sys.stderr)

report = {'generated': datetime.datetime.now().isoformat(timespec='seconds'),
          'counts': {'packages': len(packages), 'scripts': len(scripts)}}

# ---------------------------------------------------------------- duplicates
by_size = collections.defaultdict(list)
for rel in packages:
    try:
        by_size[os.path.getsize(os.path.join(ROOT, rel))].append(rel)
    except OSError:
        pass


def filehash(rel):
    h = hashlib.sha1()
    with open(os.path.join(ROOT, rel), 'rb') as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


dupes = []
for size, group in by_size.items():
    if len(group) < 2:
        continue
    byhash = collections.defaultdict(list)
    for rel in group:
        try:
            byhash[filehash(rel)].append(rel)
        except OSError:
            pass
    for hsh, files in byhash.items():
        if len(files) > 1:
            dupes.append({'sha1': hsh, 'size': size, 'files': sorted(files)})
dupes.sort(key=lambda d: -d['size'])
report['identical_duplicates'] = dupes
wasted = sum(d['size'] * (len(d['files']) - 1) for d in dupes)
report['duplicate_bytes_wasted'] = wasted
print(f"identical duplicate sets: {len(dupes)}  wasted {wasted/1048576:.1f} MB", file=sys.stderr)

# ---------------------------------------------------------------- index + tuning
tgi_owners = collections.defaultdict(list)
tuning = []          # dicts
for n, rel in enumerate(packages):
    p = os.path.join(ROOT, rel)
    try:
        ents = list(read_index(p))
    except Exception:
        continue
    try:
        fh = open(p, 'rb')
    except OSError:
        continue
    with fh:
        for (t, g, inst, off, fsz, msz, comp) in ents:
            tgi_owners[(t, g, inst)].append(rel)
            if t == STBL or msz > 2_000_000 or fsz < 8:
                continue
            try:
                fh.seek(off)
                raw = fh.read(min(fsz, 8192))
                data = zlib.decompressobj().decompress(raw, 3000) if comp == 0x5A42 else (raw if comp == 0 else None)
            except Exception:
                continue
            if not data:
                continue
            if data[:3] == b'\xef\xbb\xbf':
                data = data[3:]
            if not data.lstrip().startswith(b'<'):
                continue
            m = hdr_re.search(data)
            if not m:
                continue
            a = dict((k.decode(), v.decode('utf-8', 'replace')) for k, v in attr_re.findall(m.group(2)))
            if not a.get('n'):
                continue
            tuning.append({'pkg': rel, 'name': a['n'], 'i': a.get('i', ''),
                           'c': a.get('c', ''), 'inst': inst, 'type': t})
    if n % 200 == 0:
        print(f"  indexed {n}/{len(packages)}", file=sys.stderr)

report['counts']['tuning_resources'] = len(tuning)

# ---------------------------------------------------------------- EA overrides
ea_over = [r for r in tuning if r['inst'] < 2**32 and ':' not in r['name']]
by_inst = collections.defaultdict(list)
for r in ea_over:
    by_inst[r['inst']].append(r)

conflicts = []
for inst, rs in by_inst.items():
    pkgs = sorted({r['pkg'] for r in rs})
    if len(pkgs) > 1:
        conflicts.append({'instance': inst, 'kind': rs[0]['i'],
                          'names': sorted({r['name'] for r in rs}), 'packages': pkgs})
conflicts.sort(key=lambda c: -len(c['packages']))
report['ea_override_conflicts'] = conflicts

ovr_by_pkg = collections.defaultdict(list)
for r in ea_over:
    ovr_by_pkg[r['pkg']].append(r)
stale = []
for pkg, rs in ovr_by_pkg.items():
    try:
        mt = os.path.getmtime(os.path.join(ROOT, pkg))
    except OSError:
        continue
    stale.append({'pkg': pkg, 'overrides': len(rs),
                  'date': datetime.datetime.fromtimestamp(mt).strftime('%Y-%m-%d'),
                  'pre_patch': (mt < PATCH_DATE) if PATCH_DATE else None,
                  'kinds': dict(collections.Counter(r['i'] for r in rs).most_common(6))})
stale.sort(key=lambda s: s['date'])
report['ea_overriding_packages'] = stale

# ---------------------------------------------------------------- non-tuning TGI collisions
res_conf = []
for tgi, owners in tgi_owners.items():
    o = sorted(set(owners))
    if len(o) > 1:
        res_conf.append({'type': f"0x{tgi[0]:08X}", 'group': f"0x{tgi[1]:08X}",
                         'instance': f"0x{tgi[2]:016X}", 'packages': o})
bytype = collections.Counter(c['type'] for c in res_conf)
report['resource_collisions_by_type'] = dict(bytype.most_common())
report['resource_collisions'] = res_conf[:400]
report['counts']['resource_collisions_total'] = len(res_conf)

# ---------------------------------------------------------------- scripts
MAG = {3394: 'py3.7 (correct)', 3413: 'py3.8', 3425: 'py3.9', 3439: 'py3.10', 3495: 'py3.11'}
INJECT_MARKERS = [b'load_data_into_class_instances', b'_zone_load', b'add_superaffordances']
sinfo = []
for rel in scripts:
    p = os.path.join(ROOT, rel)
    d = {'script': rel, 'depth': rel.count(os.sep),
         'date': datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d'),
         'size': os.path.getsize(p)}
    if not zipfile.is_zipfile(p):
        d['fatal'] = 'not a zip archive - cannot load'
        sinfo.append(d); continue
    mags, names, blob = set(), [], b''
    try:
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            for nm in names:
                if nm.endswith('.pyc'):
                    b = z.read(nm)
                    blob += b
                    if len(b) >= 2:
                        mags.add(struct.unpack('<H', b[:2])[0])
                elif nm.endswith('.py'):
                    blob += z.read(nm)
    except Exception as e:
        d['fatal'] = f'unreadable: {e}'
        sinfo.append(d); continue
    d['pyc'] = sorted(MAG.get(m, str(m)) for m in mags)
    d['has_py_fallback'] = any(nm.endswith('.py') for nm in names)
    d['injects'] = [m.decode() for m in INJECT_MARKERS if m in blob]
    sinfo.append(d)
report['scripts'] = sinfo

json.dump(report, open(os.path.join(gate.out_dir(), 'report.json'), 'w',
                       encoding='utf-8'), indent=1)
print("\n=== wrote report.json ===")
print(f"identical duplicate sets : {len(dupes)}  ({wasted/1048576:.1f} MB wasted)")
print(f"EA-override conflicts    : {len(conflicts)}")
print(f"resource collisions      : {len(res_conf)}")
print(f"packages overriding EA   : {len(stale)}")
print(f"scripts                  : {len(sinfo)}")
