import sys,pickle,collections,bisect
sys.path.insert(0,'tools')
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
F=pickle.load(open('scratch/gx/flow3.pkl','rb'));memops=F['memops']
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')));fstarts=[f[0] for f in funcs]
sdk={}
for ln in open(SCR+r'\skies_sdk_symbols.txt'):
    if ln.startswith('0x'):
        p=ln.split(); sdk[int(p[0],16)]=p[2]
def fn(a):
    i=bisect.bisect_right(fstarts,a)-1
    f=funcs[i]; ok=f[0]<=a<f[0]+f[1]
    return (f[0],f[1],sdk.get(f[0],f[2]),ok)
SDKLO,SDKHI=0x802319E0,0x80266770
gp=[x for x in memops if x[2]==0xCC008000]
byf=collections.defaultdict(list)
for a,m,ea,ra in gp: byf[fn(a)[0]].append((a,m))
rows=[]
for fa,l in byf.items():
    _,sz,nm,_=fn(l[0][0]); rows.append((fa,sz,nm,len(l),SDKLO<=fa<SDKHI,collections.Counter(m for _,m in l)))
ins=[r for r in rows if r[4]];out=[r for r in rows if not r[4]]
print("distinct functions with gather-pipe stores:",len(rows))
print(f"  SDK block  : {len(ins):3d} funcs {sum(r[3] for r in ins):5d} stores")
print(f"  outside    : {len(out):3d} funcs {sum(r[3] for r in out):5d} stores")
print("\n### OUTSIDE-SDK functions with gather-pipe stores (sorted by addr)")
for r in sorted(out):
    print(f"0x{r[0]:08X} size={r[1]:6d} n={r[3]:4d} {dict(r[5])} {r[2]}")
print("\n### SDK-block functions, top 25 by store count")
for r in sorted(ins,key=lambda x:-x[3])[:25]:
    print(f"0x{r[0]:08X} size={r[1]:6d} n={r[3]:4d} {dict(r[5])} {r[2]}")
# address span histogram of outside sites
ao=sorted(a for a,_,_,_ in gp if not(SDKLO<=a<SDKHI))
print("\noutside-SDK store address span: 0x%08X .. 0x%08X  (%d stores)"%(ao[0],ao[-1],len(ao)))
# cluster them
cl=[];cur=[ao[0]]
for a in ao[1:]:
    if a-cur[-1]>0x2000: cl.append(cur);cur=[a]
    else: cur.append(a)
cl.append(cur)
print("clusters (gap>8KB):")
for c in cl: print("   0x%08X-0x%08X  %d stores"%(c[0],c[-1],len(c)))
pickle.dump(rows,open('scratch/gx/gprows2.pkl','wb'))
