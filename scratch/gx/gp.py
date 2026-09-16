import sys,pickle,struct,collections,bisect
sys.path.insert(0,'tools')
from soa import dol as D
from soa.ppc import decode
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
d=D.parse(open('extracted/sys/main.dol','rb').read())
M=pickle.load(open('scratch/gx/m2.pkl','rb')); memops=M['memops']
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')))
fstarts=[f[0] for f in funcs]
sdk={}
for ln in open(SCR+r'\skies_sdk_symbols.txt'):
    if ln.startswith('0x'):
        p=ln.split(); sdk[int(p[0],16)]=p[2]
def fn(a):
    i=bisect.bisect_right(fstarts,a)-1
    if i<0: return (None,None,None)
    f=funcs[i]
    if f[0]<=a<f[0]+f[1]: return (f[0],f[1],sdk.get(f[0],f[2]))
    return (f[0],f[1],'AFTER:'+sdk.get(f[0],f[2]))
SDKLO,SDKHI=0x802319E0,0x80266770
GP=0xCC008000
gp=[x for x in memops if 0xCC008000<=x[2]<0xCC008020]
print("stores in 0xCC008000..1F:",len(gp),collections.Counter(x[2] for x in gp))
gp=[x for x in memops if x[2]==GP]
byfunc=collections.defaultdict(list)
for a,m,ea,ra in gp: byfunc[fn(a)[0]].append((a,m))
print("\ndistinct functions containing gather-pipe stores:",len(byfunc))
rows=[]
for fa,lst in byfunc.items():
    f0,sz,nm=fn(lst[0][0])
    rows.append((fa,sz,nm,len(lst),SDKLO<=fa<SDKHI,collections.Counter(m for _,m in lst)))
rows.sort(key=lambda r:-r[3])
insdk=[r for r in rows if r[4]]; out=[r for r in rows if not r[4]]
print(f"  in SDK block: {len(insdk)} funcs / {sum(r[3] for r in insdk)} stores")
print(f"  outside SDK : {len(out)} funcs / {sum(r[3] for r in out)} stores")
print("\n--- ALL functions with gather-pipe stores (addr size name nstores inSDK mix) ---")
for r in sorted(rows):
    print(f"0x{r[0]:08X} {r[1]:6d} {'SDK' if r[4] else 'GAME'} n={r[3]:3d} {dict(r[5])} {r[2]}")
pickle.dump(rows,open('scratch/gx/gprows.pkl','wb'))
