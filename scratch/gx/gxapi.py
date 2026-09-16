import sys,pickle,collections,bisect
sys.path.insert(0,'tools')
SCR=r'C:\Users\bmfre\AppData\Local\Temp\claude\C--Users-bmfre\ea97428e-9906-4826-98b8-90b86878c881\scratchpad'
calls,callers=pickle.load(open('scratch/gx/cg.pkl','rb'))
funcs=sorted(pickle.load(open(SCR+r'\skies_funcs.pkl','rb')))
fmap={f[0]:f for f in funcs}
sdk={}
for ln in open(SCR+r'\skies_sdk_symbols.txt'):
    if ln.startswith('0x'): p=ln.split(); sdk[int(p[0],16)]=p[2]
def nm(a): return sdk.get(a,'fn_%08X'%a)
SDKLO,SDKHI=0x802319E0,0x80266778
GXLO,GXHI=0x8024B2B0,0x80252B00   # GX module span (GXInit .. end of GX code)
rows=pickle.load(open('scratch/gx/gprows2.pkl','rb'))
gp={r[0]:r for r in rows}
print("### GX-module functions (0x%08X-0x%08X): call-site census"%(GXLO,GXHI))
gxf=[f for f in funcs if GXLO<=f[0]<GXHI]
print("functions in GX module:",len(gxf))
tot_sites=0;tot_from_game=0
tbl=[]
for f in gxf:
    cs=callers.get(f[0],{})
    ngame=sum(n for c,n in cs.items() if not (SDKLO<=c<SDKHI))
    nsdk=sum(n for c,n in cs.items() if SDKLO<=c<SDKHI)
    tot_sites+=ngame+nsdk;tot_from_game+=ngame
    g=gp.get(f[0])
    tbl.append((ngame,nsdk,f[0],f[1],nm(f[0]),g[3] if g else 0,dict(g[5]) if g else {}))
tbl.sort(key=lambda r:-r[0])
print("total call sites into GX module: %d  (from non-SDK code: %d)"%(tot_sites,tot_from_game))
print("\n--- GX functions called from GAME code, ranked (ngame nsdk addr size gpstores mix name)")
for r in tbl:
    if r[0]==0: continue
    print("  %5d %4d  0x%08X sz=%-5d gp=%-3d %-28s %s"%(r[0],r[1],r[2],r[3],r[5],str(r[6]),r[4]))
ncalled=[r for r in tbl if r[0]==0 and r[1]==0]
print("\nGX functions never called at all: %d"%len(ncalled))
print("GX functions called only from SDK: %d"%len([r for r in tbl if r[0]==0 and r[1]>0]))
