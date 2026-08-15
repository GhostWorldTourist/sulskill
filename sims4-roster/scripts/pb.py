import struct
def uv(b,p):
    r=s=0
    while True:
        x=b[p]; p+=1; r |= (x&0x7f)<<s; s+=7
        if not x&0x80: return r,p
def parse(b, p=0, end=None):
    if end is None: end=len(b)
    out=[]
    while p<end:
        try:
            k,p = uv(b,p)
        except IndexError: break
        f, wt = k>>3, k&7
        if f==0: raise ValueError('field 0')
        if wt==0: v,p = uv(b,p)
        elif wt==1: v=b[p:p+8]; p+=8
        elif wt==2:
            ln,p = uv(b,p)
            if p+ln>end: raise ValueError('len overrun')
            v=b[p:p+ln]; p+=ln
        elif wt==5: v=b[p:p+4]; p+=4
        else: raise ValueError('wt %d'%wt)
        out.append((f,wt,v))
    return out
def is_pb(b):
    try:
        r=parse(b)
        return bool(r)
    except Exception:
        return False
def show(b, depth=0, maxdepth=6, prefix=''):
    try: fields=parse(b)
    except Exception as e:
        return
    for f,wt,v in fields:
        ind='  '*depth
        if wt==2:
            sub = parse(v) if len(v)>0 else None
            ok=False
            if depth<maxdepth and len(v)>1:
                try:
                    s=parse(v)
                    ok = bool(s)
                except Exception: ok=False
            txt=None
            try:
                t=v.decode('utf-8')
                if t.isprintable() and len(t)>0: txt=t
            except Exception: pass
            if txt and (not ok or len(v)<40):
                print(f'{ind}{prefix}{f} [str{len(v)}] {txt!r}')
            elif ok:
                print(f'{ind}{prefix}{f} [msg{len(v)}]')
                show(v, depth+1, maxdepth)
            else:
                print(f'{ind}{prefix}{f} [bytes{len(v)}] {v[:32].hex()}')
        elif wt==0:
            print(f'{ind}{prefix}{f} varint {v} (0x{v:X})')
        elif wt==5:
            print(f'{ind}{prefix}{f} f32 {struct.unpack("<I",v)[0]} / {struct.unpack("<f",v)[0]:.4g}')
        else:
            print(f'{ind}{prefix}{f} f64 {struct.unpack("<Q",v)[0]}')
