import sys,pickle,struct,collections,bisect
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode
exec(open('scratch/gx/tables.py').read())
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d=D.parse(open('extracted/sys/main.dol','rb').read())
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')));fstarts=[f[0] for f in funcs]
sdk={}
for ln in open(SCR+r'\skies_sdk_symbols.txt'):
    if ln.startswith('0x'): p=ln.split(); sdk[int(p[0],16)]=p[2]
def f0(a):
    i=bisect.bisect_right(fstarts,a)-1
    if i<0: return None
    f=funcs[i];return f[0] if f[0]<=a<f[0]+f[1] else None
def nm(a): return sdk.get(a,'fn_%08X'%a) if a else '?'
calls=collections.defaultdict(collections.Counter)   # caller -> callee counts
for s in d.sections:
    if not s.is_text: continue
    b=d.data[s.file_offset:s.file_offset+s.size]
    for i in range(0,s.size,4):
        a=s.address+i;ins=decode(struct.unpack_from('>I',b,i)[0],a)
        if ins.valid and ins.mnemonic in ('b','bc') and ins.lk_bit and ins.target:
            c=f0(a);t=f0(ins.target) or ins.target
            if c: calls[c][t]+=1
callers=collections.defaultdict(collections.Counter)
for c,tg in calls.items():
    for t,n in tg.items(): callers[t][c]+=n
pickle.dump((dict(calls),dict(callers)),open('scratch/gx/cg.pkl','wb'))
GPF=set(r[0] for r in pickle.load(open('scratch/gx/gprows2.pkl','rb')))
CL=[f[0] for f in funcs if 0x80289B70<=f[0]<0x80291800]
print("functions in 0x80289B70-0x802917FF:",len(CL))
SDKLO,SDKHI=0x802319E0,0x80266778
# what does the cluster call?
out=collections.Counter()
for c in CL:
    for t,n in calls.get(c,{}).items(): out[t]+=n
print("\ncluster outbound call targets (top 30):")
for t,n in out.most_common(30):
    z='SDK' if SDKLO<=t<SDKHI else ('CLUSTER' if 0x80289B70<=t<0x80291800 else 'other')
    print("   x%-4d %-8s 0x%08X %s"%(n,z,t,nm(t)))
print("\ncluster inbound callers (by zone):")
inb=collections.Counter()
for c in CL:
    for cc,n in callers.get(c,{}).items(): inb[cc]+=n
z=collections.Counter()
for cc,n in inb.items():
    z['SDK' if SDKLO<=cc<SDKHI else ('CLUSTER' if 0x80289B70<=cc<0x80291800 else 'game')]+=n
print("  ",dict(z),"distinct callers:",len(inb))
print("  top external callers:")
for cc,n in inb.most_common(15):
    if not (0x80289B70<=cc<0x80291800): print("     x%-3d 0x%08X %s"%(n,cc,nm(cc)))
