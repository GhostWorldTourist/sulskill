"""General premade-household extractor for The Sims 4."""
import sys, struct, os, pickle, collections
sys.path.insert(0,'.')
from idx import index
from s4io import get
from s4types import T
from pb import parse, uv
ROOT = r'C:\Games\The Sims 4'
u32=lambda b,o: struct.unpack_from('<I',b,o)[0]
u64=lambda b,o: struct.unpack_from('<Q',b,o)[0]
# HHDESC field offsets: lot u64 @ base, name u32 @ base+8, bio u32 @ base+12, hhbin u64 @ base+16
HDBASE = {7:0x46, 10:0x52, 11:0x6A, 14:0x6A, 18:0x6A}
AGE={1:'Baby',2:'Toddler',4:'Child',8:'Teen',16:'YoungAdult',32:'Adult',64:'Elder'}
GEN={4096:'Male',8192:'Female'}
S=pickle.load(open('stbl_all.pkl','rb'))
TR=pickle.load(open('traits_all.pkl','rb'))
def build():
    HD={};HB={};LOT={};WORLD={};REGION={}
    want={T['HOUSEHOLD_DESCRIPTION']:HD,T['HOUSEHOLD_BINARY']:HB,T['LOT_DESCRIPTION']:LOT,
          T['WORLD_DESCRIPTION']:WORLD,T['REGION_DESCRIPTION']:REGION}
    for dp,dn,fn in os.walk(ROOT):
        for f in sorted(fn):
            if not f.endswith('.package'): continue
            p=os.path.join(dp,f)
            try: ents=index(p) or []
            except Exception: continue
            for t,g,i,off,fsz,msz,comp in ents:
                if t in want:
                    try: b=get(p,off,fsz,comp)
                    except Exception: continue
                    if len(b)>=8: want[t][i]=b   # later (Delta) wins
    return HD,HB,LOT,WORLD,REGION
def pk(v):
    o=[];p=0
    while p<len(v): x,p=uv(v,p);o.append(x)
    return o
def sims_of(hb):
    off = 8 if u32(hb,0) < 2 else 16
    top = parse(hb[off:off+u32(hb,off-4)])
    hhm = [v for f,wt,v in top if f==1][0]
    d=collections.defaultdict(list)
    for f,wt,v in parse(hhm): d[f].append(v)
    out=[]
    for s in d[6]:
        sd=collections.defaultdict(list)
        for f,wt,v in parse(s): sd[f].append(v)
        traits=[]
        if 30 in sd:
            f30=collections.defaultdict(list)
            for f,wt,v in parse(sd[30][0]): f30[f].append(v)
            if 10 in f30:
                for f,wt,v in parse(f30[10][0]):
                    if f==1: traits=pk(v)
        out.append(dict(first=sd[5][0].decode('utf-8','replace'), last=sd[6][0].decode('utf-8','replace'),
            gender=GEN.get(sd[7][0],sd[7][0]) if 7 in sd else None,
            age=AGE.get(sd[8][0],sd[8][0]) if 8 in sd else None,
            sim_id=struct.unpack('<Q',sd[1][0])[0] if 1 in sd else 0,
            first_key=sd[55][0] if 55 in sd else 0, last_key=sd[56][0] if 56 in sd else 0,
            traits=[(t,TR.get(t)) for t in traits]))
    return dict(name=d[3][0].decode('utf-8','replace') if 3 in d else '',
                funds=d[4][0] if 4 in d else 0,
                household_id=d[2][0] if 2 in d else 0, sims=out)
def household(inst, HD,HB,LOT,WORLD,REGION):
    b=HD[inst]; ver=u32(b,0); o=HDBASE[ver]
    r=dict(inst=inst, version=ver, guid=u64(b,4), lot=u64(b,o),
           name_key=u32(b,o+8), bio_key=u32(b,o+12), hhbin=u64(b,o+16))
    r['name']=S.get(r['name_key']); r['bio']=S.get(r['bio_key'])
    if r['lot'] in LOT:
        w=u64(LOT[r['lot']],4); r['world']=w
        if w in WORLD:
            wb=WORLD[w]; r['world_name']=S.get(u32(wb,4)); r['world_desc']=S.get(u32(wb,8))
            ln=u32(wb,0x18); r['world_internal']=wb[0x1C:0x1C+ln].decode('ascii','replace')
            reg=u64(wb,0x10); r['region']=reg
            if reg in REGION: r['region_name']=S.get(u32(REGION[reg],4))
    if r['hhbin'] in HB: r.update(sims_of(HB[r['hhbin']]))
    return r
if __name__=='__main__':
    HD,HB,LOT,WORLD,REGION = build()
    pickle.dump((HD,HB,LOT,WORLD,REGION), open('game.pkl','wb'))
    print('HD %d HB %d LOT %d WORLD %d REGION %d'%(len(HD),len(HB),len(LOT),len(WORLD),len(REGION)))
    hits=[]
    for i in HD:
        try: r=household(i,HD,HB,LOT,WORLD,REGION)
        except Exception as e: continue
        if r.get('name') and r.get('sims'): hits.append(r)
    print('extractable households:',len(hits))
    for r in sorted(hits, key=lambda r:(r.get('region_name') or '', r['name'])):
        if r['name'] in ('Goth','Straud','Caliente','Landgraab','Pancakes','Spencer-Kim-Lewis','Vatore','Munch'):
            print()
            print('%s  [0x%X v%d] world=%s / region=%s  funds=%s'%(r['name'],r['inst'],r['version'],
                r.get('world_name'), r.get('region_name'), r.get('funds')))
            print('   bio key 0x%08X: %s'%(r['bio_key'], (r['bio'] or '')[:110]))
            for s in r['sims']:
                print('   %-12s %-14s %-11s %-7s %s'%(s['first'],s['last'],s['age'],s['gender'],
                    ', '.join(n or ('#%d'%t) for t,n in s['traits'])))
